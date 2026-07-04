"""
Mirror CAS group attributes onto WDG group membership.

Each CAS group name is mapped to a WDG :class:`~core.models.Group` — either one
that declares the name in ``cas_names``, or one whose ``name`` matches exactly,
or a freshly auto-created group (so unknown CAS groups still surface and can be
wired to gateways/networks later in the admin).
"""

from django.contrib.auth.models import User

from .models import Group


def resolve_group(cas_name: str) -> Group:
    group = (
        Group.objects.filter(cas_names__contains=[cas_name]).first()
        or Group.objects.filter(name=cas_name).first()
    )
    if group is None:
        group = Group.objects.create(name=cas_name, cas_names=[cas_name])
    return group


def sync_membership(
    user: User, cas_group_names: list[str], replace_when_empty: bool = False
) -> list[Group]:
    """
    Mirror the CAS-derived group names onto the user's WDG membership.

    When CAS releases group names, they are authoritative: membership is set to
    exactly those groups. When CAS releases *nothing* (empty list) the existing
    membership is left untouched by default — this preserves manual admin
    assignments for deployments where the IdP hasn't (yet) released group
    attributes. Pass ``replace_when_empty=True`` to make CAS strictly
    authoritative (empty means "no groups").
    """
    if not cas_group_names and not replace_when_empty:
        return list(user.wdg_groups.all())

    groups = [resolve_group(name) for name in cas_group_names]
    user.wdg_groups.set(groups)
    return groups
