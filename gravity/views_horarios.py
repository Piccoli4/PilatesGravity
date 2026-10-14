"""
Equipo del estudio: quiénes son, su acceso al panel, sus horarios, horas y pagos.

Superadministradores (Nico y Cami): ven al equipo con las horas y el costo del
período, suman o quitan personas, cargan el horario semanal y el valor hora de cada
una, corrigen días puntuales y registran el pago mensual.

Profesoras (equipo): en "Mis horarios" ven su horario y las horas que fueron
haciendo en el mes, con lo que les corresponde cobrar.

El mes en curso se muestra "hasta hoy" (lo trabajado) y "a fin de mes" (proyección);
el pago de un mes se registra desde su último día. Los cálculos están en
gravity/horarios.py y las altas y bajas del equipo en gravity/equipo_admin.py.
"""

from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.invitacion import enviar_invitacion, tiene_invitacion_pendiente
from accounts.models import UserProfile

from . import horarios as h
from .equipo_admin import alumnas_para_sumar, crear_integrante, devolver_acceso, quitar_acceso, sumar_alumna
from .forms import IntegranteDatosForm, IntegranteNuevoForm
from .hoy import MESES, fecha_larga
from .models import (
    AjusteHorarioProfesora,
    BloqueHorarioProfesora,
    Clase,
    LiquidacionProfesora,
    PlanUsuario,
    ValorHoraProfesora,
)
from .views import fmt_pesos, superadmin_required

MESES_HISTORIAL = 6
VISTAS_FICHA = ('horas', 'horario', 'acceso')


# ==============================================================================
# UTILIDADES
# ==============================================================================

def profesora_required(view_func):
    """
    Requiere ser del equipo (staff que no es superusuario).

    Los superadministradores tienen su propia pantalla, así que se los manda ahí.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Iniciá sesión para ver tus horarios.')
            return redirect('accounts:login')

        if request.user.is_superuser:
            return redirect('gravity:admin_profesoras_lista')

        if not request.user.is_staff:
            messages.error(request, 'No tenés permisos para acceder a esta sección.')
            return redirect('gravity:home')

        return view_func(request, *args, **kwargs)

    return wrapper


def _get_profesora(profesora_id):
    """Alguien del equipo (con o sin acceso), nunca un superadmin ni un alumno común."""
    usuario = get_object_or_404(User.objects.select_related('profile'), id=profesora_id, is_superuser=False)
    if not usuario.is_staff and not h.integrantes_equipo('sin_acceso').filter(id=usuario.id).exists():
        raise Http404('No es del equipo')
    return usuario


def _fecha_get(request, clave, por_defecto):
    try:
        return date.fromisoformat(request.GET.get(clave, ''))
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
    try:
        año, mes = request.GET.get(clave, '').split('-')
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


def _hora_post(request, clave):
    try:
        return time.fromisoformat(request.POST.get(clave, ''))
    except ValueError:
        return None


def _mes_anterior(primer_dia):
    return (primer_dia - timedelta(days=1)).replace(day=1)


def _mes_siguiente(primer_dia):
    if primer_dia.month == 12:
        return date(primer_dia.year + 1, 1, 1)
    return date(primer_dia.year, primer_dia.month + 1, 1)


def nombre_mes(primer_dia):
    return f'{MESES[primer_dia.month - 1]} {primer_dia.year}'


def _url_detalle(profesora, fecha=None, ver=None):
    """Ficha de la profesora, en una pestaña y (para las horas) en el mes de una fecha."""
    url = reverse('gravity:admin_profesora_detalle', kwargs={'profesora_id': profesora.id})
    params = []
    if ver:
        params.append(f'ver={ver}')
    if fecha:
        params.append(f'mes={fecha:%Y-%m}')
    return f'{url}?{"&".join(params)}' if params else url


def _avisar_mes_pagado(request, profesora, desde, hasta=None):
    """Si un cambio toca un mes ya pagado, avisarlo (en ese mes se ve la diferencia)."""
    pagado = h.mes_pagado_desde(profesora, desde, hasta)
    if pagado:
        messages.warning(
            request,
            f'Ojo: el cambio toca {nombre_mes(pagado.mes_año)}, que ya está pagado. '
            f'En ese mes vas a ver la diferencia con lo que se pagó.'
        )


def _rango_del_periodo(request):
    """
    Rango de fechas según el período elegido (día, semana, mes o rango), con los
    enlaces para ir al anterior y al siguiente.
    """
    hoy = h.hoy()
    periodo = request.GET.get('periodo', 'mes')
    anterior = siguiente = ''

    if periodo == 'dia':
        fecha = _fecha_get(request, 'fecha', hoy)
        desde, hasta = h.rango_dia(fecha)
        titulo = fecha_larga(fecha)
        anterior = f'?periodo=dia&fecha={fecha - timedelta(days=1):%Y-%m-%d}'
        siguiente = f'?periodo=dia&fecha={fecha + timedelta(days=1):%Y-%m-%d}'
        mes = date(fecha.year, fecha.month, 1)

    elif periodo == 'semana':
        fecha = _fecha_get(request, 'fecha', hoy)
        desde, hasta = h.rango_semana(fecha)
        titulo = f'Semana del {desde:%d/%m} al {hasta:%d/%m}'
        anterior = f'?periodo=semana&fecha={desde - timedelta(days=7):%Y-%m-%d}'
        siguiente = f'?periodo=semana&fecha={desde + timedelta(days=7):%Y-%m-%d}'
        mes = date(fecha.year, fecha.month, 1)

    elif periodo == 'personalizado':
        desde = _fecha_get(request, 'desde', hoy.replace(day=1))
        hasta = _fecha_get(request, 'hasta', hoy)
        if hasta < desde:
            desde, hasta = hasta, desde
        titulo = f'Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'
        mes = date(desde.year, desde.month, 1)

    else:
        periodo = 'mes'
        mes = _mes_get(request)
        desde, hasta = h.rango_mes(mes.year, mes.month)
        titulo = nombre_mes(mes).capitalize()
        anterior = f'?periodo=mes&mes={_mes_anterior(mes):%Y-%m}'
        siguiente = f'?periodo=mes&mes={_mes_siguiente(mes):%Y-%m}'

    return desde, hasta, {
        'periodo': periodo,
        'desde': desde,
        'hasta': hasta,
        'titulo_periodo': titulo,
        'anterior': anterior,
        'siguiente': siguiente,
        'mes_seleccionado': mes,
        'es_mes_completo': periodo == 'mes',
    }


def _historial_meses(profesora, hasta_mes, cantidad=MESES_HISTORIAL):
    """Horas, monto y estado de pago de los meses anteriores de una profesora."""
    historial = []
    mes = hasta_mes
    for _ in range(cantidad):
        desde, hasta = h.rango_mes(mes.year, mes.month)
        resumen = h.resumen_profesora(profesora, desde, hasta)
        liquidacion = h.liquidacion_del_mes(profesora, mes)
        if resumen['horas'] or liquidacion:
            historial.append({
                'mes': mes,
                'titulo': nombre_mes(mes).capitalize(),
                'horas': resumen['horas'],
                'monto': resumen['monto'],
                'liquidacion': liquidacion,
            })
        mes = _mes_anterior(mes)
    return historial


def _datos_horas(profesora, request):
    """Horas y pago de un mes (la pestaña de la ficha y Mis horarios)."""
    hoy = h.hoy()
    mes = _mes_get(request)
    desde, hasta = h.rango_mes(mes.year, mes.month)
    resumen = h.resumen_hasta_hoy(profesora, desde, hasta, hoy)
    for dia in resumen['dias']:
        dia['futuro'] = dia['fecha'] > hoy
        dia['es_hoy'] = dia['fecha'] == hoy
    liquidacion = h.liquidacion_del_mes(profesora, mes)
    mes_actual = date(hoy.year, hoy.month, 1)
    return {
        'mes_seleccionado': mes,
        'mes_titulo': nombre_mes(mes).capitalize(),
        'mes_anterior': _mes_anterior(mes),
        'mes_siguiente': _mes_siguiente(mes),
        'hay_mes_siguiente': _mes_siguiente(mes) <= _mes_siguiente(mes_actual),
        'mes_futuro': desde > hoy,
        'resumen': resumen,
        'liquidacion': liquidacion,
        'diferencia': h.diferencia_liquidacion(liquidacion),
        'puede_liquidar': not liquidacion and h.mes_terminado(mes, hoy) and resumen['horas'] > 0,
        'ultimo_dia': hasta,
        'valor_actual': h.valor_hora_vigente(profesora),
        'historial_meses': _historial_meses(profesora, _mes_anterior(mes)),
    }


def _datos_horario(profesora):
    """Horario semanal (con avisos si un turno ya no coincide con su clase) y valor hora."""
    semana = h.horario_semanal(profesora)
    for dia in semana:
        for bloque in dia['bloques']:
            bloque.aviso = ''
            clase = bloque.clase
            if clase:
                if not clase.activa:
                    bloque.aviso = 'La clase está en pausa'
                elif (clase.dia, clase.horario, clase.direccion) != (bloque.dia, bloque.hora_inicio, bloque.sede):
                    bloque.aviso = (f'La clase ahora es los {clase.dia.lower()} a las '
                                    f'{clase.horario:%H:%M} ({clase.get_direccion_corta()})')
    return {
        'horario_semanal': semana,
        'horas_semanales': h.horas_semanales(profesora),
        'bloques_historicos': BloqueHorarioProfesora.objects.filter(
            profesora=profesora, vigente_hasta__isnull=False,
        ).select_related('clase').order_by('-vigente_hasta', 'dia'),
        'valor_actual': h.valor_hora_vigente(profesora),
        'historial_valores': ValorHoraProfesora.objects.filter(
            profesora=profesora,
        ).select_related('registrado_por').order_by('-vigente_desde'),
        'clases': h.clases_disponibles(),
        'dias_semana': h.DIAS_INDICE[:6],
    }


def _datos_acceso(profesora, request, form=None):
    return {
        'form_datos': form or IntegranteDatosForm(usuario=profesora),
        'invitacion_pendiente': tiene_invitacion_pendiente(profesora) and profesora.is_staff,
        'turnos_abiertos': h.bloques_vigentes(profesora).count(),
        'tiene_plan': PlanUsuario.objects.filter(usuario=profesora, activo=True).exists(),
        'reservas_activas': profesora.reservas_pilates.filter(activa=True).count(),
        'clave_inicial': request.session.pop(f'clave_inicial_{profesora.id}', None),
    }


# ==============================================================================
# EQUIPO (SUPERADMIN)
# ==============================================================================

@superadmin_required
def admin_profesoras_lista(request):
    """
    Equipo: las personas con acceso al panel con las horas y el costo del período
    (hasta hoy y proyectado), el pago del mes y el estado de su acceso. Quienes ya no
    tienen acceso aparecen si trabajaron en el período, o todos con "Sin acceso".
    """
    desde, hasta, filtro = _rango_del_periodo(request)
    hoy = h.hoy()
    ver_sin_acceso = request.GET.get('estado') == 'sin_acceso'

    sin_acceso = list(h.integrantes_equipo('sin_acceso'))
    personas = sin_acceso if ver_sin_acceso else list(h.integrantes_equipo('con_acceso')) + sin_acceso

    filas = []
    for persona in personas:
        resumen = h.resumen_hasta_hoy(persona, desde, hasta, hoy)
        estado = h.estado_acceso(persona)
        con_acceso = estado[0] in ('activo', 'invitacion')
        liquidacion = h.liquidacion_del_mes(persona, filtro['mes_seleccionado']) if filtro['es_mes_completo'] else None
        if not ver_sin_acceso and not con_acceso and not (resumen['proyeccion_horas'] or liquidacion):
            continue

        pago = None
        if filtro['es_mes_completo']:
            if liquidacion:
                pago = (f'Pagado el {liquidacion.fecha_pago:%d/%m}', 'ok')
            elif desde > hoy:
                pago = None
            elif resumen['en_curso']:
                pago = ('Mes en curso', 'muted') if resumen['proyeccion_horas'] else None
            elif resumen['horas']:
                pago = ('Falta pagar', 'warn')

        filas.append({
            'persona': persona,
            'estado': estado,
            'con_acceso': con_acceso,
            'horas': resumen['horas'],
            'monto': resumen['monto'],
            'proyeccion_horas': resumen['proyeccion_horas'],
            'proyeccion_monto': resumen['proyeccion_monto'],
            'en_curso': resumen['en_curso'],
            'sin_valor_hora': resumen['sin_valor_hora'],
            'valor_hora': h.valor_hora_vigente(persona),
            'horas_semanales': h.horas_semanales(persona),
            'pago': pago,
        })

    context = {
        'filas': filas,
        'ver_sin_acceso': ver_sin_acceso,
        'cantidad_sin_acceso': len(sin_acceso),
        'total_horas': sum((f['horas'] for f in filas), h.CERO),
        'total_monto': sum((f['monto'] for f in filas), h.CERO),
        'total_proyeccion': sum((f['proyeccion_monto'] for f in filas), h.CERO),
        'en_curso': hasta > hoy and desde <= hoy,
        'falta_pagar': sum(1 for f in filas if f['pago'] and f['pago'][1] == 'warn'),
        'alguna_sin_valor_hora': any(f['sin_valor_hora'] for f in filas),
        'superadmins': User.objects.filter(is_superuser=True, is_active=True).order_by('first_name'),
        'hoy': hoy,
        **filtro,
    }
    return render(request, 'gravity/admin/profesoras_lista.html', context)


@superadmin_required
def admin_profesora_detalle(request, profesora_id):
    """Ficha de alguien del equipo, en pestañas: Horas y pago · Horario · Acceso."""
    profesora = _get_profesora(profesora_id)
    ver = request.GET.get('ver', 'horas')
    if ver not in VISTAS_FICHA:
        ver = 'horas'

    context = {
        'profesora': profesora,
        'estado': h.estado_acceso(profesora),
        'ver': ver,
        'hoy': h.hoy(),
        'ayer': h.hoy() - timedelta(days=1),
        'sedes': Clase.DIRECCIONES,
        'meses_pagados': h.meses_pagados(profesora),
    }
    if ver == 'horas':
        context.update(_datos_horas(profesora, request))
        context['clases'] = h.clases_disponibles()
    elif ver == 'horario':
        context.update(_datos_horario(profesora))
    else:
        context.update(_datos_acceso(profesora, request))
    return render(request, 'gravity/admin/profesora_detalle.html', context)


@superadmin_required
def admin_gestionar_admins(request):
    """La gestión de accesos ahora es parte de Equipo."""
    return redirect('gravity:admin_profesoras_lista')


@superadmin_required
def admin_equipo_sumar(request):
    """
    Sumar a alguien al equipo: una persona nueva (con invitación por email) o una
    alumna que ya tiene cuenta.
    """
    buscar = request.GET.get('buscar', '').strip()
    form = IntegranteNuevoForm(request.POST or None) if request.POST.get('modo') != 'alumna' else IntegranteNuevoForm()

    if request.method == 'POST':
        if request.POST.get('modo') == 'alumna':
            usuario = User.objects.filter(
                id=request.POST.get('usuario_id') or 0, is_active=True, is_staff=False, is_superuser=False,
            ).first()
            if not usuario:
                messages.error(request, 'No encontramos esa cuenta. Buscala de nuevo.')
                return redirect('gravity:admin_equipo_sumar')
            sumar_alumna(usuario)
            messages.success(request, f'{usuario.get_full_name() or usuario.username} ya es parte del equipo: '
                                      f'entra al panel con su usuario y contraseña de siempre.')
            return redirect(_url_detalle(usuario, ver='horario'))

        if form.is_valid():
            usuario, clave, invitado = crear_integrante(form.cleaned_data)
            nombre = usuario.get_full_name()
            if clave:
                request.session[f'clave_inicial_{usuario.id}'] = clave
                messages.success(request, f'Sumaste a {nombre} al equipo. Pasale el usuario y la contraseña inicial.')
                return redirect(_url_detalle(usuario, ver='acceso'))
            if invitado:
                messages.success(request, f'Sumaste a {nombre} al equipo. Le mandamos un email a '
                                          f'{usuario.email} para que elija su contraseña.')
            else:
                messages.warning(request, f'Sumaste a {nombre}, pero no se pudo mandar el email. '
                                          f'Probá reenviarlo desde Acceso.')
            return redirect(_url_detalle(usuario, ver='horario'))

    return render(request, 'gravity/admin/equipo_sumar.html', {
        'form': form,
        'buscar': buscar,
        'alumnas': alumnas_para_sumar(buscar),
        'modo': 'alumna' if 'buscar' in request.GET else 'nueva',
    })


@superadmin_required
def admin_eliminar_admin_restringido(request, admin_id):
    """Quitar el acceso al panel: cierra los turnos y desactiva la cuenta o la deja como alumna."""
    profesora = _get_profesora(admin_id)
    if request.method != 'POST':
        return redirect(_url_detalle(profesora, ver='acceso'))
    if not (profesora.is_staff and profesora.is_active):
        messages.info(request, 'Ya no tenía acceso al panel.')
        return redirect(_url_detalle(profesora, ver='acceso'))

    ultimo_dia = _fecha_post(request, 'ultimo_dia') or h.hoy()
    como = 'alumna' if request.POST.get('como') == 'alumna' else 'desactivar'
    cerrados = quitar_acceso(profesora, ultimo_dia, como)

    nombre = profesora.get_full_name() or profesora.username
    texto = f'{nombre} ya no tiene acceso al panel.'
    if como == 'alumna':
        texto += ' Sigue pudiendo entrar como alumna.'
    if cerrados:
        texto += f' Sus turnos se cuentan hasta el {ultimo_dia:%d/%m/%Y}.'
    messages.success(request, texto + ' Su historial de horas y pagos queda acá.')
    _avisar_mes_pagado(request, profesora, ultimo_dia + timedelta(days=1))
    return redirect(_url_detalle(profesora, ver='acceso'))


@superadmin_required
def admin_equipo_reactivar(request, profesora_id):
    """Devolverle el acceso al panel a alguien que lo había perdido."""
    profesora = _get_profesora(profesora_id)
    if request.method == 'POST':
        devolver_acceso(profesora)
        nombre = profesora.get_full_name() or profesora.username
        texto = f'{nombre} vuelve a tener acceso al panel.'
        if not profesora.has_usable_password():
            texto += ' Todavía no eligió su contraseña: reenviale la invitación.'
        messages.success(request, texto + ' Si vuelve a dar clases, cargale el horario.')
    return redirect(_url_detalle(profesora, ver='acceso'))


@superadmin_required
def admin_equipo_datos(request, profesora_id):
    """Editar nombre, email y teléfono."""
    profesora = _get_profesora(profesora_id)
    if request.method != 'POST':
        return redirect(_url_detalle(profesora, ver='acceso'))
    form = IntegranteDatosForm(request.POST, usuario=profesora)
    if not form.is_valid():
        context = {
            'profesora': profesora, 'estado': h.estado_acceso(profesora), 'ver': 'acceso',
            'hoy': h.hoy(), 'ayer': h.hoy() - timedelta(days=1), 'sedes': Clase.DIRECCIONES,
            'meses_pagados': h.meses_pagados(profesora),
        }
        context.update(_datos_acceso(profesora, request, form=form))
        return render(request, 'gravity/admin/profesora_detalle.html', context)

    datos = form.cleaned_data
    with transaction.atomic():
        profesora.first_name, profesora.last_name, profesora.email = datos['nombre'], datos['apellido'], datos['email']
        profesora.save(update_fields=['first_name', 'last_name', 'email'])
        perfil, _ = UserProfile.objects.get_or_create(user=profesora)
        perfil.telefono = datos['telefono']
        perfil.save()
    messages.success(request, 'Datos guardados.')
    return redirect(_url_detalle(profesora, ver='acceso'))


@superadmin_required
def admin_equipo_reenviar(request, profesora_id):
    """Volver a mandar la invitación para elegir la contraseña."""
    profesora = _get_profesora(profesora_id)
    if request.method == 'POST':
        if not profesora.email:
            messages.error(request, 'No tiene email: cargalo en sus datos para mandarle la invitación.')
        elif enviar_invitacion(profesora):
            messages.success(request, f'Le reenviamos la invitación a {profesora.email}.')
        else:
            messages.error(request, 'No se pudo mandar el email. Probá de nuevo en un rato.')
    return redirect(_url_detalle(profesora, ver='acceso'))


# ==============================================================================
# HORARIO, VALOR HORA, DÍAS PUNTUALES Y PAGOS (SUPERADMIN)
# ==============================================================================

@superadmin_required
def admin_profesora_horario_agregar(request, profesora_id):
    """
    Carga turnos para una profesora.

    Se pueden elegir clases del sistema —cada clase es un turno, porque se le
    paga por clase— o cargar un horario libre, y aplicarlo a todas las semanas
    o a una fecha puntual.
    """
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora, ver='horario'))

    modo = request.POST.get('modo', 'semanal')
    fecha = _fecha_post(request, 'fecha')
    vigente_desde = _fecha_post(request, 'vigente_desde') or h.hoy()
    volver = _url_detalle(profesora, fecha, ver='horas') if modo == 'fecha' else _url_detalle(profesora, ver='horario')

    if modo == 'fecha' and not fecha:
        messages.error(request, 'Indicá la fecha del turno.')
        return redirect(volver)

    pedidos, problemas = _turnos_pedidos(
        request, fecha if modo == 'fecha' else None,
        origen=request.POST.get('origen', 'clase'),
    )

    if not pedidos:
        messages.error(
            request,
            problemas[0] if problemas else 'Elegí al menos una clase o cargá un horario.',
        )
        return redirect(volver)

    motivo = request.POST.get('motivo', '').strip()
    creados = []

    for turno in pedidos:
        if modo == 'fecha':
            registro = AjusteHorarioProfesora(
                profesora=profesora, fecha=fecha, tipo='extra', bloque=None, clase=turno['clase'],
                hora_inicio=turno['hora_inicio'], hora_fin=turno['hora_fin'], sede=turno['sede'],
                motivo=motivo, registrado_por=request.user,
            )
        else:
            registro = BloqueHorarioProfesora(
                profesora=profesora, dia=turno['dia'], hora_inicio=turno['hora_inicio'],
                hora_fin=turno['hora_fin'], sede=turno['sede'], clase=turno['clase'],
                vigente_desde=vigente_desde, creado_por=request.user,
            )

        etiqueta = f"{turno['dia']} de {turno['hora_inicio']:%H:%M} a {turno['hora_fin']:%H:%M}"

        try:
            registro.full_clean(exclude=['bloque'] if modo == 'fecha' else None)
        except Exception as error:
            mensajes = getattr(error, 'messages', None) or [str(error)]
            problemas.append(f'{etiqueta}: {" ".join(mensajes)}')
            continue

        if modo == 'semanal':
            solapado = _buscar_solapamiento(registro)
            if solapado:
                problemas.append(
                    f'{etiqueta} se superpone con el turno de {solapado.hora_inicio:%H:%M} '
                    f'a {solapado.hora_fin:%H:%M} que ya tenía cargado.'
                )
                continue
        else:
            solapado = h.turno_superpuesto(profesora, fecha, registro.hora_inicio, registro.hora_fin)
            if solapado:
                problemas.append(
                    f'{etiqueta} se superpone con el turno de {solapado["hora_inicio"]:%H:%M} '
                    f'a {solapado["hora_fin"]:%H:%M} que ya tiene ese día.'
                )
                continue

        registro.save()
        creados.append(etiqueta)

    if creados:
        detalle = f'para el {fecha:%d/%m/%Y}' if modo == 'fecha' else f'a partir del {vigente_desde:%d/%m/%Y}'
        if len(creados) == 1:
            messages.success(request, f'Turno agregado: {creados[0]}, {detalle}.')
        else:
            messages.success(request, f'Se agregaron {len(creados)} turnos {detalle}.')
        if modo == 'fecha':
            _avisar_mes_pagado(request, profesora, fecha, fecha.replace(day=1))
        else:
            _avisar_mes_pagado(request, profesora, vigente_desde)

    for problema in problemas:
        messages.warning(request, problema)

    return redirect(volver)


def _turnos_pedidos(request, fecha=None, origen='clase'):
    """
    Turnos que se quieren cargar, ya sea desde clases o a mano.

    Devuelve la lista de turnos y los avisos de lo que no se pudo interpretar.
    """
    problemas = []
    turnos = []

    ids_clases = request.POST.getlist('clases')

    if origen == 'clase' and not ids_clases:
        problemas.append('Marcá al menos una clase de las que aparecen para ese día.')
        return [], problemas

    if ids_clases:
        try:
            minutos = int(request.POST.get('duracion_minutos') or 60)
        except ValueError:
            minutos = 60
        minutos = max(15, min(minutos, 480))

        clases = Clase.objects.filter(id__in=ids_clases, activa=True)
        for clase in clases:
            if fecha and clase.dia != h.nombre_dia(fecha):
                problemas.append(
                    f'{clase.get_nombre_display()} de las {clase.horario:%H:%M} es de los '
                    f'{clase.dia.lower()}, y el {fecha:%d/%m/%Y} es {h.nombre_dia(fecha).lower()}.'
                )
                continue
            turnos.append({
                'dia': clase.dia,
                'hora_inicio': clase.horario,
                'hora_fin': _sumar_minutos(clase.horario, minutos),
                'sede': clase.direccion,
                'clase': clase,
            })
        return turnos, problemas

    hora_inicio = _hora_post(request, 'hora_inicio')
    hora_fin = _hora_post(request, 'hora_fin')
    dia = h.nombre_dia(fecha) if fecha else request.POST.get('dia', '')

    if not hora_inicio or not hora_fin:
        problemas.append('Cargá la hora de entrada y la de salida.')
        return [], problemas

    turnos.append({
        'dia': dia,
        'hora_inicio': hora_inicio,
        'hora_fin': hora_fin,
        'sede': request.POST.get('sede', ''),
        'clase': None,
    })
    return turnos, problemas


def _sumar_minutos(hora, minutos):
    """Suma minutos a una hora, sin pasar de las 23:59."""
    total = hora.hour * 60 + hora.minute + minutos
    return time(min(total // 60, 23), total % 60 if total < 24 * 60 else 59)


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
        return redirect(_url_detalle(profesora, ver='horario'))

    bloque = get_object_or_404(BloqueHorarioProfesora, id=bloque_id, profesora=profesora)
    ultimo_dia = _fecha_post(request, 'ultimo_dia') or h.hoy()

    if ultimo_dia < bloque.vigente_desde:
        bloque.delete()
        messages.success(request, 'Turno eliminado: todavía no había empezado a regir.')
    else:
        bloque.vigente_hasta = ultimo_dia
        bloque.save(update_fields=['vigente_hasta'])
        if ultimo_dia >= h.hoy():
            messages.success(
                request,
                f'Turno dado de baja: se cuenta hasta el {ultimo_dia:%d/%m/%Y} inclusive, '
                f'así que sigue apareciendo en el horario hasta esa fecha.'
            )
        else:
            messages.success(request, f'Turno dado de baja. Se contó hasta el {ultimo_dia:%d/%m/%Y} inclusive.')
        _avisar_mes_pagado(request, profesora, ultimo_dia + timedelta(days=1))

    return redirect(_url_detalle(profesora, ver='horario'))


@superadmin_required
def admin_profesora_valor_hora(request, profesora_id):
    """
    Carga un nuevo valor hora y cierra el anterior el día previo.

    De esta forma los meses ya trabajados se siguen calculando con el valor que
    regía en ese momento. Si ya había un valor que empieza más adelante, el nuevo
    se cierra el día antes de ese.
    """
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora, ver='horario'))

    valor = _decimal_post(request, 'valor_hora')
    vigente_desde = _fecha_post(request, 'vigente_desde') or h.hoy()
    observaciones = request.POST.get('observaciones', '').strip()

    if valor is None or valor <= 0:
        messages.error(request, 'Ingresá un valor por hora válido, mayor a cero.')
        return redirect(_url_detalle(profesora, ver='horario'))

    with transaction.atomic():
        existente = ValorHoraProfesora.objects.filter(profesora=profesora, vigente_desde=vigente_desde).first()

        if existente:
            existente.valor_hora = valor
            existente.observaciones = observaciones
            existente.registrado_por = request.user
            existente.save()
            messages.success(
                request, f'Valor hora actualizado a ${fmt_pesos(valor)} desde el {vigente_desde:%d/%m/%Y}.')
        else:
            anteriores = ValorHoraProfesora.objects.filter(
                profesora=profesora, vigente_desde__lt=vigente_desde,
            ).filter(h.vigente_en(vigente_desde))
            for anterior in anteriores:
                anterior.vigente_hasta = vigente_desde - timedelta(days=1)
                anterior.save(update_fields=['vigente_hasta'])

            siguiente = ValorHoraProfesora.objects.filter(
                profesora=profesora, vigente_desde__gt=vigente_desde,
            ).order_by('vigente_desde').first()

            ValorHoraProfesora.objects.create(
                profesora=profesora,
                valor_hora=valor,
                vigente_desde=vigente_desde,
                vigente_hasta=siguiente.vigente_desde - timedelta(days=1) if siguiente else None,
                observaciones=observaciones,
                registrado_por=request.user,
            )
            texto = f'Nuevo valor hora: ${fmt_pesos(valor)} a partir del {vigente_desde:%d/%m/%Y}'
            if siguiente:
                texto += f' y hasta el {siguiente.vigente_desde - timedelta(days=1):%d/%m/%Y} (después rige el que ya estaba cargado)'
            messages.success(request, texto + '.')

    _avisar_mes_pagado(request, profesora, vigente_desde)
    return redirect(_url_detalle(profesora, ver='horario'))


@superadmin_required
def admin_profesora_dia_editar(request, profesora_id):
    """
    Cambia lo que pasó en un día puntual, sin tocar el horario semanal.

    Sirve para marcar que no trabajó un turno, que lo hizo en otro horario, o
    para deshacer un cambio cargado antes. Cada cambio apunta al turno concreto,
    así se puede corregir uno solo aunque ese día tenga varios.
    """
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora))

    fecha = _fecha_post(request, 'fecha')
    accion = request.POST.get('accion', '')

    if not fecha:
        messages.error(request, 'No se pudo identificar la fecha del cambio.')
        return redirect(_url_detalle(profesora))

    bloque = None
    if request.POST.get('bloque_id'):
        bloque = BloqueHorarioProfesora.objects.filter(id=request.POST['bloque_id'], profesora=profesora).first()

    ajuste = None
    if request.POST.get('ajuste_id'):
        ajuste = AjusteHorarioProfesora.objects.filter(id=request.POST['ajuste_id'], profesora=profesora).first()

    motivo = request.POST.get('motivo', '').strip()
    hubo_cambio = True

    if accion == 'deshacer':
        if ajuste:
            ajuste.delete()
            messages.success(request, f'Listo, el {fecha:%d/%m/%Y} vuelve a contarse según el horario habitual.')
        else:
            hubo_cambio = False
            messages.error(request, 'Ese cambio ya no existe.')

    elif accion == 'no_trabajo':
        if ajuste and ajuste.tipo == 'extra':
            ajuste.delete()
            messages.success(request, f'Se quitó el turno suelto del {fecha:%d/%m/%Y}.')
        else:
            _guardar_cambio_del_dia(profesora, fecha, bloque, 'ausencia', request.user, motivo=motivo)
            que = 'ese turno' if bloque else 'ese día'
            messages.success(request, f'Quedó registrado que no trabajó {que}.')

    elif accion == 'otro_horario':
        hora_inicio = _hora_post(request, 'hora_inicio')
        hora_fin = _hora_post(request, 'hora_fin')

        if not hora_inicio or not hora_fin or hora_fin <= hora_inicio:
            messages.error(request, 'Revisá el horario: la salida tiene que ser posterior a la entrada.')
            return redirect(_url_detalle(profesora, fecha))

        solapado = h.turno_superpuesto(
            profesora, fecha, hora_inicio, hora_fin,
            ignorar_bloque=bloque.id if bloque else None,
            ignorar_ajuste=ajuste.id if ajuste else None,
        )
        if solapado:
            messages.error(
                request,
                f'Ese horario se superpone con el turno de {solapado["hora_inicio"]:%H:%M} a '
                f'{solapado["hora_fin"]:%H:%M} que tiene ese día.'
            )
            return redirect(_url_detalle(profesora, fecha))

        sede = request.POST.get('sede') or (bloque.sede if bloque else '')

        if ajuste and ajuste.tipo == 'extra':
            ajuste.hora_inicio = hora_inicio
            ajuste.hora_fin = hora_fin
            ajuste.sede = sede
            if motivo:
                ajuste.motivo = motivo
            ajuste.save()
        else:
            _guardar_cambio_del_dia(
                profesora, fecha, bloque, 'reemplazo', request.user,
                hora_inicio=hora_inicio, hora_fin=hora_fin, sede=sede, motivo=motivo,
                clase=bloque.clase if bloque else None,
            )

        messages.success(request, f'El {fecha:%d/%m/%Y} ese turno queda de {hora_inicio:%H:%M} a {hora_fin:%H:%M}.')

    else:
        hubo_cambio = False
        messages.error(request, 'No se entendió qué había que cambiar.')

    if hubo_cambio:
        _avisar_mes_pagado(request, profesora, fecha, fecha.replace(day=1))
    return redirect(_url_detalle(profesora, fecha))


def _guardar_cambio_del_dia(profesora, fecha, bloque, tipo, usuario, **datos):
    """
    Registra el cambio de un turno en una fecha, pisando el anterior si lo había.

    Los turnos sueltos de ese día no se tocan: solo se reemplaza el cambio que
    afecta al mismo turno del horario semanal.
    """
    AjusteHorarioProfesora.objects.filter(
        profesora=profesora, fecha=fecha, bloque=bloque,
        tipo__in=['ausencia', 'reemplazo'],
    ).delete()

    AjusteHorarioProfesora.objects.create(
        profesora=profesora, fecha=fecha, tipo=tipo, bloque=bloque, registrado_por=usuario, **datos,
    )


@superadmin_required
def admin_profesora_ajuste_eliminar(request, profesora_id, ajuste_id):
    """Borra un ajuste puntual y vuelve a valer el horario habitual de ese día."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora))

    ajuste = get_object_or_404(AjusteHorarioProfesora, id=ajuste_id, profesora=profesora)
    fecha = ajuste.fecha
    ajuste.delete()

    messages.success(request, f'Ajuste del {fecha:%d/%m/%Y} eliminado.')
    _avisar_mes_pagado(request, profesora, fecha, fecha.replace(day=1))
    return redirect(_url_detalle(profesora, fecha))


@superadmin_required
def admin_profesora_liquidar(request, profesora_id):
    """Registra el pago del mes a una profesora (desde el último día del mes)."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora))

    mes = _mes_post(request, 'mes')
    if not mes:
        messages.error(request, 'No se pudo identificar el mes a pagar.')
        return redirect(_url_detalle(profesora))

    if LiquidacionProfesora.objects.filter(profesora=profesora, mes_año=mes).exists():
        messages.error(request, 'Ese mes ya figura como pagado.')
        return redirect(_url_detalle(profesora, mes))

    desde, hasta = h.rango_mes(mes.year, mes.month)
    if not h.mes_terminado(mes):
        messages.error(request, f'{nombre_mes(mes).capitalize()} todavía no terminó: '
                                f'el pago se registra desde el {hasta:%d/%m}.')
        return redirect(_url_detalle(profesora, mes))

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
        f'Pago registrado: {resumen["horas"]} horas de {nombre_mes(mes)} por ${fmt_pesos(monto_pagado)}.'
    )
    return redirect(_url_detalle(profesora, mes))


@superadmin_required
def admin_profesora_liquidacion_anular(request, profesora_id, liquidacion_id):
    """Deja el mes otra vez como pendiente de pago."""
    profesora = _get_profesora(profesora_id)

    if request.method != 'POST':
        return redirect(_url_detalle(profesora))

    liquidacion = get_object_or_404(LiquidacionProfesora, id=liquidacion_id, profesora=profesora)
    mes = liquidacion.mes_año
    liquidacion.delete()

    messages.success(request, f'Se eliminó el pago de {nombre_mes(mes)}: el mes queda pendiente.')
    return redirect(_url_detalle(profesora, mes))


# ==============================================================================
# PANTALLA DE LA PROFESORA
# ==============================================================================

@profesora_required
def mis_horarios(request):
    """
    Horario y horas trabajadas de quien está logueada: su horario semanal, las horas
    del mes hasta hoy (y lo que falta), lo que le corresponde cobrar y los meses
    anteriores con su estado de pago.
    """
    profesora = request.user
    context = {
        'profesora': profesora,
        'hoy': h.hoy(),
        'horario_semanal': h.horario_semanal(profesora),
        'horas_semanales': h.horas_semanales(profesora),
    }
    context.update(_datos_horas(profesora, request))
    return render(request, 'gravity/admin/mis_horarios.html', context)
