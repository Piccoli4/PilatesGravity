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
        Verifica si la reserva puede modificarse (3 horas de anticipación).
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
        
        # Verificar si faltan más de 3 horas
        tiempo_limite = proxima_fecha_clase - timedelta(hours=3)
        
        if hoy >= tiempo_limite:
            horas_restantes = (proxima_fecha_clase - hoy).total_seconds() / 3600
            return False, f"Solo puedes modificar tu reserva con 3 horas de anticipación. Próxima clase en {horas_restantes:.1f} horas."
        
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

    @staticmethod
    def contar_reservas_usuario_semana(usuario, fecha_inicio_semana=None):
        """
        Cuenta las reservas activas de un usuario en una semana específica
        """
        if fecha_inicio_semana is None:
            # Obtener el lunes de la semana actual
            hoy = timezone.now().date()
            fecha_inicio_semana = hoy - timedelta(days=hoy.weekday())
        
        fecha_fin_semana = fecha_inicio_semana + timedelta(days=5)  # Hasta sábado
        
        # Mapear días de la semana
        dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
        
        reservas_count = Reserva.objects.filter(
            usuario=usuario,
            activa=True,
            clase__dia__in=dias_semana
        ).count()
        
        return reservas_count

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

    def __str__(self):
        estado = "Activo" if self.activo else "Inactivo"
        return f"{self.nombre} - ${self.precio_mensual} ({estado})"

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
        Calcula qué plan debería tener según sus reservas activas.
        Retorna el PlanPago correspondiente o None.
        """
        try:
            # Contar reservas activas del usuario
            reservas_activas = self.usuario.reservas_pilates.filter(activa=True).count()
            
            if reservas_activas == 0:
                return None
            
            # Buscar el plan que corresponde a esa cantidad de clases
            plan = PlanPago.objects.filter(
                clases_por_semana=reservas_activas,
                activo=True
            ).first()
            
            return plan
            
        except Exception:
            return None

    def actualizar_plan_automatico(self):
        """
        Actualiza automáticamente el plan según las reservas actuales.
        """
        plan_correcto = self.calcular_plan_segun_reservas()
        
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

    def _obtener_saldo_mes_anterior(self):
        """
        Obtiene el saldo que tenía el cliente al final del mes anterior
        """
        # Por simplicidad, usaremos el saldo_actual actual como base
        # En un sistema más complejo tendríamos un historial mensual
        return self.saldo_actual
        
        return nuevo_saldo

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
            
            # Actualizar saldo (sumar el pago al saldo actual)
            estado_cliente.saldo_actual += self.monto
            
            # Actualizar plan según reservas actuales
            estado_cliente.actualizar_plan_automatico()
            
            # Guardar cambios
            estado_cliente.save()
            
        except Exception as e:
            # Log del error pero no fallar la operación
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error actualizando estado de cliente en pago {self.id}: {str(e)}")

    def get_nombre_completo_cliente(self):
        """Devuelve el nombre completo del cliente"""
        if not self.cliente:
            return "Cliente no especificado"
        
        if self.cliente.first_name and self.cliente.last_name:
            return f"{self.cliente.first_name} {self.cliente.last_name}"
        return self.cliente.username

    def __str__(self):
        return f"Pago ${self.monto} - {self.get_nombre_completo_cliente()} - {self.fecha_pago}"

    class Meta:
        verbose_name = "Registro de Pago"
        verbose_name_plural = "Registros de Pagos"
        ordering = ['-fecha_pago', '-fecha_registro']

# Señales para actualizar automáticamente el estado de pagos cuando cambian las reservas
@receiver(post_save, sender=Reserva)
def actualizar_estado_pago_por_reserva(sender, instance, created, **kwargs):
    """
    Actualiza el estado de pago cuando se crea o modifica una reserva.
    """
    try:
        estado_cliente, created_estado = EstadoPagoCliente.objects.get_or_create(
            usuario=instance.usuario,
            defaults={'activo': True}
        )
        
        # Actualizar plan según reservas actuales
        estado_cliente.actualizar_plan_automatico()
        
    except Exception as e:
        # Log del error pero no fallar la operación
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando estado de pago por reserva {instance.id}: {str(e)}")

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
    
