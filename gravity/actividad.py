"""
Actividad de los alumnos para el panel: bajas de horario, avisos de ausencia,
planes cancelados o sumados, recuperos, clases únicas y cancelaciones del estudio.

La usan la pantalla Actividad (con filtros) y "Hoy" (las últimas novedades).

Recuperos y clases únicas: un comando marca como inactivos los que ya pasaron
(limpiar_reservas_fecha_unica), así que "inactiva" no quiere decir "cancelada".
Una reserva de una sola vez cuenta como cancelada solo si hay un registro de la
cancelación (aviso del alumno o cancelación del estudio).
"""
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from .models import (
    CancelacionAdmin,
    NotificacionCancelacion,
    NotificacionCancelacionPlan,
    NotificacionPlanAdicional,
    Reserva,
)

TIPOS = [
    ('cancelacion_permanente', 'Bajas'),
    ('ausencia_temporal', 'Avisos de ausencia'),
    ('recupero', 'Recuperos'),
    ('clase_unica', 'Clases únicas'),
    ('cancelacion_plan', 'Planes cancelados'),
    ('plan_adicional', 'Planes sumados'),
    ('cancelacion_admin', 'Canceladas por el estudio'),
]

DIAS_RANGO_POR_DEFECTO = 30


def sueltas_no_canceladas(qs):
    """Reservas de una sola vez sin cancelación registrada (siguen o ya se hicieron)."""
    return qs.exclude(cancelaciones_admin__isnull=False).exclude(
        notificaciones_cancelacion__tipo='permanente'
    )


def dar_de_baja_reservas(reservas):
    """
    Cancela de una vez reservas que da de baja el propio alumno (al cancelar el plan
    o eliminar la cuenta), dejando el registro: sin él, un recupero cancelado se
    confundiría con uno realizado y la asistencia de días pasados no sabría desde
    cuándo dejó de venir.
    """
    ids = list(reservas.filter(activa=True).values_list('id', flat=True))
    if ids:
        Reserva.objects.filter(id__in=ids).update(activa=False, fecha_modificacion=timezone.now())
        NotificacionCancelacion.objects.bulk_create(
            [NotificacionCancelacion(reserva_id=i, tipo='permanente') for i in ids]
        )
    return len(ids)


def _nombre(usuario):
    return usuario.get_full_name() or usuario.username


def _url_alumno(usuario):
    if usuario.is_staff:
        return ''
    return reverse('gravity:admin_usuario_detalle', args=[usuario.id])


def _clase(clase):
    return f'{clase.get_nombre_display()} · {clase.dia} {clase.horario:%H:%M} · {clase.get_direccion_corta()}'


def _buscar(campo, texto):
    return (Q(**{f'{campo}__username__icontains': texto})
            | Q(**{f'{campo}__first_name__icontains': texto})
            | Q(**{f'{campo}__last_name__icontains': texto}))


def _evento(tipo, icono, titulo, detalle, fecha, alumno, quien='', estado=None, nota=''):
    return {
        'tipo': tipo,
        'icono': icono,
        'titulo': titulo,
        'detalle': detalle,
        'fecha': fecha,
        'dia': timezone.localtime(fecha).date(),
        'hace': 'hace ' + timesince(fecha, depth=1),
        'alumno': alumno,
        'url': _url_alumno(alumno),
        'quien': quien,
        'estado': estado,  # (texto, tono) o None
        'nota': nota,
    }


def _estado_suelta(reserva, cancelada, hoy):
    if cancelada:
        return ('Cancelada', 'muted')
    if reserva.fecha_unica < hoy or not reserva.activa:
        return ('Realizada', 'ok')
    return ('Reservada', 'info')


def eventos_actividad(tipo='', buscar='', sede='', desde=None, hasta=None, fecha_unica_desde=None, limite=None):
    """
    Lista de eventos ordenada del más nuevo al más viejo. `desde`/`hasta` son fechas
    (se comparan con el día en que pasó cada cosa).
    """
    hoy = timezone.localdate()
    eventos = []

    def rango(qs, campo):
        if desde:
            qs = qs.filter(**{f'{campo}__date__gte': desde})
        if hasta:
            qs = qs.filter(**{f'{campo}__date__lte': hasta})
        return qs

    # 1. Bajas de horario y avisos de ausencia (los hace el alumno)
    if not fecha_unica_desde and tipo in ('', 'cancelacion_permanente', 'ausencia_temporal'):
        qs = NotificacionCancelacion.objects.select_related('reserva__clase', 'reserva__usuario')
        if tipo == 'cancelacion_permanente':
            qs = qs.filter(tipo='permanente')
        elif tipo == 'ausencia_temporal':
            qs = qs.filter(tipo='temporal')
        if buscar:
            qs = qs.filter(_buscar('reserva__usuario', buscar))
        if sede:
            qs = qs.filter(reserva__clase__direccion=sede)
        for n in rango(qs, 'fecha_creacion'):
            reserva, alumno = n.reserva, n.reserva.usuario
            if n.tipo == 'temporal':
                fecha = f' el {n.fecha_ausencia:%d/%m}' if n.fecha_ausencia else ''
                # El aviso lo puede cargar el alumno o el estudio en su nombre: no se sabe quién
                eventos.append(_evento('ausencia_temporal', 'ausencia', f'{_nombre(alumno)} avisó que no va{fecha}',
                                       _clase(reserva.clase), n.fecha_creacion, alumno))
            elif reserva.fecha_unica:
                que = 'su recupero' if reserva.es_recupero else 'su clase única'
                eventos.append(_evento('cancelacion_permanente', 'baja',
                                       f'{_nombre(alumno)} canceló {que} del {reserva.fecha_unica:%d/%m}',
                                       _clase(reserva.clase), n.fecha_creacion, alumno, 'El alumno'))
            else:
                eventos.append(_evento('cancelacion_permanente', 'baja', f'{_nombre(alumno)} dejó su horario fijo',
                                       _clase(reserva.clase), n.fecha_creacion, alumno, 'El alumno'))

    # 2 y 3. Planes cancelados y sumados (no tienen sede)
    if not fecha_unica_desde and not sede:
        planes = [
            ('cancelacion_plan', NotificacionCancelacionPlan, 'canceló su plan'),
            ('plan_adicional', NotificacionPlanAdicional, 'sumó un plan'),
        ]
        for clave, modelo, accion in planes:
            if tipo not in ('', clave):
                continue
            qs = modelo.objects.select_related('usuario', 'plan')
            if buscar:
                qs = qs.filter(_buscar('usuario', buscar))
            for n in rango(qs, 'fecha_creacion'):
                eventos.append(_evento(clave, 'plan', f'{_nombre(n.usuario)} {accion}',
                                       n.plan.nombre if n.plan else 'Plan eliminado',
                                       n.fecha_creacion, n.usuario, 'El alumno'))

    # 4. Recuperos y clases únicas
    if tipo in ('', 'recupero', 'clase_unica'):
        qs = Reserva.objects.filter(fecha_unica__isnull=False).select_related(
            'usuario', 'clase', 'creado_por'
        ).prefetch_related('cancelaciones_admin', 'notificaciones_cancelacion')
        if tipo == 'recupero':
            qs = qs.filter(es_recupero=True)
        elif tipo == 'clase_unica':
            qs = qs.filter(es_recupero=False)
        if buscar:
            qs = qs.filter(_buscar('usuario', buscar))
        if sede:
            qs = qs.filter(clase__direccion=sede)
        if fecha_unica_desde:
            qs = sueltas_no_canceladas(qs.filter(fecha_unica__gte=fecha_unica_desde))
        else:
            qs = rango(qs, 'fecha_reserva')
        for r in qs:
            cancelada = bool(r.cancelaciones_admin.all()) or any(
                n.tipo == 'permanente' for n in r.notificaciones_cancelacion.all()
            )
            if r.creado_por_id and r.creado_por_id != r.usuario_id:
                quien = _nombre(r.creado_por)
            else:
                quien = 'El alumno'
            que = 'un recupero' if r.es_recupero else 'una clase única'
            eventos.append(_evento(
                'recupero' if r.es_recupero else 'clase_unica', 'recupero',
                f'{_nombre(r.usuario)} reservó {que} para el {r.fecha_unica:%d/%m}',
                _clase(r.clase), r.fecha_reserva, r.usuario, quien,
                estado=_estado_suelta(r, cancelada, hoy),
            ))

    # 5. Cancelaciones del estudio
    if not fecha_unica_desde and tipo in ('', 'cancelacion_admin'):
        qs = CancelacionAdmin.objects.select_related('reserva__clase', 'reserva__usuario', 'admin_user')
        if buscar:
            qs = qs.filter(_buscar('reserva__usuario', buscar))
        if sede:
            qs = qs.filter(reserva__clase__direccion=sede)
        for c in rango(qs, 'fecha_creacion'):
            reserva, alumno = c.reserva, c.reserva.usuario
            if reserva.fecha_unica:
                que = f'el recupero del {reserva.fecha_unica:%d/%m}' if reserva.es_recupero else f'la clase única del {reserva.fecha_unica:%d/%m}'
            else:
                que = 'el horario fijo'
            nota = c.motivo + (f' — {c.motivo_detalle}' if c.motivo_detalle else '')
            eventos.append(_evento('cancelacion_admin', 'baja', f'Se canceló {que} de {_nombre(alumno)}',
                                   _clase(reserva.clase), c.fecha_creacion, alumno,
                                   _nombre(c.admin_user) if c.admin_user else 'El estudio', nota=nota))

    eventos.sort(key=lambda e: e['fecha'], reverse=True)
    return eventos[:limite] if limite else eventos


def rango_por_defecto(hoy=None):
    hoy = hoy or timezone.localdate()
    return hoy - timedelta(days=DIAS_RANGO_POR_DEFECTO - 1), hoy
