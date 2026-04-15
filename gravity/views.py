from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .models import Reserva, Clase, PlanUsuario, AusenciaTemporal, NotificacionCancelacion, NotificacionCancelacionPlan, DIAS_SEMANA, DIAS_SEMANA_COMPLETOS
from .forms import ReservaForm, ModificarReservaForm, BuscarReservaForm
import json
import calendar
from accounts.models import UserProfile
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
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
    enviar_email_modificacion_reserva
)
from .models import PlanPago, EstadoPagoCliente, RegistroPago, DeudaMensual
from .forms import ( PlanPagoForm, RegistroPagoForm, EstadoPagoClienteForm, FiltrosPagosForm )
from django.db.models import Sum, Count, Q
from decimal import Decimal

# Configurar el logger
logger = logging.getLogger(__name__)

# Página de inicio (pública)
def home(request):
    """Vista pública de la página principal"""
    return render(request, 'gravity/home.html')

# Vista para reservar una clase (solo usuarios autenticados)
@login_required
def reservar_clase(request):
    """
    Permite a un usuario autenticado crear una nueva reserva.
    Utiliza ReservaForm que ya tiene todas las validaciones necesarias.
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
                f'❌ No puedes reservar clases porque tienes una deuda vencida de ${estado_pago.monto_deuda_mensual:,.0f}. '
                f'La fecha límite de pago era el {estado_pago.fecha_limite_pago.strftime("%d/%m/%Y")} '
                f'({dias_atraso} {"día" if dias_atraso == 1 else "días"} de atraso). '
                f'Por favor, realiza el pago o contacta a la administración para regularizar tu situación.'
            )
            return redirect('accounts:profile')
    except EstadoPagoCliente.DoesNotExist:
        # Usuario sin estado de pago, permitir reservar
        pass

    # Obtener o crear el perfil del usuario
    try:
        user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        user_profile = UserProfile.objects.create(user=request.user)

    # Obtener tipo preseleccionado ANTES del bloque if/else
    tipo_preseleccionado = request.GET.get('tipo', '')
    
    # **NUEVA LÓGICA DE PLANES**
    planes_activos = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=True,
        fecha_fin__gte=timezone.now().date()
    ).select_related('plan')
    
    # Calcular clases disponibles según planes
    clases_disponibles, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    
    # Contar reservas de esta semana
    reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)
    
    # Calcular clases restantes
    clases_restantes = max(0, clases_disponibles - reservas_actuales)
    
    if request.method == 'POST':
        form = ReservaForm(request.POST, user=request.user)
        
        if form.is_valid():
            try:
                # El formulario ya validó todo y nos devuelve la clase en cleaned_data
                clase = form.cleaned_data['clase']
                
                # Crear la reserva
                es_temporal = request.POST.get('es_temporal') == 'true'
                fecha_unica = None

                if es_temporal:
                    hoy = timezone.now().date()
                    dias_map = {
                        'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
                        'Jueves': 3, 'Viernes': 4, 'Sábado': 5
                    }
                    dia_clase = dias_map.get(clase.dia, 0)
                    dias_hasta = (dia_clase - hoy.weekday()) % 7
                    if dias_hasta == 0:
                        ahora = timezone.localtime(timezone.now())
                        clase_hoy = ahora.replace(
                            hour=clase.horario.hour,
                            minute=clase.horario.minute,
                            second=0, microsecond=0
                        )
                        if ahora >= clase_hoy - timedelta(hours=3):
                            dias_hasta = 7
                    fecha_unica = hoy + timedelta(days=dias_hasta)

                reserva = Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_unica=fecha_unica
                )

                # 📧 ENVIAR EMAIL DE CONFIRMACIÓN DE RESERVA
                try:
                    email_enviado = enviar_email_confirmacion_reserva_detallado(reserva)
                    if email_enviado:
                        logger.info(f"Email de confirmación enviado para reserva {reserva.numero_reserva}")
                except Exception as e:
                    logger.error(f"Error enviando email de confirmación: {str(e)}")
                
                request.session['reserva_exitosa'] = {
                    'tipo': 'temporal' if es_temporal else 'recurrente',
                    'clase': clase.get_nombre_display(),
                    'dia': clase.dia,
                    'horario': clase.horario.strftime('%H:%M'),
                    'sede': clase.get_direccion_corta(),
                    'fecha_unica': fecha_unica.strftime('%d/%m/%Y') if fecha_unica else None,
                }
                return redirect('accounts:mis_reservas')
                
            except IntegrityError:
                # Error de duplicado - no debería ocurrir por las validaciones del form
                messages.error(
                    request,
                    'Error interno: Ya tienes una reserva para esta clase. '
                    'Si esto persiste, contacta al administrador.'
                )
    else:
        # Permitir preseleccionar tipo de clase desde URL
        initial_data = {'tipo_clase': tipo_preseleccionado} if tipo_preseleccionado else None
        form = ReservaForm(user=request.user, initial=initial_data)

    # Preparar información del usuario para mostrar en el template
    user_info = {
        'username': request.user.username,
        'first_name': request.user.first_name,
        'last_name': request.user.last_name,
        'email': request.user.email,
        'telefono': user_profile.telefono if user_profile.telefono else '',
        'nombre_completo': user_profile.get_nombre_completo()
    }

    return render(request, 'gravity/reservar_clase.html', {
        'form': form,
        'user_info': user_info,
        'tipo_preseleccionado': tipo_preseleccionado,
        # **NUEVOS DATOS DE PLANES**
        'planes_activos': planes_activos,
        'clases_disponibles': clases_disponibles,
        'reservas_actuales': reservas_actuales,
        'clases_restantes': clases_restantes,
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
                
            except IntegrityError:
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
        messages.error(request, f'No puedes cancelar esta reserva: {mensaje}')
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    if request.method == 'POST':
        confirmar = request.POST.get('confirmar_cancelacion')
        tipo = request.POST.get('tipo_cancelacion', 'permanente')

        if confirmar != 'confirmar':
            messages.error(request, 'Debes confirmar la cancelación.')
            return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

        try:
            if tipo == 'temporal':
                proxima_fecha = reserva.get_proxima_fecha()

                if not proxima_fecha:
                    messages.error(request, 'No se pudo determinar la próxima fecha de clase.')
                    return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

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
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    # GET: redirigir al detalle (el modal está ahí)
    return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

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
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    # 1. Verificar ventana de 3 horas
    puede_modificar, mensaje = reserva.puede_modificarse()
    if not puede_modificar:
        messages.error(
            request,
            f'No podés cancelar la ausencia: {mensaje}'
        )
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

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
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    # 3. Todo ok: eliminar la ausencia
    fecha_str = ausencia.fecha.strftime('%d/%m/%Y')
    ausencia.delete()

    messages.success(
        request,
        f'Ausencia cancelada. Tu lugar para el {fecha_str} está confirmado nuevamente.'
    )
    return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

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
def detalle_reserva(request, numero_reserva):
    """
    Muestra el detalle de una reserva específica.
    Solo el dueño de la reserva puede verla (o admin más adelante).
    """
    reserva = get_object_or_404(Reserva, numero_reserva=numero_reserva, activa=True)
    
    # Verificar permisos: solo el dueño puede ver su reserva
    if request.user.is_authenticated and request.user == reserva.usuario:
        puede_ver = True
        es_propietario = True
    else:
        # Para usuarios no autenticados o que no son dueños, no mostrar
        puede_ver = False
        es_propietario = False
    
    if not puede_ver:
        messages.error(request, 'No tienes permisos para ver esta reserva.')
        return redirect('gravity:home')
    
    # Obtener información sobre si puede modificarse
    puede_modificar, mensaje_modificacion = reserva.puede_modificarse()
    
     # Ausencia registrada para la próxima clase (filtrando por fecha exacta)
    proxima_fecha = reserva.get_proxima_fecha()
    ausencia_proxima = None
    if proxima_fecha:
        ausencia_proxima = AusenciaTemporal.objects.filter(
            reserva=reserva,
            fecha=proxima_fecha,
        ).first()

    return render(request, 'gravity/detalle_reserva.html', {
        'reserva': reserva,
        'puede_modificar': puede_modificar,
        'mensaje_modificacion': mensaje_modificacion,
        'proxima_clase_info': reserva.get_proxima_clase_info(),
        'es_propietario': es_propietario,
        'ausencia_proxima': ausencia_proxima,
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
    """Vista informativa sobre el estudio"""
    testimonios = Testimonio.objects.filter(aprobado=True).select_related('usuario').order_by('-fecha_actualizacion')
    return render(request, 'gravity/conoce_mas.html', {'testimonios': testimonios})

# API Endpoints para funcionalidad AJAX
@require_http_methods(["POST"])
def sedes_disponibles(request):
    """
    API que devuelve las sedes únicas disponibles para un tipo de clase específico
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        
        if not tipo_clase:
            return JsonResponse({'error': 'Tipo de clase requerido'}, status=400)

        # Obtener sedes únicas para el tipo de clase (solo clases activas)
        # Usar distinct() correctamente con order_by
        sedes_disponibles = Clase.objects.filter(
            tipo=tipo_clase, 
            activa=True
        ).values('direccion').distinct().order_by('direccion')

        # Convertir a formato legible, asegurándonos de que sean únicas
        sedes_info = []
        sedes_agregadas = set()  # Para evitar duplicados
        
        for sede_dict in sedes_disponibles:
            sede = sede_dict['direccion']
            if sede not in sedes_agregadas:
                sede_display = dict(Clase.DIRECCIONES).get(sede, sede)
                sedes_info.append({
                    'value': sede,
                    'text': sede_display
                })
                sedes_agregadas.add(sede)

        return JsonResponse({
            'sedes': sedes_info
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

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

@require_http_methods(["POST"])
def verificar_disponibilidad(request):
    """
    API que verifica la disponibilidad de una combinación específica tipo-sede-día-horario
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        sede = data.get('sede')
        dia_clase = data.get('dia')
        horario_str = data.get('horario')
        
        if not all([tipo_clase, sede, dia_clase, horario_str]):
            return JsonResponse({'error': 'Todos los campos son requeridos'}, status=400)
        
        from datetime import datetime
        horario_time = datetime.strptime(horario_str, '%H:%M').time()
        
        try:
            clase = Clase.objects.get(
                tipo=tipo_clase,
                direccion=sede,
                dia=dia_clase, 
                horario=horario_time,
                activa=True
            )
            cupos_disponibles = clase.cupos_disponibles()
            
            return JsonResponse({
                'disponible': cupos_disponibles > 0,
                'cupos_disponibles': cupos_disponibles,
                'cupo_maximo': clase.cupo_maximo,
                'sede': clase.get_direccion_corta(),
                'mensaje': f'Quedan {cupos_disponibles} cupos disponibles en {clase.get_direccion_corta()}' if cupos_disponibles > 0 else 'Clase completa'
            })
            
        except Clase.DoesNotExist:
            return JsonResponse({
                'disponible': False,
                'mensaje': 'Esta combinación de clase no existe o no está activa'
            })
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
    except ValueError:
        return JsonResponse({'error': 'Formato de horario inválido'}, status=400)
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

def get_puede_ver_pagos(user):
    """
    Retorna True si el usuario tiene permiso para ver información financiera.
    Por defecto True (acceso completo). Solo False si se configuró explícitamente.
    """
    try:
        return user.profile.puede_ver_pagos
    except Exception:
        return True

# ==============================================================================
# DASHBOARD PRINCIPAL DEL ADMINISTRADOR
# ==============================================================================

@admin_required
def admin_dashboard(request):
    """
    Panel principal del administrador con estadísticas y resumen general
    Ahora incluye estadísticas por sede
    """
    # Estadísticas generales
    total_clases = Clase.objects.filter(activa=True).count()
    total_reservas_activas = Reserva.objects.filter(activa=True).count()
    total_usuarios = User.objects.filter(is_active=True, is_staff=False).count()
    
    # Estadísticas por sede
    stats_por_sede = []
    for direccion_key, direccion_display in Clase.DIRECCIONES:
        clases_sede = Clase.objects.filter(direccion=direccion_key, activa=True)
        total_clases_sede = clases_sede.count()
        total_reservas_sede = Reserva.objects.filter(
            clase__direccion=direccion_key,
            activa=True
        ).count()
        
        stats_por_sede.append({
            'sede': direccion_display,
            'total_clases': total_clases_sede,
            'total_reservas': total_reservas_sede,
            'porcentaje_reservas': round((total_reservas_sede / total_reservas_activas * 100), 2) if total_reservas_activas > 0 else 0
        })
    
    # Clases más populares
    clases_populares = Clase.objects.filter(activa=True).annotate(
        total_reservas=Count('reserva', filter=Q(reserva__activa=True))
    ).order_by('-total_reservas')[:5]
    
    # Reservas recientes (últimas 10)
    reservas_recientes = Reserva.objects.filter(activa=True).select_related(
        'usuario', 'clase'
    ).order_by('-fecha_reserva')[:10]
    
    # Usuarios registrados recientemente (últimos 7 días)
    hace_una_semana = timezone.now() - timedelta(days=7)
    usuarios_nuevos = User.objects.filter(
        date_joined__gte=hace_una_semana,
        is_staff=False
    ).count()
    
    # Clases con poco cupo disponible (menos del 20%)
    clases_casi_llenas = []
    for clase in Clase.objects.filter(activa=True):
        cupos_disponibles = clase.cupos_disponibles()
        porcentaje_ocupacion = clase.get_porcentaje_ocupacion()
        if porcentaje_ocupacion >= 80:  # Más del 80% ocupado
            clases_casi_llenas.append({
                'clase': clase,
                'cupos_disponibles': cupos_disponibles,
                'porcentaje_ocupacion': porcentaje_ocupacion
            })
    
    # Configuración del estudio
    configuracion = ConfiguracionEstudio.get_configuracion()

    # Notificaciones de cancelaciones de reservas (últimos 7 días, no leídas)
    try:
        notificaciones_cancelacion = NotificacionCancelacion.objects.filter(
            fecha_creacion__gte=hace_una_semana
        ).exclude(
            leida_por=request.user
        ).select_related('reserva', 'reserva__clase', 'reserva__usuario').order_by('-fecha_creacion')
    except Exception:
        notificaciones_cancelacion = NotificacionCancelacion.objects.none()

    # Notificaciones de cancelaciones de planes (últimos 30 días, no leídas)
    desde_30_dias = timezone.now() - timedelta(days=30)
    try:
        notificaciones_cancelacion_plan = NotificacionCancelacionPlan.objects.filter(
            fecha_creacion__gte=desde_30_dias
        ).exclude(
            leida_por=request.user
        ).select_related('usuario', 'plan').order_by('-fecha_creacion')
    except Exception:
        notificaciones_cancelacion_plan = NotificacionCancelacionPlan.objects.none()

    # Reservas de cupos temporales recientes (últimos 7 días, no vistas en sesión)
    recuperos_vistos = request.session.get('recuperos_vistos', [])
    reservas_temporales_recientes = Reserva.objects.filter(
        activa=True,
        fecha_unica__isnull=False,
        fecha_reserva__gte=hace_una_semana,
    ).exclude(
        id__in=recuperos_vistos
    ).select_related('usuario', 'clase').order_by('-fecha_reserva')
    hay_reservas_temporales = reservas_temporales_recientes.exists()

    context = {
        'total_clases': total_clases,
        'total_reservas_activas': total_reservas_activas,
        'total_usuarios': total_usuarios,
        'usuarios_nuevos': usuarios_nuevos,
        'stats_por_sede': stats_por_sede,
        'clases_populares': clases_populares,
        'reservas_recientes': reservas_recientes,
        'clases_casi_llenas': clases_casi_llenas,
        'configuracion': configuracion,
        'notificaciones_cancelacion': notificaciones_cancelacion,
        'hay_notificaciones': notificaciones_cancelacion.exists(),
        'notificaciones_cancelacion_plan': notificaciones_cancelacion_plan,
        'hay_notificaciones_plan': notificaciones_cancelacion_plan.exists(),
        'reservas_temporales_recientes': reservas_temporales_recientes,
        'hay_reservas_temporales': hay_reservas_temporales,
        'total_notificaciones': (
            notificaciones_cancelacion.count() +
            notificaciones_cancelacion_plan.count() +
            reservas_temporales_recientes.count()
        ),
        'puede_ver_pagos': get_puede_ver_pagos(request.user),
    }

    return render(request, 'gravity/admin/dashboard.html', context)

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
    Lista todas las clases con opciones de filtrado y paginación
    Ahora incluye filtros por sede
    """
    clases = Clase.objects.all().order_by('direccion', 'tipo', 'dia', 'horario')
    
    # Filtros
    tipo_filtro = request.GET.get('tipo', '')
    dia_filtro = request.GET.get('dia', '')
    estado_filtro = request.GET.get('estado', '')
    sede_filtro = request.GET.get('sede', '')
    
    if tipo_filtro:
        clases = clases.filter(tipo=tipo_filtro)
    
    if dia_filtro:
        clases = clases.filter(dia=dia_filtro)
    
    if sede_filtro:
        clases = clases.filter(direccion=sede_filtro)
    
    if estado_filtro == 'activas':
        clases = clases.filter(activa=True)
    elif estado_filtro == 'inactivas':
        clases = clases.filter(activa=False)
    
    # Agregar información de reservas a cada clase
    clases_info = []
    for clase in clases:
        clases_info.append({
            'clase': clase,
            'total_reservas': clase.reserva_set.filter(activa=True).count(),
            'cupos_disponibles': clase.cupos_disponibles(),
            'porcentaje_ocupacion': clase.get_porcentaje_ocupacion(),
            'puede_eliminarse': clase.puede_eliminarse()
        })
    
    # Paginación
    paginator = Paginator(clases_info, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'tipo_filtro': tipo_filtro,
        'dia_filtro': dia_filtro,
        'estado_filtro': estado_filtro,
        'sede_filtro': sede_filtro,
        'tipos_clases': Clase.TIPO_CLASES,
        'dias_semana': DIAS_SEMANA_COMPLETOS,
        'sedes': Clase.DIRECCIONES,
    }
    
    return render(request, 'gravity/admin/clases_lista.html', context)

@admin_required
def admin_clase_crear(request):
    """
    Crear una nueva clase - Actualizado para incluir direccion
    """
    if request.method == 'POST':
        # Obtener datos del formulario
        tipo = request.POST.get('tipo')
        nombre_personalizado = request.POST.get('nombre_personalizado', '').strip() or None
        direccion = request.POST.get('direccion')
        dia = request.POST.get('dia')
        horario_str = request.POST.get('horario')
        cupo_maximo = request.POST.get('cupo_maximo')
        
        try:
            # Validar horario
            horario = datetime.strptime(horario_str, '%H:%M').time()
            
            # Validaciones específicas para clases especiales
            if tipo == 'Especial':
                if not nombre_personalizado:
                    messages.error(request, 'Las clases especiales deben tener un nombre personalizado.')
                    return render(request, 'gravity/admin/clase_form.html', {
                        'tipos_clases': Clase.TIPO_CLASES,
                        'dias_semana': DIAS_SEMANA_COMPLETOS,
                        'direcciones': Clase.DIRECCIONES,
                        'form_data': request.POST
                    })
            elif nombre_personalizado:
                messages.error(request, 'Solo las clases especiales pueden tener nombre personalizado.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'form_data': request.POST
                })
            
            # Validar día para clases no especiales
            if dia == 'Sábado' and tipo != 'Especial':
                messages.error(request, 'Solo las clases especiales pueden programarse los sábados.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'form_data': request.POST
                })
            
            # Construir filtro para verificar duplicados
            duplicate_filter = {
                'tipo': tipo,
                'direccion': direccion,
                'dia': dia,
                'horario': horario
            }
            
            if tipo == 'Especial':
                duplicate_filter['nombre_personalizado'] = nombre_personalizado
            else:
                duplicate_filter['nombre_personalizado__isnull'] = True
            
            # Verificar que no exista una clase igual
            if Clase.objects.filter(**duplicate_filter).exists():
                direccion_display = dict(Clase.DIRECCIONES).get(direccion, direccion)
                if tipo == 'Especial':
                    error_msg = f'Ya existe una clase especial "{nombre_personalizado}" los {dia} a las {horario_str} en {direccion_display}.'
                else:
                    tipo_display = dict(Clase.TIPO_CLASES).get(tipo, tipo)
                    error_msg = f'Ya existe una clase de {tipo_display} los {dia} a las {horario_str} en {direccion_display}.'
                
                messages.error(request, error_msg)
                return render(request, 'gravity/admin/clase_form.html', {
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'form_data': request.POST
                })
            
            # Crear la clase
            clase = Clase.objects.create(
                tipo=tipo,
                nombre_personalizado=nombre_personalizado,
                direccion=direccion,
                dia=dia,
                horario=horario,
                cupo_maximo=int(cupo_maximo),
                activa=True
            )
            
            messages.success(request, f'Clase creada exitosamente: {clase}')
            return redirect('gravity:admin_clases_lista')
            
        except ValueError as e:
            messages.error(request, f'Error en los datos: {str(e)}')
        except Exception as e:
            messages.error(request, f'Error al crear la clase: {str(e)}')
    
    context = {
        'tipos_clases': Clase.TIPO_CLASES,
        'dias_semana': DIAS_SEMANA_COMPLETOS,
        'direcciones': Clase.DIRECCIONES,
        'accion': 'Crear'
    }
    
    return render(request, 'gravity/admin/clase_form.html', context)

@admin_required
def admin_clase_editar(request, clase_id):
    """
    Editar una clase existente - Actualizado para incluir direccion
    """
    clase = get_object_or_404(Clase, id=clase_id)
    
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        nombre_personalizado = request.POST.get('nombre_personalizado', '').strip() or None
        direccion = request.POST.get('direccion')
        dia = request.POST.get('dia')
        horario_str = request.POST.get('horario')
        cupo_maximo = request.POST.get('cupo_maximo')
        activa = request.POST.get('activa') == 'on'
        
        try:
            horario = datetime.strptime(horario_str, '%H:%M').time()
            
            # Validaciones específicas para clases especiales
            if tipo == 'Especial':
                if not nombre_personalizado:
                    messages.error(request, 'Las clases especiales deben tener un nombre personalizado.')
                    return render(request, 'gravity/admin/clase_form.html', {
                        'clase': clase,
                        'tipos_clases': Clase.TIPO_CLASES,
                        'dias_semana': DIAS_SEMANA_COMPLETOS,
                        'direcciones': Clase.DIRECCIONES,
                        'accion': 'Editar'
                    })
            elif nombre_personalizado:
                messages.error(request, 'Solo las clases especiales pueden tener nombre personalizado.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'clase': clase,
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'accion': 'Editar'
                })
            
            # Validar día para clases no especiales
            if dia == 'Sábado' and tipo != 'Especial':
                messages.error(request, 'Solo las clases especiales pueden programarse los sábados.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'clase': clase,
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'accion': 'Editar'
                })
            
            # Construir filtro para verificar duplicados
            duplicate_filter = {
                'tipo': tipo,
                'direccion': direccion,
                'dia': dia,
                'horario': horario
            }
            
            if tipo == 'Especial':
                duplicate_filter['nombre_personalizado'] = nombre_personalizado
            else:
                duplicate_filter['nombre_personalizado__isnull'] = True
            
            # Verificar duplicados (excluyendo la clase actual)
            if Clase.objects.filter(**duplicate_filter).exclude(id=clase.id).exists():
                direccion_display = dict(Clase.DIRECCIONES).get(direccion, direccion)
                if tipo == 'Especial':
                    error_msg = f'Ya existe otra clase especial "{nombre_personalizado}" los {dia} a las {horario_str} en {direccion_display}.'
                else:
                    tipo_display = dict(Clase.TIPO_CLASES).get(tipo, tipo)
                    error_msg = f'Ya existe otra clase de {tipo_display} los {dia} a las {horario_str} en {direccion_display}.'
                
                messages.error(request, error_msg)
                return render(request, 'gravity/admin/clase_form.html', {
                    'clase': clase,
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA_COMPLETOS,
                    'direcciones': Clase.DIRECCIONES,
                    'accion': 'Editar'
                })
            
            # Actualizar la clase
            clase.tipo = tipo
            clase.nombre_personalizado = nombre_personalizado
            clase.direccion = direccion
            clase.dia = dia
            clase.horario = horario
            clase.cupo_maximo = int(cupo_maximo)
            clase.activa = activa
            clase.save()
            
            messages.success(request, f'Clase actualizada exitosamente: {clase}')
            return redirect('gravity:admin_clases_lista')
            
        except ValueError as e:
            messages.error(request, f'Error en los datos: {str(e)}')
        except Exception as e:
            messages.error(request, f'Error al actualizar la clase: {str(e)}')
    
    context = {
        'clase': clase,
        'tipos_clases': Clase.TIPO_CLASES,
        'dias_semana': DIAS_SEMANA_COMPLETOS,
        'direcciones': Clase.DIRECCIONES,
        'accion': 'Editar'
    }
    
    return render(request, 'gravity/admin/clase_form.html', context)

@admin_required
def admin_clase_eliminar(request, clase_id):
    """
    Eliminar una clase (solo si no tiene reservas activas)
    """
    clase = get_object_or_404(Clase, id=clase_id)
    
    if request.method == 'POST':
        if clase.puede_eliminarse():
            nombre_display = clase.get_nombre_display()
            dia = clase.dia
            horario = clase.horario.strftime('%H:%M')
            sede = clase.get_direccion_corta()
            
            clase.delete()
            messages.success(
                request, 
                f'Clase eliminada exitosamente: {nombre_display} - {dia} {horario} - {sede}'
            )
        else:
            messages.error(
                request, 
                'No se puede eliminar esta clase porque tiene reservas activas.'
            )
        
        return redirect('gravity:admin_clases_lista')
    
    context = {
        'clase': clase,
        'reservas_activas': clase.get_reservas_activas()
    }
    
    return render(request, 'gravity/admin/clase_eliminar.html', context)

@admin_required
def admin_clase_detalle(request, clase_id):
    """
    Ver detalle completo de una clase con todas sus reservas
    """
    clase = get_object_or_404(Clase, id=clase_id)

    # Calcular próxima fecha de esta clase
    hoy = timezone.localtime(timezone.now())
    dias_semana = {'Lunes': 0, 'Martes': 1, 'Miércoles': 2, 'Jueves': 3, 'Viernes': 4, 'Sábado': 5}
    dia_num = dias_semana.get(clase.dia, 0)
    dias_hasta = (dia_num - hoy.weekday()) % 7
    if dias_hasta == 0:
        proxima_hoy = hoy.replace(hour=clase.horario.hour, minute=clase.horario.minute, second=0, microsecond=0)
        if proxima_hoy <= hoy:
            dias_hasta = 7
    proxima_fecha_clase = (hoy + timedelta(days=dias_hasta)).date()

    # Reservas permanentes (asisten todas las semanas)
    reservas_permanentes = clase.reserva_set.filter(
        activa=True,
        fecha_unica__isnull=True,
    ).select_related('usuario', 'usuario__profile')

    # Reservas de fecha única SOLO para la próxima clase
    reservas_fecha_unica = clase.reserva_set.filter(
        activa=True,
        fecha_unica=proxima_fecha_clase,
    ).select_related('usuario', 'usuario__profile')

    # IDs de ausencias para la próxima clase
    reservas_con_ausencia = set(
        AusenciaTemporal.objects.filter(
            reserva__clase=clase,
            reserva__activa=True,
            fecha=proxima_fecha_clase
        ).values_list('reserva_id', flat=True)
    )

    # Badge "Recupera clase": fue a su propia clase y recupera aquí
    ids_recupero = set(
        reservas_fecha_unica.filter(es_recupero=True).values_list('id', flat=True)
    )

    # Badge "Clase única": eligió venir solo esta vez (cupo temporal)
    ids_cupo_temporal = set(
        reservas_fecha_unica.filter(es_recupero=False).values_list('id', flat=True)
    )

    # Lista unificada ordenada por nombre
    from itertools import chain
    reservas = sorted(
        chain(reservas_permanentes, reservas_fecha_unica),
        key=lambda r: (r.usuario.first_name or '', r.usuario.last_name or '')
    )

    total_reservas = reservas_permanentes.count() + reservas_fecha_unica.count()

    # Estadísticas reales para la próxima clase (descuenta ausencias, suma fecha única)
    cupos_disponibles_proxima = clase.cupos_disponibles(fecha=proxima_fecha_clase)
    asistentes_proxima = clase.cupo_maximo - cupos_disponibles_proxima
    porcentaje_proxima = round((asistentes_proxima / clase.cupo_maximo) * 100) if clase.cupo_maximo > 0 else 0

    context = {
        'clase': clase,
        'reservas': reservas,
        'total_reservas': total_reservas,
        'cupos_disponibles': clase.cupos_disponibles(),
        'porcentaje_ocupacion': clase.get_porcentaje_ocupacion(),
        'proxima_fecha_clase': proxima_fecha_clase,
        'reservas_con_ausencia': reservas_con_ausencia,
        'ids_recupero': ids_recupero,
        'ids_cupo_temporal': ids_cupo_temporal,
        'cupos_disponibles_proxima': cupos_disponibles_proxima,
        'asistentes_proxima': asistentes_proxima,
        'porcentaje_proxima': porcentaje_proxima,
    }

    return render(request, 'gravity/admin/clase_detalle.html', context)

@admin_required
def admin_clase_toggle_status(request, clase_id):
    """
    Activa o desactiva una clase (AJAX)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    clase = get_object_or_404(Clase, id=clase_id)
    
    try:
        import json
        data = json.loads(request.body)
        activate = data.get('activate', False)
        
        # Cambiar el estado de la clase
        clase.activa = activate
        clase.save()
        
        action = 'activada' if activate else 'desactivada'
        
        return JsonResponse({
            'success': True,
            'message': f'Clase {clase.get_nombre_display()} - {clase.dia} {clase.horario.strftime("%H:%M")} {action} exitosamente.',
            'new_status': clase.activa
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ==============================================================================
# GESTIÓN DE RESERVAS
# ==============================================================================

@admin_required
def admin_reservas_lista(request):
    """
    Lista todas las reservas con filtros y paginación
    Ahora incluye filtro por sede
    """
    reservas = Reserva.objects.select_related(
        'usuario', 'clase', 'usuario__profile'
    ).order_by('-fecha_reserva')
    
    # Filtros
    estado_filtro = request.GET.get('estado', '')
    tipo_clase_filtro = request.GET.get('tipo_clase', '')
    sede_filtro = request.GET.get('sede', '')
    dia_filtro = request.GET.get('dia', '')
    usuario_filtro = request.GET.get('usuario', '')
    
    if estado_filtro == 'activas':
        reservas = reservas.filter(activa=True)
    elif estado_filtro == 'canceladas':
        reservas = reservas.filter(activa=False)
    
    if tipo_clase_filtro:
        reservas = reservas.filter(clase__tipo=tipo_clase_filtro)
    
    if sede_filtro:
        reservas = reservas.filter(clase__direccion=sede_filtro)
    
    if dia_filtro:
        reservas = reservas.filter(clase__dia=dia_filtro)
    
    if usuario_filtro:
        reservas = reservas.filter(
            Q(usuario__username__icontains=usuario_filtro) |
            Q(usuario__first_name__icontains=usuario_filtro) |
            Q(usuario__last_name__icontains=usuario_filtro)
        )
    
    # Paginación
    paginator = Paginator(reservas, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'estado_filtro': estado_filtro,
        'tipo_clase_filtro': tipo_clase_filtro,
        'sede_filtro': sede_filtro,
        'dia_filtro': dia_filtro,
        'usuario_filtro': usuario_filtro,
        'tipos_clases': Clase.TIPO_CLASES,
        'sedes': Clase.DIRECCIONES,
        'dias_semana': DIAS_SEMANA,
    }
    
    return render(request, 'gravity/admin/reservas_lista.html', context)

@admin_required
def admin_reserva_cancelar(request, reserva_id):
    """
    Cancelar una reserva como administrador (sin restricciones de tiempo)
    Ahora con sistema de emails automático
    """
    reserva = get_object_or_404(Reserva, id=reserva_id, activa=True)
    
    if request.method == 'POST':
        # Obtener datos del formulario
        motivo = request.POST.get('motivo', '').strip()
        motivo_detalle = request.POST.get('motivo_detalle', '').strip()
        notificar_usuario = request.POST.get('notificar_usuario') == 'on'
        ofrecer_reemplazo = request.POST.get('ofrecer_reemplazo') == 'on'
        ofrecer_otras_sedes = request.POST.get('ofrecer_otras_sedes') == 'on'
        registrar_incidencia = request.POST.get('registrar_incidencia') == 'on'
        
        # Validar que se haya seleccionado un motivo
        if not motivo:
            messages.error(request, 'Debes seleccionar un motivo para la cancelación.')
            return render(request, 'gravity/admin/reserva_cancelar.html', {'reserva': reserva})
        
        try:
            with transaction.atomic():
                # Guardar información adicional en las notas antes de cancelar
                notas_cancelacion = f"Cancelada por administrador - Motivo: {motivo}"
                if motivo_detalle:
                    notas_cancelacion += f" - Detalle: {motivo_detalle}"
                
                # Actualizar las notas de la reserva
                if reserva.notas:
                    reserva.notas += f"\n{notas_cancelacion}"
                else:
                    reserva.notas = notas_cancelacion
                
                # Cancelar la reserva
                reserva.activa = False
                reserva.save()
                
                # Registrar incidencia si se solicitó
                if registrar_incidencia:
                    registrar_incidencia_cancelacion(reserva, motivo, motivo_detalle, request.user)
                
                # Enviar email de notificación si se solicitó
                email_enviado = False
                if notificar_usuario and reserva.usuario.email:
                    try:
                        email_enviado = enviar_email_cancelacion_reserva(
                            reserva=reserva,
                            motivo=motivo,
                            motivo_detalle=motivo_detalle,
                            ofrecer_reemplazo=ofrecer_reemplazo,
                            ofrecer_otras_sedes=ofrecer_otras_sedes
                        )
                    except Exception as e:
                        logger.error(f"Error enviando email de cancelación: {str(e)}")
                        email_enviado = False
                
                # Mensaje de éxito
                mensaje_exito = (
                    f'Reserva {reserva.numero_reserva} de {reserva.get_nombre_completo_usuario()} '
                    f'cancelada exitosamente.'
                )
                
                if notificar_usuario:
                    if email_enviado:
                        mensaje_exito += f' Se envió notificación por email a {reserva.usuario.email}.'
                    elif reserva.usuario.email:
                        mensaje_exito += f' ⚠️ No se pudo enviar el email a {reserva.usuario.email}.'
                    else:
                        mensaje_exito += ' ⚠️ El usuario no tiene email configurado.'
                
                if registrar_incidencia:
                    mensaje_exito += ' Se registró como incidencia para seguimiento.'
                
                messages.success(request, mensaje_exito)
                
        except Exception as e:
            messages.error(
                request, 
                f'Error al cancelar la reserva: {str(e)}. '
                'La cancelación no se completó.'
            )
            return render(request, 'gravity/admin/reserva_cancelar.html', {'reserva': reserva})
        
        return redirect('gravity:admin_reservas_lista')
    
    # GET request - mostrar formulario
    context = {
        'reserva': reserva
    }
    
    return render(request, 'gravity/admin/reserva_cancelar.html', context)

@admin_required
def admin_reserva_modificar(request, reserva_id):
    """
    Modificar una reserva como administrador (sin restricciones de tiempo).
    """
    reserva = get_object_or_404(Reserva, id=reserva_id, activa=True)

    if request.method == 'POST':
        notificar_usuario = request.POST.get('notificar_usuario') == 'on'

        form = ModificarReservaForm(
            request.POST,
            reserva_actual=reserva,
            user=reserva.usuario
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    nueva_clase = form.cleaned_data['nueva_clase']
                    clase_anterior = reserva.clase

                    reserva.clase = nueva_clase
                    reserva.save()

                    # Enviar email de notificación si se solicitó
                    email_enviado = False
                    if notificar_usuario and reserva.usuario.email:
                        try:
                            email_enviado = enviar_email_modificacion_reserva(
                                reserva=reserva,
                                clase_anterior=clase_anterior,
                            )
                        except Exception as e:
                            logger.error(f"Error enviando email de modificación: {str(e)}")

                    mensaje_exito = (
                        f'Reserva {reserva.numero_reserva} de {reserva.get_nombre_completo_usuario()} '
                        f'modificada: {clase_anterior.get_nombre_display()} ({clase_anterior.dia} '
                        f'{clase_anterior.horario.strftime("%H:%M")}) → '
                        f'{nueva_clase.get_nombre_display()} ({nueva_clase.dia} '
                        f'{nueva_clase.horario.strftime("%H:%M")}).'
                    )

                    if notificar_usuario:
                        if email_enviado:
                            mensaje_exito += f' Notificación enviada a {reserva.usuario.email}.'
                        elif reserva.usuario.email:
                            mensaje_exito += f' ⚠️ No se pudo enviar el email a {reserva.usuario.email}.'
                        else:
                            mensaje_exito += ' ⚠️ El usuario no tiene email configurado.'

                    messages.success(request, mensaje_exito)
                    return redirect('gravity:admin_reservas_lista')

            except IntegrityError:
                messages.error(request, 'Error: el alumno ya tiene una reserva en esa clase.')
            except Exception as e:
                messages.error(request, f'Error al modificar la reserva: {str(e)}')
    else:
        form = ModificarReservaForm(
            reserva_actual=reserva,
            user=reserva.usuario
        )

    return render(request, 'gravity/admin/reserva_modificar.html', {
        'form': form,
        'reserva': reserva,
    })

def registrar_incidencia_cancelacion(reserva, motivo, motivo_detalle, admin_user):
    """
    Registra una incidencia cuando una cancelación es marcada para seguimiento.
    
    Args:
        reserva: Reserva cancelada
        motivo: Motivo de la cancelación
        motivo_detalle: Detalle adicional
        admin_user: Usuario administrador que realizó la cancelación
    """
    try:
        # Por ahora, vamos a registrar la incidencia en los logs
        # En el futuro, podrías crear un modelo IncidenciaCancelacion
        
        incidencia_info = {
            'tipo': 'cancelacion_reserva',
            'reserva_numero': reserva.numero_reserva,
            'usuario': reserva.usuario.username,
            'usuario_email': reserva.usuario.email,
            'clase_tipo': reserva.clase.tipo,
            'clase_dia': reserva.clase.dia,
            'clase_horario': reserva.clase.horario.strftime('%H:%M'),
            'clase_sede': reserva.clase.direccion,
            'motivo': motivo,
            'motivo_detalle': motivo_detalle,
            'admin_user': admin_user.username,
            'fecha_cancelacion': timezone.now(),
        }
        
        logger.info(f"INCIDENCIA_CANCELACION: {incidencia_info}")
        
        # Aquí podrías agregar lógica adicional como:
        # - Enviar email al gerente
        # - Guardar en base de datos específica
        # - Enviar notificación a Slack
        # - Crear ticket en sistema de soporte
        
        return True
        
    except Exception as e:
        logger.error(f"Error registrando incidencia de cancelación: {str(e)}")
        return False

@login_required
def reservar_recupero(request):
    """
    Permite reservar una clase de recupero por ausencia temporal registrada esta semana.
    La reserva es solo para esa fecha. No consume clases del plan.
    """
    puede, n_disponibles, ausencias = Reserva.usuario_puede_hacer_recupero(request.user)

    if not puede:
        messages.error(request, 'No tenés ausencias disponibles para recuperar esta semana.')
        return redirect('accounts:mis_reservas')

    hoy = timezone.now().date()
    # El plazo máximo es la fecha_limite_recupero más lejana entre las ausencias vigentes
    fin_ventana = max((a.fecha_limite_recupero for a in ausencias), default=hoy)

    clases_para_recupero = []
    dias_totales = (fin_ventana - hoy).days + 1
    for offset in range(dias_totales):
        fecha_dia = hoy + timedelta(days=offset)
        dia_nombre = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][fecha_dia.weekday()]
        for clase in Clase.objects.filter(activa=True, dia=dia_nombre).order_by('horario'):
            cupos = clase.cupos_disponibles(fecha=fecha_dia)
            if cupos <= 0:
                continue
            ya_tiene = Reserva.objects.filter(
                usuario=request.user,
                clase=clase,
                activa=True
            ).filter(
                fecha_unica=fecha_dia
            ).exists()
            ya_tiene_permanente = Reserva.objects.filter(
                usuario=request.user,
                clase=clase,
                activa=True,
                fecha_unica__isnull=True
            ).exists()
            if ya_tiene or ya_tiene_permanente:
                continue
            clases_para_recupero.append({
                'clase': clase,
                'fecha': fecha_dia,
                'fecha_str': fecha_dia.strftime('%Y-%m-%d'),
                'cupos': cupos,
            })

    if request.method == 'POST':
        clase_id = request.POST.get('clase_id')
        fecha_str = request.POST.get('fecha')
        try:
            from datetime import date as date_type
            fecha_recupero = date_type.fromisoformat(fecha_str)
            clase = get_object_or_404(Clase, id=clase_id, activa=True)

            if fecha_recupero < hoy or fecha_recupero > fin_ventana:
                messages.error(request, 'Fecha inválida para el recupero.')
                return redirect('gravity:reservar_recupero')

            if clase.cupos_disponibles(fecha=fecha_recupero) <= 0:
                messages.error(request, 'Ya no hay cupos disponibles para esa clase en esa fecha.')
                return redirect('gravity:reservar_recupero')

            puede, _, _ = Reserva.usuario_puede_hacer_recupero(request.user)
            if not puede:
                messages.error(request, 'Ya no tenés recuperos disponibles esta semana.')
                return redirect('accounts:mis_reservas')

            reserva = Reserva(
                usuario=request.user,
                clase=clase,
                es_recupero=True,
                fecha_unica=fecha_recupero,
                notas=f'Recupero por ausencia temporal — {fecha_recupero.strftime("%d/%m/%Y")}'
            )
            reserva.full_clean()
            reserva.save()

            request.session['reserva_exitosa'] = {
                'tipo': 'recupero',
                'clase': clase.get_nombre_display(),
                'dia': clase.dia,
                'horario': clase.horario.strftime('%H:%M'),
                'sede': clase.get_direccion_corta(),
                'fecha': fecha_recupero.strftime('%d/%m/%Y'),
            }
            return redirect('accounts:mis_reservas')

        except Exception as e:
            messages.error(request, f'Error al procesar el recupero: {str(e)}')
            return redirect('gravity:reservar_recupero')

    context = {
        'clases_para_recupero': clases_para_recupero,
        'ausencias': ausencias,
        'n_disponibles': n_disponibles,
        'hoy': hoy,
        'fin_ventana': fin_ventana,
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
    Permite tomar un cupo temporal liberado por la ausencia de otro usuario.
    La reserva es solo para esa fecha y cuenta contra el límite semanal del plan.
    """
    from datetime import date as date_type

    clase = get_object_or_404(Clase, id=clase_id, activa=True)

    try:
        fecha = date_type.fromisoformat(fecha_str)
    except ValueError:
        messages.error(request, 'Fecha inválida.')
        return redirect('gravity:clases_disponibles')

    hoy = timezone.now().date()

    if fecha < hoy:
        messages.error(request, 'El cupo temporal ya no está disponible.')
        return redirect('gravity:clases_disponibles')

    cupos = clase.cupos_disponibles(fecha=fecha)
    if cupos <= 0:
        messages.error(request, 'Ya no hay cupos disponibles para esta clase en esa fecha.')
        return redirect('gravity:clases_disponibles')

    clases_disponibles_usuario, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    if clases_disponibles_usuario == 0:
        messages.error(request, 'Necesitás un plan activo para reservar.')
        return redirect('gravity:mis_planes')

    # Detectar si el usuario tiene una ausencia disponible para usar como recupero
    puede_recupero, _, _ = Reserva.usuario_puede_hacer_recupero(request.user)

    if not puede_recupero:
        # Sin ausencia disponible: verificar límite semanal normal
        reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)
        if reservas_actuales >= clases_disponibles_usuario:
            messages.error(
                request,
                'Ya usaste todas tus clases disponibles esta semana.'
            )
            return redirect('accounts:mis_reservas')

    ya_tiene = Reserva.objects.filter(
        usuario=request.user, clase=clase, activa=True
    ).exists()
    if ya_tiene:
        messages.error(request, 'Ya tenés una reserva para esta clase.')
        return redirect('gravity:clases_disponibles')

    if request.method == 'POST':
        try:
            tipo_nota = 'Recupero' if puede_recupero else 'Cupo temporal'
            reserva = Reserva(
                usuario=request.user,
                clase=clase,
                es_recupero=puede_recupero,
                fecha_unica=fecha,
                notas=f'{tipo_nota} — {fecha.strftime("%d/%m/%Y")}'
            )
            reserva.full_clean()
            reserva.save()

            request.session['reserva_exitosa'] = {
                'tipo': 'recupero' if puede_recupero else 'temporal',
                'clase': clase.get_nombre_display(),
                'dia': clase.dia,
                'horario': clase.horario.strftime('%H:%M'),
                'sede': clase.get_direccion_corta(),
                'fecha': fecha.strftime('%d/%m/%Y'),
            }
            return redirect('accounts:mis_reservas')

        except Exception as e:
            messages.error(request, f'Error al procesar la reserva: {str(e)}')

    context = {
        'clase': clase,
        'fecha': fecha,
        'cupos': cupos,
        'es_recupero': puede_recupero,
    }
    return render(request, 'gravity/reservar_cupo_temporal.html', context)

# ==============================================================================
# RESERVA DE CLASE POR ADMINISTRADOR
# ==============================================================================

@admin_required
def admin_reservar_para_usuario(request, clase_id=None, usuario_id=None):
    """
    Permite al administrador crear una reserva para cualquier usuario.
    - Si viene con clase_id: la clase está preseleccionada (desde lista de clases)
    - Si viene con usuario_id: el usuario está preseleccionado (desde ficha de cliente)
    - Bypasea validaciones de plan/saldo del usuario
    - Respeta cupo máximo y duplicados
    """
    # Preselecciones opcionales
    clase_preseleccionada = None
    usuario_preseleccionado = None

    if clase_id:
        clase_preseleccionada = get_object_or_404(Clase, id=clase_id, activa=True)
    if usuario_id:
        usuario_preseleccionado = get_object_or_404(User, id=usuario_id, is_staff=False)

    # Datos para los selectores
    clases_disponibles = Clase.objects.filter(activa=True).order_by(
        'direccion', 'tipo', 'dia', 'horario'
    )
    todos_los_usuarios = User.objects.filter(
        is_active=True, is_staff=False
    ).order_by('last_name', 'first_name', 'username')

    if request.method == 'POST':
        clase_id_post = request.POST.get('clase')
        usuario_id_post = request.POST.get('usuario')
        notificar = request.POST.get('notificar_usuario') == 'on'
        tipo_reserva = request.POST.get('tipo_reserva', 'recurrente')

        # Validar que se seleccionaron ambos
        if not clase_id_post or not usuario_id_post:
            messages.error(request, 'Debés seleccionar un alumno y una clase.')
            return render(request, 'gravity/admin/admin_reservar_para_usuario.html', {
                'clases_disponibles': clases_disponibles,
                'todos_los_usuarios': todos_los_usuarios,
                'clase_preseleccionada': clase_preseleccionada,
                'usuario_preseleccionado': usuario_preseleccionado,
            })

        clase = get_object_or_404(Clase, id=clase_id_post, activa=True)
        usuario = get_object_or_404(User, id=usuario_id_post, is_staff=False)

        # Para recurrente: no puede haber ninguna reserva activa en esa clase
        # Para temporal/recupero: el modelo valida duplicados de fecha_unica
        if tipo_reserva == 'recurrente' and Reserva.objects.filter(usuario=usuario, clase=clase, activa=True).exists():
            messages.error(
                request,
                f'{usuario.get_full_name() or usuario.username} ya tiene una reserva activa '
                f'en {clase.get_nombre_display()} - {clase.dia} {clase.horario.strftime("%H:%M")}.'
            )
            return render(request, 'gravity/admin/admin_reservar_para_usuario.html', {
                'clases_disponibles': clases_disponibles,
                'todos_los_usuarios': todos_los_usuarios,
                'clase_preseleccionada': clase_preseleccionada,
                'usuario_preseleccionado': usuario_preseleccionado,
            })

        # Validar cupo disponible
        if clase.cupos_disponibles() <= 0:
            messages.error(
                request,
                f'La clase {clase.get_nombre_display()} - {clase.dia} {clase.horario.strftime("%H:%M")} '
                f'no tiene cupos disponibles.'
            )
            return render(request, 'gravity/admin/admin_reservar_para_usuario.html', {
                'clases_disponibles': clases_disponibles,
                'todos_los_usuarios': todos_los_usuarios,
                'clase_preseleccionada': clase_preseleccionada,
                'usuario_preseleccionado': usuario_preseleccionado,
            })

        # Reemplazar con:
        try:
            with transaction.atomic():
                # Calcular fecha_unica y es_recupero según tipo
                fecha_unica = None
                es_recupero = False
                if tipo_reserva in ('temporal', 'recupero'):
                    hoy = timezone.now().date()
                    dias_map = {
                        'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
                        'Jueves': 3, 'Viernes': 4, 'Sábado': 5
                    }
                    dia_num = dias_map.get(clase.dia, 0)
                    dias_hasta = (dia_num - hoy.weekday()) % 7
                    if dias_hasta == 0:
                        dias_hasta = 7
                    fecha_unica = hoy + timedelta(days=dias_hasta)
                    es_recupero = (tipo_reserva == 'recupero')

                reserva = Reserva.objects.create(
                    usuario=usuario,
                    clase=clase,
                    fecha_unica=fecha_unica,
                    es_recupero=es_recupero,
                )

                # Email opcional
                email_enviado = False
                if notificar and usuario.email:
                    try:
                        email_enviado = enviar_email_confirmacion_reserva_detallado(reserva)
                    except Exception as e:
                        logger.error(f"Error enviando email de confirmación (admin): {str(e)}")

                tipo_label = {
                    'recurrente': 'recurrente',
                    'temporal': 'una sola vez',
                    'recupero': 'recupero',
                }.get(tipo_reserva, 'recurrente')

                mensaje = (
                    f'✅ Reserva {reserva.numero_reserva} ({tipo_label}) creada para '
                    f'{usuario.get_full_name() or usuario.username} en '
                    f'{clase.get_nombre_display()} - {clase.dia} '
                    f'{clase.horario.strftime("%H:%M")} ({clase.get_direccion_corta()}).'
                )
                if notificar:
                    if email_enviado:
                        mensaje += f' Email de confirmación enviado a {usuario.email}.'
                    elif usuario.email:
                        mensaje += f' ⚠️ No se pudo enviar el email a {usuario.email}.'
                    else:
                        mensaje += ' ⚠️ El alumno no tiene email configurado.'

                messages.success(request, mensaje)

                # Redirigir según el origen
                if usuario_id:
                    return redirect('gravity:admin_usuario_detalle', usuario_id=usuario.id)
                return redirect('gravity:admin_clases_lista')

        except IntegrityError:
            messages.error(request, 'Error: ya existe una reserva para ese alumno en esa clase.')
        except Exception as e:
            messages.error(request, f'Error al crear la reserva: {str(e)}')

    return render(request, 'gravity/admin/admin_reservar_para_usuario.html', {
        'clases_disponibles': clases_disponibles,
        'todos_los_usuarios': todos_los_usuarios,
        'clase_preseleccionada': clase_preseleccionada,
        'usuario_preseleccionado': usuario_preseleccionado,
    })

# ==============================================================================
# GESTIÓN DE USUARIOS
# ==============================================================================

@admin_required
def admin_usuarios_lista(request):
    """
    Lista todos los usuarios registrados con sus perfiles
    """
    usuarios = User.objects.filter(is_staff=False).select_related(
        'profile'
    ).order_by('-date_joined')
    
    # Filtros
    busqueda = request.GET.get('busqueda', '')
    filtro = request.GET.get('filtro', '')
    
    if busqueda:
        usuarios = usuarios.filter(
            Q(username__icontains=busqueda) |
            Q(first_name__icontains=busqueda) |
            Q(last_name__icontains=busqueda) |
            Q(email__icontains=busqueda)
        )
    
    # Aplicar filtros específicos
    if filtro == 'con_reservas':
        usuarios = usuarios.filter(reservas_pilates__activa=True).distinct()
    elif filtro == 'nuevos':
        hace_7_dias = timezone.now() - timedelta(days=7)
        usuarios = usuarios.filter(date_joined__gte=hace_7_dias)
    elif filtro == 'activos':
        usuarios = usuarios.filter(is_active=True)
    
    # Agregar información adicional a cada usuario
    usuarios_info = []
    for usuario in usuarios:
        try:
            profile = usuario.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=usuario)
        
        usuarios_info.append({
            'usuario': usuario,
            'profile': profile,
            'total_reservas': usuario.reservas_pilates.filter(activa=True).count(),
            'fecha_ultima_reserva': usuario.reservas_pilates.filter(
                activa=True
            ).order_by('-fecha_reserva').first()
        })
    
    # Paginación
    paginator = Paginator(usuarios_info, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'busqueda': busqueda,
        'filtro': filtro,
    }
    
    return render(request, 'gravity/admin/usuarios_lista.html', context)

@admin_required
def admin_usuario_detalle(request, usuario_id):
    """
    Ver detalle completo de un usuario con todas sus reservas
    """
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False)
    
    try:
        profile = usuario.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=usuario)
    
    # Obtener todas las reservas del usuario, ordenadas por sede
    reservas_activas = usuario.reservas_pilates.filter(activa=True).select_related(
        'clase'
    ).order_by('clase__direccion', 'clase__dia', 'clase__horario')
    
    reservas_canceladas = usuario.reservas_pilates.filter(activa=False).select_related(
        'clase'
    ).order_by('-fecha_modificacion')[:10]  # Últimas 10 canceladas
    
    context = {
        'usuario': usuario,
        'profile': profile,
        'reservas_activas': reservas_activas,
        'reservas_canceladas': reservas_canceladas,
        'total_reservas_activas': reservas_activas.count(),
        'total_reservas_historicas': usuario.reservas_pilates.count(),
    }
    
    return render(request, 'gravity/admin/usuario_detalle.html', context)

@admin_required
def admin_usuario_toggle_status(request, usuario_id):
    """
    Activa o desactiva un usuario (AJAX)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False)
    
    try:
        import json
        data = json.loads(request.body)
        activate = data.get('activate', False)
        
        # Cambiar el estado del usuario
        usuario.is_active = activate
        usuario.save()
        
        action = 'activado' if activate else 'desactivado'
        
        return JsonResponse({
            'success': True,
            'message': f'Usuario {usuario.get_full_name() or usuario.username} {action} exitosamente.',
            'new_status': usuario.is_active
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@admin_required
def admin_usuario_add_note(request, usuario_id):
    """
    Agregar una nota administrativa a un usuario (AJAX)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    usuario = get_object_or_404(User, id=usuario_id, is_staff=False)
    
    try:
        import json
        data = json.loads(request.body)
        nota = data.get('nota', '').strip()
        
        if not nota:
            return JsonResponse({'success': False, 'error': 'La nota no puede estar vacía'}, status=400)
        
        # Obtener o crear el perfil del usuario
        try:
            profile = usuario.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=usuario)
        
        # Agregar la nueva nota con timestamp y usuario admin
        fecha_actual = timezone.now().strftime('%d/%m/%Y %H:%M')
        admin_name = request.user.get_full_name() or request.user.username
        
        nueva_nota = f"[{fecha_actual} - {admin_name}]: {nota}"
        
        if profile.notas_admin:
            profile.notas_admin = f"{profile.notas_admin}\n\n{nueva_nota}"
        else:
            profile.notas_admin = nueva_nota
        
        profile.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Nota agregada exitosamente al perfil de {usuario.get_full_name() or usuario.username}.',
            'nueva_nota': nueva_nota,
            'notas_completas': profile.notas_admin
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos JSON inválidos'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ==============================================================================
# AGREGAR USUARIOS AL SISTEMA
# ==============================================================================

@admin_required
def admin_agregar_usuario(request):
    """
    Agregar un usuario directamente al sistema.
    La reserva en una clase es opcional.
    """
    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.POST.get('nombre', '').strip().title()
        apellido = request.POST.get('apellido', '').strip().title()
        email = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '').strip()
        clase_id = request.POST.get('clase_id', '').strip()
        incluir_credenciales = request.POST.get('incluir_credenciales') == 'on'

        # Validaciones básicas (clase ya no es obligatoria)
        if not nombre or not apellido or not password or not telefono:
            messages.error(request, 'Nombre, apellido, contraseña y teléfono son obligatorios.')
            return render(request, 'gravity/admin/agregar_cliente_form.html', {
                'clases_disponibles': Clase.objects.filter(activa=True).order_by(
                    'direccion', 'tipo', 'dia', 'horario'
                ),
                'form_data': request.POST
            })

        # Si se seleccionó clase, verificar que existe y tiene cupos
        clase = None
        if clase_id:
            clase = get_object_or_404(Clase, id=clase_id, activa=True)
            if clase.cupos_disponibles() <= 0:
                messages.error(request, 'La clase seleccionada no tiene cupos disponibles.')
                return render(request, 'gravity/admin/agregar_cliente_form.html', {
                    'clases_disponibles': Clase.objects.filter(activa=True).order_by(
                        'direccion', 'tipo', 'dia', 'horario'
                    ),
                    'form_data': request.POST
                })

        try:
            # Generar username único
            base_username = f"{nombre.lower()}{apellido.lower()}"
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            with transaction.atomic():
                # Crear usuario
                user = User.objects.create_user(
                    username=username,
                    email=email if email else '',
                    first_name=nombre,
                    last_name=apellido,
                    password=password,
                )

                # Obtener o actualizar el perfil
                profile, created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'telefono': telefono,
                        'sede_preferida': 'cualquiera'
                    }
                )
                if not created:
                    profile.telefono = telefono
                    profile.sede_preferida = 'cualquiera'
                    profile.save()

                # Enviar email de bienvenida (siempre, si tiene email)
                if email:
                    try:
                        enviar_email_bienvenida(
                            usuario=user,
                            is_admin_created=incluir_credenciales,
                            password_temporal=password if incluir_credenciales else None,
                        )
                        logger.info(f"Email de bienvenida enviado a {user.email}")
                    except Exception as e:
                        logger.error(f"Error enviando email de bienvenida: {str(e)}")

                # Si se seleccionó clase, crear la reserva
                if clase:
                    reserva = Reserva.objects.create(
                        usuario=user,
                        clase=clase
                    )

                    # Enviar email de confirmación de reserva si se marcó la opción
                    if request.POST.get('enviar_confirmacion') and email:
                        try:
                            enviar_email_confirmacion_reserva_detallado(reserva)
                            logger.info(f"Email de confirmación de reserva enviado para {reserva.numero_reserva}")
                        except Exception as e:
                            logger.error(f"Error enviando email de confirmación de reserva: {str(e)}")

                    messages.success(
                        request,
                        f'Usuario {nombre} {apellido} creado y reservado en '
                        f'{clase.get_nombre_display()} del {clase.dia} a las {clase.horario.strftime("%H:%M")} '
                        f'en {clase.get_direccion_corta()}. '
                        f'Credenciales: usuario={username}, contraseña={password}. '
                        f'Reserva: {reserva.numero_reserva}'
                    )
                else:
                    messages.success(
                        request,
                        f'Usuario {nombre} {apellido} creado exitosamente. '
                        f'Credenciales: usuario={username}, contraseña={password}.'
                    )

                return redirect('gravity:admin_usuarios_lista')

        except IntegrityError as e:
            messages.error(request, f'Error de integridad en la base de datos: {str(e)}')
        except Exception as e:
            messages.error(request, f'Error al crear usuario: {str(e)}')

    # Obtener clases disponibles con cupos, organizadas por sede
    clases_disponibles = []
    for clase in Clase.objects.filter(activa=True).order_by('direccion', 'tipo', 'dia', 'horario'):
        cupos = clase.cupos_disponibles()
        if cupos > 0:
            clases_disponibles.append({
                'clase': clase,
                'cupos_disponibles': cupos
            })

    context = {
        'clases_disponibles': clases_disponibles
    }

    return render(request, 'gravity/admin/agregar_cliente_form.html', context)

# ==============================================================================
# REPORTES Y ESTADÍSTICAS
# ==============================================================================

@admin_required
def admin_reportes(request):
    """
    Página de reportes y estadísticas avanzadas
    Ahora incluye estadísticas por sede
    """
    # Estadísticas por período
    hoy = timezone.now().date()
    hace_una_semana = hoy - timedelta(days=7)
    hace_un_mes = hoy - timedelta(days=30)
    
    # Reservas por período
    reservas_esta_semana = Reserva.objects.filter(
        fecha_reserva__date__gte=hace_una_semana,
        activa=True
    ).count()
    
    reservas_este_mes = Reserva.objects.filter(
        fecha_reserva__date__gte=hace_un_mes,
        activa=True
    ).count()
    
    # Usuarios nuevos por período
    usuarios_esta_semana = User.objects.filter(
        date_joined__date__gte=hace_una_semana,
        is_staff=False
    ).count()
    
    usuarios_este_mes = User.objects.filter(
        date_joined__date__gte=hace_un_mes,
        is_staff=False
    ).count()
    
    # Estadísticas por tipo de clase
    stats_por_tipo = []
    for tipo, nombre in Clase.TIPO_CLASES:
        clases_tipo = Clase.objects.filter(tipo=tipo, activa=True)
        total_clases = clases_tipo.count()
        total_reservas = Reserva.objects.filter(
            clase__tipo=tipo,
            activa=True
        ).count()
        total_cupos = sum(clase.cupo_maximo for clase in clases_tipo)
        
        stats_por_tipo.append({
            'tipo': tipo,
            'nombre': nombre,
            'total_clases': total_clases,
            'total_reservas': total_reservas,
            'total_cupos': total_cupos,
            'porcentaje_ocupacion': round((total_reservas / total_cupos * 100), 2) if total_cupos > 0 else 0
        })
    
    # Estadísticas por sede
    stats_por_sede = []
    for sede_key, sede_nombre in Clase.DIRECCIONES:
        clases_sede = Clase.objects.filter(direccion=sede_key, activa=True)
        total_clases = clases_sede.count()
        total_reservas = Reserva.objects.filter(
            clase__direccion=sede_key,
            activa=True
        ).count()
        total_cupos = sum(clase.cupo_maximo for clase in clases_sede)
        
        stats_por_sede.append({
            'sede': sede_nombre,
            'total_clases': total_clases,
            'total_reservas': total_reservas,
            'total_cupos': total_cupos,
            'porcentaje_ocupacion': round((total_reservas / total_cupos * 100), 2) if total_cupos > 0 else 0
        })
    
    # Estadísticas por día de la semana
    stats_por_dia = []
    for dia, nombre in DIAS_SEMANA_COMPLETOS:
        clases_dia = Clase.objects.filter(dia=dia, activa=True)
        total_clases = clases_dia.count()
        total_reservas = Reserva.objects.filter(
            clase__dia=dia,
            activa=True
        ).count()
        
        stats_por_dia.append({
            'dia': dia,
            'total_clases': total_clases,
            'total_reservas': total_reservas,
            'promedio_reservas_por_clase': round(total_reservas / total_clases, 2) if total_clases > 0 else 0
        })
    
    context = {
        'reservas_esta_semana': reservas_esta_semana,
        'reservas_este_mes': reservas_este_mes,
        'usuarios_esta_semana': usuarios_esta_semana,
        'usuarios_este_mes': usuarios_este_mes,
        'stats_por_tipo': stats_por_tipo,
        'stats_por_sede': stats_por_sede,
        'stats_por_dia': stats_por_dia,
    }
    
    return render(request, 'gravity/admin/reportes.html', context)

# ==============================================================================
# VISTAS DEL SISTEMA DE PAGOS
# ==============================================================================

@admin_required
def admin_pagos_vista_principal(request):
    """
    VISTA ÚNICA CENTRALIZADA para todo el sistema de pagos.
    Contiene: configuración de costos, lista de clientes, resumen general, filtros.
    """
    # ===== FILTROS =====
    filtro_estado = request.GET.get('estado', '')
    filtro_mes = request.GET.get('mes', '')
    buscar_nombre = request.GET.get('buscar', '')
    
    # ===== OBTENER TODOS LOS CLIENTES CON ESTADO DE PAGO =====
    # Crear estados para usuarios que no los tengan
    usuarios_sin_estado = User.objects.filter(
        is_staff=False,
        estado_pago__isnull=True
    )
    for usuario in usuarios_sin_estado:
        EstadoPagoCliente.objects.get_or_create(
            usuario=usuario,
            defaults={'activo': True}
        )
    
    # Obtener todos los estados de pago
    clientes_pagos = EstadoPagoCliente.objects.select_related(
        'usuario', 'plan_actual'
    ).prefetch_related('usuario__pagos_realizados')
    
    # ===== ACTUALIZAR SALDOS Y OBTENER ÚLTIMO PAGO =====
    clientes_procesados = []
    
    for cliente_estado in clientes_pagos:
        # Obtener último pago para mostrar en la tabla
        ultimo_pago = RegistroPago.objects.filter(
            cliente=cliente_estado.usuario,
            estado='confirmado'
        ).order_by('-fecha_pago').first()
        
        cliente_estado.ultimo_pago_obj = ultimo_pago
        clientes_procesados.append(cliente_estado)
    
    # ===== APLICAR FILTROS =====
    if filtro_estado == 'al_dia':
        clientes_procesados = [c for c in clientes_procesados if c.saldo_actual >= 0 and c.plan_actual]
    elif filtro_estado == 'debe':
        clientes_procesados = [c for c in clientes_procesados if c.saldo_actual < 0]
    elif filtro_estado == 'sin_plan':
        clientes_procesados = [c for c in clientes_procesados if not c.plan_actual]
    
    # Filtro por búsqueda de nombre
    if buscar_nombre:
        clientes_procesados = [c for c in clientes_procesados if (
            buscar_nombre.lower() in (c.usuario.first_name or '').lower() or
            buscar_nombre.lower() in (c.usuario.last_name or '').lower() or
            buscar_nombre.lower() in c.usuario.username.lower()
        )]
    
    # Ordenar por estado (deudores primero, luego por apellido)
    clientes_procesados.sort(key=lambda x: (x.saldo_actual, x.usuario.last_name or x.usuario.username))
    
    # ===== RESUMEN GENERAL =====
    mes_actual = timezone.now().date().replace(day=1)
    
    total_clientes = len(clientes_procesados)
    clientes_al_dia = len([c for c in clientes_procesados if c.saldo_actual >= 0 and c.plan_actual])
    clientes_con_deuda = len([c for c in clientes_procesados if c.saldo_actual < 0])
    clientes_sin_plan = len([c for c in clientes_procesados if not c.plan_actual])
    
    ingresos_mes = RegistroPago.objects.filter(
        fecha_pago__gte=mes_actual,
        estado='confirmado'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
    
    total_deuda = sum([abs(c.saldo_actual) for c in clientes_procesados if c.saldo_actual < 0])
    
    # ===== PLANES DE PAGO =====
    planes_activos = PlanPago.objects.filter(activo=True).order_by('clases_por_semana')
    
    # ===== CREAR PAGINADOR MANUAL =====
    from django.core.paginator import Paginator
    
    # Crear paginador con la lista procesada
    paginator = Paginator(clientes_procesados, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    puede_ver = get_puede_ver_pagos(request.user)

    context = {
        'page_obj': page_obj,
        'planes_activos': planes_activos,
        'filtro_estado': filtro_estado,
        'filtro_mes': filtro_mes,
        'buscar_nombre': buscar_nombre,
        'total_clientes': total_clientes,
        'clientes_al_dia': clientes_al_dia,
        'clientes_con_deuda': clientes_con_deuda,
        'clientes_sin_plan': clientes_sin_plan,
        'ingresos_mes': ingresos_mes if puede_ver else None,
        'total_deuda': total_deuda if puede_ver else None,
        'mes_actual': mes_actual,
        'puede_ver_pagos': puede_ver,
    }
    
    return render(request, 'gravity/admin/pagos_principal.html', context)

@admin_required
def admin_pagos_registrar_pago(request, cliente_id):
    """
    Modal/página simple para registrar un pago de un cliente específico.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)
    estado_pago, created = EstadoPagoCliente.objects.get_or_create(
        usuario=cliente,
        defaults={'activo': True}
    )
    
    if request.method == 'POST':
        form = RegistroPagoForm(request.POST)
        
        if form.is_valid():
            pago = form.save(commit=False)
            pago.cliente = cliente
            pago.registrado_por = request.user
            pago.save()

            # 📧 ENVIAR EMAIL DE CONFIRMACIÓN DE PAGO
            try:
                email_enviado = enviar_email_confirmacion_pago_completo(pago)
                if email_enviado:
                    logger.info(f"Email de pago enviado para pago ID {pago.id}")
            except Exception as e:
                logger.error(f"Error enviando email de pago: {str(e)}")
            
            # El saldo ya fue actualizado correctamente por el método save() de RegistroPago
            # Solo actualizar los campos de último pago
            estado_pago.ultimo_pago = pago.fecha_pago
            estado_pago.monto_ultimo_pago = pago.monto
            estado_pago.save(update_fields=['ultimo_pago', 'monto_ultimo_pago'])
            
            messages.success(
                request,
                f'Pago de ${pago.monto} registrado exitosamente para {cliente.get_full_name() or cliente.username}'
            )
            return redirect('gravity:admin_pagos_vista_principal')
    else:
        # Prellenar con datos sugeridos
        form = RegistroPagoForm(initial={
            'fecha_pago': timezone.now().date(),
            'concepto': f'Pago mensual {timezone.now().strftime("%B %Y")}',
            'monto': estado_pago.plan_actual.precio_mensual if estado_pago.plan_actual else None
        })

    # Calcular precio sugerido en efectivo para mostrarlo en el formulario
    precio_efectivo_sugerido = None
    if estado_pago.plan_actual:
        precio_efectivo_sugerido = estado_pago.plan_actual.calcular_precio_efectivo()

    context = {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
        'precio_efectivo_sugerido': precio_efectivo_sugerido,
        'precio_completo': estado_pago.plan_actual.precio_mensual if estado_pago.plan_actual else None,
    }
    
    return render(request, 'gravity/admin/pagos_registrar.html', context)

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
    ).order_by('-fecha_pago', '-fecha_registro')
    
    # Estadísticas del cliente
    total_pagado = pagos.filter(estado='confirmado').aggregate(
        total=Sum('monto')
    )['total'] or Decimal('0')
    
    total_pagos = pagos.filter(estado='confirmado').count()
    
    puede_ver = get_puede_ver_pagos(request.user)
    context = {
        'cliente': cliente,
        'estado_pago': estado_pago,
        'pagos': pagos if puede_ver else [],
        'total_pagado': total_pagado if puede_ver else None,
        'total_pagos': total_pagos if puede_ver else None,
        'puede_ver_pagos': puede_ver,
    }
    
    return render(request, 'gravity/admin/pagos_historial.html', context)

@admin_required
def admin_pagos_configurar_planes(request):
    """
    Página simple para configurar planes de pago (costos).
    """
    planes = PlanPago.objects.all().order_by('clases_por_semana')
    
    # Inicializar el formulario SIEMPRE
    form = PlanPagoForm()

    if request.method == 'POST':
        if 'crear_plan' in request.POST:
            form = PlanPagoForm(request.POST)
            if form.is_valid():
                plan = form.save()
                messages.success(request, f'Plan "{plan.nombre}" creado exitosamente.')
                return redirect('gravity:admin_pagos_configurar_planes')
        elif 'editar_plan' in request.POST:
            plan_id = request.POST.get('editar_plan')
            plan = get_object_or_404(PlanPago, id=plan_id)
            form = PlanPagoForm(request.POST, instance=plan)
            if form.is_valid():
                form.save()
                messages.success(request, f'Plan "{plan.nombre}" actualizado exitosamente.')
                return redirect('gravity:admin_pagos_configurar_planes')
        elif 'eliminar_plan' in request.POST:
            plan_id = request.POST.get('eliminar_plan')
            plan = get_object_or_404(PlanPago, id=plan_id)
            
            # Verificar que no tenga clientes asignados
            if plan.estadopagocliente_set.count() > 0:
                messages.error(request, f'No se puede eliminar el plan "{plan.nombre}" porque tiene clientes asignados.')
            else:
                plan_nombre = plan.nombre
                plan.delete()
                messages.success(request, f'Plan "{plan_nombre}" eliminado exitosamente.')
            
            return redirect('gravity:admin_pagos_configurar_planes')
        elif 'toggle_activo_plan' in request.POST:
            plan_id = request.POST.get('toggle_activo_plan')
            plan = get_object_or_404(PlanPago, id=plan_id)
            plan.activo = not plan.activo
            plan.save()
            estado = "activado" if plan.activo else "desactivado"
            
            messages.success(request, f'Plan "{plan.nombre}" {estado} exitosamente.')
            
            return redirect('gravity:admin_pagos_configurar_planes')
    
    context = {
        'planes': planes,
        'form': form,
    }
    
    return render(request, 'gravity/admin/pagos_configurar_planes.html', context)

@admin_required
def admin_pagos_editar_estado_cliente(request, cliente_id):
    """
    Modal/página simple para editar manualmente el estado de pago de un cliente.
    """
    cliente = get_object_or_404(User, id=cliente_id, is_staff=False)

    if not get_puede_ver_pagos(request.user):
        messages.error(request, 'No tenés permisos para editar información de pagos.')
        return redirect('gravity:admin_pagos_vista_principal')

    estado_pago, created = EstadoPagoCliente.objects.get_or_create(
        usuario=cliente,
        defaults={'activo': True}
    )
    
    if request.method == 'POST':
        form = EstadoPagoClienteForm(request.POST, instance=estado_pago)
        if form.is_valid():
            plan_anterior = estado_pago.plan_actual
            estado_actualizado = form.save()

            # Si se asignó un plan nuevo
            tiene_plan_usuario_activo = PlanUsuario.objects.filter(
                usuario=cliente,
                activo=True,
            ).exists()

            if estado_actualizado.plan_actual and (
                estado_actualizado.plan_actual != plan_anterior or not tiene_plan_usuario_activo
            ):
                
                # Crear PlanUsuario para que el cliente pueda reservar
                hoy = timezone.now().date()
                fecha_fin = date(2099, 12, 31)

                # Desactivar planes anteriores activos
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

                # Generar deuda del mes si no existe
                estado_actualizado.generar_deuda_mes_actual()

                # Recalcular saldo desde cero para evitar que el valor del
                # formulario + la deuda generada se dupliquen
                total_pagado = RegistroPago.objects.filter(
                    cliente=cliente, estado='confirmado'
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
                total_deudas = DeudaMensual.objects.filter(
                    usuario=cliente
                ).aggregate(total=Sum('monto_original'))['total'] or Decimal('0')
                estado_actualizado.saldo_actual = total_pagado - total_deudas
                estado_actualizado.save(update_fields=['saldo_actual'])

            messages.success(
                request,
                f'Estado de pago actualizado para {cliente.get_full_name() or cliente.username}'
            )
            return redirect('gravity:admin_pagos_vista_principal')
    else:
        form = EstadoPagoClienteForm(instance=estado_pago)
    
    planes_precios = {
        str(p.id): str(p.precio_mensual)
        for p in PlanPago.objects.filter(activo=True)
    }

    context = {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
        'planes_precios': planes_precios,
    }
    
    return render(request, 'gravity/admin/pagos_editar_estado.html', context)

# ==============================================================================
# GESTIÓN DE ADMINISTRADORES CON PERMISOS RESTRINGIDOS (solo superadmins)
# ==============================================================================

@superadmin_required
def admin_gestionar_admins(request):
    """
    Lista y gestión de usuarios administradores sin acceso a pagos.
    Solo accesible por superusuarios.
    """
    admins_restringidos = User.objects.filter(
        is_staff=True,
        is_superuser=False,
        is_active=True
    ).select_related('profile').order_by('first_name', 'last_name')

    context = {
        'admins_restringidos': admins_restringidos,
    }
    return render(request, 'gravity/admin/gestionar_admins.html', context)

@superadmin_required
def admin_crear_admin_restringido(request):
    """
    Crear un nuevo usuario administrador sin acceso a información de pagos.
    Solo accesible por superusuarios.
    """
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip().title()
        apellido = request.POST.get('apellido', '').strip().title()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        if not nombre or not apellido or not password:
            messages.error(request, 'Nombre, apellido y contraseña son obligatorios.')
            return redirect('gravity:admin_gestionar_admins')

        base_username = f"{nombre.lower()}{apellido.lower()}"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        try:
            with transaction.atomic():
                nuevo_admin = User.objects.create_user(
                    username=username,
                    email=email if email else '',
                    first_name=nombre,
                    last_name=apellido,
                    password=password,
                    is_staff=True,
                    is_superuser=False,
                )
                profile, _ = UserProfile.objects.get_or_create(user=nuevo_admin)
                profile.puede_ver_pagos = False
                profile.save()

                messages.success(
                    request,
                    f'Administrador {nombre} {apellido} creado exitosamente. '
                    f'Usuario: {username}. No podrá ver información de pagos.'
                )
        except Exception as e:
            messages.error(request, f'Error al crear administrador: {str(e)}')

        return redirect('gravity:admin_gestionar_admins')

    return redirect('gravity:admin_gestionar_admins')

@superadmin_required
def admin_eliminar_admin_restringido(request, admin_id):
    """
    Eliminar (desactivar) un administrador restringido.
    Solo accesible por superusuarios.
    """
    if request.method != 'POST':
        return redirect('gravity:admin_gestionar_admins')

    admin_a_eliminar = get_object_or_404(
        User,
        id=admin_id,
        is_staff=True,
        is_superuser=False
    )

    nombre_completo = admin_a_eliminar.get_full_name() or admin_a_eliminar.username
    admin_a_eliminar.is_active = False
    admin_a_eliminar.is_staff = False
    admin_a_eliminar.save()

    messages.success(request, f'Administrador {nombre_completo} eliminado del sistema.')
    return redirect('gravity:admin_gestionar_admins')

# ==============================================================================
# VISTAS DE PLANES DE PAGO
# ==============================================================================

@login_required
def seleccionar_plan(request):
    """
    Vista para que el usuario seleccione su primer plan o agregue planes adicionales
    """
    # Verificar si ya tiene planes activos - CORREGIR 'activa' por 'activo'
    planes_actuales = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=True,  # Cambiar 'activa' por 'activo'
        fecha_fin__gte=timezone.now().date()
    )
    
    # Obtener planes disponibles
    planes_disponibles = PlanPago.objects.filter(activo=True).order_by('clases_por_semana')
    
    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')
        tipo_plan = request.POST.get('tipo_plan', 'permanente')
        
        try:
            plan_seleccionado = PlanPago.objects.get(id=plan_id, activo=True)
            
            # Calcular fechas (inicio hoy, fin en un mes)
            fecha_inicio = timezone.now().date()
            fecha_fin = date(2099, 12, 31)
            
            # Crear el plan del usuario
            plan_usuario = PlanUsuario.objects.create(
                usuario=request.user,
                plan=plan_seleccionado,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                tipo_plan=tipo_plan,
                renovacion_automatica=True if tipo_plan == 'permanente' else False
            )
            
            if planes_actuales.exists():
                messages.success(
                    request,
                    f'¡Plan adicional agregado exitosamente! '
                    f'Ahora tienes "{plan_seleccionado.nombre}" válido hasta que decidas cancelarlo.'
                )
            else:
                messages.success(
                    request,
                    f'¡Plan seleccionado exitosamente! '
                    f'Tienes "{plan_seleccionado.nombre}" válido hasta que decidas cancelarlo. '
                    f'Ya puedes empezar a reservar tus clases.'
                )
            
            # Redirigir según el contexto
            next_url = request.GET.get('next')
            if next_url == 'reservar':
                return redirect('gravity:reservar_clase')
            else:
                return redirect('gravity:mis_planes')
                
        except PlanPago.DoesNotExist:
            messages.error(request, 'Plan inválido. Por favor selecciona un plan válido.')
        except Exception as e:
            messages.error(request, f'Error al asignar el plan: {str(e)}')
    
    # Calcular clases disponibles actualmente
    clases_disponibles, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)
    
    context = {
        'planes_disponibles': planes_disponibles,
        'planes_actuales': planes_actuales,
        'tiene_planes': planes_actuales.exists(),
        'clases_disponibles': clases_disponibles,
        'reservas_actuales': reservas_actuales,
        'es_primer_plan': not planes_actuales.exists()
    }
    
    return render(request, 'gravity/seleccionar_plan.html', context)

@login_required
def mis_planes(request):
    """
    Vista para mostrar los planes actuales del usuario y su estado
    """
    # Obtener planes activos - CORREGIR 'activa' por 'activo'
    planes_activos = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=True,
    ).select_related('plan').order_by('-fecha_creacion')

    # Planes cancelados explícitamente (historial)
    planes_vencidos = PlanUsuario.objects.filter(
        usuario=request.user,
        activo=False,
    ).select_related('plan').order_by('-fecha_creacion')[:5]
    
    # Calcular estadísticas de la semana actual
    clases_disponibles, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)
    
    # Obtener reservas activas
    reservas_activas = request.user.reservas_pilates.filter(activa=True).select_related('clase')
    
    context = {
        'planes_activos': planes_activos,
        'planes_vencidos': planes_vencidos,
        'clases_disponibles': clases_disponibles,
        'reservas_actuales': reservas_actuales,
        'clases_restantes': max(0, clases_disponibles - reservas_actuales),
        'reservas_activas': reservas_activas,
        'tiene_planes_activos': planes_activos.exists()
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
            hoy = timezone.now().date()
            dia_actual = hoy.day
            primer_dia_mes = date(hoy.year, hoy.month, 1)
            clases_a_cancelar = plan.plan.clases_por_semana

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
                        deuda_actual.monto_pendiente = Decimal('0')
                        deuda_actual.estado = 'pagado'
                        deuda_actual.observaciones += (
                            f'\nDeuda anulada por cancelación de plan '
                            f'antes del día 5 ({hoy.strftime("%d/%m/%Y")}).'
                        )
                        deuda_actual.save()
                        try:
                            estado = request.user.estado_pago
                            estado.monto_deuda_mensual = Decimal('0')
                            estado.save()
                        except Exception:
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
                            estado = request.user.estado_pago
                            estado.monto_deuda_mensual = monto_medio
                            estado.saldo_actual = -monto_medio
                            estado.save(update_fields=['monto_deuda_mensual', 'saldo_actual'])
                        except EstadoPagoCliente.DoesNotExist:
                            pass
            except DeudaMensual.DoesNotExist:
                pass

            # --- Política de reservas ---
            reservas_activas = list(
                request.user.reservas_pilates.filter(activa=True).select_related('clase')
            )

            if dia_actual <= 4:
                # Cancelar X reservas inmediatamente
                canceladas = 0
                for reserva in reservas_activas:
                    if canceladas >= clases_a_cancelar:
                        break
                    reserva.activa = False
                    reserva.save()
                    canceladas += 1
                plan.reservas_canceladas = True

            elif dia_actual <= 9:
                # Calcular la fecha de la X-ésima próxima ocurrencia
                ocurrencias = []
                for reserva in reservas_activas:
                    proxima = reserva.get_proxima_fecha()
                    if proxima:
                        for semana in range(clases_a_cancelar + 4):
                            ocurrencias.append(proxima + timedelta(weeks=semana))

                ocurrencias.sort()

                if len(ocurrencias) >= clases_a_cancelar:
                    plan.fecha_cancelacion_reservas = ocurrencias[clases_a_cancelar - 1]
                else:
                    # Si no hay suficientes ocurrencias, cancelar al fin de mes
                    import calendar
                    ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
                    plan.fecha_cancelacion_reservas = date(hoy.year, hoy.month, ultimo_dia)

            else:
                # Día 10+: cancelar el 1º del mes siguiente
                if hoy.month == 12:
                    plan.fecha_cancelacion_reservas = date(hoy.year + 1, 1, 1)
                else:
                    plan.fecha_cancelacion_reservas = date(hoy.year, hoy.month + 1, 1)

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

            # Mensaje según política aplicada
            if dia_actual <= 4:
                msg_cobro = 'No se te cobrará el mes actual.'
                msg_reservas = f'Tus {canceladas} reserva{"s" if canceladas != 1 else ""} fueron canceladas.'
            elif dia_actual <= 9:
                msg_cobro = 'Se te cobrará la mitad del mes actual.'
                msg_reservas = (
                    f'Podrás asistir a tus próximas {clases_a_cancelar} '
                    f'clase{"s" if clases_a_cancelar != 1 else ""} y luego se cancelarán automáticamente.'
                )
            else:
                msg_cobro = 'Se te cobrará el mes completo.'
                msg_reservas = 'Podrás asistir a tus clases hasta fin de mes. El 1º del mes siguiente se cancelarán.'

            messages.success(
                request,
                f'Plan "{plan.plan.nombre}" cancelado. {msg_cobro} {msg_reservas}'
            )
        else:
            messages.error(request, 'Error en la confirmación.')

        return redirect('gravity:mis_planes')

    # --- GET: preparar contexto ---
    clases_disponibles_sin_plan, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    plan.activo = False
    clases_despues_cancelacion, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    plan.activo = True

    reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)

    hoy = timezone.now().date()
    dia_actual = hoy.day
    if dia_actual <= 4:
        politica_cancelacion = 'sin_cargo'
        mensaje_politica = 'Como cancelás antes del día 5, no se te cobrará el mes actual.'
        mensaje_reservas = (
            f'Tus {plan.plan.clases_por_semana} reserva{"s" if plan.plan.clases_por_semana != 1 else ""} '
            f'se cancelarán inmediatamente.'
        )
    elif dia_actual <= 9:
        politica_cancelacion = 'medio_mes'
        mensaje_politica = 'Como cancelás entre el día 5 y 9, se te cobrará la mitad del mes actual.'
        mensaje_reservas = (
            f'Podrás asistir a tus próximas {plan.plan.clases_por_semana} '
            f'clase{"s" if plan.plan.clases_por_semana != 1 else ""} y luego se cancelarán automáticamente.'
        )
    else:
        politica_cancelacion = 'mes_completo'
        mensaje_politica = 'Como cancelás a partir del día 10, se te cobrará el mes completo.'
        mensaje_reservas = 'Podrás asistir a tus clases hasta fin de mes. El 1º del mes siguiente se cancelarán.'

    context = {
        'plan': plan,
        'clases_actuales': clases_disponibles_sin_plan,
        'clases_despues_cancelacion': clases_despues_cancelacion,
        'reservas_actuales': reservas_actuales,
        'podria_afectar_reservas': clases_despues_cancelacion < reservas_actuales,
        'politica_cancelacion': politica_cancelacion,
        'mensaje_politica': mensaje_politica,
        'mensaje_reservas': mensaje_reservas,
        'dia_actual': dia_actual,
    }
    
    return render(request, 'gravity/cancelar_plan.html', context)

# ==============================================================================
# VISTAS ADMIN — TESTIMONIOS
# ==============================================================================

@staff_member_required
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

@staff_member_required
def admin_testimonio_aprobar(request, testimonio_id):
    """Aprueba un testimonio para que sea visible públicamente"""
    if request.method != 'POST':
        return redirect('gravity:admin_testimonios_lista')

    testimonio = get_object_or_404(Testimonio, id=testimonio_id)
    testimonio.aprobado = True
    testimonio.save()
    messages.success(request, f'Testimonio de {testimonio.usuario.get_full_name() or testimonio.usuario.username} aprobado correctamente.')
    return redirect('gravity:admin_testimonios_lista')


@staff_member_required
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


@staff_member_required
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

def service_worker_js(request):
    from django.utils.timezone import now
    # Cambiar esta versión en cada deploy para forzar actualización en clientes
    version = now().strftime('%Y%m%d')  # Ej: '20250410' — cambia automáticamente cada día
    sw_content = f"""
        const CACHE_NAME = 'pilates-gravity-{version}';
        const STATIC_ASSETS = [
            '/',
            '/static/css/tailwind-output.css',
            '/static/js/base_scripts.js',
            '/static/icons/icon-192x192.png',
        ];

        self.addEventListener('install', (event) => {{
            event.waitUntil(
                caches.open(CACHE_NAME).then((cache) => {{
                    return cache.addAll(STATIC_ASSETS);
                }})
            );
            self.skipWaiting();
        }});

        self.addEventListener('activate', (event) => {{
            event.waitUntil(
                caches.keys().then((cacheNames) => {{
                    return Promise.all(
                        cacheNames
                            .filter((name) => name !== CACHE_NAME)
                            .map((name) => caches.delete(name))
                    );
                }}).then(() => {{
                    return self.clients.matchAll({{ type: 'window' }});
                }}).then((clients) => {{
                    clients.forEach(client => client.postMessage({{ type: 'SW_UPDATED' }}));
                }})
            );
            self.clients.claim();
        }});

        self.addEventListener('fetch', (event) => {{
            if (event.request.method !== 'GET') return;

            event.respondWith(
                caches.match(event.request).then((cached) => {{
                    return cached || fetch(event.request);
                }})
            );
        }});
    """
    return HttpResponse(sw_content, content_type='application/javascript')

