import ipaddress
import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from casauth.bearer import require_bearer
from core import resolve
from core.models import Device, Gateway

from . import service, wgconf

GATEWAY_LISTEN_PORT = 51820


@csrf_exempt
@require_bearer
@require_http_methods(["POST"])
def register_peer(request):
    """Register the client's public key on every gateway the user may use."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid JSON"}, status=400)

    public_key = (body.get("public_key") or "").strip()
    if not public_key:
        return JsonResponse({"detail": "public_key required"}, status=400)

    try:
        devices = service.register_devices(request.wdg_user, public_key)
    except service.PublicKeyConflict:
        return JsonResponse(
            {"detail": "public key already registered by another user"}, status=409
        )
    if not devices:
        return JsonResponse({"detail": "no VPN access for this user"}, status=403)

    return JsonResponse(
        {"devices": [{"gateway": d.gateway.name, "address": d.address} for d in devices]},
        status=200,
    )


@require_bearer
@require_http_methods(["GET"])
def list_configs(request):
    """Enumerate the gateways available to the user (for multi-tunnel clients)."""
    user = request.wdg_user
    gateways = resolve.gateways_for_user(user)
    return JsonResponse(
        {
            "gateways": [
                {
                    "name": g.name,
                    "endpoint": g.endpoint,
                    "networks": [n.cidr for n in resolve.networks_via_gateway(user, g)],
                }
                for g in gateways
            ]
        }
    )


@require_bearer
@require_http_methods(["GET"])
def get_plan(request):
    """
    The user's multi-tunnel plan (docs/DESIGN-MULTITUNNEL.md): ordered tunnels
    (default-route last), each with disjoint AllowedIPs and its instances in
    failover order (the user's site first). Per-instance credentials (address,
    PSK) are null until the device is registered on that gateway.
    """
    user = request.wdg_user
    tunnels = resolve.plan_for_user(user)
    if not tunnels:
        return JsonResponse({"detail": "no VPN access for this user"}, status=403)

    gateway_ids = [g.pk for t in tunnels for g in t.instances]
    devices = {
        d.gateway_id: d
        for d in Device.objects.filter(user=user, is_active=True, gateway_id__in=gateway_ids)
    }
    site = resolve.user_site(user)
    return JsonResponse(
        {
            "site": site.name if site else None,
            "tunnels": [
                {
                    "service": t.service.name,
                    "default_route": t.service.default_route,
                    "allowed_ips": t.allowed_ips,
                    "instances": [
                        {
                            "gateway": g.name,
                            "site": g.site.name if g.site else None,
                            "endpoint": g.endpoint,
                            "public_key": g.public_key,
                            "address": devices[g.pk].address if g.pk in devices else None,
                            "preshared_key": devices[g.pk].preshared_key if g.pk in devices else None,
                        }
                        for g in t.instances
                    ],
                }
                for t in tunnels
            ],
        }
    )


@require_bearer
@require_http_methods(["GET"])
def get_config(request):
    """
    Return the WireGuard .conf for one gateway (``?gateway=NAME``; defaults to
    the primary gateway). AllowedIPs are scoped to what that gateway routes.
    """
    user = request.wdg_user
    gateways = resolve.gateways_for_user(user)
    if not gateways:
        return JsonResponse({"detail": "no VPN access for this user"}, status=403)

    requested = request.GET.get("gateway")
    if requested:
        gateway = next((g for g in gateways if g.name == requested), None)
        if gateway is None:
            return JsonResponse({"detail": "gateway not available to user"}, status=404)
    else:
        gateway = gateways[0]

    device = Device.objects.filter(user=user, gateway=gateway, is_active=True).first()
    if device is None:
        return JsonResponse({"detail": "register a peer first"}, status=409)

    conf = wgconf.build_config(device, gateway, resolve.allowed_ips_for_user(user, gateway))
    return HttpResponse(conf, content_type="text/plain; charset=utf-8")


def _gateway_from_token(request) -> Gateway | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer ") :]
    if not token:
        return None
    return Gateway.objects.filter(sync_token=token, is_active=True).first()


def _gateway_address(gateway: Gateway) -> str:
    """The gateway's own tunnel IP: first host of its subnet."""
    return str(next(ipaddress.ip_network(gateway.tunnel_subnet, strict=False).hosts()))


@csrf_exempt
@require_http_methods(["POST"])
def gateway_sync(request):
    """
    Gateway agent endpoint: the agent presents its sync token, self-reports its
    current WireGuard public key, and receives everything it must program —
    its client peers, its inter-gateway relay peers (forward + return paths),
    the per-client egress permissions it enforces at this hop (local and
    relayed clients alike), and the client subnets to MASQUERADE on its legs.
    Devices of deactivated users/accounts are excluded, which is how
    revocation propagates.
    """
    gateway = _gateway_from_token(request)
    if gateway is None:
        return JsonResponse({"detail": "unknown gateway token"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid JSON"}, status=400)

    public_key = (body.get("public_key") or "").strip()
    if public_key and public_key != gateway.public_key:
        gateway.public_key = public_key
        gateway.save(update_fields=["public_key"])

    devices = Device.objects.filter(
        gateway=gateway, is_active=True, user__is_active=True
    )
    peers = [
        {
            "public_key": d.public_key,
            "preshared_key": d.preshared_key,
            "address": d.address,
            "allowed_ips": [f"{d.address}/32"],
        }
        for d in devices
    ]
    return JsonResponse(
        {
            "gateway": gateway.name,
            "address": _gateway_address(gateway),
            "tunnel_subnet": gateway.tunnel_subnet,
            "listen_port": GATEWAY_LISTEN_PORT,
            "peers": peers,
            "relay_peers": resolve.relay_peers_for_gateway(gateway),
            "forward_rules": resolve.forward_rules_for_gateway(gateway),
            "masq_subnets": resolve.masq_subnets_for_gateway(gateway),
        }
    )
