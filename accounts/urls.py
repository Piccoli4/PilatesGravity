from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Autenticación
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.custom_logout_view, name='logout'),
    path('signup/', views.signup, name='signup'),
    
    # Perfil del usuario
    path('profile/', views.profile, name='profile'),
    path('profile/complete/', views.profile_complete, name='profile_complete'),
    path('profile/password/', views.cambiar_password, name='cambiar_password'),
    
    # Reservas del usuario
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),
    
    # Gestión de cuenta
    path('eliminar-cuenta/', views.eliminar_cuenta, name='eliminar_cuenta'),

    # Reset de contraseña
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset/complete/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]