from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import (User, Department, Patient, Bed, BedAllocation, Equipment,
                     EquipmentRequest, EquipmentAllocation, Medicine, StockTransaction,
                     Feedback, ActivityLog)

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username', 'email', 'role', 'is_approved', 'is_active', 'is_staff')
    list_filter = ('role', 'is_approved', 'is_active')
    fieldsets = DjangoUserAdmin.fieldsets + (("Hospital access", {'fields': ('role', 'phone', 'department', 'is_approved')}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("Hospital access", {'fields': ('role', 'phone', 'department', 'is_approved')}),)

for model in (Department, Patient, Bed, BedAllocation, Equipment, EquipmentRequest,
              EquipmentAllocation, Medicine, StockTransaction, Feedback, ActivityLog):
    admin.site.register(model)
