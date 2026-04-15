from django.db import models
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum
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
        ('sede_2', 'Sede 2 - 9 de julio 3696'),
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
            'sede_2': '9 de julio 3696'
        }
        return direcciones_cortas.get(self.direccion, self.get_direccion_display())

    def cupos_disponibles(self, fecha=None):
        """
        Devuelve cupos disponibles.
        Sin fecha: solo cuenta reservas permanentes (para display general).
        Con fecha: cuenta permanentes - ausencias_de_ese_día + reservas_de_fecha_única_de_ese_día.
        """
        if not self.activa:
            return 0

        # Solo las permanentes siempre ocupan cupo
        reservas_permanentes = self.reserva_set.filter(
            activa=True,
            fecha_unica__isnull=True
        ).count()

        if fecha:
            ausencias_del_dia = AusenciaTemporal.objects.filter(
                reserva__clase=self,
                reserva__activa=True,
                reserva__fecha_unica__isnull=True,
                fecha=fecha
            ).count()
            reservas_fecha = self.reserva_set.filter(
                activa=True,
                fecha_unica=fecha
            ).count()
            total = reservas_permanentes - ausencias_del_dia + reservas_fecha
        else:
            total = reservas_permanentes

        return max(0, self.cupo_maximo - total)

    def get_cupo_temporal_semana(self):
        """
        Retorna {fecha, cupos, fecha_str} si en los próximos 10 días hay un
        cupo temporal disponible por ausencia. Retorna None si no hay ninguno.
        """
        hoy = timezone.now().date()
        fin_ventana = hoy + timedelta(days=10)

        dias_map = {
            'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
            'Jueves': 3, 'Viernes': 4, 'Sábado': 5
        }
        dia_objetivo = dias_map.get(self.dia)
        if dia_objetivo is None:
            return None

        # Próxima ocurrencia de este día (nunca hoy mismo, siempre hacia adelante)
        dias_hasta = (dia_objetivo - hoy.weekday()) % 7
        if dias_hasta == 0:
            dias_hasta = 7

        fecha_clase = hoy + timedelta(days=dias_hasta)

        if fecha_clase > fin_ventana:
            return None

        # Solo aplica si la clase está permanentemente llena
        if self.cupos_disponibles() > 0:
            return None

        cupos_fecha = self.cupos_disponibles(fecha=fecha_clase)
        if cupos_fecha > 0:
            return {
                'fecha': fecha_clase,
                'cupos': cupos_fecha,
                'fecha_str': fecha_clase.strftime('%Y-%m-%d'),
            }
        return None

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
    es_recupero = models.BooleanField(
        default=False,
        verbose_name="Es recupero",
        help_text="Reserva de recupero por ausencia propia. No cuenta para el límite semanal del plan."
    )
    fecha_unica = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha única",
        help_text="Para recuperos y cupos temporales. Se cancela automáticamente al día siguiente de esta fecha."
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que la clase esté activa
        if self.clase and not self.clase.activa:
            raise ValidationError({
                'clase': 'No se puede reservar una clase inactiva'
            })
        
        # Validar duplicados (las reservas de fecha única se permiten mientras no choquen con otra del mismo día o con una permanente)
        if self.activa and self.usuario and self.clase:
            if self.fecha_unica:
                tiene_permanente = Reserva.objects.filter(
                    usuario=self.usuario,
                    clase=self.clase,
                    activa=True,
                    fecha_unica__isnull=True
                ).exclude(pk=self.pk).exists()
                tiene_misma_fecha = Reserva.objects.filter(
                    usuario=self.usuario,
                    clase=self.clase,
                    activa=True,
                    fecha_unica=self.fecha_unica
                ).exclude(pk=self.pk).exists()
                if tiene_permanente or tiene_misma_fecha:
                    raise ValidationError(
                        'Ya tienes una reserva activa para esta clase en esa fecha. '
                        'Cancela la reserva actual antes de crear una nueva.'
                    )
            else:
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
        Verifica si la reserva puede modificarse (3 horas de anticipación).
        Calcula basándose en el próximo día de clase.
        """
        if not self.activa:
            return False, "La reserva está cancelada"
        
        if not self.clase.activa:
            return False, "La clase ya no está disponible"
        
        # Obtener el día de la semana actual
        hoy = timezone.localtime(timezone.now())
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
        
        # Verificar si faltan más de 3 horas
        tiempo_limite = proxima_fecha_clase - timedelta(hours=3)
        
        if hoy >= tiempo_limite:
            horas_restantes = (proxima_fecha_clase - hoy).total_seconds() / 3600
            return False, f"Solo puedes modificar tu reserva con 3 horas de anticipación. Próxima clase en {horas_restantes:.1f} horas."
        
        return True, "Puedes modificar tu reserva"

    def get_proxima_clase_info(self):
        """Devuelve información sobre cuándo es la próxima clase"""
        hoy = timezone.localtime(timezone.now())
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

    def get_proxima_fecha(self):
        """Devuelve la fecha (date) de la próxima ocurrencia de esta clase."""
        hoy = timezone.localtime(timezone.now())
        dias_semana = {
            'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
            'Jueves': 3, 'Viernes': 4, 'Sábado': 5
        }
        dia_clase = dias_semana.get(self.clase.dia)
        if dia_clase is None:
            return None

        dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
        if dias_hasta_clase == 0:
            proxima_clase_hoy = hoy.replace(
                hour=self.clase.horario.hour,
                minute=self.clase.horario.minute,
                second=0, microsecond=0
            )
            if proxima_clase_hoy <= hoy:
                dias_hasta_clase = 7

        proxima_fecha = (hoy + timedelta(days=dias_hasta_clase)).date()
        return proxima_fecha

    def tiene_ausencia_proxima(self):
        """Verifica si ya existe una ausencia temporal registrada para la próxima clase."""
        proxima = self.get_proxima_fecha()
        if not proxima:
            return False
        return self.ausencias_temporales.filter(fecha=proxima).exists()

    def get_nombre_completo_usuario(self):
        """Devuelve el nombre completo del usuario"""
        if self.usuario.first_name and self.usuario.last_name:
            return f"{self.usuario.first_name} {self.usuario.last_name}"
        return self.usuario.username

    def __str__(self):
        estado = "Activa" if self.activa else "Cancelada"
        direccion = self.clase.get_direccion_corta()
        return f"Reserva {self.numero_reserva} - {self.get_nombre_completo_usuario()} - {self.clase.get_nombre_display()} en {direccion} ({estado})"

    @staticmethod
    def contar_reservas_usuario_semana(usuario, fecha_inicio_semana=None):
        """
        Cuenta las reservas activas de un usuario en una semana específica
        """
        if fecha_inicio_semana is None:
            hoy = timezone.now().date()
            fecha_inicio_semana = hoy - timedelta(days=hoy.weekday())

        fecha_fin_semana = fecha_inicio_semana + timedelta(days=5)
        dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

        # Reservas permanentes (siempre cuentan contra el límite)
        permanentes = Reserva.objects.filter(
            usuario=usuario,
            activa=True,
            clase__dia__in=dias_semana,
            fecha_unica__isnull=True
        ).count()

        # Cupos temporales tomados esta semana (cuentan, los recuperos NO)
        temporales = Reserva.objects.filter(
            usuario=usuario,
            activa=True,
            es_recupero=False,
            fecha_unica__isnull=False,
            fecha_unica__gte=fecha_inicio_semana,
            fecha_unica__lte=fecha_fin_semana
        ).count()

        return permanentes + temporales

    @staticmethod
    def usuario_puede_reservar(usuario, nueva_clase=None):
        """
        Verifica si un usuario puede hacer una nueva reserva según sus planes
        """
        # Verificar si tiene planes activos
        clases_disponibles, planes = PlanUsuario.obtener_clases_disponibles_usuario(usuario)
        
        if clases_disponibles == 0:
            return False, "No tienes un plan activo. Debes seleccionar un plan antes de reservar."
        
        # Contar reservas actuales de la semana
        reservas_actuales = Reserva.contar_reservas_usuario_semana(usuario)
        
        # Si ya tiene el máximo de reservas
        if reservas_actuales >= clases_disponibles:
            return False, f"Ya tienes {reservas_actuales} reservas esta semana. Tu plan permite máximo {clases_disponibles} clases semanales."
        
        # Si es una modificación, verificar que no sea la misma clase
        if nueva_clase:
            reserva_existente = Reserva.objects.filter(
                usuario=usuario,
                clase=nueva_clase,
                activa=True
            ).exists()
            
            if reserva_existente:
                return False, "Ya tienes una reserva para esta clase."
        
        return True, f"Puedes reservar. Tienes {clases_disponibles - reservas_actuales} clases disponibles esta semana."

        class Meta:
            verbose_name = "Reserva"
            verbose_name_plural = "Reservas"
            constraints = [
                models.UniqueConstraint(
                    fields=['usuario', 'clase'],
                    condition=models.Q(activa=True),
                    name='unique_active_reservation_per_user_class'
                )
            ]
            ordering = ['-fecha_reserva']
            permissions = [
                ('can_manage_all_reservas', 'Puede gestionar todas las reservas'),
                ('can_view_all_reservas', 'Puede ver todas las reservas'),
            ]

    @staticmethod
    def usuario_puede_hacer_recupero(usuario):
        hoy = timezone.now().date()

        # Ausencias vigentes: cuya ventana de recupero no venció (fecha + 6 días >= hoy)
        ausencias = AusenciaTemporal.objects.filter(
            reserva__usuario=usuario,
            reserva__activa=True,
            reserva__fecha_unica__isnull=True,
            fecha__gte=hoy - timedelta(days=6),
        ).select_related('reserva__clase')

        n_ausencias = ausencias.count()
        if n_ausencias == 0:
            return False, 0, ausencias

        # Recuperos ya reservados activos a partir de hoy
        recuperos_usados = Reserva.objects.filter(
            usuario=usuario,
            activa=True,
            es_recupero=True,
            fecha_unica__gte=hoy,
        ).count()

        disponibles = n_ausencias - recuperos_usados
        return disponibles > 0, disponibles, ausencias

class AusenciaTemporal(models.Model):
    """
    Registra una ausencia puntual de un cliente a su clase recurrente.
    La reserva sigue activa, pero ese día en particular el cupo queda libre.
    """
    reserva = models.ForeignKey(
        Reserva,
        on_delete=models.CASCADE,
        related_name='ausencias_temporales',
        verbose_name="Reserva"
    )
    fecha = models.DateField(
        verbose_name="Fecha de ausencia",
        help_text="Fecha específica en que el cliente no asistirá"
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Registrado el"
    )
    notificacion_vencimiento_vista = models.BooleanField(
        default=False,
        verbose_name="Notificación de vencimiento vista",
        help_text="True cuando el usuario ya vio el aviso de que perdió el plazo de recupero"
    )

    class Meta:
        verbose_name = "Ausencia Temporal"
        verbose_name_plural = "Ausencias Temporales"
        unique_together = ['reserva', 'fecha']
        ordering = ['-fecha']

    @property
    def fecha_limite_recupero(self):
        """
        Fecha límite para reservar un recupero por esta ausencia.
        Es el día anterior a la siguiente clase (fecha_ausencia + 6 días,
        ya que la clase repite semanalmente a los 7 días).
        """
        return self.fecha + timedelta(days=6)

    @property
    def recupero_vencido(self):
        """True si ya pasó la fecha límite para hacer el recupero."""
        return timezone.now().date() > self.fecha_limite_recupero

    def __str__(self):
        return (
            f"Ausencia de {self.reserva.get_nombre_completo_usuario()} "
            f"— {self.reserva.clase.get_nombre_display()} "
            f"el {self.fecha.strftime('%d/%m/%Y')}"
        )

class NotificacionCancelacion(models.Model):
    """
    Registra cada cancelación (permanente o temporal) para mostrar
    a los administradores en el panel de control.
    """
    TIPOS = [
        ('permanente', 'Cancelación permanente'),
        ('temporal', 'Ausencia temporal'),
    ]

    reserva = models.ForeignKey(
        Reserva,
        on_delete=models.CASCADE,
        related_name='notificaciones_cancelacion',
        verbose_name="Reserva"
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPOS,
        verbose_name="Tipo de cancelación"
    )
    fecha_ausencia = models.DateField(
        null=True, blank=True,
        verbose_name="Fecha de ausencia",
        help_text="Solo para cancelaciones temporales"
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de notificación"
    )
    leida_por = models.ManyToManyField(
        User,
        blank=True,
        related_name='notificaciones_leidas',
        verbose_name="Vista por"
    )

    class Meta:
        verbose_name = "Notificación de Cancelación"
        verbose_name_plural = "Notificaciones de Cancelaciones"
        ordering = ['-fecha_creacion']

    def __str__(self):
        return (
            f"[{self.get_tipo_display()}] "
            f"{self.reserva.get_nombre_completo_usuario()} — "
            f"{self.reserva.clase.get_nombre_display()} "
            f"{self.reserva.clase.dia} {self.reserva.clase.horario.strftime('%H:%M')}"
        )

# ==============================================================================
# MODELOS REGISTROS DE PAGOS
# ==============================================================================

class PlanPago(models.Model):
    """
    Plan de pagos según cantidad de clases por semana.
    Define cuánto debe pagar un cliente según cuántas clases tenga reservadas.
    """
    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre del plan",
        help_text="Ej: '1 clase semanal', '2 clases semanales', etc."
    )
    
    clases_por_semana = models.PositiveIntegerField(
        verbose_name="Clases por semana",
        help_text="Cantidad de clases reservadas por semana"
    )
    
    precio_mensual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Precio mensual",
        help_text="Precio que debe pagar el cliente por mes"
    )
    
    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
        help_text="Descripción opcional del plan"
    )
    
    activo = models.BooleanField(
        default=True,
        verbose_name="Plan activo",
        help_text="Si este plan está disponible para asignar"
    )
    
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    
    fecha_modificacion = models.DateTimeField(
        auto_now=True,
        verbose_name="Última modificación"
    )

    tipo_plan = models.CharField(
        max_length=20,
        choices=[
            ('mensual', 'Plan Mensual Recurrente'),
            ('por_clase', 'Pago por Clase Individual'),
        ],
        default='mensual',
        verbose_name="Tipo de plan",
        help_text="Mensual: plan recurrente con pago mensual adelantado. Por clase: pago individual por clase."
    )

    precio_por_clase = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio por clase individual",
        help_text="Solo para planes tipo 'por_clase'. Precio que se cobra por cada clase individual."
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que el precio sea positivo
        if self.precio_mensual <= 0:
            raise ValidationError({
                'precio_mensual': 'El precio debe ser mayor a cero.'
            })
        
        # Validar que no haya duplicados activos
        if self.activo:
            existing = PlanPago.objects.filter(
                clases_por_semana=self.clases_por_semana,
                activo=True
            ).exclude(pk=self.pk)
            
            if existing.exists():
                raise ValidationError({
                    'clases_por_semana': f'Ya existe un plan activo para {self.clases_por_semana} clases por semana.'
                })
        # Validaciones para planes por clase
        if self.tipo_plan == 'por_clase':
            if not self.precio_por_clase or self.precio_por_clase <= 0:
                raise ValidationError({
                    'precio_por_clase': 'Los planes por clase deben tener un precio por clase válido.'
                })
            # Para planes por clase, las clases_por_semana debe ser 0 o None
            if self.clases_por_semana != 0:
                raise ValidationError({
                    'clases_por_semana': 'Los planes por clase no deben tener límite de clases por semana.'
                })
        
        # Validaciones para planes mensuales
        if self.tipo_plan == 'mensual':
            if self.precio_por_clase is not None:
                raise ValidationError({
                    'precio_por_clase': 'Los planes mensuales no deben tener precio por clase.'
                })
            if self.clases_por_semana <= 0:
                raise ValidationError({
                    'clases_por_semana': 'Los planes mensuales deben tener al menos 1 clase por semana.'
                })

    def calcular_precio_efectivo(self):
        """
        Calcula el precio con descuento del 10% por pago en efectivo,
        redondeado al millar más cercano (< 500 hacia abajo, >= 500 hacia arriba).
        Ejemplo: $53.000 × 0.9 = $47.700 → $48.000
                $53.333 × 0.9 = $47.999.7 → $48.000
        """
        from decimal import ROUND_HALF_UP
        precio_con_descuento = self.precio_mensual * Decimal('0.90')
        precio_redondeado = (
            precio_con_descuento / Decimal('1000')
        ).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * Decimal('1000')
        return precio_redondeado

    def __str__(self):
        estado = "Activo" if self.activo else "Inactivo"
        if self.tipo_plan == 'por_clase':
            return f"{self.nombre} - ${self.precio_por_clase}/clase ({estado})"
        return f"{self.nombre} - ${self.precio_mensual}/mes ({estado})"

    class Meta:
        verbose_name = "Plan de Pago"
        verbose_name_plural = "Planes de Pago"
        ordering = ['clases_por_semana']

class EstadoPagoCliente(models.Model):
    """
    Estado de pagos de cada cliente/usuario.
    Mantiene el seguimiento de cuánto debe pagar cada cliente según sus reservas.
    """
    usuario = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        verbose_name="Usuario",
        related_name='estado_pago'
    )
    
    plan_actual = models.ForeignKey(
        PlanPago,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Plan actual",
        help_text="Plan de pago asignado según sus reservas activas"
    )
    
    ultimo_pago = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha del último pago",
        help_text="Fecha en que realizó su último pago"
    )
    
    monto_ultimo_pago = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Monto del último pago"
    )
    
    saldo_actual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Saldo actual",
        help_text="Positivo = crédito a favor, Negativo = deuda"
    )
    
    observaciones = models.TextField(
        blank=True,
        verbose_name="Observaciones",
        help_text="Notas internas sobre el estado de pago del cliente"
    )
    
    activo = models.BooleanField(
        default=True,
        verbose_name="Estado activo",
        help_text="Si el cliente está activo para el sistema de pagos"
    )
    
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización"
    )

    ultimo_mes_cobrado = models.DateField(
        null=True,
        blank=True,
        verbose_name="Último mes cobrado",
        help_text="Mes/año del último cobro mensual generado (formato: primer día del mes)"
    )

    puede_reservar = models.BooleanField(
        default=True,
        verbose_name="Puede reservar clases",
        help_text="Si el cliente puede reservar/modificar clases (False si tiene deuda vencida)"
    )

    fecha_limite_pago = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha límite de pago",
        help_text="Fecha límite para pagar sin restricciones (día 10 de cada mes)"
    )

    monto_deuda_mensual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Deuda mensual actual",
        help_text="Monto adeudado del mes actual"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar fecha de último pago
        if self.ultimo_pago and self.ultimo_pago > timezone.now().date():
            raise ValidationError({
                'ultimo_pago': 'La fecha del último pago no puede ser futura.'
            })

    def calcular_plan_segun_reservas(self):
        """
        Calcula qué plan de pago debería tener según los PlanUsuario activos
        que el cliente seleccionó, independientemente de cuántas reservas haya hecho.
        Si tiene múltiples planes activos, suma las clases para buscar el PlanPago.
        Retorna el PlanPago correspondiente o None.
        """
        try:
            hoy = timezone.now().date()

            # Obtener los PlanUsuario activos y vigentes del cliente
            planes_usuario = PlanUsuario.objects.filter(
                usuario=self.usuario,
                activo=True,
                fecha_inicio__lte=hoy,
                fecha_fin__gte=hoy
            ).select_related('plan')

            if not planes_usuario.exists():
                return None

            # Sumar las clases por semana de todos los planes activos
            total_clases = sum(pu.plan.clases_por_semana for pu in planes_usuario)

            # Buscar el PlanPago que corresponde a ese total de clases
            plan = PlanPago.objects.filter(
                clases_por_semana=total_clases,
                activo=True
            ).first()

            return plan

        except Exception:
            return None

    def actualizar_plan_automatico(self):
        """
        Actualiza automáticamente el plan según las reservas actuales.
        Si el plan_actual ya tiene las clases_por_semana correctas, no lo pisa
        para evitar ambigüedad cuando hay varios PlanPago con igual cantidad de clases.
        """
        plan_correcto = self.calcular_plan_segun_reservas()

        if plan_correcto is None:
            return plan_correcto

        # Si ya tiene un plan con las mismas clases/semana, respetarlo
        if (
            self.plan_actual is not None
            and self.plan_actual.clases_por_semana == plan_correcto.clases_por_semana
        ):
            return self.plan_actual

        if plan_correcto != self.plan_actual:
            self.plan_actual = plan_correcto
            self.save()

        return plan_correcto

    def calcular_deuda_mensual(self):
        """
        Calcula cuánto debe pagar este mes según su plan actual.
        """
        if not self.plan_actual:
            return 0
        
        return self.plan_actual.precio_mensual

    def calcular_saldo_actual(self):
        """
        Calcula el saldo basado en:
        1. Total pagado históricamente
        2. Menos: costo mensual × meses que debe haber pagado
        """
        if not self.plan_actual:
            return Decimal('0')
        
        # Total pagado por el cliente (histórico completo)
        total_pagado = RegistroPago.objects.filter(
            cliente=self.usuario,
            estado='confirmado'
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
        
        # Calcular cuántos meses debe
        meses_que_debe = self._calcular_meses_que_debe()
        
        # Total que debería haber pagado
        total_que_debe = self.plan_actual.precio_mensual * meses_que_debe
        
        # Saldo = Total pagado - Total que debe
        return total_pagado - total_que_debe

    def _calcular_meses_que_debe(self):
        """
        Calcula cuántos meses debe haber pagado el cliente
        """
        if not self.plan_actual:
            return 0
        
        # Buscar el primer pago o cuando se asignó el plan
        primer_pago = RegistroPago.objects.filter(
            cliente=self.usuario,
            estado='confirmado'
        ).order_by('fecha_pago').first()
        
        # Si no hay pagos, usar fecha de creación del estado de pago
        fecha_inicio = primer_pago.fecha_pago if primer_pago else self.fecha_creacion.date()
        
        hoy = timezone.now().date()
        
        # Calcular meses transcurridos
        meses_transcurridos = (hoy.year - fecha_inicio.year) * 12 + (hoy.month - fecha_inicio.month)
        
        # Si ya pasó el día 10 del mes actual, contar este mes también
        if hoy.day > 10:
            meses_transcurridos += 1
        
        return max(0, meses_transcurridos)

    def actualizar_saldo_automatico(self):
        """
        Actualiza el saldo recalculando desde el histórico completo
        """
        nuevo_saldo = self.calcular_saldo_actual()
        
        if self.saldo_actual != nuevo_saldo:
            self.saldo_actual = nuevo_saldo
            self.save()
        
        return nuevo_saldo
    
    def generar_deuda_mes_actual(self):
        """
        Genera la deuda del mes actual cuando se asigna un plan nuevo.
        Calcula si debe cobrar mes completo o medio mes según la fecha.
        """
        if not self.plan_actual:
            return None
        
        from datetime import date
        hoy = timezone.now().date()
        primer_dia_mes = date(hoy.year, hoy.month, 1)
        
        # Calcular fecha de vencimiento
        # Si ya pasó el día 10, el vencimiento es el 10 del mes siguiente
        if hoy.day > 10:
            if hoy.month == 12:
                fecha_vencimiento = date(hoy.year + 1, 1, 10)
            else:
                fecha_vencimiento = date(hoy.year, hoy.month + 1, 10)
        else:
            fecha_vencimiento = date(hoy.year, hoy.month, 10)
        
        # Determinar si cobrar mes completo o medio mes
        es_medio_mes = False
        monto_a_cobrar = self.plan_actual.precio_mensual
        
        # Si se registra después del día 15, cobrar medio mes
        if hoy.day > 15:
            es_medio_mes = True
            monto_a_cobrar = self.plan_actual.precio_mensual / 2
        
        # Verificar si ya existe una deuda para este mes
        deuda_existente = DeudaMensual.objects.filter(
            usuario=self.usuario,
            mes_año=primer_dia_mes
        ).first()
        
        if deuda_existente:
            # El admin cambió el plan: sobreescribir la deuda del mes actual
            deuda_existente.plan_aplicado = self.plan_actual
            deuda_existente.monto_original = monto_a_cobrar
            deuda_existente.monto_pendiente = monto_a_cobrar
            deuda_existente.es_medio_mes = es_medio_mes
            deuda_existente.save()
            return deuda_existente
        
        # Crear la deuda mensual
        nueva_deuda = DeudaMensual.objects.create(
            usuario=self.usuario,
            mes_año=primer_dia_mes,
            plan_aplicado=self.plan_actual,
            monto_original=monto_a_cobrar,
            monto_pendiente=monto_a_cobrar,
            es_medio_mes=es_medio_mes,
            estado='pendiente',
            fecha_vencimiento=fecha_vencimiento,
            observaciones=f"Deuda generada automáticamente al {'registrarse' if es_medio_mes else 'seleccionar plan'}"
        )
        
        # Actualizar el saldo actual (deuda = saldo negativo)
        self.saldo_actual -= monto_a_cobrar
        self.monto_deuda_mensual = monto_a_cobrar
        self.fecha_limite_pago = fecha_vencimiento
        
        self.save()
        
        return nueva_deuda

    def _obtener_saldo_mes_anterior(self):
        """
        Obtiene el saldo que tenía el cliente al final del mes anterior
        """
        # Por simplicidad, usaremos el saldo_actual actual como base
        # En un sistema más complejo tendríamos un historial mensual
        return self.saldo_actual

    def esta_al_dia(self):
        """
        Verifica si el cliente está al día con sus pagos (incluyendo cálculo automático)
        """
        saldo_calculado = self.calcular_saldo_actual()
        return saldo_calculado >= 0

    def get_meses_atrasado(self):
        """
        Calcula cuántos meses de atraso tiene el cliente.
        """
        if not self.ultimo_pago or not self.plan_actual:
            return 0
        
        hoy = timezone.now().date()
        meses_transcurridos = (hoy.year - self.ultimo_pago.year) * 12 + (hoy.month - self.ultimo_pago.month)
        
        # Si han pasado más de 30 días desde el último pago, contar como al menos 1 mes
        if (hoy - self.ultimo_pago).days > 30:
            meses_transcurridos = max(1, meses_transcurridos)
        
        return max(0, meses_transcurridos)

    def get_estado_display(self):
        """
        Retorna una descripción legible del estado de pago.
        """
        if not self.plan_actual:
            return "Sin plan asignado"
        
        if self.saldo_actual > 0:
            return f"Crédito: ${self.saldo_actual}"
        elif self.saldo_actual == 0:
            return "Al día"
        else:
            return f"Debe: ${abs(self.saldo_actual)}"

    def get_nombre_completo(self):
        """Devuelve el nombre completo del usuario"""
        if self.usuario.first_name and self.usuario.last_name:
            return f"{self.usuario.first_name} {self.usuario.last_name}"
        return self.usuario.username

    def __str__(self):
        return f"Estado de pago - {self.get_nombre_completo()}"

    class Meta:
        verbose_name = "Estado de Pago de Cliente"
        verbose_name_plural = "Estados de Pago de Clientes"
        ordering = ['-fecha_actualizacion']

class RegistroPago(models.Model):
    """
    Historial de pagos realizados por cada cliente.
    Cada registro representa un pago individual.
    """
    TIPOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('tarjeta', 'Tarjeta'),
        ('otro', 'Otro'),
    ]
    
    ESTADOS_PAGO = [
        ('confirmado', 'Confirmado'),
        ('pendiente', 'Pendiente de confirmación'),
        ('rechazado', 'Rechazado'),
    ]
    
    cliente = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,  # ← Agregar esto temporalmente
        blank=True,  # ← Agregar esto temporalmente
        verbose_name="Cliente",
        related_name='pagos_realizados'
    )
    
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto pagado"
    )
    
    fecha_pago = models.DateField(
        verbose_name="Fecha del pago",
        help_text="Fecha en que se realizó el pago"
    )
    
    tipo_pago = models.CharField(
        max_length=20,
        choices=TIPOS_PAGO,
        default='efectivo',
        verbose_name="Tipo de pago"
    )
    
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS_PAGO,
        default='confirmado',
        verbose_name="Estado del pago"
    )
    
    concepto = models.CharField(
        max_length=200,
        verbose_name="Concepto",
        help_text="Descripción del pago (ej: 'Pago mensual Enero 2025')"
    )
    
    observaciones = models.TextField(
        blank=True,
        verbose_name="Observaciones",
        help_text="Notas adicionales sobre este pago"
    )
    
    comprobante = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Número de comprobante",
        help_text="Número de recibo, transferencia, etc."
    )
    
    # Usuario administrador que registró este pago
    registrado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='pagos_registrados',
        verbose_name="Registrado por",
        help_text="Administrador que registró este pago"
    )
    
    fecha_registro = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro"
    )
    
    fecha_modificacion = models.DateTimeField(
        auto_now=True,
        verbose_name="Última modificación"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que el monto sea positivo
        if self.monto <= 0:
            raise ValidationError({
                'monto': 'El monto debe ser mayor a cero.'
            })
        
        # Validar fecha de pago
        if self.fecha_pago > timezone.now().date():
            raise ValidationError({
                'fecha_pago': 'La fecha del pago no puede ser futura.'
            })

    def save(self, *args, **kwargs):
        """Override save para actualizar el estado del cliente automáticamente"""
        # Ejecutar validaciones
        self.full_clean()
        
        # Guardar el registro
        super().save(*args, **kwargs)
        
        # Actualizar estado del cliente solo si el pago está confirmado
        if self.estado == 'confirmado':
            self.actualizar_estado_cliente()

    def actualizar_estado_cliente(self):
        """
        Actualiza el estado de pago del cliente cuando se confirma un pago.
        """
        try:
            # Obtener o crear estado de pago del cliente
            estado_cliente, created = EstadoPagoCliente.objects.get_or_create(
                usuario=self.cliente,
                defaults={'activo': True}
            )

            # Actualizar fecha y monto del último pago
            estado_cliente.ultimo_pago = self.fecha_pago
            estado_cliente.monto_ultimo_pago = self.monto

            # ⚡ PASO 0: Generar la deuda del mes actual ANTES de aplicar el pago.
            # Esto garantiza que si la deuda no fue creada aún por el cron,
            # exista al momento de aplicar el descuento por efectivo en el PASO 1.
            if estado_cliente.plan_actual:
                estado_cliente.generar_deuda_mes_actual()

            # 💰 PASO 1: Aplicar el pago a las deudas pendientes (más antiguas primero)
            monto_restante = Decimal(str(self.monto))
            es_pago_efectivo = self.tipo_pago == 'efectivo'

            deudas_pendientes = DeudaMensual.objects.filter(
                usuario=self.cliente,
                estado__in=['pendiente', 'vencido', 'parcial']
            ).order_by('mes_año')

            for deuda in deudas_pendientes:
                if monto_restante <= 0:
                    break

                # Si el pago es en efectivo y la deuda no fue pagada parcialmente,
                # ajustar el monto original al precio con descuento del plan
                if es_pago_efectivo and deuda.estado != 'parcial':
                    try:
                        precio_efectivo = deuda.plan_aplicado.calcular_precio_efectivo()
                        # Solo ajustar si el precio efectivo es menor al original
                        # (evitar sobreescribir deudas ya ajustadas o de medio mes)
                        if precio_efectivo < deuda.monto_original:
                            diferencia = deuda.monto_original - precio_efectivo
                            deuda.monto_original = precio_efectivo
                            deuda.monto_pendiente = max(
                                Decimal('0'),
                                deuda.monto_pendiente - diferencia
                            )
                            deuda.save(update_fields=['monto_original', 'monto_pendiente'])
                    except Exception:
                        pass  # Si falla el ajuste, continuar con el monto original

                # Aplicar pago a esta deuda
                monto_aplicado = deuda.aplicar_pago_parcial(monto_restante)
                monto_restante -= Decimal(str(monto_aplicado))

            # 📊 PASO 2: Recalcular el saldo DESDE CERO
            # Saldo = Total pagado - Total de deudas generadas (monto_original ajustado)

            total_pagado = RegistroPago.objects.filter(
                cliente=self.cliente,
                estado='confirmado'
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

            total_deudas_generadas = DeudaMensual.objects.filter(
                usuario=self.cliente
            ).aggregate(total=Sum('monto_original'))['total'] or Decimal('0')

            estado_cliente.saldo_actual = total_pagado - total_deudas_generadas

            # Si no quedan deudas vencidas pendientes, desbloquear reservas
            if not estado_cliente.puede_reservar:
                tiene_deudas_vencidas = DeudaMensual.objects.filter(
                    usuario=self.cliente,
                    estado='vencido',
                    monto_pendiente__gt=0
                ).exists()
                if not tiene_deudas_vencidas:
                    estado_cliente.puede_reservar = True

            # Guardar cambios
            estado_cliente.save()

        except Exception as e:
            # Log del error pero no fallar la operación
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error actualizando estado de cliente en pago {self.id}: {str(e)}")

    class Meta:
        verbose_name = "Registro de Pago"
        verbose_name_plural = "Registros de Pagos"
        ordering = ['-fecha_pago', '-fecha_registro']

# Señales para actualizar automáticamente el estado de pagos cuando cambian las reservas
@receiver(post_save, sender=Reserva)
def actualizar_estado_pago_por_reserva(sender, instance, created, **kwargs):
    """
    Actualiza el estado de pago cuando se crea o modifica una reserva.
    Genera deuda automática al asignar un plan nuevo.
    """
    try:
        estado_cliente, created_estado = EstadoPagoCliente.objects.get_or_create(
            usuario=instance.usuario,
            defaults={'activo': True}
        )
        
        # Guardar el plan anterior para detectar cambios
        plan_anterior = estado_cliente.plan_actual
        
        # Actualizar plan según reservas actuales
        nuevo_plan = estado_cliente.actualizar_plan_automatico()
        
        # Si es una nueva reserva Y se asignó un plan nuevo (o es la primera vez)
        if created and nuevo_plan and (not plan_anterior or plan_anterior != nuevo_plan):
            # Generar deuda del mes actual automáticamente
            deuda_generada = estado_cliente.generar_deuda_mes_actual()
            
            if deuda_generada:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"Deuda generada automáticamente para {instance.usuario.username}: "
                    f"${deuda_generada.monto_original} - Plan: {nuevo_plan.nombre}"
                )
        
    except Exception as e:
        # Log del error pero no fallar la operación
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando estado de pago por reserva {instance.id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

# función para crear estados de pago para usuarios existentes
def crear_estados_pago_usuarios_existentes():
    """
    Función para crear estados de pago para usuarios que ya existen en el sistema.
    Se ejecuta una sola vez para migrar datos existentes.
    """
    from django.contrib.auth.models import User
    
    usuarios_sin_estado = User.objects.filter(
        is_staff=False,
        estado_pago__isnull=True
    )
    
    for usuario in usuarios_sin_estado:
        estado = EstadoPagoCliente.objects.create(
            usuario=usuario,
            activo=True
        )
        # Actualizar plan según reservas actuales
        estado.actualizar_plan_automatico()

# ==============================================================================
# MODELO PARA PLANES DE PAGOS
# ==============================================================================

class PlanUsuario(models.Model):
    """
    Plan activo de un usuario. Un usuario puede tener múltiples planes activos
    para diferentes períodos o tipos (ej: plan permanente + plan adicional temporal)
    """
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Usuario",
        related_name='planes_activos'
    )
    
    plan = models.ForeignKey(
        PlanPago,
        on_delete=models.CASCADE,
        verbose_name="Plan de pago"
    )
    
    fecha_inicio = models.DateField(
        verbose_name="Fecha de inicio",
        help_text="Fecha desde cuando es válido este plan"
    )
    
    fecha_fin = models.DateField(
        verbose_name="Fecha de fin",
        help_text="Fecha hasta cuando es válido este plan"
    )
    
    activo = models.BooleanField(
        default=True,
        verbose_name="Plan activo",
        help_text="Si este plan está activo para el usuario"
    )
    
    tipo_plan = models.CharField(
        max_length=20,
        choices=[
            ('permanente', 'Plan Permanente'),
            ('temporal', 'Plan Temporal/Adicional'),
        ],
        default='permanente',
        verbose_name="Tipo de plan",
        help_text="Permanente se renueva automáticamente, temporal es de una sola vez"
    )
    
    renovacion_automatica = models.BooleanField(
        default=True,
        verbose_name="Renovación automática",
        help_text="Si el plan se renueva automáticamente al vencer"
    )
    
    observaciones = models.TextField(
        blank=True,
        verbose_name="Observaciones",
        help_text="Notas sobre este plan específico"
    )
    
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='planes_creados',
        verbose_name="Creado por",
        help_text="Administrador que asignó este plan"
    )

    fecha_cancelacion_reservas = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de cancelación de reservas",
        help_text="Fecha en que el cron debe cancelar las reservas de este plan"
    )

    reservas_canceladas = models.BooleanField(
        default=False,
        verbose_name="Reservas canceladas",
        help_text="True si el cron ya procesó la cancelación de reservas de este plan"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que fecha_fin sea posterior a fecha_inicio
        if self.fecha_inicio and self.fecha_fin:
            if self.fecha_fin <= self.fecha_inicio:
                raise ValidationError({
                    'fecha_fin': 'La fecha de fin debe ser posterior a la fecha de inicio.'
                })
        
        # Validar que el plan esté activo
        if not self.plan.activo:
            raise ValidationError({
                'plan': 'No se puede asignar un plan inactivo.'
            })

    def esta_vigente(self, fecha=None):
        """Verifica si el plan está vigente en una fecha específica"""
        if not self.activo:
            return False
        
        if fecha is None:
            fecha = timezone.now().date()
        
        return self.fecha_inicio <= fecha <= self.fecha_fin

    def clases_disponibles_semana(self, fecha_inicio_semana=None):
        """
        Calcula cuántas clases puede reservar en una semana específica
        considerando todos sus planes activos
        """
        if fecha_inicio_semana is None:
            # Obtener el lunes de la semana actual
            hoy = timezone.now().date()
            fecha_inicio_semana = hoy - timedelta(days=hoy.weekday())
        
        if not self.esta_vigente(fecha_inicio_semana):
            return 0
        
        return self.plan.clases_por_semana

    def dias_restantes(self):
        """Calcula cuántos días faltan para que expire el plan"""
        if not self.activo:
            return 0
        
        hoy = timezone.now().date()
        if self.fecha_fin < hoy:
            return 0
        
        return (self.fecha_fin - hoy).days

    def renovar_plan(self):
        """
        Renueva el plan por un mes más (solo para planes con renovación automática)
        """
        if not self.renovacion_automatica or self.tipo_plan != 'permanente':
            return False
        
        # Extender fecha_fin por un mes más (aproximadamente 30 días)
        from datetime import timedelta
        self.fecha_fin = self.fecha_fin + timedelta(days=30)
        self.save()
        return True

    def get_estado_display(self):
        """Devuelve el estado actual del plan"""
        if not self.activo:
            return "Inactivo"
        
        hoy = timezone.now().date()
        if hoy < self.fecha_inicio:
            return "Pendiente"
        elif hoy > self.fecha_fin:
            return "Vencido"
        else:
            dias_restantes = self.dias_restantes()
            if dias_restantes <= 7:
                return f"Vence en {dias_restantes} días"
            return "Activo"

    def __str__(self):
        estado = self.get_estado_display()
        return f"{self.usuario.username} - {self.plan.nombre} ({estado})"

    class Meta:
        verbose_name = "Plan de Usuario"
        verbose_name_plural = "Planes de Usuarios"
        ordering = ['-fecha_creacion']

    @staticmethod
    def obtener_clases_disponibles_usuario(usuario, fecha_inicio_semana=None):
        """
        Método estático para obtener el total de clases disponibles 
        para un usuario en una semana específica
        """
        if fecha_inicio_semana is None:
            # Obtener el lunes de la semana actual
            hoy = timezone.now().date()
            fecha_inicio_semana = hoy - timedelta(days=hoy.weekday())
        
        # Obtener todos los planes activos y vigentes del usuario
        planes_vigentes = PlanUsuario.objects.filter(
            usuario=usuario,
            activo=True,
            fecha_inicio__lte=timezone.now().date(),
            fecha_fin__gte=timezone.now().date()
        )
        
        total_clases = sum(plan.plan.clases_por_semana for plan in planes_vigentes)
        return total_clases, planes_vigentes

class DeudaMensual(models.Model):
    """
    Registro de deudas mensuales generadas automáticamente.
    Se genera una deuda el día 1 de cada mes para cada usuario con plan activo.
    """
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Usuario",
        related_name='deudas_mensuales'
    )
    
    mes_año = models.DateField(
        verbose_name="Mes/Año",
        help_text="Primer día del mes al que corresponde esta deuda"
    )
    
    plan_aplicado = models.ForeignKey(
        PlanPago,
        on_delete=models.CASCADE,
        verbose_name="Plan aplicado",
        help_text="Plan que se usó para calcular esta deuda"
    )
    
    monto_original = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto original",
        help_text="Monto calculado según el plan (completo o medio mes)"
    )
    
    monto_pendiente = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto pendiente",
        help_text="Monto que aún se debe (se reduce con pagos parciales)"
    )
    
    es_medio_mes = models.BooleanField(
        default=False,
        verbose_name="Es medio mes",
        help_text="Si se cobró medio mes por registrarse en segunda quincena"
    )
    
    estado = models.CharField(
        max_length=20,
        choices=[
            ('pendiente', 'Pendiente de pago'),
            ('pagado', 'Pagado completamente'),
            ('vencido', 'Vencido (después del día 10)'),
            ('parcial', 'Pagado parcialmente'),
        ],
        default='pendiente',
        verbose_name="Estado de la deuda"
    )
    
    fecha_vencimiento = models.DateField(
        verbose_name="Fecha de vencimiento",
        help_text="Día 10 del mes correspondiente"
    )
    
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    
    observaciones = models.TextField(
        blank=True,
        verbose_name="Observaciones"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar que el monto pendiente no sea mayor al original
        if self.monto_pendiente > self.monto_original:
            raise ValidationError({
                'monto_pendiente': 'El monto pendiente no puede ser mayor al monto original.'
            })
        
        # Validar que la fecha de vencimiento sea día 10
        if self.fecha_vencimiento.day != 10:
            raise ValidationError({
                'fecha_vencimiento': 'La fecha de vencimiento debe ser el día 10 del mes.'
            })

    def esta_vencida(self):
        """Verifica si la deuda está vencida"""
        return timezone.now().date() > self.fecha_vencimiento and self.estado != 'pagado'
    
    def marcar_como_pagado(self):
        """Marca la deuda como pagada completamente"""
        self.monto_pendiente = 0
        self.estado = 'pagado'
        self.save()
    
    def aplicar_pago_parcial(self, monto_pago):
        """Aplica un pago parcial a la deuda"""
        if monto_pago >= self.monto_pendiente:
            # Capturar monto antes de zerear con marcar_como_pagado()
            monto_aplicado = self.monto_pendiente
            self.marcar_como_pagado()
            return monto_aplicado
        else:
            # Pago parcial
            self.monto_pendiente -= monto_pago
            self.estado = 'parcial'
            self.save()
            return monto_pago

    def __str__(self):
        mes_año_str = self.mes_año.strftime('%B %Y')
        return f"Deuda {mes_año_str} - {self.usuario.username} - ${self.monto_pendiente}"

    class Meta:
        verbose_name = "Deuda Mensual"
        verbose_name_plural = "Deudas Mensuales"
        unique_together = ['usuario', 'mes_año']
        ordering = ['-mes_año']

class NotificacionCancelacionPlan(models.Model):
    """
    Notifica a los administradores cuando un usuario cancela su plan.
    """
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notificaciones_cancelacion_plan',
        verbose_name="Usuario"
    )
    plan = models.ForeignKey(
        PlanPago,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Plan cancelado"
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de cancelación"
    )
    leida_por = models.ManyToManyField(
        User,
        blank=True,
        related_name='notificaciones_plan_leidas',
        verbose_name="Vista por"
    )

    class Meta:
        verbose_name = "Notificación de Cancelación de Plan"
        verbose_name_plural = "Notificaciones de Cancelaciones de Plan"
        ordering = ['-fecha_creacion']

    def __str__(self):
        nombre = self.usuario.get_full_name() or self.usuario.username
        plan_nombre = self.plan.nombre if self.plan else 'Plan eliminado'
        return f"[Cancelación Plan] {nombre} — {plan_nombre}"
