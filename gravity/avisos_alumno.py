"""
Avisos push a los alumnos por algo que acaba de pasar: el estudio canceló o cambió
una clase, resolvió un pedido de plan, cargó un pago, o se liberó un lugar en una
clase en la que el alumno está en lista de espera.

Los programados (recordatorio de clase, recupero por vencer, cumpleaños) están en
recordatorios.py. Cada alumno elige qué tipos recibe (push.AVISOS_ALUMNO).
"""
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from .models import ListaEspera, Reserva
from .push import aviso_seguro, enviar_push_usuario
from .templatetags.formato import pesos


def _clase_corta(clase):
    return f'{clase.get_nombre_display()} · {clase.dia} {clase.horario:%H:%M} · {clase.get_direccion_corta()}'


# ------------------------------------------------------------------------------
# Cambios que hace el estudio
# ------------------------------------------------------------------------------

@aviso_seguro
def avisar_reserva_cancelada(reserva, detalle=''):
    """El estudio canceló una reserva del alumno (horario fijo, recupero o clase única)."""
    clase = reserva.clase
    if reserva.fecha_unica:
        que = 'recupero' if reserva.es_recupero else 'clase'
        titulo = f'Cancelamos tu {que} del {reserva.fecha_unica:%d/%m}'
    else:
        titulo = f'Cancelamos tu horario de los {clase.dia.lower()} a las {clase.horario:%H:%M}'
    return enviar_push_usuario(
        reserva.usuario, 'cambios', titulo,
        detalle or f'{_clase_corta(clase)}. Mirá el detalle en Mis reservas o escribinos.',
        url=reverse('accounts:mis_reservas'), etiqueta=f'cancelada-{reserva.pk}',
    )


@aviso_seguro
def avisar_reserva_modificada(reserva, clase_anterior=None):
    """El estudio pasó una reserva del alumno a otra clase, o cambió el día u horario de su clase."""
    clase = reserva.clase
    cuando = f' (el {reserva.fecha_unica:%d/%m})' if reserva.fecha_unica else ''
    return enviar_push_usuario(
        reserva.usuario, 'cambios', 'Cambiamos una de tus clases',
        f'Ahora es {_clase_corta(clase)}{cuando}.',
        url=reverse('gravity:detalle_reserva', args=[reserva.numero_reserva]),
        etiqueta=f'modificada-{reserva.pk}',
    )


# ------------------------------------------------------------------------------
# Plan y pagos
# ------------------------------------------------------------------------------

@aviso_seguro
def avisar_solicitud_resuelta(solicitud):
    """El estudio aprobó o rechazó un pedido de plan del alumno."""
    plan = solicitud.plan_solicitado.nombre if solicitud.plan_solicitado else ''
    if solicitud.estado == 'aprobada':
        titulo = 'Aprobamos tu pedido de plan'
        cuerpo = f'Ya tenés el plan "{plan}".' if plan else 'Ya podés verlo en Mis planes.'
    else:
        titulo = 'No pudimos aprobar tu pedido de plan'
        cuerpo = 'Entrá a Mis planes para ver el motivo o escribinos.'
    return enviar_push_usuario(
        solicitud.usuario, 'plan', titulo, cuerpo,
        url=reverse('gravity:mis_planes'), etiqueta=f'solicitud-{solicitud.pk}',
    )


@aviso_seguro
def avisar_pago_registrado(pago):
    """El estudio cargó un pago del alumno."""
    return enviar_push_usuario(
        pago.cliente, 'pago', 'Registramos tu pago',
        f'Recibimos ${pesos(pago.monto)}. ¡Gracias!',
        url=reverse('accounts:profile'), etiqueta=f'pago-{pago.pk}',
    )


# ------------------------------------------------------------------------------
# Lista de espera: se liberó un lugar
# ------------------------------------------------------------------------------

def anotar_en_espera(usuario, clase):
    """Anota al alumno en la lista de espera de una clase. Devuelve (ok, mensaje)."""
    if not clase.activa:
        return False, 'Esa clase ya no está disponible.'
    if Reserva.objects.filter(usuario=usuario, clase=clase, activa=True, fecha_unica__isnull=True).exists():
        return False, 'Ya tenés ese horario.'
    ListaEspera.objects.get_or_create(usuario=usuario, clase=clase)
    return True, (
        f'Te anotamos en la lista de espera de {clase.get_nombre_display()} '
        f'({clase.dia} {clase.horario:%H:%M}). Te avisamos si se libera un lugar.'
    )


def salir_de_espera(usuario, clase):
    ListaEspera.objects.filter(usuario=usuario, clase=clase).delete()


def _url_para_reservar(clase, una_vez):
    parametros = {
        'tipo': clase.tipo, 'sede': clase.direccion, 'dia': clase.dia,
        'horario': clase.horario.strftime('%H:%M'),
    }
    if una_vez:
        parametros['es_temporal'] = '1'
    return f"{reverse('gravity:reservar_clase')}?{urlencode(parametros)}"


@aviso_seguro
def avisar_lugar_liberado(clase, fecha=None):
    """
    Se liberó un lugar en una clase: avisa a quienes esperan lugar ahí.
    Con `fecha`, el lugar es solo para ese día (alguien avisó que no va, o canceló un
    recupero); sin fecha, es un lugar fijo. No avisa si en realidad no quedó lugar,
    si la clase ya pasó, ni a quien ya tiene la clase.
    """
    en_espera = list(ListaEspera.objects.filter(clase=clase, usuario__is_active=True).select_related('usuario'))
    if not en_espera or not clase.activa:
        return 0

    ahora = timezone.localtime(timezone.now())
    if fecha:
        if fecha < ahora.date() or (fecha == ahora.date() and clase.horario <= ahora.time()):
            return 0
    if clase.cupos_disponibles(fecha=fecha) <= 0:
        return 0

    # Quien ya tiene la clase (fija, o reservada para esa fecha) no necesita el aviso
    ya_la_tienen = Reserva.objects.filter(clase=clase, activa=True, usuario__in=[e.usuario for e in en_espera])
    fijos = set(ya_la_tienen.filter(fecha_unica__isnull=True).values_list('usuario_id', flat=True))
    en_fecha = set(ya_la_tienen.filter(fecha_unica=fecha).values_list('usuario_id', flat=True)) if fecha else set()
    if fijos:
        # Ya consiguieron el horario: salen de la lista
        ListaEspera.objects.filter(clase=clase, usuario_id__in=fijos).delete()

    if fecha:
        titulo = f'Se liberó un lugar el {clase.dia.lower()} {fecha:%d/%m}'
        cuerpo = (f'{clase.get_nombre_display()} · {clase.horario:%H:%M} · {clase.get_direccion_corta()}. '
                  f'Es solo para ese día: reservalo antes de que lo tome otra persona.')
    else:
        titulo = 'Se liberó un lugar fijo'
        cuerpo = f'{_clase_corta(clase)}. Reservalo antes de que lo tome otra persona.'
    url = _url_para_reservar(clase, una_vez=bool(fecha))
    etiqueta = f'lugar-{clase.pk}-{fecha:%Y%m%d}' if fecha else f'lugar-{clase.pk}'

    enviados = 0
    for espera in en_espera:
        if espera.usuario_id in fijos or espera.usuario_id in en_fecha:
            continue
        enviados += enviar_push_usuario(espera.usuario, 'lugar', titulo, cuerpo, url=url, etiqueta=etiqueta)
    return enviados


def avisar_lugar_por_reserva(reserva, fecha=None):
    """Atajo: una reserva dejó de ocupar su lugar (para siempre, o solo en `fecha`)."""
    return avisar_lugar_liberado(reserva.clase, fecha=fecha or reserva.fecha_unica)
