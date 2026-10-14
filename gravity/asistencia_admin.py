"""
Asistencia del panel: pasar lista de un día y la lista de faltas.

Pasar lista: la asistencia se da por hecha; el equipo marca "No vino" (una
Inasistencia) a quien faltó sin avisar, desde que la clase empieza y hasta
DIAS_PARA_MARCAR días atrás. Las fechas más viejas se ven en modo lectura.

La lista de un día pasado se arma con lo que había ese día (no con las reservas
de hoy):
  - horarios fijos reservados antes de que empezara la clase y que todavía no se
    habían dado de baja (la fecha de la baja sale del registro de la cancelación);
  - recuperos y clases únicas de esa fecha sin cancelación registrada (la limpieza
    los desactiva al pasar, así que "inactiva" no quiere decir "cancelada");
  - clases que ya existían ese día. De una clase en pausa no se guarda desde
    cuándo: se muestra en los días anteriores a su última modificación.
Si a una reserva le cambiaron la clase, figura en la clase nueva.

Faltas: avisos de ausencia (con el estado del recupero) e inasistencias sin aviso.
"""
from datetime import datetime, timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .actividad import sueltas_no_canceladas
from .hoy import DIAS, DIAS_CORTOS, _alumno, _momento, fecha_larga
from .models import AusenciaTemporal, Clase, Inasistencia, Reserva
from .recuperos import _emparejar

DIAS_PARA_MARCAR = 7


def inicio_clase(clase, fecha):
    return timezone.make_aware(datetime.combine(fecha, clase.horario))


def puede_marcar_fecha(fecha, hoy):
    return hoy - timedelta(days=DIAS_PARA_MARCAR) <= fecha <= hoy


def chips_fechas(hoy, fecha, dias_con_clases):
    """Hoy y los DIAS_PARA_MARCAR días anteriores (los que se pueden marcar)."""
    chips = []
    for i in range(DIAS_PARA_MARCAR + 1):
        f = hoy - timedelta(days=i)
        if i == 0:
            texto = 'Hoy'
        elif i == 1:
            texto = 'Ayer'
        else:
            texto = f'{DIAS_CORTOS[f.weekday()]} {f.day}'
        chips.append({
            'fecha': f, 'texto': texto, 'activo': f == fecha,
            'con_clases': DIAS[f.weekday()] in dias_con_clases,
        })
    return chips


def _clases_de(fecha, hoy, sede=''):
    """Clases que se dictaban ese día de la semana en esa fecha."""
    qs = Clase.objects.filter(dia=DIAS[fecha.weekday()])
    if sede:
        qs = qs.filter(direccion=sede)
    clases = []
    for clase in qs.order_by('horario', 'direccion'):
        if timezone.localtime(clase.fecha_creacion).date() > fecha:
            continue
        if not clase.activa and (fecha >= hoy or timezone.localtime(clase.fecha_modificacion).date() <= fecha):
            continue
        clases.append(clase)
    return clases


def _fecha_baja(reserva):
    """Cuándo dejó de valer un horario fijo (necesita las cancelaciones precargadas)."""
    fechas = [c.fecha_creacion for c in reserva.cancelaciones_admin.all()]
    fechas += [n.fecha_creacion for n in reserva.notificaciones_cancelacion.all() if n.tipo == 'permanente']
    return min(fechas) if fechas else reserva.fecha_modificacion


def _fija_vigente(reserva, inicio):
    """¿El horario fijo estaba anotado cuando empezó la clase?"""
    if reserva.fecha_reserva >= inicio:
        return False
    return reserva.activa or _fecha_baja(reserva) > inicio


def _fijas_de(clases, fecha):
    if not clases:
        return []
    inicios = {c.id: inicio_clase(c, fecha) for c in clases}
    qs = (
        Reserva.objects.filter(clase__in=clases, fecha_unica__isnull=True, fecha_reserva__lt=max(inicios.values()))
        .filter(Q(activa=True) | Q(fecha_modificacion__gt=min(inicios.values())))
        .select_related('usuario__profile', 'clase')
        .prefetch_related('cancelaciones_admin', 'notificaciones_cancelacion')
    )
    return [r for r in qs if _fija_vigente(r, inicios[r.clase_id])]


def _sueltas_de(clases, fecha, hoy, ahora):
    qs = Reserva.objects.filter(clase__in=clases, fecha_unica=fecha).select_related('usuario__profile', 'clase')
    if fecha > hoy:
        return list(qs.filter(activa=True))
    sueltas = sueltas_no_canceladas(qs).distinct()
    if fecha == hoy:
        # Hoy, una inactiva sin cancelación solo es "realizada" si la clase ya terminó
        return [r for r in sueltas if r.activa or _momento(fecha, r.clase, ahora) == 'pasada']
    return list(sueltas)


def reserva_en_fecha(reserva, fecha, ahora=None):
    """¿La reserva figura en la lista de su clase en esa fecha? (para validar al marcar)"""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    if reserva.fecha_unica:
        if reserva.fecha_unica != fecha:
            return False
        return any(r.id == reserva.id for r in _sueltas_de([reserva.clase], fecha, hoy, ahora))
    if reserva.clase.dia != DIAS[fecha.weekday()]:
        return False
    return any(r.id == reserva.id for r in _fijas_de([reserva.clase], fecha))


def lista_del_dia(fecha, sede='', ahora=None):
    """Clases de `fecha` con sus alumnos y el estado de cada uno para pasar lista."""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    clases = _clases_de(fecha, hoy, sede)
    if not clases:
        return []
    fijas = _fijas_de(clases, fecha)
    sueltas = _sueltas_de(clases, fecha, hoy, ahora)
    ids = [r.id for r in fijas] + [r.id for r in sueltas]
    avisaron = set(
        AusenciaTemporal.objects.filter(reserva_id__in=[r.id for r in fijas], fecha=fecha)
        .values_list('reserva_id', flat=True)
    )
    no_vinieron = set(
        Inasistencia.objects.filter(reserva_id__in=ids, fecha=fecha).values_list('reserva_id', flat=True)
    ) if fecha <= hoy else set()
    se_puede_marcar = puede_marcar_fecha(fecha, hoy)

    por_clase = {c.id: [] for c in clases}
    for r in fijas + sueltas:
        por_clase[r.clase_id].append(r)

    resultado = []
    for clase in clases:
        momento = _momento(fecha, clase, ahora) if fecha == hoy else ('pasada' if fecha < hoy else 'proxima')
        marcable = se_puede_marcar and momento != 'proxima'
        alumnos = []
        for r in por_clase[clase.id]:
            alumno = _alumno(r, fecha, avisaron=r.id in avisaron)
            alumno.update({
                'reserva_id': r.id,
                'no_vino': r.id in no_vinieron,
                'marcable': marcable and r.id not in avisaron,
            })
            alumnos.append(alumno)
        alumnos.sort(key=lambda a: (a['avisaron'], a['nombre'].lower()))

        anotados = sum(1 for a in alumnos if not a['avisaron'])
        no_vino = sum(1 for a in alumnos if a['no_vino'])
        resultado.append({
            'clase': clase,
            'nombre': clase.get_nombre_display(),
            'sede': clase.get_direccion_corta(),
            'momento': momento,
            'marcable': marcable,
            'alumnos': alumnos,
            'anotados': anotados,
            'avisaron': len(alumnos) - anotados,
            'no_vino': no_vino,
            'vinieron': anotados - no_vino,
            'cupo': clase.cupo_maximo or 0,
        })
    return resultado


def datos_pasar_lista(fecha, sede='', ahora=None):
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    clases = lista_del_dia(fecha, sede, ahora)
    dias_con_clases = set(Clase.objects.filter(activa=True).values_list('dia', flat=True))
    chips = chips_fechas(hoy, fecha, dias_con_clases)
    pasadas = [c for c in clases if c['momento'] != 'proxima']
    return {
        'fecha': fecha,
        'hoy': hoy,
        'fecha_larga': fecha_larga(fecha),
        'es_hoy': fecha == hoy,
        'es_ayer': fecha == hoy - timedelta(days=1),
        'es_futura': fecha > hoy,
        'solo_lectura': fecha < hoy - timedelta(days=DIAS_PARA_MARCAR),
        'dias_para_marcar': DIAS_PARA_MARCAR,
        'fecha_minima': hoy - timedelta(days=DIAS_PARA_MARCAR),
        'chips': chips,
        'otra_fecha': not any(c['activo'] for c in chips),
        'clases': clases,
        'totales': {
            'clases': len(clases),
            'anotados': sum(c['anotados'] for c in clases),
            'avisaron': sum(c['avisaron'] for c in clases),
            'no_vino': sum(c['no_vino'] for c in clases),
            'vinieron': sum(c['vinieron'] for c in pasadas),
            'pasadas': len(pasadas),
        },
    }


# ---------------------------------------------------------------------------
# Faltas
# ---------------------------------------------------------------------------

PERIODOS = ('proximas', '7', '30', '90')
TIPOS_FALTA = [('avisada', 'Avisaron'), ('sin_aviso', 'No vinieron')]


def _recuperos_cubiertos(ausencias, hoy):
    """
    {id de ausencia: fecha del recupero que la cubre}. Usa el mismo emparejamiento
    que las reglas de recupero (gravity/recuperos.py), con todas las ausencias y
    recuperos de los alumnos involucrados.
    """
    usuarios = {a.reserva.usuario_id for a in ausencias}
    if not usuarios:
        return {}
    todas = (
        AusenciaTemporal.objects.filter(reserva__usuario_id__in=usuarios, reserva__fecha_unica__isnull=True)
        .select_related('reserva__clase').order_by('fecha')
    )
    recuperos = (
        Reserva.objects.filter(usuario_id__in=usuarios, es_recupero=True, fecha_unica__isnull=False)
        .exclude(Q(activa=False) & (Q(notificaciones_cancelacion__tipo='permanente')
                                    | Q(cancelaciones_admin__isnull=False)))
        .select_related('clase').distinct()
    )
    por_usuario = {}
    for a in todas:
        por_usuario.setdefault(a.reserva.usuario_id, ([], []))[0].append(a)
    for r in recuperos:
        if r.usuario_id in por_usuario:
            por_usuario[r.usuario_id][1].append(r)

    cubiertas = {}
    for lista_aus, lista_rec in por_usuario.values():
        tuplas = [(r.clase.tipo, r.fecha_unica, r.fecha_reserva) for r in lista_rec]
        for i_rec, i_aus in _emparejar(lista_aus, tuplas).items():
            cubiertas[lista_aus[i_aus].id] = lista_rec[i_rec].fecha_unica
    return cubiertas


def estado_aviso(ausencia, cubiertas, hoy):
    """(texto, tono) del recupero de una ausencia avisada."""
    recupero = cubiertas.get(ausencia.id)
    if recupero:
        if recupero < hoy:
            return (f'Recuperó el {recupero:%d/%m}', 'ok')
        return (f'Recupera el {recupero:%d/%m}', 'ok')
    if ausencia.fecha_limite_recupero >= hoy and ausencia.reserva.activa:
        return (f'Puede recuperar hasta el {ausencia.fecha_limite_recupero:%d/%m}', 'warn')
    return ('No recuperó', 'muted')


def faltas(desde=None, hasta=None, sede='', buscar='', tipo='', usuario=None, proximas=False):
    """
    Avisos e inasistencias del período, de la más nueva a la más vieja (las
    próximas, de la más cercana a la más lejana). Devuelve (filas, conteo por tipo).
    """
    def filtrar(qs):
        if usuario:
            qs = qs.filter(reserva__usuario=usuario)
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        if sede:
            qs = qs.filter(reserva__clase__direccion=sede)
        if buscar:
            for palabra in buscar.split():
                qs = qs.filter(Q(reserva__usuario__first_name__icontains=palabra)
                               | Q(reserva__usuario__last_name__icontains=palabra)
                               | Q(reserva__usuario__username__icontains=palabra))
        return qs.select_related('reserva__usuario__profile', 'reserva__clase')

    avisos = list(filtrar(AusenciaTemporal.objects.filter(reserva__fecha_unica__isnull=True)))
    sin_aviso = list(filtrar(Inasistencia.objects.select_related('registrado_por')))
    conteo = {'avisada': len(avisos), 'sin_aviso': len(sin_aviso)}

    filas = []
    if tipo in ('', 'avisada'):
        filas += [{'tipo': 'avisada', 'obj': a} for a in avisos]
    if tipo in ('', 'sin_aviso'):
        filas += [{'tipo': 'sin_aviso', 'obj': i} for i in sin_aviso]
    filas.sort(key=lambda f: (f['obj'].fecha, f['obj'].reserva.clase.horario), reverse=not proximas)
    return filas, conteo


def completar_filas(filas, hoy):
    """Datos para mostrar (solo de la página visible: el recupero se calcula acá)."""
    cubiertas = _recuperos_cubiertos([f['obj'] for f in filas if f['tipo'] == 'avisada'], hoy)
    ayer = hoy - timedelta(days=1)
    manana = hoy + timedelta(days=1)
    for f in filas:
        obj = f['obj']
        reserva = obj.reserva
        usuario = reserva.usuario
        clase = reserva.clase
        f['fecha'] = obj.fecha
        if obj.fecha == hoy:
            f['dia_texto'] = 'Hoy'
        elif obj.fecha == ayer:
            f['dia_texto'] = 'Ayer'
        elif obj.fecha == manana:
            f['dia_texto'] = 'Mañana'
        else:
            f['dia_texto'] = fecha_larga(obj.fecha)
        f['usuario'] = usuario
        f['nombre'] = usuario.get_full_name() or usuario.username
        f['url'] = reverse('gravity:admin_usuario_detalle', args=[usuario.id]) if not usuario.is_staff else ''
        f['clase'] = f'{clase.get_nombre_display()} · {clase.horario:%H:%M} · {clase.get_direccion_corta()}'
        f['url_lista'] = (reverse('gravity:admin_asistencia') + f'?fecha={obj.fecha.isoformat()}#clase-{clase.id}')
        if f['tipo'] == 'avisada':
            f['estado'] = estado_aviso(obj, cubiertas, hoy)
            f['detalle'] = f'Avisó el {timezone.localtime(obj.fecha_creacion):%d/%m a las %H:%M}'
        else:
            f['estado'] = ('No vino sin avisar', 'danger')
            quien = obj.registrado_por
            f['detalle'] = f'Lo marcó {quien.get_full_name() or quien.username}' if quien else ''
    return filas
