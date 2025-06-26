from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import Reserva, Clase, DIAS_SEMANA, Cliente, Turno
from .forms import ReservaForm, ModificarReservaForm, EliminarReservaForm, BuscarReservaForm
import json
from accounts.models import UserProfile
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Cliente, Turno
from accounts.models import UserProfile, ConfiguracionEstudio
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction

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
                
                messages.success(
                    request,
                    f'¡Reserva exitosa! Tu número de reserva es {reserva.numero_reserva}. '
                    f'Asistirás todos los {clase.dia} a las {clase.horario.strftime("%H:%M")} '
                    f'a la clase de {clase.get_tipo_display()}.'
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
        tipo_preseleccionado = request.GET.get('tipo', '')
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
        'tipo_preseleccionado': tipo_preseleccionado
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
                    f'{nueva_clase.get_tipo_display()} los {nueva_clase.dia} '
                    f'a las {nueva_clase.horario.strftime("%H:%M")}.'
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
def eliminar_reserva(request, numero_reserva):
    """
    Permite a un usuario cancelar su propia reserva.
    Utiliza EliminarReservaForm con validación de confirmación.
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
        form = EliminarReservaForm(
            request.POST, 
            reserva=reserva, 
            user=request.user
        )
        
        if form.is_valid():
            # Cancelar la reserva
            reserva.activa = False
            reserva.save()
            
            messages.success(
                request,
                f'Tu reserva para la clase de {reserva.clase.get_tipo_display()} '
                f'los {reserva.clase.dia} a las {reserva.clase.horario.strftime("%H:%M")} '
                'ha sido cancelada exitosamente.'
            )
            
            return redirect('gravity:home')
    else:
        form = EliminarReservaForm(reserva=reserva, user=request.user)

    return render(request, 'gravity/eliminar_reserva.html', {
        'form': form,
        'reserva': reserva,
        'puede_cancelar': puede_cancelar,
        'mensaje_restriccion': mensaje if not puede_cancelar else None
    })

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
                # Obtener todas las reservas activas del usuario
                reservas_usuario = Reserva.objects.filter(
                    usuario=usuario_encontrado,
                    activa=True
                ).select_related('clase').order_by('clase__dia', 'clase__horario')
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
    Vista informativa pública.
    """
    clases = Clase.objects.filter(activa=True).order_by('tipo', 'dia', 'horario')
    
    clases_info = []
    for clase in clases:
        clases_info.append({
            'clase': clase,
            'cupos_disponibles': clase.cupos_disponibles(),
            'esta_completa': clase.esta_completa(),
            'porcentaje_ocupacion': clase.get_porcentaje_ocupacion()
        })
    
    return render(request, 'gravity/clases_disponibles.html', {
        'clases_info': clases_info
    })

# Vista para el botón de "Conoce más" (pública)
def conoce_mas(request):
    """Vista informativa sobre el estudio"""
    return render(request, 'gravity/conoce_mas.html')

# API Endpoints para funcionalidad AJAX
@require_http_methods(["POST"])
def dias_disponibles(request):
    """
    API que devuelve los días únicos disponibles para un tipo de clase específico
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        
        if not tipo_clase:
            return JsonResponse({'error': 'Tipo de clase requerido'}, status=400)

        # Obtener días únicos para el tipo de clase (solo clases activas)
        dias_disponibles = Clase.objects.filter(
            tipo=tipo_clase, 
            activa=True
        ).values_list('dia', flat=True).distinct()

        # Ordenar días según el orden de la semana
        orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
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
    API que devuelve los horarios disponibles para un tipo de clase y día específicos
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        dia_clase = data.get('dia')
        
        if not tipo_clase or not dia_clase:
            return JsonResponse({'error': 'Tipo de clase y día requeridos'}, status=400)
        
        # Obtener horarios para la combinación tipo-día (solo clases activas)
        clases = Clase.objects.filter(
            tipo=tipo_clase, 
            dia=dia_clase,
            activa=True
        ).order_by('horario')
        
        horarios_info = []
        for clase in clases:
            cupos_disponibles = clase.cupos_disponibles()
            horarios_info.append({
                'value': clase.horario.strftime('%H:%M'),
                'text': f"{clase.horario.strftime('%H:%M')} ({cupos_disponibles} cupos disponibles)",
                'cupos': cupos_disponibles,
                'disponible': cupos_disponibles > 0
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
    API que verifica la disponibilidad de una combinación específica tipo-día-horario
    """
    try:
        data = json.loads(request.body)
        tipo_clase = data.get('tipo')
        dia_clase = data.get('dia')
        horario_str = data.get('horario')
        
        if not all([tipo_clase, dia_clase, horario_str]):
            return JsonResponse({'error': 'Todos los campos son requeridos'}, status=400)
        
        from datetime import datetime
        horario_time = datetime.strptime(horario_str, '%H:%M').time()
        
        try:
            clase = Clase.objects.get(
                tipo=tipo_clase, 
                dia=dia_clase, 
                horario=horario_time,
                activa=True
            )
            cupos_disponibles = clase.cupos_disponibles()
            
            return JsonResponse({
                'disponible': cupos_disponibles > 0,
                'cupos_disponibles': cupos_disponibles,
                'cupo_maximo': clase.cupo_maximo,
                'mensaje': f'Quedan {cupos_disponibles} cupos disponibles' if cupos_disponibles > 0 else 'Clase completa'
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
    API que devuelve todas las clases disponibles con información de cupos
    """
    try:
        clases = Clase.objects.filter(activa=True).order_by('tipo', 'dia', 'horario')
        
        clases_data = []
        for clase in clases:
            cupos_disponibles = clase.cupos_disponibles()
            clases_data.append({
                'id': clase.id,
                'tipo': clase.tipo,
                'tipo_display': clase.get_tipo_display(),
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
    """
    # Estadísticas generales
    total_clases = Clase.objects.filter(activa=True).count()
    total_reservas_activas = Reserva.objects.filter(activa=True).count()
    total_usuarios = User.objects.filter(is_active=True, is_staff=False).count()
    total_clientes_legacy = Cliente.objects.count()
    
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
        'total_clientes_legacy': total_clientes_legacy,
        'usuarios_nuevos': usuarios_nuevos,
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
    """
    clases = Clase.objects.all().order_by('tipo', 'dia', 'horario')
    
    # Filtros
    tipo_filtro = request.GET.get('tipo', '')
    dia_filtro = request.GET.get('dia', '')
    estado_filtro = request.GET.get('estado', '')
    
    if tipo_filtro:
        clases = clases.filter(tipo=tipo_filtro)
    
    if dia_filtro:
        clases = clases.filter(dia=dia_filtro)
    
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
        'tipos_clases': Clase.TIPO_CLASES,
        'dias_semana': DIAS_SEMANA,
    }
    
    return render(request, 'gravity/admin/clases_lista.html', context)


@admin_required
def admin_clase_crear(request):
    """
    Crear una nueva clase
    """
    if request.method == 'POST':
        # Obtener datos del formulario
        tipo = request.POST.get('tipo')
        dia = request.POST.get('dia')
        horario_str = request.POST.get('horario')
        cupo_maximo = request.POST.get('cupo_maximo')
        
        try:
            # Validar horario
            horario = datetime.strptime(horario_str, '%H:%M').time()
            
            # Verificar que no exista una clase igual
            if Clase.objects.filter(tipo=tipo, dia=dia, horario=horario).exists():
                messages.error(request, 'Ya existe una clase con estas características.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA,
                    'form_data': request.POST
                })
            
            # Crear la clase
            clase = Clase.objects.create(
                tipo=tipo,
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
        'dias_semana': DIAS_SEMANA,
        'accion': 'Crear'
    }
    
    return render(request, 'gravity/admin/clase_form.html', context)


@admin_required
def admin_clase_editar(request, clase_id):
    """
    Editar una clase existente
    """
    clase = get_object_or_404(Clase, id=clase_id)
    
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        dia = request.POST.get('dia')
        horario_str = request.POST.get('horario')
        cupo_maximo = request.POST.get('cupo_maximo')
        activa = request.POST.get('activa') == 'on'
        
        try:
            horario = datetime.strptime(horario_str, '%H:%M').time()
            
            # Verificar duplicados (excluyendo la clase actual)
            if Clase.objects.filter(
                tipo=tipo, dia=dia, horario=horario
            ).exclude(id=clase.id).exists():
                messages.error(request, 'Ya existe otra clase con estas características.')
                return render(request, 'gravity/admin/clase_form.html', {
                    'clase': clase,
                    'tipos_clases': Clase.TIPO_CLASES,
                    'dias_semana': DIAS_SEMANA,
                    'accion': 'Editar'
                })
            
            # Actualizar la clase
            clase.tipo = tipo
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
        'dias_semana': DIAS_SEMANA,
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
            tipo_nombre = clase.get_tipo_display()
            dia = clase.dia
            horario = clase.horario.strftime('%H:%M')
            
            clase.delete()
            messages.success(
                request, 
                f'Clase eliminada exitosamente: {tipo_nombre} - {dia} {horario}'
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
    """
    reservas = Reserva.objects.select_related(
        'usuario', 'clase', 'usuario__profile'
    ).order_by('-fecha_reserva')
    
    # Filtros
    estado_filtro = request.GET.get('estado', 'activas')
    tipo_clase_filtro = request.GET.get('tipo_clase', '')
    dia_filtro = request.GET.get('dia', '')
    usuario_filtro = request.GET.get('usuario', '')
    
    if estado_filtro == 'activas':
        reservas = reservas.filter(activa=True)
    elif estado_filtro == 'canceladas':
        reservas = reservas.filter(activa=False)
    
    if tipo_clase_filtro:
        reservas = reservas.filter(clase__tipo=tipo_clase_filtro)
    
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
        'dia_filtro': dia_filtro,
        'usuario_filtro': usuario_filtro,
        'tipos_clases': Clase.TIPO_CLASES,
        'dias_semana': DIAS_SEMANA,
    }
    
    return render(request, 'gravity/admin/reservas_lista.html', context)


@admin_required
def admin_reserva_cancelar(request, reserva_id):
    """
    Cancelar una reserva como administrador (sin restricciones de tiempo)
    """
    reserva = get_object_or_404(Reserva, id=reserva_id, activa=True)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo', '')
        
        # Cancelar la reserva
        reserva.activa = False
        if motivo:
            reserva.notas = f"Cancelada por administrador: {motivo}"
        reserva.save()
        
        messages.success(
            request,
            f'Reserva {reserva.numero_reserva} de {reserva.get_nombre_completo_usuario()} cancelada exitosamente.'
        )
        
        return redirect('gravity:admin_reservas_lista')
    
    context = {
        'reserva': reserva
    }
    
    return render(request, 'gravity/admin/reserva_cancelar.html', context)


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
    
    if busqueda:
        usuarios = usuarios.filter(
            Q(username__icontains=busqueda) |
            Q(first_name__icontains=busqueda) |
            Q(last_name__icontains=busqueda) |
            Q(email__icontains=busqueda)
        )
    
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
    
    # Obtener todas las reservas del usuario
    reservas_activas = usuario.reservas_pilates.filter(activa=True).select_related(
        'clase'
    ).order_by('clase__dia', 'clase__horario')
    
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


# ==============================================================================
# AGREGAR CLIENTES NO REGISTRADOS
# ==============================================================================

@admin_required
def admin_agregar_cliente_no_registrado(request):
    """
    Agregar un cliente directamente a una clase sin que esté registrado en el sistema
    """
    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        email = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        clase_id = request.POST.get('clase_id')
        
        # Validaciones básicas
        if not nombre or not apellido or not telefono or not clase_id:
            messages.error(request, 'Nombre, apellido, teléfono y clase son obligatorios.')
            return render(request, 'gravity/admin/agregar_cliente_form.html', {
                'clases_disponibles': Clase.objects.filter(activa=True).order_by(
                    'tipo', 'dia', 'horario'
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
                        'tipo', 'dia', 'horario'
                    ),
                    'form_data': request.POST
                })
            
            # Crear cliente no registrado
            cliente = Cliente.objects.create(
                nombre=nombre,
                apellido=apellido,
                email=email if email else None,
                telefono=telefono,
                codigo_verificacion='0000'  # Código dummy para clientes admin
            )
            
            # Crear turno para el cliente (usando el modelo legacy)
            # Calcular la próxima fecha de esta clase
            today = timezone.now().date()
            dias_semana_num = {
                'Lunes': 0, 'Martes': 1, 'Miércoles': 2, 'Jueves': 3, 'Viernes': 4
            }
            
            dia_clase_num = dias_semana_num.get(clase.dia)
            dias_hasta_clase = (dia_clase_num - today.weekday()) % 7
            if dias_hasta_clase == 0:
                # Si es hoy, verificar si la clase ya pasó
                now = timezone.now()
                clase_hoy = now.replace(
                    hour=clase.horario.hour,
                    minute=clase.horario.minute,
                    second=0,
                    microsecond=0
                )
                if clase_hoy <= now:
                    dias_hasta_clase = 7
            
            fecha_clase = today + timedelta(days=dias_hasta_clase)
            
            turno = Turno.objects.create(
                cliente=cliente,
                clase=clase,
                fecha=fecha_clase
            )
            
            messages.success(
                request,
                f'Cliente {nombre} {apellido} agregado exitosamente a la clase de '
                f'{clase.get_tipo_display()} del {clase.dia} a las {clase.horario.strftime("%H:%M")}. '
                f'Número de cliente: {cliente.numero_cliente}'
            )
            
            return redirect('gravity:admin_clases_lista')
            
        except Exception as e:
            messages.error(request, f'Error al agregar cliente: {str(e)}')
    
    # Obtener clases disponibles con cupos
    clases_disponibles = []
    for clase in Clase.objects.filter(activa=True).order_by('tipo', 'dia', 'horario'):
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


@admin_required
def admin_clientes_no_registrados_lista(request):
    """
    Lista de clientes no registrados (modelo Cliente legacy)
    """
    clientes = Cliente.objects.filter(usuario__isnull=True).order_by('-id')
    
    # Busqueda
    busqueda = request.GET.get('busqueda', '')
    if busqueda:
        clientes = clientes.filter(
            Q(nombre__icontains=busqueda) |
            Q(apellido__icontains=busqueda) |
            Q(email__icontains=busqueda) |
            Q(telefono__icontains=busqueda) |
            Q(numero_cliente__icontains=busqueda)
        )
    
    # Agregar información de turnos a cada cliente
    clientes_info = []
    for cliente in clientes:
        turnos = Turno.objects.filter(cliente=cliente).select_related('clase')
        clientes_info.append({
            'cliente': cliente,
            'turnos': turnos,
            'total_turnos': turnos.count()
        })
    
    # Paginación
    paginator = Paginator(clientes_info, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'busqueda': busqueda,
    }
    
    return render(request, 'gravity/admin/clientes_no_registrados_lista.html', context)


# ==============================================================================
# REPORTES Y ESTADÍSTICAS
# ==============================================================================

@admin_required
def admin_reportes(request):
    """
    Página de reportes y estadísticas avanzadas
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
    
    # Estadísticas por día de la semana
    stats_por_dia = []
    for dia, nombre in DIAS_SEMANA:
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
        'stats_por_dia': stats_por_dia,
    }
    
    return render(request, 'gravity/admin/reportes.html', context)