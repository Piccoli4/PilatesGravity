from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.models import User
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from .models import UserProfile, Testimonio
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.conf import settings
import re


def normalizar_telefono(telefono):
    """
    Limpia el teléfono y lo valida con la misma regla que UserProfile.telefono.
    Devuelve solo dígitos (con + opcional al inicio): si se guardara tal cual
    lo escribió el usuario, el full_clean() del perfil lo rechazaría y la
    request terminaría en error 500.
    """
    if not telefono:
        return telefono

    telefono_limpio = re.sub(r'[\s\-().]', '', telefono)

    if not re.fullmatch(r'\+?\d+', telefono_limpio):
        raise ValidationError('El teléfono solo puede contener números, espacios, guiones y paréntesis.')

    digitos = len(telefono_limpio.lstrip('+'))
    if digitos < 9:
        raise ValidationError('El teléfono debe tener al menos 9 dígitos.')
    if digitos > 15:
        raise ValidationError('El teléfono no puede tener más de 15 dígitos.')

    return telefono_limpio


class SignUpForm(UserCreationForm):
    """
    Formulario de registro extendido que incluye información adicional
    y crea automáticamente el perfil del usuario.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Correo electrónico'
        }),
        help_text="Correo electrónico para notificaciones y recuperación de cuenta"
    )
    first_name = forms.CharField(
        max_length=30, 
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre'
        })
    )
    last_name = forms.CharField(
        max_length=30, 
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Apellido'
        })
    )
    telefono = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Teléfono',
            'type': 'tel'
        }),
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Aplicar clases CSS a todos los campos
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            
        # Personalizar placeholders
        self.fields['username'].widget.attrs.update({
            'placeholder': 'Nombre de usuario',
            'help_text': 'Solo letras, números y @/./+/-/_ permitidos'
        })
        self.fields['password1'].widget.attrs['placeholder'] = 'Contraseña'
        self.fields['password2'].widget.attrs['placeholder'] = 'Confirmar contraseña'
        
        # Mejorar mensajes de ayuda
        self.fields['username'].help_text = 'Solo letras, números y @/./+/-/_ permitidos'

    def clean_email(self):
        """Validar que el email no esté ya registrado"""
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise ValidationError('Ya existe un usuario registrado con este correo electrónico.')
        return email

    def clean_telefono(self):
        """Validar formato del teléfono si se proporciona"""
        return normalizar_telefono(self.cleaned_data.get('telefono'))

    def clean_first_name(self):
        return self.cleaned_data.get('first_name', '').strip().title()

    def clean_last_name(self):
        return self.cleaned_data.get('last_name', '').strip().title()

    def save(self, commit=True):
        """Guardar usuario y crear perfil con información adicional"""
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        if commit:
            user.save()
            
            # Actualizar el perfil que se creó automáticamente con la señal
            profile = user.profile
            telefono = self.cleaned_data.get('telefono')
            if telefono:
                profile.telefono = telefono
                profile.save()
                
        return user

class ProfileUpdateForm(forms.Form):
    """
    Formulario para actualizar información básica del usuario.
    Actualiza tanto User como UserProfile.
    """
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre'
        }),
        label='Nombre'
    )
    
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Apellido'
        }),
        label='Apellido'
    )
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Correo electrónico'
        }),
        label='Email'
    )
    
    telefono = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Teléfono',
            'type': 'tel'
        }),
        label='Teléfono'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        
        # Inicializar campos con datos actuales del usuario
        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name
        self.fields['email'].initial = user.email
        
        # Inicializar teléfono desde el perfil - CORREGIDO
        try:
            if hasattr(user, 'profile') and user.profile:
                self.fields['telefono'].initial = user.profile.telefono or ''
            else:
                # Si no tiene perfil, crear uno
                profile, created = UserProfile.objects.get_or_create(user=user)
                self.fields['telefono'].initial = profile.telefono or ''
        except Exception:
            # En caso de cualquier error, usar cadena vacía
            self.fields['telefono'].initial = ''

    def clean_email(self):
        """Validar que el email no esté usado por otro usuario"""
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exclude(pk=self.user.pk).exists():
            raise ValidationError('Ya existe otro usuario registrado con este correo electrónico.')
        return email

    def clean_telefono(self):
        """Validar formato del teléfono si se proporciona"""
        return normalizar_telefono(self.cleaned_data.get('telefono'))

    def clean_first_name(self):
        return self.cleaned_data.get('first_name', '').strip().title()

    def clean_last_name(self):
        return self.cleaned_data.get('last_name', '').strip().title()

    def save(self):
        """Guardar usuario y actualizar perfil"""
        # Actualizar campos del User
        self.user.first_name = self.cleaned_data['first_name']
        self.user.last_name = self.cleaned_data['last_name']
        self.user.email = self.cleaned_data['email']
        self.user.save()
        
        # Actualizar o crear perfil y actualizar teléfono - CORREGIDO
        try:
            profile = self.user.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=self.user)
        
        profile.telefono = self.cleaned_data.get('telefono', '')
        profile.save()
        
        return self.user

class UserProfileForm(forms.ModelForm):
    """
    Ficha del alumno (/accounts/profile/complete/): datos personales, salud,
    foto y avisos. La fecha de primera clase la carga el estudio.
    """

    # Pregunta de salud con respuesta explícita (Sí/No)
    tiene_lesiones = forms.TypedChoiceField(
        choices=[('False', 'No tengo lesiones ni condiciones a tener en cuenta'),
                 ('True', 'Sí, tengo algo para contarles')],
        coerce=lambda valor: valor == 'True',
        widget=forms.RadioSelect,
        error_messages={'required': 'Elegí una opción para continuar.'},
    )

    quitar_avatar = forms.BooleanField(required=False)

    NIVEL_AYUDA = {
        'principiante': 'Es mi primera vez o hice pocas clases',
        'intermedio': 'Ya entreno hace un tiempo',
        'avanzado': 'Domino la técnica y busco más desafío',
        'instructor': 'Doy clases o me formé en Pilates',
    }
    SEDE_AYUDA = {
        'cualquiera': 'Me da igual',
        'sede_principal': 'La Rioja 3044',
        'sede_2': '9 de Julio 3696',
    }

    class Meta:
        model = UserProfile
        fields = (
            'telefono', 'fecha_nacimiento', 'nivel_experiencia',
            'tiene_lesiones', 'descripcion_lesiones',
            'avatar', 'acepta_recordatorios', 'sede_preferida',
        )
        widgets = {
            'telefono': forms.TextInput(attrs={
                'type': 'tel', 'class': 'pc-input', 'autocomplete': 'tel',
                'inputmode': 'tel', 'placeholder': 'Ej: 3425114448',
            }),
            'fecha_nacimiento': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date', 'class': 'pc-input', 'autocomplete': 'bday',
            }),
            'nivel_experiencia': forms.RadioSelect,
            'descripcion_lesiones': forms.Textarea(attrs={
                'rows': 4, 'class': 'pc-input', 'maxlength': '500',
                'placeholder': 'Ej: hernia de disco lumbar, operación de rodilla en 2024, embarazo de 20 semanas…',
            }),
            'avatar': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
            'sede_preferida': forms.RadioSelect,
        }
        error_messages = {
            'telefono': {'invalid': 'Ingresá solo números (entre 9 y 15), sin espacios ni guiones.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['descripcion_lesiones'].required = False
        self.fields['sede_preferida'].choices = [
            ('cualquiera', 'Cualquier sede'),
            ('sede_principal', 'Sede Central'),
            ('sede_2', 'Sede 2'),
        ]
        # La primera vez no damos por hecho que no tiene lesiones: tiene que elegir
        if self.instance and not self.instance.perfil_completado and not self.is_bound:
            self.initial['tiene_lesiones'] = None

    def opciones_nivel(self):
        """(valor, nombre, ayuda) para las tarjetas de nivel."""
        # 'Instructor/Profesional' no tiene dónde cortar y desborda la tarjeta
        return [(v, n.replace('/', ' / '), self.NIVEL_AYUDA.get(v, '')) for v, n in self.fields['nivel_experiencia'].choices]

    def opciones_sede(self):
        return [(v, n, self.SEDE_AYUDA.get(v, '')) for v, n in self.fields['sede_preferida'].choices]

    def clean(self):
        cleaned_data = super().clean()
        # Si dice que no tiene lesiones, no guardamos una descripción vieja.
        # (Si dice que sí y no describe nada, lo rechaza UserProfile.clean().)
        if cleaned_data.get('tiene_lesiones') is False:
            cleaned_data['descripcion_lesiones'] = ''
        return cleaned_data

    def clean_avatar(self):
        """Validar tamaño y formato de la foto nueva (la que ya estaba no se revisa)."""
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'content_type'):
            if avatar.size > 5 * 1024 * 1024:
                raise ValidationError('La imagen no puede superar los 5 MB.')
            if avatar.content_type not in ('image/jpeg', 'image/png', 'image/webp'):
                raise ValidationError('Subí una imagen JPG, PNG o WebP.')
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=False)
        nueva = self.files.get('avatar')
        if self.cleaned_data.get('quitar_avatar') and not nueva:
            if profile.avatar:
                profile.avatar.delete(save=False)
            profile.avatar = None
        if commit:
            profile.save()
        return profile

class CustomUserChangeForm(UserChangeForm):
    """
    Formulario personalizado para que los administradores puedan 
    editar usuarios desde el admin de Django.
    """
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Remover el campo de contraseña del formulario de edición
        if 'password' in self.fields:
            del self.fields['password']

class CambiarPasswordForm(forms.Form):
    """
    Cambio de contraseña del usuario actual. La contraseña nueva pasa por las mismas
    reglas que al crear la cuenta (AUTH_PASSWORD_VALIDATORS).
    """
    password_actual = forms.CharField(
        label='Contraseña actual',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'pc-input', 'autocomplete': 'current-password'}),
        error_messages={'required': 'Escribí tu contraseña actual.'},
    )
    password_nueva = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'pc-input', 'autocomplete': 'new-password'}),
        error_messages={'required': 'Escribí la nueva contraseña.'},
    )
    password_confirmacion = forms.CharField(
        label='Repetila',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'pc-input', 'autocomplete': 'new-password'}),
        error_messages={'required': 'Repetí la nueva contraseña.'},
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password_actual(self):
        password_actual = self.cleaned_data.get('password_actual')
        if not self.user.check_password(password_actual):
            raise ValidationError('La contraseña actual no es correcta.')
        return password_actual

    def clean_password_nueva(self):
        password_nueva = self.cleaned_data.get('password_nueva')
        if password_nueva:
            password_validation.validate_password(password_nueva, self.user)
        return password_nueva

    def clean(self):
        cleaned_data = super().clean()
        actual = cleaned_data.get('password_actual')
        nueva = cleaned_data.get('password_nueva')
        confirmacion = cleaned_data.get('password_confirmacion')

        if nueva and confirmacion and nueva != confirmacion:
            self.add_error('password_confirmacion', 'Las contraseñas no coinciden.')
        if actual and nueva and actual == nueva:
            self.add_error('password_nueva', 'La nueva contraseña tiene que ser distinta de la actual.')
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data['password_nueva'])
        self.user.save()

class EliminarCuentaForm(forms.Form):
    """Confirmación para eliminar la cuenta: contraseña y escribir ELIMINAR."""
    password = forms.CharField(
        label='Tu contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'pc-input', 'autocomplete': 'current-password'}),
        error_messages={'required': 'Escribí tu contraseña.'},
    )
    confirmacion = forms.CharField(
        label='Escribí ELIMINAR para confirmar',
        widget=forms.TextInput(attrs={'class': 'pc-input', 'autocomplete': 'off', 'autocapitalize': 'characters',
                                      'spellcheck': 'false', 'placeholder': 'ELIMINAR'}),
        error_messages={'required': 'Escribí ELIMINAR para confirmar.'},
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.user.check_password(password):
            raise ValidationError('La contraseña no es correcta.')
        return password

    def clean_confirmacion(self):
        texto = (self.cleaned_data.get('confirmacion') or '').strip().upper()
        if texto != 'ELIMINAR':
            raise ValidationError('Escribí ELIMINAR (tal cual) para confirmar.')
        return texto

class CustomPasswordResetForm(PasswordResetForm):
    """
    Pedir el enlace para crear una contraseña nueva. No avisa si el email no está
    registrado (no revela quién es alumno): Django solo envía el email si existe una
    cuenta activa con ese email.
    """
    email = forms.EmailField(
        max_length=254,
        label='Tu email',
        widget=forms.EmailInput(attrs={'placeholder': ' ', 'autocomplete': 'email', 'autofocus': True}),
        error_messages={'required': 'Escribí tu email.', 'invalid': 'Ese email no parece válido. Revisalo.'},
    )

    def get_users(self, email):
        """
        Cuentas activas con ese email, aunque todavía no tengan contraseña: los
        alumnos que crea el estudio la eligen con una invitación y, si se les vence,
        la crean desde acá.
        """
        from django.contrib.auth import get_user_model
        modelo = get_user_model()
        campo = modelo.get_email_field_name()
        return modelo._default_manager.filter(**{f'{campo}__iexact': email, 'is_active': True})

    def save(self, domain_override=None,
             subject_template_name='accounts/password_reset_subject.txt',
             email_template_name='accounts/password_reset_email.txt',
             use_https=False, token_generator=None,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):
        """
        Personalizar el envío del email con información adicional del estudio.
        """
        if extra_email_context is None:
            extra_email_context = {}
        
        # Agregar información del estudio al contexto del email
        try:
            from .models import ConfiguracionEstudio
            config = ConfiguracionEstudio.get_configuracion()
            extra_email_context.update({
                'studio_name': config.nombre_estudio,
                'studio_phone': config.telefono_contacto,
                'studio_email': config.email_contacto,
                'domain_url': settings.SITE_URL,
            })
        except Exception:
            # Si no se puede obtener la configuración, usar valores por defecto
            extra_email_context.update({
                'studio_name': 'Pilates Gravity',
                'studio_phone': '+54 342 511 4448',
                'studio_email': 'pilatesgravity@gmail.com',
                'domain_url': settings.SITE_URL,
            })

        return super().save(
            domain_override=domain_override,
            subject_template_name=subject_template_name,
            email_template_name=email_template_name,
            use_https=use_https,
            token_generator=token_generator,
            from_email=from_email,
            request=request,
            html_email_template_name='accounts/password_reset_email.html',
            extra_email_context=extra_email_context
        )

class CustomSetPasswordForm(SetPasswordForm):
    """Elegir la contraseña nueva desde el enlace del email (mismas reglas que el registro)."""
    new_password1 = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'placeholder': ' ', 'autocomplete': 'new-password', 'autofocus': True}),
        error_messages={'required': 'Escribí la nueva contraseña.'},
    )
    new_password2 = forms.CharField(
        label='Repetila',
        strip=False,
        widget=forms.PasswordInput(attrs={'placeholder': ' ', 'autocomplete': 'new-password'}),
        error_messages={'required': 'Repetí la nueva contraseña.'},
    )
    error_messages = {'password_mismatch': 'Las contraseñas no coinciden.'}

class TestimonioForm(forms.ModelForm):
    """
    Formulario para que los alumnos escriban o editen su testimonio.
    """

    class Meta:
        model = Testimonio
        fields = ['texto']
        widgets = {
            'texto': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-principal resize-none',
                'rows': 4,
                'placeholder': 'Contanos brevemente tu experiencia en Pilates Gravity...',
                'maxlength': '500',
                'id': 'id_texto_testimonio'
            })
        }
        error_messages = {
            'texto': {
                'required': 'Por favor escribí tu comentario antes de enviar.',
                'max_length': 'El comentario no puede superar los 500 caracteres.'
            }
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['texto'].label = "Tu comentario"
        self.fields['texto'].help_text = "Máximo 500 caracteres"

