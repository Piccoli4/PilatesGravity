from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import (
    LoginView, PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView
)
from django.contrib import messages
from django.urls import reverse_lazy
from .forms import SignUpForm, ProfileUpdateForm, UserProfileForm, CambiarPasswordForm, EliminarCuentaForm, CustomPasswordResetForm, CustomSetPasswordForm, TestimonioForm
from .models import UserProfile, Testimonio
from .mi_espacio import resumen_alumno, reservas_alumno, SEDE_PREFERIDA
from gravity.email_service import enviar_email_bienvenida_completo, enviar_email_despedida_completo
from gravity.models import AusenciaTemporal
from datetime import date, timedelta
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

AUTH_TEMPLATE = 'accounts/auth.html'


def _render_auth(request, mode, login_form=None, signup_form=None, extra=None):
    """Login y registro comparten una sola vista con panel deslizante."""
    context = {
        'mode': mode,
        'login_form': login_form or AuthenticationForm(request),
        'signup_form': signup_form or SignUpForm(),
    }
    context.update(extra or {})
    return render(request, AUTH_TEMPLATE, context)


class CustomLoginView(LoginView):
    """Vista personalizada para el login"""
    template_name = AUTH_TEMPLATE
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('accounts:profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mode'] = 'login'
        context['login_form'] = context['form']
        context['signup_form'] = SignUpForm()
        return context

    def form_invalid(self, form):
        # El error se muestra dentro del panel de login (non_field_errors), sin aviso duplicado.
        return super().form_invalid(form)

def custom_logout_view(request):
    """Vista personalizada para el logout"""
    if request.method == 'POST':
        # Realizar logout
        logout(request)
        messages.success(request, 'Cerraste sesión. ¡Te esperamos en la próxima clase!')
        return redirect('gravity:home')
    else:
        # Mostrar página de confirmación
        return render(request, 'accounts/logout.html')

def signup(request):
    """Vista para registro de nuevos usuarios"""
    if request.user.is_authenticated:
        return redirect('gravity:home')
    
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                # Atómico: si falla al guardar el perfil, no queda el User creado a medias
                with transaction.atomic():
                    user = form.save()
            except IntegrityError:
                form.add_error('username', 'Ya existe una cuenta con ese nombre de usuario. Por favor elegí uno diferente.')
                return _render_auth(request, 'signup', signup_form=form)
            except ValidationError:
                logger.exception("Error de validación al guardar el perfil en el registro")
                messages.error(request, 'No pudimos crear la cuenta. Revisá los datos e intentá de nuevo.')
                return _render_auth(request, 'signup', signup_form=form)
            username = form.cleaned_data.get('username')
            messages.success(
                request,
                f'¡Cuenta creada exitosamente para {username}! '
                'Ya podés empezar a reservar tus clases de Pilates.'
            )
            
            # Iniciar sesión automáticamente después del registro
            login(request, user)

            # 📧 ENVIAR EMAIL DE BIENVENIDA
            try:
                enviar_email_bienvenida_completo(user)
                logger.info(f"Email de bienvenida enviado a {user.username}")
            except Exception as e:
                logger.error(f"Error enviando email de bienvenida: {str(e)}")
            
            return redirect('accounts:profile_complete') # Redirigir a completar perfil
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario')
    else:
        form = SignUpForm()

    return _render_auth(request, 'signup', signup_form=form)

@login_required
def profile(request):
    """Vista para ver/editar información básica del perfil"""
    
    try:
        user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        user_profile = UserProfile.objects.create(user=request.user)

    # Obtener o preparar el testimonio del usuario
    try:
        testimonio = request.user.testimonio
    except Testimonio.DoesNotExist:
        testimonio = None

    if request.method == 'POST':
        form = ProfileUpdateForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tus datos se guardaron correctamente.')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Revisá los datos marcados e intentá de nuevo.')
    else:
        form = ProfileUpdateForm(request.user)

    testimonio_form = TestimonioForm(instance=testimonio)

    # Ausencias cuyo plazo de recupero ya venció y el usuario aún no vio el aviso
    hoy = date.today()
    ausencias_vencidas_sin_ver = AusenciaTemporal.objects.filter(
        reserva__usuario=request.user,
        notificacion_vencimiento_vista=False,
        fecha__lt=hoy - timedelta(days=6),
    ).select_related('reserva__clase')

    me = resumen_alumno(request.user)
    context = {
        'form': form,
        # Si los datos no se pudieron guardar, el formulario se muestra abierto con los errores
        'editar_abierto': request.method == 'POST',
        'user_profile': user_profile,
        'testimonio': testimonio,
        'testimonio_form': testimonio_form,
        'ausencias_vencidas_sin_ver': ausencias_vencidas_sin_ver,
        'me': me,
        'hay_avisos': bool(
            me['n_recuperos'] or me['solicitud'] or not user_profile.perfil_completado
            or (not me['plan'] and not request.user.is_staff)
        ),
        'sede_preferida': SEDE_PREFERIDA.get(user_profile.sede_preferida, 'Cualquier sede'),
    }
    return render(request, 'accounts/profile.html', context)

# Paso del recorrido guiado en el que se pide cada campo de la ficha
PASOS_FICHA = {
    'telefono': 1, 'fecha_nacimiento': 1, 'nivel_experiencia': 1,
    'tiene_lesiones': 2, 'descripcion_lesiones': 2,
    'avatar': 3, 'acepta_recordatorios': 3, 'sede_preferida': 3,
}


@login_required
def profile_complete(request):
    """
    Ficha del alumno. La primera vez (perfil sin completar) es un recorrido guiado
    de 3 pasos; después, una sola página para editar.
    """
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    es_primera_vez = not profile.perfil_completado

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.perfil_completado = True
            profile.save()
            if es_primera_vez:
                messages.success(request, '¡Listo! Tu ficha quedó completa. Ya podés reservar tus clases.')
            else:
                messages.success(request, 'Tus cambios se guardaron.')
            return redirect('accounts:profile')
        messages.error(request, 'Revisá los datos marcados e intentá de nuevo.')
    else:
        form = UserProfileForm(instance=profile)

    # Si hubo errores, el recorrido arranca en el primer paso que falló
    pasos_con_error = [PASOS_FICHA.get(campo, 1) for campo in form.errors]
    context = {
        'form': form,
        'es_primera_vez': es_primera_vez,
        'paso_inicial': min(pasos_con_error) if pasos_con_error else 1,
        'profile': profile,
    }
    return render(request, 'accounts/profile_complete.html', context)

@login_required
def cambiar_password(request):
    """Vista para cambiar la contraseña del usuario"""
    if request.method == 'POST':
        form = CambiarPasswordForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            # Mantener la sesión activa después del cambio de contraseña
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Listo, cambiaste tu contraseña. Usala la próxima vez que entres.')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Revisá los datos marcados e intentá de nuevo.')
    else:
        form = CambiarPasswordForm(request.user)
    
    return render(request, 'accounts/cambiar_password.html', {'form': form})

@login_required
def mis_reservas(request):
    """Agenda, horarios fijos, recuperos e historial del alumno."""
    context = {
        'me': resumen_alumno(request.user),
        'r': reservas_alumno(request.user),
        # Avisos de una sola vez que deja la acción anterior (se cierran por AJAX)
        'reserva_exitosa': request.session.get('reserva_exitosa'),
        'ausencia_registrada': request.session.get('ausencia_registrada'),
    }
    return render(request, 'accounts/mis_reservas.html', context)

@login_required
def guardar_testimonio(request):
    """Vista para crear o actualizar el testimonio del usuario"""
    if request.method != 'POST':
        return redirect('accounts:profile')

    try:
        testimonio = request.user.testimonio
    except Testimonio.DoesNotExist:
        testimonio = None

    form = TestimonioForm(request.POST, instance=testimonio)
    if form.is_valid():
        nuevo = form.save(commit=False)
        nuevo.usuario = request.user
        nuevo.save()
        messages.success(request, 'Tu comentario fue guardado y está pendiente de aprobación.')
    else:
        messages.error(request, 'Por favor corrige los errores en el formulario.')

    return redirect('accounts:profile')

@login_required
def eliminar_cuenta(request):
    """
    El alumno elimina su cuenta: se anonimiza (ver accounts/baja.py). No se permite
    con deuda pendiente ni para cuentas del equipo.
    """
    from .baja import anonimizar_cuenta, motivo_bloqueo
    from gravity.models import PlanUsuario

    bloqueo = motivo_bloqueo(request.user)

    if request.method == 'POST' and not bloqueo:
        form = EliminarCuentaForm(request.user, request.POST)
        if form.is_valid():
            usuario = request.user
            # El email de despedida sale antes de borrar el email y el nombre
            try:
                enviar_email_despedida_completo(usuario)
            except Exception as e:
                logger.error(f"Error enviando email de despedida: {str(e)}")
            anonimizar_cuenta(usuario)
            logout(request)
            messages.success(request, 'Eliminamos tu cuenta. Gracias por haber sido parte de Pilates Gravity.')
            return redirect('gravity:home')
        messages.error(request, 'Revisá los datos marcados e intentá de nuevo.')
    else:
        form = EliminarCuentaForm(request.user)

    context = {
        'form': form,
        'bloqueo': bloqueo[0] if bloqueo else None,
        'deuda': bloqueo[1] if bloqueo else None,
        'reservas_activas': request.user.reservas_pilates.filter(activa=True).count(),
        'plan': PlanUsuario.objects.filter(usuario=request.user, activo=True).select_related('plan').first(),
    }
    return render(request, 'accounts/eliminar_cuenta.html', context)

class CustomPasswordResetView(PasswordResetView):
    """Pedir el enlace por email. El mensaje es el mismo exista o no la cuenta."""
    template_name = 'accounts/password_reset_form.html'
    form_class = CustomPasswordResetForm
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    html_email_template_name = 'accounts/password_reset_email.html'
    success_url = reverse_lazy('accounts:password_reset_done')

    def form_valid(self, form):
        # Para mostrarlo en "Revisá tu correo" y poder reenviar
        self.request.session['reset_email'] = form.cleaned_data['email']
        return super().form_valid(form)


class CustomPasswordResetDoneView(PasswordResetDoneView):
    """Confirma que se envió el email (si la cuenta existe)."""
    template_name = 'accounts/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['email'] = self.request.session.get('reset_email', '')
        return context


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """Elegir la contraseña nueva desde el enlace del email."""
    template_name = 'accounts/password_reset_confirm.html'
    form_class = CustomSetPasswordForm
    success_url = reverse_lazy('accounts:password_reset_complete')

    def form_valid(self, form):
        self.request.session.pop('reset_email', None)
        return super().form_valid(form)

def invitacion(request, uidb64, token):
    """
    Crear la contraseña desde la invitación que manda el estudio al crear la cuenta.
    Al guardarla, entra directo: un alumno va a completar su ficha; alguien del
    equipo, al panel.
    """
    from django.contrib.auth.models import User
    from django.utils.encoding import force_str
    from django.utils.http import urlsafe_base64_decode
    from .invitacion import invitacion_token

    try:
        usuario = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        usuario = None
    valido = usuario is not None and invitacion_token.check_token(usuario, token)

    form = CustomSetPasswordForm(usuario, request.POST or None) if valido else None
    if valido and request.method == 'POST' and form.is_valid():
        form.save()
        if request.user.is_authenticated:
            logout(request)
        login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
        if usuario.is_staff:
            messages.success(request, f'¡Listo, {usuario.first_name or usuario.username}! Ya tenés tu contraseña. Te damos la bienvenida al panel.')
            return redirect('gravity:admin_dashboard')
        messages.success(request, f'¡Listo, {usuario.first_name or usuario.username}! Ya tenés tu contraseña. Completá tu ficha para empezar.')
        return redirect('accounts:profile_complete')
    return render(request, 'accounts/invitacion.html', {'form': form, 'validlink': valido, 'usuario': usuario if valido else None})


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    """Vista que confirma que el reset fue exitoso"""
    template_name = 'accounts/password_reset_complete.html'