from django.contrib import admin

from .models import Device, Gateway, Group, Network, RelayLink, Service, Site, UserProfile


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "cas_values")
    search_fields = ("name", "cas_values")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "accepts_clients", "default_route", "description")
    list_filter = ("accepts_clients", "default_route")
    search_fields = ("name",)


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = ("name", "service", "site", "endpoint", "tunnel_subnet", "is_active")
    list_filter = ("service", "site", "is_active")
    search_fields = ("name", "endpoint")


@admin.register(RelayLink)
class RelayLinkAdmin(admin.ModelAdmin):
    list_display = ("from_gateway", "to_gateway")
    list_filter = ("from_gateway", "to_gateway")


@admin.register(Network)
class NetworkAdmin(admin.ModelAdmin):
    list_display = ("name", "cidr", "description")
    search_fields = ("name", "cidr")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name", "cas_names")
    filter_horizontal = ("services", "networks", "members")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "site")
    list_filter = ("site",)
    search_fields = ("user__username",)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "gateway", "address", "is_active", "created_at")
    list_filter = ("gateway", "is_active")
    search_fields = ("user__username", "public_key", "address")
