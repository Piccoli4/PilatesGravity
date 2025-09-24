from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView, PasswordResetView, PasswordResetDoneView, 
    PasswordResetConfirmView, PasswordResetCompleteView
)
from django.contrib import messages
from django.urls import reverse_lazy
from .forms import SignUpForm, ProfileUpdateForm, UserProfileForm, CambiarPasswordForm, CustomPasswordResetForm, CustomSetPasswordForm
from .models import UserProfile

class CustomLoginView(LoginView):
    """Vista personalizada para el login"""
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return reverse_lazy('accounts:profile')
    
    def form_invalid(self, form):
        messages.error(self.request, 'Usuario o contraseña incorrectos')
        return super().form_invalid(form)

def custom_logout_view(request):
    """Vista personalizada para el logout"""
    if request.method == 'POST':
        # Realizar logout
        logout(request)
        messages.success(request, '¡Has cerrado sesión exitosamente!')
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
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(
                request, 
                f'¡Cuenta creada exitosamente para {username}! '
                'Ya puedes empezar a reservar tus clases de Pilates.'
            )
            
            # Iniciar sesión automáticamente después del registro
            login(request, user)
            return redirect('accounts:profile_complete')  # Redirigir a completar perfil
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario')
    else:
        form = SignUpForm()
    
    return render(request, 'accounts/signup.html', {'form': form})

@login_required
def profile(request):
    """Vista para ver/editar información básica del perfil"""
    
    # Asegura que el usuario tenga un perfil 
    try:
        user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        user_profile = UserProfile.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = ProfileUpdateForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tu información básica ha sido actualizada exitosamente')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario')
    else:
        form = ProfileUpdateForm(request.user)
    
    context = {
        'form': form,
        'user_profile': user_profile
    }
    return render(request, 'accounts/profile.html', context)

@login_required
def profile_complete(request):
    """Vista para completar el perfil extendido del usuario"""
    # Obtener o crear el perfil del usuario
    profile, created = request.user.profile, False
    if not hasattr(request.user, 'profile'):
        from .models import UserProfile
        profile = UserProfile.objects.create(user=request.user)
        created = True
    
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.perfil_completado = True
            profile.save()
            
            messages.success(
                request, 
                '¡Tu perfil ha sido completado exitosamente! '
                'Ahora puedes empezar a reservar tus clases.'
            )
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario')
    else:
        form = UserProfileForm(instance=profile)
    
    context = {
        'form': form,
        'is_new_profile': created or not profile.perfil_completado
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
            messages.success(request, '¡Tu contraseña ha sido cambiada exitosamente!')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario')
    else:
        form = CambiarPasswordForm(request.user)
    
    return render(request, 'accounts/cambiar_password.html', {'form': form})

@login_required
def mis_reservas(request):
    """Vista para mostrar las reservas del usuario actual"""
    reservas_activas = request.user.reservas_pilates.filter(activa=True).select_related('clase')
    reservas_inactivas = request.user.reservas_pilates.filter(activa=False).select_related('clase')[:10]  # Últimas 10 canceladas
    
    context = {
        'reservas_activas': reservas_activas,
        'reservas_inactivas': reservas_inactivas,
        'total_reservas': request.user.reservas_pilates.count()
    }
    return render(request, 'accounts/mis_reservas.html', context)

@login_required
def eliminar_cuenta(request): 
    """Vista para que el usuario pueda eliminar su propia cuenta"""
    if request.method == 'POST':
        # Confirmar eliminación
        confirmacion = request.POST.get('confirmar_eliminacion')
        if confirmacion == 'confirmar':
            username = request.user.username
            
            # Obtener estadísticas antes de eliminar
            total_reservas = request.user.reservas_pilates.count()
            reservas_activas = request.user.reservas_pilates.filter(activa=True).count()
            
            # Eliminar usuario (esto eliminará automáticamente todas las reservas por CASCADE)
            request.user.delete()
            
            messages.success(
                request, 
                f'La cuenta de {username} ha sido eliminada exitosamente junto con {total_reservas} reservas. '
                '¡Esperamos verte de nuevo pronto!'
            )
            return redirect('gravity:home')
        else:
            messages.error(request, 'Error en la confirmación. Por favor, intenta nuevamente.')
    
    # Obtener información para mostrar en la confirmación
    reservas_activas = request.user.reservas_pilates.filter(activa=True).select_related('clase')
    reservas_historicas = request.user.reservas_pilates.filter(activa=False).select_related('clase')
    total_reservas = request.user.reservas_pilates.count()
    
    # Obtener información del perfil si existe
    try:
        user_profile = request.user.profile
    except:
        user_profile = None
    
    context = {
        'reservas_activas': reservas_activas,
        'reservas_historicas': reservas_historicas,
        'total_reservas': total_reservas,
        'user_profile': user_profile,
        'tiempo_en_estudio': user_profile.get_tiempo_en_estudio() if user_profile else None
    }
    return render(request, 'accounts/eliminar_cuenta.html', context)

class CustomPasswordResetView(PasswordResetView):
    """Vista personalizada para solicitar reset de contraseña"""
    template_name = 'accounts/password_reset_form.html'
    form_class = CustomPasswordResetForm
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')
    
    def form_valid(self, form):
        """Agregar mensaje de éxito personalizado"""
        messages.success(
            self.request,
            '¡Perfecto! Hemos enviado las instrucciones para restablecer tu contraseña '
            'a tu correo electrónico. Revisa tu bandeja de entrada y spam.'
        )
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Agregar mensaje de error personalizado"""
        messages.error(
            self.request,
            'Por favor corrige los errores en el formulario.'
        )
        return super().form_invalid(form)

class CustomPasswordResetDoneView(PasswordResetDoneView):
    """Vista que confirma que se envió el email de reset"""
    template_name = 'accounts/password_reset_done.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """Vista para confirmar el token y establecer nueva contraseña"""
    template_name = 'accounts/password_reset_confirm.html'
    form_class = CustomSetPasswordForm
    success_url = reverse_lazy('accounts:password_reset_complete')
    
    def form_valid(self, form):
        """Agregar mensaje de éxito personalizado"""
        messages.success(
            self.request,
            '¡Excelente! Tu contraseña ha sido cambiada exitosamente. '
            'Ya puedes iniciar sesión con tu nueva contraseña.'
        )
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Agregar mensaje de error personalizado"""
        if self.validlink:
            messages.error(
                self.request,
                'Por favor corrige los errores en el formulario.'
            )
        else:
            messages.error(
                self.request,
                'El enlace de restablecimiento es inválido o ha expirado. '
                'Por favor solicita un nuevo enlace.'
            )
        return super().form_invalid(form)

class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    """Vista que confirma que el reset fue exitoso"""
    template_name = 'accounts/password_reset_complete.html'