from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from .models import Clase
import logging

logger = logging.getLogger(__name__)

def enviar_email_cancelacion_reserva(reserva, motivo=None, motivo_detalle=None, 
                                   ofrecer_reemplazo=False, ofrecer_otras_sedes=False):
    """
    Envía un email al usuario notificando la cancelación de su reserva.
    
    Args:
        reserva: Objeto Reserva que fue cancelada
        motivo: Motivo de la cancelación
        motivo_detalle: Detalle adicional del motivo
        ofrecer_reemplazo: Boolean si se deben sugerir clases alternativas
        ofrecer_otras_sedes: Boolean si se incluyen otras sedes en las sugerencias
    
    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    
    try:
        # Verificar que el usuario tenga email
        if not reserva.usuario.email:
            logger.warning(f"Usuario {reserva.usuario.username} no tiene email configurado")
            return False
        
        # Obtener clases alternativas si se solicita
        clases_alternativas = []
        if ofrecer_reemplazo:
            clases_alternativas = obtener_clases_alternativas(
                reserva.clase, 
                incluir_otras_sedes=ofrecer_otras_sedes
            )
        
        # Preparar el contexto para el template
        domain_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        
        context = {
            'reserva': reserva,
            'motivo': motivo,
            'motivo_detalle': motivo_detalle,
            'ofrecer_reemplazo': ofrecer_reemplazo,
            'clases_alternativas': clases_alternativas,
            'domain_url': domain_url,
            'studio_name': 'Pilates Gravity',
            'studio_phone': '+54 342 511 4448',
            'studio_email': 'pilatesgravity@gmail.com',
        }
        
        # Renderizar los templates
        subject = render_to_string(
            'gravity/emails/reserva_cancelada_subject.txt', 
            context
        ).strip()
        
        html_message = render_to_string(
            'gravity/emails/reserva_cancelada_email.html',
            context
        )
        
        # Crear el email
        email = EmailMultiAlternatives(
            subject=subject,
            body=f"Tu reserva {reserva.numero_reserva} ha sido cancelada. "
                 f"Por favor revisa el email en formato HTML para más detalles.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        
        # Adjuntar la versión HTML
        email.attach_alternative(html_message, "text/html")
        
        # Enviar el email
        email.send(fail_silently=False)
        
        logger.info(f"Email de cancelación enviado exitosamente a {reserva.usuario.email} "
                   f"para reserva {reserva.numero_reserva}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de cancelación para reserva {reserva.numero_reserva}: {str(e)}")
        return False

def obtener_clases_alternativas(clase_cancelada, incluir_otras_sedes=False, limite=5):
    """
    Obtiene clases alternativas para sugerir al usuario.
    
    Args:
        clase_cancelada: La clase que fue cancelada
        incluir_otras_sedes: Si incluir clases de otras sedes
        limite: Número máximo de alternativas a devolver
    
    Returns:
        QuerySet: Clases alternativas disponibles
    """
    
    # Comenzar con clases activas que no sean la cancelada
    queryset = Clase.objects.filter(
        activa=True
    ).exclude(
        id=clase_cancelada.id
    )
    
    # Si no incluir otras sedes, filtrar por la misma sede
    if not incluir_otras_sedes:
        queryset = queryset.filter(direccion=clase_cancelada.direccion)
    
    # Filtrar solo clases con cupos disponibles
    clases_con_cupos = []
    for clase in queryset.order_by('direccion', 'dia', 'horario'):
        if clase.cupos_disponibles() > 0:
            clases_con_cupos.append(clase)
            if len(clases_con_cupos) >= limite:
                break
    
    return clases_con_cupos

def enviar_email_confirmacion_reserva(reserva):
    """
    Envía un email de confirmación cuando se crea una nueva reserva.
    
    Args:
        reserva: Objeto Reserva que fue creada
    
    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    
    try:
        # Verificar que el usuario tenga email
        if not reserva.usuario.email:
            logger.warning(f"Usuario {reserva.usuario.username} no tiene email configurado")
            return False
        
        # Preparar el contexto
        domain_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        
        context = {
            'reserva': reserva,
            'domain_url': domain_url,
            'proxima_clase_info': reserva.get_proxima_clase_info(),
        }
        
        # Subject simple para confirmación
        subject = f"[Pilates Gravity] Confirmación de reserva {reserva.numero_reserva}"
        
        # Mensaje simple para confirmaciones
        message = f"""
            Hola {reserva.usuario.first_name or reserva.usuario.username},

            ¡Tu reserva ha sido confirmada exitosamente!

            Detalles de tu reserva:
            • Número de reserva: {reserva.numero_reserva}
            • Clase: {reserva.clase.get_nombre_display()}
            • Día y horario: {reserva.clase.dia} a las {reserva.clase.horario.strftime('%H:%M')}
            • Sede: {reserva.clase.get_direccion_display()}

            Esta es una reserva recurrente, por lo que asistirás cada {reserva.clase.dia} a esta clase hasta que decidas cancelarla.

            Puedes gestionar tus reservas en: {domain_url}{reverse('accounts:mis_reservas')}

            ¡Te esperamos en Pilates Gravity!

            Saludos,
            El equipo de Pilates Gravity
            """
        
        # Enviar email simple
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reserva.usuario.email],
            fail_silently=False,
        )
        
        logger.info(f"Email de confirmación enviado exitosamente a {reserva.usuario.email} "
                   f"para reserva {reserva.numero_reserva}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de confirmación para reserva {reserva.numero_reserva}: {str(e)}")
        return False

def enviar_recordatorio_clase(reserva, horas_antes=24):
    """
    Envía un recordatorio de clase al usuario.
    Esta función se puede usar con una tarea programada (celery, cron, etc.)
    
    Args:
        reserva: Objeto Reserva para recordar
        horas_antes: Número de horas antes de la clase para enviar el recordatorio
    
    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    
    try:
        if not reserva.usuario.email or not reserva.activa:
            return False
        
        # Verificar si el usuario acepta recordatorios
        try:
            if hasattr(reserva.usuario, 'profile') and not reserva.usuario.profile.acepta_recordatorios:
                return False
        except:
            pass  # Si no hay perfil, asumir que acepta recordatorios
        
        subject = f"[Pilates Gravity] Recordatorio: Tu clase de mañana"
        
        message = f"""
            Hola {reserva.usuario.first_name or reserva.usuario.username},

            ¡Te recordamos tu clase de Pilates de mañana!

            Detalles:
            • Clase: {reserva.clase.get_nombre_display()}
            • Día y horario: {reserva.clase.dia} a las {reserva.clase.horario.strftime('%H:%M')}
            • Sede: {reserva.clase.get_direccion_display()}

            Consejos para tu clase:
            • Llega 10 minutos antes
            • Trae una botella de agua
            • Usa ropa cómoda para ejercitarte

            Si necesitas cancelar, recuerda que debes hacerlo con al menos 12 horas de anticipación.

            ¡Te esperamos en Pilates Gravity!

            Saludos,
            El equipo de Pilates Gravity
            """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reserva.usuario.email],
            fail_silently=False,
        )
        
        logger.info(f"Recordatorio enviado exitosamente a {reserva.usuario.email} "
                   f"para reserva {reserva.numero_reserva}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando recordatorio para reserva {reserva.numero_reserva}: {str(e)}")
        return False