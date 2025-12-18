from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import Reserva, Clase, PlanUsuario, DIAS_SEMANA, DIAS_SEMANA_COMPLETOS
from .forms import ReservaForm, ModificarReservaForm, BuscarReservaForm
import json
from accounts.models import UserProfile
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from datetime import datetime, timedelta, date
from accounts.models import UserProfile, ConfiguracionEstudio
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
import logging
from .email_service import (
    enviar_email_cancelacion_reserva,
    enviar_email_confirmacion_reserva_detallado,
    enviar_email_recordatorio_clase_completo,
    enviar_email_confirmacion_pago_completo
)
from .models import PlanPago, EstadoPagoCliente, RegistroPago
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
                reserva = Reserva.objects.create(
                    usuario=request.user,
                    clase=clase
                )

                # 📧 ENVIAR EMAIL DE CONFIRMACIÓN DE RESERVA
                try:
                    email_enviado = enviar_email_confirmacion_reserva_detallado(reserva)
                    if email_enviado:
                        logger.info(f"Email de confirmación enviado para reserva {reserva.numero_reserva}")
                except Exception as e:
                    logger.error(f"Error enviando email de confirmación: {str(e)}")
                
                # Recalcular reservas después de crear
                nuevas_reservas = Reserva.contar_reservas_usuario_semana(request.user)
                
                messages.success(
                    request,
                    f'¡Reserva exitosa! Tu número de reserva es {reserva.numero_reserva}. '
                    f'Asistirás todos los {clase.dia} a las {clase.horario.strftime("%H:%M")} '
                    f'a la clase de {clase.get_nombre_display()} en {clase.get_direccion_corta()}. '
                    f'Reservas esta semana: {nuevas_reservas}/{clases_disponibles}'
                )
                
                return redirect('gravity:home')
                
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
    # Obtener la reserva y verificar que pertenece al usuario
    reserva = get_object_or_404(
        Reserva,
        numero_reserva=numero_reserva,
        usuario=request.user,
        activa=True
    )
    
    # Verificar si la reserva puede modificarse (12 horas de anticipación)
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
    Permite a un usuario cancelar su propia reserva.
    Maneja tanto GET (para mostrar confirmación) como POST (para cancelar).
    """
    # Obtener la reserva y verificar que pertenece al usuario
    reserva = get_object_or_404(
        Reserva, 
        numero_reserva=numero_reserva, 
        usuario=request.user, 
        activa=True
    )
    
    # Verificar si la reserva puede modificarse (12 horas de anticipación)
    puede_cancelar, mensaje = reserva.puede_modificarse()
    
    if not puede_cancelar:
        messages.error(request, f'No puedes cancelar esta reserva: {mensaje}')
        return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)

    if request.method == 'POST':
        # Verificar confirmación
        confirmar = request.POST.get('confirmar_cancelacion')
        
        if confirmar == 'confirmar':
            try:
                # Cancelar la reserva
                reserva.activa = False
                reserva.save()
                
                messages.success(
                    request,
                    f'Tu reserva para la clase de {reserva.clase.get_nombre_display()} '
                    f'los {reserva.clase.dia} a las {reserva.clase.horario.strftime("%H:%M")} '
                    f'en {reserva.clase.get_direccion_corta()} ha sido cancelada exitosamente.'
                )
                
                return redirect('accounts:mis_reservas')
                
            except Exception as e:
                messages.error(
                    request,
                    'Ocurrió un error al cancelar tu reserva. Por favor intenta nuevamente.'
                )
                return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)
        else:
            messages.error(request, 'Debes confirmar la cancelación de tu reserva.')
            return redirect('gravity:detalle_reserva', numero_reserva=numero_reserva)
    
    # Si es GET, redirigir al detalle (ya que ahora usamos modal)
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
    
    return render(request, 'gravity/detalle_reserva.html', {
        'reserva': reserva,
        'puede_modificar': puede_modificar,
        'mensaje_modificacion': mensaje_modificacion,
        'proxima_clase_info': reserva.get_proxima_clase_info(),
        'es_propietario': es_propietario
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
            'porcentaje_ocupacion': porcentaje_ocupacion
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
    return render(request, 'gravity/conoce_mas.html')

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
    }
    
    return render(request, 'gravity/admin/dashboard.html', context)

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
    
    # Obtener todas las reservas de esta clase
    reservas = clase.reserva_set.filter(activa=True).select_related(
        'usuario', 'usuario__profile'
    ).order_by('usuario__first_name', 'usuario__last_name')
    
    context = {
        'clase': clase,
        'reservas': reservas,
        'total_reservas': reservas.count(),
        'cupos_disponibles': clase.cupos_disponibles(),
        'porcentaje_ocupacion': clase.get_porcentaje_ocupacion()
    }
    
    return render(request, 'gravity/admin/clase_detalle.html', context)

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
    Agregar un usuario directamente al sistema y reservarlo en una clase
    """
    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        email = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '').strip()
        clase_id = request.POST.get('clase_id')
        
        # Validaciones básicas
        if not nombre or not apellido or not password or not telefono or not clase_id:
            messages.error(request, 'Nombre, apellido, contraseña, teléfono y clase son obligatorios.')
            return render(request, 'gravity/admin/agregar_cliente_form.html', {
                'clases_disponibles': Clase.objects.filter(activa=True).order_by(
                    'direccion', 'tipo', 'dia', 'horario'
                ),
                'form_data': request.POST
            })
        
        try:
            clase = get_object_or_404(Clase, id=clase_id, activa=True)
            
            # Verificar que la clase tenga cupos disponibles
            if clase.cupos_disponibles() <= 0:
                messages.error(request, 'La clase seleccionada no tiene cupos disponibles.')
                return render(request, 'gravity/admin/agregar_cliente_form.html', {
                    'clases_disponibles': Clase.objects.filter(activa=True).order_by(
                        'direccion', 'tipo', 'dia', 'horario'
                    ),
                    'form_data': request.POST
                })
            
            # Generar username único
            base_username = f"{nombre.lower()}{apellido.lower()}"
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Usar transacción para asegurar consistencia
            with transaction.atomic():
                # Crear usuario (esto automáticamente crea el UserProfile via señal)
                user = User.objects.create_user(
                    username=username,
                    email=email if email else '',
                    first_name=nombre,
                    last_name=apellido,
                    password=password,
                )
                
                # Obtener el perfil que se creó automáticamente y actualizarlo
                # Usar get_or_create para mayor seguridad
                profile, created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'telefono': telefono,
                        'sede_preferida': 'cualquiera'
                    }
                )
                
                # Si el perfil ya existía, actualizar solo el teléfono
                if not created:
                    profile.telefono = telefono
                    profile.sede_preferida = 'cualquiera'
                    profile.save()
                
                # Crear la reserva
                reserva = Reserva.objects.create(
                    usuario=user,
                    clase=clase
                )
                
                messages.success(
                    request,
                    f'Usuario {nombre} {apellido} creado exitosamente y reservado en '
                    f'{clase.get_nombre_display()} del {clase.dia} a las {clase.horario.strftime("%H:%M")} '
                    f'en {clase.get_direccion_corta()}. '
                    f'Credenciales: usuario={username}, contraseña={password}. '
                    f'Reserva: {reserva.numero_reserva}'
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
        if cupos > 0:  # Solo mostrar clases con cupos
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
        'ingresos_mes': ingresos_mes,
        'total_deuda': total_deuda,
        'mes_actual': mes_actual,
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
            
            # NO recalcular desde cero, sino actualizar acumulativamente
            estado_pago.actualizar_saldo_automatico()
            estado_pago.ultimo_pago = pago.fecha_pago
            estado_pago.monto_ultimo_pago = pago.monto
            estado_pago.save()
            
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
    
    context = {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
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
    
    context = {
        'cliente': cliente,
        'estado_pago': estado_pago,
        'pagos': pagos,
        'total_pagado': total_pagado,
        'total_pagos': total_pagos,
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
    estado_pago, created = EstadoPagoCliente.objects.get_or_create(
        usuario=cliente,
        defaults={'activo': True}
    )
    
    if request.method == 'POST':
        form = EstadoPagoClienteForm(request.POST, instance=estado_pago)
        
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Estado de pago actualizado para {cliente.get_full_name() or cliente.username}'
            )
            return redirect('gravity:admin_pagos_vista_principal')
    else:
        form = EstadoPagoClienteForm(instance=estado_pago)
    
    context = {
        'form': form,
        'cliente': cliente,
        'estado_pago': estado_pago,
    }
    
    return render(request, 'gravity/admin/pagos_editar_estado.html', context)

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
            fecha_fin = fecha_inicio + timedelta(days=30)
            
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
                    f'Ahora tienes "{plan_seleccionado.nombre}" válido hasta {fecha_fin.strftime("%d/%m/%Y")}.'
                )
            else:
                messages.success(
                    request,
                    f'¡Plan seleccionado exitosamente! '
                    f'Tienes "{plan_seleccionado.nombre}" válido hasta {fecha_fin.strftime("%d/%m/%Y")}. '
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
        activo=True,  # Cambiar 'activa' por 'activo'
        fecha_fin__gte=timezone.now().date()
    ).select_related('plan').order_by('fecha_fin')
    
    # Obtener planes vencidos (últimos 5)
    planes_vencidos = PlanUsuario.objects.filter(
        Q(usuario=request.user) & 
        (Q(activo=False) | Q(fecha_fin__lt=timezone.now().date()))
    ).select_related('plan').order_by('-fecha_fin')[:5]
    
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
            plan.activo = False
            plan.save()
            
            messages.success(
                request,
                f'Plan "{plan.plan.nombre}" cancelado exitosamente. '
                f'Las reservas existentes no se ven afectadas.'
            )
        else:
            messages.error(request, 'Error en la confirmación.')
        
        return redirect('gravity:mis_planes')
    
    # Verificar si tiene reservas que podrían verse afectadas
    clases_disponibles_sin_plan, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    # Simular la cancelación para ver cuántas clases quedarían
    plan.activo = False
    clases_despues_cancelacion, _ = PlanUsuario.obtener_clases_disponibles_usuario(request.user)
    plan.activo = True  # Restaurar
    
    reservas_actuales = Reserva.contar_reservas_usuario_semana(request.user)
    
    context = {
        'plan': plan,
        'clases_actuales': clases_disponibles_sin_plan,
        'clases_despues_cancelacion': clases_despues_cancelacion,
        'reservas_actuales': reservas_actuales,
        'podria_afectar_reservas': clases_despues_cancelacion < reservas_actuales
    }
    
    return render(request, 'gravity/cancelar_plan.html', context)

