from unfold.admin import ModelAdmin
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Perfil del usuario"
    fields = (
        'telefono',
        'fecha_nacimiento',
        'sede_preferida',
        'nivel_experiencia',
        'acepta_recordatorios',
        'acepta_marketing',
        'tiene_lesiones',
        'descripcion_lesiones',
        'notas_admin',
        'puede_ver_pagos',
    )


class UserAdmin(BaseUserAdmin, ModelAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
