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
    
    # Una sola vez (solo la próxima fecha) o todas las semanas (horario fijo)
    es_temporal = forms.BooleanField(required=False)

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
                    raise ValidationError(
                        'Ese horario ya no está disponible. Elegí otro de la grilla.'
                    )

                proxima_fecha = clase.proxima_fecha_reservable()
                es_temporal = cleaned_data.get('es_temporal')

                # Una sola vez que cubre una ausencia pendiente: se toma como recupero
                # y no usa clases del plan (reglas en gravity/recuperos.py)
                from .recuperos import EstadoRecuperos
                es_recupero = bool(es_temporal) and EstadoRecuperos(self.user).puede_recuperar_en(clase, proxima_fecha)
                cleaned_data['es_recupero'] = es_recupero

                # Plan activo y límite semanal (en la semana de la clase si es una sola vez)
                if not es_recupero:
                    puede_reservar, mensaje = Reserva.usuario_puede_reservar(
                        self.user, clase, fecha=proxima_fecha if es_temporal else None
                    )
                    if not puede_reservar:
                        raise ValidationError(mensaje)

                # Cupos: para una sola vez alcanza con que haya lugar en la próxima fecha;
                # como horario fijo además tiene que haber un lugar permanente (si no,
                # se sobrevende la clase desde la semana siguiente).
                descripcion = f'{clase.get_nombre_display()} del {dia.lower()} a las {horario_str}'

                if clase.cupos_disponibles(fecha=proxima_fecha) <= 0:
                    raise ValidationError(f'La clase de {descripcion} está completa esa semana.')
                if not es_temporal and clase.cupos_disponibles() <= 0:
                    raise ValidationError(
                        f'La clase de {descripcion} no tiene lugares fijos. '
                        f'Podés reservarla solo el {proxima_fecha.strftime("%d/%m")}.'
                    )

                # Verificar duplicados
                if Reserva.objects.filter(
                    usuario=self.user,
                    clase=clase,
                    activa=True
                ).exists():
                    raise ValidationError('Ya tenés una reserva para esta clase.')

                cleaned_data['proxima_fecha'] = proxima_fecha
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
    Crear y editar clases desde el panel. Además de las reglas del modelo (horario
    de 06 a 22, cupo, nombre de las especiales, sábados solo especiales) controla
    que no haya otra clase igual y que el cupo no quede por debajo de los alumnos
    que ya tienen ese horario fijo.
    """

    class Meta:
        model = Clase
        fields = ['tipo', 'nombre_personalizado', 'direccion', 'dia', 'horario', 'cupo_maximo', 'activa']
        widgets = {
            'tipo': forms.RadioSelect,
            'direccion': forms.RadioSelect,
            'dia': forms.RadioSelect,
            'nombre_personalizado': forms.TextInput(attrs={
                'class': 'pn-input', 'placeholder': 'Ej.: Pilates prenatal', 'maxlength': '100',
            }),
            'horario': forms.TimeInput(format='%H:%M', attrs={
                'class': 'pn-input', 'type': 'time', 'min': '06:00', 'max': '22:00', 'step': '300',
            }),
            'cupo_maximo': forms.NumberInput(attrs={
                'class': 'pn-input', 'min': '1', 'max': '30', 'inputmode': 'numeric',
            }),
        }
        labels = {
            'tipo': 'Tipo de clase',
            'nombre_personalizado': 'Nombre de la clase especial',
            'direccion': 'Sede',
            'dia': 'Día',
            'horario': 'Hora de inicio',
            'cupo_maximo': 'Cupo',
            'activa': 'Clase activa',
        }
        error_messages = {
            'tipo': {'required': 'Elegí el tipo de clase.'},
            'direccion': {'required': 'Elegí la sede.'},
            'dia': {'required': 'Elegí el día.'},
            'horario': {'required': 'Poné la hora de inicio.', 'invalid': 'Poné una hora válida (por ejemplo 18:30).'},
            'cupo_maximo': {'required': 'Poné el cupo.', 'invalid': 'El cupo tiene que ser un número.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo'].choices = Clase.TIPO_CLASES
        self.fields['direccion'].choices = Clase.DIRECCIONES
        self.fields['dia'].choices = DIAS_SEMANA_COMPLETOS
        self.fields['activa'].help_text = 'Si la pausás, los alumnos conservan su lugar pero no se aceptan reservas nuevas.'
        if not self.instance.pk:
            # Una clase nueva siempre arranca activa
            del self.fields['activa']

    def clean(self):
        datos = super().clean()
        tipo = datos.get('tipo')
        if tipo and tipo != 'Especial':
            datos['nombre_personalizado'] = None
        elif datos.get('nombre_personalizado'):
            datos['nombre_personalizado'] = datos['nombre_personalizado'].strip() or None

        dia, horario, direccion = datos.get('dia'), datos.get('horario'), datos.get('direccion')
        if tipo and dia and horario and direccion:
            iguales = Clase.objects.filter(tipo=tipo, dia=dia, horario=horario, direccion=direccion)
            if tipo == 'Especial':
                iguales = iguales.filter(nombre_personalizado__iexact=datos.get('nombre_personalizado') or '')
            if self.instance.pk:
                iguales = iguales.exclude(pk=self.instance.pk)
            if iguales.exists():
                otra = iguales.first()
                raise ValidationError(
                    f'Ya existe {otra.get_nombre_display()} los {dia} a las {horario:%H:%M} en '
                    f'{otra.get_direccion_corta()}{"" if otra.activa else " (pausada)"}.'
                )

        cupo = datos.get('cupo_maximo')
        if self.instance.pk and cupo is not None:
            fijos = self.instance.reserva_set.filter(activa=True, fecha_unica__isnull=True).count()
            if cupo < fijos:
                self.add_error('cupo_maximo', f'Esta clase tiene {fijos} alumnos con horario fijo: el cupo no puede ser menor.')
        return datos


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

        # El tipo arranca vacío: que lo elijan a conciencia (o lo complete un monto sugerido)
        self.fields['tipo_pago'].choices = [('', 'Elegí cómo pagó')] + list(RegistroPago.TIPOS_PAGO)
        self.fields['tipo_pago'].error_messages['required'] = 'Elegí el tipo de pago.'
        if not self.instance.pk:
            # El modelo trae 'efectivo' por defecto
            self.fields['tipo_pago'].initial = None
            self.initial.pop('tipo_pago', None)

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
        fields = ['plan_actual', 'observaciones', 'activo', 'puede_reservar']
        widgets = {
            'plan_actual': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_plan_actual'
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
            }),
            'puede_reservar': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_puede_reservar'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['plan_actual'].queryset = PlanPago.objects.filter(activo=True)
        self.fields['plan_actual'].empty_label = "Sin plan asignado"

        self.fields['plan_actual'].label = "Plan Asignado"
        self.fields['observaciones'].label = "Observaciones"
        self.fields['activo'].label = "Cliente activo en sistema de pagos"
        self.fields['puede_reservar'].label = "Puede reservar clases"

        self.fields['plan_actual'].help_text = "Plan asignado manualmente (o automático según reservas)"
        self.fields['observaciones'].help_text = "Notas internas sobre el estado de pago"
        self.fields['activo'].help_text = "Si el cliente está activo en el sistema de pagos"
        self.fields['puede_reservar'].help_text = "Desactivar para bloquear reservas por deuda vencida"

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

class AjusteDeudaForm(forms.Form):
    """
    Formulario para que superadmins registren un monto especial acordado con un cliente.
    """
    monto_ajustado = forms.DecimalField(
        label="¿Cuánto tiene que pagar por ese mes? ($)",
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'min': '0',
            'placeholder': '0',
        }),
        help_text="Poné $0 si ese mes no hay que cobrarlo. El estado de la cuota se recalcula "
                  "solo según lo que el cliente ya pagó."
    )
    motivo = forms.CharField(
        label="Motivo del ajuste",
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Acuerdo especial, descuento puntual, etc. (opcional)',
        }),
    )


class CorregirSaldoForm(forms.Form):
    """
    Corrección directa del saldo de un cliente: el admin dice cómo tiene que
    quedar la cuenta y el sistema calcula la diferencia y la registra.
    """
    SITUACIONES = [
        ('al_dia', 'Está al día (saldo $0)'),
        ('a_favor', 'Tiene saldo a favor'),
        ('debe', 'Debe plata'),
    ]

    situacion = forms.ChoiceField(
        choices=SITUACIONES,
        widget=forms.RadioSelect,
        label="¿Cómo tiene que quedar la cuenta?"
    )
    monto = forms.DecimalField(
        label="Monto ($)",
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': '0'})
    )
    motivo = forms.CharField(
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Ej: el cambio de plan de agosto le descontó $2.000 de más.',
        }),
        help_text="Queda registrado en el historial de la cuenta."
    )

    def clean(self):
        cleaned = super().clean()
        situacion = cleaned.get('situacion')
        monto = cleaned.get('monto')

        if situacion == 'al_dia':
            cleaned['saldo_objetivo'] = Decimal('0')
        else:
            if monto is None:
                raise ValidationError({'monto': 'Indicá el monto.'})
            if monto <= 0:
                raise ValidationError({'monto': 'El monto tiene que ser mayor a cero.'})
            cleaned['saldo_objetivo'] = monto if situacion == 'a_favor' else -monto

        return cleaned


class EditarPagoForm(forms.ModelForm):
    """
    Corrección de un pago ya registrado (típicamente un monto mal tipeado).
    """
    motivo = forms.CharField(
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Ej: se cargó $550.000 en vez de $55.000.',
        })
    )

    class Meta:
        model = RegistroPago
        fields = ['monto', 'fecha_pago', 'tipo_pago', 'concepto']
        widgets = {
            'monto': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'fecha_pago': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise ValidationError('El monto debe ser mayor a cero.')
        return monto

    def clean_fecha_pago(self):
        fecha_pago = self.cleaned_data.get('fecha_pago')
        if fecha_pago and fecha_pago > timezone.localtime(timezone.now()).date():
            raise ValidationError('La fecha del pago no puede ser futura.')
        return fecha_pago


class AnularPagoForm(forms.Form):
    """
    Anulación de un pago cargado por error. El pago no se borra: queda como
    rechazado y deja de contar en el saldo.
    """
    motivo = forms.CharField(
        label="Motivo de la anulación",
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Ej: el pago era de otra clienta.',
        })
    )


def estilo_panel(form):
    """
    Pone a los campos de un formulario las clases del panel (pn-input, pn-select,
    pn-textarea) y el formato de fecha que entiende <input type="date">.
    Sirve para los formularios viejos sin reescribir sus widgets.
    """
    for campo in form.fields.values():
        w = campo.widget
        if isinstance(w, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
            continue
        if isinstance(w, forms.Select):
            clase = 'pn-select'
        elif isinstance(w, forms.Textarea):
            clase = 'pn-textarea'
        else:
            clase = 'pn-input'
        w.attrs['class'] = clase
        if isinstance(w, forms.DateInput):
            w.format = '%Y-%m-%d'
            w.attrs['type'] = 'date'
    return form


# ==============================================================================
# ALUMNOS DESDE EL PANEL
# ==============================================================================

def normalizar_telefono(valor):
    """Saca espacios, guiones y paréntesis: el modelo acepta solo dígitos (y + al inicio)."""
    return re.sub(r'[\s\-().]', '', (valor or '').strip())


def _validar_telefono(telefono):
    if telefono and not re.fullmatch(r'\+?\d{9,15}', telefono):
        raise ValidationError('El teléfono tiene que tener entre 9 y 15 números (con característica, sin el 15).')


def _validar_email_libre(email, excluir_id=None):
    if not email:
        return
    otros = User.objects.filter(email__iexact=email)
    if excluir_id:
        otros = otros.exclude(pk=excluir_id)
    otro = otros.first()
    if otro:
        raise ValidationError(f'Ese email ya lo usa {otro.get_full_name() or otro.username}.', code='email_repetido')


class AlumnoNuevoForm(forms.Form):
    """Alta de un alumno desde el panel (la contraseña la elige el alumno con la invitación)."""
    nombre = forms.CharField(
        label='Nombre', max_length=150, error_messages={'required': 'Poné el nombre.'},
        widget=forms.TextInput(attrs={'class': 'pn-input', 'autocomplete': 'off', 'autofocus': True}))
    apellido = forms.CharField(
        label='Apellido', max_length=150, error_messages={'required': 'Poné el apellido.'},
        widget=forms.TextInput(attrs={'class': 'pn-input', 'autocomplete': 'off'}))
    telefono = forms.CharField(
        label='Teléfono (WhatsApp)', max_length=25,
        error_messages={'required': 'Poné el teléfono: es por donde se le avisa.'},
        widget=forms.TextInput(attrs={'class': 'pn-input', 'inputmode': 'tel', 'placeholder': '342 511 4448'}))
    email = forms.EmailField(
        label='Email', required=False, error_messages={'invalid': 'Ese email no parece válido.'},
        widget=forms.EmailInput(attrs={'class': 'pn-input', 'autocomplete': 'off', 'placeholder': 'nombre@email.com'}))
    notas = forms.CharField(
        label='Notas internas', required=False, max_length=500,
        widget=forms.Textarea(attrs={'class': 'pn-textarea', 'rows': 3,
                                     'placeholder': 'Cómo nos conoció, qué busca, lo que el equipo tenga que saber'}))

    def clean_nombre(self):
        return self.cleaned_data['nombre'].strip().title()

    def clean_apellido(self):
        return self.cleaned_data['apellido'].strip().title()

    def clean_telefono(self):
        telefono = normalizar_telefono(self.cleaned_data['telefono'])
        _validar_telefono(telefono)
        return telefono

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        _validar_email_libre(email)
        return email


class AlumnoDatosForm(forms.Form):
    """Editar los datos de un alumno desde su ficha (todo menos la contraseña)."""
    first_name = forms.CharField(label='Nombre', max_length=150, error_messages={'required': 'Poné el nombre.'},
                                 widget=forms.TextInput(attrs={'class': 'pn-input'}))
    last_name = forms.CharField(label='Apellido', max_length=150, error_messages={'required': 'Poné el apellido.'},
                                widget=forms.TextInput(attrs={'class': 'pn-input'}))
    telefono = forms.CharField(label='Teléfono (WhatsApp)', max_length=25, required=False,
                               widget=forms.TextInput(attrs={'class': 'pn-input', 'inputmode': 'tel'}))
    email = forms.EmailField(label='Email', required=False, error_messages={'invalid': 'Ese email no parece válido.'},
                             widget=forms.EmailInput(attrs={'class': 'pn-input'}))
    fecha_nacimiento = forms.DateField(
        label='Fecha de nacimiento', required=False, error_messages={'invalid': 'Poné una fecha válida.'},
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': 'pn-input', 'type': 'date'}))
    tiene_lesiones = forms.TypedChoiceField(
        label='¿Tiene alguna lesión o condición?', choices=[('no', 'No'), ('si', 'Sí')],
        coerce=lambda v: v == 'si', widget=forms.RadioSelect)
    descripcion_lesiones = forms.CharField(label='Qué tiene', required=False, max_length=500,
                                           widget=forms.Textarea(attrs={'class': 'pn-textarea', 'rows': 3}))
    fecha_primera_clase = forms.DateField(
        label='Fecha de primera clase', required=False, error_messages={'invalid': 'Poné una fecha válida.'},
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': 'pn-input', 'type': 'date'}))
    sede_primera_clase = forms.ChoiceField(
        label='Sede de primera clase', required=False,
        choices=[('', 'Sin dato'), ('sede_principal', 'La Rioja 3044'), ('sede_2', '9 de Julio 3696')],
        widget=forms.Select(attrs={'class': 'pn-select'}))

    def __init__(self, *args, usuario=None, **kwargs):
        self.usuario = usuario
        if usuario is not None and not args and 'data' not in kwargs:
            perfil = usuario.profile
            kwargs['initial'] = {
                'first_name': usuario.first_name, 'last_name': usuario.last_name, 'email': usuario.email,
                'telefono': perfil.telefono or '', 'fecha_nacimiento': perfil.fecha_nacimiento,
                'tiene_lesiones': 'si' if perfil.tiene_lesiones else 'no',
                'descripcion_lesiones': perfil.descripcion_lesiones,
                'fecha_primera_clase': perfil.fecha_primera_clase,
                'sede_primera_clase': perfil.sede_primera_clase or '',
            }
        super().__init__(*args, **kwargs)

    def clean_telefono(self):
        telefono = normalizar_telefono(self.cleaned_data.get('telefono'))
        _validar_telefono(telefono)
        return telefono or None

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        _validar_email_libre(email, excluir_id=self.usuario.pk if self.usuario else None)
        return email

    def clean(self):
        datos = super().clean()
        if datos.get('tiene_lesiones') and not (datos.get('descripcion_lesiones') or '').strip():
            self.add_error('descripcion_lesiones', 'Contá brevemente qué lesión o condición tiene.')
        if not datos.get('tiene_lesiones'):
            datos['descripcion_lesiones'] = ''
        hoy = timezone.localdate()
        if datos.get('fecha_primera_clase') and datos['fecha_primera_clase'] > hoy:
            self.add_error('fecha_primera_clase', 'La fecha de primera clase no puede ser futura.')
        nacimiento = datos.get('fecha_nacimiento')
        if nacimiento and (nacimiento > hoy or (hoy - nacimiento).days // 365 < 16):
            self.add_error('fecha_nacimiento', 'Revisá la fecha: tiene que tener al menos 16 años.')
        return datos

    def guardar(self):
        u, datos = self.usuario, self.cleaned_data
        u.first_name, u.last_name, u.email = datos['first_name'].strip(), datos['last_name'].strip(), datos['email']
        u.save(update_fields=['first_name', 'last_name', 'email'])
        perfil = u.profile
        perfil.telefono = datos['telefono']
        perfil.fecha_nacimiento = datos['fecha_nacimiento']
        perfil.tiene_lesiones = datos['tiene_lesiones']
        perfil.descripcion_lesiones = datos['descripcion_lesiones']
        perfil.fecha_primera_clase = datos['fecha_primera_clase']
        perfil.sede_primera_clase = datos['sede_primera_clase'] or None
        perfil.save()
        return u


def capitalizar_nombre(valor):
    """"maría de los ángeles" -> "María De Los Ángeles", sin tocar el resto ("McDonald" queda igual)."""
    return ' '.join(p[:1].upper() + p[1:] for p in (valor or '').split())


class IntegranteNuevoForm(forms.Form):
    """Alta de alguien del equipo (la contraseña la elige con la invitación)."""
    nombre = forms.CharField(
        label='Nombre', max_length=150, error_messages={'required': 'Poné el nombre.'},
        widget=forms.TextInput(attrs={'class': 'pn-input', 'autocomplete': 'off'}))
    apellido = forms.CharField(
        label='Apellido', max_length=150, error_messages={'required': 'Poné el apellido.'},
        widget=forms.TextInput(attrs={'class': 'pn-input', 'autocomplete': 'off'}))
    email = forms.EmailField(
        label='Email', required=False, error_messages={'invalid': 'Ese email no parece válido.'},
        widget=forms.EmailInput(attrs={'class': 'pn-input', 'autocomplete': 'off', 'placeholder': 'nombre@email.com'}))
    telefono = forms.CharField(
        label='Teléfono (WhatsApp)', max_length=25, required=False,
        widget=forms.TextInput(attrs={'class': 'pn-input', 'inputmode': 'tel', 'placeholder': '342 511 4448'}))

    def clean_nombre(self):
        return capitalizar_nombre(self.cleaned_data['nombre'])

    def clean_apellido(self):
        return capitalizar_nombre(self.cleaned_data['apellido'])

    def clean_telefono(self):
        telefono = normalizar_telefono(self.cleaned_data.get('telefono'))
        _validar_telefono(telefono)
        return telefono

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        _validar_email_libre(email, excluir_id=getattr(self, 'excluir_id', None))
        return email


class IntegranteDatosForm(IntegranteNuevoForm):
    """Editar nombre, email y teléfono de alguien del equipo."""

    def __init__(self, *args, usuario=None, **kwargs):
        self.excluir_id = usuario.pk if usuario else None
        if usuario is not None and not args and 'data' not in kwargs:
            perfil = getattr(usuario, 'profile', None)
            kwargs['initial'] = {
                'nombre': usuario.first_name, 'apellido': usuario.last_name, 'email': usuario.email,
                'telefono': (perfil.telefono if perfil else '') or '',
            }
        super().__init__(*args, **kwargs)

