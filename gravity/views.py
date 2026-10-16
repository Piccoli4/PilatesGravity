from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .models import (
    Reserva,
    Clase,
    PlanUsuario,
    AusenciaTemporal,
    Inasistencia,
    NotificacionCancelacion,
    NotificacionCancelacionPlan,
    AjusteDeudaEspecial,
    NotificacionPlanAdicional,
    CancelacionAdmin,
    DIAS_SEMANA,
    DIAS_SEMANA_COMPLETOS
)
from .forms import ( 
    ReservaForm, 
    ModificarReservaForm, 
    BuscarReservaForm, 
    AjusteDeudaForm,
    ClaseAdminForm,
    AlumnoNuevoForm,
    AlumnoDatosForm,
    normalizar_telefono,
    estilo_panel,
)
import csv
import json
import calendar
from accounts.models import UserProfile
from django.utils import timezone
from django.utils import formats
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from urllib.parse import urlencode
from datetime import datetime, timedelta, date
from accounts.models import UserProfile, ConfiguracionEstudio, Testimonio
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
import logging
from .email_service import (
    enviar_email_cancelacion_reserva,
    enviar_email_confirmacion_reserva_detallado,
    enviar_email_recordatorio_clase_completo,
    enviar_email_confirmacion_pago_completo,
    enviar_email_bienvenida_completo,
    enviar_email_bienvenida,
    enviar_email_modificacion_reserva,
    enviar_email_cambio_plan_aprobado,
    enviar_email_solicitud_rechazada,
)
from .models import (
    PlanPago, EstadoPagoCliente, RegistroPago, DeudaMensual, SolicitudCambioPlan,
    AjusteSaldo, recalcular_estado_pagos, aplicar_precio_a_cuotas_del_mes
)
from .templatetags.formato import pesos
from .panel import ve_ingresos_estudio, puede_corregir_cuentas
from .hoy import datos_hoy, fecha_larga, clases_del_dia
from .asistencia_admin import (datos_pasar_lista, puede_marcar_fecha, reserva_en_fecha, inicio_clase,
                               faltas, completar_filas, DIAS_PARA_MARCAR, TIPOS_FALTA,
                               PERIODOS as PERIODOS_FALTAS)
from .clases_admin import alumnos_afectados, guardar_cambios, se_puede_eliminar
from .horarios import turnos_de_la_clase
from .reservas_admin import proximas_fechas, fecha_corta, ocupacion, info_alumno, estado_reserva
from .alumnos_admin import (crear_alumno, agregar_nota, notas_lista, whatsapp_url, estado_cuenta,
                            que_se_cancela, desactivar_alumno)
from accounts.invitacion import enviar_invitacion, tiene_invitacion_pendiente
from accounts.mi_espacio import reservas_alumno
from .actividad import eventos_actividad, rango_por_defecto, sueltas_no_canceladas, dar_de_baja_reservas, TIPOS as TIPOS_ACTIVIDAD
from .forms import (
    PlanPagoForm, RegistroPagoForm, EstadoPagoClienteForm, FiltrosPagosForm,
    CorregirSaldoForm, EditarPagoForm, AnularPagoForm
)
from django.db.models import Sum, Count, Q
from decimal import Decimal

# Configurar el logger
logger = logging.getLogger(__name__)

# Página de inicio (pública)
def home(request):
    """Vista pública de la página principal"""
    return render(request, 'gravity/home.html')

DIAS_GRILLA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
DIAS_CORTOS_GRILLA = {'Lunes': 'Lun', 'Martes': 'Mar', 'Miércoles': 'Mié', 'Jueves': 'Jue', 'Viernes': 'Vie', 'Sábado': 'Sáb'}
SEDES_GRILLA = {'sede_principal': 'Sede Central', 'sede_2': 'Sede 2'}


def grilla_reservas(usuario, recuperos=None):
    """
    Horarios de la semana para la grilla de "Reservar clase": cada clase activa con
    su próxima fecha reservable, los lugares libres y el estado para este usuario.

    Estados: 'tuya' (ya la tiene), 'libre' (se puede como horario fijo o una sola vez),
    'solo_fecha' (sin lugares fijos, pero esa fecha se liberó un lugar) y 'completa'.
    'recupero': si reservarla una sola vez cubriría una ausencia pendiente (no usa el plan).
    """
    if recuperos is None:
        from .recuperos import EstadoRecuperos
        recuperos = EstadoRecuperos(usuario)
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()
    mias = {
        r.clase_id: r for r in Reserva.objects.filter(usuario=usuario, activa=True)
        if not r.fecha_unica or r.fecha_unica >= hoy
    }

    clases = Clase.objects.filter(activa=True, dia__in=DIAS_GRILLA)
    dias = {dia: [] for dia in DIAS_GRILLA}
    for clase in clases:
        fecha = clase.proxima_fecha_reservable(ahora)
        libres_fecha = clase.cupos_disponibles(fecha=fecha)
        libres_fijos = clase.cupos_disponibles()
        if clase.id in mias:
            estado = 'tuya'
        elif libres_fijos > 0 and libres_fecha > 0:
            estado = 'libre'
        elif libres_fecha > 0:
            estado = 'solo_fecha'
        else:
            estado = 'completa'
        dias[clase.dia].append({
            'clase': clase,
            'tipo': clase.tipo,
            'nombre': clase.nombre_personalizado if clase.tipo == 'Especial' and clase.nombre_personalizado else clase.tipo,
            'sede': clase.direccion,
            'sede_nombre': SEDES_GRILLA.get(clase.direccion, clase.get_direccion_display()),
            'hora': clase.horario.strftime('%H:%M'),
            'fecha': fecha,
            'estado': estado,
            'libres': libres_fijos if estado == 'libre' else libres_fecha,
            'es_puntual_mia': bool(estado == 'tuya' and mias[clase.id].fecha_unica),
            'recupero': estado in ('libre', 'solo_fecha') and recuperos.puede_recuperar_en(clase, fecha),
        })

    columnas = []
    for dia in DIAS_GRILLA:
        slots = sorted(dias[dia], key=lambda s: (s['hora'], s['sede']))
        if slots:
            columnas.append({'dia': dia, 'corto': DIAS_CORTOS_GRILLA[dia], 'slots': slots})

    tipos = sorted({(c.tipo, c.get_tipo_display()) for c in clases}, key=lambda t: ['Reformer', 'Cadillac', 'Especial'].index(t[0]) if t[0] in ('Reformer', 'Cadillac', 'Especial') else 9)
    sedes = [(k, v) for k, v in SEDES_GRILLA.items() if any(c.direccion == k for c in clases)]
    return {'columnas': columnas, 'tipos': tipos, 'sedes': sedes}


# Vista para reservar una clase (solo usuarios autenticados)
@login_required
def reservar_clase(request):
    """
    Grilla semanal para elegir un horario y reservarlo como horario fijo
    (todas las semanas) o una sola vez. ReservaForm hace todas las validaciones.
    """
    try:
        estado_pago = request.user.estado_pago
        if not estado_pago.puede_reservar:
            dias_atraso = 0
            if estado_pago.fecha_limite_pago:
                dias_atraso = (timezone.now().date() - estado_pago.fecha_limite_pago).days
            messages.error(
                request,
                f'No podés reservar porque tenés una cuota vencida de ${estado_pago.monto_deuda_mensual:,.0f} '
                f'(venció el {estado_pago.fecha_limite_pago.strftime("%d/%m/%Y")}, hace {dias_atraso} '
                f'{"día" if dias_atraso == 1 else "días"}). Escribinos para regularizarla.'
            )
            return redirect('accounts:profile')
    except EstadoPagoCliente.DoesNotExist:
        pass

    try:
        request.user.profile
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=request.user)

    clases_plan, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    reservas_semana = Reserva.contar_reservas_usuario_semana(request.user)
    clases_restantes = max(0, clases_plan - reservas_semana)

    if request.method == 'POST':
        form = ReservaForm(request.POST, user=request.user)
        if form.is_valid():
            clase = form.cleaned_data['clase']
            es_temporal = form.cleaned_data.get('es_temporal')
            es_recupero = form.cleaned_data.get('es_recupero', False)
            fecha_unica = form.cleaned_data['proxima_fecha'] if es_temporal else None
            try:
                reserva = Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_unica=fecha_unica,
                    es_recupero=es_recupero,
                    notas=f'Recupero por ausencia temporal — {fecha_unica.strftime("%d/%m/%Y")}' if es_recupero else '',
                    creado_por=request.user,
                )
            except (IntegrityError, ValidationError):
                # Doble envío: dos POST simultáneos pueden pasar la validación del form
                messages.error(request, 'Ya tenés una reserva para esta clase. Revisá "Mis reservas".')
                return redirect('accounts:mis_reservas')

            try:
                if enviar_email_confirmacion_reserva_detallado(reserva):
                    logger.info(f"Email de confirmación enviado para reserva {reserva.numero_reserva}")
            except Exception as e:
                logger.error(f"Error enviando email de confirmación: {str(e)}")

            request.session['reserva_exitosa'] = {
                'tipo': 'recupero' if es_recupero else 'temporal' if es_temporal else 'recurrente',
                'clase': clase.get_nombre_display(),
                'dia': clase.dia,
                'horario': clase.horario.strftime('%H:%M'),
                'sede': clase.get_direccion_corta(),
                'fecha_unica': fecha_unica.strftime('%d/%m/%Y') if fecha_unica else None,
            }
            return redirect('accounts:mis_reservas')
    else:
        form = ReservaForm(user=request.user)

    # Horario a preseleccionar: el del POST con error o el que llega desde Clases disponibles
    origen = request.POST if request.method == 'POST' else request.GET
    preseleccion = {
        'tipo': origen.get('tipo_clase') or origen.get('tipo', ''),
        'sede': origen.get('sede', ''),
        'dia': origen.get('dia', ''),
        'horario': origen.get('horario', ''),
        'temporal': origen.get('es_temporal') in ('true', 'on', '1'),
    }

    solicitud_pendiente = SolicitudCambioPlan.objects.filter(
        usuario=request.user, estado='pendiente'
    ).select_related('plan_solicitado').first()
    from .recuperos import EstadoRecuperos
    recuperos = EstadoRecuperos(request.user)

    return render(request, 'gravity/reservar_clase.html', {
        'form': form,
        'grilla': grilla_reservas(request.user, recuperos),
        'preseleccion': preseleccion,
        'clases_plan': clases_plan,
        'reservas_semana': reservas_semana,
        'clases_restantes': clases_restantes,
        'porcentaje_plan': min(100, round(reservas_semana * 100 / clases_plan)) if clases_plan else 0,
        'puede_reservar': clases_plan > 0 and clases_restantes > 0,
        'solicitud_pendiente': solicitud_pendiente,
        'n_recuperos': recuperos.disponibles,
    })

# Vista para modificar una reserva existente
@login_required
def modificar_reserva(request, numero_reserva):
    """
    Permite a un usuario modificar su propia reserva.
    Utiliza ModificarReservaForm con todas las validaciones.
    """

    try:
        estado_pago = request.user.estado_pago
        if not estado_pago.puede_reservar:
            # Calcular días de atraso
            dias_atraso = 0
            if estado_pago.fecha_limite_pago:
                dias_atraso = (timezone.now().date() - estado_pago.fecha_limite_pago).days
            
            messages.error(
                request,
                f'❌ No puedes modificar reservas porque tienes una deuda vencida de ${estado_pago.monto_deuda_mensual:,.0f}. '
                f'La fecha límite de pago era el {estado_pago.fecha_limite_pago.strftime("%d/%m/%Y")} '
                f'({dias_atraso} {"día" if dias_atraso == 1 else "días"} de atraso). '
                f'Por favor, realiza el pago o contacta a la administración para regularizar tu situación.'
            )
            return redirect('accounts:profile')
    except EstadoPagoCliente.DoesNotExist:
        # Usuario sin estado de pago, permitir modificar
        pass

    # Obtener la reserva y verificar que pertenece al usuario
    reserva = get_object_or_404(
        Reserva,
        numero_reserva=numero_reserva,
        usuario=request.user,
        activa=True
    )
    
    # Verificar si la reserva puede modificarse (3 horas de anticipación)
    puede_modificar, mensaje = reserva.puede_modificarse()
    
    if not puede_modificar:
        messages.error(request, f'No puedes modificar esta reserva: {mensaje}')
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    if request.method == 'POST':
        form = ModificarReservaForm(
            request.POST, 
            reserva_actual=reserva, 
            user=request.user
        )
        
        if form.is_valid():
            try:
                nueva_clase = form.cleaned_data['nueva_clase']
                
                # Actualizar la reserva
                reserva.clase = nueva_clase
                reserva.save()
                
                messages.success(
                    request,
                    f'¡Cambio exitoso! Tu reserva ahora es para la clase de '
                    f'{nueva_clase.get_nombre_display()} los {nueva_clase.dia} '
                    f'a las {nueva_clase.horario.strftime("%H:%M")} en {nueva_clase.get_direccion_corta()}.'
                )
                
                return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)
                
            except (IntegrityError, ValidationError):
                messages.error(
                    request,
                    'Error interno: conflicto de reserva. '
                    'Si esto persiste, contacta al administrador.'
                )
    else:
        form = ModificarReservaForm(reserva_actual=reserva, user=request.user)

    return render(request, 'gravity/modificar_reserva.html', {
        'form': form,
        'reserva': reserva,
        'puede_modificar': puede_modificar,
        'mensaje_restriccion': mensaje if not puede_modificar else None
    })

def _volver_a(request, numero_reserva):
    """
    Destino después de una acción sobre una reserva: el 'next' del formulario
    (por ejemplo, Mis reservas) si es una URL de este sitio, o el detalle.
    """
    destino = request.POST.get('next') or request.GET.get('next')
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(destino)
    return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)


# Vista para eliminar/cancelar una reserva
@login_required
def cancelar_reserva(request, numero_reserva):
    """
    Permite a un usuario cancelar su reserva, de forma permanente o
    temporal (solo para la próxima ocurrencia de la clase).
    """
    # Verificar deudas vencidas (mantener lógica existente si la tenés)
    reserva = get_object_or_404(
        Reserva,
        numero_reserva=numero_reserva,
        usuario=request.user
    )

    # Protección contra double-POST: si ya fue cancelada, redirigir limpiamente
    if not reserva.activa:
        messages.info(request, 'Esta reserva ya fue cancelada.')
        return redirect('accounts:mis_reservas')

    puede_cancelar, mensaje = reserva.puede_modificarse()

    if not puede_cancelar:
        messages.error(request, f'No podés cancelar esta reserva: {mensaje}')
        return _volver_a(request, numero_reserva)

    if request.method == 'POST':
        confirmar = request.POST.get('confirmar_cancelacion')
        tipo = request.POST.get('tipo_cancelacion', 'permanente')

        if confirmar != 'confirmar':
            messages.error(request, 'Debes confirmar la cancelación.')
            return _volver_a(request, numero_reserva)

        try:
            if tipo == 'temporal':
                proxima_fecha = reserva.get_proxima_fecha()

                if not proxima_fecha:
                    messages.error(request, 'No se pudo determinar la próxima fecha de clase.')
                    return _volver_a(request, numero_reserva)

                # Verificar que no exista ya una ausencia para esa fecha
                ausencia, creada = AusenciaTemporal.objects.get_or_create(
                    reserva=reserva,
                    fecha=proxima_fecha
                )

                if not creada:
                    messages.warning(
                        request,
                        f'Ya tenías registrada una ausencia para el '
                        f'{proxima_fecha.strftime("%d/%m/%Y")}.'
                    )
                else:
                    request.session['ausencia_registrada'] = {
                        'clase': reserva.clase.get_nombre_display(),
                        'dia': reserva.clase.dia,
                        'horario': reserva.clase.horario.strftime('%H:%M'),
                        'sede': reserva.clase.get_direccion_corta(),
                        'fecha_ausencia': proxima_fecha.strftime('%d/%m/%Y'),
                        'fecha_limite': ausencia.fecha_limite_recupero.strftime('%d/%m/%Y'),
                    }
                    # Notificar admins
                    notificar_admins_cancelacion(reserva, tipo='temporal', fecha=proxima_fecha)
                    return redirect('accounts:mis_reservas')

            else:  # permanente
                reserva.activa = False
                reserva.save()

                messages.success(
                    request,
                    f'Tu reserva para {reserva.clase.get_nombre_display()} '
                    f'los {reserva.clase.dia} a las {reserva.clase.horario.strftime("%H:%M")} '
                    f'en {reserva.clase.get_direccion_corta()} fue cancelada.'
                )
                # Notificar admins
                notificar_admins_cancelacion(reserva, tipo='permanente')
                return redirect('accounts:mis_reservas')

        except Exception as e:
            messages.error(request, 'Ocurrió un error al procesar la cancelación. Intentá nuevamente.')

        # Si la reserva quedó inactiva en DB (por el save antes de la excepción),
        # no redirigir a detalle_reserva (causaría 404)
        if not reserva.activa:
            return redirect('accounts:mis_reservas')
        return _volver_a(request, numero_reserva)

    # GET: redirigir al detalle (el modal está ahí)
    return _volver_a(request, numero_reserva)

def notificar_admins_cancelacion(reserva, tipo, fecha=None):
    """
    Notifica a los administradores cuando un cliente cancela una clase.
    Guarda en base de datos y envía email.
    """
    from .email_service import enviar_notificacion_cancelacion_a_admins

    # Guardar en base de datos para el panel
    try:
        NotificacionCancelacion.objects.create(
            reserva=reserva,
            tipo=tipo,
            fecha_ausencia=fecha if tipo == 'temporal' else None,
        )
    except Exception as e:
        logger.error(f"Error guardando notificación de cancelación: {e}")

    # Enviar email
    try:
        enviar_notificacion_cancelacion_a_admins(reserva, tipo=tipo, fecha=fecha)
    except Exception as e:
        logger.error(f"Error notificando admins por cancelación de {reserva.numero_reserva}: {e}")

@login_required
@require_http_methods(["POST"])
def cerrar_modal_ausencia_registrada(request):
    """
    Elimina la session key 'ausencia_registrada' cuando el usuario cierra el modal.
    Se llama por AJAX desde mis_reservas.html.
    """
    request.session.pop('ausencia_registrada', None)
    return JsonResponse({'ok': True})

@login_required
def cancelar_ausencia(request, ausencia_id):
    """
    Permite al usuario cancelar una ausencia temporal ya registrada,
    recuperando su lugar en la clase.
    Restricciones:
      - Misma ventana de 3 horas que la cancelación de reserva.
      - No se puede cancelar si ya hay un recupero reservado en la ventana de esa ausencia.
    """
    ausencia = get_object_or_404(
        AusenciaTemporal,
        id=ausencia_id,
        reserva__usuario=request.user,
        reserva__activa=True,
    )
    reserva = ausencia.reserva
    numero_reserva = reserva.numero_reserva

    if request.method != 'POST':
        return _volver_a(request, numero_reserva)

    # 1. Verificar ventana de 3 horas
    puede_modificar, mensaje = reserva.puede_modificarse()
    if not puede_modificar:
        messages.error(
            request,
            f'No podés cancelar la ausencia: {mensaje}'
        )
        return _volver_a(request, numero_reserva)

    # 2. Verificar que no haya un recupero ya reservado en la ventana de esta ausencia
    hoy = timezone.now().date()
    recupero_existente = Reserva.objects.filter(
        usuario=request.user,
        activa=True,
        es_recupero=True,
        fecha_unica__gte=hoy,
        fecha_unica__lte=ausencia.fecha_limite_recupero,
    ).first()

    if recupero_existente:
        messages.error(
            request,
            f'No podés cancelar esta ausencia porque ya tenés un recupero reservado '
            f'para el {recupero_existente.fecha_unica.strftime("%d/%m/%Y")} '
            f'({recupero_existente.clase.get_nombre_display()} '
            f'en {recupero_existente.clase.get_direccion_corta()}). '
            f'Primero cancelá ese recupero desde "Mis Reservas".'
        )
        return _volver_a(request, numero_reserva)

    # 3. Todo ok: eliminar la ausencia
    fecha_str = ausencia.fecha.strftime('%d/%m/%Y')
    ausencia.delete()

    messages.success(
        request,
        f'Ausencia cancelada. Tu lugar para el {fecha_str} está confirmado nuevamente.'
    )
    return _volver_a(request, numero_reserva)

# Vista para buscar reservas de usuario (pública)
def buscar_reservas_usuario(request):
    """
    Permite buscar reservas por nombre de usuario.
    Utiliza BuscarReservaForm para validar el usuario.
    """
    reservas_usuario = []
    usuario_encontrado = None
    
    if request.method == 'POST':
        form = BuscarReservaForm(request.POST)
        
        if form.is_valid():
            # El formulario ya validó que el usuario existe
            usuario_encontrado = form.cleaned_data.get('user')
            
            if usuario_encontrado:
                # Obtener todas las reservas activas del usuario, ordenadas por sede
                reservas_usuario = Reserva.objects.filter(
                    usuario=usuario_encontrado,
                    activa=True
                ).select_related('clase').order_by('clase__direccion', 'clase__dia', 'clase__horario')
    else:
        form = BuscarReservaForm()

    return render(request, 'gravity/buscar_reservas_usuario.html', {
        'form': form,
        'reservas_usuario': reservas_usuario,
        'usuario_encontrado': usuario_encontrado
    })

# Vista para mostrar detalle de una reserva
@login_required
def detalle_reserva(request, numero_reserva):
    """
    Detalle de una reserva del alumno: tipo, próxima clase, próximas fechas y las
    mismas acciones que Mis reservas (avisar que no voy, deshacer, dar de baja).
    """
    from accounts.mi_espacio import detalle_reserva_alumno

    reserva = Reserva.objects.filter(numero_reserva=numero_reserva, usuario=request.user).select_related('clase').first()
    if not reserva:
        messages.error(request, 'No encontramos esa reserva entre las tuyas.')
        return redirect('accounts:mis_reservas')
    if not reserva.activa:
        messages.info(request, 'Esa reserva ya no está activa. Acá están tus reservas actuales.')
        return redirect('accounts:mis_reservas')

    return render(request, 'gravity/detalle_reserva.html', {
        'reserva': reserva,
        'd': detalle_reserva_alumno(reserva),
    })

# Vista para mostrar clases disponibles (pública)
def clases_disponibles(request):
    """
    Muestra todas las clases disponibles con información de cupos.
    Vista informativa pública, ahora organizadas por sede.
    """
    clases = Clase.objects.filter(activa=True).order_by('direccion', 'tipo', 'dia', 'horario')
    
    # Organizar clases por sede
    clases_por_sede = {}
    estadisticas_generales = {
        'disponibles': 0,
        'limitadas': 0,
        'completas': 0,
        'total': 0
    }
    
    for clase in clases:
        cupos_disponibles = clase.cupos_disponibles()
        esta_completa = clase.esta_completa()
        porcentaje_ocupacion = clase.get_porcentaje_ocupacion()
        
        # Organizar por sede
        sede_key = clase.direccion
        sede_display = clase.get_direccion_display()
        
        if sede_key not in clases_por_sede:
            clases_por_sede[sede_key] = {
                'nombre': sede_display,
                'clases': [],
                'estadisticas': {
                    'disponibles': 0,
                    'limitadas': 0,
                    'completas': 0,
                    'total': 0
                }
            }
        
        clase_info = {
            'clase': clase,
            'cupos_disponibles': cupos_disponibles,
            'esta_completa': esta_completa,
            'porcentaje_ocupacion': porcentaje_ocupacion,
            'cupo_temporal': clase.get_cupo_temporal_semana() if esta_completa else None,
        }
        
        clases_por_sede[sede_key]['clases'].append(clase_info)
        
        # Contar para estadísticas por sede
        if esta_completa:
            clases_por_sede[sede_key]['estadisticas']['completas'] += 1
            estadisticas_generales['completas'] += 1
        elif cupos_disponibles <= 2:
            clases_por_sede[sede_key]['estadisticas']['limitadas'] += 1
            estadisticas_generales['limitadas'] += 1
        else:
            clases_por_sede[sede_key]['estadisticas']['disponibles'] += 1
            estadisticas_generales['disponibles'] += 1
        
        clases_por_sede[sede_key]['estadisticas']['total'] += 1
        estadisticas_generales['total'] += 1
    
    return render(request, 'gravity/clases_disponibles.html', {
        'clases_por_sede': clases_por_sede,
        'estadisticas_generales': estadisticas_generales
    })

# Vista para el botón de "Conoce más" (pública)
def conoce_mas(request):
    """El estudio: método, equipos, instructores, sedes y testimonios."""
    from accounts.mi_espacio import SEDES

    testimonios = []
    for t in (Testimonio.objects.filter(aprobado=True, usuario__is_active=True)
              .select_related('usuario').order_by('-fecha_actualizacion')[:9]):
        nombre = (t.usuario.first_name or t.usuario.username).strip().split(' ')[0]
        inicial = t.usuario.last_name.strip()[:1]
        testimonios.append({
            'texto': t.texto,
            # Nombre e inicial del apellido ("Lucía G."): real pero cuidando la privacidad
            'nombre': f'{nombre} {inicial.upper()}.' if inicial else nombre,
            'iniciales': (nombre[:1] + inicial).upper(),
        })

    sedes = [
        dict(SEDES['sede_principal'], foto='img/estudio/sede-central.webp', clave='sede_principal'),
        dict(SEDES['sede_2'], foto='img/estudio/sede-2.webp', clave='sede_2'),
    ]
    return render(request, 'gravity/conoce_mas.html', {'testimonios': testimonios, 'sedes': sedes})

# Vista para mostrar planes y precios (pública)
def anotar_planes(planes):
    """
    Agrega a cada PlanPago los datos que muestran las tarjetas de planes
    (/precios/, elegir y cambiar de plan): precios formateados (lista, efectivo
    y por clase), si es de Reformer, si es el destacado y los días de su semana.
    """
    planes = list(planes)

    # El más elegido: el que más alumnos activos tienen vigente hoy (si empatan, el más barato)
    hoy = timezone.localdate()
    alumnos_por_plan = dict(
        PlanUsuario.objects.filter(
            plan__in=planes, activo=True, fecha_inicio__lte=hoy, fecha_fin__gte=hoy, usuario__is_active=True,
        ).values_list('plan').annotate(n=Count('usuario', distinct=True))
    )
    mas_elegido = max(
        (p for p in planes if alumnos_por_plan.get(p.id)),
        key=lambda p: (alumnos_por_plan[p.id], -p.precio_mensual),
        default=None,
    )

    # Días de la semana (L a S) que se marcan en la tarjeta según las clases semanales
    ritmo_por_clases = {1: {2}, 2: {1, 3}, 3: {0, 2, 4}, 4: {0, 1, 3, 4}, 5: {0, 1, 2, 3, 4}}
    for plan in planes:
        clases = plan.clases_por_semana or 1
        plan.precio_fmt = pesos(plan.precio_mensual)
        plan.efectivo_fmt = pesos(plan.calcular_precio_efectivo())
        plan.por_clase_fmt = pesos(plan.precio_mensual / (clases * 4))
        plan.es_reformer = 'reformer' in plan.nombre.lower()
        marcados = ritmo_por_clases.get(clases, set(range(min(clases, 6))))
        plan.semana = [(dia, i in marcados) for i, dia in enumerate(['L', 'M', 'M', 'J', 'V', 'S'])]
        plan.destacado = plan is mas_elegido

    # Primero los planes generales y después los de Reformer
    planes.sort(key=lambda p: (p.es_reformer, p.clases_por_semana, p.precio_mensual))
    return planes


def precios_publicos(request):
    """
    Vista pública para mostrar los planes y precios sin necesidad de login.
    """
    planes_disponibles = anotar_planes(
        PlanPago.objects.filter(activo=True).order_by('clases_por_semana', 'precio_mensual')
    )
    context = {
        'planes_disponibles': planes_disponibles,
    }
    return render(request, 'gravity/precios_publicos.html', context)

# API Endpoints para funcionalidad AJAX (las usa el panel de administración)
@require_http_methods(["POST"])
def dias_disponibles(request):
    """
    API que devuelve los días únicos disponibles para un tipo de clase y sede específicos
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        sede = data.get('sede')
        
        if not tipo_clase:
            return JsonResponse({'error': 'Tipo de clase requerido'}, status=400)

        # Construir filtro base
        filtro = {
            'tipo': tipo_clase, 
            'activa': True
        }
        
        # Agregar sede al filtro si se especifica
        if sede:
            filtro['direccion'] = sede

        # Obtener días únicos para la combinación tipo-sede (solo clases activas)
        dias_disponibles = Clase.objects.filter(**filtro).values_list('dia', flat=True).distinct()

        # Ordenar días según el orden de la semana
        orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
        dias_ordenados = sorted(
            set(dias_disponibles), 
            key=lambda x: orden_dias.index(x) if x in orden_dias else 999
        )

        return JsonResponse({
            'dias': dias_ordenados
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["POST"])
def horarios_disponibles(request):
    """
    API que devuelve los horarios disponibles para un tipo de clase, sede y día específicos
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        sede = data.get('sede')
        dia_clase = data.get('dia')
        
        if not tipo_clase or not dia_clase:
            return JsonResponse({'error': 'Tipo de clase y día requeridos'}, status=400)
        
        # Construir filtro
        filtro = {
            'tipo': tipo_clase, 
            'dia': dia_clase,
            'activa': True
        }
        
        if sede:
            filtro['direccion'] = sede
        
        # Obtener horarios para la combinación (solo clases activas)
        clases = Clase.objects.filter(**filtro).order_by('horario')
        
        horarios_info = []
        for clase in clases:
            cupos_disponibles = clase.cupos_disponibles()
            sede_corta = clase.get_direccion_corta()
            
            horarios_info.append({
                'value': clase.horario.strftime('%H:%M'),
                'text': f"{clase.horario.strftime('%H:%M')} - {sede_corta} ({cupos_disponibles} cupos)",
                'cupos': cupos_disponibles,
                'disponible': cupos_disponibles > 0,
                'sede': clase.direccion,
                'sede_display': sede_corta
            })
        
        return JsonResponse({
            'horarios': horarios_info
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def clases_disponibles_api(request):
    """
    API que devuelve todas las clases disponibles con información de cupos y sede
    """
    try:
        clases = Clase.objects.filter(activa=True).order_by('direccion', 'tipo', 'dia', 'horario')
        
        clases_data = []
        for clase in clases:
            cupos_disponibles = clase.cupos_disponibles()
            clases_data.append({
                'id': clase.id,
                'tipo': clase.tipo,
                'tipo_display': clase.get_nombre_display(),
                'direccion': clase.direccion,
                'direccion_display': clase.get_direccion_display(),
                'direccion_corta': clase.get_direccion_corta(),
                'dia': clase.dia,
                'horario': clase.horario.strftime('%H:%M'),
                'horario_display': clase.horario.strftime('%H:%M'),
                'cupos_disponibles': cupos_disponibles,
                'cupo_maximo': clase.cupo_maximo,
                'disponible': cupos_disponibles > 0,
                'porcentaje_ocupacion': clase.get_porcentaje_ocupacion()
            })
        
        return JsonResponse(clases_data, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ==============================================================================
# VISTAS DEL ADMINISTRADOR
# ==============================================================================
# ==============================================================================
# DECORADORES Y UTILIDADES PARA ADMINISTRADOR
# ==============================================================================

def admin_required(view_func):
    """
    Decorador personalizado que requiere que el usuario sea staff/admin
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debes iniciar sesión como administrador.')
            return redirect('accounts:login')
        
        if not request.user.is_staff:
            messages.error(request, 'No tienes permisos de administrador.')
            return redirect('gravity:home')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper

def superadmin_required(view_func):
    """
    Decorador que requiere que el usuario sea superusuario (Nico o Cami).
    Solo ellos pueden gestionar administradores con permisos restringidos.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debes iniciar sesión como administrador.')
            return redirect('accounts:login')
        if not request.user.is_superuser:
            messages.error(request, 'No tenés permisos para acceder a esta sección.')
            return redirect('gravity:admin_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

# Quién ve qué en el panel: reglas en gravity/panel.py (ve_ingresos_estudio,
# puede_corregir_cuentas). El equipo ve los montos de cada alumno para poder cobrar;
# los ingresos del estudio son solo del superadmin.

# ==============================================================================
# DASHBOARD PRINCIPAL DEL ADMINISTRADOR
# ==============================================================================

@admin_required
def admin_dashboard(request):
    """
    "Hoy": las clases del día con quién viene (se puede mirar hasta 6 días para
    adelante), lo que hay para resolver y las últimas novedades.
    Los datos se arman en gravity/hoy.py.
    """
    return render(request, 'gravity/admin/dashboard.html', datos_hoy(request))

@admin_required
def admin_marcar_notificaciones_leidas(request):
    """
    Marca todas las notificaciones de cancelación como leídas para el admin actual.
    Se llama por AJAX al cerrar el pop-up.
    """
    if request.method == 'POST':
        from .models import NotificacionCancelacion

        # Leer IDs de recuperos/cupos temporales desde el body
        try:
            data = json.loads(request.body)
            recupero_ids = data.get('recupero_ids', [])
        except (json.JSONDecodeError, TypeError):
            recupero_ids = []

        # Marcar cancelaciones de reservas como leídas
        desde = timezone.now() - timedelta(days=7)
        notificaciones = NotificacionCancelacion.objects.filter(
            fecha_creacion__gte=desde
        ).exclude(leida_por=request.user)
        for n in notificaciones:
            n.leida_por.add(request.user)

        # Marcar cancelaciones de planes como leídas
        desde_30 = timezone.now() - timedelta(days=30)
        notificaciones_plan = NotificacionCancelacionPlan.objects.filter(
            fecha_creacion__gte=desde_30
        ).exclude(leida_por=request.user)
        for n in notificaciones_plan:
            n.leida_por.add(request.user)

        # Marcar planes adicionales como leídos
        notificaciones_adicional = NotificacionPlanAdicional.objects.filter(
            fecha_creacion__gte=desde_30
        ).exclude(leida_por=request.user)
        for n in notificaciones_adicional:
            n.leida_por.add(request.user)

        # Guardar IDs de reservas temporales vistas en la sesión
        if recupero_ids:
            vistos = list(request.session.get('recuperos_vistos', []))
            vistos.extend([int(i) for i in recupero_ids if str(i).isdigit()])
            request.session['recuperos_vistos'] = vistos

        return JsonResponse({'ok': True})

    return JsonResponse({'ok': False}, status=400)

# ==============================================================================
# GESTIÓN DE CLASES
# ==============================================================================

@admin_required
def admin_clases_lista(request):
    """
    Todas las clases en una página, agrupadas por día, con su ocupación de
    horarios fijos. Filtros por sede, tipo y estado (por defecto, activas).
    """
    sede = request.GET.get('sede', '')
    if sede not in dict(Clase.DIRECCIONES):
        sede = ''
    tipo = request.GET.get('tipo', '')
    if tipo not in dict(Clase.TIPO_CLASES):
        tipo = ''
    estado = request.GET.get('estado', 'activas')
    if estado == 'inactivas':
        estado = 'pausadas'
    if estado not in ('activas', 'pausadas', 'todas'):
        estado = 'activas'

    clases = Clase.objects.annotate(
        fijos=Count('reserva', filter=Q(reserva__activa=True, reserva__fecha_unica__isnull=True))
    ).order_by('horario', 'direccion')
    if sede:
        clases = clases.filter(direccion=sede)
    if tipo:
        clases = clases.filter(tipo=tipo)
    conteo = {
        'activas': clases.filter(activa=True).count(),
        'pausadas': clases.filter(activa=False).count(),
    }
    conteo['todas'] = conteo['activas'] + conteo['pausadas']
    if estado == 'activas':
        clases = clases.filter(activa=True)
    elif estado == 'pausadas':
        clases = clases.filter(activa=False)

    por_dia = {dia: [] for dia, _ in DIAS_SEMANA_COMPLETOS}
    total_fijos = total_cupo = 0
    for clase in clases:
        cupo = clase.cupo_maximo or 0
        porcentaje = round(clase.fijos / cupo * 100) if cupo else 0
        por_dia.setdefault(clase.dia, []).append({
            'clase': clase,
            'fijos': clase.fijos,
            'libres': max(cupo - clase.fijos, 0),
            'porcentaje': min(porcentaje, 100),
            'nivel': 'lleno' if clase.fijos >= cupo else ('alto' if porcentaje >= 80 else ''),
        })
        if clase.activa:
            total_fijos += clase.fijos
            total_cupo += cupo
    dias = [{'dia': dia, 'clases': items} for dia, items in por_dia.items() if items]

    def url_con(**cambios):
        params = request.GET.copy()
        for clave, valor in cambios.items():
            if valor and not (clave == 'estado' and valor == 'activas'):
                params[clave] = valor
            else:
                params.pop(clave, None)
        return '?' + params.urlencode()

    chips_estado = [
        {'texto': texto, 'url': url_con(estado=clave), 'activo': estado == clave, 'cantidad': conteo[clave]}
        for clave, texto in (('activas', 'Activas'), ('pausadas', 'Pausadas'), ('todas', 'Todas'))
    ]
    chips_sede = [{'texto': 'Las dos sedes', 'url': url_con(sede=''), 'activo': not sede}] + [
        {'texto': Clase(direccion=clave).get_direccion_corta(), 'url': url_con(sede=clave), 'activo': sede == clave}
        for clave, _ in Clase.DIRECCIONES
    ]
    chips_tipo = [{'texto': 'Todos los tipos', 'url': url_con(tipo=''), 'activo': not tipo}] + [
        {'texto': clave, 'url': url_con(tipo=clave), 'activo': tipo == clave}
        for clave, _ in Clase.TIPO_CLASES
    ]

    context = {
        'dias': dias,
        'chips_estado': chips_estado,
        'chips_sede': chips_sede,
        'chips_tipo': chips_tipo,
        'total': sum(len(d['clases']) for d in dias),
        'conteo': conteo,
        'total_fijos': total_fijos,
        'total_cupo': total_cupo,
        'sede_filtro': sede,
        'tipo_filtro': tipo,
        'estado_filtro': estado,
        'sedes': Clase.DIRECCIONES,
        'tipos': Clase.TIPO_CLASES,
        'hay_filtros': bool(sede or tipo or estado != 'activas'),
    }
    return render(request, 'gravity/admin/clases_lista.html', context)


@admin_required
def admin_clase_crear(request):
    """
    Crear una clase. Acepta datos iniciales por GET (?tipo&direccion&dia&horario&cupo_maximo)
    para "Crear otra igual" desde el detalle de una clase.
    """
    inicial = {k: request.GET[k] for k in ('tipo', 'direccion', 'dia', 'horario', 'cupo_maximo', 'nombre_personalizado')
               if request.GET.get(k)}
    form = ClaseAdminForm(request.POST or None, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        clase = form.save()
        messages.success(
            request,
            f'Listo: creaste {clase.get_nombre_display()} los {clase.dia} a las {clase.horario:%H:%M} '
            f'en {clase.get_direccion_corta()}.'
        )
        return redirect('gravity:admin_clase_detalle', clase_id=clase.id)
    return render(request, 'gravity/admin/clase_form.html', {'form': form, 'accion': 'crear'})


@admin_required
def admin_clase_editar(request, clase_id):
    """
    Editar una clase. Si cambia el día, el horario o la sede, se mueve a los
    alumnos con horario fijo (con email opcional) y, si cambia el día, se cancelan
    los recuperos y clases únicas ya reservados (ver gravity/clases_admin.py).
    """
    clase = get_object_or_404(Clase, id=clase_id)
    fijas, sueltas = alumnos_afectados(clase)
    form = ClaseAdminForm(request.POST or None, instance=clase)
    if request.method == 'POST' and form.is_valid():
        resumen = guardar_cambios(form, request.user, avisar=request.POST.get('avisar') == 'on')
        clase.refresh_from_db()
        texto = f'Guardaste los cambios de {clase.get_nombre_display()} ({clase.dia} {clase.horario:%H:%M}).'
        if resumen['avisados']:
            texto += f' Les avisamos por email a {resumen["avisados"]} alumno{"s" if resumen["avisados"] != 1 else ""}.'
        if resumen['sueltas_canceladas']:
            n = resumen['sueltas_canceladas']
            texto += f' Se cancelaron {n} recupero{"s" if n != 1 else ""} o {"clases únicas" if n != 1 else "clase única"} reservado{"s" if n != 1 else ""} para el día anterior.'
        if resumen['profesoras']:
            nombres = ', '.join(p.get_full_name() or p.username for p in resumen['profesoras'])
            texto += f' El turno de {nombres} pasó al horario nuevo.'
        messages.success(request, texto)
        return redirect('gravity:admin_clase_detalle', clase_id=clase.id)
    return render(request, 'gravity/admin/clase_form.html', {
        'form': form,
        'accion': 'editar',
        'clase': Clase.objects.get(pk=clase.pk),  # la guardada, por si el formulario tiene errores
        'fijos': len(fijas),
        'sueltas': len(sueltas),
        'fijos_con_email': sum(1 for r in fijas if r.usuario.email),
        'profesoras': [b.profesora.get_full_name() or b.profesora.username for b in turnos_de_la_clase(clase)],
    })


@admin_required
def admin_clase_eliminar(request, clase_id):
    """
    Eliminar una clase solo si nunca tuvo reservas. Si tuvo, se ofrece pausarla:
    borrarla eliminaría en cascada su historia (reservas, asistencia, recuperos).
    """
    clase = get_object_or_404(Clase, id=clase_id)
    puede = se_puede_eliminar(clase)

    if request.method == 'POST':
        if not puede:
            messages.error(request, 'Esta clase ya tuvo alumnos: no se puede eliminar, pero podés pausarla.')
            return redirect('gravity:admin_clase_eliminar', clase_id=clase.id)
        nombre = f'{clase.get_nombre_display()} ({clase.dia} {clase.horario:%H:%M}, {clase.get_direccion_corta()})'
        clase.delete()
        messages.success(request, f'Eliminaste la clase {nombre}.')
        return redirect('gravity:admin_clases_lista')

    return render(request, 'gravity/admin/clase_eliminar.html', {
        'clase': clase,
        'puede': puede,
        'fijos': clase.reserva_set.filter(activa=True, fecha_unica__isnull=True).count(),
        'historial': clase.reserva_set.count(),
    })


def _proxima_fecha_clase(clase, ahora):
    """La próxima vez que se dicta la clase (hoy si todavía no terminó)."""
    hoy = ahora.date()
    indice = [d for d, _ in DIAS_SEMANA_COMPLETOS].index(clase.dia)
    dias_hasta = (indice - hoy.weekday()) % 7
    if dias_hasta == 0:
        fin = ahora.replace(hour=clase.horario.hour, minute=clase.horario.minute, second=0, microsecond=0) + timedelta(hours=1)
        if ahora >= fin:
            dias_hasta = 7
    return hoy + timedelta(days=dias_hasta)


@admin_required
def admin_clase_detalle(request, clase_id):
    """
    Una clase: quién viene la próxima vez, los alumnos con horario fijo, los
    recuperos y clases únicas reservados y la ocupación de las próximas semanas.
    """
    clase = get_object_or_404(Clase, id=clase_id)
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()
    fijas = list(
        clase.reserva_set.filter(activa=True, fecha_unica__isnull=True)
        .select_related('usuario__profile', 'creado_por')
        .order_by('usuario__first_name', 'usuario__last_name')
    )
    sueltas = list(
        clase.reserva_set.filter(activa=True, fecha_unica__gte=hoy)
        .select_related('usuario', 'creado_por').order_by('fecha_unica')
    )

    proxima = semanas = None
    if clase.activa:
        fecha = _proxima_fecha_clase(clase, ahora)
        proxima = next((c for c in clases_del_dia(fecha, timezone.now()) if c['clase'].id == clase.id), None)
        if proxima:
            proxima['fecha'] = fecha
            proxima['fecha_larga'] = fecha_larga(fecha)
            proxima['es_hoy'] = fecha == hoy
        semanas = []
        for i in range(4):
            dia = fecha + timedelta(days=7 * i)
            libres = clase.cupos_disponibles(fecha=dia)
            vienen = clase.cupo_maximo - libres
            semanas.append({
                'fecha': dia,
                'vienen': vienen,
                'libres': libres,
                'porcentaje': min(round(vienen / clase.cupo_maximo * 100), 100) if clase.cupo_maximo else 0,
            })

    cupo = clase.cupo_maximo or 0
    context = {
        'clase': clase,
        'fijas': fijas,
        'sueltas': sueltas,
        'proxima': proxima,
        'semanas': semanas,
        'fijos': len(fijas),
        'libres_fijos': max(cupo - len(fijas), 0),
        'porcentaje_fijos': min(round(len(fijas) / cupo * 100), 100) if cupo else 0,
        'puede_eliminar': se_puede_eliminar(clase),
        'profesoras': [b.profesora.get_full_name() or b.profesora.username for b in turnos_de_la_clase(clase)],
    }
    return render(request, 'gravity/admin/clase_detalle.html', context)


@admin_required
@require_http_methods(["POST"])
def admin_clase_toggle_status(request, clase_id):
    """
    Pausar o reactivar una clase. En pausa los alumnos conservan su lugar, pero la
    clase no se dicta ni acepta reservas nuevas.
    """
    clase = get_object_or_404(Clase, id=clase_id)
    clase.activa = not clase.activa
    clase.save(update_fields=['activa', 'fecha_modificacion'])
    nombre = f'{clase.get_nombre_display()} ({clase.dia} {clase.horario:%H:%M})'
    if clase.activa:
        messages.success(request, f'{nombre} vuelve a estar activa.')
    else:
        fijos = clase.reserva_set.filter(activa=True, fecha_unica__isnull=True).count()
        extra = f' Los {fijos} alumnos con horario fijo conservan su lugar.' if fijos else ''
        messages.success(request, f'Pausaste {nombre}: no se dicta ni acepta reservas nuevas.{extra}')

    destino = request.POST.get('next', '')
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect('gravity:admin_clase_detalle', clase_id=clase.id)

# ==============================================================================
# ASISTENCIA
# ==============================================================================

def _sedes_cortas():
    return [(valor, Clase(direccion=valor).get_direccion_corta()) for valor, _ in Clase.DIRECCIONES]


@admin_required
def admin_asistencia(request):
    """
    Pasar lista: las clases de un día con sus alumnos. Se marca "No vino" desde que
    empieza la clase y hasta 7 días atrás; las fechas más viejas son de consulta.
    La lista se arma con lo que había ese día (gravity/asistencia_admin.py).
    """
    hoy = timezone.localdate()
    try:
        fecha = date.fromisoformat(request.GET.get('fecha', ''))
    except ValueError:
        fecha = hoy
    sede = request.GET.get('sede', '')
    if sede not in dict(Clase.DIRECCIONES):
        sede = ''

    context = datos_pasar_lista(fecha, sede)
    context.update({'sede_filtro': sede, 'sedes': _sedes_cortas()})
    return render(request, 'gravity/admin/asistencia.html', context)


def _marcar_inasistencia(user, datos):
    """Marca o deshace un "No vino". Devuelve (error, mensaje, estado)."""
    try:
        reserva_id = int(datos.get('reserva_id'))
        fecha = date.fromisoformat(str(datos.get('fecha')))
    except (TypeError, ValueError):
        return 'Faltan datos para marcar la asistencia.', None, None
    marcar = datos.get('marcar') in (True, 1, '1', 'true')

    ahora = timezone.now()
    if not puede_marcar_fecha(fecha, timezone.localdate(ahora)):
        return f'Solo se puede marcar la asistencia de hoy y de los últimos {DIAS_PARA_MARCAR} días.', None, None
    reserva = Reserva.objects.select_related('usuario', 'clase').filter(id=reserva_id).first()
    if not reserva or not reserva_en_fecha(reserva, fecha, ahora):
        return 'Ese alumno no estaba anotado en esa clase ese día.', None, None
    inicio = inicio_clase(reserva.clase, fecha)
    if ahora < inicio:
        return f'La clase todavía no empezó: vas a poder marcarlo desde las {timezone.localtime(inicio):%H:%M}.', None, None
    if AusenciaTemporal.objects.filter(reserva=reserva, fecha=fecha).exists():
        return 'Ese alumno avisó que no venía: no hace falta marcarlo.', None, None

    nombre = reserva.usuario.get_full_name() or reserva.usuario.username
    if marcar:
        Inasistencia.objects.get_or_create(reserva=reserva, fecha=fecha, defaults={'registrado_por': user})
        return None, f'Marcaste que {nombre} no vino.', 'no_vino'
    Inasistencia.objects.filter(reserva=reserva, fecha=fecha).delete()
    return None, f'Listo: {nombre} figura como que vino.', 'vino'


@admin_required
@require_http_methods(['POST'])
def admin_asistencia_marcar(request):
    """
    Marca o deshace un "No vino". Desde la lista llega en JSON (sin recargar la
    página); sin JavaScript, como formulario común (vuelve a la lista con un aviso).
    """
    es_json = request.content_type == 'application/json'
    if es_json:
        try:
            datos = json.loads(request.body or b'{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            datos = {}
        if not isinstance(datos, dict):
            datos = {}
    else:
        datos = request.POST

    error, mensaje, estado = _marcar_inasistencia(request.user, datos)
    if es_json:
        if error:
            return JsonResponse({'success': False, 'error': error}, status=400)
        return JsonResponse({'success': True, 'message': mensaje, 'estado': estado})

    if error:
        messages.error(request, error)
    else:
        messages.success(request, mensaje)
    return _volver(request, reverse('gravity:admin_asistencia'))


@admin_required
def admin_asistencia_ausencias(request):
    """
    Faltas: avisos de ausencia (con el estado del recupero) y "No vino" sin aviso,
    agrupados por día. Por defecto, los últimos 7 días; "Próximas" muestra los
    avisos de hoy en adelante.
    """
    hoy = timezone.localdate()

    def fecha_get(clave):
        try:
            return date.fromisoformat(request.GET.get(clave, ''))
        except ValueError:
            return None

    desde, hasta = fecha_get('desde'), fecha_get('hasta')
    personalizado = bool(desde or hasta)
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
    periodo = request.GET.get('periodo', '')
    if personalizado:
        periodo = ''
    else:
        periodo = periodo if periodo in PERIODOS_FALTAS else '7'
        if periodo == 'proximas':
            desde, hasta = hoy, None
        else:
            desde, hasta = hoy - timedelta(days=int(periodo) - 1), hoy

    tipo = request.GET.get('tipo', '')
    if tipo not in dict(TIPOS_FALTA):
        tipo = ''
    sede = request.GET.get('sede', '')
    if sede not in dict(Clase.DIRECCIONES):
        sede = ''
    buscar = request.GET.get('buscar', '').strip()
    alumno = None
    if request.GET.get('alumno', '').isdigit():
        alumno = User.objects.filter(id=request.GET['alumno']).first()

    filas, conteo = faltas(desde=desde, hasta=hasta, sede=sede, buscar=buscar, tipo=tipo,
                           usuario=alumno, proximas=periodo == 'proximas')
    page_obj = Paginator(filas, 30).get_page(request.GET.get('page'))
    completar_filas(page_obj.object_list, hoy)

    # Filtros actuales sin el tipo ni la página, para armar los enlaces de los chips
    params = request.GET.copy()
    for clave in ('tipo', 'page'):
        params.pop(clave, None)
    params_pagina = request.GET.copy()
    params_pagina.pop('page', None)

    context = {
        'page_obj': page_obj,
        'total_filas': len(filas),
        'total_todos': sum(conteo.values()),
        'tipos': [{'clave': c, 'texto': t, 'cantidad': conteo[c]} for c, t in TIPOS_FALTA],
        'tipo_filtro': tipo,
        'sede_filtro': sede,
        'sedes': _sedes_cortas(),
        'buscar': buscar,
        'alumno': alumno,
        'periodo': periodo,
        'personalizado': personalizado,
        'desde': desde,
        'hasta': hasta,
        'qs_sin_tipo': params.urlencode(),
        'qs_pagina': params_pagina.urlencode(),
        'hoy': hoy,
    }
    return render(request, 'gravity/admin/asistencia_ausencias.html', context)

# ==============================================================================
# GESTIÓN DE RESERVAS
# ==============================================================================

def _next_seguro(request):
    """El `next` pedido, solo si es una dirección del propio sitio (si no, vacío)."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return destino
    return ''


def _volver(request, defecto):
    """A `next` si es una dirección del sitio; si no, al destino por defecto."""
    return redirect(_next_seguro(request) or defecto)


def _opciones_clases(ahora, excluir_id=None):
    """
    Clases activas agrupadas por día, con lugares fijos libres y las próximas 4
    fechas con sus lugares libres (para reservar o cambiar una reserva).
    """
    hoy = timezone.localtime(ahora).date()
    clases = [c for c in Clase.objects.filter(activa=True).order_by('horario', 'direccion') if c.id != excluir_id]
    fechas = {c.id: proximas_fechas(c, ahora) for c in clases}
    libres = ocupacion(clases, fechas)
    grupos = {dia: [] for dia, _ in DIAS_SEMANA_COMPLETOS}
    datos_js = {}
    for c in clases:
        info = libres[c.id]
        item = {
            'clase': c,
            'id': c.id,
            'libres_fijos': info['libres_fijos'],
            'fechas': [
                {'iso': f.isoformat(), 'texto': fecha_corta(f, hoy), 'libres': info['fechas'][f]}
                for f in fechas[c.id]
            ],
        }
        grupos.setdefault(c.dia, []).append(item)
        datos_js[c.id] = {'fijos': info['libres_fijos'], 'fechas': item['fechas'], 'tipo': c.tipo}
    return [{'dia': d, 'clases': cs} for d, cs in grupos.items() if cs], datos_js


def _fecha_post(request, clase, ahora):
    """La fecha elegida para una reserva de una sola vez, si es una de las próximas de la clase."""
    posibles = proximas_fechas(clase, ahora)
    valor = request.POST.get('fecha', '')
    for f in posibles:
        if f.isoformat() == valor:
            return f
    return posibles[0] if not valor and posibles else None


@admin_required
def admin_reservas_lista(request):
    """
    Reservas en tres pestañas: horarios fijos, recuperos y clases únicas desde hoy,
    e historial con el estado real (realizada, cancelada por el alumno o por el
    estudio, dada de baja). Buscador por alumno y filtros de sede, tipo y día.
    """
    hoy = timezone.localdate()
    ver = request.GET.get('ver', 'fijos')
    if ver not in ('fijos', 'sueltas', 'historial'):
        ver = 'fijos'
    buscar = request.GET.get('usuario', '').strip()
    sede = request.GET.get('sede', '')
    if sede not in dict(Clase.DIRECCIONES):
        sede = ''
    tipo = request.GET.get('tipo_clase', '')
    if tipo not in dict(Clase.TIPO_CLASES):
        tipo = ''
    dia = request.GET.get('dia', '')
    if dia not in dict(DIAS_SEMANA_COMPLETOS):
        dia = ''

    base = Reserva.objects.select_related('usuario', 'clase', 'creado_por')
    if buscar:
        base = base.filter(
            Q(usuario__username__icontains=buscar) | Q(usuario__first_name__icontains=buscar)
            | Q(usuario__last_name__icontains=buscar) | Q(usuario__email__icontains=buscar)
        )
    if sede:
        base = base.filter(clase__direccion=sede)
    if tipo:
        base = base.filter(clase__tipo=tipo)
    if dia:
        base = base.filter(clase__dia=dia)

    consultas = {
        'fijos': base.filter(activa=True, fecha_unica__isnull=True)
                     .order_by('usuario__first_name', 'usuario__last_name', 'clase__horario'),
        'sueltas': base.filter(activa=True, fecha_unica__gte=hoy).order_by('fecha_unica', 'clase__horario'),
        'historial': base.filter(Q(activa=False) | Q(fecha_unica__lt=hoy))
                         .prefetch_related('cancelaciones_admin', 'notificaciones_cancelacion')
                         .order_by('-fecha_modificacion'),
    }
    conteo = {clave: qs.count() for clave, qs in consultas.items()}
    page_obj = Paginator(consultas[ver], 25).get_page(request.GET.get('page'))
    filas = []
    for r in page_obj:
        filas.append({
            'reserva': r,
            'estado': estado_reserva(r, hoy) if ver == 'historial' else None,
            'tipo': 'Recupero' if r.es_recupero else ('Clase única' if r.fecha_unica else 'Horario fijo'),
        })

    params = request.GET.copy()
    params.pop('page', None)
    sin_ver = params.copy()
    sin_ver.pop('ver', None)
    context = {
        'page_obj': page_obj,
        'filas': filas,
        'ver': ver,
        'pestanas': [
            {'clave': 'fijos', 'texto': 'Horarios fijos', 'cantidad': conteo['fijos']},
            {'clave': 'sueltas', 'texto': 'Recuperos y clases únicas', 'cantidad': conteo['sueltas']},
            {'clave': 'historial', 'texto': 'Historial', 'cantidad': conteo['historial']},
        ],
        'qs_pagina': params.urlencode(),
        'qs_sin_ver': sin_ver.urlencode(),
        'usuario_filtro': buscar,
        'sede_filtro': sede,
        'tipo_filtro': tipo,
        'dia_filtro': dia,
        'sedes': Clase.DIRECCIONES,
        'tipos': Clase.TIPO_CLASES,
        'dias': DIAS_SEMANA_COMPLETOS,
        'hay_filtros': bool(buscar or sede or tipo or dia),
        'hoy': hoy,
        'aqui': request.get_full_path(),
    }
    return render(request, 'gravity/admin/reservas_lista.html', context)


@admin_required
def admin_reserva_cancelar(request, reserva_id):
    """
    Cancelar desde el panel (sin la restricción de horario del alumno).
    En un horario fijo se puede elegir avisar la ausencia de una sola fecha (el
    alumno queda con su recupero, como si lo hubiera avisado él) o dar de baja el
    horario. Un recupero o una clase única se cancela entero.
    """
    reserva = get_object_or_404(Reserva.objects.select_related('usuario', 'clase'), id=reserva_id)
    ficha = reverse('gravity:admin_usuario_detalle', args=[reserva.usuario_id]) if not reserva.usuario.is_staff \
        else reverse('gravity:admin_reservas_lista')

    # Protección contra doble envío: si ya fue cancelada, volver
    if not reserva.activa:
        messages.info(request, f'La reserva {reserva.numero_reserva} ya estaba cancelada.')
        return _volver(request, ficha)

    ahora = timezone.now()
    ausentes = set(reserva.ausencias_temporales.values_list('fecha', flat=True))
    fechas = []
    if not reserva.fecha_unica and reserva.clase.activa:
        fechas = [
            {'fecha': f, 'iso': f.isoformat(), 'texto': fecha_corta(f), 'avisada': f in ausentes}
            for f in proximas_fechas(reserva.clase, ahora)
        ]

    if request.method == 'POST':
        alcance = request.POST.get('alcance', 'baja')
        nombre = reserva.get_nombre_completo_usuario()

        if alcance == 'fecha' and fechas:
            elegida = next((f for f in fechas if f['iso'] == request.POST.get('fecha') and not f['avisada']), None)
            if not elegida:
                messages.error(request, 'Elegí una fecha en la que el alumno todavía no avisó que falta.')
            else:
                ausencia, creada = AusenciaTemporal.objects.get_or_create(reserva=reserva, fecha=elegida['fecha'])
                if creada:
                    aviso = NotificacionCancelacion.objects.create(
                        reserva=reserva, tipo='temporal', fecha_ausencia=elegida['fecha']
                    )
                    aviso.leida_por.add(request.user)
                messages.success(
                    request,
                    f'Listo: {nombre} no va el {elegida["fecha"]:%d/%m}. Su lugar queda libre ese día y '
                    f'puede recuperar la clase hasta el {ausencia.fecha_limite_recupero:%d/%m}.'
                )
                return _volver(request, ficha)

        else:
            motivo = request.POST.get('motivo', '').strip()
            motivo_detalle = request.POST.get('motivo_detalle', '').strip()
            notificar_usuario = request.POST.get('notificar_usuario') == 'on'
            ofrecer_reemplazo = request.POST.get('ofrecer_reemplazo') == 'on'

            if not motivo:
                messages.error(request, 'Elegí el motivo de la cancelación.')
            else:
                cancelacion = None
                try:
                    # Solo los cambios en la base van en la transacción; el email sale después
                    with transaction.atomic():
                        # Bloquear la fila: si llegan dos POST a la vez, el segundo ve la reserva cancelada
                        reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
                        if not reserva.activa:
                            messages.info(request, f'La reserva {reserva.numero_reserva} ya estaba cancelada.')
                            return _volver(request, ficha)
                        nota = f'Cancelada por el estudio - Motivo: {motivo}' + (f' - Detalle: {motivo_detalle}' if motivo_detalle else '')
                        reserva.notas = f'{reserva.notas}\n{nota}' if reserva.notas else nota
                        reserva.activa = False
                        reserva.save()
                        cancelacion = CancelacionAdmin.objects.create(
                            reserva=reserva, admin_user=request.user, motivo=motivo,
                            motivo_detalle=motivo_detalle, email_enviado=False,
                        )
                except Exception as e:
                    logger.error(f'Error cancelando la reserva {reserva.numero_reserva}: {e}')
                    messages.error(request, 'No se pudo cancelar la reserva. Probá de nuevo.')
                else:
                    email_enviado = False
                    if notificar_usuario and reserva.usuario.email:
                        try:
                            email_enviado = enviar_email_cancelacion_reserva(
                                reserva=reserva, motivo=motivo, motivo_detalle=motivo_detalle,
                                ofrecer_reemplazo=ofrecer_reemplazo, ofrecer_otras_sedes=False,
                            )
                        except Exception as e:
                            logger.error(f'Error enviando email de cancelación: {e}')
                    if email_enviado and cancelacion:
                        CancelacionAdmin.objects.filter(pk=cancelacion.pk).update(email_enviado=True)

                    que = 'el horario fijo' if not reserva.fecha_unica else (
                        f'el recupero del {reserva.fecha_unica:%d/%m}' if reserva.es_recupero
                        else f'la clase única del {reserva.fecha_unica:%d/%m}')
                    texto = f'Cancelaste {que} de {nombre} ({reserva.clase.get_nombre_display()} {reserva.clase.dia} {reserva.clase.horario:%H:%M}).'
                    if notificar_usuario:
                        if email_enviado:
                            texto += f' Le avisamos a {reserva.usuario.email}.'
                        elif reserva.usuario.email:
                            texto += f' No se pudo mandar el email a {reserva.usuario.email}.'
                        else:
                            texto += ' No tiene email cargado para avisarle.'
                    messages.success(request, texto)
                    return _volver(request, ficha)

    return render(request, 'gravity/admin/reserva_cancelar.html', {
        'reserva': reserva,
        'fechas': fechas,
        'motivos': MOTIVOS_CANCELACION_ADMIN,
        'alcance': request.POST.get('alcance', 'fecha' if fechas else 'baja'),
        'fecha_defecto': request.POST.get('fecha') or next((f['iso'] for f in fechas if not f['avisada']), ''),
        'next': _next_seguro(request),
    })


MOTIVOS_CANCELACION_ADMIN = [
    'Pedido del alumno',
    'Clase suspendida por el estudio',
    'Cambio de horario de la clase',
    'Problema de salud del alumno',
    'Falta de pago',
    'Incumplimiento de normas',
    'Error al cargar la reserva',
    'Otro',
]


@admin_required
def admin_reserva_modificar(request, reserva_id):
    """
    Pasar una reserva a otra clase desde el panel. No mira el límite del plan
    (lo maneja el estudio) pero sí el cupo. Un recupero o una clase única elige
    también la fecha nueva.
    """
    reserva = get_object_or_404(Reserva.objects.select_related('usuario', 'clase'), id=reserva_id, activa=True)
    ficha = reverse('gravity:admin_usuario_detalle', args=[reserva.usuario_id])
    ahora = timezone.now()
    puntual = bool(reserva.fecha_unica)
    # Un horario fijo cambia de clase; uno puntual puede quedarse en la misma clase con otra fecha
    grupos, datos_js = _opciones_clases(ahora, excluir_id=None if puntual else reserva.clase_id)

    if request.method == 'POST':
        nueva = Clase.objects.filter(id=request.POST.get('nueva_clase'), activa=True).first()
        notificar = request.POST.get('notificar_usuario') == 'on'
        error = None
        fecha = None
        if not nueva:
            error = 'Elegí la clase nueva.'
        elif puntual:
            fecha = _fecha_post(request, nueva, ahora)
            if not fecha:
                error = 'Elegí una de las fechas de la clase nueva.'
            elif nueva.id == reserva.clase_id and fecha == reserva.fecha_unica:
                error = 'Es la misma clase y la misma fecha que ya tiene.'
            elif nueva.cupos_disponibles(fecha=fecha) <= 0:
                error = f'{nueva.get_nombre_display()} del {fecha:%d/%m} no tiene lugar.'
            elif Reserva.objects.filter(usuario=reserva.usuario, clase=nueva, activa=True).filter(
                    Q(fecha_unica=fecha) | Q(fecha_unica__isnull=True)).exclude(pk=reserva.pk).exists():
                error = 'El alumno ya tiene esa clase ese día.'
        else:
            if nueva.cupos_disponibles() <= 0:
                error = f'{nueva.get_nombre_display()} {nueva.dia} {nueva.horario:%H:%M} no tiene lugares fijos libres.'
            elif Reserva.objects.filter(usuario=reserva.usuario, clase=nueva, activa=True).exclude(pk=reserva.pk).exists():
                error = 'El alumno ya tiene una reserva en esa clase.'

        if error:
            messages.error(request, error)
        else:
            clase_anterior = reserva.clase
            fecha_anterior = reserva.fecha_unica
            try:
                with transaction.atomic():
                    reserva.clase = nueva
                    if puntual:
                        reserva.fecha_unica = fecha
                    reserva.save()
                    borradas = 0
                    if not puntual and clase_anterior.dia != nueva.dia:
                        # Los avisos de ausencia futuros eran para el día viejo
                        borradas, _ = reserva.ausencias_temporales.filter(fecha__gte=ahora.date()).delete()
            except (IntegrityError, ValidationError) as e:
                reserva.clase, reserva.fecha_unica = clase_anterior, fecha_anterior
                messages.error(request, ' '.join(getattr(e, 'messages', [])) or 'El alumno ya tiene una reserva en esa clase.')
            else:
                email_enviado = False
                if notificar and reserva.usuario.email:
                    try:
                        email_enviado = enviar_email_modificacion_reserva(reserva=reserva, clase_anterior=clase_anterior)
                    except Exception as e:
                        logger.error(f'Error enviando email de modificación: {e}')
                cuando = f' el {fecha:%d/%m}' if puntual else ''
                texto = (f'{reserva.get_nombre_completo_usuario()} pasó de {clase_anterior.get_nombre_display()} '
                         f'{clase_anterior.dia} {clase_anterior.horario:%H:%M} a {nueva.get_nombre_display()} '
                         f'{nueva.dia} {nueva.horario:%H:%M}{cuando} ({nueva.get_direccion_corta()}).')
                if borradas:
                    texto += f' Se borraron {borradas} aviso{"s" if borradas != 1 else ""} de ausencia del día anterior.'
                if notificar:
                    texto += f' Le avisamos a {reserva.usuario.email}.' if email_enviado else ' No se pudo mandar el email.'
                messages.success(request, texto)
                return _volver(request, ficha)

    return render(request, 'gravity/admin/reserva_modificar.html', {
        'reserva': reserva,
        'puntual': puntual,
        'grupos': grupos,
        'datos_js': datos_js,
        'info': info_alumno(reserva.usuario),
        'elegida': request.POST.get('nueva_clase', ''),
        'next': _next_seguro(request),
    })

def grilla_recuperos(usuario, estado):
    """
    Columnas por fecha (de hoy al plazo de recupero) con las clases donde se puede
    recuperar: tipo permitido según la clase que faltó, con lugar esa fecha y que
    todavía no empezaron. No se ofrece la propia clase fija del alumno.
    """
    hoy = estado.ahora.date()
    if not estado.fecha_limite:
        return {'columnas': [], 'tipos': [], 'sedes': []}

    tipos = estado.tipos_disponibles
    propias = set(Reserva.objects.filter(usuario=usuario, activa=True, fecha_unica__isnull=True).values_list('clase_id', flat=True))
    puntuales = set(Reserva.objects.filter(usuario=usuario, activa=True, fecha_unica__gte=hoy).values_list('clase_id', 'fecha_unica'))
    clases = list(Clase.objects.filter(activa=True, tipo__in=tipos, dia__in=DIAS_GRILLA))

    columnas = []
    fecha = hoy
    while fecha <= estado.fecha_limite:
        dia = (DIAS_GRILLA + ['Domingo'])[fecha.weekday()]
        slots = []
        for clase in clases:
            if clase.dia != dia or clase.id in propias or (clase.id, fecha) in puntuales:
                continue
            if not estado.puede_recuperar_en(clase, fecha):
                continue
            libres = clase.cupos_disponibles(fecha=fecha)
            slots.append({
                'clase': clase,
                'tipo': clase.tipo,
                'nombre': clase.nombre_personalizado if clase.tipo == 'Especial' and clase.nombre_personalizado else clase.tipo,
                'sede': clase.direccion,
                'sede_nombre': SEDES_GRILLA.get(clase.direccion, clase.get_direccion_display()),
                'hora': clase.horario.strftime('%H:%M'),
                'estado': 'libre' if libres > 0 else 'completa',
                'libres': libres,
            })
        if slots:
            dias_hasta = (fecha - hoy).days
            columnas.append({
                'fecha': fecha,
                'fecha_iso': fecha.isoformat(),
                'corto': DIAS_CORTOS_GRILLA.get(dia, dia[:3]),
                'relativo': 'Hoy' if dias_hasta == 0 else 'Mañana' if dias_hasta == 1 else '',
                'slots': sorted(slots, key=lambda x: (x['hora'], x['sede'])),
            })
        fecha += timedelta(days=1)

    orden_tipos = ['Reformer', 'Cadillac', 'Especial']
    tipos_lista = sorted({(c.tipo, c.get_tipo_display()) for c in clases},
                         key=lambda t: orden_tipos.index(t[0]) if t[0] in orden_tipos else 9)
    sedes = [(k, v) for k, v in SEDES_GRILLA.items() if any(c.direccion == k for c in clases)]
    return {'columnas': columnas, 'tipos': tipos_lista, 'sedes': sedes}


@login_required
def reservar_recupero(request):
    """
    Recuperar una clase que se avisó que se faltaba. Es solo para esa fecha y no usa
    clases del plan. Reglas (tipo, plazo y qué recupero cubre cada ausencia) en
    gravity/recuperos.py.
    """
    from datetime import date as date_type
    from .recuperos import EstadoRecuperos, tipos_permitidos

    estado = EstadoRecuperos(request.user)
    if not estado.disponibles:
        messages.info(request, 'No tenés clases para recuperar en este momento.')
        return redirect('accounts:mis_reservas')

    if request.method == 'POST':
        try:
            fecha_recupero = date_type.fromisoformat(request.POST.get('fecha', ''))
            clase = Clase.objects.get(id=request.POST.get('clase_id'), activa=True)
        except (ValueError, Clase.DoesNotExist):
            messages.error(request, 'Ese horario ya no está disponible. Elegí otro.')
            return redirect('gravity:reservar_recupero')

        error = None
        dia_de_la_fecha = (DIAS_GRILLA + ['Domingo'])[fecha_recupero.weekday()]
        if dia_de_la_fecha != clase.dia:
            error = 'Ese horario ya no está disponible. Elegí otro.'
        elif Reserva.objects.filter(usuario=request.user, clase=clase, activa=True).filter(
                Q(fecha_unica__isnull=True) | Q(fecha_unica=fecha_recupero)).exists():
            error = 'Ya tenés una reserva para esa clase.'
        elif not estado.puede_recuperar_en(clase, fecha_recupero):
            error = 'Ese horario no está disponible para recuperar (ya empezó, pasa tu plazo o no corresponde al tipo de clase que faltaste).'
        elif clase.cupos_disponibles(fecha=fecha_recupero) <= 0:
            error = 'Se ocupó el último lugar de esa clase. Elegí otro horario.'

        if error:
            messages.error(request, error)
            return redirect('gravity:reservar_recupero')

        try:
            Reserva(
                usuario=request.user,
                clase=clase,
                es_recupero=True,
                fecha_unica=fecha_recupero,
                notas=f'Recupero por ausencia temporal — {fecha_recupero.strftime("%d/%m/%Y")}',
                creado_por=request.user,
            ).save()  # save() ya ejecuta full_clean()
        except IntegrityError:
            messages.error(request, 'Ya tenés una reserva para esa clase en esa fecha.')
            return redirect('accounts:mis_reservas')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return redirect('gravity:reservar_recupero')

        request.session['reserva_exitosa'] = {
            'tipo': 'recupero',
            'clase': clase.get_nombre_display(),
            'dia': clase.dia,
            'horario': clase.horario.strftime('%H:%M'),
            'sede': clase.get_direccion_corta(),
            'fecha': fecha_recupero.strftime('%d/%m/%Y'),
        }
        return redirect('accounts:mis_reservas')

    pendientes = [{
        'ausencia': a,
        'clase': a.reserva.clase,
        'permitidos': sorted(tipos_permitidos(a.reserva.clase.tipo), key=lambda t: t != a.reserva.clase.tipo),
    } for a in estado.pendientes]

    context = {
        'pendientes': pendientes,
        'n_disponibles': estado.disponibles,
        'fecha_limite': estado.fecha_limite,
        'grilla': grilla_recuperos(request.user, estado),
    }
    return render(request, 'gravity/reservar_recupero.html', context)

@login_required
def marcar_vencimiento_visto(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    hoy = timezone.now().date()
    AusenciaTemporal.objects.filter(
        reserva__usuario=request.user,
        notificacion_vencimiento_vista=False,
        fecha__lt=hoy - timedelta(days=6),  # fecha_limite_recupero < hoy → vencida
    ).update(notificacion_vencimiento_vista=True)

    return JsonResponse({'success': True})

@login_required
def cerrar_modal_reserva_exitosa(request):
    """Limpia el modal de reserva exitosa de la sesión al hacer click en Entendido."""
    if request.method == 'POST':
        request.session.pop('reserva_exitosa', None)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)

@login_required
def cerrar_modal_ausencia_registrada(request):
    """Limpia el modal de ausencia registrada de la sesión."""
    if request.method == 'POST':
        request.session.pop('ausencia_registrada', None)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)

@login_required
def reservar_cupo_temporal(request, clase_id, fecha_str):
    """
    Los lugares sueltos (clase llena con alguien que avisó que falta) se reservan desde
    la grilla de Reservar clase como "una sola vez". Se conserva la URL por enlaces viejos.
    """
    clase = get_object_or_404(Clase, id=clase_id)
    params = {
        'tipo': clase.tipo,
        'sede': clase.direccion,
        'dia': clase.dia,
        'horario': clase.horario.strftime('%H:%M'),
        'es_temporal': '1',
    }
    return redirect(f"{reverse('gravity:reservar_clase')}?{urlencode(params)}")

@admin_required
def admin_reservar_para_usuario(request, clase_id=None, usuario_id=None):
    """
    Reservar para un alumno desde el panel: horario fijo, clase única o recupero
    (estas dos con fecha a elegir entre las próximas cuatro). Respeta el cupo y los
    duplicados; el plan y los recuperos disponibles se muestran como aviso, pero el
    estudio puede cargarla igual. La clase y el alumno pueden venir preseleccionados
    (por la URL o por ?clase / ?alumno).
    """
    ahora = timezone.now()
    if clase_id:
        get_object_or_404(Clase, id=clase_id, activa=True)
    else:
        clase_id = request.GET.get('clase') if str(request.GET.get('clase', '')).isdigit() else None
    if usuario_id:
        get_object_or_404(User, id=usuario_id, is_staff=False)
    else:
        usuario_id = request.GET.get('alumno') if str(request.GET.get('alumno', '')).isdigit() else None

    if request.method == 'POST':
        alumno = User.objects.filter(id=request.POST.get('usuario') or 0, is_staff=False, is_active=True).first()
        clase = Clase.objects.filter(id=request.POST.get('clase') or 0, activa=True).first()
        tipo_reserva = request.POST.get('tipo_reserva', 'recurrente')
        if tipo_reserva not in ('recurrente', 'temporal', 'recupero'):
            tipo_reserva = 'recurrente'
        notificar = request.POST.get('notificar_usuario') == 'on'
        usuario_id = alumno.id if alumno else usuario_id
        clase_id = clase.id if clase else clase_id

        error = None
        fecha = None
        if not alumno or not clase:
            error = 'Elegí un alumno y una clase.'
        elif tipo_reserva == 'recurrente':
            if Reserva.objects.filter(usuario=alumno, clase=clase, activa=True, fecha_unica__isnull=True).exists():
                error = (f'{alumno.get_full_name() or alumno.username} ya tiene una reserva activa en '
                         f'{clase.get_nombre_display()} {clase.dia} {clase.horario:%H:%M}.')
            elif clase.cupos_disponibles() <= 0:
                error = f'{clase.get_nombre_display()} {clase.dia} {clase.horario:%H:%M} no tiene lugares fijos libres.'
        else:
            fecha = _fecha_post(request, clase, ahora)
            if not fecha:
                error = 'Elegí una de las fechas de la clase.'
            elif Reserva.objects.filter(usuario=alumno, clase=clase, activa=True).filter(
                    Q(fecha_unica=fecha) | Q(fecha_unica__isnull=True)).exists():
                error = (f'{alumno.get_full_name() or alumno.username} ya tiene una reserva activa en esa '
                         f'clase el {fecha:%d/%m}.')
            elif clase.cupos_disponibles(fecha=fecha) <= 0:
                error = f'{clase.get_nombre_display()} del {fecha:%d/%m} no tiene lugar.'

        if error:
            messages.error(request, error)
        else:
            try:
                # Solo la creación va en la transacción: el email sale después del commit
                with transaction.atomic():
                    reserva = Reserva.objects.create(
                        usuario=alumno, clase=clase, fecha_unica=fecha,
                        es_recupero=tipo_reserva == 'recupero', creado_por=request.user,
                    )
            except IntegrityError:
                messages.error(request, 'Ese alumno ya tiene una reserva en esa clase.')
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                email_enviado = False
                if notificar and alumno.email:
                    try:
                        email_enviado = enviar_email_confirmacion_reserva_detallado(reserva)
                    except Exception as e:
                        logger.error(f'Error enviando email de confirmación (panel): {e}')
                que = {'recurrente': 'el horario fijo', 'temporal': f'una clase única el {fecha:%d/%m}' if fecha else '',
                       'recupero': f'un recupero el {fecha:%d/%m}' if fecha else ''}[tipo_reserva]
                texto = (f'Listo: reservaste {que} de {alumno.get_full_name() or alumno.username} en '
                         f'{clase.get_nombre_display()} {clase.dia} {clase.horario:%H:%M} ({clase.get_direccion_corta()}).')
                if notificar:
                    if email_enviado:
                        texto += f' Le avisamos a {alumno.email}.'
                    elif alumno.email:
                        texto += f' No se pudo mandar el email a {alumno.email}.'
                    else:
                        texto += ' No tiene email cargado para avisarle.'
                messages.success(request, texto)
                return _volver(request, reverse('gravity:admin_usuario_detalle', args=[alumno.id]))

    alumno = User.objects.filter(id=usuario_id, is_staff=False).first() if usuario_id else None
    grupos, datos_js = _opciones_clases(ahora)
    alumnos = [
        {'id': u.id, 'nombre': u.get_full_name() or u.username, 'email': u.email}
        for u in User.objects.filter(is_active=True, is_staff=False).order_by('first_name', 'last_name', 'username')
    ]
    return render(request, 'gravity/admin/admin_reservar_para_usuario.html', {
        'alumno': alumno,
        'info': info_alumno(alumno) if alumno else None,
        'alumnos': alumnos,
        'grupos': grupos,
        'datos_js': datos_js,
        'clase_elegida': str(request.POST.get('clase') or clase_id or ''),
        'tipo_elegido': request.POST.get('tipo_reserva', 'recurrente'),
        'fecha_elegida': request.POST.get('fecha', ''),
        'next': _next_seguro(request),
    })

# ==============================================================================
# GESTIÓN DE USUARIOS
# ==============================================================================

@admin_required
def admin_usuarios_lista(request):
    """
    Alumnos con buscador y filtros: activos (por defecto, sin los eliminados ni los
    desactivados), nuevos, sin plan, con deuda, desactivados y cuentas eliminadas.
    """
    filtro = request.GET.get('filtro', 'activos')
    if filtro == 'con_reservas':
        filtro = 'activos'
    buscar = request.GET.get('busqueda', '').strip()

    base = User.objects.filter(is_staff=False)
    if buscar:
        base = base.filter(
            Q(username__icontains=buscar) | Q(first_name__icontains=buscar) | Q(last_name__icontains=buscar)
            | Q(email__icontains=buscar) | Q(profile__telefono__icontains=normalizar_telefono(buscar) or buscar)
        )
    activos = base.filter(is_active=True)
    con_plan = PlanUsuario.objects.filter(activo=True).values('usuario_id')
    consultas = {
        'activos': activos,
        'nuevos': activos.filter(date_joined__gte=timezone.now() - timedelta(days=7)),
        'sin_plan': activos.exclude(id__in=con_plan),
        'con_deuda': activos.filter(estado_pago__saldo_actual__lt=0),
        'desactivados': base.filter(is_active=False).exclude(username__startswith='eliminado-'),
        'eliminados': base.filter(is_active=False, username__startswith='eliminado-'),
    }
    if filtro not in consultas:
        filtro = 'activos'
    textos = {'activos': 'Activos', 'nuevos': 'Nuevos', 'sin_plan': 'Sin plan', 'con_deuda': 'Con deuda',
              'desactivados': 'Desactivados', 'eliminados': 'Eliminados'}

    qs = consultas[filtro].select_related('profile', 'estado_pago').annotate(
        fijos=Count('reservas_pilates', filter=Q(reservas_pilates__activa=True, reservas_pilates__fecha_unica__isnull=True))
    ).order_by('-date_joined' if filtro == 'nuevos' else 'first_name', 'last_name', 'username')
    page_obj = Paginator(qs, 30).get_page(request.GET.get('page'))

    ids = [u.id for u in page_obj]
    planes = {}
    for pu in PlanUsuario.objects.filter(usuario_id__in=ids, activo=True).select_related('plan'):
        planes.setdefault(pu.usuario_id, pu.plan.nombre)
    filas = []
    for u in page_obj:
        perfil = getattr(u, 'profile', None)
        estado_pago = getattr(u, 'estado_pago', None)
        filas.append({
            'usuario': u,
            'plan': planes.get(u.id),
            'fijos': u.fijos,
            'saldo': estado_pago.saldo_actual if estado_pago else None,
            'salud': bool(perfil and perfil.tiene_lesiones),
            'telefono': perfil.telefono if perfil else '',
            'whatsapp': whatsapp_url(perfil.telefono) if perfil else '',
            'estado': estado_cuenta(u),
            'nuevo': u.date_joined >= timezone.now() - timedelta(days=7),
        })

    params = request.GET.copy()
    params.pop('page', None)
    sin_filtro = params.copy()
    sin_filtro.pop('filtro', None)
    chips = [{'clave': c, 'texto': textos[c], 'cantidad': consultas[c].count(), 'activo': c == filtro} for c in consultas]
    return render(request, 'gravity/admin/usuarios_lista.html', {
        'page_obj': page_obj,
        'filas': filas,
        'chips': chips,
        'filtro': filtro,
        'busqueda': buscar,
        'qs_pagina': params.urlencode(),
        'qs_sin_filtro': sin_filtro.urlencode(),
        'aqui': request.get_full_path(),
    })


@admin_required
def admin_usuario_detalle(request, usuario_id):
    """
    Ficha del alumno: contacto, plan y cuenta, próximas clases, horarios fijos,
    recuperos, asistencia, notas internas e historial. Lo que hace en su espacio
    lo calcula accounts/mi_espacio.py (el mismo cálculo que ve el alumno).
    """
    usuario = get_object_or_404(User.objects.select_related('estado_pago'), id=usuario_id, is_staff=False)
    perfil, _ = UserProfile.objects.get_or_create(user=usuario)
    hoy = timezone.localdate()

    activa = usuario.is_active
    mis = reservas_alumno(usuario) if activa else {'agenda': [], 'horarios': [], 'extras': []}
    historial = [
        {'reserva': r, 'estado': estado_reserva(r, hoy)}
        for r in usuario.reservas_pilates.filter(Q(activa=False) | Q(fecha_unica__lt=hoy))
        .select_related('clase').prefetch_related('cancelaciones_admin', 'notificaciones_cancelacion')
        .order_by('-fecha_modificacion')[:10]
    ]

    ids_reservas = usuario.reservas_pilates.values_list('id', flat=True)
    ausencias = sorted(
        [{'tipo': 'avisada', 'fecha': a.fecha, 'clase': a.reserva.clase}
         for a in AusenciaTemporal.objects.filter(reserva_id__in=ids_reservas).select_related('reserva__clase').order_by('-fecha')[:10]]
        + [{'tipo': 'sin_aviso', 'fecha': i.fecha, 'clase': i.reserva.clase}
           for i in Inasistencia.objects.filter(reserva_id__in=ids_reservas).select_related('reserva__clase').order_by('-fecha')[:10]],
        key=lambda x: x['fecha'], reverse=True,
    )[:10]
    hace_30 = hoy - timedelta(days=30)
    faltas_30 = (AusenciaTemporal.objects.filter(reserva_id__in=ids_reservas, fecha__gte=hace_30, fecha__lte=hoy).count()
                 + Inasistencia.objects.filter(reserva_id__in=ids_reservas, fecha__gte=hace_30).count())

    estado_pago = getattr(usuario, 'estado_pago', None)
    return render(request, 'gravity/admin/usuario_detalle.html', {
        'usuario': usuario,
        'perfil': perfil,
        'estado': estado_cuenta(usuario),
        'info': info_alumno(usuario),
        'proximas': mis['agenda'][:6],
        'horarios': mis['horarios'],
        'extras': mis['extras'],
        'historial': historial,
        'ausencias': ausencias,
        'faltas_30': faltas_30,
        'planes': PlanUsuario.objects.filter(usuario=usuario, activo=True).select_related('plan', 'creado_por'),
        'saldo': estado_pago.saldo_actual if estado_pago else None,
        'notas': notas_lista(perfil),
        'whatsapp': whatsapp_url(perfil.telefono),
        'invitacion_pendiente': tiene_invitacion_pendiente(usuario),
        'clave_inicial': request.session.pop(f'clave_inicial_{usuario.id}', None),
        'aqui': request.get_full_path(),
    })


@admin_required
def admin_usuario_editar(request, usuario_id):
    """Editar los datos del alumno (contacto, nacimiento, salud y primera clase)."""
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False, is_active=True)
    UserProfile.objects.get_or_create(user=usuario)
    form = AlumnoDatosForm(request.POST, usuario=usuario) if request.method == 'POST' else AlumnoDatosForm(usuario=usuario)
    if request.method == 'POST' and form.is_valid():
        email_anterior = usuario.email
        form.guardar()
        texto = f'Guardaste los datos de {usuario.get_full_name() or usuario.username}.'
        if usuario.email and usuario.email != email_anterior and tiene_invitacion_pendiente(usuario):
            if enviar_invitacion(usuario):
                texto += f' Le mandamos la invitación a {usuario.email}.'
        messages.success(request, texto)
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)
    return render(request, 'gravity/admin/usuario_editar.html', {'form': form, 'usuario': usuario})


@admin_required
@require_http_methods(["POST"])
def admin_usuario_reenviar_invitacion(request, usuario_id):
    """Reenvía el email para crear la contraseña a un alumno que todavía no la eligió."""
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False)
    if not tiene_invitacion_pendiente(usuario):
        messages.info(request, 'Este alumno ya tiene su contraseña.')
    elif not usuario.email:
        messages.error(request, 'No tiene email cargado. Agregalo en "Editar datos" para mandarle la invitación.')
    elif enviar_invitacion(usuario):
        messages.success(request, f'Le reenviamos la invitación a {usuario.email}. El enlace vale 7 días.')
    else:
        messages.error(request, 'No se pudo mandar el email. Probá de nuevo en un rato.')
    return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)


@superadmin_required
def admin_usuario_toggle_status(request, usuario_id):
    """
    Desactivar o reactivar la cuenta de un alumno (solo superadmin). Desactivar
    cancela sus reservas y planes; las deudas y los pagos se conservan. Primero se
    muestra qué se va a cancelar.
    """
    usuario = get_object_or_404(User.objects.select_related('estado_pago'), id=usuario_id, is_staff=False)
    clave, _, _ = estado_cuenta(usuario)
    if clave == 'eliminado':
        messages.error(request, 'Es una cuenta que el alumno eliminó: no se puede reactivar.')
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)
    nombre = usuario.get_full_name() or usuario.username

    if request.method == 'POST':
        if usuario.is_active:
            canceladas = desactivar_alumno(usuario, request.user, avisar=request.POST.get('avisar') == 'on')
            messages.success(request, f'Desactivaste la cuenta de {nombre}.'
                             + (f' Se cancelaron {canceladas} reserva{"s" if canceladas != 1 else ""}.' if canceladas else ''))
        else:
            usuario.is_active = True
            usuario.save(update_fields=['is_active'])
            EstadoPagoCliente.objects.filter(usuario=usuario).update(activo=True)
            messages.success(request, f'{nombre} vuelve a estar activo. Asignale un plan desde Pagos para que pueda reservar.')
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)

    estado_pago = getattr(usuario, 'estado_pago', None)
    return render(request, 'gravity/admin/usuario_estado.html', {
        'usuario': usuario,
        'cancela': que_se_cancela(usuario) if usuario.is_active else None,
        'saldo': estado_pago.saldo_actual if estado_pago else None,
    })


@admin_required
def admin_usuario_add_note(request, usuario_id):
    """Agregar una nota interna al alumno (con fecha y hora de Argentina y quién la escribió)."""
    if request.method != 'POST':
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario_id)
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False)
    perfil, _ = UserProfile.objects.get_or_create(user=usuario)
    texto = request.POST.get('nota', '').strip()
    if not texto:
        messages.error(request, 'Escribí la nota.')
    elif len(texto) > 500:
        messages.error(request, 'La nota es muy larga (hasta 500 caracteres).')
    else:
        agregar_nota(perfil, texto, request.user)
        messages.success(request, 'Guardaste la nota.')
    return redirect(reverse('gravity:admin_usuario_detalle', args=[usuario.id]) + '#notas')


# ==============================================================================
# AGREGAR USUARIOS AL SISTEMA
# ==============================================================================

@admin_required
def admin_agregar_usuario(request):
    """
    Alta de un alumno. Con email, le llega una invitación para crear su contraseña;
    sin email, se genera una contraseña inicial que se muestra una sola vez en su
    ficha para pasársela por WhatsApp. Después se le asigna el plan y se reserva.
    """
    form = AlumnoNuevoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        usuario, clave, invitado = crear_alumno(form.cleaned_data, request.user)
        nombre = usuario.get_full_name()
        if clave:
            request.session[f'clave_inicial_{usuario.id}'] = clave
            messages.success(request, f'Creaste la cuenta de {nombre}. Pasale su usuario y contraseña inicial por WhatsApp.')
        elif invitado:
            messages.success(request, f'Creaste la cuenta de {nombre}. Le mandamos la invitación a {usuario.email} para que cree su contraseña.')
        else:
            messages.warning(request, f'Creaste la cuenta de {nombre}, pero no se pudo mandar la invitación. Reenviala desde su ficha.')
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)
    return render(request, 'gravity/admin/agregar_cliente_form.html', {'form': form})

# ==============================================================================
# REPORTES Y ESTADÍSTICAS
# ==============================================================================

PERIODOS_REPORTE = [
    ('7', 'Últimos 7 días'),
    ('30', 'Últimos 30 días'),
    ('90', 'Últimos 90 días'),
    ('mes', 'Mes actual'),
    ('anio', 'Año actual'),
    ('personalizado', 'Personalizado'),
]

DIA_A_INDICE = {
    'Lunes': 0,
    'Martes': 1,
    'Miércoles': 2,
    'Jueves': 3,
    'Viernes': 4,
    'Sábado': 5,
}

MESES_CORTOS = [
    'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'
]


def _reportes_rango(request):
    """
    Interpreta los filtros de período del querystring.
    Devuelve (periodo, desde, hasta, etiqueta).
    """
    hoy = timezone.localtime(timezone.now()).date()
    periodo = request.GET.get('periodo', '30')

    def _parse_fecha(valor):
        try:
            return datetime.strptime(valor, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    if periodo == 'personalizado':
        desde = _parse_fecha(request.GET.get('desde')) or (hoy - timedelta(days=29))
        hasta = _parse_fecha(request.GET.get('hasta')) or hoy
        if desde > hasta:
            desde, hasta = hasta, desde
        etiqueta = f'{desde.strftime("%d/%m/%Y")} al {hasta.strftime("%d/%m/%Y")}'
    elif periodo == 'mes':
        desde, hasta = hoy.replace(day=1), hoy
        etiqueta = 'Mes actual'
    elif periodo == 'anio':
        desde, hasta = hoy.replace(month=1, day=1), hoy
        etiqueta = 'Año actual'
    else:
        if periodo not in ('7', '30', '90'):
            periodo = '30'
        dias = int(periodo)
        desde, hasta = hoy - timedelta(days=dias - 1), hoy
        etiqueta = f'Últimos {dias} días'

    return periodo, desde, hasta, etiqueta


def _reportes_periodo_anterior(desde, hasta):
    """Período inmediatamente anterior, de la misma cantidad de días."""
    dias = (hasta - desde).days + 1
    fin = desde - timedelta(days=1)
    return fin - timedelta(days=dias - 1), fin


def _variacion_porcentual(actual, anterior):
    """Variación % contra el período anterior. None si no hay base de comparación."""
    if not anterior:
        return None
    return round((float(actual) - float(anterior)) / float(anterior) * 100, 1)


def _ocurrencias_dia_semana(indice_dia, desde, hasta):
    """Cuántas veces cae ese día de la semana entre dos fechas (inclusive)."""
    if indice_dia is None or hasta < desde:
        return 0
    total_dias = (hasta - desde).days + 1
    semanas, resto = divmod(total_dias, 7)
    total = semanas
    for i in range(resto):
        if (desde + timedelta(days=i)).weekday() == indice_dia:
            total += 1
    return total


def _nivel_ocupacion(porcentaje):
    """Clasifica la ocupación para colorear la plantilla."""
    if porcentaje >= 100:
        return 'completo'
    if porcentaje >= 75:
        return 'alto'
    if porcentaje >= 50:
        return 'medio'
    return 'bajo'


def _kpi(titulo, valor, detalle, icono, sufijo='', actual=None, anterior=None,
         subir_es_bueno=True, es_dinero=False):
    """Arma una tarjeta de KPI con su comparación contra el período anterior."""
    variacion = _variacion_porcentual(actual, anterior) if actual is not None else None
    tarjeta = {
        'titulo': titulo,
        'valor': valor,
        'sufijo': sufijo,
        'detalle': detalle,
        'icono': icono,
        'es_dinero': es_dinero,
        'variacion': variacion,
        'variacion_abs': abs(variacion) if variacion is not None else None,
        'sube': variacion > 0 if variacion is not None else None,
        'es_bueno': None,
    }
    if variacion:
        tarjeta['es_bueno'] = (variacion > 0) == subir_es_bueno
    return tarjeta


def _restar_meses(fecha, meses):
    """Primer día del mes que está `meses` meses antes de `fecha`."""
    mes = fecha.month - meses
    anio = fecha.year
    while mes <= 0:
        mes += 12
        anio -= 1
    return date(anio, mes, 1)


def _fin_de_mes(primer_dia):
    """Último día del mes al que pertenece `primer_dia`."""
    ultimo = calendar.monthrange(primer_dia.year, primer_dia.month)[1]
    return date(primer_dia.year, primer_dia.month, ultimo)


def _plural(cantidad, singular, plural):
    """Devuelve la palabra que corresponde a la cantidad."""
    return singular if cantidad == 1 else plural


def _calcular_reportes(request):
    """
    Calcula todas las estadísticas del panel de reportes.
    Se usa tanto para la vista HTML como para la exportación a CSV.
    """
    hoy = timezone.localtime(timezone.now()).date()
    periodo, desde, hasta, periodo_label = _reportes_rango(request)
    desde_prev, hasta_prev = _reportes_periodo_anterior(desde, hasta)
    dias_periodo = (hasta - desde).days + 1
    puede_ver_pagos = ve_ingresos_estudio(request.user)

    # ===== FILTRO DE SEDE =====
    sedes = list(Clase.DIRECCIONES)
    sede = request.GET.get('sede', '')
    if sede not in [clave for clave, _ in sedes]:
        sede = ''
    sede_label = dict(sedes).get(sede, 'Todas las sedes')

    f_clase = {'direccion': sede} if sede else {}
    f_reserva = {'clase__direccion': sede} if sede else {}
    f_ausencia = {'reserva__clase__direccion': sede} if sede else {}

    # ==========================================================================
    # 1. OCUPACIÓN ACTUAL (foto de hoy, no depende del período)
    # ==========================================================================
    clases = list(
        Clase.objects.filter(activa=True, **f_clase)
        .annotate(
            ocupadas=Count(
                'reserva',
                filter=Q(reserva__activa=True, reserva__fecha_unica__isnull=True)
            )
        )
        .order_by('direccion', 'dia', 'horario')
    )

    detalle_clases = []
    for clase in clases:
        cupo = clase.cupo_maximo or 0
        porcentaje = round(clase.ocupadas / cupo * 100) if cupo else 0
        detalle_clases.append({
            'id': clase.id,
            'nombre': clase.get_nombre_display(),
            'tipo': clase.tipo,
            'sede_key': clase.direccion,
            'sede': clase.get_direccion_corta(),
            'dia': clase.dia,
            'horario': clase.horario,
            'cupo': cupo,
            'ocupadas': clase.ocupadas,
            'libres': max(cupo - clase.ocupadas, 0),
            'porcentaje': porcentaje,
            'nivel': _nivel_ocupacion(porcentaje),
        })

    total_clases = len(detalle_clases)
    total_cupos = sum(c['cupo'] for c in detalle_clases)
    total_ocupados = sum(c['ocupadas'] for c in detalle_clases)
    lugares_libres = max(total_cupos - total_ocupados, 0)
    ocupacion_general = round(total_ocupados / total_cupos * 100, 1) if total_cupos else 0

    clases_completas = [c for c in detalle_clases if c['cupo'] and c['libres'] == 0]
    clases_bajo_rendimiento = sorted(
        [c for c in detalle_clases if c['porcentaje'] < 50],
        key=lambda c: c['porcentaje']
    )
    ranking_clases = sorted(
        detalle_clases,
        key=lambda c: (-c['porcentaje'], -c['ocupadas'])
    )

    # ===== Agrupaciones (sede / tipo / día) =====
    reservas_periodo_qs = Reserva.objects.filter(
        fecha_reserva__date__gte=desde,
        fecha_reserva__date__lte=hasta,
        **f_reserva
    )
    nuevas_por_sede = dict(
        reservas_periodo_qs.values_list('clase__direccion').annotate(total=Count('id'))
    )
    nuevas_por_tipo = dict(
        reservas_periodo_qs.values_list('clase__tipo').annotate(total=Count('id'))
    )
    nuevas_por_dia = dict(
        reservas_periodo_qs.values_list('clase__dia').annotate(total=Count('id'))
    )

    def _resumen_grupo(nombre, items, reservas_periodo):
        cupos = sum(i['cupo'] for i in items)
        ocupadas = sum(i['ocupadas'] for i in items)
        porcentaje = round(ocupadas / cupos * 100, 1) if cupos else 0.0
        return {
            'nombre': nombre,
            'total_clases': len(items),
            'cupos': cupos,
            'ocupadas': ocupadas,
            'libres': max(cupos - ocupadas, 0),
            'porcentaje': porcentaje,
            'nivel': _nivel_ocupacion(porcentaje),
            'reservas_periodo': reservas_periodo,
        }

    stats_por_sede = [
        _resumen_grupo(
            nombre,
            [c for c in detalle_clases if c['sede_key'] == clave],
            nuevas_por_sede.get(clave, 0)
        )
        for clave, nombre in sedes
        if not sede or clave == sede
    ]

    stats_por_tipo = [
        _resumen_grupo(
            nombre,
            [c for c in detalle_clases if c['tipo'] == clave],
            nuevas_por_tipo.get(clave, 0)
        )
        for clave, nombre in Clase.TIPO_CLASES
    ]

    stats_por_dia = []
    for clave, nombre in DIAS_SEMANA_COMPLETOS:
        resumen = _resumen_grupo(
            nombre,
            [c for c in detalle_clases if c['dia'] == clave],
            nuevas_por_dia.get(clave, 0)
        )
        resumen['promedio_por_clase'] = (
            round(resumen['ocupadas'] / resumen['total_clases'], 1)
            if resumen['total_clases'] else 0
        )
        stats_por_dia.append(resumen)

    max_ocupadas_dia = max([d['ocupadas'] for d in stats_por_dia] or [0])
    for dia in stats_por_dia:
        dia['barra'] = round(dia['ocupadas'] / max_ocupadas_dia * 100) if max_ocupadas_dia else 0

    # ===== Agenda por día (versión vertical del mapa, para pantallas chicas) =====
    agenda_por_dia = [
        {
            'dia': nombre,
            'clases': sorted(
                [c for c in detalle_clases if c['dia'] == nombre],
                key=lambda c: c['horario']
            ),
        }
        for _, nombre in DIAS_SEMANA_COMPLETOS
    ]

    # ===== Mapa semanal (horario x día) =====
    horarios = sorted({c['horario'] for c in detalle_clases})
    dias_grilla = [nombre for _, nombre in DIAS_SEMANA_COMPLETOS]
    grilla_semanal = []
    for horario in horarios:
        grilla_semanal.append({
            'horario': horario,
            'celdas': [
                {
                    'dia': dia,
                    'clases': [
                        c for c in detalle_clases
                        if c['horario'] == horario and c['dia'] == dia
                    ],
                }
                for dia in dias_grilla
            ],
        })

    # ==========================================================================
    # 2. ACTIVIDAD DEL PERÍODO
    # ==========================================================================
    reservas_nuevas = reservas_periodo_qs.count()
    reservas_nuevas_prev = Reserva.objects.filter(
        fecha_reserva__date__gte=desde_prev,
        fecha_reserva__date__lte=hasta_prev,
        **f_reserva
    ).count()

    # Bajas: solo horarios fijos. Los recuperos y clases únicas que ya pasaron también
    # quedan inactivos (los limpia un comando), pero no son bajas.
    bajas = Reserva.objects.filter(
        activa=False,
        fecha_unica__isnull=True,
        fecha_modificacion__date__gte=desde,
        fecha_modificacion__date__lte=hasta,
        **f_reserva
    ).count()
    bajas_prev = Reserva.objects.filter(
        activa=False,
        fecha_unica__isnull=True,
        fecha_modificacion__date__gte=desde_prev,
        fecha_modificacion__date__lte=hasta_prev,
        **f_reserva
    ).count()

    # Recuperos y clases únicas del período: los que siguen en pie o ya se hicieron
    # (inactivos sin cancelación registrada), contados por la fecha de la clase.
    sueltas_periodo = sueltas_no_canceladas(Reserva.objects.filter(
        fecha_unica__gte=desde,
        fecha_unica__lte=hasta,
        **f_reserva
    )).filter(Q(activa=True) | Q(fecha_unica__lte=hoy)).distinct()
    recuperos = sueltas_periodo.filter(es_recupero=True).count()
    clases_extra = sueltas_periodo.filter(es_recupero=False).count()

    ausencias = AusenciaTemporal.objects.filter(
        fecha__gte=desde, fecha__lte=hasta, **f_ausencia
    ).count()
    ausencias_prev = AusenciaTemporal.objects.filter(
        fecha__gte=desde_prev, fecha__lte=hasta_prev, **f_ausencia
    ).count()
    inasistencias = Inasistencia.objects.filter(
        fecha__gte=desde, fecha__lte=hasta, **f_ausencia
    ).count()

    cancelaciones_admin = CancelacionAdmin.objects.filter(
        fecha_creacion__date__gte=desde,
        fecha_creacion__date__lte=hasta,
        **{f'reserva__{clave}': valor for clave, valor in f_reserva.items()}
    ).count()

    # Asistencia estimada: se cuentan las veces que cada reserva activa tuvo
    # clase dentro del período y se descuentan ausencias e inasistencias.
    hasta_asistencia = min(hasta, hoy)
    clases_previstas = sueltas_periodo.filter(fecha_unica__lte=hasta_asistencia).count()
    for reserva in Reserva.objects.filter(
        activa=True, fecha_unica__isnull=True, **f_reserva
    ).select_related('clase'):
        inicio = max(desde, timezone.localtime(reserva.fecha_reserva).date())
        clases_previstas += _ocurrencias_dia_semana(
            DIA_A_INDICE.get(reserva.clase.dia), inicio, hasta_asistencia
        )

    faltas = ausencias + inasistencias
    asistencias_estimadas = max(clases_previstas - faltas, 0)
    tasa_asistencia = (
        round(asistencias_estimadas / clases_previstas * 100, 1)
        if clases_previstas else 0
    )
    tasa_ausentismo = round(100 - tasa_asistencia, 1) if clases_previstas else 0

    # ==========================================================================
    # 3. CLIENTES
    # ==========================================================================
    clientes_qs = User.objects.filter(is_staff=False)
    q_reserva_activa = Q(reservas_pilates__activa=True)
    if sede:
        q_reserva_activa &= Q(reservas_pilates__clase__direccion=sede)

    total_clientes = clientes_qs.filter(is_active=True).count()
    clientes_activos = clientes_qs.filter(is_active=True).filter(
        q_reserva_activa
    ).distinct().count()
    clientes_sin_reserva = max(total_clientes - clientes_activos, 0)
    # Las cuentas eliminadas por el alumno quedan inactivas como "eliminado-<id>"
    clientes_eliminados = clientes_qs.filter(is_active=False, username__startswith='eliminado-').count()
    clientes_desactivados = clientes_qs.filter(is_active=False).count() - clientes_eliminados

    nuevos_clientes = clientes_qs.filter(
        date_joined__date__gte=desde, date_joined__date__lte=hasta
    ).count()
    nuevos_clientes_prev = clientes_qs.filter(
        date_joined__date__gte=desde_prev, date_joined__date__lte=hasta_prev
    ).count()

    # Para el ranking se cuentan solo las reservas fijas (no los recuperos puntuales)
    q_reserva_fija = q_reserva_activa & Q(reservas_pilates__fecha_unica__isnull=True)
    top_clientes = list(
        clientes_qs.filter(is_active=True)
        .annotate(total_reservas=Count('reservas_pilates', filter=q_reserva_fija, distinct=True))
        .filter(total_reservas__gt=0)
        .order_by('-total_reservas', 'last_name', 'username')[:8]
    )

    q_ausencia_periodo = Q(
        reservas_pilates__ausencias_temporales__fecha__gte=desde,
        reservas_pilates__ausencias_temporales__fecha__lte=hasta,
    )
    q_inasistencia_periodo = Q(
        reservas_pilates__inasistencias__fecha__gte=desde,
        reservas_pilates__inasistencias__fecha__lte=hasta,
    )
    if sede:
        q_ausencia_periodo &= Q(reservas_pilates__clase__direccion=sede)
        q_inasistencia_periodo &= Q(reservas_pilates__clase__direccion=sede)

    clientes_faltas = []
    for cliente in clientes_qs.annotate(
        total_ausencias=Count('reservas_pilates__ausencias_temporales',
                              filter=q_ausencia_periodo, distinct=True),
        total_inasistencias=Count('reservas_pilates__inasistencias',
                                  filter=q_inasistencia_periodo, distinct=True),
    ):
        total = cliente.total_ausencias + cliente.total_inasistencias
        if total:
            clientes_faltas.append({
                'id': cliente.id,
                'nombre': cliente.get_full_name() or cliente.username,
                'ausencias': cliente.total_ausencias,
                'inasistencias': cliente.total_inasistencias,
                'total': total,
            })
    clientes_faltas.sort(key=lambda c: (-c['total'], c['nombre']))
    clientes_faltas = clientes_faltas[:6]

    # Antigüedad promedio de los clientes activos, en meses
    fechas_alta = list(
        clientes_qs.filter(is_active=True).values_list('date_joined', flat=True)
    )
    antiguedad_promedio = (
        round(sum((hoy - timezone.localtime(fecha).date()).days for fecha in fechas_alta)
              / len(fechas_alta) / 30, 1)
        if fechas_alta else 0
    )

    # ==========================================================================
    # 4. PLANES
    # ==========================================================================
    clientes_con_plan = set(
        PlanUsuario.objects.filter(
            activo=True, usuario__is_active=True, usuario__is_staff=False
        ).values_list('usuario_id', flat=True)
    )

    distribucion_planes = []
    for plan in PlanPago.objects.filter(activo=True).order_by('clases_por_semana'):
        cantidad = PlanUsuario.objects.filter(
            plan=plan, activo=True, usuario__is_active=True, usuario__is_staff=False
        ).values('usuario').distinct().count()
        distribucion_planes.append({
            'nombre': plan.nombre,
            'clases_semana': plan.clases_por_semana,
            'precio': plan.precio_mensual,
            'cantidad': cantidad,
            'facturacion': plan.precio_mensual * cantidad,
        })
    max_plan = max([p['cantidad'] for p in distribucion_planes] or [0])
    for plan in distribucion_planes:
        plan['barra'] = round(plan['cantidad'] / max_plan * 100) if max_plan else 0

    clientes_sin_plan = max(total_clientes - len(clientes_con_plan), 0)
    facturacion_esperada = sum(
        (p['facturacion'] for p in distribucion_planes), Decimal('0')
    )

    solicitudes_periodo = list(
        SolicitudCambioPlan.objects.filter(
            fecha_solicitud__date__gte=desde, fecha_solicitud__date__lte=hasta
        ).select_related('plan_actual', 'plan_solicitado')
    )
    solicitudes = {
        'total': len(solicitudes_periodo),
        'pendientes': SolicitudCambioPlan.objects.filter(estado='pendiente').count(),
        'aprobadas': len([s for s in solicitudes_periodo if s.estado == 'aprobada']),
        'rechazadas': len([s for s in solicitudes_periodo if s.estado == 'rechazada']),
        'upgrades': len([s for s in solicitudes_periodo if s.es_upgrade()]),
        'downgrades': len([s for s in solicitudes_periodo if s.es_downgrade()]),
    }

    # ==========================================================================
    # 5. FINANZAS (solo para admins con permiso)
    # ==========================================================================
    finanzas = None
    if puede_ver_pagos:
        pagos_periodo = RegistroPago.objects.filter(
            estado='confirmado', fecha_pago__gte=desde, fecha_pago__lte=hasta
        )
        ingresos = pagos_periodo.aggregate(total=Sum('monto'))['total'] or Decimal('0')
        cantidad_pagos = pagos_periodo.count()
        ingresos_prev = RegistroPago.objects.filter(
            estado='confirmado', fecha_pago__gte=desde_prev, fecha_pago__lte=hasta_prev
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

        metodos_pago = []
        for clave, nombre in RegistroPago.TIPOS_PAGO:
            datos_metodo = pagos_periodo.filter(tipo_pago=clave).aggregate(
                total=Sum('monto'), cantidad=Count('id')
            )
            total_metodo = datos_metodo['total'] or Decimal('0')
            metodos_pago.append({
                'nombre': nombre,
                'total': total_metodo,
                'cantidad': datos_metodo['cantidad'] or 0,
                'porcentaje': (
                    round(float(total_metodo) / float(ingresos) * 100, 1) if ingresos else 0
                ),
            })

        # Evolución de los últimos 6 meses: facturado (deudas) vs cobrado (pagos)
        primer_dia_mes = hoy.replace(day=1)
        evolucion_meses = []
        for i in range(5, -1, -1):
            inicio_mes = _restar_meses(primer_dia_mes, i)
            fin_mes = _fin_de_mes(inicio_mes)
            cobrado = RegistroPago.objects.filter(
                estado='confirmado', fecha_pago__gte=inicio_mes, fecha_pago__lte=fin_mes
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
            facturado = DeudaMensual.objects.filter(mes_año=inicio_mes).aggregate(
                total=Sum('monto_original')
            )['total'] or Decimal('0')
            evolucion_meses.append({
                'label': f'{MESES_CORTOS[inicio_mes.month - 1]} {str(inicio_mes.year)[2:]}',
                'cobrado': cobrado,
                'facturado': facturado,
                'es_mes_actual': inicio_mes == primer_dia_mes,
            })
        max_mes = max(
            [float(m['cobrado']) for m in evolucion_meses]
            + [float(m['facturado']) for m in evolucion_meses]
            + [0]
        )
        for mes in evolucion_meses:
            mes['barra_cobrado'] = round(float(mes['cobrado']) / max_mes * 100) if max_mes else 0
            mes['barra_facturado'] = round(float(mes['facturado']) / max_mes * 100) if max_mes else 0

        # Estado de cuentas de los clientes
        estados = list(
            EstadoPagoCliente.objects.select_related('usuario', 'plan_actual')
            .filter(usuario__is_active=True, usuario__is_staff=False)
        )
        con_deuda = [e for e in estados if e.saldo_actual < 0]
        deuda_total = sum((abs(e.saldo_actual) for e in con_deuda), Decimal('0'))
        saldo_a_favor = sum(
            (e.saldo_actual for e in estados if e.saldo_actual > 0), Decimal('0')
        )
        top_deudores = [
            {
                'id': estado.usuario_id,
                'nombre': estado.get_nombre_completo(),
                'deuda': abs(estado.saldo_actual),
                'plan': estado.plan_actual.nombre if estado.plan_actual else 'Sin plan',
                'meses_atraso': estado.get_meses_atrasado(),
            }
            for estado in sorted(con_deuda, key=lambda e: e.saldo_actual)[:6]
        ]

        # Cobranza del mes en curso
        deuda_mes = DeudaMensual.objects.filter(mes_año=primer_dia_mes).aggregate(
            facturado=Sum('monto_original'), pendiente=Sum('monto_pendiente')
        )
        facturado_mes = deuda_mes['facturado'] or Decimal('0')
        pendiente_mes = deuda_mes['pendiente'] or Decimal('0')
        cobrado_mes = facturado_mes - pendiente_mes
        tasa_cobranza = (
            round(float(cobrado_mes) / float(facturado_mes) * 100, 1)
            if facturado_mes else 0
        )
        cuotas_vencidas = DeudaMensual.objects.filter(
            estado__in=['pendiente', 'vencido', 'parcial'],
            fecha_vencimiento__lt=hoy
        ).count()

        finanzas = {
            'ingresos': ingresos,
            'ingresos_prev': ingresos_prev,
            'cantidad_pagos': cantidad_pagos,
            'ticket_promedio': (ingresos / cantidad_pagos) if cantidad_pagos else Decimal('0'),
            'metodos_pago': metodos_pago,
            'evolucion_meses': evolucion_meses,
            'deuda_total': deuda_total,
            'saldo_a_favor': saldo_a_favor,
            'clientes_con_deuda': len(con_deuda),
            'clientes_al_dia': len([e for e in estados if e.saldo_actual >= 0 and e.plan_actual]),
            'top_deudores': top_deudores,
            'facturado_mes': facturado_mes,
            'cobrado_mes': cobrado_mes,
            'pendiente_mes': pendiente_mes,
            'tasa_cobranza': tasa_cobranza,
            'cuotas_vencidas': cuotas_vencidas,
            'facturacion_esperada': facturacion_esperada,
            'ingreso_por_cliente': (ingresos / clientes_activos) if clientes_activos else Decimal('0'),
        }

    # ==========================================================================
    # 6. TARJETAS DE INDICADORES
    # ==========================================================================
    kpis = [
        _kpi(
            'Ocupación general', ocupacion_general,
            f'{total_ocupados} de {total_cupos} lugares ocupados',
            'ocupacion', sufijo='%'
        ),
        _kpi(
            'Reservas nuevas', reservas_nuevas,
            f'{bajas} {_plural(bajas, "baja", "bajas")} en el período',
            'reservas', actual=reservas_nuevas, anterior=reservas_nuevas_prev
        ),
        _kpi(
            'Clientes activos', clientes_activos,
            f'{clientes_sin_reserva} sin reserva activa',
            'clientes'
        ),
        _kpi(
            'Clientes nuevos', nuevos_clientes,
            f'Antigüedad promedio: {antiguedad_promedio} meses',
            'nuevos', actual=nuevos_clientes, anterior=nuevos_clientes_prev
        ),
        _kpi(
            'Asistencia estimada', tasa_asistencia,
            f'{ausencias} con aviso · {inasistencias} sin aviso',
            'asistencia', sufijo='%'
        ),
        _kpi(
            'Recuperos', recuperos,
            f'{clases_extra} {_plural(clases_extra, "clase única", "clases únicas")} · '
            f'{ausencias} {_plural(ausencias, "ausencia avisada", "ausencias avisadas")}',
            'recuperos'
        ),
    ]

    if puede_ver_pagos:
        kpis.append(_kpi(
            'Ingresos del período', finanzas['ingresos'],
            f'{finanzas["cantidad_pagos"]} {_plural(finanzas["cantidad_pagos"], "pago registrado", "pagos registrados")}',
            'ingresos', actual=finanzas['ingresos'], anterior=finanzas['ingresos_prev'],
            es_dinero=True
        ))
        kpis.append(_kpi(
            'Deuda acumulada', finanzas['deuda_total'],
            f'{finanzas["clientes_con_deuda"]} {_plural(finanzas["clientes_con_deuda"], "cliente", "clientes")} con saldo pendiente',
            'deuda', es_dinero=True
        ))

    # ==========================================================================
    # 7. ALERTAS Y RECOMENDACIONES
    # ==========================================================================
    alertas = []

    for clase in clases_bajo_rendimiento[:3]:
        alertas.append({
            'nivel': 'atencion',
            'titulo': f'{clase["nombre"]} · {clase["dia"]} {clase["horario"].strftime("%H:%M")}',
            'detalle': (
                f'Solo {clase["ocupadas"]} de {clase["cupo"]} lugares ocupados '
                f'({clase["porcentaje"]}%) en {clase["sede"]}. Conviene promocionar el '
                f'horario o reagrupar alumnas.'
            ),
        })

    if clases_completas:
        horarios_completos = ', '.join(
            f'{c["dia"]} {c["horario"].strftime("%H:%M")}' for c in clases_completas[:4]
        )
        alertas.append({
            'nivel': 'exito',
            'titulo': (
                f'{len(clases_completas)} '
                f'{_plural(len(clases_completas), "clase con cupo completo", "clases con cupo completo")}'
            ),
            'detalle': f'{horarios_completos}. Hay demanda para abrir un horario nuevo o sumar cupos.',
        })

    if solicitudes['pendientes'] and request.user.is_superuser:
        alertas.append({
            'nivel': 'atencion',
            'titulo': (
                f'{solicitudes["pendientes"]} '
                f'{_plural(solicitudes["pendientes"], "solicitud de cambio de plan", "solicitudes de cambio de plan")} sin resolver'
            ),
            'detalle': 'Resolvelas para que los planes y la facturación queden al día.',
        })

    recuperos_vigentes = AusenciaTemporal.objects.filter(
        reserva__activa=True,
        reserva__fecha_unica__isnull=True,
        fecha__gte=hoy - timedelta(days=6),
        fecha__lte=hoy,
        **f_ausencia
    ).count()
    if recuperos_vigentes:
        alertas.append({
            'nivel': 'info',
            'titulo': (
                f'{recuperos_vigentes} '
                f'{_plural(recuperos_vigentes, "recupero con plazo vigente", "recuperos con plazo vigente")}'
            ),
            'detalle': 'Ausencias avisadas que todavía pueden recuperarse dentro de los 6 días.',
        })

    if clientes_sin_reserva:
        alertas.append({
            'nivel': 'atencion',
            'titulo': (
                f'{clientes_sin_reserva} '
                f'{_plural(clientes_sin_reserva, "cliente sin reserva activa", "clientes sin reserva activa")}'
            ),
            'detalle': 'Cuentas activas que hoy no ocupan ningún cupo: buen objetivo para reactivar.',
        })

    if puede_ver_pagos and finanzas['clientes_con_deuda']:
        alertas.append({
            'nivel': 'critico',
            'titulo': (
                f'{finanzas["clientes_con_deuda"]} '
                f'{_plural(finanzas["clientes_con_deuda"], "cliente con deuda", "clientes con deuda")}'
            ),
            'detalle': (
                f'Total pendiente de cobro: ${fmt_pesos(finanzas["deuda_total"])}. '
                f'{finanzas["cuotas_vencidas"]} '
                f'{_plural(finanzas["cuotas_vencidas"], "cuota vencida", "cuotas vencidas")}.'
            ),
        })

    if not alertas:
        alertas.append({
            'nivel': 'exito',
            'titulo': 'Todo en orden',
            'detalle': 'No hay clases con baja ocupación ni pendientes destacados en este período.',
        })

    # Querystring para conservar los filtros en los enlaces (exportar, imprimir)
    filtros_qs = f'periodo={periodo}&desde={desde.isoformat()}&hasta={hasta.isoformat()}'
    if sede:
        filtros_qs += f'&sede={sede}'

    return {
        # Filtros
        'periodo': periodo,
        'periodos': PERIODOS_REPORTE,
        'periodo_label': periodo_label,
        'desde': desde,
        'hasta': hasta,
        'desde_prev': desde_prev,
        'hasta_prev': hasta_prev,
        'dias_periodo': dias_periodo,
        'sede': sede,
        'sedes': sedes,
        'sede_label': sede_label,
        'filtros_qs': filtros_qs,
        'hoy': hoy,
        'puede_ver_pagos': puede_ver_pagos,
        # Indicadores y alertas
        'kpis': kpis,
        'alertas': alertas,
        # Ocupación
        'total_clases': total_clases,
        'total_cupos': total_cupos,
        'total_ocupados': total_ocupados,
        'lugares_libres': lugares_libres,
        'ocupacion_general': ocupacion_general,
        'detalle_clases': detalle_clases,
        'ranking_clases': ranking_clases,
        'clases_completas': clases_completas,
        'clases_bajo_rendimiento': clases_bajo_rendimiento,
        'stats_por_sede': stats_por_sede,
        'stats_por_tipo': stats_por_tipo,
        'stats_por_dia': stats_por_dia,
        'dias_grilla': dias_grilla,
        'grilla_semanal': grilla_semanal,
        'agenda_por_dia': agenda_por_dia,
        # Actividad del período
        'reservas_nuevas': reservas_nuevas,
        'reservas_nuevas_prev': reservas_nuevas_prev,
        'bajas': bajas,
        'bajas_prev': bajas_prev,
        'saldo_neto_reservas': reservas_nuevas - bajas,
        'recuperos': recuperos,
        'clases_extra': clases_extra,
        'ausencias': ausencias,
        'ausencias_prev': ausencias_prev,
        'inasistencias': inasistencias,
        'cancelaciones_admin': cancelaciones_admin,
        'clases_previstas': clases_previstas,
        'asistencias_estimadas': asistencias_estimadas,
        'tasa_asistencia': tasa_asistencia,
        'tasa_ausentismo': tasa_ausentismo,
        # Clientes
        'total_clientes': total_clientes,
        'clientes_activos': clientes_activos,
        'clientes_sin_reserva': clientes_sin_reserva,
        'clientes_desactivados': clientes_desactivados,
        'clientes_eliminados': clientes_eliminados,
        'nuevos_clientes': nuevos_clientes,
        'nuevos_clientes_prev': nuevos_clientes_prev,
        'antiguedad_promedio': antiguedad_promedio,
        'top_clientes': top_clientes,
        'clientes_faltas': clientes_faltas,
        # Planes
        'distribucion_planes': distribucion_planes,
        'clientes_sin_plan': clientes_sin_plan,
        'facturacion_esperada': facturacion_esperada if puede_ver_pagos else None,
        'solicitudes': solicitudes,
        # Finanzas
        'finanzas': finanzas,
    }


@admin_required
def admin_reportes(request):
    """
    Panel de estadísticas del estudio: ocupación, actividad, clientes,
    planes y finanzas, filtrable por período y por sede.
    """
    return render(request, 'gravity/admin/reportes.html', _calcular_reportes(request))


@admin_required
def admin_reportes_exportar(request):
    """
    Exporta a CSV las estadísticas del período y la sede seleccionados.
    """
    datos = _calcular_reportes(request)

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    nombre_archivo = f'estadisticas_gravity_{datos["desde"]}_{datos["hasta"]}.csv'
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    # BOM para que Excel abra bien los acentos
    respuesta.write('﻿')

    escritor = csv.writer(respuesta, delimiter=';')

    def seccion(titulo, cabeceras):
        escritor.writerow([])
        escritor.writerow([titulo.upper()])
        escritor.writerow(cabeceras)

    escritor.writerow(['Estadísticas Pilates Gravity'])
    escritor.writerow(['Período', datos['periodo_label']])
    escritor.writerow(['Desde', datos['desde'].strftime('%d/%m/%Y'),
                       'Hasta', datos['hasta'].strftime('%d/%m/%Y')])
    escritor.writerow(['Sede', datos['sede_label']])
    escritor.writerow(['Generado', timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')])

    seccion('Resumen general', ['Indicador', 'Valor'])
    resumen = [
        ('Clases activas', datos['total_clases']),
        ('Cupos totales', datos['total_cupos']),
        ('Lugares ocupados', datos['total_ocupados']),
        ('Lugares libres', datos['lugares_libres']),
        ('Ocupación general (%)', datos['ocupacion_general']),
        ('Reservas nuevas', datos['reservas_nuevas']),
        ('Reservas dadas de baja', datos['bajas']),
        ('Recuperos', datos['recuperos']),
        ('Clases únicas', datos['clases_extra']),
        ('Ausencias avisadas', datos['ausencias']),
        ('Inasistencias sin aviso', datos['inasistencias']),
        ('Asistencia estimada (%)', datos['tasa_asistencia']),
        ('Clientes activos', datos['clientes_activos']),
        ('Clientes sin reserva activa', datos['clientes_sin_reserva']),
        ('Clientes nuevos', datos['nuevos_clientes']),
        ('Clientes sin plan', datos['clientes_sin_plan']),
    ]
    if datos['puede_ver_pagos']:
        finanzas = datos['finanzas']
        resumen += [
            ('Ingresos del período', finanzas['ingresos']),
            ('Cantidad de pagos', finanzas['cantidad_pagos']),
            ('Ticket promedio', round(finanzas['ticket_promedio'])),
            ('Deuda acumulada', finanzas['deuda_total']),
            ('Clientes con deuda', finanzas['clientes_con_deuda']),
            ('Cobranza del mes (%)', finanzas['tasa_cobranza']),
            ('Facturación mensual esperada', finanzas['facturacion_esperada']),
        ]
    for etiqueta, valor in resumen:
        escritor.writerow([etiqueta, valor])

    seccion('Ocupación por clase',
            ['Clase', 'Sede', 'Día', 'Horario', 'Cupo', 'Ocupados', 'Libres', 'Ocupación (%)'])
    for clase in datos['ranking_clases']:
        escritor.writerow([
            clase['nombre'], clase['sede'], clase['dia'],
            clase['horario'].strftime('%H:%M'), clase['cupo'],
            clase['ocupadas'], clase['libres'], clase['porcentaje'],
        ])

    seccion('Ocupación por sede',
            ['Sede', 'Clases', 'Cupos', 'Ocupados', 'Ocupación (%)', 'Reservas del período'])
    for item in datos['stats_por_sede']:
        escritor.writerow([item['nombre'], item['total_clases'], item['cupos'],
                           item['ocupadas'], item['porcentaje'], item['reservas_periodo']])

    seccion('Ocupación por tipo de clase',
            ['Tipo', 'Clases', 'Cupos', 'Ocupados', 'Ocupación (%)', 'Reservas del período'])
    for item in datos['stats_por_tipo']:
        escritor.writerow([item['nombre'], item['total_clases'], item['cupos'],
                           item['ocupadas'], item['porcentaje'], item['reservas_periodo']])

    seccion('Actividad por día',
            ['Día', 'Clases', 'Cupos', 'Ocupados', 'Promedio por clase', 'Reservas del período'])
    for item in datos['stats_por_dia']:
        escritor.writerow([item['nombre'], item['total_clases'], item['cupos'],
                           item['ocupadas'], item['promedio_por_clase'], item['reservas_periodo']])

    seccion('Clientes con más reservas', ['Cliente', 'Reservas activas'])
    for cliente in datos['top_clientes']:
        escritor.writerow([cliente.get_full_name() or cliente.username, cliente.total_reservas])

    seccion('Clientes con más faltas', ['Cliente', 'Con aviso', 'Sin aviso', 'Total'])
    for cliente in datos['clientes_faltas']:
        escritor.writerow([cliente['nombre'], cliente['ausencias'],
                           cliente['inasistencias'], cliente['total']])

    seccion('Distribución de planes',
            ['Plan', 'Clases por semana', 'Clientes', 'Precio mensual', 'Facturación esperada'])
    for plan in datos['distribucion_planes']:
        escritor.writerow([plan['nombre'], plan['clases_semana'], plan['cantidad'],
                           plan['precio'], plan['facturacion']])
    escritor.writerow(['Sin plan asignado', '', datos['clientes_sin_plan'], '', ''])

    if datos['puede_ver_pagos']:
        finanzas = datos['finanzas']
        seccion('Ingresos por método de pago', ['Método', 'Pagos', 'Total', '% del período'])
        for metodo in finanzas['metodos_pago']:
            escritor.writerow([metodo['nombre'], metodo['cantidad'],
                               metodo['total'], metodo['porcentaje']])

        seccion('Evolución mensual', ['Mes', 'Facturado', 'Cobrado'])
        for mes in finanzas['evolucion_meses']:
            escritor.writerow([mes['label'], mes['facturado'], mes['cobrado']])

        seccion('Principales deudores', ['Cliente', 'Plan', 'Deuda', 'Meses de atraso'])
        for deudor in finanzas['top_deudores']:
            escritor.writerow([deudor['nombre'], deudor['plan'],
                               deudor['deuda'], deudor['meses_atraso']])

    return respuesta

# ==============================================================================
# VISTAS DEL SISTEMA DE PAGOS
# ==============================================================================

MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
                'septiembre', 'octubre', 'noviembre', 'diciembre']


@admin_required
def admin_pagos_vista_principal(request):
    """
    Pagos "para cobrar": alumnos activos con su saldo. Por defecto, los que deben,
    de mayor a menor deuda; también al día, a favor, sin plan y todos. Arriba, lo
    que falta cobrar del mes (todo el equipo) y lo cobrado (solo superadmin).
    """
    from django.db.models.functions import Coalesce
    from django.db.models import Value, DecimalField

    hoy = timezone.localdate()
    mes_actual = hoy.replace(day=1)
    ve_ingresos = ve_ingresos_estudio(request.user)
    buscar = request.GET.get('buscar', '').strip()
    filtro = request.GET.get('estado', 'debe')

    alumnos = User.objects.filter(is_staff=False, is_active=True).annotate(
        saldo=Coalesce('estado_pago__saldo_actual', Value(Decimal('0')), output_field=DecimalField())
    )
    if buscar:
        alumnos = alumnos.filter(
            Q(first_name__icontains=buscar) | Q(last_name__icontains=buscar)
            | Q(username__icontains=buscar) | Q(email__icontains=buscar)
        )
    con_plan = PlanUsuario.objects.filter(activo=True).values('usuario_id')
    consultas = {
        'debe': alumnos.filter(saldo__lt=0).order_by('saldo', 'first_name'),
        'al_dia': alumnos.filter(saldo=0, id__in=con_plan).order_by('first_name', 'last_name'),
        'a_favor': alumnos.filter(saldo__gt=0).order_by('-saldo', 'first_name'),
        'sin_plan': alumnos.exclude(id__in=con_plan).order_by('first_name', 'last_name'),
        'todos': alumnos.order_by('first_name', 'last_name'),
    }
    if filtro not in consultas:
        filtro = 'debe'
    textos = {'debe': 'Deben', 'al_dia': 'Al día', 'a_favor': 'A favor', 'sin_plan': 'Sin plan', 'todos': 'Todos'}
    chips = [{'clave': c, 'texto': textos[c], 'cantidad': consultas[c].count(), 'activo': c == filtro} for c in consultas]

    page_obj = Paginator(consultas[filtro].select_related('profile'), 30).get_page(request.GET.get('page'))
    ids = [u.id for u in page_obj]
    planes = {}
    for pu in PlanUsuario.objects.filter(usuario_id__in=ids, activo=True).select_related('plan'):
        planes.setdefault(pu.usuario_id, []).append(pu.plan)
    ultimos = {}
    for pago in RegistroPago.objects.filter(cliente_id__in=ids, estado='confirmado').order_by('cliente_id', '-fecha_pago', '-id'):
        ultimos.setdefault(pago.cliente_id, pago)
    filas = [{
        'usuario': u,
        'saldo': u.saldo,
        'deuda': -u.saldo if u.saldo < 0 else Decimal('0'),
        'planes': planes.get(u.id, []),
        'cuota': sum((p.precio_mensual for p in planes.get(u.id, [])), Decimal('0')),
        'ultimo_pago': ultimos.get(u.id),
    } for u in page_obj]

    deudores = User.objects.filter(is_staff=False, is_active=True, estado_pago__saldo_actual__lt=0)
    total_deuda = deudores.aggregate(t=Sum('estado_pago__saldo_actual'))['t'] or Decimal('0')
    falta_mes = DeudaMensual.objects.filter(
        mes_año=mes_actual, usuario__is_active=True, usuario__is_staff=False
    ).aggregate(t=Sum('monto_pendiente'))['t'] or Decimal('0')
    ingresos_mes = RegistroPago.objects.filter(
        fecha_pago__gte=mes_actual, estado='confirmado'
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    params = request.GET.copy()
    params.pop('page', None)
    sin_estado = params.copy()
    sin_estado.pop('estado', None)
    return render(request, 'gravity/admin/pagos_principal.html', {
        'page_obj': page_obj,
        'filas': filas,
        'chips': chips,
        'filtro_estado': filtro,
        'buscar_nombre': buscar,
        'qs_pagina': params.urlencode(),
        'qs_sin_estado': sin_estado.urlencode(),
        'mes_texto': MESES_LARGOS[hoy.month - 1],
        'falta_mes': falta_mes,
        'clientes_con_deuda': deudores.count(),
        'total_deuda': -total_deuda,
        'ingresos_mes': ingresos_mes if ve_ingresos else None,
        've_ingresos': ve_ingresos,
        'puede_configurar_planes': puede_corregir_cuentas(request.user),
        'planes_activos': PlanPago.objects.filter(activo=True).order_by('clases_por_semana'),
        'aqui': request.get_full_path(),
    })


@admin_required
def admin_pagos_registrar_pago(request, cliente_id):
    """
    Registrar un pago. Sugiere montos (lo que debe, la cuota del plan y la cuota en
    efectivo con 10% menos) y el recibo por email es opcional. El saldo y las
    cuotas se actualizan solos al guardar (RegistroPago.save).
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)
    estado_pago, _ = EstadoPagoCliente.objects.get_or_create(usuario=cliente, defaults={'activo': True})
    hoy = timezone.localdate()
    plan = estado_pago.plan_actual

    if request.method == 'POST':
        form = estilo_panel(RegistroPagoForm(request.POST))
        if form.is_valid():
            pago = form.save(commit=False)
            pago.cliente = cliente
            pago.registrado_por = request.user
            pago.save()
            texto = f'Registraste un pago de ${fmt_pesos(pago.monto)} de {cliente.get_full_name() or cliente.username}.'
            if request.POST.get('enviar_recibo') == 'on' and cliente.email:
                try:
                    if enviar_email_confirmacion_pago_completo(pago):
                        texto += f' Le mandamos el recibo a {cliente.email}.'
                except Exception as e:
                    logger.error(f'Error enviando el recibo del pago {pago.id}: {e}')
                    texto += ' No se pudo mandar el recibo por email.'
            estado_pago.refresh_from_db()
            saldo = estado_pago.saldo_actual
            texto += f' Su cuenta: {formato_saldo(saldo)}.' if saldo else ' Quedó al día.'
            messages.success(request, texto)
            return _volver(request, reverse('gravity:admin_pagos_editar_estado_cliente', args=[cliente.id]))
    else:
        # Monto y tipo arrancan vacíos: se completan con un monto sugerido o a mano
        form = estilo_panel(RegistroPagoForm(initial={
            'fecha_pago': hoy,
            'concepto': f'Cuota {MESES_LARGOS[hoy.month - 1]} {hoy.year}',
        }))

    sugerencias = []
    if estado_pago.saldo_actual < 0:
        sugerencias.append({'texto': 'Lo que debe', 'monto': -estado_pago.saldo_actual, 'tipo': ''})
    if plan:
        sugerencias.append({'texto': f'Cuota {plan.nombre}', 'monto': plan.precio_mensual, 'tipo': 'transferencia'})
        sugerencias.append({'texto': 'En efectivo (−10%)', 'monto': plan.calcular_precio_efectivo(), 'tipo': 'efectivo'})

    return render(request, 'gravity/admin/pagos_registrar.html', {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
        'sugerencias': sugerencias,
        'next': _next_seguro(request),
    })

@admin_required
def admin_pagos_historial_cliente(request, cliente_id):
    """
    Página simple para ver historial de pagos de un cliente específico.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)
    estado_pago = get_object_or_404(EstadoPagoCliente, usuario=cliente)
    
    # Obtener historial de pagos
    pagos = RegistroPago.objects.filter(
        cliente=cliente
    ).select_related('registrado_por').order_by('-fecha_pago', '-fecha_registro')
    
    # Estadísticas del cliente
    total_pagado = pagos.filter(estado='confirmado').aggregate(
        total=Sum('monto')
    )['total'] or Decimal('0')
    
    total_pagos = pagos.filter(estado='confirmado').count()
    
    context = {
        'cliente': cliente,
        'estado_pago': estado_pago,
        'pagos': pagos,
        'total_pagado': total_pagado,
        'total_pagos': total_pagos,
        'puede_ver_pagos': True,  # se va con el rediseño de Pagos
    }
    
    return render(request, 'gravity/admin/pagos_historial.html', context)

@superadmin_required
def admin_pagos_configurar_planes(request):
    """
    Planes y precios (solo superadmin): crear, editar (con la opción de aplicar el
    precio nuevo a las cuotas impagas del mes), pausar y eliminar.
    """
    planes = list(PlanPago.objects.all().order_by('-activo', 'clases_por_semana'))
    form = estilo_panel(PlanPagoForm(auto_id='nuevo_%s'))
    editando_id, form_edicion = None, None

    if request.method == 'POST':
        if 'crear_plan' in request.POST:
            form = estilo_panel(PlanPagoForm(request.POST, auto_id='nuevo_%s'))
            if form.is_valid():
                plan = form.save()
                messages.success(request, f'Creaste el plan {plan.nombre}.')
                return redirect('gravity:admin_pagos_configurar_planes')
        elif 'editar_plan' in request.POST:
            plan = get_object_or_404(PlanPago, id=request.POST.get('editar_plan'))
            # Guardarlo antes de is_valid(), que ya le asigna los datos nuevos a la instancia
            precio_anterior = plan.precio_mensual
            form_edicion = estilo_panel(PlanPagoForm(request.POST, instance=plan, auto_id=f'p{plan.id}_%s'))
            if form_edicion.is_valid():
                with transaction.atomic():
                    plan = form_edicion.save()
                    actualizadas = []
                    if request.POST.get('aplicar_a_cuotas_del_mes'):
                        actualizadas = aplicar_precio_a_cuotas_del_mes(plan, precio_anterior)
                messages.success(request, f'Guardaste el plan {plan.nombre}.')
                if actualizadas:
                    messages.success(
                        request,
                        f'Se actualizaron {len(actualizadas)} cuota(s) impaga(s) de este mes '
                        f'de ${pesos(precio_anterior)} a ${pesos(plan.precio_mensual)}.'
                    )
                return redirect('gravity:admin_pagos_configurar_planes')
            editando_id = plan.id
        elif 'eliminar_plan' in request.POST:
            plan = get_object_or_404(PlanPago, id=request.POST.get('eliminar_plan'))
            if plan.estadopagocliente_set.exists() or PlanUsuario.objects.filter(plan=plan).exists():
                messages.error(request, f'El plan {plan.nombre} ya tuvo alumnos: no se puede eliminar, pero podés pausarlo.')
            else:
                nombre = plan.nombre
                plan.delete()
                messages.success(request, f'Eliminaste el plan {nombre}.')
            return redirect('gravity:admin_pagos_configurar_planes')
        elif 'toggle_activo_plan' in request.POST:
            plan = get_object_or_404(PlanPago, id=request.POST.get('toggle_activo_plan'))
            plan.activo = not plan.activo
            plan.save()
            messages.success(request, f'El plan {plan.nombre} {"vuelve a estar disponible" if plan.activo else "quedó pausado: no se ofrece a los alumnos"}.')
            return redirect('gravity:admin_pagos_configurar_planes')

    alumnos_por_plan = dict(
        PlanUsuario.objects.filter(activo=True, usuario__is_active=True)
        .values_list('plan_id').annotate(n=Count('usuario', distinct=True))
    )
    filas = []
    for plan in planes:
        f = form_edicion if plan.id == editando_id else estilo_panel(PlanPagoForm(instance=plan, auto_id=f'p{plan.id}_%s'))
        filas.append({
            'plan': plan,
            'form': f,
            'alumnos': alumnos_por_plan.get(plan.id, 0),
            'efectivo': plan.calcular_precio_efectivo(),
            'abierto': plan.id == editando_id,
        })
    return render(request, 'gravity/admin/pagos_configurar_planes.html', {
        'filas': filas,
        'form': form,
        'crear_abierto': request.method == 'POST' and 'crear_plan' in request.POST,
    })

@admin_required
def admin_pagos_editar_estado_cliente(request, cliente_id):
    """
    Cuenta del cliente: saldo explicado, cuotas, pagos e historial de
    correcciones, todo en una sola pantalla desde donde se puede arreglar
    cualquier problema (saldo mal, pago mal cargado, cuota de más o de menos).
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)

    estado_pago, created = EstadoPagoCliente.objects.get_or_create(
        usuario=cliente,
        defaults={'activo': True}
    )

    if request.method == 'POST' and not puede_corregir_cuentas(request.user):
        messages.error(request, 'Cambiar el plan o la configuración de pagos de un alumno es solo para superadministradores.')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    if request.method == 'POST':
        form = estilo_panel(EstadoPagoClienteForm(request.POST, instance=estado_pago))
        if form.is_valid():
            estado_actualizado = form.save()
            puede_reservar_elegido = form.cleaned_data.get('puede_reservar')

            # Sincronizar PlanUsuario con plan_actual si el plan cambió.
            if estado_actualizado.plan_actual:
                plan_usuario_sincronizado = PlanUsuario.objects.filter(
                    usuario=cliente,
                    activo=True,
                    plan=estado_actualizado.plan_actual
                ).exists()

                if not plan_usuario_sincronizado:
                    hoy = timezone.localtime(timezone.now()).date()
                    fecha_fin = date(2099, 12, 31)

                    # Desactivar todos los planes activos del cliente
                    PlanUsuario.objects.filter(
                        usuario=cliente,
                        activo=True,
                    ).update(activo=False)

                    PlanUsuario.objects.create(
                        usuario=cliente,
                        plan=estado_actualizado.plan_actual,
                        fecha_inicio=hoy,
                        fecha_fin=fecha_fin,
                        activo=True,
                        tipo_plan='permanente',
                        renovacion_automatica=True,
                        creado_por=request.user,
                        observaciones='Asignado por administrador desde panel de pagos'
                    )

                    # Actualizar deuda del mes actual con el nuevo plan
                    estado_actualizado.generar_deuda_mes_actual()

            else:
                # El admin quitó el plan, ajustar o eliminar deuda del mes actual
                hoy = timezone.localtime(timezone.now()).date()
                primer_dia_mes = date(hoy.year, hoy.month, 1)
                deuda_mes = DeudaMensual.objects.filter(
                    usuario=cliente,
                    mes_año=primer_dia_mes
                ).exclude(estado='pagado').first()

                if deuda_mes:
                    if hoy.day <= 4:
                        # Baja temprana: eliminar deuda completa
                        deuda_mes.delete()
                    elif hoy.day <= 9:
                        # Baja a mitad de mes: dejar solo medio mes
                        medio_mes = deuda_mes.plan_aplicado.precio_mensual / 2
                        if deuda_mes.monto_pendiente > medio_mes:
                            deuda_mes.monto_original = medio_mes
                            deuda_mes.monto_pendiente = medio_mes
                            deuda_mes.es_medio_mes = True
                            deuda_mes.save()
                    # día >= 10: no tocar la deuda

                # Desactivar PlanUsuario activos
                PlanUsuario.objects.filter(usuario=cliente, activo=True).update(activo=False)

            # Recalcular toda la cuenta y respetar el bloqueo elegido a mano
            recalcular_estado_pagos(cliente)
            EstadoPagoCliente.objects.filter(usuario=cliente).update(
                puede_reservar=puede_reservar_elegido
            )

            messages.success(
                request,
                f'Estado de pago actualizado para {cliente.get_full_name() or cliente.username}'
            )
            return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)
    else:
        form = estilo_panel(EstadoPagoClienteForm(instance=estado_pago))

    planes_precios = {
        str(p.id): str(p.precio_mensual)
        for p in PlanPago.objects.filter(activo=True)
    }

    resumen = resumen_cuenta_cliente(cliente)
    hoy = timezone.localtime(timezone.now()).date()

    context = {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
        'planes_precios': planes_precios,
        'saldo_calculado': resumen['saldo'],
        'saldo_absoluto': abs(resumen['saldo']),
        'total_pagado': resumen['total_pagado'],
        'total_deudas': resumen['total_deudas'],
        'total_correcciones': resumen['total_correcciones'],
        'total_correcciones_abs': abs(resumen['total_correcciones']),
        'total_pendiente': resumen['total_pendiente'],
        'deudas': DeudaMensual.objects.filter(usuario=cliente).select_related(
            'plan_aplicado').order_by('-mes_año'),
        'pagos': RegistroPago.objects.filter(cliente=cliente).select_related(
            'registrado_por').order_by('-fecha_pago', '-id'),
        'correcciones': AjusteSaldo.objects.filter(usuario=cliente).select_related(
            'admin_que_ajusto')[:30],
        'planes_activos_usuario': PlanUsuario.objects.filter(
            usuario=cliente,
            activo=True
        ).select_related('plan').order_by('fecha_inicio'),
        'puede_corregir': puede_corregir_cuentas(request.user),
        'mes_actual_valor': hoy.strftime('%Y-%m'),
    }

    return render(request, 'gravity/admin/pagos_editar_estado.html', context)


def resumen_cuenta_cliente(cliente):
    """
    Calcula (sin escribir nada) los totales de la cuenta de un cliente,
    con la misma fórmula que usa recalcular_estado_pagos().
    """
    total_pagado = RegistroPago.objects.filter(
        cliente=cliente, estado='confirmado'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

    total_correcciones = AjusteSaldo.objects.filter(
        usuario=cliente, tipo=AjusteSaldo.TIPO_CORRECCION_SALDO
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

    total_deudas = DeudaMensual.objects.filter(
        usuario=cliente
    ).aggregate(total=Sum('monto_original'))['total'] or Decimal('0')

    total_pendiente = DeudaMensual.objects.filter(
        usuario=cliente
    ).aggregate(total=Sum('monto_pendiente'))['total'] or Decimal('0')

    return {
        'total_pagado': total_pagado,
        'total_correcciones': total_correcciones,
        'total_deudas': total_deudas,
        'total_pendiente': total_pendiente,
        'saldo': total_pagado + total_correcciones - total_deudas,
    }


def registrar_correccion(cliente, admin, tipo, descripcion, motivo='', monto=Decimal('0'),
                         saldo_anterior=Decimal('0'), saldo_nuevo=Decimal('0')):
    """Deja constancia en el historial de correcciones de la cuenta."""
    return AjusteSaldo.objects.create(
        usuario=cliente,
        tipo=tipo,
        monto=monto,
        descripcion=descripcion[:300],
        motivo=motivo,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        admin_que_ajusto=admin,
    )

@superadmin_required
def admin_cancelar_plan_usuario(request, plan_id):
    """
    Cancelar un plan de un alumno. Primero se muestra qué reservas se cancelan:
    si no le queda otro plan, todas; si le queda otro, vienen tildados los horarios
    fijos que ese plan no cubre (los más nuevos) y el admin puede cambiar la
    elección. Las reservas canceladas quedan registradas como cancelación del
    estudio y la cuota del mes se ajusta según el día de la baja.
    """
    plan = get_object_or_404(PlanUsuario.objects.select_related('plan', 'usuario'), id=plan_id, activo=True)
    usuario = plan.usuario
    otros = list(PlanUsuario.objects.filter(usuario=usuario, activo=True).exclude(pk=plan.pk).select_related('plan'))
    cupo_otros = sum(p.plan.clases_por_semana for p in otros)
    fijas = list(usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=True)
                 .select_related('clase').order_by('fecha_reserva'))
    sueltas = list(usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=False)
                   .select_related('clase').order_by('fecha_unica'))
    if otros:
        sugeridas = {r.id for r in fijas[cupo_otros:]}
    else:
        sugeridas = {r.id for r in fijas + sueltas}

    if request.method == 'POST':
        validas = {r.id for r in fijas + sueltas}
        if 'reservas' in request.POST or 'elegir' in request.POST:
            elegidas = {int(i) for i in request.POST.getlist('reservas') if i.isdigit()} & validas
        else:
            elegidas = sugeridas

        precio_mensual_plan = plan.plan.precio_mensual
        with transaction.atomic():
            for reserva in fijas + sueltas:
                if reserva.id in elegidas:
                    reserva.activa = False
                    reserva.save()
                    CancelacionAdmin.objects.create(
                        reserva=reserva, admin_user=request.user, motivo='Baja del plan',
                        motivo_detalle=f'Se canceló el plan {plan.plan.nombre}.', email_enviado=False,
                    )
            plan.activo = False
            plan.reservas_canceladas = bool(elegidas)
            plan.save()

            try:
                estado = usuario.estado_pago
            except EstadoPagoCliente.DoesNotExist:
                estado = None
            if estado:
                estado.actualizar_plan_automatico()
                if not PlanUsuario.objects.filter(usuario=usuario, activo=True).exists():
                    estado.plan_actual = None
                    estado.save(update_fields=['plan_actual'])
                    # Cuota del mes según el día de la baja: hasta el 4 no se cobra,
                    # del 5 al 9 medio mes, desde el 10 el mes completo
                    hoy = timezone.localdate()
                    deuda_mes = DeudaMensual.objects.filter(
                        usuario=usuario, mes_año=hoy.replace(day=1)
                    ).exclude(estado='pagado').first()
                    if deuda_mes:
                        if hoy.day <= 4:
                            deuda_mes.delete()
                        elif hoy.day <= 9:
                            medio_mes = precio_mensual_plan / 2
                            if deuda_mes.monto_pendiente > medio_mes:
                                deuda_mes.monto_original = medio_mes
                                deuda_mes.monto_pendiente = medio_mes
                                deuda_mes.es_medio_mes = True
                                deuda_mes.save()
                    recalcular_estado_pagos(usuario)

        n = len(elegidas)
        messages.success(
            request,
            f'Cancelaste el plan {plan.plan.nombre} de {usuario.get_full_name() or usuario.username}.'
            + (f' Se cancelaron {n} reserva{"s" if n != 1 else ""}.' if n else ' Sus reservas siguen igual.')
        )
        return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)

    return render(request, 'gravity/admin/plan_cancelar.html', {
        'plan': plan,
        'usuario': usuario,
        'otros': otros,
        'cupo_otros': cupo_otros,
        'fijas': fijas,
        'sueltas': sueltas,
        'sugeridas': sugeridas,
        'hoy': timezone.localdate(),
    })

# ==============================================================================
# GESTIÓN DE ADMINISTRADORES CON PERMISOS RESTRINGIDOS (solo superadmins)
# ==============================================================================

@superadmin_required
def admin_generar_deuda_manual(request, cliente_id):
    """
    Genera una DeudaMensual manualmente para un mes que no tiene deuda aún.
    Si el mes ya tiene deuda, rechaza con mensaje de error (usar Ajustar).
    Solo acepta POST. Solo superusuarios.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)

    if request.method != 'POST':
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente_id)

    mes_str = request.POST.get('mes_año', '')
    monto_str = request.POST.get('monto', '')
    motivo = request.POST.get('motivo', '').strip()

    try:
        partes = mes_str.split('-')
        año, mes = int(partes[0]), int(partes[1])
        primer_dia_mes = date(año, mes, 1)
        monto = Decimal(monto_str)

        if monto <= 0:
            messages.error(request, 'El monto debe ser mayor a cero.')
            return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente_id)

        if DeudaMensual.objects.filter(usuario=cliente, mes_año=primer_dia_mes).exists():
            messages.error(
                request,
                f'Ya existe una deuda para ese mes. Usá el botón "Ajustar" sobre la fila correspondiente.'
            )
            return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente_id)

        estado_pago = EstadoPagoCliente.objects.filter(usuario=cliente).first()
        plan = estado_pago.plan_actual if estado_pago else None

        if not plan:
            messages.error(
                request,
                'El cliente no tiene un plan asignado. Asigná uno antes de generar una deuda.'
            )
            return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente_id)

        # Fecha de vencimiento: día 10 del mismo mes si no pasó, sino día 10 del mes siguiente
        hoy = timezone.localtime(timezone.now()).date()
        dia_10_mismo_mes = date(año, mes, 10)
        if hoy <= dia_10_mismo_mes:
            fecha_vencimiento = dia_10_mismo_mes
        else:
            if mes == 12:
                fecha_vencimiento = date(año + 1, 1, 10)
            else:
                fecha_vencimiento = date(año, mes + 1, 10)

        with transaction.atomic():
            DeudaMensual.objects.create(
                usuario=cliente,
                mes_año=primer_dia_mes,
                plan_aplicado=plan,
                monto_original=monto,
                monto_pendiente=monto,
                es_medio_mes=False,
                estado='pendiente',
                fecha_vencimiento=fecha_vencimiento,
                observaciones=(
                    f'Generada manualmente por '
                    f'{request.user.get_full_name() or request.user.username}.'
                    + (f' {motivo}' if motivo else '')
                ).strip()
            )

            saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']
            resumen = recalcular_estado_pagos(cliente)

            registrar_correccion(
                cliente, request.user, 'cuota_creada',
                f'Cuota de {formats.date_format(primer_dia_mes, "F Y")} creada por ${fmt_pesos(monto)}',
                motivo=motivo,
                saldo_anterior=saldo_anterior,
                saldo_nuevo=resumen['saldo'],
            )

        mes_display = primer_dia_mes.strftime('%B %Y')
        messages.success(
            request,
            f'Deuda de {mes_display} generada por ${fmt_pesos(monto)}. Saldo recalculado.'
        )

    except (ValueError, TypeError, IndexError):
        messages.error(request, 'Datos inválidos. Verificá el mes y el monto ingresados.')

    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente_id)

@superadmin_required
def admin_ajustar_deuda_especial(request, deuda_id):
    """
    Cambia cuánto tiene que pagar el cliente por un mes puntual (descuento,
    acuerdo especial, mes mal cobrado). Después se recalcula toda la cuenta.
    """
    deuda = get_object_or_404(DeudaMensual, id=deuda_id)
    cliente = deuda.usuario

    if request.method != 'POST':
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    form = AjusteDeudaForm(request.POST)

    if not form.is_valid():
        messages.error(request, 'Error al procesar el ajuste. Revisá los datos ingresados.')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    monto_ajustado = form.cleaned_data['monto_ajustado']
    motivo = form.cleaned_data.get('motivo', '')
    monto_anterior = deuda.monto_original
    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']
    mes_str = formats.date_format(deuda.mes_año, 'F Y')

    with transaction.atomic():
        AjusteDeudaEspecial.objects.create(
            deuda=deuda,
            usuario_cliente=cliente,
            admin_que_ajusto=request.user,
            monto_original_anterior=monto_anterior,
            monto_ajustado=monto_ajustado,
            motivo=motivo,
        )

        nota = (
            f'Ajustada de ${fmt_pesos(monto_anterior)} a ${fmt_pesos(monto_ajustado)} por '
            f'{request.user.get_full_name() or request.user.username} el '
            f'{timezone.localtime(timezone.now()).strftime("%d/%m/%Y")}.'
        )
        deuda.monto_original = monto_ajustado
        deuda.observaciones = (
            f'{deuda.observaciones}\n{nota}' if deuda.observaciones else nota
        )
        deuda.save(update_fields=['monto_original', 'observaciones'])

        resumen = recalcular_estado_pagos(cliente)

        registrar_correccion(
            cliente, request.user, 'cuota_ajustada',
            f'Cuota de {mes_str}: ${fmt_pesos(monto_anterior)} → ${fmt_pesos(monto_ajustado)}',
            motivo=motivo,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=resumen['saldo'],
        )

    messages.success(
        request,
        f'Cuota de {mes_str} ajustada a ${fmt_pesos(monto_ajustado)}. La cuenta se recalculó sola.'
    )
    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


@superadmin_required
def admin_corregir_saldo(request, cliente_id):
    """
    Corrección directa del saldo: el admin dice cómo tiene que quedar la cuenta
    (al día / a favor / debiendo) y el sistema registra la diferencia.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)

    if request.method != 'POST':
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    form = CorregirSaldoForm(request.POST)

    if not form.is_valid():
        primer_error = next(iter(form.errors.values()))[0]
        messages.error(request, f'No se pudo corregir el saldo: {primer_error}')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    saldo_objetivo = form.cleaned_data['saldo_objetivo']
    motivo = form.cleaned_data['motivo']
    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']
    diferencia = saldo_objetivo - saldo_anterior

    if diferencia == 0:
        messages.info(request, 'La cuenta ya estaba así, no hizo falta corregir nada.')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    if saldo_objetivo > 0:
        descripcion = f'Saldo corregido a ${fmt_pesos(saldo_objetivo)} a favor'
    elif saldo_objetivo < 0:
        descripcion = f'Saldo corregido a ${fmt_pesos(abs(saldo_objetivo))} de deuda'
    else:
        descripcion = 'Cuenta puesta al día (saldo $0)'

    with transaction.atomic():
        registrar_correccion(
            cliente, request.user, AjusteSaldo.TIPO_CORRECCION_SALDO,
            descripcion,
            motivo=motivo,
            monto=diferencia,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=saldo_objetivo,
        )
        recalcular_estado_pagos(cliente)

    messages.success(request, f'{descripcion}. Antes: {formato_saldo(saldo_anterior)}.')
    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


@superadmin_required
def admin_pago_editar(request, pago_id):
    """
    Corrige un pago ya registrado (monto mal tipeado, fecha o tipo equivocados).
    """
    pago = get_object_or_404(RegistroPago, id=pago_id)
    cliente = pago.cliente

    if request.method != 'POST' or cliente is None:
        return redirect('gravity:admin_pagos_vista_principal')

    form = EditarPagoForm(request.POST, instance=pago)

    if not form.is_valid():
        primer_error = next(iter(form.errors.values()))[0]
        messages.error(request, f'No se pudo corregir el pago: {primer_error}')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    datos = form.cleaned_data
    monto_anterior = RegistroPago.objects.get(id=pago.id).monto
    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']
    motivo = datos['motivo']

    nota = (
        f'Corregido el {timezone.localtime(timezone.now()).strftime("%d/%m/%Y")} por '
        f'{request.user.get_full_name() or request.user.username}: '
        f'monto ${fmt_pesos(monto_anterior)} → ${fmt_pesos(datos["monto"])}. {motivo}'.strip()
    )

    with transaction.atomic():
        # Se actualiza sin pasar por save() para no volver a aplicar el pago
        # sobre las cuotas: de eso se encarga el recálculo de abajo.
        RegistroPago.objects.filter(id=pago.id).update(
            monto=datos['monto'],
            fecha_pago=datos['fecha_pago'],
            tipo_pago=datos['tipo_pago'],
            concepto=datos['concepto'],
            observaciones=f'{pago.observaciones}\n{nota}'.strip() if pago.observaciones else nota,
        )
        resumen = recalcular_estado_pagos(cliente)

        registrar_correccion(
            cliente, request.user, 'pago_editado',
            f'Pago del {datos["fecha_pago"].strftime("%d/%m/%Y")}: '
            f'${fmt_pesos(monto_anterior)} → ${fmt_pesos(datos["monto"])}',
            motivo=motivo,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=resumen['saldo'],
        )

    messages.success(
        request,
        f'Pago corregido: ${fmt_pesos(monto_anterior)} → ${fmt_pesos(datos["monto"])}. La cuenta se recalculó sola.'
    )
    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


@superadmin_required
def admin_pago_anular(request, pago_id):
    """
    Anula un pago cargado por error. No se borra: queda marcado como anulado
    y deja de contar en la cuenta.
    """
    pago = get_object_or_404(RegistroPago, id=pago_id)
    cliente = pago.cliente

    if request.method != 'POST' or cliente is None:
        return redirect('gravity:admin_pagos_vista_principal')

    form = AnularPagoForm(request.POST)

    if not form.is_valid():
        messages.error(request, 'Escribí el motivo de la anulación.')
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    motivo = form.cleaned_data['motivo']
    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']

    nota = (
        f'ANULADO el {timezone.localtime(timezone.now()).strftime("%d/%m/%Y")} por '
        f'{request.user.get_full_name() or request.user.username}: {motivo}'
    )

    with transaction.atomic():
        RegistroPago.objects.filter(id=pago.id).update(
            estado='rechazado',
            observaciones=f'{pago.observaciones}\n{nota}'.strip() if pago.observaciones else nota,
        )
        resumen = recalcular_estado_pagos(cliente)

        registrar_correccion(
            cliente, request.user, 'pago_anulado',
            f'Pago del {pago.fecha_pago.strftime("%d/%m/%Y")} de ${fmt_pesos(pago.monto)} anulado',
            motivo=motivo,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=resumen['saldo'],
        )

    messages.success(
        request,
        f'Pago de ${fmt_pesos(pago.monto)} anulado. La cuenta se recalculó sola.'
    )
    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


@superadmin_required
def admin_eliminar_deuda(request, deuda_id):
    """
    Elimina una cuota que no correspondía cobrar (por ejemplo un mes generado
    de más por el cron).
    """
    deuda = get_object_or_404(DeudaMensual, id=deuda_id)
    cliente = deuda.usuario

    if request.method != 'POST':
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    motivo = request.POST.get('motivo', '').strip()
    mes_str = formats.date_format(deuda.mes_año, 'F Y')
    monto = deuda.monto_original
    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']

    with transaction.atomic():
        deuda.delete()
        resumen = recalcular_estado_pagos(cliente)

        registrar_correccion(
            cliente, request.user, 'cuota_eliminada',
            f'Cuota de {mes_str} de ${fmt_pesos(monto)} eliminada',
            motivo=motivo,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=resumen['saldo'],
        )

    messages.success(
        request,
        f'Cuota de {mes_str} eliminada. La cuenta se recalculó sola.'
    )
    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


@superadmin_required
def admin_recalcular_cuenta(request, cliente_id):
    """
    Vuelve a calcular la cuenta del cliente desde cero (pagos + correcciones -
    cuotas) y deja el estado de cada cuota coherente con ese resultado.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)

    if request.method != 'POST':
        return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)

    saldo_anterior = resumen_cuenta_cliente(cliente)['saldo']
    resumen = recalcular_estado_pagos(cliente)

    if saldo_anterior != resumen['saldo']:
        registrar_correccion(
            cliente, request.user, 'recalculo',
            f'Recálculo de la cuenta: {formato_saldo(saldo_anterior)} → {formato_saldo(resumen["saldo"])}',
            saldo_anterior=saldo_anterior,
            saldo_nuevo=resumen['saldo'],
        )
        messages.success(
            request,
            f'Cuenta recalculada: {formato_saldo(saldo_anterior)} → {formato_saldo(resumen["saldo"])}.'
        )
    else:
        messages.success(
            request,
            f'Cuenta recalculada. El saldo sigue igual: {formato_saldo(resumen["saldo"])}.'
        )

    return redirect('gravity:admin_pagos_editar_estado_cliente', cliente_id=cliente.id)


def fmt_pesos(monto):
    """Formatea un monto al estilo argentino: 61000 -> 61.000"""
    return '{:,.0f}'.format(monto).replace(',', '.')


def formato_saldo(saldo):
    """Texto legible de un saldo: al día / a favor / debe."""
    if saldo > 0:
        return f'${fmt_pesos(saldo)} a favor'
    if saldo < 0:
        return f'debe ${fmt_pesos(abs(saldo))}'
    return 'al día'


# ==============================================================================
# PAGOS CARGADOS POR CADA ADMINISTRADORA (solo superadmins)
# ==============================================================================

# Cantidad de pagos que se listan por página en el detalle
PAGOS_ADMIN_POR_PAGINA = 25


def _rango_pagos_admins(request):
    """
    Rango de fechas del filtro de la pantalla de pagos por administradora.

    Funciona igual que el filtro de Profesoras: un día puntual, la semana que
    contiene a una fecha, un mes completo o un rango libre. Devuelve el rango y
    el contexto para volver a dibujar el selector como quedó elegido.
    """
    hoy = timezone.localtime(timezone.now()).date()
    periodo = request.GET.get('periodo', 'mes')

    def leer_fecha(clave, por_defecto):
        try:
            return datetime.strptime(request.GET.get(clave, ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return por_defecto

    def leer_mes():
        try:
            año, mes = request.GET.get('mes', '').split('-')
            return date(int(año), int(mes), 1)
        except (ValueError, TypeError, AttributeError):
            return hoy.replace(day=1)

    if periodo == 'dia':
        fecha = leer_fecha('fecha', hoy)
        desde = hasta = fecha
        mes_seleccionado = fecha.replace(day=1)

    elif periodo == 'semana':
        fecha = leer_fecha('fecha', hoy)
        desde = fecha - timedelta(days=fecha.weekday())
        hasta = desde + timedelta(days=6)
        mes_seleccionado = fecha.replace(day=1)

    elif periodo == 'personalizado':
        desde = leer_fecha('desde', hoy.replace(day=1))
        hasta = leer_fecha('hasta', hoy)
        if hasta < desde:
            desde, hasta = hasta, desde
        fecha = desde
        mes_seleccionado = desde.replace(day=1)

    else:
        periodo = 'mes'
        mes_seleccionado = leer_mes()
        ultimo_dia = calendar.monthrange(mes_seleccionado.year, mes_seleccionado.month)[1]
        desde = mes_seleccionado
        hasta = mes_seleccionado.replace(day=ultimo_dia)
        fecha = hoy

    contexto = {
        'periodo': periodo,
        'desde': desde,
        'hasta': hasta,
        'fecha': fecha,
        'mes_seleccionado': mes_seleccionado,
        'hoy': hoy,
    }
    return desde, hasta, contexto


def _fila_pagos_admin(resumen, clave, tipos):
    """Fila del resumen de una administradora, creándola vacía si no existe."""
    if clave not in resumen:
        resumen[clave] = {
            'admin': None,
            'es_sin_registrar': clave is None,
            'por_tipo': {
                tipo: {'cantidad': 0, 'monto': Decimal('0')} for tipo, _ in tipos
            },
            'cantidad': 0,
            'monto': Decimal('0'),
            'anulados_cantidad': 0,
            'anulados_monto': Decimal('0'),
            'pendientes_cantidad': 0,
        }
    return resumen[clave]


@superadmin_required
def admin_pagos_por_admin(request):
    """
    Cuántos pagos cargó cada administradora en el período elegido, abiertos por
    forma de cobro, más el detalle de cada pago.

    Los totales suman solo los pagos confirmados; los anulados van en una
    columna aparte para que se note si alguien carga y anula seguido.
    """
    desde, hasta, filtro = _rango_pagos_admins(request)
    tipos = list(RegistroPago.TIPOS_PAGO)
    claves_tipo = [clave for clave, _ in tipos]

    # Los pagos se pueden mirar por la fecha en que el cliente pagó (la que se
    # usa en el resto del sistema) o por la fecha en que se cargaron al sistema.
    criterio = request.GET.get('criterio', 'pago')
    if criterio not in ('pago', 'carga'):
        criterio = 'pago'

    if criterio == 'carga':
        rango = {
            'fecha_registro__date__gte': desde,
            'fecha_registro__date__lte': hasta,
        }
        orden = ('-fecha_registro', '-id')
    else:
        rango = {'fecha_pago__gte': desde, 'fecha_pago__lte': hasta}
        orden = ('-fecha_pago', '-fecha_registro', '-id')

    # ===== FILTROS =====
    admin_filtro = request.GET.get('admin', '')
    tipo_filtro = request.GET.get('tipo', '')
    buscar = request.GET.get('buscar', '').strip()

    if tipo_filtro not in claves_tipo:
        tipo_filtro = ''

    pagos = RegistroPago.objects.filter(**rango)

    if admin_filtro == 'sin_registrar':
        pagos = pagos.filter(registrado_por__isnull=True)
    elif admin_filtro.isdigit():
        pagos = pagos.filter(registrado_por_id=int(admin_filtro))
    else:
        admin_filtro = ''

    if tipo_filtro:
        pagos = pagos.filter(tipo_pago=tipo_filtro)

    if buscar:
        pagos = pagos.filter(
            Q(cliente__first_name__icontains=buscar) |
            Q(cliente__last_name__icontains=buscar) |
            Q(cliente__username__icontains=buscar)
        )

    # ===== RESUMEN POR ADMINISTRADORA =====
    resumen = {}

    confirmados = pagos.filter(estado='confirmado').values(
        'registrado_por', 'tipo_pago'
    ).annotate(cantidad=Count('id'), total=Sum('monto'))

    for dato in confirmados:
        fila = _fila_pagos_admin(resumen, dato['registrado_por'], tipos)
        monto = dato['total'] or Decimal('0')
        tipo = dato['tipo_pago'] if dato['tipo_pago'] in fila['por_tipo'] else 'otro'
        fila['por_tipo'][tipo]['cantidad'] += dato['cantidad']
        fila['por_tipo'][tipo]['monto'] += monto
        fila['cantidad'] += dato['cantidad']
        fila['monto'] += monto

    anulados = pagos.filter(estado='rechazado').values('registrado_por').annotate(
        cantidad=Count('id'), total=Sum('monto')
    )
    for dato in anulados:
        fila = _fila_pagos_admin(resumen, dato['registrado_por'], tipos)
        fila['anulados_cantidad'] += dato['cantidad']
        fila['anulados_monto'] += dato['total'] or Decimal('0')

    pendientes = pagos.filter(estado='pendiente').values('registrado_por').annotate(
        cantidad=Count('id')
    )
    for dato in pendientes:
        fila = _fila_pagos_admin(resumen, dato['registrado_por'], tipos)
        fila['pendientes_cantidad'] += dato['cantidad']

    # Administradoras del sistema: las contratadas y los superadministradores,
    # porque todos pueden cargar pagos.
    administradoras = list(
        User.objects.filter(is_staff=True, is_active=True)
        .order_by('first_name', 'last_name', 'username')
    )
    por_id = {usuario.id: usuario for usuario in administradoras}

    # Quien cargó pagos y después quedó inactiva o dejó de ser staff igual tiene
    # que aparecer, si no los totales no cierran.
    faltantes = [clave for clave in resumen if clave is not None and clave not in por_id]
    if faltantes:
        for usuario in User.objects.filter(id__in=faltantes):
            por_id[usuario.id] = usuario
            administradoras.append(usuario)

    filas = []
    if admin_filtro != 'sin_registrar':
        for usuario in administradoras:
            # Con el filtro de administradora puesto, solo se muestra esa fila
            if admin_filtro and str(usuario.id) != admin_filtro:
                continue
            fila = _fila_pagos_admin(resumen, usuario.id, tipos)
            fila['admin'] = usuario
            filas.append(fila)

    if None in resumen:
        fila_sin_autor = resumen[None]
        fila_sin_autor['admin'] = None
        filas.append(fila_sin_autor)

    filas.sort(key=lambda f: (-f['monto'], -f['cantidad']))

    # Las plantillas no pueden buscar por clave en un diccionario: se pasa cada
    # forma de pago como lista, en el mismo orden que los encabezados.
    for fila in filas:
        fila['tipos'] = [
            {
                'clave': tipo,
                'nombre': nombre,
                'cantidad': fila['por_tipo'][tipo]['cantidad'],
                'monto': fila['por_tipo'][tipo]['monto'],
            }
            for tipo, nombre in tipos
        ]

    # ===== TOTALES DEL PERÍODO =====
    totales = {
        'tipos': [
            {
                'clave': tipo,
                'nombre': nombre,
                'cantidad': sum(f['por_tipo'][tipo]['cantidad'] for f in filas),
                'monto': sum((f['por_tipo'][tipo]['monto'] for f in filas), Decimal('0')),
            }
            for tipo, nombre in tipos
        ],
        'cantidad': sum(f['cantidad'] for f in filas),
        'monto': sum((f['monto'] for f in filas), Decimal('0')),
        'anulados_cantidad': sum(f['anulados_cantidad'] for f in filas),
        'anulados_monto': sum((f['anulados_monto'] for f in filas), Decimal('0')),
        'pendientes_cantidad': sum(f['pendientes_cantidad'] for f in filas),
    }

    admins_que_cargaron = len([f for f in filas if f['cantidad']])

    # ===== DETALLE DE CADA PAGO =====
    detalle = pagos.select_related('cliente', 'registrado_por').order_by(*orden)
    paginator = Paginator(detalle, PAGOS_ADMIN_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Querystring sin la página, para que la paginación conserve los filtros
    parametros = request.GET.copy()
    parametros.pop('page', None)
    querystring = parametros.urlencode()

    # Los mismos filtros sin el período, para los botones de día/semana/mes/rango
    extra = request.GET.copy()
    for clave in ('page', 'periodo', 'fecha', 'mes', 'desde', 'hasta'):
        extra.pop(clave, None)
    filtros_extra = extra.urlencode()

    context = {
        **filtro,
        'criterio': criterio,
        'admin_filtro': admin_filtro,
        'tipo_filtro': tipo_filtro,
        'buscar': buscar,
        'tipos_pago': tipos,
        'administradoras': administradoras,
        'hay_sin_registrar': None in resumen,
        'filas': filas,
        'totales': totales,
        'admins_que_cargaron': admins_que_cargaron,
        'page_obj': page_obj,
        'querystring': querystring,
        'filtros_extra': filtros_extra,
    }
    return render(request, 'gravity/admin/pagos_por_admin.html', context)


# ==============================================================================
# VISTAS DE PLANES DE PAGO
# ==============================================================================

@login_required
def seleccionar_plan(request):
    """
    Vista para que un usuario sin plan activo solicite su primer plan.
    La solicitud queda pendiente hasta que un superadministrador la apruebe.
    """
    tiene_plan_activo = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=True,
        fecha_fin__gte=timezone.localtime(timezone.now()).date()
    ).exists()

    if tiene_plan_activo:
        messages.info(
            request,
            'Ya tenés un plan activo. Si querés cambiarlo, usá la opción "Cambiar de plan".'
        )
        return redirect('gravity:mis_planes')

    solicitud_pendiente = SolicitudCambioPlan.objects.filter(
        usuario=request.user, estado='pendiente'
    ).select_related('plan_solicitado').first()

    if solicitud_pendiente:
        messages.info(
            request,
            f'Ya tenés una solicitud pendiente de aprobación para el plan '
            f'"{solicitud_pendiente.plan_solicitado.nombre}".'
        )
        return redirect('gravity:mis_planes')

    # Obtener planes disponibles
    planes_disponibles = anotar_planes(
        PlanPago.objects.filter(activo=True).order_by('clases_por_semana', 'precio_mensual')
    )

    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')

        try:
            plan_seleccionado = PlanPago.objects.get(id=plan_id, activo=True)

            SolicitudCambioPlan.objects.create(
                usuario=request.user,
                plan_actual=None,
                plan_solicitado=plan_seleccionado,
                estado='pendiente'
            )

            messages.success(
                request,
                f'Tu solicitud para el plan "{plan_seleccionado.nombre}" fue enviada y '
                f'está pendiente de aprobación. Te avisaremos cuando sea aprobada.'
            )
            return redirect('gravity:mis_planes')

        except PlanPago.DoesNotExist:
            messages.error(request, 'Ese plan ya no está disponible. Elegí otro.')
        except Exception:
            logger.exception('Error enviando solicitud de plan')
            messages.error(request, 'No pudimos enviar la solicitud. Intentá de nuevo en un momento.')

    context = {
        'planes_disponibles': planes_disponibles,
        'politica': politica_baja_plan(timezone.localtime(timezone.now()).date()),
    }

    return render(request, 'gravity/seleccionar_plan.html', context)

def politica_baja_plan(hoy):
    """Qué se cobra del mes en curso si el plan se da de baja en la fecha 'hoy'."""
    if hoy.day <= 4:
        return {'tipo': 'sin_cargo', 'titulo': 'Sin cargo', 'texto': 'No se cobra el mes en curso.'}
    if hoy.day <= 9:
        return {'tipo': 'medio_mes', 'titulo': 'Medio mes', 'texto': 'Se cobra la mitad del mes en curso.'}
    return {'tipo': 'mes_completo', 'titulo': 'Mes completo', 'texto': 'Se cobra el mes completo.'}


def _horarios_fijos(usuario):
    """Reservas fijas activas del usuario, ordenadas por día y hora."""
    orden = {d: i for i, d in enumerate(['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'])}
    return sorted(
        usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=True).select_related('clase'),
        key=lambda r: (orden.get(r.clase.dia, 9), r.clase.horario),
    )


@login_required
def modificar_plan(request):
    """
    Cambio de plan en una sola página: el alumno elige el nuevo plan y, si tiene
    más horarios fijos que las clases del plan nuevo, marca ahí mismo cuáles libera.
    El cambio queda pendiente hasta que un superadministrador lo apruebe.
    """
    request.session.pop('downgrade_plan_solicitado_id', None)

    plan_usuario_actual = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=True,
        fecha_fin__gte=timezone.localtime(timezone.now()).date()
    ).select_related('plan').first()

    if not plan_usuario_actual:
        messages.info(request, 'No tenés un plan activo todavía. Elegí uno para empezar.')
        return redirect('gravity:seleccionar_plan')

    if SolicitudCambioPlan.objects.filter(usuario=request.user, estado='pendiente').exists():
        messages.info(request, 'Ya tenés una solicitud de cambio de plan pendiente de aprobación.')
        return redirect('gravity:mis_planes')

    plan_actual = plan_usuario_actual.plan
    anotar_planes([plan_actual])
    planes_disponibles = anotar_planes(
        PlanPago.objects.filter(activo=True).exclude(id=plan_actual.id).order_by('clases_por_semana', 'precio_mensual')
    )
    fijas = _horarios_fijos(request.user)

    plan_elegido_id = None
    reservas_marcadas = []

    if request.method == 'POST':
        try:
            plan_solicitado = PlanPago.objects.get(id=request.POST.get('plan_id'), activo=True)
        except (PlanPago.DoesNotExist, ValueError):
            messages.error(request, 'Elegí uno de los planes disponibles.')
            return redirect('gravity:modificar_plan')

        # Solo hay que liberar horarios si los fijos no entran en el plan nuevo
        minimo_a_ceder = max(0, len(fijas) - plan_solicitado.clases_por_semana)
        ids = set(request.POST.getlist('reservas'))
        elegidas = [r for r in fijas if str(r.id) in ids]

        if len(elegidas) < minimo_a_ceder:
            plan_elegido_id = plan_solicitado.id
            reservas_marcadas = [str(r.id) for r in elegidas]
            messages.error(
                request,
                f'Para pasar a "{plan_solicitado.nombre}" marcá {minimo_a_ceder} '
                f'horario{"s" if minimo_a_ceder != 1 else ""} para liberar.'
            )
        else:
            solicitud = SolicitudCambioPlan.objects.create(
                usuario=request.user,
                plan_actual=plan_actual,
                plan_solicitado=plan_solicitado,
                estado='pendiente'
            )
            if elegidas:
                solicitud.reservas_a_cancelar.set(elegidas)
            messages.success(
                request,
                f'Enviamos tu solicitud para pasar a "{plan_solicitado.nombre}". '
                f'Mientras la revisamos, seguís con tu plan actual'
                f'{" y tus horarios" if elegidas else ""} sin cambios.'
            )
            return redirect('gravity:mis_planes')

    for plan in planes_disponibles:
        plan.a_ceder = max(0, len(fijas) - plan.clases_por_semana)
        diferencia = plan.clases_por_semana - plan_actual.clases_por_semana
        plan.cambio = 'mas' if diferencia > 0 else 'menos' if diferencia < 0 else 'igual'

    context = {
        'plan_actual': plan_actual,
        'planes_disponibles': planes_disponibles,
        'fijas': fijas,
        'plan_elegido_id': plan_elegido_id,
        'reservas_marcadas': reservas_marcadas,
    }
    return render(request, 'gravity/modificar_plan.html', context)


@login_required
def elegir_reservas_downgrade(request):
    """Paso que quedó integrado en 'Cambiar de plan' (se conserva la URL por enlaces viejos)."""
    request.session.pop('downgrade_plan_solicitado_id', None)
    return redirect('gravity:modificar_plan')

@login_required
def mis_planes(request):
    """Plan vigente, solicitud en revisión, qué pasaría si se da de baja hoy e historial."""
    hoy = timezone.localtime(timezone.now()).date()

    planes_activos = list(
        PlanUsuario.objects.filter(usuario=request.user, activo=True)
        .select_related('plan').order_by('fecha_inicio')
    )
    plan_vigente = next((p for p in planes_activos if p.fecha_inicio <= hoy <= p.fecha_fin), None)
    otros_planes = [p for p in planes_activos if p is not plan_vigente]
    anotar_planes([p.plan for p in planes_activos])

    historial = list(
        PlanUsuario.objects.filter(usuario=request.user, activo=False)
        .select_related('plan').order_by('-fecha_fin')[:5]
    )

    fijas = request.user.reservas_pilates.filter(activa=True, fecha_unica__isnull=True).count()
    uso = None
    if plan_vigente:
        clases = plan_vigente.plan.clases_por_semana
        uso = {
            'clases': clases,
            'fijas': fijas,
            'libres': max(0, clases - fijas),
            'porcentaje': min(100, round(fijas * 100 / clases)) if clases else 0,
            'renueva': plan_vigente.tipo_plan == 'permanente' and plan_vigente.renovacion_automatica,
            'renueva_el': plan_vigente.fecha_fin + timedelta(days=1),
            'dias_restantes': plan_vigente.dias_restantes(),
        }

    solicitud_pendiente = SolicitudCambioPlan.objects.filter(
        usuario=request.user, estado='pendiente'
    ).select_related('plan_actual', 'plan_solicitado').prefetch_related(
        'reservas_a_cancelar__clase'
    ).first()

    context = {
        'plan_vigente': plan_vigente,
        'otros_planes': otros_planes,
        'historial': historial,
        'uso': uso,
        'solicitud_pendiente': solicitud_pendiente,
        'politica': politica_baja_plan(hoy),
        'dia_hoy': hoy.day,
        'puede_cambiar_plan': bool(plan_vigente) and not solicitud_pendiente,
    }
    return render(request, 'gravity/mis_planes.html', context)

@login_required
def cancelar_plan(request, plan_id):
    """
    Vista para cancelar un plan específico del usuario
    """
    plan = get_object_or_404(
        PlanUsuario, 
        id=plan_id, 
        usuario=request.user, 
        activo=True  # Cambiar 'activa' por 'activo'
    )
    
    if request.method == 'POST':
        confirmacion = request.POST.get('confirmar_cancelacion')
        if confirmacion == 'confirmar':
            hoy = timezone.localtime(timezone.now()).date()
            dia_actual = hoy.day
            primer_dia_mes = date(hoy.year, hoy.month, 1)

            # --- Verificar si puede cancelar ---

            # 1. Deuda de meses anteriores → bloqueo siempre
            deuda_anterior = DeudaMensual.objects.filter(
                usuario=request.user,
                mes_año__lt=primer_dia_mes,
                estado__in=('pendiente', 'vencido', 'parcial')
            ).order_by('mes_año').first()

            if deuda_anterior:
                mes_str = deuda_anterior.mes_año.strftime('%B %Y').capitalize()
                messages.error(
                    request,
                    f'No podés cancelar tu plan porque tenés una deuda pendiente de {mes_str} '
                    f'(${deuda_anterior.monto_pendiente:,.0f}). '
                    f'Regularizá tu situación con la administración antes de cancelar.'
                )
                return redirect('gravity:mis_planes')

            # 2. Deuda del mes actual → bloqueo según situación
            try:
                deuda_mes_actual = DeudaMensual.objects.get(
                    usuario=request.user,
                    mes_año=primer_dia_mes
                )
                if deuda_mes_actual.monto_pendiente > 0:
                    # Detectar si la deuda fue modificada por una cancelación previa este mes
                    # (el monto original no coincide con el precio del plan y no es un medio mes por ingreso tardío)
                    deuda_de_cancelacion_previa = (
                        deuda_mes_actual.monto_original != plan.plan.precio_mensual
                        and not deuda_mes_actual.es_medio_mes
                    )
                    # Día 10+: debe pagar el mes completo antes de cancelar
                    debe_pagar_primero = dia_actual >= 10

                    if deuda_de_cancelacion_previa or debe_pagar_primero:
                        messages.error(
                            request,
                            f'No podés cancelar tu plan porque tenés una deuda pendiente de '
                            f'${deuda_mes_actual.monto_pendiente:,.0f} de este mes. '
                            f'Regularizá tu situación con la administración antes de cancelar.'
                        )
                        return redirect('gravity:mis_planes')
            except DeudaMensual.DoesNotExist:
                pass

            # --- Política de cobro ---
            try:
                deuda_actual = DeudaMensual.objects.get(
                    usuario=request.user,
                    mes_año=primer_dia_mes
                )
                if dia_actual <= 4:
                    if deuda_actual.estado in ('pendiente', 'vencido', 'parcial'):
                        deuda_actual.monto_original = Decimal('0')
                        deuda_actual.monto_pendiente = Decimal('0')
                        deuda_actual.estado = 'pagado'
                        deuda_actual.observaciones += (
                            f'\nDeuda anulada por cancelación de plan '
                            f'antes del día 5 ({hoy.strftime("%d/%m/%Y")}).'
                        )
                        deuda_actual.save()
                        try:
                            recalcular_estado_pagos(request.user)
                        except EstadoPagoCliente.DoesNotExist:
                            pass
                elif dia_actual <= 9:
                    if deuda_actual.estado in ('pendiente', 'vencido', 'parcial'):
                        monto_medio = (deuda_actual.monto_original / Decimal('2')).quantize(Decimal('0.01'))
                        deuda_actual.monto_original = monto_medio
                        deuda_actual.monto_pendiente = min(monto_medio, deuda_actual.monto_pendiente)
                        deuda_actual.observaciones += (
                            f'\nMonto ajustado a medio mes por cancelación '
                            f'entre día 5 y 9 ({hoy.strftime("%d/%m/%Y")}).'
                        )
                        deuda_actual.save()
                        try:
                            recalcular_estado_pagos(request.user)
                        except EstadoPagoCliente.DoesNotExist:
                            pass
            except DeudaMensual.DoesNotExist:
                pass

            # --- Cancelar todas las reservas de inmediato (permanentes y recuperos/cupos temporales) ---
            # La política según el día del mes solo afecta cuánto se le cobra (arriba),
            # no cuándo se cancelan las reservas: al confirmar la baja se cancelan todas ya mismo.
            canceladas = dar_de_baja_reservas(request.user.reservas_pilates.all())
            plan.reservas_canceladas = True

            # Cancelar el plan
            plan.activo = False
            plan.save()

            # Limpiar plan_actual en EstadoPagoCliente si no quedan otros planes activos
            if not PlanUsuario.objects.filter(usuario=request.user, activo=True).exists():
                try:
                    ep = request.user.estado_pago
                    ep.plan_actual = None
                    ep.save(update_fields=['plan_actual'])
                except EstadoPagoCliente.DoesNotExist:
                    pass

            # Crear notificación para administradores
            NotificacionCancelacionPlan.objects.create(
                usuario=request.user,
                plan=plan.plan,
            )

            # Si tenía una solicitud de cambio de plan pendiente, ya no aplica
            # porque el plan_actual que referenciaba dejó de existir
            SolicitudCambioPlan.objects.filter(
                usuario=request.user, estado='pendiente'
            ).update(
                estado='rechazada',
                fecha_resolucion=timezone.localtime(timezone.now()),
                observaciones='Rechazada automáticamente: el usuario canceló su plan actual.'
            )

            # Mensaje según política de cobro aplicada (las reservas ya se cancelaron todas)
            if dia_actual <= 4:
                msg_cobro = 'No se te cobrará el mes actual.'
            elif dia_actual <= 9:
                msg_cobro = 'Se te cobrará la mitad del mes actual.'
            else:
                msg_cobro = 'Se te cobrará el mes completo.'

            msg_reservas = f'Se cancelaron {canceladas} reserva{"s" if canceladas != 1 else ""}.'

            messages.success(
                request,
                f'Plan "{plan.plan.nombre}" cancelado. {msg_cobro} {msg_reservas}'
            )
        else:
            messages.error(request, 'Error en la confirmación.')

        return redirect('gravity:mis_planes')

    # --- GET: preparar contexto ---
    hoy = timezone.localtime(timezone.now()).date()
    anotar_planes([plan.plan])
    reservas_activas = sorted(
        request.user.reservas_pilates.filter(activa=True).select_related('clase'),
        key=lambda r: (r.fecha_unica is not None, r.fecha_unica or hoy, r.clase.horario),
    )

    context = {
        'plan': plan,
        'reservas_activas': reservas_activas,
        'politica': politica_baja_plan(hoy),
        'dia_actual': hoy.day,
    }

    return render(request, 'gravity/cancelar_plan.html', context)

# ==============================================================================
# VISTAS ADMIN — TESTIMONIOS
# ==============================================================================

@superadmin_required
def admin_testimonios_lista(request):
    """Lista todos los testimonios con filtros y permite aprobar/rechazar"""
    testimonios = Testimonio.objects.select_related('usuario').all()

    # Filtro por estado
    estado_filtro = request.GET.get('estado', '')
    if estado_filtro == 'pendientes':
        testimonios = testimonios.filter(aprobado=False)
    elif estado_filtro == 'aprobados':
        testimonios = testimonios.filter(aprobado=True)

    # Filtro por búsqueda de alumno
    busqueda_filtro = request.GET.get('busqueda', '')
    if busqueda_filtro:
        testimonios = testimonios.filter(
            Q(usuario__first_name__icontains=busqueda_filtro) |
            Q(usuario__last_name__icontains=busqueda_filtro) |
            Q(usuario__email__icontains=busqueda_filtro)
        )

    context = {
        'testimonios': testimonios,
        'total_pendientes': Testimonio.objects.filter(aprobado=False).count(),
        'total_aprobados': Testimonio.objects.filter(aprobado=True).count(),
        'estado_filtro': estado_filtro,
        'busqueda_filtro': busqueda_filtro,
    }
    return render(request, 'gravity/admin/testimonios_lista.html', context)

@superadmin_required
def admin_testimonio_aprobar(request, testimonio_id):
    """Aprueba un testimonio para que sea visible públicamente"""
    if request.method != 'POST':
        return redirect('gravity:admin_testimonios_lista')

    testimonio = get_object_or_404(Testimonio, id=testimonio_id)
    testimonio.aprobado = True
    testimonio.save()
    messages.success(request, f'Testimonio de {testimonio.usuario.get_full_name() or testimonio.usuario.username} aprobado correctamente.')
    return redirect('gravity:admin_testimonios_lista')


@superadmin_required
def admin_testimonio_rechazar(request, testimonio_id):
    """Vuelve un testimonio a estado pendiente"""
    if request.method != 'POST':
        return redirect('gravity:admin_testimonios_lista')

    testimonio = get_object_or_404(Testimonio, id=testimonio_id)
    testimonio.aprobado = False
    # Guardamos directamente sin pasar por el save() del modelo
    # para no activar la lógica de "texto cambiado"
    Testimonio.objects.filter(pk=testimonio.pk).update(aprobado=False)
    messages.success(request, f'Testimonio de {testimonio.usuario.get_full_name() or testimonio.usuario.username} vuelto a pendiente.')
    return redirect('gravity:admin_testimonios_lista')


@superadmin_required
def admin_testimonio_eliminar(request, testimonio_id):
    """Elimina un testimonio definitivamente"""
    if request.method != 'POST':
        return redirect('gravity:admin_testimonios_lista')

    testimonio = get_object_or_404(Testimonio, id=testimonio_id)
    nombre = testimonio.usuario.get_full_name() or testimonio.usuario.username
    testimonio.delete()
    messages.success(request, f'Testimonio de {nombre} eliminado correctamente.')
    return redirect('gravity:admin_testimonios_lista')

# ==============================================================================
# VISTAS ADMIN — SOLICITUDES DE CAMBIO DE PLAN
# ==============================================================================

@superadmin_required
def admin_solicitudes_plan_lista(request):
    """Lista todas las solicitudes de cambio de plan con filtros y permite aprobar/rechazar"""
    solicitudes = SolicitudCambioPlan.objects.select_related(
        'usuario', 'plan_actual', 'plan_solicitado', 'resuelto_por'
    ).prefetch_related('reservas_a_cancelar__clase').all()

    estado_filtro = request.GET.get('estado', 'pendiente')
    if estado_filtro in ('pendiente', 'aprobada', 'rechazada'):
        solicitudes = solicitudes.filter(estado=estado_filtro)
    else:
        estado_filtro = 'todas'
    solicitudes = solicitudes.order_by('-fecha_solicitud')

    busqueda_filtro = request.GET.get('busqueda', '')
    if busqueda_filtro:
        solicitudes = solicitudes.filter(
            Q(usuario__first_name__icontains=busqueda_filtro) |
            Q(usuario__last_name__icontains=busqueda_filtro) |
            Q(usuario__email__icontains=busqueda_filtro)
        )

    context = {
        'solicitudes': solicitudes,
        'total_pendientes': SolicitudCambioPlan.objects.filter(estado='pendiente').count(),
        'total_aprobadas': SolicitudCambioPlan.objects.filter(estado='aprobada').count(),
        'total_rechazadas': SolicitudCambioPlan.objects.filter(estado='rechazada').count(),
        'estado_filtro': estado_filtro,
        'busqueda_filtro': busqueda_filtro,
    }
    return render(request, 'gravity/admin/solicitudes_plan_lista.html', context)

@superadmin_required
def admin_solicitud_plan_aprobar(request, solicitud_id):
    """Aprueba una solicitud de cambio de plan: asigna el nuevo plan y cancela las reservas cedidas"""
    if request.method != 'POST':
        return redirect('gravity:admin_solicitudes_plan_lista')

    solicitud = get_object_or_404(SolicitudCambioPlan, id=solicitud_id)

    if solicitud.estado != 'pendiente':
        messages.error(request, 'Esta solicitud ya fue resuelta.')
        return redirect('gravity:admin_solicitudes_plan_lista')

    usuario = solicitud.usuario

    with transaction.atomic():
        PlanUsuario.objects.filter(usuario=usuario, activo=True).update(activo=False)

        PlanUsuario.objects.create(
            usuario=usuario,
            plan=solicitud.plan_solicitado,
            fecha_inicio=timezone.localtime(timezone.now()).date(),
            fecha_fin=date(2099, 12, 31),
            tipo_plan='permanente',
            renovacion_automatica=True,
            creado_por=request.user,
            observaciones=f'Creado por aprobación de solicitud de cambio de plan #{solicitud.id}'
        )

        estado_cliente, _ = EstadoPagoCliente.objects.get_or_create(
            usuario=usuario,
            defaults={'activo': True}
        )
        estado_cliente.plan_actual = solicitud.plan_solicitado
        estado_cliente.save(update_fields=['plan_actual'])

        # Ajustar la facturación del mes actual según corresponda
        if solicitud.plan_actual:
            # Cambio de plan existente: reemplazar el monto del mes por el nuevo precio,
            # respetando lo ya pagado (ver EstadoPagoCliente.ajustar_deuda_por_cambio_plan)
            estado_cliente.ajustar_deuda_por_cambio_plan(solicitud.plan_solicitado)
        else:
            # Primer plan del usuario: generar la deuda del mes con la política habitual
            # (mes completo o medio mes según el día de aprobación)
            estado_cliente.generar_deuda_mes_actual()

        # Los horarios que el alumno eligió liberar: baja suya, con registro (para el historial)
        for reserva in solicitud.reservas_a_cancelar.filter(activa=True):
            reserva.activa = False
            reserva.save()
            aviso = NotificacionCancelacion.objects.create(reserva=reserva, tipo='permanente')
            aviso.leida_por.add(request.user)

        solicitud.estado = 'aprobada'
        solicitud.fecha_resolucion = timezone.localtime(timezone.now())
        solicitud.resuelto_por = request.user
        solicitud.save(update_fields=['estado', 'fecha_resolucion', 'resuelto_por'])

    try:
        enviar_email_cambio_plan_aprobado(solicitud)
    except Exception as e:
        logger.error(f"Error enviando email de cambio de plan aprobado (solicitud {solicitud.id}): {str(e)}")

    messages.success(
        request,
        f'Solicitud aprobada. {usuario.get_full_name() or usuario.username} ahora tiene el plan '
        f'"{solicitud.plan_solicitado.nombre}".'
    )
    return redirect('gravity:admin_solicitudes_plan_lista')

@superadmin_required
def admin_solicitud_plan_rechazar(request, solicitud_id):
    """Rechaza una solicitud de cambio de plan. No se modifica el plan ni las reservas del usuario."""
    if request.method != 'POST':
        return redirect('gravity:admin_solicitudes_plan_lista')

    solicitud = get_object_or_404(SolicitudCambioPlan, id=solicitud_id)

    if solicitud.estado != 'pendiente':
        messages.error(request, 'Esta solicitud ya fue resuelta.')
        return redirect('gravity:admin_solicitudes_plan_lista')

    motivo = request.POST.get('motivo_rechazo', '').strip()

    solicitud.estado = 'rechazada'
    solicitud.fecha_resolucion = timezone.localtime(timezone.now())
    solicitud.resuelto_por = request.user
    if motivo:
        solicitud.observaciones = motivo
    solicitud.save(update_fields=['estado', 'fecha_resolucion', 'resuelto_por', 'observaciones'])

    texto = f'Rechazaste la solicitud de {solicitud.usuario.get_full_name() or solicitud.usuario.username}.'
    if solicitud.usuario.email:
        if enviar_email_solicitud_rechazada(solicitud):
            texto += f' Le avisamos a {solicitud.usuario.email}.'
        else:
            texto += ' No se pudo mandar el email.'
    messages.success(request, texto)
    return redirect('gravity:admin_solicitudes_plan_lista')

# ==============================================================================
# VISTAS ADMIN — HISTORIAL DE ACTIVIDAD
# ==============================================================================

@admin_required
def admin_historial_actividad(request):
    """
    Actividad de los alumnos (bajas, avisos, planes, recuperos, clases únicas y
    cancelaciones del estudio), agrupada por día. Por defecto, los últimos 30 días.
    Los eventos se arman en gravity/actividad.py.
    """
    hoy = timezone.localdate()

    def fecha_get(clave):
        try:
            return date.fromisoformat(request.GET.get(clave, ''))
        except ValueError:
            return None

    tipo = request.GET.get('tipo', '')
    if tipo not in dict(TIPOS_ACTIVIDAD):
        tipo = ''
    buscar = request.GET.get('usuario', '').strip()
    sede = request.GET.get('sede', '')
    if sede not in dict(Clase.DIRECCIONES):
        sede = ''
    fecha_unica_desde = fecha_get('fecha_unica_desde')

    desde, hasta = fecha_get('fecha_desde'), fecha_get('fecha_hasta')
    dias = request.GET.get('dias', '')
    personalizado = bool(desde or hasta)
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
    if not personalizado:
        dias = dias if dias in ('7', '30', '90') else '30'
        desde, hasta = hoy - timedelta(days=int(dias) - 1), hoy
    if fecha_unica_desde:
        # "Próximos recuperos / clases únicas": por fecha de la clase, sin rango de creación
        desde = hasta = None

    todos = eventos_actividad(buscar=buscar, sede=sede, desde=desde, hasta=hasta,
                              fecha_unica_desde=fecha_unica_desde)
    conteo = {}
    for e in todos:
        conteo[e['tipo']] = conteo.get(e['tipo'], 0) + 1
    eventos = [e for e in todos if e['tipo'] == tipo] if tipo else todos

    page_obj = Paginator(eventos, 30).get_page(request.GET.get('page'))
    ayer = hoy - timedelta(days=1)
    for e in page_obj:
        if e['dia'] == hoy:
            e['dia_texto'] = 'Hoy'
        elif e['dia'] == ayer:
            e['dia_texto'] = 'Ayer'
        else:
            e['dia_texto'] = fecha_larga(e['dia'])

    # Filtros actuales sin el tipo ni la página, para armar los enlaces de los chips
    params = request.GET.copy()
    for clave in ('tipo', 'page'):
        params.pop(clave, None)
    params_pagina = request.GET.copy()
    params_pagina.pop('page', None)

    context = {
        'page_obj': page_obj,
        'total_eventos': len(eventos),
        'total_todos': len(todos),
        'tipos': [{'clave': c, 'texto': t, 'cantidad': conteo.get(c, 0)} for c, t in TIPOS_ACTIVIDAD],
        'tipo_filtro': tipo,
        'usuario_filtro': buscar,
        'sede_filtro': sede,
        'sedes': Clase.DIRECCIONES,
        'dias': dias,
        'personalizado': personalizado,
        'desde': desde,
        'hasta': hasta,
        'fecha_unica_desde': fecha_unica_desde,
        'qs_sin_tipo': params.urlencode(),
        'qs_pagina': params_pagina.urlencode(),
        'hoy': hoy,
    }
    return render(request, 'gravity/admin/historial_actividad.html', context)

# ==============================================================================
# PWA - MANIFEST Y SERVICE WORKER
# ==============================================================================

def manifest_json(request):
    manifest = {
        "name": "Pilates Gravity",
        "short_name": "Gravity",
        "description": "Reservá tus clases de Pilates en Gravity",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#F8EFE5",
        "theme_color": "#5D768B",
        "orientation": "portrait",
        "lang": "es",
        "id": "/",
        "start_url": "/",
        "icons": [
            {
                "src": "/static/icons/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any"
            }
        ]
    }
    return JsonResponse(manifest)

def _version_deploy():
    """
    Versión del service worker: el commit desplegado (cambia con cada git pull).
    Así cada deploy instala un service worker nuevo y los clientes se actualizan solos.
    Si no se puede leer git, usa la fecha del día.
    """
    from pathlib import Path
    from django.conf import settings
    try:
        git_dir = Path(settings.BASE_DIR) / '.git'
        head = (git_dir / 'HEAD').read_text().strip()
        if head.startswith('ref:'):
            ref = head.split(' ', 1)[1].strip()
            ref_file = git_dir / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:12]
            # refs empaquetadas (después de un git gc)
            for linea in (git_dir / 'packed-refs').read_text().splitlines():
                if linea.endswith(' ' + ref):
                    return linea.split(' ', 1)[0][:12]
        return head[:12]
    except Exception:
        return timezone.localtime(timezone.now()).strftime('%Y%m%d')


def service_worker_js(request):
    version = _version_deploy()
    sw_content = f"""
        const CACHE_NAME = 'pilates-gravity-{version}';
        const OFFLINE_ASSETS = [
            '/',
            '/static/css/tailwind-output.css',
            '/static/icons/icon-192x192.png',
        ];

        self.addEventListener('install', (event) => {{
            event.waitUntil(
                caches.open(CACHE_NAME).then((cache) => cache.addAll(OFFLINE_ASSETS))
            );
            self.skipWaiting();
        }});

        self.addEventListener('activate', (event) => {{
            event.waitUntil(
                caches.keys().then((cacheNames) => Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => caches.delete(name))
                )).then(() => self.clients.claim())
                  .then(() => self.clients.matchAll({{ type: 'window' }}))
                  .then((clients) => {{
                      clients.forEach(client => client.postMessage({{ type: 'SW_UPDATED' }}));
                  }})
            );
        }});

        self.addEventListener('fetch', (event) => {{
            const req = event.request;
            if (req.method !== 'GET') return;

            // Páginas: siempre primero la red (contenido al día); la caché solo sin conexión
            if (req.mode === 'navigate') {{
                event.respondWith(
                    fetch(req).catch(() => caches.match(req).then(r => r || caches.match('/')))
                );
                return;
            }}

            // Archivos precargados: red primero y caché como respaldo
            const url = new URL(req.url);
            if (url.origin === location.origin && OFFLINE_ASSETS.includes(url.pathname)) {{
                event.respondWith(fetch(req).catch(() => caches.match(req)));
            }}
            // El resto (videos, imágenes, CSS/JS versionados) va directo a la red
        }});
    """
    response = HttpResponse(sw_content, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Service-Worker-Allowed'] = '/'
    return response

# ==============================================================================
# VISTAS PÚBLICAS DE LINKS PARA REDES SOCIALES
# ==============================================================================

def links(request):
    """Página pública de links para bio de redes sociales"""
    return render(request, 'gravity/links.html')