"""
Vistas de horarios y liquidación de profesoras.

Superadministradores (Nico y Cami): cargan el horario semanal y el valor hora de
cada profesora, ven las horas trabajadas por día, semana o mes, cuánto sale cada
una y el total del estudio, y registran el pago mensual.

Profesoras (administradoras contratadas): ven su horario y las horas que fueron
haciendo en el mes, junto con lo que les corresponde cobrar.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import horarios as h
from .models import (
    AjusteHorarioProfesora,
    BloqueHorarioProfesora,
    Clase,
    LiquidacionProfesora,
    ValorHoraProfesora,
)
from .views import fmt_pesos, superadmin_required

MESES_HISTORIAL = 6


# ==============================================================================
# UTILIDADES
# ==============================================================================

def profesora_required(view_func):
    """
    Requiere ser administradora contratada (staff que no es superusuario).

    Los superadministradores tienen su propia pantalla, así que se los manda ahí.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debes iniciar sesión para ver tus horarios.')
            return redirect('accounts:login')

        if request.user.is_superuser:
            return redirect('gravity:admin_profesoras_lista')

        if not request.user.is_staff:
            messages.error(request, 'No tenés permisos para acceder a esta sección.')
            return redirect('gravity:home')

        return view_func(request, *args, **kwargs)

    return wrapper


def _get_profesora(profesora_id):
    """Busca una profesora (staff no superusuario), activa o no."""
    return get_object_or_404(
        User,
        id=profesora_id,
        is_staff=True,
        is_superuser=False,
    )


def _fecha_get(request, clave, por_defecto):
    """Lee una fecha ISO del querystring, con valor por defecto."""
    valor = request.GET.get(clave, '')
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return por_defecto


def _fecha_post(request, clave):
    """Lee una fecha ISO del POST. Devuelve None si falta o es inválida."""
    try:
        return date.fromisoformat(request.POST.get(clave, ''))
    except ValueError:
        return None


def _mes_get(request, clave='mes'):
    """Lee un mes 'YYYY-MM' del querystring. Por defecto, el mes actual."""
    hoy = h.hoy()
    valor = request.GET.get(clave, '')
    try:
        año, mes = valor.split('-')
        return date(int(año), int(mes), 1)
    except (ValueError, AttributeError):
        return date(hoy.year, hoy.month, 1)


def _mes_post(request, clave='mes'):
    try:
        año, mes = request.POST.get(clave, '').split('-')
        return date(int(año), int(mes), 1)
    except (ValueError, AttributeError):
        return None


def _decimal_post(request, clave):
    try:
        return Decimal(request.POST.get(clave, '').replace(',', '.').strip())
    except (InvalidOperation, AttributeError):
        return None


def _mes_anterior(primer_dia):
    return (primer_dia - timedelta(days=1)).replace(day=1)


def _mes_siguiente(primer_dia):
    if primer_dia.month == 12:
        return date(primer_dia.year + 1, 1, 1)
    return date(primer_dia.year, primer_dia.month + 1, 1)


def _rango_del_periodo(request):
    """
    Rango de fechas según el filtro elegido en la pantalla.

    Devuelve (desde, hasta, contexto_del_filtro) para que la plantilla pueda
    volver a dibujar el selector con lo que el usuario eligió.
    """
    hoy = h.hoy()
    periodo = request.GET.get('periodo', 'mes')

    if periodo == 'dia':
        fecha = _fecha_get(request, 'fecha', hoy)
        desde, hasta = h.rango_dia(fecha)
        contexto = {'fecha': fecha, 'mes_seleccionado': date(fecha.year, fecha.month, 1)}

    elif periodo == 'semana':
        fecha = _fecha_get(request, 'fecha', hoy)
        desde, hasta = h.rango_semana(fecha)
        contexto = {'fecha': fecha, 'mes_seleccionado': date(fecha.year, fecha.month, 1)}

    elif periodo == 'personalizado':
        desde = _fecha_get(request, 'desde', hoy.replace(day=1))
        hasta = _fecha_get(request, 'hasta', hoy)
        if hasta < desde:
            desde, hasta = hasta, desde
        contexto = {'fecha': desde, 'mes_seleccionado': date(desde.year, desde.month, 1)}

    else:
        periodo = 'mes'
        primer_dia = _mes_get(request)
        desde, hasta = h.rango_mes(primer_dia.year, primer_dia.month)
        contexto = {'fecha': hoy, 'mes_seleccionado': primer_dia}

    contexto.update({
        'periodo': periodo,
        'desde': desde,
        'hasta': hasta,
        'es_mes_completo': periodo == 'mes',
    })
    return desde, hasta, contexto


def _historial_meses(profesora, hasta_mes, cantidad=MESES_HISTORIAL):
    """Horas, monto y estado de pago de los últimos meses de una profesora."""
    historial = []
    mes = hasta_mes
    for _ in range(cantidad):
        desde, hasta = h.rango_mes(mes.year, mes.month)
        resumen = h.resumen_profesora(profesora, desde, hasta)
        historial.append({
            'mes': mes,
            'horas': resumen['horas'],
            'monto': resumen['monto'],
            'liquidacion': h.liquidacion_del_mes(profesora, mes),
        })
        mes = _mes_anterior(mes)
    return historial


# ==============================================================================
# PANTALLAS DE SUPERADMINISTRADOR
# ==============================================================================

@superadmin_required
def admin_profesoras_lista(request):
    """
    Listado de profesoras con las horas trabajadas y el costo del período.

    El período se elige arriba: un día puntual, una semana, un mes completo o un
    rango personalizado.
    """
    desde, hasta, filtro = _rango_del_periodo(request)

    profesoras = list(h.profesoras_activas())
    general = h.resumen_general(desde, hasta, profesoras)

    filas = []
    for resumen in general['resumenes']:
        profesora = resumen['profesora']
        liquidacion = None
        if filtro['es_mes_completo']:
            liquidacion = h.liquidacion_del_mes(profesora, filtro['mes_seleccionado'])

        filas.append({
            'profesora': profesora,
            'horas': resumen['horas'],
            'monto': resumen['monto'],
            'valor_hora': resumen['valor_hora_actual'],
            'sin_valor_hora': resumen['sin_valor_hora'],
            'horas_semanales': h.horas_semanales(profesora),
            'liquidacion': liquidacion,
        })

    context = {
        'filas': filas,
        'total_horas': general['total_horas'],
        'total_monto': general['total_monto'],
        'alguna_sin_valor_hora': general['alguna_sin_valor_hora'],
        'cantidad_profesoras': len(profesoras),
        'hoy': h.hoy(),
        **filtro,
    }
    return render(request, 'gravity/admin/profesoras_lista.html', context)


@superadmin_required
def admin_profesora_detalle(request, profesora_id):
    """
    Ficha de una profesora: horario semanal, valor hora, horas del mes y pagos.
    """
    profesora = _get_profesora(profesora_id)
    hoy = h.hoy()

    mes_seleccionado = _mes_get(request)
    desde_mes, hasta_mes = h.rango_mes(mes_seleccionado.year, mes_seleccionado.month)

    resumen_mes = h.resumen_profesora(profesora, desde_mes, hasta_mes)

    desde_semana, hasta_semana = h.rango_semana(hoy)
    resumen_semana = h.resumen_profesora(profesora, desde_semana, hasta_semana)
    resumen_hoy = h.resumen_profesora(profesora, hoy, hoy)

    valor_actual = h.valor_hora_vigente(profesora)

    context = {
        'profesora': profesora,
        'hoy': hoy,
        'mes_seleccionado': mes_seleccionado,
        'mes_anterior': _mes_anterior(mes_seleccionado),
        'mes_siguiente': _mes_siguiente(mes_seleccionado),
        'hay_mes_siguiente': _mes_siguiente(mes_seleccionado) <= date(hoy.year, hoy.month, 1),

        'horario_semanal': h.horario_semanal(profesora),
        'horas_semanales': h.horas_semanales(profesora),
        'bloques_historicos': BloqueHorarioProfesora.objects.filter(
            profesora=profesora,
            vigente_hasta__isnull=False,
        ).order_by('-vigente_hasta', 'dia'),

        'valor_actual': valor_actual,
        'historial_valores': ValorHoraProfesora.objects.filter(
            profesora=profesora
        ).select_related('registrado_por').order_by('-vigente_desde'),

        'resumen_mes': resumen_mes,
        'resumen_semana': resumen_semana,
        'resumen_hoy': resumen_hoy,
        'desde_semana': desde_semana,
        'hasta_semana': hasta_semana,

        'ajustes_mes': AjusteHorarioProfesora.objects.filter(
            profesora=profesora,
            fecha__gte=desde_mes,
            fecha__lte=hasta_mes,
        ).select_related('registrado_por').order_by('-fecha'),

        'liquidacion': h.liquidacion_del_mes(profesora, mes_seleccionado),
        'historial_meses': _historial_meses(profesora, _mes_anterior(mes_seleccionado)),

        'sedes': Clase.DIRECCIONES,
        'dias_semana': h.DIAS_INDICE[:6],
        'tipos_ajuste': AjusteHorarioProfesora.TIPOS_AJUSTE,
    }
    return render(request, 'gravity/admin/profesora_detalle.html', context)


@superadmin_required
def admin_profesora_horario_agregar(request, profesora_id):
    """Agrega un bloque al horario semanal de una profesora."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    dia = request.POST.get('dia', '')
    hora_inicio = request.POST.get('hora_inicio', '')
    hora_fin = request.POST.get('hora_fin', '')
    sede = request.POST.get('sede', '')
    vigente_desde = _fecha_post(request, 'vigente_desde') or h.hoy()

    bloque = BloqueHorarioProfesora(
        profesora=profesora,
        dia=dia,
        hora_inicio=hora_inicio or None,
        hora_fin=hora_fin or None,
        sede=sede,
        vigente_desde=vigente_desde,
        creado_por=request.user,
    )

    try:
        bloque.full_clean()
    except Exception as error:
        mensajes = getattr(error, 'messages', None) or [str(error)]
        messages.error(request, f'No se pudo agregar el horario: {" ".join(mensajes)}')
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    solapado = _buscar_solapamiento(bloque)
    if solapado:
        messages.error(
            request,
            f'Ese horario se superpone con el bloque de {solapado.dia} de '
            f'{solapado.hora_inicio:%H:%M} a {solapado.hora_fin:%H:%M} que ya tiene cargado.'
        )
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    bloque.save()
    messages.success(
        request,
        f'Horario agregado: {dia} de {bloque.hora_inicio:%H:%M} a {bloque.hora_fin:%H:%M}, '
        f'a partir del {vigente_desde:%d/%m/%Y}.'
    )
    return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)


def _buscar_solapamiento(bloque):
    """
    Devuelve el bloque vigente que se pisa con el que se quiere guardar.

    Se comparan solo los bloques del mismo día cuya vigencia se cruza con la del
    bloque nuevo.
    """
    candidatos = BloqueHorarioProfesora.objects.filter(
        profesora=bloque.profesora,
        dia=bloque.dia,
    ).filter(h.vigente_en(bloque.vigente_desde))

    if bloque.pk:
        candidatos = candidatos.exclude(pk=bloque.pk)

    for otro in candidatos:
        if bloque.hora_inicio < otro.hora_fin and otro.hora_inicio < bloque.hora_fin:
            return otro
    return None


@superadmin_required
def admin_profesora_horario_eliminar(request, profesora_id, bloque_id):
    """
    Da de baja un bloque del horario semanal.

    Si el bloque ya rigió se lo cierra con fecha, para no alterar los meses
    anteriores. Si nunca llegó a regir, se borra.
    """
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    bloque = get_object_or_404(BloqueHorarioProfesora, id=bloque_id, profesora=profesora)
    ultimo_dia = _fecha_post(request, 'ultimo_dia') or h.hoy()

    if ultimo_dia < bloque.vigente_desde:
        bloque.delete()
        messages.success(request, 'Horario eliminado. Todavía no había empezado a regir.')
    else:
        bloque.vigente_hasta = ultimo_dia
        bloque.save(update_fields=['vigente_hasta'])
        messages.success(
            request,
            f'Horario dado de baja. Rigió hasta el {ultimo_dia:%d/%m/%Y} inclusive.'
        )

    return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)


@superadmin_required
def admin_profesora_valor_hora(request, profesora_id):
    """
    Carga un nuevo valor hora y cierra el anterior el día previo.

    De esta forma los meses ya trabajados se siguen calculando con el valor que
    regía en ese momento.
    """
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    valor = _decimal_post(request, 'valor_hora')
    vigente_desde = _fecha_post(request, 'vigente_desde') or h.hoy()
    observaciones = request.POST.get('observaciones', '').strip()

    if valor is None or valor <= 0:
        messages.error(request, 'Ingresá un valor por hora válido, mayor a cero.')
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    with transaction.atomic():
        existente = ValorHoraProfesora.objects.filter(
            profesora=profesora,
            vigente_desde=vigente_desde,
        ).first()

        if existente:
            existente.valor_hora = valor
            existente.observaciones = observaciones
            existente.registrado_por = request.user
            existente.save()
            messages.success(
                request,
                f'Valor hora actualizado a ${fmt_pesos(valor)} desde el {vigente_desde:%d/%m/%Y}.'
            )
        else:
            anteriores = ValorHoraProfesora.objects.filter(
                profesora=profesora,
                vigente_desde__lt=vigente_desde,
            ).filter(h.vigente_en(vigente_desde))

            for anterior in anteriores:
                anterior.vigente_hasta = vigente_desde - timedelta(days=1)
                anterior.save(update_fields=['vigente_hasta'])

            ValorHoraProfesora.objects.create(
                profesora=profesora,
                valor_hora=valor,
                vigente_desde=vigente_desde,
                observaciones=observaciones,
                registrado_por=request.user,
            )
            messages.success(
                request,
                f'Nuevo valor hora: ${fmt_pesos(valor)} a partir del {vigente_desde:%d/%m/%Y}.'
            )

    return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)


@superadmin_required
def admin_profesora_ajuste_crear(request, profesora_id):
    """Carga un ajuste puntual: turno extra, horario distinto o día no trabajado."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    fecha = _fecha_post(request, 'fecha')
    tipo = request.POST.get('tipo', '')

    if not fecha:
        messages.error(request, 'Indicá la fecha del ajuste.')
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    ajuste = AjusteHorarioProfesora(
        profesora=profesora,
        fecha=fecha,
        tipo=tipo,
        hora_inicio=request.POST.get('hora_inicio') or None,
        hora_fin=request.POST.get('hora_fin') or None,
        sede=request.POST.get('sede', '') if tipo != 'ausencia' else '',
        motivo=request.POST.get('motivo', '').strip(),
        registrado_por=request.user,
    )

    try:
        ajuste.full_clean()
    except Exception as error:
        mensajes = getattr(error, 'messages', None) or [str(error)]
        messages.error(request, f'No se pudo cargar el ajuste: {" ".join(mensajes)}')
        return redirect(_url_detalle(profesora, fecha))

    ajuste.save()
    messages.success(
        request,
        f'Ajuste cargado para el {fecha:%d/%m/%Y}: {ajuste.get_tipo_display().lower()}.'
    )
    return redirect(_url_detalle(profesora, fecha))


def _url_detalle(profesora, fecha=None):
    """URL del detalle de la profesora, opcionalmente en el mes de una fecha."""
    url = reverse('gravity:admin_profesora_detalle', kwargs={'profesora_id': profesora.id})
    if fecha:
        return f"{url}?mes={fecha:%Y-%m}"
    return url


@superadmin_required
def admin_profesora_ajuste_eliminar(request, profesora_id, ajuste_id):
    """Borra un ajuste puntual y vuelve a valer el horario habitual de ese día."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    ajuste = get_object_or_404(AjusteHorarioProfesora, id=ajuste_id, profesora=profesora)
    fecha = ajuste.fecha
    ajuste.delete()

    messages.success(request, f'Ajuste del {fecha:%d/%m/%Y} eliminado.')
    return redirect(_url_detalle(profesora, fecha))


@superadmin_required
def admin_profesora_liquidar(request, profesora_id):
    """Registra el pago del mes a una profesora."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    mes = _mes_post(request, 'mes')
    if not mes:
        messages.error(request, 'No se pudo identificar el mes a liquidar.')
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    if LiquidacionProfesora.objects.filter(profesora=profesora, mes_año=mes).exists():
        messages.error(request, 'Ese mes ya figura como pagado.')
        return redirect(_url_detalle(profesora, mes))

    desde, hasta = h.rango_mes(mes.year, mes.month)
    resumen = h.resumen_profesora(profesora, desde, hasta)

    monto_pagado = _decimal_post(request, 'monto_pagado')
    if monto_pagado is None:
        monto_pagado = resumen['monto']

    fecha_pago = _fecha_post(request, 'fecha_pago') or h.hoy()

    liquidacion = LiquidacionProfesora(
        profesora=profesora,
        mes_año=mes,
        horas_liquidadas=resumen['horas'],
        monto_calculado=resumen['monto'],
        monto_pagado=monto_pagado,
        fecha_pago=fecha_pago,
        observaciones=request.POST.get('observaciones', '').strip(),
        registrado_por=request.user,
    )

    try:
        liquidacion.full_clean()
        liquidacion.save()
    except Exception as error:
        mensajes = getattr(error, 'messages', None) or [str(error)]
        messages.error(request, f'No se pudo registrar el pago: {" ".join(mensajes)}')
        return redirect(_url_detalle(profesora, mes))

    messages.success(
        request,
        f'Pago registrado: {resumen["horas"]} horas de {mes:%m/%Y} por ${fmt_pesos(monto_pagado)}.'
    )
    return redirect(_url_detalle(profesora, mes))


@superadmin_required
def admin_profesora_liquidacion_anular(request, profesora_id, liquidacion_id):
    """Deja el mes otra vez como pendiente de pago."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect('gravity:admin_profesora_detalle', profesora_id=profesora.id)

    liquidacion = get_object_or_404(
        LiquidacionProfesora, id=liquidacion_id, profesora=profesora
    )
    mes = liquidacion.mes_año
    liquidacion.delete()

    messages.success(request, f'El pago de {mes:%m/%Y} se eliminó. El mes queda pendiente.')
    return redirect(_url_detalle(profesora, mes))


# ==============================================================================
# PANTALLA DE LA PROFESORA
# ==============================================================================

@profesora_required
def mis_horarios(request):
    """
    Horario y horas trabajadas de la profesora que está logueada.

    Ve su horario semanal, la semana en curso, el detalle del mes con las horas
    de cada día y el monto que le corresponde, y el historial de meses anteriores.
    """
    profesora = request.user
    hoy = h.hoy()

    mes_seleccionado = _mes_get(request)
    desde_mes, hasta_mes = h.rango_mes(mes_seleccionado.year, mes_seleccionado.month)
    resumen_mes = h.resumen_profesora(profesora, desde_mes, hasta_mes)

    desde_semana, hasta_semana = h.rango_semana(hoy)
    resumen_semana = h.resumen_profesora(profesora, desde_semana, hasta_semana)

    context = {
        'profesora': profesora,
        'hoy': hoy,
        'mes_seleccionado': mes_seleccionado,
        'mes_anterior': _mes_anterior(mes_seleccionado),
        'mes_siguiente': _mes_siguiente(mes_seleccionado),
        'hay_mes_siguiente': _mes_siguiente(mes_seleccionado) <= date(hoy.year, hoy.month, 1),

        'horario_semanal': h.horario_semanal(profesora),
        'horas_semanales': h.horas_semanales(profesora),
        'valor_actual': h.valor_hora_vigente(profesora),

        'resumen_mes': resumen_mes,
        'resumen_semana': resumen_semana,
        'resumen_hoy': h.resumen_profesora(profesora, hoy, hoy),
        'desde_semana': desde_semana,
        'hasta_semana': hasta_semana,

        'liquidacion': h.liquidacion_del_mes(profesora, mes_seleccionado),
        'historial_meses': _historial_meses(profesora, _mes_anterior(mes_seleccionado)),
    }
    return render(request, 'gravity/admin/mis_horarios.html', context)
