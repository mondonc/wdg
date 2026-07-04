"""
Multi-tunnel model (docs/DESIGN-MULTITUNNEL.md, M8).

Schema: Site, Service, RelayLink, UserProfile; Gateway gains service/site and
a fleet-unique tunnel_subnet; Group grants services instead of gateways.

Data: every existing gateway becomes the single instance of a new Service
bearing its name, and group gateway-grants are converted to service-grants —
existing access is preserved verbatim.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def gateways_to_services(apps, schema_editor):
    Gateway = apps.get_model("core", "Gateway")
    Service = apps.get_model("core", "Service")
    Group = apps.get_model("core", "Group")

    for gateway in Gateway.objects.all():
        service, _ = Service.objects.get_or_create(
            name=gateway.name,
            defaults={"accepts_clients": True, "default_route": False},
        )
        gateway.service = service
        gateway.save(update_fields=["service"])

    for group in Group.objects.all():
        services = [g.service for g in group.gateways.all() if g.service]
        group.services.set(services)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0003_gateway_networks_alter_device_public_key_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Site",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("cas_values", models.JSONField(blank=True, default=list)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("accepts_clients", models.BooleanField(default=True)),
                ("default_route", models.BooleanField(default=False)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="gateway",
            name="service",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="instances",
                to="core.service",
            ),
        ),
        migrations.AddField(
            model_name="gateway",
            name="site",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="gateways",
                to="core.site",
            ),
        ),
        migrations.AlterField(
            model_name="gateway",
            name="tunnel_subnet",
            field=models.CharField(max_length=64, unique=True),
        ),
        migrations.CreateModel(
            name="RelayLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "from_gateway",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="relays_out",
                        to="core.gateway",
                    ),
                ),
                (
                    "to_gateway",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="relays_in",
                        to="core.gateway",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="relaylink",
            constraint=models.UniqueConstraint(
                fields=("from_gateway", "to_gateway"), name="unique_relay_link"
            ),
        ),
        migrations.AddConstraint(
            model_name="relaylink",
            constraint=models.CheckConstraint(
                condition=models.Q(("from_gateway", models.F("to_gateway")), _negated=True),
                name="relay_link_not_self",
            ),
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="users",
                        to="core.site",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wdg_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="group",
            name="services",
            field=models.ManyToManyField(blank=True, related_name="groups", to="core.service"),
        ),
        migrations.RunPython(gateways_to_services, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="group",
            name="gateways",
        ),
    ]
