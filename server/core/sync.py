"""
Mirror CAS attributes onto WDG state: group membership and home site.

Each CAS group name is mapped to a WDG :class:`~core.models.Group` — either one
that declares the name in ``cas_names``, or one whose ``name`` matches exactly,
or a freshly auto-created group (so unknown CAS groups still surface and can be
wired to services/networks later in the admin).

Sites are different: they are infrastructure, so an unknown CAS site value is
**ignored**, never auto-created, and an empty release preserves the existing
(possibly admin-assigned) site.
"""

from django.contrib.auth.models import User

from .models import Group, Site, UserProfile


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


def resolve_site(cas_value: str) -> Site | None:
    return (
        Site.objects.filter(cas_values__contains=[cas_value]).first()
        or Site.objects.filter(name=cas_value).first()
    )


def sync_site(user: User, cas_site_values: list[str]) -> Site | None:
    """
    Mirror the CAS-derived site onto the user's profile (first matching value
    wins). Unmatched or missing values leave the current site untouched.
    """
    profile, _created = UserProfile.objects.get_or_create(user=user)
    for value in cas_site_values:
        site = resolve_site(value)
        if site is not None:
            if profile.site_id != site.pk:
                profile.site = site
                profile.save(update_fields=["site"])
            return site
    return profile.site
