from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import Clase, Reserva, DIAS_SEMANA, DIAS_SEMANA_COMPLETOS
from datetime import datetime
from accounts.models import UserProfile
from django.core.validators import RegexValidator
import re


class ReservaForm(forms.Form):
    """
    Formulario para crear una nueva reserva.
    Permite seleccionar tipo de clase, día, horario y sede.
    """
    tipo_clase = forms.ChoiceField(
        choices=[('', 'Selecciona el tipo de clase')],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gris-medio/30 rounded-lg focus:ring-2 focus:ring-principal/20 focus:border-principal transition-colors duration-200 bg-white',
            'id': 'id_tipo_clase'
        }),
        label="Tipo de Clase",
        error_messages={
            'required': 'Debes seleccionar un tipo de clase.',
            'invalid_choice': 'Selecciona un tipo de clase válido.'
        }
    )
    
    sede = forms.ChoiceField(
        choices=[('', 'Selecciona la sede')],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gris-medio/30 rounded-lg focus:ring-2 focus:ring-principal/20 focus:border-principal transition-colors duration-200 bg-white',
            'id': 'id_sede'
        }),
        label="Sede",
        error_messages={
            'required': 'Debes seleccionar una sede.',
            'invalid_choice': 'Selecciona una sede válida.'
        }
    )
    
    dia = forms.ChoiceField(
        choices=[('', 'Selecciona el día')],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gris-medio/30 rounded-lg focus:ring-2 focus:ring-principal/20 focus:border-principal transition-colors duration-200 bg-white',
            'id': 'id_dia'
        }),
        label="Día de la Semana",
        error_messages={
            'required': 'Debes seleccionar un día.',
            'invalid_choice': 'Selecciona un día válido.'
        }
    )
    
    horario = forms.ChoiceField(
        choices=[('', 'Selecciona el horario')],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gris-medio/30 rounded-lg focus:ring-2 focus:ring-principal/20 focus:border-principal transition-colors duration-200 bg-white',
            'id': 'id_horario'
        }),
        label="Horario",
        error_messages={
            'required': 'Debes seleccionar un horario.',
            'invalid_choice': 'Selecciona un horario válido.'
        }
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  # Usuario actual
        super().__init__(*args, **kwargs)
        
        # Obtener tipos únicos de clases activas disponibles
        tipos_disponibles = Clase.objects.filter(
            activa=True
        ).values_list('tipo', flat=True).distinct().order_by('tipo')
        
        self.fields['tipo_clase'].choices = [('', 'Selecciona el tipo de clase')] + [
            (tipo, dict(Clase.TIPO_CLASES).get(tipo, tipo)) for tipo in tipos_disponibles
        ]
        
        # Obtener sedes únicas disponibles
        sedes_disponibles = Clase.objects.filter(
            activa=True
        ).values('direccion').distinct().order_by('direccion')
        
        sedes_choices = [('', 'Selecciona la sede')]
        sedes_agregadas = set()
        
        for sede_dict in sedes_disponibles:
            sede = sede_dict['direccion']
            if sede not in sedes_agregadas:
                sede_display = dict(Clase.DIRECCIONES).get(sede, sede)
                sedes_choices.append((sede, sede_display))
                sedes_agregadas.add(sede)
        
        self.fields['sede'].choices = sedes_choices
        
        # Obtener días únicos disponibles
        dias_disponibles = Clase.objects.filter(
            activa=True
        ).values_list('dia', flat=True).distinct()
        
        # Ordenar días según el orden de la semana
        orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
        dias_ordenados = sorted(
            set(dias_disponibles), 
            key=lambda x: orden_dias.index(x) if x in orden_dias else 999
        )
        
        self.fields['dia'].choices = [('', 'Selecciona el día')] + [
            (dia, dia) for dia in dias_ordenados
        ]
        
        # Obtener horarios únicos disponibles (se filtrarán dinámicamente via AJAX)
        horarios_disponibles = Clase.objects.filter(
            activa=True
        ).values_list('horario', flat=True).distinct().order_by('horario')
        
        self.fields['horario'].choices = [('', 'Selecciona el horario')] + [
            (horario.strftime('%H:%M'), horario.strftime('%H:%M')) 
            for horario in horarios_disponibles
        ]
    
    def clean(self):
        cleaned_data = super().clean()
        tipo_clase = cleaned_data.get('tipo_clase')
        sede = cleaned_data.get('sede')
        dia = cleaned_data.get('dia')
        horario_str = cleaned_data.get('horario')
        
        if not self.user:
            raise ValidationError('Usuario no autenticado.')
        
        if tipo_clase and sede and dia and horario_str:
            try:
                # Convertir string de horario a time object
                horario_time = datetime.strptime(horario_str, '%H:%M').time()
                
                # Buscar la clase específica incluyendo la sede
                clase = Clase.objects.get(
                    tipo=tipo_clase, 
                    direccion=sede,
                    dia=dia, 
                    horario=horario_time,
                    activa=True
                )
                
                # Verificar si la clase tiene cupo disponible
                if clase.esta_completa():
                    sede_display = dict(Clase.DIRECCIONES).get(sede, sede)
                    raise ValidationError(
                        f'La clase de {clase.get_nombre_display()} los {dia} a las {horario_str} '
                        f'en {sede_display} está completa. Por favor selecciona otra opción.'
                    )
                
                # Verificar que el usuario no tenga ya una reserva activa para este día
                reserva_existente = Reserva.objects.filter(
                    usuario=self.user,
                    clase__dia=dia,
                    activa=True
                ).first()
                
                if reserva_existente:
                    raise ValidationError(
                        f'Ya tienes una reserva activa para los {dia} '
                        f'({reserva_existente.clase.get_nombre_display()} a las '
                        f'{reserva_existente.clase.horario.strftime("%H:%M")} en '
                        f'{reserva_existente.clase.get_direccion_corta()}). '
                        'Solo puedes tener una reserva por día.'
                    )
                
                # Verificar que el usuario no tenga ya una reserva para esta clase específica
                reserva_clase_existente = Reserva.objects.filter(
                    usuario=self.user,
                    clase=clase,
                    activa=True
                ).first()
                
                if reserva_clase_existente:
                    raise ValidationError(
                        f'Ya tienes una reserva activa para esta clase específica. '
                        'No puedes reservar la misma clase dos veces.'
                    )
                
                # Agregar la clase al cleaned_data para usar en la vista
                cleaned_data['clase'] = clase
                
            except Clase.DoesNotExist:
                sede_display = dict(Clase.DIRECCIONES).get(sede, sede)
                raise ValidationError(
                    f'No existe una clase de {tipo_clase} los {dia} a las {horario_str} '
                    f'en {sede_display} o la clase no está activa. Por favor verifica tu selección.'
                )
            except ValueError:
                raise ValidationError('Formato de horario inválido.')
        
        return cleaned_data

class ModificarReservaForm(forms.Form):
    """
    Formulario para modificar una reserva existente.
    Permite cambiar a una nueva clase disponible.
    """
    nueva_clase = forms.ModelChoiceField(
        queryset=Clase.objects.none(),  # Se definirá en __init__
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label="Nueva Clase",
        empty_label="Selecciona una nueva clase",
        error_messages={
            'required': 'Debes seleccionar una nueva clase.',
            'invalid_choice': 'Selecciona una clase válida.'
        }
    )
    
    def __init__(self, *args, **kwargs):
        self.reserva_actual = kwargs.pop('reserva_actual', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.reserva_actual and self.user:
            # Verificar que el usuario sea el dueño de la reserva
            if self.reserva_actual.usuario != self.user:
                # Si no es el dueño, no mostrar opciones
                self.fields['nueva_clase'].queryset = Clase.objects.none()
                return
            
            # Obtener clases disponibles excluyendo:
            # 1. La clase actual de la reserva
            # 2. Clases inactivas
            # 3. Clases completas
            # 4. Clases del mismo día si el usuario ya tiene otra reserva en ese día
            
            clases_base = Clase.objects.filter(
                activa=True
            ).exclude(
                id=self.reserva_actual.clase.id
            )
            
            # Filtrar clases que no estén completas
            clases_disponibles = []
            for clase in clases_base:
                # Verificar cupo disponible
                if clase.esta_completa():
                    continue
                
                # Verificar que no haya conflicto con otras reservas del usuario en el mismo día
                conflicto = Reserva.objects.filter(
                    usuario=self.user,
                    clase__dia=clase.dia,
                    activa=True
                ).exclude(
                    id=self.reserva_actual.id
                ).exists()
                
                if not conflicto:
                    clases_disponibles.append(clase.id)
            
            # Establecer el queryset con las clases disponibles
            self.fields['nueva_clase'].queryset = Clase.objects.filter(
                id__in=clases_disponibles
            ).order_by('direccion', 'tipo', 'dia', 'horario')
    
    def clean_nueva_clase(self):
        nueva_clase = self.cleaned_data.get('nueva_clase')
        
        if not nueva_clase:
            return nueva_clase
        
        # Verificar que la clase siga teniendo cupo disponible
        if nueva_clase.esta_completa():
            raise ValidationError(
                f'La clase de {nueva_clase.get_nombre_display()} los {nueva_clase.dia} '
                f'a las {nueva_clase.horario.strftime("%H:%M")} en {nueva_clase.get_direccion_corta()} '
                'ya no tiene cupos disponibles. Por favor selecciona otra clase.'
            )
        
        # Verificar que no haya conflicto con otras reservas activas del usuario
        if self.user and self.reserva_actual:
            conflicto = Reserva.objects.filter(
                usuario=self.user,
                clase__dia=nueva_clase.dia,
                activa=True
            ).exclude(
                id=self.reserva_actual.id
            ).exists()
            
            if conflicto:
                raise ValidationError(
                    f'Ya tienes una reserva activa para los {nueva_clase.dia}. '
                    'Solo puedes tener una reserva por día.'
                )
        
        return nueva_clase

class EliminarReservaForm(forms.Form):
    """
    Formulario de confirmación para eliminar una reserva.
    Incluye un checkbox de confirmación para evitar eliminaciones accidentales.
    """
    confirmar_eliminacion = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="Confirmo que deseo cancelar mi reserva",
        error_messages={
            'required': 'Debes confirmar que deseas cancelar tu reserva.'
        }
    )
    
    def __init__(self, *args, **kwargs):
        self.reserva = kwargs.pop('reserva', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.reserva:
            # Personalizar el label con información específica de la reserva incluyendo sede
            self.fields['confirmar_eliminacion'].label = (
                f"Confirmo que deseo cancelar mi reserva para la clase de "
                f"{self.reserva.clase.get_nombre_display()} los "
                f"{self.reserva.clase.dia} a las "
                f"{self.reserva.clase.horario.strftime('%H:%M')} en "
                f"{self.reserva.clase.get_direccion_corta()}"
            )
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Verificar que el usuario sea el dueño de la reserva
        if self.reserva and self.user:
            if self.reserva.usuario != self.user:
                raise ValidationError('No tienes permisos para cancelar esta reserva.')
            
            # Verificar que la reserva siga activa
            if not self.reserva.activa:
                raise ValidationError('Esta reserva ya está cancelada.')
            
            # Verificar restricciones de tiempo (12 horas de anticipación)
            puede_modificar, mensaje = self.reserva.puede_modificarse()
            if not puede_modificar:
                raise ValidationError(f'No puedes cancelar esta reserva: {mensaje}')
        
        return cleaned_data

class BuscarReservaForm(forms.Form):
    """
    Formulario para que los usuarios busquen sus reservas.
    Solo requiere el nombre de usuario para la búsqueda.
    """
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingresa tu nombre de usuario'
        }),
        label="Nombre de Usuario",
        help_text="Ingresa tu nombre de usuario para ver tus reservas activas",
        error_messages={
            'required': 'Debes ingresar tu nombre de usuario.',
            'max_length': 'El nombre de usuario no puede exceder 150 caracteres.'
        }
    )
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        
        if username:
            # Verificar que el usuario existe
            try:
                user = User.objects.get(username=username)
                # Almacenar el usuario para uso posterior
                self.cleaned_data['user'] = user
            except User.DoesNotExist:
                raise ValidationError('No existe un usuario con ese nombre.')
        
        return username
    
# ==============================================================================
# FORMULARIOS DEL ADMINISTRADOR
# ==============================================================================
# ==============================================================================
# FORMULARIOS PARA GESTIÓN DE CLASES
# ==============================================================================

class ClaseAdminForm(forms.ModelForm):
    """
    Formulario para crear y editar clases desde el panel de administración.
    Incluye lógica condicional para clases especiales y selección de sede.
    """
    
    class Meta:
        model = Clase
        fields = ['tipo', 'nombre_personalizado', 'direccion', 'dia', 'horario', 'cupo_maximo', 'activa']
        widgets = {
            'tipo': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_tipo',
                'onchange': 'toggleEspecialFields()'
            }),
            'nombre_personalizado': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_nombre_personalizado',
                'placeholder': 'Ej: Pilates Prenatal, Rehabilitación, etc.',
                'maxlength': '100'
            }),
            'direccion': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_direccion'
            }),
            'dia': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_dia'
            }),
            'horario': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time',
                'id': 'id_horario'
            }),
            'cupo_maximo': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '20',
                'id': 'id_cupo_maximo'
            }),
            'activa': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_activa'
            })
        }
        error_messages = {
            'tipo': {
                'required': 'Debes seleccionar un tipo de clase.',
                'invalid_choice': 'Selecciona un tipo válido.'
            },
            'nombre_personalizado': {
                'required': 'Las clases especiales deben tener un nombre personalizado.',
                'max_length': 'El nombre no puede exceder 100 caracteres.'
            },
            'direccion': {
                'required': 'Debes seleccionar una sede.',
                'invalid_choice': 'Selecciona una sede válida.'
            },
            'dia': {
                'required': 'Debes seleccionar un día de la semana.',
                'invalid_choice': 'Selecciona un día válido.'
            },
            'horario': {
                'required': 'Debes especificar un horario.',
                'invalid': 'Ingresa un horario válido (HH:MM).'
            },
            'cupo_maximo': {
                'required': 'Debes especificar el cupo máximo.',
                'invalid': 'Ingresa un número válido.',
                'min_value': 'El cupo mínimo es 1.',
                'max_value': 'El cupo máximo es 20.'
            }
        }

    def __init__(self, *args, **kwargs):
        self.instance_id = kwargs.get('instance').id if kwargs.get('instance') else None
        super().__init__(*args, **kwargs)
        
        # Personalizar choices para mejor UX
        self.fields['tipo'].empty_label = "Selecciona el tipo de clase"
        self.fields['direccion'].empty_label = "Selecciona la sede"
        
        # Configurar el campo de días dinámicamente
        self._setup_dia_choices()
        
        # Agregar help_text
        self.fields['nombre_personalizado'].help_text = "Solo para clases especiales (obligatorio si seleccionas 'Clase Especial')"
        self.fields['direccion'].help_text = "Sede donde se dictará la clase"
        self.fields['horario'].help_text = "Formato 24 horas (ej: 09:00, 18:30)"
        self.fields['cupo_maximo'].help_text = "Número máximo de personas (1-20)"
        self.fields['activa'].help_text = "Las clases inactivas no aparecen para reservar"
        
        # Si estamos editando una clase existente, configurar los campos apropiadamente
        if self.instance and self.instance.pk:
            self._configure_existing_instance()

    def _setup_dia_choices(self):
        """Configura las opciones de días según el tipo de clase"""
        # Por defecto, mostrar todos los días (se filtrará con JavaScript)
        self.fields['dia'].choices = [('', 'Selecciona el día')] + list(DIAS_SEMANA_COMPLETOS)

    def _configure_existing_instance(self):
        """Configura el formulario para una instancia existente"""
        if self.instance.tipo == 'Especial':
            # Asegurar que el nombre personalizado esté visible
            self.fields['nombre_personalizado'].required = True
        else:
            # Para clases no especiales, hacer el campo opcional
            self.fields['nombre_personalizado'].required = False

    def clean_tipo(self):
        tipo = self.cleaned_data.get('tipo')
        return tipo

    def clean_nombre_personalizado(self):
        nombre_personalizado = self.cleaned_data.get('nombre_personalizado')
        tipo = self.cleaned_data.get('tipo')
        
        # Si es clase especial, el nombre es obligatorio
        if tipo == 'Especial':
            if not nombre_personalizado or not nombre_personalizado.strip():
                raise ValidationError('Las clases especiales deben tener un nombre personalizado.')
            
            # Validar que el nombre no sea muy similar a los tipos existentes
            nombre_lower = nombre_personalizado.lower().strip()
            tipos_existentes = ['reformer', 'cadillac', 'pilates reformer', 'pilates cadillac']
            
            if nombre_lower in tipos_existentes:
                raise ValidationError(
                    'El nombre personalizado no puede ser igual a un tipo de clase existente. '
                    'Usa nombres como "Pilates Prenatal", "Rehabilitación", etc.'
                )
        else:
            # Si no es especial, no debe tener nombre personalizado
            if nombre_personalizado:
                raise ValidationError('Solo las clases especiales pueden tener nombre personalizado.')
        
        return nombre_personalizado.strip() if nombre_personalizado else None

    def clean_dia(self):
        dia = self.cleaned_data.get('dia')
        tipo = self.cleaned_data.get('tipo')
        
        # Validar que solo las clases especiales puedan ser los sábados
        if dia == 'Sábado' and tipo != 'Especial':
            raise ValidationError('Solo las clases especiales pueden programarse los sábados.')
        
        return dia

    def clean_horario(self):
        horario = self.cleaned_data.get('horario')
        
        if horario:
            # Validar que esté en horario laboral (6 AM - 10 PM)
            if horario.hour < 6 or horario.hour >= 22:
                raise ValidationError(
                    'El horario debe estar entre las 06:00 y las 22:00.'
                )
        
        return horario

    def clean_cupo_maximo(self):
        cupo_maximo = self.cleaned_data.get('cupo_maximo')
        
        if cupo_maximo:
            # Si estamos editando, verificar que el nuevo cupo no sea menor que las reservas actuales
            if self.instance and self.instance.pk:
                reservas_actuales = self.instance.reserva_set.filter(activa=True).count()
                if cupo_maximo < reservas_actuales:
                    raise ValidationError(
                        f'No puedes reducir el cupo a {cupo_maximo} porque ya hay '
                        f'{reservas_actuales} reservas activas. Primero cancela algunas reservas.'
                    )
        
        return cupo_maximo

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get('tipo')
        nombre_personalizado = cleaned_data.get('nombre_personalizado')
        direccion = cleaned_data.get('direccion')
        dia = cleaned_data.get('dia')
        horario = cleaned_data.get('horario')
        
        if tipo and direccion and dia and horario:
            # Construir la consulta base para verificar duplicados
            duplicate_filter = {
                'tipo': tipo,
                'direccion': direccion,
                'dia': dia,
                'horario': horario
            }
            
            # Para clases especiales, incluir el nombre personalizado en la verificación
            if tipo == 'Especial':
                duplicate_filter['nombre_personalizado'] = nombre_personalizado
            else:
                # Para clases normales, el nombre debe ser null
                duplicate_filter['nombre_personalizado__isnull'] = True
            
            # Verificar que no exista una clase igual (excluyendo la instancia actual si estamos editando)
            existing_clase = Clase.objects.filter(**duplicate_filter)
            
            if self.instance and self.instance.pk:
                existing_clase = existing_clase.exclude(pk=self.instance.pk)
            
            if existing_clase.exists():
                direccion_display = dict(Clase.DIRECCIONES).get(direccion, direccion)
                if tipo == 'Especial':
                    error_msg = (
                        f'Ya existe una clase especial "{nombre_personalizado}" '
                        f'los {dia} a las {horario.strftime("%H:%M")} en {direccion_display}.'
                    )
                else:
                    tipo_display = dict(Clase.TIPO_CLASES).get(tipo, tipo)
                    error_msg = (
                        f'Ya existe una clase de {tipo_display} '
                        f'los {dia} a las {horario.strftime("%H:%M")} en {direccion_display}.'
                    )
                raise ValidationError(error_msg)
        
        return cleaned_data

# ==============================================================================
# FORMULARIOS PARA GESTIÓN DE RESERVAS
# ==============================================================================

class CancelarReservaAdminForm(forms.Form):
    """
    Formulario para que el administrador cancele reservas con motivo.
    """
    MOTIVOS_CANCELACION = [
        ('', 'Selecciona un motivo'),
        ('solicitud_cliente', 'Solicitud del cliente'),
        ('problema_medico', 'Problema médico del cliente'),
        ('cambio_horario', 'Cambio de horario de clase'),
        ('clase_cancelada', 'Clase cancelada por el estudio'),
        ('falta_pago', 'Falta de pago'),
        ('incumplimiento', 'Incumplimiento de normas'),
        ('error_admin', 'Error administrativo'),
        ('otro', 'Otro motivo')
    ]
    
    motivo = forms.ChoiceField(
        choices=MOTIVOS_CANCELACION,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_motivo'
        }),
        label="Motivo de la cancelación",
        error_messages={
            'required': 'Debes seleccionar un motivo.',
            'invalid_choice': 'Selecciona un motivo válido.'
        }
    )
    
    motivo_detalle = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Descripción detallada del motivo (opcional)',
            'id': 'id_motivo_detalle'
        }),
        label="Detalle del motivo",
        max_length=500,
        help_text="Información adicional sobre la cancelación (máximo 500 caracteres)"
    )
    
    notificar_usuario = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_notificar_usuario'
        }),
        label="Notificar al usuario por email"
    )
    
    def __init__(self, *args, **kwargs):
        self.reserva = kwargs.pop('reserva', None)
        super().__init__(*args, **kwargs)
        
        if self.reserva:
            # Personalizar el help_text con información de la reserva
            self.fields['motivo'].help_text = (
                f"Cancelando reserva {self.reserva.numero_reserva} de "
                f"{self.reserva.get_nombre_completo_usuario()}"
            )

    def clean(self):
        cleaned_data = super().clean()
        motivo = cleaned_data.get('motivo')
        motivo_detalle = cleaned_data.get('motivo_detalle')
        
        # Si selecciona "otro", el detalle es obligatorio
        if motivo == 'otro' and not motivo_detalle:
            raise ValidationError({
                'motivo_detalle': 'Debes especificar el motivo cuando seleccionas "Otro motivo".'
            })
        
        return cleaned_data

# ==============================================================================
# FORMULARIOS PARA CLIENTES NO REGISTRADOS
# ==============================================================================

class ClienteNoRegistradoForm(forms.Form):
    """
    Formulario para agregar clientes directamente a una clase sin registro previo.
    """
    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: María',
            'id': 'id_nombre'
        }),
        label="Nombre",
        error_messages={
            'required': 'El nombre es obligatorio.',
            'max_length': 'El nombre no puede exceder 100 caracteres.'
        }
    )
    
    apellido = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: González',
            'id': 'id_apellido'
        }),
        label="Apellido",
        error_messages={
            'required': 'El apellido es obligatorio.',
            'max_length': 'El apellido no puede exceder 100 caracteres.'
        }
    )
    
    telefono = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: +54 11 1234-5678',
            'id': 'id_telefono'
        }),
        label="Teléfono",
        validators=[
            RegexValidator(
                regex=r'^[\+]?[0-9\s\-\(\)]{9,20}$',
                message='Ingresa un número de teléfono válido.'
            )
        ],
        error_messages={
            'required': 'El teléfono es obligatorio.',
            'max_length': 'El teléfono no puede exceder 20 caracteres.'
        },
        help_text="Número de contacto del cliente"
    )
    
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: maria@email.com',
            'id': 'id_email'
        }),
        label="Email (Opcional)",
        help_text="Para enviar confirmaciones y recordatorios",
        error_messages={
            'invalid': 'Ingresa una dirección de email válida.'
        }
    )
    
    clase = forms.ModelChoiceField(
        queryset=Clase.objects.none(),  # Se definirá en __init__
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_clase'
        }),
        label="Clase",
        empty_label="Selecciona una clase disponible",
        error_messages={
            'required': 'Debes seleccionar una clase.',
            'invalid_choice': 'Selecciona una clase válida.'
        }
    )
    
    notas = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Notas adicionales sobre este cliente (opcional)',
            'id': 'id_notas'
        }),
        label="Notas adicionales",
        max_length=500,
        help_text="Información que puede ser útil para las clases"
    )
    
    enviar_confirmacion = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_enviar_confirmacion'
        }),
        label="Enviar confirmación por email (si se proporcionó email)"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Solo mostrar clases activas con cupos disponibles, ordenadas por sede
        clases_disponibles = []
        for clase in Clase.objects.filter(activa=True).order_by('direccion', 'tipo', 'dia', 'horario'):
            if clase.cupos_disponibles() > 0:
                clases_disponibles.append(clase.id)
        
        self.fields['clase'].queryset = Clase.objects.filter(
            id__in=clases_disponibles
        ).order_by('direccion', 'tipo', 'dia', 'horario')

    def clean_nombre(self):
        nombre = self.cleaned_data.get('nombre')
        if nombre:
            # Limpiar y capitalizar el nombre
            nombre = ' '.join(word.capitalize() for word in nombre.strip().split())
            # Validar que solo contenga letras y espacios
            if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', nombre):
                raise ValidationError('El nombre solo puede contener letras y espacios.')
        return nombre

    def clean_apellido(self):
        apellido = self.cleaned_data.get('apellido')
        if apellido:
            # Limpiar y capitalizar el apellido
            apellido = ' '.join(word.capitalize() for word in apellido.strip().split())
            # Validar que solo contenga letras y espacios
            if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', apellido):
                raise ValidationError('El apellido solo puede contener letras y espacios.')
        return apellido

    def clean_clase(self):
        clase = self.cleaned_data.get('clase')
        
        if clase:
            # Verificar que la clase siga teniendo cupos disponibles
            if clase.cupos_disponibles() <= 0:
                raise ValidationError(
                    f'La clase de {clase.get_nombre_display()} los {clase.dia} '
                    f'a las {clase.horario.strftime("%H:%M")} en {clase.get_direccion_corta()} '
                    'ya no tiene cupos disponibles.'
                )
            
            # Verificar que la clase esté activa
            if not clase.activa:
                raise ValidationError('La clase seleccionada no está activa.')
        
        return clase

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        enviar_confirmacion = cleaned_data.get('enviar_confirmacion')
        
        # Si no hay email, no se puede enviar confirmación
        if enviar_confirmacion and not email:
            cleaned_data['enviar_confirmacion'] = False
        
        return cleaned_data

# ==============================================================================
# FORMULARIOS DE BÚSQUEDA Y FILTROS
# ==============================================================================

class BuscarUsuarioAdminForm(forms.Form):
    """
    Formulario para buscar usuarios en el panel de administración.
    """
    busqueda = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buscar por nombre, apellido, email o username...',
            'id': 'id_busqueda'
        }),
        label="Buscar Usuario"
    )
    
    FILTROS_ESTADO = [
        ('', 'Todos los estados'),
        ('activos', 'Solo usuarios activos'),
        ('inactivos', 'Solo usuarios inactivos'),
        ('staff', 'Solo administradores'),
        ('con_reservas', 'Con reservas activas'),
        ('sin_reservas', 'Sin reservas'),
        ('nuevos', 'Registrados esta semana')
    ]
    
    filtro = forms.ChoiceField(
        required=False,
        choices=FILTROS_ESTADO,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_filtro'
        }),
        label="Filtrar por estado"
    )

class BuscarReservasAdminForm(forms.Form):
    """
    Formulario para buscar y filtrar reservas en el panel de administración.
    """
    usuario = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buscar por nombre de usuario...',
            'id': 'id_usuario'
        }),
        label="Usuario"
    )
    
    ESTADOS_RESERVA = [
        ('', 'Todos los estados'),
        ('activas', 'Solo reservas activas'),
        ('canceladas', 'Solo reservas canceladas')
    ]
    
    estado = forms.ChoiceField(
        required=False,
        choices=ESTADOS_RESERVA,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_estado'
        }),
        label="Estado de reserva"
    )
    
    tipo_clase = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos los tipos')] + Clase.TIPO_CLASES,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_tipo_clase'
        }),
        label="Tipo de clase"
    )
    
    sede = forms.ChoiceField(
        required=False,
        choices=[('', 'Todas las sedes')] + Clase.DIRECCIONES,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_sede'
        }),
        label="Sede"
    )
    
    dia = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos los días')] + DIAS_SEMANA,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_dia'
        }),
        label="Día de la semana"
    )
    
    fecha_desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'id_fecha_desde'
        }),
        label="Desde"
    )
    
    fecha_hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'id_fecha_hasta'
        }),
        label="Hasta"
    )
    
    def clean(self):
        cleaned_data = super().clean()
        fecha_desde = cleaned_data.get('fecha_desde')
        fecha_hasta = cleaned_data.get('fecha_hasta')
        
        # Validar que fecha_desde no sea mayor que fecha_hasta
        if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
            raise ValidationError({
                'fecha_hasta': 'La fecha final no puede ser anterior a la fecha inicial.'
            })
        
        return cleaned_data

class BuscarClientesNoRegistradosForm(forms.Form):
    """
    Formulario para buscar clientes no registrados.
    """
    busqueda = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buscar por nombre, apellido, email, teléfono o número...',
            'id': 'id_busqueda'
        }),
        label="Buscar Cliente"
    )
    
    FILTROS_CLIENTE = [
        ('', 'Todos los clientes'),
        ('con_email', 'Con email registrado'),
        ('sin_email', 'Sin email'),
        ('con_turnos', 'Con turnos activos'),
        ('sin_turnos', 'Sin turnos'),
        ('vinculados', 'Vinculados a usuario'),
        ('no_vinculados', 'No vinculados')
    ]
    
    filtro = forms.ChoiceField(
        required=False,
        choices=FILTROS_CLIENTE,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_filtro'
        }),
        label="Filtrar por estado"
    )

# ==============================================================================
# FORMULARIOS PARA REPORTES
# ==============================================================================

class FiltrosReportesForm(forms.Form):
    """
    Formulario para filtrar reportes y estadísticas.
    """
    PERIODOS = [
        ('semana', 'Esta semana'),
        ('mes', 'Este mes'),
        ('trimestre', 'Este trimestre'),
        ('año', 'Este año'),
        ('personalizado', 'Período personalizado'),
        ('todo', 'Todo el tiempo')
    ]
    
    periodo = forms.ChoiceField(
        choices=PERIODOS,
        initial='mes',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_periodo'
        }),
        label="Período de análisis"
    )
    
    fecha_desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'id_fecha_desde'
        }),
        label="Fecha desde"
    )
    
    fecha_hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'id_fecha_hasta'
        }),
        label="Fecha hasta"
    )
    
    incluir_inactivas = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_incluir_inactivas'
        }),
        label="Incluir clases inactivas en estadísticas"
    )
    
    incluir_canceladas = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_incluir_canceladas'
        }),
        label="Incluir reservas canceladas en estadísticas"
    )
    
    def clean(self):
        cleaned_data = super().clean()
        periodo = cleaned_data.get('periodo')
        fecha_desde = cleaned_data.get('fecha_desde')
        fecha_hasta = cleaned_data.get('fecha_hasta')
        
        # Si el período es personalizado, las fechas son obligatorias
        if periodo == 'personalizado':
            if not fecha_desde:
                raise ValidationError({
                    'fecha_desde': 'La fecha de inicio es obligatoria para períodos personalizados.'
                })
            if not fecha_hasta:
                raise ValidationError({
                    'fecha_hasta': 'La fecha final es obligatoria para períodos personalizados.'
                })
        
        # Validar que fecha_desde no sea mayor que fecha_hasta
        if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
            raise ValidationError({
                'fecha_hasta': 'La fecha final no puede ser anterior a la fecha inicial.'
            })
        
        return cleaned_data