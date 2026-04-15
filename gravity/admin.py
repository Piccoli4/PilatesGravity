from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import AjusteDeudaEspecial


@admin.register(AjusteDeudaEspecial)
class AjusteDeudaEspecialAdmin(ModelAdmin):
    list_display = ['fecha_ajuste', 'usuario_cliente', 'deuda', 'monto_original_anterior', 'monto_ajustado', 'admin_que_ajusto']
    list_filter = ['fecha_ajuste']
    search_fields = ['usuario_cliente__first_name', 'usuario_cliente__last_name', 'motivo']
    readonly_fields = ['deuda', 'usuario_cliente', 'admin_que_ajusto', 'monto_original_anterior', 'monto_ajustado', 'motivo', 'fecha_ajuste']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False