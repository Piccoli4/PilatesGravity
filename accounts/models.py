from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from PIL import Image
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


class UserProfile(models.Model):
    """
    Perfil extendido para usuarios del sistema de reservas de Pilates Gravity.
    Extiende el modelo User de Django con información adicional específica del estudio.
    """
    
    # Relación uno a uno con el modelo User de Django
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        verbose_name="Usuario",
        related_name='profile'
    )
    
    # Información de contacto adicional
    telefono = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="El teléfono debe tener entre 9 y 15 dígitos. Puede incluir + al inicio."
            )
        ],
        verbose_name="Teléfono",
        help_text="Número de teléfono para contacto (opcional)"
    )
    
    # Sede preferida del usuario
    SEDES_PREFERENCIA = [
        ('cualquiera', 'Cualquier sede'),
        ('sede_principal', 'Sede Principal - La Rioja 3044'),
        ('sede_2', 'Sede 2 - 9 de julio 3698'),
    ]
    
    sede_preferida = models.CharField(
        max_length=20,
        choices=SEDES_PREFERENCIA,
        default='cualquiera',
        verbose_name="Sede preferida",
        help_text="Sede de preferencia para recibir notificaciones sobre clases"
    )
    
    # Información personal adicional
    fecha_nacimiento = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de nacimiento",
        help_text="Fecha de nacimiento (opcional)"
    )
    
    # Información médica básica (opcional pero útil para un estudio de Pilates)
    tiene_lesiones = models.BooleanField(
        default=False,
        verbose_name="¿Tienes alguna lesión o condición médica?",
        help_text="Marcar si tiene lesiones o condiciones que debamos conocer"
    )
    
    descripcion_lesiones = models.TextField(
        blank=True,
        verbose_name="Descripción de lesiones/condiciones",
        help_text="Describe brevemente cualquier lesión o condición médica relevante",
        max_length=500
    )
    
    # Nivel de experiencia en Pilates
    NIVEL_EXPERIENCIA_CHOICES = [
        ('principiante', 'Principiante'),
        ('intermedio', 'Intermedio'),
        ('avanzado', 'Avanzado'),
        ('instructor', 'Instructor/Profesional'),
    ]
    
    nivel_experiencia = models.CharField(
        max_length=15,
        choices=NIVEL_EXPERIENCIA_CHOICES,
        default='principiante',
        verbose_name="Nivel de experiencia en Pilates"
    )
    
    # Preferencias de contacto
    acepta_marketing = models.BooleanField(
        default=False,
        verbose_name="Acepto recibir información promocional",
        help_text="Marcar para recibir emails sobre promociones y eventos especiales"
    )
    
    acepta_recordatorios = models.BooleanField(
        default=True,
        verbose_name="Acepto recibir recordatorios de clases",
        help_text="Marcar para recibir recordatorios de tus clases reservadas"
    )
    
    # Preferencias específicas por sede
    notificar_clases_sede_principal = models.BooleanField(
        default=True,
        verbose_name="Notificar sobre clases en Sede Principal",
        help_text="Recibir notificaciones sobre nuevas clases en La Rioja 3044"
    )
    
    notificar_clases_sede_2 = models.BooleanField(
        default=True,
        verbose_name="Notificar sobre clases en Sede 2",
        help_text="Recibir notificaciones sobre nuevas clases en 9 de julio 3698"
    )
    
    # Información del estudio
    fecha_primera_clase = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de primera clase",
        help_text="Fecha en que tomó su primera clase en el estudio"
    )
    
    # Sede donde tomó su primera clase
    sede_primera_clase = models.CharField(
        max_length=20,
        choices=[
            ('sede_principal', 'Sede Principal - La Rioja 3044'),
            ('sede_2', 'Sede 2 - 9 de julio 3698'),
        ],
        blank=True,
        null=True,
        verbose_name="Sede de primera clase",
        help_text="Sede donde tomó su primera clase"
    )
    
    # Notas internas (solo para administradores)
    notas_admin = models.TextField(
        blank=True,
        verbose_name="Notas administrativas",
        help_text="Notas internas del estudio (solo visible para administradores)",
        max_length=1000
    )
    
    # Avatar/foto de perfil (opcional)
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        verbose_name="Foto de perfil",
        help_text="Foto de perfil opcional (se redimensionará automáticamente)"
    )
    
    # Campos de auditoría
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación del perfil"
    )
    
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización del perfil"
    )
    
    # Campo para rastrear si es la primera vez que completa el perfil
    perfil_completado = models.BooleanField(
        default=False,
        verbose_name="Perfil completado",
        help_text="Indica si el usuario ha completado su información de perfil"
    )

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()
        
        # Validar fecha de nacimiento
        if self.fecha_nacimiento:
            if self.fecha_nacimiento > timezone.now().date():
                raise ValidationError({
                    'fecha_nacimiento': 'La fecha de nacimiento no puede ser futura.'
                })
            
            # Validar edad mínima (por ejemplo, 16 años)
            edad = (timezone.now().date() - self.fecha_nacimiento).days // 365
            if edad < 16:
                raise ValidationError({
                    'fecha_nacimiento': 'Debes tener al menos 16 años para registrarte.'
                })
        
        # Validar que si tiene lesiones, debe describir
        if self.tiene_lesiones and not self.descripcion_lesiones.strip():
            raise ValidationError({
                'descripcion_lesiones': 'Si tienes lesiones o condiciones médicas, por favor descríbelas brevemente.'
            })
        
        # Validar fecha de primera clase
        if self.fecha_primera_clase:
            if self.fecha_primera_clase > timezone.now().date():
                raise ValidationError({
                    'fecha_primera_clase': 'La fecha de primera clase no puede ser futura.'
                })

    def save(self, *args, **kwargs):
        """Override save para procesar la imagen"""
        # Ejecutar validaciones
        self.full_clean()
            
        # Guardar el objeto
        super().save(*args, **kwargs)
            
        # Procesar avatar si existe
        if self.avatar:
            self.resize_avatar()

    def resize_avatar(self):
        """Redimensiona el avatar a un tamaño apropiado"""
        try:
            img = Image.open(self.avatar.path)
            
            # Redimensionar si es muy grande (máximo 300x300)
            if img.height > 300 or img.width > 300:
                output_size = (300, 300)
                img.thumbnail(output_size)
                img.save(self.avatar.path)
        except Exception:
            # Si hay error procesando la imagen, continuar sin problema
            pass

    def get_nombre_completo(self):
        """Devuelve el nombre completo del usuario"""
        if self.user.first_name and self.user.last_name:
            return f"{self.user.first_name} {self.user.last_name}"
        return self.user.username

    def get_edad(self):
        """Calcula y devuelve la edad del usuario"""
        if not self.fecha_nacimiento:
            return None
        
        today = timezone.now().date()
        return today.year - self.fecha_nacimiento.year - (
            (today.month, today.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )

    def get_tiempo_en_estudio(self):
        """Devuelve cuánto tiempo lleva el usuario en el estudio"""
        if not self.fecha_primera_clase:
            return None
        
        delta = timezone.now().date() - self.fecha_primera_clase
        
        if delta.days < 30:
            return f"{delta.days} días"
        elif delta.days < 365:
            meses = delta.days // 30
            return f"{meses} mes{'es' if meses > 1 else ''}"
        else:
            años = delta.days // 365
            return f"{años} año{'s' if años > 1 else ''}"

    def get_reservas_activas(self):
        """Devuelve las reservas activas del usuario"""
        return self.user.reservas_pilates.filter(activa=True)

    def get_total_reservas(self):
        """Devuelve el total de reservas (activas e inactivas) del usuario"""
        return self.user.reservas_pilates.count()

    def tiene_reservas_activas(self):
        """Verifica si el usuario tiene reservas activas"""
        return self.get_reservas_activas().exists()

    # Métodos específicos para sedes
    def get_reservas_por_sede(self, sede=None):
        """Devuelve las reservas del usuario filtradas por sede"""
        reservas = self.get_reservas_activas()
        if sede:
            reservas = reservas.filter(clase__direccion=sede)
        return reservas

    def get_sede_preferida_display(self):
        """Devuelve el nombre legible de la sede preferida"""
        return dict(self.SEDES_PREFERENCIA).get(self.sede_preferida, 'Cualquier sede')

    def debe_notificar_sede(self, sede):
        """Verifica si debe recibir notificaciones de una sede específica"""
        if not self.acepta_marketing:
            return False
        
        if sede == 'sede_principal':
            return self.notificar_clases_sede_principal
        elif sede == 'sede_2':
            return self.notificar_clases_sede_2
        
        return False

    def get_sedes_notificacion(self):
        """Devuelve las sedes para las que acepta notificaciones"""
        sedes = []
        if self.notificar_clases_sede_principal:
            sedes.append('sede_principal')
        if self.notificar_clases_sede_2:
            sedes.append('sede_2')
        return sedes

    def puede_hacer_reserva(self):
        """
        Verifica si el usuario puede hacer nuevas reservas.
        Por ahora siempre True, pero se puede extender con lógica de negocio.
        """
        return True

    def __str__(self):
        return f"Perfil de {self.get_nombre_completo()}"

    class Meta:
        verbose_name = "Perfil de Usuario"
        verbose_name_plural = "Perfiles de Usuario"
        ordering = ['-fecha_creacion']

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Señal que crea automáticamente un perfil cuando se crea un usuario.
    """
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    Señal que guarda el perfil cuando se guarda el usuario.
    """
    if hasattr(instance, 'profile'):
        instance.profile.save()

class ConfiguracionEstudio(models.Model):
    """
    Modelo para configuraciones globales del estudio con soporte para múltiples sedes.
    Singleton pattern - solo debe existir una instancia.
    """
    
    # Información básica del estudio
    nombre_estudio = models.CharField(
        max_length=100,
        default="Pilates Gravity",
        verbose_name="Nombre del estudio"
    )
    
    direccion = models.TextField(
        blank=True,
        verbose_name="Dirección del estudio",
        help_text="Dirección general o principal del estudio"
    )
    
    telefono_contacto = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Teléfono de contacto general"
    )
    
    email_contacto = models.EmailField(
        blank=True,
        verbose_name="Email de contacto general"
    )
    
    # === CONFIGURACIONES ESPECÍFICAS POR SEDE ===
    
    # Sede Principal
    sede_principal_activa = models.BooleanField(
        default=True,
        verbose_name="Sede Principal activa",
        help_text="Si la Sede Principal está operativa"
    )
    
    sede_principal_telefono = models.CharField(
        max_length=20,
        blank=True,
        default="+54 342 511 4448",
        verbose_name="Teléfono Sede Principal",
        help_text="Teléfono específico de La Rioja 3044"
    )
    
    sede_principal_email = models.EmailField(
        blank=True,
        verbose_name="Email Sede Principal",
        help_text="Email específico de la sede principal"
    )
    
    sede_principal_horarios = models.TextField(
        blank=True,
        verbose_name="Horarios Sede Principal",
        help_text="Horarios de atención de la Sede Principal"
    )
    
    sede_principal_capacidad_maxima = models.PositiveIntegerField(
        default=10,
        verbose_name="Capacidad máxima por clase - Sede Principal",
        help_text="Número máximo de personas por clase en la sede principal"
    )
    
    # Sede 2
    sede_2_activa = models.BooleanField(
        default=True,
        verbose_name="Sede 2 activa",
        help_text="Si la Sede 2 está operativa"
    )
    
    sede_2_telefono = models.CharField(
        max_length=20,
        blank=True,
        default="+54 342 511 4448",
        verbose_name="Teléfono Sede 2",
        help_text="Teléfono específico de 9 de julio 3698"
    )
    
    sede_2_email = models.EmailField(
        blank=True,
        verbose_name="Email Sede 2",
        help_text="Email específico de la sede 2"
    )
    
    sede_2_horarios = models.TextField(
        blank=True,
        verbose_name="Horarios Sede 2",
        help_text="Horarios de atención de la Sede 2"
    )
    
    sede_2_capacidad_maxima = models.PositiveIntegerField(
        default=8,
        verbose_name="Capacidad máxima por clase - Sede 2",
        help_text="Número máximo de personas por clase en la sede 2"
    )
    
    # === CONFIGURACIONES GENERALES DE RESERVAS ===
    
    horas_anticipacion_cancelacion = models.PositiveIntegerField(
        default=12,
        verbose_name="Horas de anticipación para cancelar",
        help_text="Número de horas de anticipación requeridas para cancelar una reserva"
    )
    
    max_reservas_por_usuario = models.PositiveIntegerField(
        default=3,
        verbose_name="Máximo de reservas activas por usuario",
        help_text="Número máximo de reservas activas que puede tener un usuario"
    )
    
    # Configuraciones de notificaciones
    enviar_recordatorios = models.BooleanField(
        default=True,
        verbose_name="Enviar recordatorios de clase",
        help_text="Enviar recordatorios por email antes de las clases"
    )
    
    horas_antes_recordatorio = models.PositiveIntegerField(
        default=24,
        verbose_name="Horas antes para enviar recordatorio",
        help_text="Cuántas horas antes de la clase enviar el recordatorio"
    )
    
    # Configuraciones de marketing por sede
    enviar_marketing_sede_principal = models.BooleanField(
        default=True,
        verbose_name="Marketing activo - Sede Principal",
        help_text="Enviar emails de marketing sobre la Sede Principal"
    )
    
    enviar_marketing_sede_2 = models.BooleanField(
        default=True,
        verbose_name="Marketing activo - Sede 2",
        help_text="Enviar emails de marketing sobre la Sede 2"
    )
    
    # Información adicional
    mensaje_bienvenida = models.TextField(
        blank=True,
        verbose_name="Mensaje de bienvenida",
        help_text="Mensaje que aparece en la página principal"
    )
    
    mensaje_sede_principal = models.TextField(
        blank=True,
        verbose_name="Mensaje específico Sede Principal",
        help_text="Mensaje específico para mostrar sobre la Sede Principal"
    )
    
    mensaje_sede_2 = models.TextField(
        blank=True,
        verbose_name="Mensaje específico Sede 2", 
        help_text="Mensaje específico para mostrar sobre la Sede 2"
    )
    
    activo = models.BooleanField(
        default=True,
        verbose_name="Configuración activa"
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Override save para implementar singleton pattern"""
        # Asegurar que solo existe una configuración
        if not self.pk and ConfiguracionEstudio.objects.exists():
            # Si ya existe una configuración, actualizarla en lugar de crear nueva
            existing = ConfiguracionEstudio.objects.first()
            self.pk = existing.pk
        
        super().save(*args, **kwargs)

    @classmethod
    def get_configuracion(cls):
        """Método de clase para obtener la configuración actual"""
        config, created = cls.objects.get_or_create(
            defaults={
                'nombre_estudio': 'Pilates Gravity',
                'horas_anticipacion_cancelacion': 12,
                'max_reservas_por_usuario': 3,
                'enviar_recordatorios': True,
                'horas_antes_recordatorio': 24,
                'sede_principal_activa': True,
                'sede_2_activa': True,
                'sede_principal_telefono': '+54 342 511 4448',
                'sede_2_telefono': '+54 342 511 4448',
                'sede_principal_capacidad_maxima': 10,
                'sede_2_capacidad_maxima': 8,
            }
        )
        return config

    # === MÉTODOS ESPECÍFICOS PARA SEDES ===
    
    def get_sedes_activas(self):
        """Devuelve las sedes activas como lista de tuplas"""
        sedes = []
        if self.sede_principal_activa:
            sedes.append(('sede_principal', 'Sede Principal - La Rioja 3044'))
        if self.sede_2_activa:
            sedes.append(('sede_2', 'Sede 2 - 9 de julio 3698'))
        return sedes

    def get_telefono_sede(self, sede):
        """Devuelve el teléfono de una sede específica"""
        if sede == 'sede_principal':
            return self.sede_principal_telefono or self.telefono_contacto
        elif sede == 'sede_2':
            return self.sede_2_telefono or self.telefono_contacto
        return self.telefono_contacto

    def get_email_sede(self, sede):
        """Devuelve el email de una sede específica"""
        if sede == 'sede_principal':
            return self.sede_principal_email or self.email_contacto
        elif sede == 'sede_2':
            return self.sede_2_email or self.email_contacto
        return self.email_contacto

    def get_capacidad_maxima_sede(self, sede):
        """Devuelve la capacidad máxima recomendada para una sede"""
        if sede == 'sede_principal':
            return self.sede_principal_capacidad_maxima
        elif sede == 'sede_2':
            return self.sede_2_capacidad_maxima
        return 10  # Default

    def get_horarios_sede(self, sede):
        """Devuelve los horarios de una sede específica"""
        if sede == 'sede_principal':
            return self.sede_principal_horarios
        elif sede == 'sede_2':
            return self.sede_2_horarios
        return ""

    def sede_puede_enviar_marketing(self, sede):
        """Verifica si una sede puede enviar emails de marketing"""
        if sede == 'sede_principal':
            return self.enviar_marketing_sede_principal
        elif sede == 'sede_2':
            return self.enviar_marketing_sede_2
        return True

    def get_mensaje_sede(self, sede):
        """Devuelve el mensaje específico de una sede"""
        if sede == 'sede_principal':
            return self.mensaje_sede_principal or self.mensaje_bienvenida
        elif sede == 'sede_2':
            return self.mensaje_sede_2 or self.mensaje_bienvenida
        return self.mensaje_bienvenida

    def get_info_completa_sede(self, sede):
        """Devuelve toda la información de una sede en un diccionario"""
        if sede == 'sede_principal':
            return {
                'nombre': 'Sede Principal - La Rioja 3044',
                'direccion': 'La Rioja 3044',
                'telefono': self.get_telefono_sede('sede_principal'),
                'email': self.get_email_sede('sede_principal'),
                'horarios': self.get_horarios_sede('sede_principal'),
                'capacidad_maxima': self.sede_principal_capacidad_maxima,
                'activa': self.sede_principal_activa,
                'mensaje': self.get_mensaje_sede('sede_principal')
            }
        elif sede == 'sede_2':
            return {
                'nombre': 'Sede 2 - 9 de julio 3698',
                'direccion': '9 de julio 3698',
                'telefono': self.get_telefono_sede('sede_2'),
                'email': self.get_email_sede('sede_2'),
                'horarios': self.get_horarios_sede('sede_2'),
                'capacidad_maxima': self.sede_2_capacidad_maxima,
                'activa': self.sede_2_activa,
                'mensaje': self.get_mensaje_sede('sede_2')
            }
        return {}

    def __str__(self):
        return f"Configuración de {self.nombre_estudio}"

    class Meta:
        verbose_name = "Configuración del Estudio"
        verbose_name_plural = "Configuración del Estudio"