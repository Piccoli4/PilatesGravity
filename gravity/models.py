from django.db import models
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta

DIAS_SEMANA = [
    ('Lunes', 'Lunes'),
    ('Martes', 'Martes'),
    ('Miércoles', 'Miércoles'),
    ('Jueves', 'Jueves'),
    ('Viernes', 'Viernes'),
]

# Días de semana incluyendo sábado para clases especiales
DIAS_SEMANA_COMPLETOS = [
    ('Lunes', 'Lunes'),
    ('Martes', 'Martes'),
    ('Miércoles', 'Miércoles'),
    ('Jueves', 'Jueves'),
    ('Viernes', 'Viernes'),
    ('Sábado', 'Sábado'),
]

class Clase(models.Model):
    TIPO_CLASES = [
        ('Reformer', 'Pilates Reformer'),
        ('Cadillac', 'Pilates Cadillac'),
        ('Especial', 'Clase Especial'),
    ]
    
    # Opciones de direcciones/sedes
    DIRECCIONES = [
        ('sede_principal', 'Sede Principal - La Rioja 3044'),
        ('sede_2', 'Sede 2 - 9 de julio 3698'),
    ]

    tipo = models.CharField(
        max_length=20, 
        choices=TIPO_CLASES, 
        verbose_name="Tipo de clase"
    )
    
    # Campo para nombre personalizado de clases especiales
    nombre_personalizado = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Nombre personalizado",
        help_text="Solo para clases especiales. Ejemplo: 'Pilates Prenatal', 'Clase de Rehabilitación', etc."
    )
    
    # Nuevo campo para dirección/sede
    direccion = models.CharField(
        max_length=20,
        choices=DIRECCIONES,
        default='sede_principal',
        verbose_name="Sede",
        help_text="Ubicación donde se dicta la clase"
    )
    
    dia = models.CharField(
        max_length=10, 
        choices=DIAS_SEMANA_COMPLETOS,  # Ahora incluye sábado
        verbose_name="Día de la semana"
    )
    horario = models.TimeField(verbose_name="Horario")
    cupo_maximo = models.PositiveIntegerField(
        default=10, 
        verbose_name="Cupo máximo"
    )
    activa = models.BooleanField(
        default=True,
        verbose_name="Clase activa",
        help_text="Las clases inactivas no aparecerán disponibles para reservar"
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    fecha_modificacion = models.DateTimeField(
        auto_now=True,
        verbose_name="Última modificación"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que el horario esté en horario laboral (ejemplo: 6:00 AM - 10:00 PM)
        if self.horario:
            if self.horario.hour < 6 or self.horario.hour > 22:
                raise ValidationError({
                    'horario': 'El horario debe estar entre las 06:00 y las 22:00'
                })
        
        # Validar cupo mínimo
        if self.cupo_maximo < 1:
            raise ValidationError({
                'cupo_maximo': 'El cupo máximo debe ser al menos 1'
            })
            
        # Validar que las clases especiales tengan nombre personalizado
        if self.tipo == 'Especial' and not self.nombre_personalizado:
            raise ValidationError({
                'nombre_personalizado': 'Las clases especiales deben tener un nombre personalizado.'
            })
            
        # Validar que solo las clases especiales puedan ser los sábados
        if self.dia == 'Sábado' and self.tipo != 'Especial':
            raise ValidationError({
                'dia': 'Solo las clases especiales pueden programarse los sábados.'
            })
            
        # Validar que las clases no especiales no tengan nombre personalizado
        if self.tipo != 'Especial' and self.nombre_personalizado:
            raise ValidationError({
                'nombre_personalizado': 'Solo las clases especiales pueden tener nombre personalizado.'
            })

    def get_nombre_display(self):
        """Devuelve el nombre a mostrar según el tipo de clase"""
        if self.tipo == 'Especial' and self.nombre_personalizado:
            return self.nombre_personalizado
        return self.get_tipo_display()
        
    def get_direccion_corta(self):
        """Devuelve una versión corta de la dirección para mostrar"""
        direcciones_cortas = {
            'sede_principal': 'La Rioja 3044',
            'sede_2': '9 de julio 3698'
        }
        return direcciones_cortas.get(self.direccion, self.get_direccion_display())

    def cupos_disponibles(self):
        """Devuelve la cantidad de cupos disponibles en esta clase"""
        if not self.activa:
            return 0
        reservas_actuales = self.reserva_set.filter(activa=True).count()
        return max(0, self.cupo_maximo - reservas_actuales)

    def esta_completa(self):
        """Verifica si la clase está completa"""
        return self.cupos_disponibles() <= 0

    def get_porcentaje_ocupacion(self):
        """Devuelve el porcentaje de ocupación de la clase"""
        if self.cupo_maximo == 0:
            return 0
        reservas_actuales = self.reserva_set.filter(activa=True).count()
        return round((reservas_actuales / self.cupo_maximo) * 100)

    def get_reservas_activas(self):
        """Devuelve todas las reservas activas para esta clase"""
        return self.reserva_set.filter(activa=True).select_related('usuario')

    def puede_eliminarse(self):
        """Verifica si la clase puede eliminarse (no tiene reservas activas)"""
        return not self.reserva_set.filter(activa=True).exists()

    def __str__(self):
        estado = "Activa" if self.activa else "Inactiva"
        nombre = self.get_nombre_display()
        direccion_corta = self.get_direccion_corta()
        return f"{nombre} - {self.dia} {self.horario.strftime('%H:%M')} - {direccion_corta} ({self.cupos_disponibles()}/{self.cupo_maximo}) - {estado}"

    class Meta:
        verbose_name = "Clase"
        verbose_name_plural = "Clases"
        # Actualizar unique_together para incluir dirección
        unique_together = [
            ['tipo', 'dia', 'horario', 'direccion', 'nombre_personalizado']
        ]
        ordering = ['direccion', 'dia', 'horario', 'tipo']
        permissions = [
            ('can_manage_all_classes', 'Puede gestionar todas las clases'),
        ]

class Reserva(models.Model):
    """
    Reserva recurrente de un usuario a una clase específica.
    El usuario asiste todas las semanas al mismo día y horario hasta que cancela.
    """
    numero_reserva = models.CharField(
        max_length=10, 
        unique=True, 
        editable=False,
        verbose_name="Número de reserva"
    )
    usuario = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        verbose_name="Usuario",
        related_name='reservas_pilates'
    )
    clase = models.ForeignKey(
        Clase, 
        on_delete=models.CASCADE, 
        verbose_name="Clase"
    )
    fecha_reserva = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Fecha de reserva"
    )
    fecha_modificacion = models.DateTimeField(
        auto_now=True, 
        verbose_name="Última modificación"
    )
    activa = models.BooleanField(
        default=True, 
        verbose_name="Reserva activa"
    )
    notas = models.TextField(
        blank=True,
        verbose_name="Notas adicionales",
        help_text="Notas internas sobre la reserva"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que la clase esté activa
        if self.clase and not self.clase.activa:
            raise ValidationError({
                'clase': 'No se puede reservar una clase inactiva'
            })
        
        # Validar que no haya duplicados activos para el mismo usuario y clase
        if self.activa and self.usuario and self.clase:
            existing_reserva = Reserva.objects.filter(
                usuario=self.usuario,
                clase=self.clase,
                activa=True
            ).exclude(pk=self.pk)
            
            if existing_reserva.exists():
                raise ValidationError(
                    'Ya tienes una reserva activa para esta clase. '
                    'Cancela la reserva actual antes de crear una nueva.'
                )

    def save(self, *args, **kwargs):
        # Generar número de reserva único
        if not self.numero_reserva:
            self.numero_reserva = self.generar_numero_reserva()
        
        # Ejecutar validaciones
        self.full_clean()
        super().save(*args, **kwargs)

    def generar_numero_reserva(self):
        """Genera un número de reserva único"""
        while True:
            numero = get_random_string(8, allowed_chars='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            if not Reserva.objects.filter(numero_reserva=numero).exists():
                return numero

    def puede_modificarse(self):
        """
        Verifica si la reserva puede modificarse (12 horas de anticipación).
        Calcula basándose en el próximo día de clase.
        """
        if not self.activa:
            return False, "La reserva está cancelada"
        
        if not self.clase.activa:
            return False, "La clase ya no está disponible"
        
        # Obtener el día de la semana actual
        hoy = timezone.now()
        dias_semana = {
            'Lunes': 0, 'Martes': 1, 'Miércoles': 2, 'Jueves': 3, 'Viernes': 4, 'Sábado': 5
        }
        
        dia_clase = dias_semana.get(self.clase.dia)
        if dia_clase is None:
            return False, "Día de clase inválido"
        
        # Encontrar la próxima fecha de esta clase
        dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
        if dias_hasta_clase == 0:  # Es hoy
            proxima_clase = hoy.replace(
                hour=self.clase.horario.hour, 
                minute=self.clase.horario.minute, 
                second=0, 
                microsecond=0
            )
            if proxima_clase <= hoy:  # La clase ya pasó hoy
                dias_hasta_clase = 7
        
        if dias_hasta_clase == 0:
            proxima_fecha_clase = hoy.replace(
                hour=self.clase.horario.hour, 
                minute=self.clase.horario.minute, 
                second=0, 
                microsecond=0
            )
        else:
            proxima_fecha_clase = hoy + timedelta(days=dias_hasta_clase)
            proxima_fecha_clase = proxima_fecha_clase.replace(
                hour=self.clase.horario.hour, 
                minute=self.clase.horario.minute, 
                second=0, 
                microsecond=0
            )
        
        # Verificar si faltan más de 12 horas
        tiempo_limite = proxima_fecha_clase - timedelta(hours=12)
        
        if hoy >= tiempo_limite:
            horas_restantes = (proxima_fecha_clase - hoy).total_seconds() / 3600
            return False, f"Solo puedes modificar tu reserva con 12 horas de anticipación. Próxima clase en {horas_restantes:.1f} horas."
        
        return True, "Puedes modificar tu reserva"

    def get_proxima_clase_info(self):
        """Devuelve información sobre cuándo es la próxima clase"""
        hoy = timezone.now()
        dias_semana = {
            'Lunes': 0, 'Martes': 1, 'Miércoles': 2, 'Jueves': 3, 'Viernes': 4, 'Sábado': 5
        }
        
        dia_clase = dias_semana.get(self.clase.dia)
        if dia_clase is None:
            return "Día inválido"
        
        # Encontrar la próxima fecha de esta clase
        dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
        if dias_hasta_clase == 0:  # Es hoy
            proxima_clase = hoy.replace(
                hour=self.clase.horario.hour, 
                minute=self.clase.horario.minute, 
                second=0, 
                microsecond=0
            )
            if proxima_clase <= hoy:  # La clase ya pasó hoy
                dias_hasta_clase = 7
        
        if dias_hasta_clase == 0:
            return f"Hoy a las {self.clase.horario.strftime('%H:%M')} en {self.clase.get_direccion_corta()}"
        elif dias_hasta_clase == 1:
            return f"Mañana a las {self.clase.horario.strftime('%H:%M')} en {self.clase.get_direccion_corta()}"
        else:
            return f"En {dias_hasta_clase} días ({self.clase.dia} a las {self.clase.horario.strftime('%H:%M')} en {self.clase.get_direccion_corta()})"

    def get_nombre_completo_usuario(self):
        """Devuelve el nombre completo del usuario"""
        if self.usuario.first_name and self.usuario.last_name:
            return f"{self.usuario.first_name} {self.usuario.last_name}"
        return self.usuario.username

    def __str__(self):
        estado = "Activa" if self.activa else "Cancelada"
        direccion = self.clase.get_direccion_corta()
        return f"Reserva {self.numero_reserva} - {self.get_nombre_completo_usuario()} - {self.clase.get_nombre_display()} en {direccion} ({estado})"

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        unique_together = ['usuario', 'clase']  # Un usuario no puede tener múltiples reservas activas para la misma clase
        ordering = ['-fecha_reserva']
        permissions = [
            ('can_manage_all_reservas', 'Puede gestionar todas las reservas'),
            ('can_view_all_reservas', 'Puede ver todas las reservas'),
        ]

# Modelo Cliente se mantiene por compatibilidad con el sistema actual
# pero ahora será usado solo para casos donde no hay usuario autenticado
class Cliente(models.Model):
    """
    DEPRECATED: Este modelo se mantiene por compatibilidad.
    Se recomienda usar el modelo User de Django para nuevas implementaciones.
    """
    numero_cliente = models.CharField(max_length=10, unique=True, editable=False)
    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre",
        error_messages={
            'required': 'El nombre es obligatorio.',
            'max_length': 'El nombre no puede tener más de 100 caracteres.',
        }
    )
    apellido = models.CharField(
        max_length=100,
        verbose_name="Apellido",
        error_messages={
            'required': 'El apellido es obligatorio.',
            'max_length': 'El apellido no puede tener más de 100 caracteres.',
        }
    )
    email = models.EmailField(
        blank=True, 
        null=True,
        verbose_name="Correo electrónico",
        error_messages={
            'invalid': 'Ingresa una dirección de correo electrónico válida.',
        }
    )
    telefono = models.CharField(
        max_length=20,
        verbose_name="Teléfono",
        error_messages={
            'required': 'El teléfono es obligatorio.',
            'max_length': 'El teléfono no puede tener más de 20 caracteres.',
        }
    )
    codigo_verificacion = models.CharField(
        max_length=4,
        validators=[
            RegexValidator(
                r'^\d{4}$', 
                'El código debe tener exactamente 4 dígitos.'
            )
        ],
        help_text="Código de 4 dígitos que se usará para validar modificaciones o cancelaciones.",
        verbose_name="Código de verificación",
        error_messages={
            'required': 'El código de verificación es obligatorio.',
            'invalid': 'El código debe tener exactamente 4 dígitos.',
            'max_length': 'El código no puede tener más de 4 caracteres.',
        }
    )
    # Relación opcional con User para migrar datos existentes
    usuario = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Usuario asociado",
        help_text="Usuario de Django asociado a este cliente"
    )

    def save(self, *args, **kwargs):
        if not self.numero_cliente:
            self.numero_cliente = get_random_string(4, allowed_chars='0123456789')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} {self.apellido} - {self.numero_cliente}"

    class Meta:
        verbose_name = "Cliente (Legacy)"
        verbose_name_plural = "Clientes (Legacy)"

# Modelo Turno se mantiene por compatibilidad
class Turno(models.Model):
    """
    DEPRECATED: Este modelo se mantiene por compatibilidad.
    Las reservas ahora son recurrentes y no requieren fechas específicas.
    """
    numero_turno = models.CharField(max_length=10, unique=True, editable=False)
    cliente = models.ForeignKey(
        Cliente, 
        on_delete=models.CASCADE, 
        verbose_name="Cliente"
    )
    clase = models.ForeignKey(
        Clase, 
        on_delete=models.CASCADE, 
        verbose_name="Clase"
    )
    fecha = models.DateField(verbose_name="Fecha del turno")

    def save(self, *args, **kwargs):
        if not self.numero_turno:
            self.numero_turno = get_random_string(10)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Turno {self.numero_turno} - {self.cliente} - {self.fecha}"

    class Meta:
        verbose_name = "Turno (Legacy)"
        verbose_name_plural = "Turnos (Legacy)"