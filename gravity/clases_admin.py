"""
Clases desde el panel: qué alumnos afecta un cambio y cómo se aplica.

- Cambiar el día, el horario o la sede mueve a todos los alumnos con horario fijo;
  se les puede avisar por email.
- Si cambia el día, los recuperos y clases únicas ya reservados quedan en una fecha
  que no es la de la clase: se cancelan (con registro y email) y se borran los avisos
  de ausencia de fechas futuras, que eran para el día viejo.
- Los turnos de profesora que salieron de la clase pasan al horario nuevo
  (gravity/horarios.py: mover_turnos_de_la_clase).
- Pausar (desactivar) una clase no toca las reservas: los alumnos conservan su lugar.
- Solo se elimina una clase que nunca tuvo reservas; si tuvo, se pausa (borrarla se
  llevaría en cascada toda su historia).
"""
import logging

from django.db import transaction
from django.utils import timezone

from .horarios import mover_turnos_de_la_clase
from .models import AusenciaTemporal, CancelacionAdmin, Reserva

logger = logging.getLogger(__name__)

CAMPOS_QUE_MUEVEN = ('dia', 'horario', 'direccion')
MOTIVO_CAMBIO = 'Cambio de horario de la clase'


def alumnos_afectados(clase, hoy=None):
    """Horarios fijos activos y recuperos/clases únicas desde hoy."""
    hoy = hoy or timezone.localdate()
    fijas = list(clase.reserva_set.filter(activa=True, fecha_unica__isnull=True).select_related('usuario'))
    sueltas = list(
        clase.reserva_set.filter(activa=True, fecha_unica__gte=hoy).select_related('usuario').order_by('fecha_unica')
    )
    return fijas, sueltas


def se_puede_eliminar(clase):
    """Solo si nunca tuvo reservas (ni activas ni pasadas)."""
    return not clase.reserva_set.exists()


def campos_cambiados(original, clase):
    return [c for c in CAMPOS_QUE_MUEVEN if getattr(original, c) != getattr(clase, c)]


def guardar_cambios(form, admin, avisar=True):
    """
    Guarda el formulario de edición de una clase y aplica las consecuencias de mover
    día/horario/sede. Devuelve un resumen para el mensaje de la pantalla.
    """
    # La instancia del formulario ya tiene los datos nuevos: la original se lee de la base
    original = type(form.instance).objects.get(pk=form.instance.pk)
    hoy = timezone.localdate()
    resumen = {'cambios': [], 'avisados': 0, 'sueltas_canceladas': 0, 'ausencias_borradas': 0, 'profesoras': []}

    with transaction.atomic():
        clase = form.save()
        cambios = campos_cambiados(original, clase)
        resumen['cambios'] = cambios
        if not cambios:
            return resumen

        resumen['profesoras'] = mover_turnos_de_la_clase(clase)
        fijas, sueltas = alumnos_afectados(clase, hoy)

        if 'dia' in cambios:
            for reserva in sueltas:
                reserva.activa = False
                reserva.save()
                CancelacionAdmin.objects.create(
                    reserva=reserva, admin_user=admin, motivo=MOTIVO_CAMBIO,
                    motivo_detalle=f'La clase pasó del {original.dia} al {clase.dia}.',
                    email_enviado=False,
                )
                if avisar and reserva.usuario.email:
                    transaction.on_commit(lambda r=reserva: _avisar_cancelacion(r, original, clase))
            resumen['sueltas_canceladas'] = len(sueltas)
            borradas, _ = AusenciaTemporal.objects.filter(
                reserva__in=fijas, fecha__gte=hoy
            ).delete()
            resumen['ausencias_borradas'] = borradas

        if avisar:
            # Los recuperos y clases únicas siguen en pie si no cambió el día: también se les avisa
            a_avisar = fijas + ([] if 'dia' in cambios else sueltas)
            for reserva in a_avisar:
                if reserva.usuario.email:
                    transaction.on_commit(lambda r=reserva: _avisar_cambio(r, original))
                    resumen['avisados'] += 1
    return resumen


def _avisar_cambio(reserva, clase_anterior):
    from .email_service import enviar_email_modificacion_reserva
    try:
        enviar_email_modificacion_reserva(reserva=reserva, clase_anterior=clase_anterior)
    except Exception as e:
        logger.error(f'No se pudo avisar el cambio de clase a {reserva.usuario.email}: {e}')


def _avisar_cancelacion(reserva, clase_anterior, clase):
    from .email_service import enviar_email_cancelacion_reserva
    try:
        enviado = enviar_email_cancelacion_reserva(
            reserva=reserva,
            motivo=MOTIVO_CAMBIO,
            motivo_detalle=(
                f'La clase de {clase_anterior.get_nombre_display()} pasó del {clase_anterior.dia} '
                f'al {clase.dia} a las {clase.horario:%H:%M}, así que tu reserva del '
                f'{reserva.fecha_unica:%d/%m} quedó sin efecto. Podés reservar otra fecha.'
            ),
            ofrecer_reemplazo=True,
            ofrecer_otras_sedes=False,
        )
        if enviado:
            CancelacionAdmin.objects.filter(reserva=reserva, motivo=MOTIVO_CAMBIO).update(email_enviado=True)
    except Exception as e:
        logger.error(f'No se pudo avisar la cancelación a {reserva.usuario.email}: {e}')
