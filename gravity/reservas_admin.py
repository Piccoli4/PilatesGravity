"""
Reservas desde el panel: fechas posibles de una clase, lugares libres de muchas
clases y fechas de una vez, lo que tiene el alumno (plan, recuperos) y el estado
real de una reserva que ya no está activa.

El panel puede pasarse del plan o cargar un recupero sin ausencia (por ejemplo, un
regalo o un arreglo), pero siempre respeta el cupo de la clase y lo avisa.
"""
from collections import Counter
from datetime import datetime, timedelta

from django.utils import timezone

from .models import AusenciaTemporal, Clase, PlanUsuario, Reserva
from .recuperos import EstadoRecuperos

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
DIAS_CORTOS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']
DURACION_CLASE = timedelta(hours=1)


def proximas_fechas(clase, ahora=None, cantidad=4):
    """Próximas fechas en que se dicta la clase (hoy, si todavía no terminó)."""
    ahora = timezone.localtime(ahora or timezone.now())
    hoy = ahora.date()
    if clase.dia not in DIAS:
        return []
    dias_hasta = (DIAS.index(clase.dia) - hoy.weekday()) % 7
    primera = hoy + timedelta(days=dias_hasta)
    if dias_hasta == 0:
        fin = timezone.make_aware(datetime.combine(hoy, clase.horario)) + DURACION_CLASE
        if ahora >= fin:
            primera += timedelta(days=7)
    return [primera + timedelta(days=7 * i) for i in range(cantidad)]


def fecha_corta(fecha, hoy=None):
    hoy = hoy or timezone.localdate()
    if fecha == hoy:
        return f'Hoy {fecha:%d/%m}'
    if fecha == hoy + timedelta(days=1):
        return f'Mañana {fecha:%d/%m}'
    return f'{DIAS_CORTOS[fecha.weekday()].capitalize()} {fecha:%d/%m}'


def ocupacion(clases, fechas_por_clase):
    """
    Lugares libres de cada clase en cada fecha pedida, con tres consultas en total.
    Devuelve {clase_id: {'fijos': n, 'libres_fijos': n, 'fechas': {fecha: libres}}}.
    """
    ids = [c.id for c in clases]
    fijos = Counter(
        Reserva.objects.filter(clase_id__in=ids, activa=True, fecha_unica__isnull=True)
        .values_list('clase_id', flat=True)
    )
    todas = {f for fechas in fechas_por_clase.values() for f in fechas}
    ausencias = Counter(
        AusenciaTemporal.objects.filter(
            reserva__clase_id__in=ids, reserva__activa=True, reserva__fecha_unica__isnull=True, fecha__in=todas
        ).values_list('reserva__clase_id', 'fecha')
    )
    sueltas = Counter(
        Reserva.objects.filter(clase_id__in=ids, activa=True, fecha_unica__in=todas)
        .values_list('clase_id', 'fecha_unica')
    )
    resultado = {}
    for clase in clases:
        cupo = clase.cupo_maximo or 0
        n = fijos.get(clase.id, 0)
        resultado[clase.id] = {
            'fijos': n,
            'libres_fijos': max(cupo - n, 0) if clase.activa else 0,
            'fechas': {
                f: max(cupo - n + ausencias.get((clase.id, f), 0) - sueltas.get((clase.id, f), 0), 0)
                if clase.activa else 0
                for f in fechas_por_clase.get(clase.id, [])
            },
        }
    return resultado


def info_alumno(usuario):
    """Plan, uso de la semana, recuperos disponibles y horarios fijos del alumno."""
    clases_plan, planes = PlanUsuario.obtener_clases_disponibles_usuario(usuario)
    plan = planes.select_related('plan').first() if clases_plan else None
    recuperos = EstadoRecuperos(usuario)
    fijas = list(
        usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=True).select_related('clase')
    )
    fijas.sort(key=lambda r: (DIAS.index(r.clase.dia) if r.clase.dia in DIAS else 9, r.clase.horario))
    usadas = Reserva.contar_reservas_usuario_semana(usuario)
    return {
        'plan': plan.plan.nombre if plan else None,
        'clases_plan': clases_plan,
        'usadas': usadas,
        'plan_completo': usadas >= clases_plan,
        'recuperos': recuperos.disponibles,
        'limite_recupero': min((a.fecha_limite_recupero for a in recuperos.pendientes), default=None)
        if recuperos.disponibles else None,
        'fijas': fijas,
    }


def estado_reserva(reserva, hoy=None):
    """
    (texto, tono) del estado real. Necesita cancelaciones_admin y
    notificaciones_cancelacion precargadas.
    """
    hoy = hoy or timezone.localdate()
    if reserva.activa:
        if reserva.fecha_unica and reserva.fecha_unica < hoy:
            return ('Realizada', 'ok')
        if not reserva.clase.activa:
            return ('Clase en pausa', 'muted')
        return ('Activa', 'info')
    if reserva.cancelaciones_admin.all():
        return ('Cancelada por el estudio', 'danger')
    baja_alumno = any(n.tipo == 'permanente' for n in reserva.notificaciones_cancelacion.all())
    if reserva.fecha_unica:
        if baja_alumno:
            return ('Cancelada por el alumno', 'warn')
        if reserva.fecha_unica <= hoy:
            return ('Realizada', 'ok')
        return ('Cancelada', 'muted')
    if baja_alumno:
        return ('Dada de baja por el alumno', 'warn')
    return ('Finalizada', 'muted')
