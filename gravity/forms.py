from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import Clase, Reserva, PlanUsuario, DIAS_SEMANA, DIAS_SEMANA_COMPLETOS
from datetime import datetime, timedelta, timezone
from accounts.models import UserProfile
from django.core.validators import RegexValidator
import re
from .models import PlanPago, EstadoPagoCliente, RegistroPago
from decimal import Decimal
from django.utils import timezone


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
        """Validaciones del formulario con verificación de planes"""
        cleaned_data = super().clean()
        
        if not self.user:
            raise ValidationError('Error interno: usuario no especificado.')
        
        tipo_clase = cleaned_data.get('tipo_clase')
        dia = cleaned_data.get('dia')
        horario = cleaned_data.get('horario')
        sede = cleaned_data.get('sede')
        
        if tipo_clase and dia and horario and sede:
            try:
                # Convertir horario string a time object
                horario_obj = datetime.strptime(horario, '%H:%M').time()
                horario_str = horario_obj.strftime('%H:%M')
                
                # Buscar la clase correspondiente
                try:
                    clase = Clase.objects.get(
                        tipo=tipo_clase,
                        dia=dia,
                        horario=horario_obj,
                        direccion=sede,
                        activa=True
                    )
                except Clase.DoesNotExist:
                    sede_display = dict(Clase.DIRECCIONES).get(sede, sede)
                    raise ValidationError(
                        f'No existe una clase de {tipo_clase} los {dia} a las {horario_str} '
                        f'en {sede_display} o la clase no está activa. Por favor verifica tu selección.'
                    )
                
                # **NUEVA VALIDACIÓN DE PLANES**
                puede_reservar, mensaje = Reserva.usuario_puede_reservar(self.user, clase)
                if not puede_reservar:
                    raise ValidationError(mensaje)
                
                # Verificar cupos disponibles
                if clase.cupos_disponibles() <= 0:
                    raise ValidationError(
                        f'La clase de {clase.get_nombre_display()} los {dia} a las {horario_str} '
                        f'en {clase.get_direccion_corta()} está completa. No hay cupos disponibles.'
                    )
                
                # Verificar duplicados
                if Reserva.objects.filter(
                    usuario=self.user, 
                    clase=clase, 
                    activa=True
                ).exists():
                    raise ValidationError(
                        'Ya tienes una reserva activa para esta clase. '
                        'No puedes reservar la misma clase dos veces.'
                    )
                
                # Agregar la clase al cleaned_data para usar en la vista
                cleaned_data['clase'] = clase
                
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
        """Validación de la nueva clase seleccionada con verificación de planes"""
        nueva_clase = self.cleaned_data.get('nueva_clase')
        
        if not nueva_clase:
            return nueva_clase
        
        if not self.reserva_actual or not self.user:
            raise ValidationError('Error interno en la validación.')
        
        # Verificar que el usuario sea el dueño de la reserva
        if self.reserva_actual.usuario != self.user:
            raise ValidationError('No tienes permisos para modificar esta reserva.')
        
        # **NUEVA VALIDACIÓN DE PLANES PARA MODIFICACIÓN**
        # Temporalmente "liberar" la reserva actual para la validación
        reserva_actual_activa = self.reserva_actual.activa
        self.reserva_actual.activa = False
        
        try:
            puede_reservar, mensaje = Reserva.usuario_puede_reservar(self.user, nueva_clase)
            if not puede_reservar:
                raise ValidationError(f"No puedes cambiar a esta clase: {mensaje}")
        finally:
            # Restaurar el estado original
            self.reserva_actual.activa = reserva_actual_activa
        
        # Verificar cupos en la nueva clase
        if nueva_clase.cupos_disponibles() <= 0:
            raise ValidationError(
                f'La clase seleccionada está completa. No hay cupos disponibles.'
            )
        
        # Verificar que no sea la misma clase actual
        if nueva_clase == self.reserva_actual.clase:
            raise ValidationError(
                'Debes seleccionar una clase diferente a la actual.'
            )
        
        return nueva_clase

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
    
# ==============================================================================
# FORMULARIOS PARA SISTEMA DE PAGOS
# ==============================================================================

class PlanPagoForm(forms.ModelForm):
    """
    Formulario para crear y editar planes de pago.
    """
    
    class Meta:
        model = PlanPago
        fields = ['nombre', 'clases_por_semana', 'precio_mensual', 'descripcion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Plan 1 clase semanal',
                'id': 'id_nombre'
            }),
            'clases_por_semana': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '10',
                'id': 'id_clases_por_semana'
            }),
            'precio_mensual': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0,00',
                'id': 'id_precio_mensual'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Descripción opcional del plan...',
                'id': 'id_descripcion'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_activo'
            })
        }
        error_messages = {
            'nombre': {
                'required': 'El nombre del plan es obligatorio.',
                'max_length': 'El nombre no puede exceder 100 caracteres.'
            },
            'clases_por_semana': {
                'required': 'Debes especificar la cantidad de clases por semana.',
                'invalid': 'Ingresa un número válido.',
                'min_value': 'Debe ser al menos 1 clase por semana.',
                'max_value': 'Máximo 10 clases por semana.'
            },
            'precio_mensual': {
                'required': 'El precio mensual es obligatorio.',
                'invalid': 'Ingresa un precio válido.',
                'min_value': 'El precio debe ser mayor a cero.'
            }
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Valores por defecto
        if not self.instance.pk:  # Solo para nuevos planes
            self.fields['activo'].initial = True
        
        # Labels personalizados
        self.fields['nombre'].label = "Nombre del Plan"
        self.fields['clases_por_semana'].label = "Clases por Semana"
        self.fields['precio_mensual'].label = "Precio Mensual ($)"
        self.fields['descripcion'].label = "Descripción"
        self.fields['activo'].label = "Plan activo"
        
        # Help text
        self.fields['clases_por_semana'].help_text = "Cantidad de clases que incluye por semana"
        self.fields['precio_mensual'].help_text = "Costo mensual del plan"
        self.fields['descripcion'].help_text = "Descripción opcional del plan"
        self.fields['activo'].help_text = "Si el plan está disponible para asignar"

    def clean_clases_por_semana(self):
        clases_por_semana = self.cleaned_data.get('clases_por_semana')
        
        if clases_por_semana:
            # Validar rango razonable
            if clases_por_semana < 1 or clases_por_semana > 7:
                raise ValidationError('La cantidad de clases debe estar entre 1 y 7 por semana.')
        
        return clases_por_semana

    def clean_precio_mensual(self):
        precio_mensual = self.cleaned_data.get('precio_mensual')
        
        if precio_mensual is not None:
            if precio_mensual <= 0:
                raise ValidationError('El precio debe ser mayor a cero.')
            
            # Validar que no sea un precio excesivamente alto
            if precio_mensual > Decimal('999999.99'):
                raise ValidationError('El precio es demasiado alto.')
        
        return precio_mensual

    def clean(self):
        cleaned_data = super().clean()
        clases_por_semana = cleaned_data.get('clases_por_semana')
        precio_mensual = cleaned_data.get('precio_mensual')
        
        # Validaciones básicas
        if clases_por_semana and clases_por_semana < 1:
            raise ValidationError({
                'clases_por_semana': 'Debe ser al menos 1 clase por semana.'
            })
        
        if precio_mensual and precio_mensual < 0:
            raise ValidationError({
                'precio_mensual': 'El precio no puede ser negativo.'
            })
        
        return cleaned_data

class RegistroPagoForm(forms.ModelForm):
    """
    Formulario para registrar un nuevo pago de un cliente.
    """
    
    class Meta:
        model = RegistroPago
        fields = ['monto', 'fecha_pago', 'tipo_pago', 'concepto', 'comprobante', 'observaciones']
        widgets = {
            'monto': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0,00',
                'id': 'id_monto'
            }),
            'fecha_pago': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_fecha_pago'
            }),
            'tipo_pago': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_tipo_pago'
            }),
            'concepto': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Pago mensual Enero 2025',
                'id': 'id_concepto'
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observaciones adicionales sobre este pago...',
                'id': 'id_observaciones'
            }),
            'comprobante': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número de recibo, transferencia, etc.',
                'id': 'id_comprobante'
            }),
            'estado': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_estado'
            })
        }
        error_messages = {
            'monto': {
                'required': 'El monto es obligatorio.',
                'invalid': 'Ingresa un monto válido.',
                'min_value': 'El monto debe ser mayor a cero.'
            },
            'fecha_pago': {
                'required': 'La fecha del pago es obligatoria.',
                'invalid': 'Ingresa una fecha válida.'
            },
            'concepto': {
                'required': 'El concepto del pago es obligatorio.',
                'max_length': 'El concepto no puede exceder 200 caracteres.'
            }
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Labels personalizados
        self.fields['monto'].label = "Monto Pagado ($)"
        self.fields['fecha_pago'].label = "Fecha del Pago"
        self.fields['tipo_pago'].label = "Tipo de Pago"
        self.fields['concepto'].label = "Concepto"
        self.fields['comprobante'].label = "N° Comprobante"
        self.fields['observaciones'].label = "Observaciones"
        
        # Help text
        self.fields['monto'].help_text = "Monto en pesos argentinos"
        self.fields['fecha_pago'].help_text = "Fecha en que se realizó el pago"
        self.fields['concepto'].help_text = "Descripción del pago"
        self.fields['comprobante'].help_text = "Opcional: número de recibo o transferencia"
        self.fields['observaciones'].help_text = "Opcional: notas adicionales"
        
        # Campo opcional
        self.fields['comprobante'].required = False
        self.fields['observaciones'].required = False

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto and monto <= 0:
            raise ValidationError('El monto debe ser mayor a cero.')
        return monto

    def clean_fecha_pago(self):
        fecha_pago = self.cleaned_data.get('fecha_pago')
        if fecha_pago and fecha_pago > timezone.now().date():
            raise ValidationError('La fecha del pago no puede ser futura.')
        return fecha_pago

    def clean_concepto(self):
        concepto = self.cleaned_data.get('concepto')
        
        if concepto:
            # Limpiar y capitalizar
            concepto = concepto.strip()
            if concepto:
                concepto = concepto[0].upper() + concepto[1:]
        
        return concepto

    def save(self, commit=True):
        """Override save para asignar el usuario que registra el pago"""
        instance = super().save(commit=False)
        
        # El usuario que registra se asignará desde la vista
        # aquí solo se prepara la instancia
        
        if commit:
            instance.save()
        
        return instance

class BuscarPagosForm(forms.Form):
    """
    Formulario para buscar y filtrar pagos en el panel de administración.
    """
    cliente = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buscar por nombre de cliente...',
            'id': 'id_cliente'
        }),
        label="Cliente"
    )
    
    ESTADOS_FILTRO = [
        ('', 'Todos los estados'),
        ('confirmado', 'Solo confirmados'),
        ('pendiente', 'Solo pendientes'),
        ('rechazado', 'Solo rechazados')
    ]
    
    estado = forms.ChoiceField(
        required=False,
        choices=ESTADOS_FILTRO,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_estado'
        }),
        label="Estado del pago"
    )
    
    tipo_pago = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos los tipos')] + RegistroPago.TIPOS_PAGO,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_tipo_pago'
        }),
        label="Tipo de pago"
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
    
    monto_minimo = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
            'placeholder': '0.00',
            'id': 'id_monto_minimo'
        }),
        label="Monto mínimo"
    )
    
    monto_maximo = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
            'placeholder': '0.00',
            'id': 'id_monto_maximo'
        }),
        label="Monto máximo"
    )
    
    def clean(self):
        cleaned_data = super().clean()
        fecha_desde = cleaned_data.get('fecha_desde')
        fecha_hasta = cleaned_data.get('fecha_hasta')
        monto_minimo = cleaned_data.get('monto_minimo')
        monto_maximo = cleaned_data.get('monto_maximo')
        
        # Validar que fecha_desde no sea mayor que fecha_hasta
        if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
            raise ValidationError({
                'fecha_hasta': 'La fecha final no puede ser anterior a la fecha inicial.'
            })
        
        # Validar que monto_minimo no sea mayor que monto_maximo
        if monto_minimo and monto_maximo and monto_minimo > monto_maximo:
            raise ValidationError({
                'monto_maximo': 'El monto máximo no puede ser menor que el monto mínimo.'
            })
        
        return cleaned_data

class EstadoPagoClienteForm(forms.ModelForm):
    """
    Formulario para editar manualmente el estado de pago de un cliente.
    """
    
    class Meta:
        model = EstadoPagoCliente
        fields = ['plan_actual', 'saldo_actual', 'observaciones', 'activo']
        widgets = {
            'plan_actual': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_plan_actual'
            }),
            'saldo_actual': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '0,00',
                'id': 'id_saldo_actual'
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Observaciones sobre el estado de pago del cliente...',
                'id': 'id_observaciones'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_activo'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Solo mostrar planes activos
        self.fields['plan_actual'].queryset = PlanPago.objects.filter(activo=True)
        self.fields['plan_actual'].empty_label = "Sin plan asignado"
        
        # Labels personalizados
        self.fields['plan_actual'].label = "Plan Asignado"
        self.fields['saldo_actual'].label = "Saldo Actual ($)"
        self.fields['observaciones'].label = "Observaciones"
        self.fields['activo'].label = "Cliente activo en sistema de pagos"
        
        # Help text
        self.fields['plan_actual'].help_text = "Plan asignado manualmente (o automático según reservas)"
        self.fields['saldo_actual'].help_text = "Saldo actual: positivo = crédito, negativo = deuda"
        self.fields['observaciones'].help_text = "Notas internas sobre el estado de pago"
        self.fields['activo'].help_text = "Si el cliente está activo en el sistema de pagos"
        
        # Campos opcionales
        self.fields['observaciones'].required = False

class EnviarEmailPagoForm(forms.Form):
    """
    Formulario para enviar emails relacionados con pagos.
    """
    TIPOS_EMAIL = [
        ('pago_recibido', 'Confirmación de pago recibido'),
        ('pago_atrasado', 'Recordatorio de pago atrasado'),
        ('estado_cuenta', 'Estado de cuenta'),
    ]
    
    tipo_email = forms.ChoiceField(
        choices=TIPOS_EMAIL,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_tipo_email'
        }),
        label="Tipo de email"
    )
    
    mensaje_personalizado = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 6,
            'placeholder': 'Mensaje adicional personalizado (opcional)...',
            'id': 'id_mensaje_personalizado'
        }),
        label="Mensaje personalizado",
        help_text="Mensaje adicional que se incluirá en el email"
    )
    
    incluir_detalle_pagos = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_incluir_detalle_pagos'
        }),
        label="Incluir detalle de pagos recientes"
    )
    
    incluir_estado_reservas = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_incluir_estado_reservas'
        }),
        label="Incluir estado de reservas actuales"
    )

    def __init__(self, cliente, *args, **kwargs):
        self.cliente = cliente
        super().__init__(*args, **kwargs)

class BuscarClientesPagosForm(forms.Form):
    """
    Formulario para buscar clientes en el sistema de pagos.
    """
    busqueda = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buscar por nombre, apellido, email o username...',
            'id': 'id_busqueda'
        }),
        label="Buscar Cliente"
    )
    
    FILTROS_ESTADO = [
        ('', 'Todos los estados'),
        ('al_dia', 'Al día'),
        ('con_credito', 'Con crédito'),
        ('con_deuda', 'Con deuda'),
        ('sin_plan', 'Sin plan asignado'),
        ('activos', 'Solo activos'),
        ('inactivos', 'Solo inactivos')
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
    
    plan_filtro = forms.ModelChoiceField(
        queryset=PlanPago.objects.filter(activo=True),
        required=False,
        empty_label="Todos los planes",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_plan_filtro'
        }),
        label="Filtrar por plan"
    )
    
    ordenar_por = forms.ChoiceField(
        required=False,
        choices=[
            ('nombre', 'Nombre'),
            ('saldo', 'Saldo'),
            ('ultimo_pago', 'Último pago'),
            ('fecha_creacion', 'Fecha de registro')
        ],
        initial='nombre',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_ordenar_por'
        }),
        label="Ordenar por"
    )

class FiltrosPagosForm(forms.Form):
    """
    Formulario para filtros en la vista principal de pagos.
    """
    ESTADOS_FILTRO = [
        ('', 'Todos los clientes'),
        ('al_dia', 'Al día'),
        ('debe', 'Con deuda'),
        ('sin_plan', 'Sin plan'),
    ]
    
    estado = forms.ChoiceField(
        choices=ESTADOS_FILTRO,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'filtro_estado'
        })
    )
    
    buscar = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre, apellido o usuario...',
            'id': 'buscar_cliente'
        })
    )
    
    mes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'type': 'month',
            'id': 'filtro_mes'
        })
    )
