"""
Datos de la pantalla "Hoy" del panel: las clases de un día con quién viene,
lo que hay para resolver y las últimas novedades.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from .actividad import eventos_actividad, sueltas_no_canceladas
from .models import (
    AusenciaTemporal,
    Clase,
    DeudaMensual,
    EstadoPagoCliente,
    Inasistencia,
    PlanUsuario,
    RegistroPago,
    Reserva,
)
from .panel import es_superadmin, ve_ingresos_estudio

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
DURACION_CLASE = timedelta(hours=1)


def fecha_larga(fecha):
    return f'{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}'


def dias_navegables(hoy, dias_con_clases):
    """Hoy y los 6 días siguientes, para los chips de la pantalla."""
    chips = []
    for i in range(7):
        fecha = hoy + timedelta(days=i)
        if i == 0:
            texto = 'Hoy'
        elif i == 1:
            texto = 'Mañana'
        else:
            texto = f'{DIAS_CORTOS[fecha.weekday()]} {fecha.day}'
        chips.append({'fecha': fecha, 'texto': texto, 'con_clases': DIAS[fecha.weekday()] in dias_con_clases})
    return chips


def elegir_fecha(valor, hoy, chips):
    """La fecha pedida si está entre los chips; si no, hoy (o el próximo día con clases)."""
    for chip in chips:
        if valor and chip['fecha'].isoformat() == valor:
            return chip['fecha']
    for chip in chips:
        if chip['con_clases']:
            return chip['fecha']
    return hoy


def _momento(fecha, clase, ahora):
    inicio = timezone.make_aware(datetime.combine(fecha, clase.horario))
    if ahora >= inicio + DURACION_CLASE:
        return 'pasada'
    if ahora >= inicio:
        return 'en_curso'
    return 'proxima'


def clases_del_dia(fecha, ahora=None):
    """
    Clases activas de `fecha` con su ocupación real ese día (horarios fijos menos
    los que avisaron, más recuperos y clases únicas) y la lista de alumnos.
    """
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    clases = list(Clase.objects.filter(activa=True, dia=DIAS[fecha.weekday()]).order_by('horario', 'direccion'))
    if not clases:
        return []

    fijas = list(
        Reserva.objects.filter(clase__in=clases, activa=True, fecha_unica__isnull=True)
        .select_related('usuario__profile')
    )
    avisaron = set(
        AusenciaTemporal.objects.filter(reserva__in=fijas, fecha=fecha).values_list('reserva_id', flat=True)
    )
    no_vinieron = set(
        Inasistencia.objects.filter(reserva__clase__in=clases, fecha=fecha).values_list('reserva_id', flat=True)
    ) if fecha <= hoy else set()

    # Recuperos y clases únicas de ese día: las activas y, si la clase ya pasó, las que
    # el comando de limpieza marcó como inactivas sin que nadie las cancelara.
    sueltas_qs = Reserva.objects.filter(clase__in=clases, fecha_unica=fecha).select_related('usuario__profile', 'clase')
    if fecha <= hoy:
        sueltas = list(sueltas_no_canceladas(sueltas_qs).filter(usuario__is_active=True).distinct())
        sueltas = [r for r in sueltas if r.activa or _momento(fecha, r.clase, ahora) == 'pasada']
    else:
        sueltas = list(sueltas_qs.filter(activa=True))

    por_clase = {c.id: {'fijas': [], 'sueltas': []} for c in clases}
    for r in fijas:
        por_clase[r.clase_id]['fijas'].append(r)
    for r in sueltas:
        por_clase[r.clase_id]['sueltas'].append(r)

    resultado = []
    for clase in clases:
        alumnos = []
        for r in por_clase[clase.id]['fijas']:
            alumnos.append(_alumno(r, fecha, avisaron=r.id in avisaron, no_vino=r.id in no_vinieron))
        for r in por_clase[clase.id]['sueltas']:
            alumnos.append(_alumno(r, fecha, no_vino=r.id in no_vinieron))
        alumnos.sort(key=lambda a: (a['avisaron'], a['nombre'].lower()))

        vienen = sum(1 for a in alumnos if not a['avisaron'])
        cupo = clase.cupo_maximo or 0
        porcentaje = round(vienen / cupo * 100) if cupo else 0
        resultado.append({
            'clase': clase,
            'nombre': clase.get_nombre_display(),
            'sede': clase.get_direccion_corta(),
            'momento': _momento(fecha, clase, ahora) if fecha == hoy else ('pasada' if fecha < hoy else 'proxima'),
            'alumnos': alumnos,
            'vienen': vienen,
            'cupo': cupo,
            'libres': max(cupo - vienen, 0),
            'porcentaje': min(porcentaje, 100),
            'nivel': 'lleno' if vienen >= cupo else ('alto' if porcentaje >= 80 else ''),
            'avisaron': sum(1 for a in alumnos if a['avisaron']),
            'sueltas': len(por_clase[clase.id]['sueltas']),
        })
    return resultado


def _alumno(reserva, fecha, avisaron=False, no_vino=False):
    usuario = reserva.usuario
    try:
        perfil = usuario.profile
    except Exception:
        perfil = None
    marcas = []
    if reserva.fecha_unica:
        marcas.append(('Recupero', 'ok') if reserva.es_recupero else ('Clase única', 'ok'))
    if avisaron:
        marcas.append(('Avisó que no viene', 'warn'))
    if no_vino:
        marcas.append(('No vino', 'danger'))
    if perfil:
        if perfil.fecha_primera_clase == fecha:
            marcas.append(('Primera clase', 'sand'))
        if perfil.fecha_nacimiento and (perfil.fecha_nacimiento.month, perfil.fecha_nacimiento.day) == (fecha.month, fecha.day):
            marcas.append(('Cumple años', 'sand'))
        if perfil.tiene_lesiones:
            marcas.append(('Salud', 'danger'))
    return {
        'nombre': usuario.get_full_name() or usuario.username,
        'usuario': usuario,
        'url': reverse('gravity:admin_usuario_detalle', args=[usuario.id]),
        'avisaron': avisaron,
        'marcas': marcas,
    }


def pendientes_hoy(user, hoy):
    """Cosas para resolver. Las deudas las ve todo el equipo (cobran); lo demás, el superadmin."""
    items = []
    deudores = EstadoPagoCliente.objects.filter(
        saldo_actual__lt=0, usuario__is_active=True, usuario__is_staff=False
    ).count()
    if deudores:
        items.append({
            'icono': 'pagos', 'tono': 'danger',
            'titulo': f'{deudores} alumno{"s" if deudores != 1 else ""} con deuda',
            'detalle': 'Revisalos antes de cobrar',
            'url': reverse('gravity:admin_pagos_vista_principal') + '?estado=debe',
        })

    hace_7 = timezone.now() - timedelta(days=7)
    con_plan = PlanUsuario.objects.filter(activo=True).values('usuario_id')
    nuevos_sin_plan = User.objects.filter(
        is_staff=False, is_active=True, date_joined__gte=hace_7
    ).exclude(id__in=con_plan).count()
    if nuevos_sin_plan:
        items.append({
            'icono': 'alumno_nuevo', 'tono': 'info',
            'titulo': f'{nuevos_sin_plan} alumno{"s" if nuevos_sin_plan != 1 else ""} nuevo{"s" if nuevos_sin_plan != 1 else ""} sin plan',
            'detalle': 'Se registraron esta semana',
            'url': reverse('gravity:admin_usuarios_lista') + '?filtro=nuevos',
        })
    return items


def resumen_mes(hoy):
    """Cobrado y pendiente del mes en curso (solo superadmin)."""
    primero = hoy.replace(day=1)
    cobrado = RegistroPago.objects.filter(
        estado='confirmado', fecha_pago__gte=primero, fecha_pago__lte=hoy
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    pendiente = DeudaMensual.objects.filter(mes_año=primero).aggregate(t=Sum('monto_pendiente'))['t'] or Decimal('0')
    return {'mes': MESES[hoy.month - 1], 'cobrado': cobrado, 'pendiente': pendiente}


def datos_hoy(request):
    ahora = timezone.now()
    hoy = timezone.localdate(ahora)
    dias_con_clases = set(Clase.objects.filter(activa=True).values_list('dia', flat=True))
    chips = dias_navegables(hoy, dias_con_clases)
    fecha = elegir_fecha(request.GET.get('fecha'), hoy, chips)
    for chip in chips:
        chip['activo'] = chip['fecha'] == fecha

    clases = clases_del_dia(fecha, ahora)
    vienen = sum(c['vienen'] for c in clases)
    cupos = sum(c['cupo'] for c in clases)
    user = request.user
    nombre = user.first_name or user.username
    hora = timezone.localtime(ahora).hour
    saludo = 'Buen día' if 5 <= hora < 13 else ('Buenas tardes' if hora < 20 else 'Buenas noches')

    return {
        'hoy': hoy,
        'fecha': fecha,
        'fecha_larga': fecha_larga(fecha),
        'es_hoy': fecha == hoy,
        'saludo': f'{saludo}, {nombre}',
        'chips': chips,
        'clases': clases,
        'totales': {
            'clases': len(clases),
            'vienen': vienen,
            'libres': max(cupos - vienen, 0),
            'avisaron': sum(c['avisaron'] for c in clases),
            'sueltas': sum(c['sueltas'] for c in clases),
        },
        'proxima': next((c for c in clases if c['momento'] in ('en_curso', 'proxima')), None) if fecha == hoy else None,
        'pendientes': pendientes_hoy(user, hoy),
        'superadmin': es_superadmin(user),
        'mes': resumen_mes(hoy) if ve_ingresos_estudio(user) else None,
        'novedades': eventos_actividad(desde=hoy - timedelta(days=6), hasta=hoy, limite=6),
    }
