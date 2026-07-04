from django.contrib import admin

from .models import Device, Gateway, Group, Network


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = ("name", "endpoint", "tunnel_subnet", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "endpoint")


@admin.register(Network)
class NetworkAdmin(admin.ModelAdmin):
    list_display = ("name", "cidr", "description")
    search_fields = ("name", "cidr")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name", "cas_names")
    filter_horizontal = ("gateways", "networks", "members")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "gateway", "address", "is_active", "created_at")
    list_filter = ("gateway", "is_active")
    search_fields = ("user__username", "public_key", "address")
