"""
Eliminación de la cuenta de un alumno.

No se borra el usuario: se anonimiza. Se eliminan los datos personales y la cuenta
queda inutilizable, pero los pagos, deudas e historial siguen existiendo a nombre de
"Alumno eliminado (Nombre Apellido)" para que los reportes de ingresos no cambien
(la Política de Privacidad permite conservar lo que haya obligación de conservar).
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


def motivo_bloqueo(usuario):
    """Texto que explica por qué no puede eliminar la cuenta, o None si puede."""
    from gravity.models import DeudaMensual

    if usuario.is_staff or usuario.is_superuser:
        return ('staff', None)
    pendiente = (
        DeudaMensual.objects.filter(usuario=usuario, estado__in=('pendiente', 'vencido', 'parcial'),
                                    monto_pendiente__gt=0)
        .order_by('mes_año')
    )
    total = sum((d.monto_pendiente for d in pendiente), Decimal('0'))
    if total > 0:
        return ('deuda', total)
    return None


@transaction.atomic
def anonimizar_cuenta(usuario):
    """Cancela reservas y planes, borra los datos personales y desactiva la cuenta."""
    from gravity.actividad import dar_de_baja_reservas
    from gravity.models import EstadoPagoCliente, PlanUsuario, SolicitudCambioPlan

    ahora = timezone.localtime(timezone.now())
    nombre = usuario.get_full_name().strip() or usuario.username

    # Reservas y planes
    dar_de_baja_reservas(usuario.reservas_pilates.all())
    PlanUsuario.objects.filter(usuario=usuario, activo=True).update(activo=False, reservas_canceladas=True)
    SolicitudCambioPlan.objects.filter(usuario=usuario, estado='pendiente').update(
        estado='rechazada', fecha_resolucion=ahora,
        observaciones='Rechazada automáticamente: el alumno eliminó su cuenta.',
    )
    EstadoPagoCliente.objects.filter(usuario=usuario).update(activo=False, plan_actual=None)

    # Comentario público
    try:
        usuario.testimonio.delete()
    except Exception:
        pass

    # Datos personales del perfil
    try:
        perfil = usuario.profile
    except Exception:
        perfil = None
    if perfil:
        if perfil.avatar:
            perfil.avatar.delete(save=False)
        # Se modifica el objeto en memoria (no con .update()): al guardar el usuario,
        # una señal vuelve a guardar este mismo perfil.
        perfil.avatar = None
        perfil.telefono = None
        perfil.fecha_nacimiento = None
        perfil.tiene_lesiones = False
        perfil.descripcion_lesiones = ''
        perfil.acepta_marketing = False
        perfil.acepta_recordatorios = False
        perfil.notificar_clases_sede_principal = False
        perfil.notificar_clases_sede_2 = False
        perfil.save()

    # Usuario: sin datos de contacto, sin acceso, con un nombre que se reconoce en los reportes
    usuario.first_name = f'Alumno eliminado ({nombre})'[:150]
    usuario.last_name = ''
    usuario.email = ''
    usuario.username = f'eliminado-{usuario.pk}'
    usuario.is_active = False
    usuario.set_unusable_password()
    usuario.save()
