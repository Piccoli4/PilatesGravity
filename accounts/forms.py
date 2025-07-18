from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import UserProfile
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User


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
        telefono = self.cleaned_data.get('telefono')
        if telefono:
            # Remover espacios y caracteres especiales comunes
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            
            # Validar que solo contenga números y posible + al inicio
            if not telefono_limpio.replace('+', '').isdigit():
                raise ValidationError('El teléfono solo puede contener números, espacios, guiones y paréntesis.')
            
            # Validar longitud
            if len(telefono_limpio.replace('+', '')) < 9:
                raise ValidationError('El teléfono debe tener al menos 9 dígitos.')
                
        return telefono

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
        telefono = self.cleaned_data.get('telefono')
        if telefono:
            # Remover espacios y caracteres especiales comunes
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            
            # Validar que solo contenga números y posible + al inicio
            if not telefono_limpio.replace('+', '').isdigit():
                raise ValidationError('El teléfono solo puede contener números, espacios, guiones y paréntesis.')
            
            # Validar longitud
            if len(telefono_limpio.replace('+', '')) < 9:
                raise ValidationError('El teléfono debe tener al menos 9 dígitos.')
                
        return telefono

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
    Formulario completo para el perfil del usuario.
    Incluye toda la información adicional del UserProfile.
    """
    
    class Meta:
        model = UserProfile
        fields = (
            'telefono', 'fecha_nacimiento', 'tiene_lesiones', 'descripcion_lesiones',
            'nivel_experiencia', 'acepta_marketing', 'acepta_recordatorios',
            'fecha_primera_clase', 'avatar'
        )
        widgets = {
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Teléfono',
                'type': 'tel'
            }),
            'fecha_nacimiento': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'tiene_lesiones': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'descripcion_lesiones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe brevemente cualquier lesión o condición médica relevante...'
            }),
            'nivel_experiencia': forms.Select(attrs={
                'class': 'form-control'
            }),
            'acepta_marketing': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'acepta_recordatorios': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'fecha_primera_clase': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'avatar': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Hacer algunos campos condicionales
        self.fields['descripcion_lesiones'].required = False
        
        # Agregar JavaScript condicional para lesiones
        self.fields['tiene_lesiones'].widget.attrs['onchange'] = '''
            const descripcion = document.querySelector('[name="descripcion_lesiones"]');
            if (this.checked) {
                descripcion.required = true;
                descripcion.parentElement.style.display = 'block';
            } else {
                descripcion.required = false;
                descripcion.value = '';
                descripcion.parentElement.style.display = 'none';
            }
        '''

    def clean(self):
        """Validaciones personalizadas del formulario"""
        cleaned_data = super().clean()
        tiene_lesiones = cleaned_data.get('tiene_lesiones')
        descripcion_lesiones = cleaned_data.get('descripcion_lesiones')
        
        # Validar que si tiene lesiones, debe describir
        if tiene_lesiones and not descripcion_lesiones:
            raise ValidationError({
                'descripcion_lesiones': 'Si tienes lesiones o condiciones médicas, por favor descríbelas brevemente.'
            })
        
        return cleaned_data

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
    Formulario para cambiar la contraseña del usuario actual.
    """
    password_actual = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contraseña actual'
        }),
        label='Contraseña actual'
    )
    password_nueva = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nueva contraseña'
        }),
        label='Nueva contraseña',
        help_text='La contraseña debe tener al menos 6 caracteres.'
    )
    password_confirmacion = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmar nueva contraseña'
        }),
        label='Confirmar nueva contraseña'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password_actual(self):
        """Validar que la contraseña actual sea correcta"""
        password_actual = self.cleaned_data.get('password_actual')
        if not self.user.check_password(password_actual):
            raise ValidationError('La contraseña actual es incorrecta.')
        return password_actual

    def clean(self):
        """Validar que las contraseñas nuevas coincidan"""
        cleaned_data = super().clean()
        password_nueva = cleaned_data.get('password_nueva')
        password_confirmacion = cleaned_data.get('password_confirmacion')

        if password_nueva and password_confirmacion:
            if password_nueva != password_confirmacion:
                raise ValidationError({
                    'password_confirmacion': 'Las contraseñas no coinciden.'
                })

        return cleaned_data

    def save(self):
        """Guardar la nueva contraseña"""
        password_nueva = self.cleaned_data['password_nueva']
        self.user.set_password(password_nueva)
        self.user.save()

class CustomPasswordResetForm(PasswordResetForm):
    """
    Formulario personalizado para solicitar reset de contraseña.
    """
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'login-input',
            'placeholder': 'Ingresa tu correo electrónico',
            'autocomplete': 'email'
        }),
        label='Correo electrónico'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Personalizar el campo email para que coincida con el diseño
        self.fields['email'].help_text = (
            'Te enviaremos un enlace para restablecer tu contraseña.'
        )

    def clean_email(self):
        """Validar que el email esté registrado en el sistema"""
        email = self.cleaned_data.get('email')
        if email:
            if not User.objects.filter(email=email).exists():
                raise ValidationError(
                    'No existe ningún usuario registrado con este correo electrónico.'
                )
        return email

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
            })
        except Exception:
            # Si no se puede obtener la configuración, usar valores por defecto
            extra_email_context.update({
                'studio_name': 'Pilates Gravity',
                'studio_phone': '+54 342 511 4448',
                'studio_email': 'pilatesgravity@gmail.com',
            })

        return super().save(
            domain_override=domain_override,
            subject_template_name=subject_template_name,
            email_template_name=email_template_name,
            use_https=use_https,
            token_generator=token_generator,
            from_email=from_email,
            request=request,
            html_email_template_name=html_email_template_name,
            extra_email_context=extra_email_context
        )

class CustomSetPasswordForm(SetPasswordForm):
    """
    Formulario personalizado para establecer nueva contraseña.
    """
    new_password1 = forms.CharField(
        label="Nueva contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'login-input',
            'placeholder': 'Ingresa tu nueva contraseña',
            'autocomplete': 'new-password'
        }),
        help_text='La contraseña debe tener al menos 6 caracteres.'
    )
    
    new_password2 = forms.CharField(
        label="Confirmar nueva contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'login-input',
            'placeholder': 'Confirma tu nueva contraseña',
            'autocomplete': 'new-password'
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Personalizar mensajes de ayuda
        self.fields['new_password1'].help_text = (
            'Tu contraseña debe tener al menos 6 caracteres y te recomendamos que no sea '
            'demasiado común o similar a tu información personal.'
        )

    def clean_new_password2(self):
        """Validar que las contraseñas coincidan con mensaje personalizado"""
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        
        if password1 and password2:
            if password1 != password2:
                raise ValidationError('Las contraseñas no coinciden.')
        
        return password2