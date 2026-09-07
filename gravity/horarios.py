"""
Cálculo de horas trabajadas y costo de las profesoras.

El horario de cada profesora se guarda como bloques semanales con vigencia
(`BloqueHorarioProfesora`). Sobre ese horario habitual se aplican los ajustes
puntuales de cada fecha (`AjusteHorarioProfesora`) y el resultado se valoriza
con el valor hora que regía ese día (`ValorHoraProfesora`).

Todo se calcula sobre la marcha: no se guardan turnos día por día, así que
corregir un horario viejo no deja registros huérfanos, y como los bloques y los
valores hora tienen vigencia, los meses ya trabajados siguen dando el mismo
resultado aunque hoy cambie el horario o el valor hora.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .models import (
    AjusteHorarioProfesora,
    BloqueHorarioProfesora,
    Clase,
    LiquidacionProfesora,
    ValorHoraProfesora,
)

# El sistema trabaja de lunes a sábado, igual que las clases.
DIAS_INDICE = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

# Nombre corto de cada sede, para que entre en las tablas.
SEDES_CORTAS = {
    'sede_principal': 'La Rioja 3044',
    'sede_2': '9 de Julio 3696',
}

CERO = Decimal('0.00')


def hoy():
    """Fecha actual en la zona horaria del proyecto."""
    return timezone.localtime(timezone.now()).date()


def nombre_dia(fecha):
    """Nombre del día de la semana de una fecha ('Lunes', 'Martes', ...)."""
    return DIAS_INDICE[fecha.weekday()]


def horas_entre(hora_inicio, hora_fin):
    """Cantidad de horas entre dos horas del mismo día, con dos decimales."""
    if not hora_inicio or not hora_fin:
        return CERO
    inicio = hora_inicio.hour * 60 + hora_inicio.minute
    fin = hora_fin.hour * 60 + hora_fin.minute
    minutos = max(fin - inicio, 0)
    return (Decimal(minutos) / Decimal('60')).quantize(Decimal('0.01'))


def profesoras_activas():
    """
    Profesoras del estudio: administradoras contratadas.

    Son los usuarios staff que no son superusuarios, es decir, todas menos los
    superadministradores del estudio.
    """
    return User.objects.filter(
        is_staff=True,
        is_superuser=False,
        is_active=True,
    ).select_related('profile').order_by('first_name', 'last_name')


def nombre_profesora(profesora):
    return profesora.get_full_name() or profesora.username


def clases_disponibles():
    """
    Clases activas del estudio, ordenadas como la semana.

    Son las que se pueden elegir al armar el horario de una profesora, para no
    tener que tipear día, hora y sede a mano.
    """
    orden = {nombre: indice for indice, nombre in enumerate(DIAS_INDICE)}
    clases = Clase.objects.filter(activa=True)
    return sorted(clases, key=lambda c: (orden.get(c.dia, 9), c.horario, c.direccion))


def nombre_sede(sede):
    """Nombre corto de una sede, o el nombre completo si no es una conocida."""
    if not sede:
        return 'Sin sede'
    return SEDES_CORTAS.get(sede) or dict(Clase.DIRECCIONES).get(sede, sede)


# ==============================================================================
# RANGOS DE FECHAS
# ==============================================================================

def rango_dia(fecha):
    return fecha, fecha


def rango_semana(fecha):
    """Semana de lunes a domingo que contiene a `fecha`."""
    lunes = fecha - timedelta(days=fecha.weekday())
    return lunes, lunes + timedelta(days=6)


def rango_mes(año, mes):
    """Primer y último día del mes indicado."""
    primero = date(año, mes, 1)
    if mes == 12:
        siguiente = date(año + 1, 1, 1)
    else:
        siguiente = date(año, mes + 1, 1)
    return primero, siguiente - timedelta(days=1)


def iterar_fechas(desde, hasta):
    fecha = desde
    while fecha <= hasta:
        yield fecha
        fecha += timedelta(days=1)


# ==============================================================================
# HORARIO Y VALOR HORA VIGENTES
# ==============================================================================

def vigente_en(fecha):
    """Q() para registros con vigencia abierta o cerrada después de `fecha`."""
    return Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha)


def bloques_vigentes(profesora, fecha=None):
    """Bloques del horario semanal que rigen en una fecha (hoy por defecto)."""
    fecha = fecha or hoy()
    return BloqueHorarioProfesora.objects.filter(
        profesora=profesora,
        vigente_desde__lte=fecha,
    ).filter(
        vigente_en(fecha)
    ).order_by('hora_inicio')


def horario_semanal(profesora, fecha=None):
    """
    Horario semanal vigente agrupado por día.

    Devuelve una lista de dicts ordenada de lunes a sábado, con los bloques de
    cada día y el total de horas de ese día.
    """
    fecha = fecha or hoy()
    bloques = list(bloques_vigentes(profesora, fecha))

    dias = []
    for nombre in DIAS_INDICE[:6]:
        del_dia = [b for b in bloques if b.dia == nombre]
        del_dia.sort(key=lambda b: b.hora_inicio)
        dias.append({
            'dia': nombre,
            'bloques': del_dia,
            'horas': sum((b.duracion_horas for b in del_dia), CERO),
        })
    return dias


def horas_semanales(profesora, fecha=None):
    """Total de horas que la profesora tiene asignadas por semana."""
    return sum((d['horas'] for d in horario_semanal(profesora, fecha)), CERO)


def valor_hora_vigente(profesora, fecha=None):
    """Registro de valor hora vigente en una fecha, o None si no tiene."""
    fecha = fecha or hoy()
    return ValorHoraProfesora.objects.filter(
        profesora=profesora,
        vigente_desde__lte=fecha,
    ).filter(
        vigente_en(fecha)
    ).order_by('-vigente_desde').first()


# ==============================================================================
# TURNOS Y RESÚMENES
# ==============================================================================

def _turno_desde_bloque(bloque):
    return {
        'hora_inicio': bloque.hora_inicio,
        'hora_fin': bloque.hora_fin,
        'sede': bloque.sede,
        'sede_display': nombre_sede(bloque.sede),
        'horas': bloque.duracion_horas,
        'origen': 'habitual',
        'motivo': '',
        'bloque_id': bloque.id,
        'ajuste_id': None,
        'clase': bloque.clase,
    }


def _turno_desde_ajuste(ajuste, origen):
    return {
        'hora_inicio': ajuste.hora_inicio,
        'hora_fin': ajuste.hora_fin,
        'sede': ajuste.sede,
        'sede_display': nombre_sede(ajuste.sede),
        'horas': ajuste.duracion_horas,
        'origen': origen,
        'motivo': ajuste.motivo,
        'bloque_id': ajuste.bloque_id,
        'ajuste_id': ajuste.id,
        'clase': ajuste.clase,
    }


def _turnos_de_fecha(fecha, bloques, ajustes_de_la_fecha):
    """
    Turnos efectivamente trabajados en una fecha.

    Se parte del horario habitual de ese día de la semana y se le aplican los
    cambios cargados para esa fecha:

    - "no trabajó" saca un turno puntual (si apunta a uno) o el día entero;
    - "otro horario" cambia el horario de un turno puntual (o, en los cambios
      viejos que no apuntan a ninguno, el del día entero);
    - los turnos sueltos se suman.
    """
    ajustes = ajustes_de_la_fecha or []
    dia = nombre_dia(fecha)

    habituales = [b for b in bloques if b.dia == dia and b.rige_en(fecha)]

    ausencias = [a for a in ajustes if a.tipo == 'ausencia']
    reemplazos = [a for a in ajustes if a.tipo == 'reemplazo']

    # Un cambio sin turno asociado vale para todo el día (así se cargaban antes).
    if any(a.bloque_id is None for a in ausencias):
        habituales = []
    generales = [a for a in reemplazos if a.bloque_id is None]
    if generales:
        turnos = [_turno_desde_ajuste(a, 'reemplazo') for a in generales]
        habituales = []
    else:
        turnos = []

    sin_trabajar = {a.bloque_id for a in ausencias if a.bloque_id is not None}
    cambiados = {a.bloque_id: a for a in reemplazos if a.bloque_id is not None}

    for bloque in habituales:
        if bloque.id in sin_trabajar:
            continue
        if bloque.id in cambiados:
            turnos.append(_turno_desde_ajuste(cambiados[bloque.id], 'reemplazo'))
        else:
            turnos.append(_turno_desde_bloque(bloque))

    for ajuste in ajustes:
        if ajuste.tipo == 'extra':
            turnos.append(_turno_desde_ajuste(ajuste, 'extra'))

    turnos.sort(key=lambda t: t['hora_inicio'])
    return turnos


def _valor_para(fecha, valores):
    """Valor hora vigente en una fecha, tomado de una lista ya cargada."""
    for valor in valores:
        if valor.rige_en(fecha):
            return valor.valor_hora
    return None


def resumen_profesora(profesora, desde, hasta, incluir_dias_sin_horas=False):
    """
    Horas y costo de una profesora entre dos fechas (ambas incluidas).

    Devuelve un dict con:
      - `horas` y `monto` totales del período
      - `dias`: detalle por fecha con sus turnos, horas y monto
      - `semanas`: subtotales por semana (de lunes a domingo)
      - `por_sede`: subtotales por sede
      - `sin_valor_hora`: True si hubo días trabajados sin valor hora cargado
    """
    bloques = list(
        BloqueHorarioProfesora.objects.filter(
            profesora=profesora,
            vigente_desde__lte=hasta,
        ).filter(vigente_en(desde)).select_related('clase')
    )

    ajustes_por_fecha = {}
    ajustes = AjusteHorarioProfesora.objects.filter(
        profesora=profesora,
        fecha__gte=desde,
        fecha__lte=hasta,
    ).select_related('clase', 'bloque').order_by('hora_inicio')
    for ajuste in ajustes:
        ajustes_por_fecha.setdefault(ajuste.fecha, []).append(ajuste)

    valores = list(
        ValorHoraProfesora.objects.filter(
            profesora=profesora,
            vigente_desde__lte=hasta,
        ).filter(vigente_en(desde)).order_by('-vigente_desde')
    )

    dias = []
    semanas = {}
    por_sede = {}
    total_horas = CERO
    total_monto = CERO
    sin_valor_hora = False

    for fecha in iterar_fechas(desde, hasta):
        turnos = _turnos_de_fecha(fecha, bloques, ajustes_por_fecha.get(fecha))
        horas_dia = sum((t['horas'] for t in turnos), CERO)

        valor = _valor_para(fecha, valores)
        if horas_dia and valor is None:
            sin_valor_hora = True
        monto_dia = (horas_dia * (valor or CERO)).quantize(Decimal('0.01'))

        ajustes_del_dia = ajustes_por_fecha.get(fecha, [])

        if turnos or ajustes_del_dia or incluir_dias_sin_horas:
            dias.append({
                'fecha': fecha,
                'dia': nombre_dia(fecha),
                'turnos': turnos,
                'horas': horas_dia,
                'valor_hora': valor,
                'monto': monto_dia,
                'ajustes': ajustes_del_dia,
            })

        for turno in turnos:
            sede = turno['sede'] or 'sin_sede'
            acumulado = por_sede.setdefault(sede, {
                'sede': sede,
                'nombre': nombre_sede(turno['sede']),
                'horas': CERO,
                'monto': CERO,
            })
            acumulado['horas'] += turno['horas']
            acumulado['monto'] += (turno['horas'] * (valor or CERO)).quantize(Decimal('0.01'))

        if horas_dia:
            inicio_semana, fin_semana = rango_semana(fecha)
            semana = semanas.setdefault(inicio_semana, {
                'desde': inicio_semana,
                'hasta': fin_semana,
                'horas': CERO,
                'monto': CERO,
            })
            semana['horas'] += horas_dia
            semana['monto'] += monto_dia

        total_horas += horas_dia
        total_monto += monto_dia

    return {
        'profesora': profesora,
        'desde': desde,
        'hasta': hasta,
        'horas': total_horas,
        'monto': total_monto,
        'dias': dias,
        'semanas': [semanas[clave] for clave in sorted(semanas)],
        'por_sede': [por_sede[clave] for clave in sorted(por_sede)],
        'sin_valor_hora': sin_valor_hora,
        'valor_hora_actual': _valor_para(hasta, valores),
    }


def resumen_general(desde, hasta, profesoras=None):
    """
    Resumen de todas las profesoras para un período.

    Devuelve la lista de resúmenes individuales y los totales del estudio.
    """
    profesoras = profesoras if profesoras is not None else profesoras_activas()

    resumenes = [resumen_profesora(p, desde, hasta) for p in profesoras]

    return {
        'desde': desde,
        'hasta': hasta,
        'resumenes': resumenes,
        'total_horas': sum((r['horas'] for r in resumenes), CERO),
        'total_monto': sum((r['monto'] for r in resumenes), CERO),
        'alguna_sin_valor_hora': any(r['sin_valor_hora'] for r in resumenes),
    }


def liquidacion_del_mes(profesora, primer_dia_mes):
    """Liquidación registrada de un mes, o None si todavía no se pagó."""
    return LiquidacionProfesora.objects.filter(
        profesora=profesora,
        mes_año=primer_dia_mes,
    ).select_related('registrado_por').first()
