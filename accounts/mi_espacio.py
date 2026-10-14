"""
Resumen del alumno para "Mi espacio" (/accounts/profile/): próxima clase, horarios
fijos de la semana, plan vigente, recuperos y avisos pendientes.
"""
from datetime import timedelta

from django.utils import timezone

from gravity.models import AusenciaTemporal, PlanUsuario, Reserva, SolicitudCambioPlan

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

SEDES = {
    'sede_principal': {
        'nombre': 'Sede Central',
        'direccion': 'La Rioja 3044',
        'mapa': 'https://www.google.com/maps/search/?api=1&query=La+Rioja+3044,+Santa+Fe',
    },
    'sede_2': {
        'nombre': 'Sede 2',
        'direccion': '9 de Julio 3696',
        'mapa': 'https://www.google.com/maps/search/?api=1&query=9+de+Julio+3696,+Santa+Fe',
    },
}

SEDE_PREFERIDA = {
    'cualquiera': 'Cualquier sede',
    'sede_principal': 'Sede Central',
    'sede_2': 'Sede 2',
}


def _cuando(fecha, hoy):
    """'Hoy', 'Mañana' o 'Lunes 13/10'."""
    dias = (fecha - hoy).days
    if dias == 0:
        return 'Hoy'
    if dias == 1:
        return 'Mañana'
    return f"{DIAS[fecha.weekday()]} {fecha.strftime('%d/%m')}"


def _proxima_fecha(reserva, ahora):
    """Próxima fecha en que el alumno va a esta clase (salteando ausencias avisadas)."""
    hoy = ahora.date()
    horario = reserva.clase.horario

    if reserva.fecha_unica:
        if reserva.fecha_unica > hoy or (reserva.fecha_unica == hoy and horario > ahora.time()):
            return reserva.fecha_unica
        return None

    if reserva.clase.dia not in DIAS:
        return None
    delta = (DIAS.index(reserva.clase.dia) - hoy.weekday()) % 7
    if delta == 0 and horario <= ahora.time():
        delta = 7

    ausentes = {a.fecha for a in reserva.ausencias_temporales.all()}
    for _ in range(10):
        fecha = hoy + timedelta(days=delta)
        if fecha not in ausentes:
            return fecha
        delta += 7
    return None


def _nombre_corto(clase):
    """'Reformer', 'Cadillac' o el nombre de la clase especial."""
    if clase.tipo == 'Especial' and clase.nombre_personalizado:
        return clase.nombre_personalizado
    return clase.tipo


def _item(reserva, fecha, hoy):
    clase = reserva.clase
    return {
        'reserva': reserva,
        'fecha': fecha,
        'cuando': _cuando(fecha, hoy) if fecha else None,
        'dia_corto': DIAS_CORTOS[DIAS.index(clase.dia)] if clase.dia in DIAS else clase.dia,
        'hora': clase.horario.strftime('%H:%M'),
        'clase': _nombre_corto(clase),
        'sede': SEDES.get(clase.direccion, {'nombre': clase.get_direccion_display(), 'direccion': '', 'mapa': ''}),
        'es_recupero': reserva.es_recupero,
        'es_puntual': bool(reserva.fecha_unica),
        # Clase en pausa (desactivada por el estudio): conserva el lugar pero no se dicta
        'pausada': not clase.activa,
    }


def resumen_alumno(user):
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()

    reservas = list(
        user.reservas_pilates.filter(activa=True)
        .select_related('clase')
        .prefetch_related('ausencias_temporales')
    )

    # Próximas clases (la primera es la "próxima clase")
    proximas = []
    for reserva in reservas:
        if not reserva.clase.activa:
            continue
        fecha = _proxima_fecha(reserva, ahora)
        if fecha:
            proximas.append(_item(reserva, fecha, hoy))
    proximas.sort(key=lambda p: (p['fecha'], p['hora']))

    # Horarios fijos de la semana, ordenados por día y hora
    fijas = sorted(
        (r for r in reservas if not r.fecha_unica),
        key=lambda r: (DIAS.index(r.clase.dia) if r.clase.dia in DIAS else 9, r.clase.horario),
    )
    semana = [_item(r, None, hoy) for r in fijas]
    puntuales = [p for p in proximas if p['es_puntual']]

    # Clases a las que avisó que no va
    ausencias = [
        {
            'cuando': _cuando(a.fecha, hoy),
            'hora': a.reserva.clase.horario.strftime('%H:%M'),
            'clase': _nombre_corto(a.reserva.clase),
        }
        for a in AusenciaTemporal.objects.filter(
            reserva__usuario=user, reserva__activa=True, fecha__gte=hoy
        ).select_related('reserva__clase').order_by('fecha')[:4]
    ]

    # Recuperos
    puede_recuperar, n_recuperos, ausencias_recupero = Reserva.usuario_puede_hacer_recupero(user)
    limite_recupero = None
    if puede_recuperar:
        limite_recupero = min(a.fecha_limite_recupero for a in ausencias_recupero)

    # Plan vigente y uso semanal
    clases_plan, planes_vigentes = PlanUsuario.obtener_clases_disponibles_usuario(user)
    plan = planes_vigentes.select_related('plan').first()
    plan_proximo = None
    if not plan:
        plan_proximo = (
            PlanUsuario.objects.filter(usuario=user, activo=True, fecha_inicio__gt=hoy)
            .select_related('plan').order_by('fecha_inicio').first()
        )
    usadas = Reserva.contar_reservas_usuario_semana(user)
    plan_info = None
    if plan:
        dias_restantes = plan.dias_restantes()
        plan_info = {
            'nombre': plan.plan.nombre,
            'clases': clases_plan,
            'usadas': usadas,
            'libres': max(0, clases_plan - usadas),
            'porcentaje': min(100, round(usadas * 100 / clases_plan)) if clases_plan else 0,
            'renueva': plan.tipo_plan == 'permanente' and plan.renovacion_automatica,
            'fecha_fin': plan.fecha_fin,
            'vence_pronto': dias_restantes <= 7,
            'dias_restantes': dias_restantes,
        }

    solicitud = (
        SolicitudCambioPlan.objects.filter(usuario=user, estado='pendiente')
        .select_related('plan_solicitado').first()
    )

    return {
        'proxima': proximas[0] if proximas else None,
        'semana': semana,
        'puntuales': puntuales,
        'ausencias': ausencias,
        'n_recuperos': n_recuperos if puede_recuperar else 0,
        'limite_recupero': limite_recupero,
        'plan': plan_info,
        'plan_proximo': plan_proximo,
        'solicitud': solicitud,
    }


def reservas_alumno(user, dias_agenda=14):
    """
    Datos de "Mis reservas": agenda de las próximas clases con fecha, horarios fijos
    con sus acciones (avisar ausencia, deshacer, dar de baja), recuperos/clases únicas
    e historial.
    """
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()
    fin_agenda = hoy + timedelta(days=dias_agenda - 1)

    reservas = list(
        user.reservas_pilates.filter(activa=True)
        .select_related('clase')
        .prefetch_related('ausencias_temporales')
    )
    fijas = sorted(
        (r for r in reservas if not r.fecha_unica),
        key=lambda r: (DIAS.index(r.clase.dia) if r.clase.dia in DIAS else 9, r.clase.horario),
    )
    puntuales = sorted(
        (r for r in reservas if r.fecha_unica and _proxima_fecha(r, ahora)),
        key=lambda r: (r.fecha_unica, r.clase.horario),
    )

    # Horarios fijos con el estado de su próxima clase
    horarios = []
    for reserva in fijas:
        item = _item(reserva, None, hoy)
        proxima = reserva.get_proxima_fecha()
        ausencias = {a.fecha: a for a in reserva.ausencias_temporales.all()}
        puede, motivo = reserva.puede_modificarse()
        if item['pausada']:
            proxima = None
            puede, motivo = False, 'La clase está en pausa: tu lugar sigue reservado.'
        item.update({
            'proxima': proxima,
            'proxima_txt': _cuando(proxima, hoy) if proxima else None,
            'ausencia': ausencias.get(proxima),
            'puede_modificar': puede,
            'motivo': motivo,
            'limite_recupero': proxima + timedelta(days=6) if proxima else None,
        })
        horarios.append(item)

    # Agenda: cada clase con fecha concreta dentro de los próximos días
    agenda = []
    for item in horarios:
        reserva = item['reserva']
        if item['pausada']:
            continue
        ausencias = {a.fecha: a for a in reserva.ausencias_temporales.all()}
        delta = (DIAS.index(reserva.clase.dia) - hoy.weekday()) % 7 if reserva.clase.dia in DIAS else None
        if delta is None:
            continue
        fecha = hoy + timedelta(days=delta)
        while fecha <= fin_agenda:
            if not (fecha == hoy and reserva.clase.horario <= ahora.time()):
                agenda.append(dict(
                    item,
                    fecha=fecha,
                    cuando=_cuando(fecha, hoy),
                    ausencia=ausencias.get(fecha),
                    limite_recupero=fecha + timedelta(days=6),
                    # Solo la próxima clase de cada horario admite avisar ausencia
                    es_proxima=fecha == item['proxima'],
                ))
            fecha += timedelta(days=7)
    for reserva in puntuales:
        if reserva.fecha_unica <= fin_agenda:
            puede, motivo = reserva.puede_modificarse()
            agenda.append(dict(
                _item(reserva, reserva.fecha_unica, hoy),
                ausencia=None, es_proxima=False, puede_modificar=puede, motivo=motivo,
            ))
    agenda.sort(key=lambda a: (a['fecha'], a['hora']))

    extras = []
    for reserva in puntuales:
        puede, motivo = reserva.puede_modificarse()
        extras.append(dict(_item(reserva, reserva.fecha_unica, hoy), puede_modificar=puede, motivo=motivo))

    return {
        'agenda': agenda,
        'horarios': horarios,
        'extras': extras,
        'historial': historial_reservas(user),
    }


def historial_reservas(user, limite=10):
    """Reservas que ya no están activas, con un estado que explica qué pasó."""
    pasadas = list(
        user.reservas_pilates.filter(activa=False)
        .select_related('clase')
        .prefetch_related('notificaciones_cancelacion', 'cancelaciones_admin')
        .order_by('-id')[:limite * 3]
    )
    items = []
    for reserva in pasadas:
        dada_de_baja = any(n.tipo == 'permanente' for n in reserva.notificaciones_cancelacion.all())
        if reserva.cancelaciones_admin.all():
            estado, tono = 'Cancelada por el estudio', 'off'
        elif dada_de_baja:
            estado, tono = ('Cancelada' if reserva.fecha_unica else 'Dada de baja'), 'off'
        elif reserva.fecha_unica:
            estado, tono = ('Recupero realizado' if reserva.es_recupero else 'Clase única realizada'), 'ok'
        else:
            estado, tono = 'Finalizada', 'off'
        fecha = reserva.fecha_unica or timezone.localtime(reserva.fecha_modificacion).date()
        items.append(dict(_item(reserva, reserva.fecha_unica, timezone.localdate()), estado=estado, tono=tono, fecha_ref=fecha))
    items.sort(key=lambda i: i['fecha_ref'], reverse=True)
    return items[:limite]


def detalle_reserva_alumno(reserva, semanas=4):
    """
    Datos para el detalle de una reserva: tipo, próxima clase con su estado,
    próximas fechas (horario fijo) y qué acciones admite.
    """
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()
    puede, motivo = reserva.puede_modificarse()

    if reserva.fecha_unica:
        item = _item(reserva, reserva.fecha_unica, hoy)
        item.update({
            'tipo_txt': 'Recupero' if reserva.es_recupero else 'Clase única',
            'proxima': reserva.fecha_unica,
            'proxima_txt': _cuando(reserva.fecha_unica, hoy),
            'ausencia': None,
            'fechas': [],
        })
    else:
        item = _item(reserva, None, hoy)
        # En pausa no hay próximas clases
        proxima = reserva.get_proxima_fecha() if reserva.clase.activa else None
        ausencias = {a.fecha: a for a in reserva.ausencias_temporales.all()}
        fechas = []
        if proxima:
            for i in range(semanas):
                fecha = proxima + timedelta(days=7 * i)
                fechas.append({'fecha': fecha, 'cuando': _cuando(fecha, hoy), 'ausencia': ausencias.get(fecha)})
        item.update({
            'tipo_txt': 'Horario fijo',
            'proxima': proxima,
            'proxima_txt': _cuando(proxima, hoy) if proxima else None,
            'ausencia': ausencias.get(proxima),
            'limite_recupero': proxima + timedelta(days=6) if proxima else None,
            'fechas': fechas,
        })
    if item['pausada'] and not reserva.fecha_unica:
        puede, motivo = False, 'La clase está en pausa: tu lugar sigue reservado.'
    item.update({'puede_modificar': puede, 'motivo': motivo})
    return item
