from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from .models import Clase, Reserva
import logging
import os

logger = logging.getLogger(__name__)

# ==============================================================================
# CANCELACIÓN DE RESERVA
# ==============================================================================

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
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')
        
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

# ==============================================================================
# CONFIRMACIÓN DE CLASES ALTERNATIVAS
# ==============================================================================

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

# ==============================================================================
# CONFIRMACIÓN DE RESERVA
# ==============================================================================

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
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')
        
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

# ==============================================================================
# RECORDATORIO DE CLASE
# ==============================================================================

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

            Si necesitas cancelar, recuerda que debes hacerlo con al menos 3 horas de anticipación.

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

# ==============================================================================
# EMAILS COMPLETOS CON TEMPLATES HTML
# ==============================================================================

def enviar_email_bienvenida_completo(usuario):
    """
    Envía un email de bienvenida completo con template HTML.
    
    Args:
        usuario: Objeto User que se registró
    
    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    
    try:
        if not usuario.email:
            logger.warning(f"Usuario {usuario.username} no tiene email configurado")
            return False
        
        # Preparar el contexto para el template
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')
        
        context = {
            'usuario': usuario,
            'domain_url': domain_url,
            'studio_name': 'Pilates Gravity',
            'studio_phone': '+54 342 511 4448',
            'studio_email': 'pilatesgravity@gmail.com',
        }
        
        # Renderizar los templates
        subject = render_to_string(
            'gravity/emails/bienvenida_subject.txt',
            context
        ).strip()
        
        html_message = render_to_string(
            'gravity/emails/bienvenida_email.html',
            context
        )
        
        # Crear versión de texto plano
        plain_message = crear_email_bienvenida_texto_plano(context)
        
        # Crear el email
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[usuario.email],
        )
        
        # Adjuntar la versión HTML
        email.attach_alternative(html_message, "text/html")
        
        # Enviar el email
        email.send(fail_silently=False)
        
        logger.info(f"Email de bienvenida enviado exitosamente a {usuario.email}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de bienvenida para usuario {usuario.username}: {str(e)}")
        return False

def crear_email_bienvenida_texto_plano(context):
    """
    Crea la versión de texto plano del email de bienvenida.
    
    Args:
        context: Diccionario con datos del template
    
    Returns:
        String: Email en formato texto plano
    """
    
    usuario = context['usuario']
    domain_url = context['domain_url']
    
    texto_plano = f"""
        ¡BIENVENIDO A PILATES GRAVITY!
        ==============================

        ¡Hola {usuario.first_name or usuario.username}!

        ¡Bienvenido a la familia de Pilates Gravity! Estamos emocionados de acompañarte en tu viaje hacia el bienestar y la fortaleza.

        TUS PRÓXIMOS PASOS:
        1. Completa tu perfil: {domain_url}/accounts/profile/
        2. Reserva tu primera clase: {domain_url}/reservar-clase/
        3. Conoce nuestros horarios: {domain_url}/clases-disponibles/

        NUESTRAS SEDES:
        • Sede Principal: La Rioja 3044, Capital, Santa Fe
        • Sede 2: 9 de julio 3696, Capital, Santa Fe

        CONTACTO:
        📞 +54 342 511 4448
        📧 pilatesgravity@gmail.com
        💬 WhatsApp: https://wa.me/543425114448

        ¡Te esperamos en el estudio!

        Con amor,
        El equipo de Pilates Gravity 💙
    """
    
    return texto_plano.strip()

def enviar_email_confirmacion_pago_completo(pago):
    """
    Envía un email de confirmación de pago completo con template HTML.

    Args:
        pago: Objeto RegistroPago

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not pago.cliente or not pago.cliente.email:
            logger.warning(f"Pago {pago.id} sin cliente o email configurado")
            return False

        from .models import EstadoPagoCliente
        estado_pago, created = EstadoPagoCliente.objects.get_or_create(
            usuario=pago.cliente,
            defaults={'activo': True}
        )

        saldo_anterior = estado_pago.saldo_actual - pago.monto
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'usuario': pago.cliente,
            'pago': pago,
            'estado_pago': estado_pago,
            'saldo_anterior': saldo_anterior,
            'saldo_actual': estado_pago.saldo_actual,
            'plan_actual': estado_pago.plan_actual,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/confirmacion_pago_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/confirmacion_pago_email.html',
            context
        )

        nombre = pago.cliente.first_name or pago.cliente.username
        if estado_pago.saldo_actual > 0:
            estado_saldo = f"${estado_pago.saldo_actual} (a favor)"
        elif estado_pago.saldo_actual == 0:
            estado_saldo = f"${estado_pago.saldo_actual} (al día)"
        else:
            estado_saldo = f"${estado_pago.saldo_actual} (pendiente)"

        text_message = (
            f"¡Pago confirmado! ✅\n\n"
            f"Hola {nombre},\n\n"
            f"Recibimos tu pago exitosamente.\n\n"
            f"Detalles del pago:\n"
            f"  Fecha:     {pago.fecha_pago.strftime('%d/%m/%Y')}\n"
            f"  Método:    {pago.get_tipo_pago_display()}\n"
            f"  Concepto:  {pago.concepto}\n"
            f"  Monto:     ${pago.monto}\n"
            f"  N° recibo: #{pago.id:06d}\n\n"
            f"Estado de cuenta:\n"
            f"  Saldo anterior: ${saldo_anterior}\n"
            f"  Pago recibido:  +${pago.monto}\n"
            f"  Saldo actual:   {estado_saldo}\n\n"
            f"Pilates Gravity · La Rioja 3044 y 9 de Julio 3698, Santa Fe\n"
            f"pilatesgravity@gmail.com · +54 342 511 4448"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[pago.cliente.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de confirmación de pago enviado a {pago.cliente.email} "
            f"— pago ID {pago.id}, monto ${pago.monto}"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando email de confirmación de pago ID {pago.id}: {str(e)}")
        return False

def crear_email_pago_texto_plano(context):
    """
    Crea la versión de texto plano del email de confirmación de pago.
    
    Args:
        context: Diccionario con los datos del template
    
    Returns:
        String: Contenido del email en texto plano
    """
    
    usuario = context['usuario']
    pago = context['pago']
    saldo_anterior = context['saldo_anterior']
    saldo_actual = context['saldo_actual']
    plan_actual = context['plan_actual']
    
    # Determinar estado del saldo
    if saldo_actual > 0:
        estado_saldo = f"${saldo_actual} (Crédito a favor)"
    elif saldo_actual == 0:
        estado_saldo = f"${saldo_actual} (Al día)"
    else:
        estado_saldo = f"${saldo_actual} (Pendiente)"
    
    texto_plano = f"""
        ¡Pago Confirmado! ✅

        Hola {usuario.first_name or usuario.username}!

        ¡Hemos recibido tu pago exitosamente!
        Gracias por confiar en Pilates Gravity.

        💰 DETALLES DEL PAGO:
        • Fecha: {pago.fecha_pago.strftime('%d/%m/%Y')}
        • Método: {pago.get_tipo_pago_display()}
        • Concepto: {pago.concepto}
        • Monto Total: ${pago.monto}
        {f'• Comprobante: {pago.comprobante}' if pago.comprobante else ''}

        📊 TU ESTADO DE CUENTA:
        • Saldo anterior: ${saldo_anterior}
        • Pago recibido: +${pago.monto}
        • Saldo actual: {estado_saldo}
        {f'• Plan actual: {plan_actual.nombre}' if plan_actual else ''}

        🧾 INFORMACIÓN DE RECIBO:
        • Número de recibo: #{pago.id:06d}
        • Fecha de emisión: {pago.fecha_registro.strftime('%d/%m/%Y %H:%M')}
        • Estado: {pago.get_estado_display()}

        🎯 ¿QUÉ PUEDES HACER AHORA?
        • Ver tu perfil: {context['domain_url']}/accounts/profile/
        • Reservar una clase: {context['domain_url']}/reservar-clase/
        • Ver horarios: {context['domain_url']}/clases-disponibles/

        📍 NUESTRAS SEDES:

        🏢 Sede Principal
        📍 La Rioja 3044, Capital, Santa Fe
        📞 +54 342 511 4448
        🕘 Lunes a Viernes 8:00 - 20:00

        🏢 Sede 2
        📍 9 de julio 3696, Capital, Santa Fe
        📞 +54 342 511 4448
        🕘 Lunes a Viernes 8:00 - 20:00

        💬 ¿Tienes alguna consulta sobre tu pago?
        WhatsApp: +54 342 511 4448
        Email: pilatesgravity@gmail.com
        Sitio Web: {context['domain_url']}

        🙏 ¡Gracias por elegirnos!
        Tu confianza y compromiso con tu bienestar nos motiva a seguir
        brindándote el mejor servicio.

        ---
        Con cariño y bienestar,
        💙 El equipo completo de Pilates Gravity

        🏢 Sede Principal: La Rioja 3044, Capital, Santa Fe
        🏢 Sede 2: 9 de julio 3696, Capital, Santa Fe
        📧 pilatesgravity@gmail.com | 📱 +54 342 511 4448

        Este es un comprobante automático. Conserva este email como
        comprobante de tu pago.
    """
    
    return texto_plano.strip()

# ==============================================================================
# EMAIL DE CONFIRMACIÓN DE RESERVA
# ==============================================================================

def enviar_email_confirmacion_reserva_detallado(reserva):
    """
    Envía un email de confirmación detallado cuando se crea una nueva reserva.
    
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
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')
        proxima_clase_info = reserva.get_proxima_clase_info()
        
        # Determinar si es hoy, mañana o días restantes
        es_hoy, es_manana, dias_restantes = calcular_tiempo_proxima_clase(reserva)
        
        context = {
            'usuario': reserva.usuario,
            'reserva': reserva,
            'domain_url': domain_url,
            'proxima_clase_info': proxima_clase_info,
            'es_hoy': es_hoy,
            'es_manana': es_manana,
            'dias_restantes': dias_restantes,
            'studio_name': 'Pilates Gravity',
            'studio_phone': '+54 342 511 4448',
            'studio_email': 'pilatesgravity@gmail.com',
        }
        
        # Renderizar los templates
        subject = render_to_string(
            'gravity/emails/confirmacion_reserva_subject.txt',
            context
        ).strip()
        
        html_message = render_to_string(
            'gravity/emails/confirmacion_reserva_email.html',
            context
        )
        
        # Crear versión de texto plano
        plain_message = crear_email_reserva_texto_plano(context)
        
        # Crear el email
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        
        # Adjuntar la versión HTML
        email.attach_alternative(html_message, "text/html")
        
        # Enviar el email
        email.send(fail_silently=False)
        
        logger.info(f"Email de confirmación de reserva enviado exitosamente a {reserva.usuario.email} "
                f"para reserva {reserva.numero_reserva}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de confirmación de reserva {reserva.numero_reserva}: {str(e)}")
        return False

def calcular_tiempo_proxima_clase(reserva):
    """
    Calcula si la próxima clase es hoy, mañana o en cuántos días.
    
    Args:
        reserva: Objeto Reserva
        
    Returns:
        Tuple: (es_hoy, es_manana, dias_restantes)
    """
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    try:
        hoy = timezone.now()
        dias_semana = {
            'Lunes': 0, 'Martes': 1, 'Miércoles': 2, 'Jueves': 3, 'Viernes': 4, 'Sábado': 5
        }
        
        dia_clase = dias_semana.get(reserva.clase.dia)
        if dia_clase is None:
            return False, False, 7
        
        # Encontrar la próxima fecha de esta clase
        dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
        if dias_hasta_clase == 0:  # Es hoy
            proxima_clase = hoy.replace(
                hour=reserva.clase.horario.hour,
                minute=reserva.clase.horario.minute,
                second=0,
                microsecond=0
            )
            if proxima_clase <= hoy:  # La clase ya pasó hoy
                dias_hasta_clase = 7
        
        es_hoy = (dias_hasta_clase == 0)
        es_manana = (dias_hasta_clase == 1)
        dias_restantes = dias_hasta_clase if dias_hasta_clase > 1 else 0
        
        return es_hoy, es_manana, dias_restantes
        
    except Exception:
        return False, False, 7

def crear_email_reserva_texto_plano(context):
    """
    Crea la versión de texto plano del email de confirmación de reserva.
    
    Args:
        context: Diccionario con los datos del template
    
    Returns:
        String: Contenido del email en texto plano
    """
    
    usuario = context['usuario']
    reserva = context['reserva']
    proxima_clase_info = context['proxima_clase_info']
    es_hoy = context['es_hoy']
    es_manana = context['es_manana']
    dias_restantes = context['dias_restantes']
    
    # Determinar mensaje de tiempo
    if es_hoy:
        tiempo_msg = "🚨 ¡Es HOY! - No te la pierdas"
    elif es_manana:
        tiempo_msg = "⏳ ¡Es MAÑANA!"
    elif dias_restantes > 0:
        tiempo_msg = f"📅 En {dias_restantes} días"
    else:
        tiempo_msg = "📅 Próximamente"
    
    texto_plano = f"""
        ¡RESERVA CONFIRMADA! - PILATES GRAVITY
        =====================================

        ¡Hola {usuario.first_name or usuario.username}!

        🎉 ¡Tu reserva ha sido confirmada exitosamente!

        📋 DETALLES DE TU RESERVA:
        • Número: {reserva.numero_reserva}
        • Clase: {reserva.clase.get_nombre_display()}
        • Día: {reserva.clase.dia}
        • Horario: {reserva.clase.horario.strftime('%H:%M')}
        • Sede: {reserva.clase.get_direccion_display()}
        • Estado: Activa y confirmada ✅

        {tiempo_msg}
        {proxima_clase_info}

        📍 UBICACIÓN:
        {reserva.clase.get_direccion_display()}
        Teléfono: +54 342 511 4448

        ⚡ ACCIONES RÁPIDAS:
        • Ver tu reserva: {context['domain_url']}/reserva/{reserva.numero_reserva}/
        • Todas tus reservas: {context['domain_url']}/accounts/mis-reservas/
        • Modificar clase: {context['domain_url']}/reserva/{reserva.numero_reserva}/modificar/
        • Cancelar reserva: {context['domain_url']}/reserva/{reserva.numero_reserva}/cancelar/

        🧘‍♀️ CONSEJOS PARA TU CLASE:
        • Llega 10 minutos antes
        • Trae ropa cómoda y una botella de agua
        • Informa sobre cualquier lesión o condición médica
        • ¡Ven con ganas de disfrutar y aprender!

        📞 ¿NECESITAS AYUDA?
        WhatsApp: +54 342 511 4448
        Email: pilatesgravity@gmail.com
        Web: {context['domain_url']}

        ⚠️ IMPORTANTE: Esta es una reserva recurrente. Asistirás todos los 
        {reserva.clase.dia} a esta clase hasta que decidas cancelarla.

        Si necesitas cancelar o modificar, hazlo con al menos 3 horas de 
        anticipación desde tu perfil web.

        💪 ¡Te esperamos en el estudio!
        Cada clase es una oportunidad de crecimiento y bienestar.

        ---
        Con amor y energía positiva,
        💙 Todo el equipo de Pilates Gravity
        👩‍🏫 Nicolás, Camila y nuestros instructores

        🏢 Sede Principal: La Rioja 3044, Capital, Santa Fe
        🏢 Sede 2: 9 de julio 3696, Capital, Santa Fe
        📧 pilatesgravity@gmail.com | 📱 +54 342 511 4448
    """
    
    return texto_plano.strip()

# ==============================================================================
# EMAIL DE DESPEDIDA
# ==============================================================================

def enviar_email_despedida_completo(usuario):
    """
    Envía un email de despedida completo con template HTML.

    Args:
        usuario: Objeto User que eliminó su cuenta

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not usuario.email:
            logger.warning(f"Usuario {usuario.username} no tiene email configurado")
            return False

        estadisticas = calcular_estadisticas_usuario_despedida(usuario)
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'usuario': usuario,
            'estadisticas': estadisticas,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/despedida_subject.txt',
            context
        ).strip()

        import base64
        logo_base64 = ''
        banner_base64 = ''

        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'solo_logo_blanco.webp')
        banner_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_gravity.webp')

        try:
            with open(logo_path, 'rb') as f:
                logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except FileNotFoundError:
            logger.warning(f"Logo no encontrado en {logo_path}.")

        try:
            with open(banner_path, 'rb') as f:
                banner_base64 = base64.b64encode(f.read()).decode('utf-8')
        except FileNotFoundError:
            logger.warning(f"Banner no encontrado en {banner_path}.")

        context['logo_base64'] = logo_base64
        context['banner_base64'] = banner_base64

        html_message = render_to_string(
            'gravity/emails/despedida_email.html',
            context
        )

        nombre = usuario.first_name or usuario.username
        text_message = (
            f"¡Hasta pronto, {nombre}!\n\n"
            f"Gracias por haber sido parte de Pilates Gravity. "
            f"Esperamos haber sido un espacio de bienestar, energía y conexión para vos.\n\n"
            f"Tu recorrido con nosotros:\n"
            f"  Clases reservadas: {estadisticas.get('total_reservas', 0)}\n"
            f"  Tiempo con nosotros: {estadisticas.get('tiempo_texto', '-')}\n"
            f"  Clase favorita: {estadisticas.get('clase_favorita', 'Pilates')}\n\n"
            f"Cuando quieras volver, acá vamos a estar: {domain_url}\n\n"
            f"Pilates Gravity · La Rioja 3044 y 9 de Julio 3698, Santa Fe\n"
            f"pilatesgravity@gmail.com · +54 342 511 4448"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        _adjuntar_imagenes_inline(email)
        email.send(fail_silently=False)

        logger.info(f"Email de despedida enviado a {usuario.email}")
        return True

    except Exception as e:
        logger.error(f"Error enviando email de despedida para {usuario.username}: {str(e)}")
        return False

def calcular_estadisticas_usuario_despedida(usuario):
    """
    Calcula las estadísticas del usuario para el email de despedida.
    
    Args:
        usuario: Objeto User
    
    Returns:
        Dict: Estadísticas del usuario
    """
    from django.utils import timezone
    
    try:
        # Contar reservas
        total_reservas = usuario.reservas_pilates.count()
        reservas_completadas = usuario.reservas_pilates.filter(activa=False).count()
        reservas_activas = usuario.reservas_pilates.filter(activa=True).count()
        
        # Calcular tiempo en el estudio
        fecha_registro = usuario.date_joined
        tiempo_en_estudio = timezone.now() - fecha_registro
        dias_en_estudio = tiempo_en_estudio.days
        
        # Calcular meses aproximados
        if dias_en_estudio > 30:
            meses_en_estudio = dias_en_estudio // 30
            tiempo_texto = f"{meses_en_estudio} mes{'es' if meses_en_estudio > 1 else ''}"
        else:
            tiempo_texto = f"{dias_en_estudio} días"
        
        # Clase más frecuente
        clases_frecuencias = {}
        for reserva in usuario.reservas_pilates.all():
            clase_tipo = reserva.clase.get_nombre_display()
            clases_frecuencias[clase_tipo] = clases_frecuencias.get(clase_tipo, 0) + 1
        
        clase_favorita = max(clases_frecuencias.items(), key=lambda x: x[1])[0] if clases_frecuencias else "Pilates"
        
        return {
            'total_reservas': total_reservas,
            'reservas_completadas': reservas_completadas,
            'reservas_activas': reservas_activas,
            'dias_en_estudio': dias_en_estudio,
            'tiempo_texto': tiempo_texto,
            'clase_favorita': clase_favorita,
        }
        
    except Exception:
        return {
            'total_reservas': 0,
            'reservas_completadas': 0,
            'reservas_activas': 0,
            'dias_en_estudio': 0,
            'tiempo_texto': 'poco tiempo',
            'clase_favorita': 'Pilates',
        }

def obtener_info_proxima_clase(reserva):
    """
    Obtiene información detallada sobre cuándo es la próxima clase.
    
    Args:
        reserva: Objeto Reserva
    
    Returns:
        Dict: Información sobre la próxima clase
    """
    from django.utils import timezone
    from datetime import datetime, timedelta
    
    hoy = timezone.now()
    
    # Mapear días de la semana
    dias_semana = {
        'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
        'Jueves': 3, 'Viernes': 4, 'Sábado': 5, 'Domingo': 6
    }
    
    dia_clase = dias_semana.get(reserva.clase.dia)
    if dia_clase is None:
        return {
            'es_hoy': False,
            'es_manana': False,
            'dias_restantes': 0,
            'fecha_proxima': None,
            'descripcion': 'Día inválido'
        }
    
    # Encontrar la próxima fecha de esta clase
    dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
    
    if dias_hasta_clase == 0:  # Es hoy
        proxima_clase = hoy.replace(
            hour=reserva.clase.horario.hour,
            minute=reserva.clase.horario.minute,
            second=0,
            microsecond=0
        )
        if proxima_clase <= hoy:  # La clase ya pasó hoy
            dias_hasta_clase = 7
    
    if dias_hasta_clase == 0:
        fecha_proxima_clase = hoy.replace(
            hour=reserva.clase.horario.hour,
            minute=reserva.clase.horario.minute,
            second=0,
            microsecond=0
        )
        es_hoy = True
        es_manana = False
    elif dias_hasta_clase == 1:
        fecha_proxima_clase = hoy + timedelta(days=1)
        fecha_proxima_clase = fecha_proxima_clase.replace(
            hour=reserva.clase.horario.hour,
            minute=reserva.clase.horario.minute,
            second=0,
            microsecond=0
        )
        es_hoy = False
        es_manana = True
    else:
        fecha_proxima_clase = hoy + timedelta(days=dias_hasta_clase)
        fecha_proxima_clase = fecha_proxima_clase.replace(
            hour=reserva.clase.horario.hour,
            minute=reserva.clase.horario.minute,
            second=0,
            microsecond=0
        )
        es_hoy = False
        es_manana = False
    
    # Crear descripción amigable
    if es_hoy:
        descripcion = f"¡Es HOY a las {reserva.clase.horario.strftime('%H:%M')}!"
    elif es_manana:
        descripcion = f"¡Es MAÑANA a las {reserva.clase.horario.strftime('%H:%M')}!"
    else:
        descripcion = f"En {dias_hasta_clase} días ({reserva.clase.dia} {reserva.clase.horario.strftime('%H:%M')})"
    
    return {
        'es_hoy': es_hoy,
        'es_manana': es_manana,
        'dias_restantes': dias_hasta_clase,
        'fecha_proxima': fecha_proxima_clase,
        'descripcion': descripcion,
        'horas_restantes': (fecha_proxima_clase - hoy).total_seconds() / 3600
    }

def crear_email_recordatorio_texto_plano(context):
    """
    Crea la versión de texto plano del email de recordatorio.
    
    Args:
        context: Diccionario con los datos del template
    
    Returns:
        String: Contenido del email en texto plano
    """
    
    reserva = context['reserva']
    proxima_clase_info = context['proxima_clase_info']
    horario_fin = context['horario_fin']
    
    texto_plano = f"""
        ⏰ ¡TU CLASE ES MAÑANA!

        Hola {reserva.usuario.first_name or reserva.usuario.username},

        Este es un recordatorio amigable de que tienes una clase programada
        para MAÑANA. ¡Estamos emocionados de verte!

        📋 DETALLES DE TU CLASE:
        • Tipo: {reserva.clase.get_nombre_display()}
        • Día: {reserva.clase.dia}
        • Horario: {reserva.clase.horario.strftime('%H:%M')} - {horario_fin.strftime('%H:%M')} hs
        • Sede: {reserva.clase.get_direccion_corta()}
        • Reserva N°: {reserva.numero_reserva}
        {f'• Grupo: Máx {reserva.clase.cupo_maximo} personas' if reserva.clase.cupo_maximo else ''}

        ⏱️ ¡Faltan aproximadamente 24 horas para tu clase!

        🎒 QUÉ TRAER:
        • Botella de agua (muy importante)
        • Toalla pequeña personal
        • Ropa cómoda y flexible
        • Medias antideslizantes (opcional)
        • Cabello recogido si es largo

        ⏰ HORARIOS IMPORTANTES:
        • Llega 10 minutos antes
        • Clase puntual a las {reserva.clase.horario.strftime('%H:%M')}
        • Duración: 60 minutos
        • Finaliza a las {horario_fin.strftime('%H:%M')}

        🍽️ RECOMENDACIONES:
        • No comas 2 horas antes
        • Mantente hidratado durante el día
        • Descansa bien la noche anterior
        • Llega con energía positiva

        📍 INFORMACIÓN DE LLEGADA:
    """

    # Agregar información específica por sede
    if reserva.clase.direccion == 'sede_principal':
        texto_plano += f"""
            🏢 Sede Principal
            📍 La Rioja 3044, Capital, Santa Fe
            📞 +54 342 511 4448
            🚗 Estacionamiento disponible en la calle
            🚌 Varias líneas de colectivo - Zona céntrica
            ⏰ Atención: Lun-Vie 8:00-20:00 | Sáb 9:00-13:00
            🚪 Entrada principal - Toca el timbre
        """
    else:
        texto_plano += f"""
            🏢 Sede 2
            📍 9 de julio 3696, Capital, Santa Fe
            📞 +54 342 511 4448
            🚗 Estacionamiento disponible en la zona
            🚌 Acceso por 9 de julio - Buena conectividad
            ⏰ Atención: Lun-Vie 8:00-20:00 | Sáb 9:00-13:00
            🚪 Entrada por 9 de julio - Edificio identificado
        """

    texto_plano += f"""

        💪 ¡ESTAMOS LISTOS PARA TI!
        Mañana será un día increíble para trabajar en tu bienestar.
        Cada clase es una oportunidad de crecimiento, fortalecimiento
        y conexión contigo mismo.

        "El cuerpo alcanza lo que la mente cree.
        ¡Mañana seguimos construyendo la mejor versión de ti!"

        🌟 ¡Nuestro equipo de instructores te está esperando con mucha energía!

        ⚡ ¿NECESITAS HACER ALGO?
        Si por algún motivo no puedes asistir mañana, por favor cancela
        tu reserva con al menos 3 horas de anticipación.

        Ver tu reserva: {context['domain_url']}/reserva/{reserva.numero_reserva}/
        Modificar clase: {context['domain_url']}/reserva/{reserva.numero_reserva}/modificar/
        Cancelar reserva: {context['domain_url']}/reserva/{reserva.numero_reserva}/cancelar/

        ⚠️ IMPORTANTE: Las cancelaciones deben realizarse con 3 horas
        de anticipación. Después de ese tiempo no se podrá cancelar online.

        📞 ¿ALGUNA CONSULTA?
        • WhatsApp: +54 342 511 4448
        • Email: pilatesgravity@gmail.com
        • Web: {context['domain_url']}
        • Teléfono: +54 342 511 4448

        Horarios de atención: Lun-Vie 8:00-20:00 | Sáb 9:00-13:00

        🚀 ¡NOS VEMOS MAÑANA!
        Estamos emocionados de acompañarte en tu viaje de bienestar.
        Cada clase es un paso hacia una versión más fuerte y saludable de ti.

        ¡Prepárate para una clase increíble! 💫

        "Mañana no es solo otro día, es otra oportunidad de ser extraordinario."

        ---
        ¡Te esperamos con mucha energía!
        💙 Todo el equipo de Pilates Gravity
        👩‍🏫 Nicolás, Camila y nuestros increíbles instructores

        🏢 Sede Principal: La Rioja 3044 | Sede 2: 9 de julio 3696
        📧 pilatesgravity@gmail.com | 📱 +54 342 511 4448

        Este recordatorio se envía automáticamente 24h antes de tu clase.
    """
    
    return texto_plano.strip()

def enviar_recordatorios_automaticos():
    """
    Función para enviar recordatorios automáticos a todas las reservas
    que tienen clase en las próximas 24 horas.
    Esta función se puede ejecutar con un cron job o tarea programada.
    """
    from django.utils import timezone
    from datetime import timedelta
    
    enviados_exitosos = 0
    errores = 0
    
    try:
        # Obtener todas las reservas activas
        reservas_activas = Reserva.objects.filter(
            activa=True,
            clase__activa=True
        ).select_related('usuario', 'clase')
        
        logger.info(f"Procesando {reservas_activas.count()} reservas activas para recordatorios")
        
        for reserva in reservas_activas:
            try:
                # Verificar si la clase es mañana
                info_proxima = obtener_info_proxima_clase(reserva)
                
                if info_proxima['es_manana']:
                    # Enviar recordatorio
                    if enviar_email_recordatorio_clase_completo(reserva):
                        enviados_exitosos += 1
                    else:
                        errores += 1
                        
            except Exception as e:
                logger.error(f"Error procesando recordatorio para reserva {reserva.numero_reserva}: {str(e)}")
                errores += 1
        
        logger.info(f"Recordatorios procesados: {enviados_exitosos} enviados, {errores} errores")
        
        return {
            'enviados': enviados_exitosos,
            'errores': errores,
            'total_procesadas': reservas_activas.count()
        }
        
    except Exception as e:
        logger.error(f"Error en envío de recordatorios automáticos: {str(e)}")
        return {
            'enviados': enviados_exitosos,
            'errores': errores + 1,
            'total_procesadas': 0
        }

def crear_email_despedida_texto_plano(context):
    """
    Crea la versión de texto plano del email de despedida.
    
    Args:
        context: Diccionario con datos del template
    
    Returns:
        String: Email en formato texto plano
    """
    
    usuario = context['usuario']
    estadisticas = context['estadisticas']
    domain_url = context['domain_url']
    
    texto_plano = f"""
        ¡Hasta pronto desde Pilates Gravity! 💙
        =====================================

        Querido/a {usuario.first_name or usuario.username},

        Hemos procesado tu solicitud de eliminación de cuenta. Aunque estamos tristes de verte partir, respetamos completamente tu decisión.

        TU TIEMPO CON NOSOTROS:
        • Tiempo en la familia PG: {estadisticas['tiempo_texto']}
        • Total de reservas realizadas: {estadisticas['total_reservas']}
        • Clases completadas: {estadisticas['reservas_completadas']}
        • Tu clase favorita: {estadisticas['clase_favorita']}

        DATOS ELIMINADOS:
        ✅ Perfil de usuario y datos personales
        ✅ Historial de reservas y pagos
        ✅ Preferencias y configuraciones
        ✅ Toda tu información personal

        ¿CAMBIO DE IDEA?
        Si en el futuro decides volver a Pilates, será como empezar de nuevo:
        • Crear una cuenta nueva: {domain_url}/accounts/signup/
        • Contactarnos: +54 342 511 4448
        • Email: pilatesgravity@gmail.com

        NUESTRAS PUERTAS SIEMPRE ESTARÁN ABIERTAS:
        🏢 Sede Principal: La Rioja 3044, Capital, Santa Fe
        🏢 Sede 2: 9 de julio 3696, Capital, Santa Fe
        📱 WhatsApp: +54 342 511 4448

        MENSAJE DEL EQUIPO:
        Fue un honor acompañarte en tu camino de bienestar. Cada clase que compartiste con nosotros fue especial, y esperamos haber contribuido positivamente a tu vida.

        Llevas contigo todo lo aprendido: la fuerza, la flexibilidad, la conciencia corporal y la confianza que desarrollaste. Eso nadie te lo puede quitar.

        ¡Te deseamos lo mejor en todo lo que viene!
        Y recuerda: aquí siempre tendrás un hogar si decides volver.

        "Una vez parte de Pilates Gravity,
        siempre parte de nuestra familia." 💙

        Con mucho cariño y los mejores deseos,
        Todo el equipo de Pilates Gravity
        👩‍🏫 Nicolás, Camila y todos nuestros instructores

        PD: Este email no requiere respuesta, pero si quieres compartir el motivo de tu partida para ayudarnos a mejorar, siempre estamos dispuestos a escuchar.

        ¡Hasta siempre! 🧘‍♀️✨
    """
    
    return texto_plano.strip()

# ==============================================================================
# EMAIL DE RECORDATORIO DE CLASE (24 HORAS ANTES)
# ==============================================================================

def enviar_email_recordatorio_clase_completo(reserva, horas_antes=24):
    """
    Envía un email de recordatorio de clase completo al usuario 24 horas antes.
    Esta función usa el template HTML completo con todos los detalles.
    
    Args:
        reserva: Objeto Reserva para recordar
        horas_antes: Número de horas antes de la clase para enviar el recordatorio
    
    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    
    try:
        if not reserva.usuario.email or not reserva.activa:
            logger.warning(f"Usuario {reserva.usuario.username} sin email o reserva inactiva para recordatorio")
            return False
        
        # Verificar si el usuario acepta recordatorios
        try:
            if hasattr(reserva.usuario, 'profile') and not reserva.usuario.profile.acepta_recordatorios:
                logger.info(f"Usuario {reserva.usuario.username} no acepta recordatorios")
                return False
        except:
            pass  # Si no hay perfil, asumir que acepta recordatorios
        
        # Verificar que la clase exista y esté activa
        if not reserva.clase or not reserva.clase.activa:
            logger.warning(f"Clase inactiva o inexistente para reserva {reserva.numero_reserva}")
            return False
        
        # Calcular tiempo exacto hasta la clase
        tiempo_info = calcular_tiempo_hasta_clase_completo(reserva.clase)
        
        # Calcular fecha límite para cancelación (3 horas antes)
        fecha_limite_cancelacion = calcular_fecha_limite_cancelacion_completa(reserva.clase)
        
        # Preparar el contexto para el template
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')
        
        context = {
            'usuario': reserva.usuario,
            'clase': reserva.clase,
            'reserva': reserva,
            'numero_reserva': reserva.numero_reserva,
            'horas_restantes': tiempo_info.get('horas_restantes'),
            'minutos_restantes': tiempo_info.get('minutos_restantes'),
            'tiempo_exacto': tiempo_info.get('tiempo_exacto'),
            'fecha_limite_cancelacion': fecha_limite_cancelacion,
            'domain_url': domain_url,
            'studio_name': 'Pilates Gravity',
            'studio_phone': '+54 342 511 4448',
            'studio_email': 'pilatesgravity@gmail.com',
        }
        
        # Renderizar los templates
        subject = render_to_string(
            'gravity/emails/recordatorio_clase_subject.txt',
            context
        ).strip()
        
        html_message = render_to_string(
            'gravity/emails/recordatorio_clase_email.html',
            context
        )
        
        # Crear versión de texto plano
        plain_message = crear_email_recordatorio_completo_texto_plano(context)
        
        # Crear el email
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        
        # Adjuntar la versión HTML
        email.attach_alternative(html_message, "text/html")
        
        # Enviar el email
        email.send(fail_silently=False)
        
        logger.info(f"Email de recordatorio completo enviado exitosamente a {reserva.usuario.email} "
                f"para reserva {reserva.numero_reserva} - Clase: {reserva.clase.get_nombre_display()}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error enviando email de recordatorio completo para reserva {reserva.numero_reserva}: {str(e)}")
        return False

def calcular_tiempo_hasta_clase_completo(clase):
    """
    Calcula el tiempo exacto hasta la próxima clase.
    
    Args:
        clase: Objeto Clase
    
    Returns:
        Dict: Información sobre tiempo restante
    """
    from django.utils import timezone
    from datetime import timedelta
    
    hoy = timezone.now()
    
    # Mapear días de la semana
    dias_semana = {
        'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
        'Jueves': 3, 'Viernes': 4, 'Sábado': 5, 'Domingo': 6
    }
    
    dia_clase = dias_semana.get(clase.dia)
    if dia_clase is None:
        return {'tiempo_exacto': 'Mañana'}
    
    # Encontrar la próxima fecha de esta clase
    dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
    if dias_hasta_clase == 0:  # Es hoy
        proxima_clase = hoy.replace(
            hour=clase.horario.hour,
            minute=clase.horario.minute,
            second=0,
            microsecond=0
        )
        if proxima_clase <= hoy:  # La clase ya pasó hoy
            dias_hasta_clase = 7
    
    if dias_hasta_clase == 0:
        proxima_fecha_clase = hoy.replace(
            hour=clase.horario.hour,
            minute=clase.horario.minute,
            second=0,
            microsecond=0
        )
    else:
        proxima_fecha_clase = hoy + timedelta(days=dias_hasta_clase)
        proxima_fecha_clase = proxima_fecha_clase.replace(
            hour=clase.horario.hour,
            minute=clase.horario.minute,
            second=0,
            microsecond=0
        )
    
    # Calcular diferencia
    diferencia = proxima_fecha_clase - hoy
    horas_total = int(diferencia.total_seconds() // 3600)
    minutos_restantes = int((diferencia.total_seconds() % 3600) // 60)
    
    # Determinar mensaje según el tiempo
    if dias_hasta_clase == 0:
        tiempo_exacto = f"hoy a las {clase.horario.strftime('%H:%M')}"
    elif dias_hasta_clase == 1:
        tiempo_exacto = f"mañana a las {clase.horario.strftime('%H:%M')}"
    else:
        tiempo_exacto = f"en {dias_hasta_clase} días ({clase.dia} a las {clase.horario.strftime('%H:%M')})"
    
    return {
        'horas_restantes': horas_total,
        'minutos_restantes': minutos_restantes,
        'tiempo_exacto': tiempo_exacto,
        'dias_hasta_clase': dias_hasta_clase
    }

def calcular_fecha_limite_cancelacion_completa(clase):
    """
    Calcula la fecha límite para cancelar una reserva (3 horas antes).
    
    Args:
        clase: Objeto Clase
    
    Returns:
        DateTime: Fecha límite para cancelación
    """
    from django.utils import timezone
    from datetime import timedelta
    
    hoy = timezone.now()
    
    # Mapear días de la semana
    dias_semana = {
        'Lunes': 0, 'Martes': 1, 'Miércoles': 2,
        'Jueves': 3, 'Viernes': 4, 'Sábado': 5, 'Domingo': 6
    }
    
    dia_clase = dias_semana.get(clase.dia)
    if dia_clase is None:
        return hoy
    
    # Encontrar la próxima fecha de esta clase
    dias_hasta_clase = (dia_clase - hoy.weekday()) % 7
    if dias_hasta_clase == 0:  # Es hoy
        proxima_clase = hoy.replace(
            hour=clase.horario.hour, 
            minute=clase.horario.minute, 
            second=0, 
            microsecond=0
        )
        if proxima_clase <= hoy:  # La clase ya pasó hoy
            dias_hasta_clase = 7
    
    if dias_hasta_clase == 0:
        proxima_fecha_clase = hoy.replace(
            hour=clase.horario.hour,
            minute=clase.horario.minute,
            second=0,
            microsecond=0
        )
    else:
        proxima_fecha_clase = hoy + timedelta(days=dias_hasta_clase)
        proxima_fecha_clase = proxima_fecha_clase.replace(
            hour=clase.horario.hour,
            minute=clase.horario.minute,
            second=0,
            microsecond=0
        )
    
    # Restar 3 horas para la fecha límite
    fecha_limite = proxima_fecha_clase - timedelta(hours=3)
    
    return fecha_limite

def crear_email_recordatorio_completo_texto_plano(context):
    """
    Crea la versión de texto plano del email de recordatorio completo.
    
    Args:
        context: Diccionario con datos del template
    
    Returns:
        String: Email en formato texto plano
    """
    
    usuario = context['usuario']
    clase = context['clase']
    numero_reserva = context.get('numero_reserva', 'Confirmada')
    tiempo_exacto = context.get('tiempo_exacto', 'mañana')
    domain_url = context.get('domain_url', 'https://pilatesgravity.com.ar')
    
    texto_plano = f"""
        ¡TU CLASE ES MAÑANA! - PILATES GRAVITY
        =======================================

        ¡Hola {usuario.first_name or usuario.username}!

        Te recordamos que {tiempo_exacto} tienes tu clase de Pilates en {clase.get_direccion_corta()}.

        ¡Estamos emocionados de verte en el estudio! 💪

        DETALLES DE TU CLASE:
        --------------------
        🧘‍♀️ Tipo de Clase: {clase.get_nombre_display()}
        📅 Día: {clase.dia}
        🕐 Horario: {clase.horario.strftime('%H:%M')}
        📍 Sede: {clase.get_direccion_corta()}
        🎯 Tu Reserva: {numero_reserva}

        CONSEJOS PARA TU CLASE:
        ----------------------
        🕒 Llega 10 minutos antes para prepararte
        👕 Usa ropa cómoda que te permita moverte libremente
        💧 Trae una botella de agua
        🧘‍♀️ Ven con actitud positiva y mente abierta
        🍽️ Evita comidas pesadas 2 horas antes
        🧦 Si tienes medias antideslizantes, tráelas

        UBICACIÓN Y CONTACTO:
        -------------------
    """

    if clase.direccion == 'sede_principal':
        texto_plano += """
            🏢 Sede Principal: La Rioja 3044, Capital, Santa Fe
            📞 Teléfono: +54 342 511 4448
            🕐 Horarios: Lun-Vie 8:00-20:00 | Sáb 9:00-13:00
            🚗 Estacionamiento disponible en la calle
            🗺️ Google Maps: https://maps.google.com/?q=La+Rioja+3044+Santa+Fe
        """
    else:
        texto_plano += """
            🏢 Sede 2: 9 de julio 3696, Capital, Santa Fe
            📞 Teléfono: +54 342 511 4448
            🕐 Horarios: Lun-Vie 8:00-20:00 | Sáb 9:00-13:00
            🚗 Estacionamiento disponible en la zona
            🗺️ Google Maps: https://maps.google.com/?q=9+de+julio+3696+Santa+Fe
        """

    fecha_limite = context.get('fecha_limite_cancelacion')
    if fecha_limite:
        texto_plano += f"""

            POLÍTICA DE CANCELACIÓN:
            -----------------------
            ⚠️ Si necesitas cancelar o modificar tu reserva, hazlo con al menos 3 horas de anticipación.
            📅 Fecha límite para cancelar: {fecha_limite.strftime('%d/%m/%Y %H:%M')}

            Puedes gestionar tu reserva desde tu perfil o contactándonos por WhatsApp.
        """

    texto_plano += f"""

        ACCIONES RÁPIDAS:
        ----------------
        📋 Ver mis reservas: {domain_url}/accounts/mis-reservas/
        📅 Ver otros horarios: {domain_url}/clases-disponibles/
        💬 WhatsApp: https://wa.me/543425114448
        ✉️ Email: pilatesgravity@gmail.com
        🌐 Sitio Web: {domain_url}

        MENSAJE MOTIVACIONAL:
        --------------------
        💪 Cada clase es una oportunidad para cuidarte y fortalecerte.
        Estamos emocionados de acompañarte en este hermoso viaje hacia el bienestar.

        "Tu cuerpo puede hacerlo. Solo convence a tu mente."

        ¡Nos vemos en el estudio! 🧘‍♀️

        Con amor,
        Todo el equipo de Pilates Gravity 💙
        👩‍🏫 Nicolás, Camila y nuestros instructores

        CONTACTO:
        ---------
        📧 pilatesgravity@gmail.com
        📱 +54 342 511 4448
        🏢 Sede Principal: La Rioja 3044, Capital, Santa Fe
        🏢 Sede 2: 9 de julio 3696, Capital, Santa Fe

        Este es un recordatorio automático. Si no deseas recibir estos emails,
        puedes desactivar las notificaciones en tu perfil.
    """
    
    return texto_plano.strip()

# ==============================================================================
# FUNCIÓN PARA ENVIAR RECORDATORIOS MASIVOS (PARA CRON/CELERY)
# ==============================================================================

def enviar_recordatorios_clases_manana_completo():
    """
    Función para enviar recordatorios a todos los usuarios que tienen clase mañana.
    Esta función se ejecutaría automáticamente con un cron job o Celery.
    
    Returns:
        Dict: Estadísticas del envío
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Reserva
    
    # Obtener mañana como día de la semana
    manana = timezone.now() + timedelta(days=1)
    dia_manana = manana.strftime('%A')
    
    # Mapear días en inglés a español
    dias_mapping = {
        'Monday': 'Lunes',
        'Tuesday': 'Martes',
        'Wednesday': 'Miércoles',
        'Thursday': 'Jueves',
        'Friday': 'Viernes',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo'
    }
    
    dia_manana_es = dias_mapping.get(dia_manana, dia_manana)
    
    # Obtener todas las reservas activas para mañana
    reservas_manana = Reserva.objects.filter(
        activa=True,
        clase__dia=dia_manana_es,
        clase__activa=True,
        usuario__email__isnull=False,
        usuario__is_active=True
    ).select_related('usuario', 'clase')
    
    # Estadísticas
    stats = {
        'total_intentos': 0,
        'emails_enviados': 0,
        'emails_fallidos': 0,
        'sin_email': 0,
        'no_acepta_recordatorios': 0,
        'dia_procesado': dia_manana_es,
        'errores': []
    }
    
    for reserva in reservas_manana:
        stats['total_intentos'] += 1
        
        try:
            # Verificar email
            if not reserva.usuario.email:
                stats['sin_email'] += 1
                continue
            
            # Verificar preferencias de recordatorio
            try:
                if hasattr(reserva.usuario, 'profile') and not reserva.usuario.profile.acepta_recordatorios:
                    stats['no_acepta_recordatorios'] += 1
                    continue
            except:
                pass
            
            # Enviar recordatorio
            resultado = enviar_email_recordatorio_clase_completo(reserva)
            
            if resultado:
                stats['emails_enviados'] += 1
            else:
                stats['emails_fallidos'] += 1
                stats['errores'].append(f"Error enviando a {reserva.usuario.username}")
                
        except Exception as e:
            stats['emails_fallidos'] += 1
            stats['errores'].append(f"Error procesando {reserva.usuario.username}: {str(e)}")
    
    # Log de estadísticas finales
    logger.info(f"Recordatorios procesados para {dia_manana_es}: "
            f"{stats['emails_enviados']} enviados, {stats['emails_fallidos']} fallidos, "
            f"{stats['total_intentos']} intentos totales")
    
    if stats['errores']:
        logger.error(f"Errores en recordatorios: {stats['errores']}")
    
    return stats

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
        if not reserva.usuario.email:
            logger.warning(f"Usuario {reserva.usuario.username} no tiene email configurado")
            return False

        import base64

        clases_alternativas = []
        if ofrecer_reemplazo:
            clases_alternativas = obtener_clases_alternativas(
                reserva.clase,
                incluir_otras_sedes=ofrecer_otras_sedes
            )

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'reserva': reserva,
            'motivo': motivo,
            'motivo_detalle': motivo_detalle,
            'ofrecer_reemplazo': ofrecer_reemplazo,
            'clases_alternativas': clases_alternativas,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/reserva_cancelada_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/reserva_cancelada_email.html',
            context
        )

        text_message = (
            f"Hola {reserva.usuario.first_name or reserva.usuario.username},\n\n"
            f"Tu reserva ha sido cancelada.\n\n"
            f"Detalles:\n"
            f"  Número:  {reserva.numero_reserva}\n"
            f"  Clase:   {reserva.clase.get_nombre_display()}\n"
            f"  Día:     {reserva.clase.dia} a las {reserva.clase.horario.strftime('%H:%M')} hs\n"
            f"  Sede:    {reserva.clase.get_direccion_display()}\n"
            + (f"\nMotivo: {motivo}\n" if motivo else "")
            + (f"{motivo_detalle}\n" if motivo_detalle else "")
            + f"\nPodés reservar una nueva clase en: {domain_url}\n"
            f"Consultas por WhatsApp: +54 342 511 4448\n\n"
            f"El equipo de Pilates Gravity"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de cancelación enviado a {reserva.usuario.email} "
            f"para reserva {reserva.numero_reserva}"
        )
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
        limite: NÃºmero mÃ¡ximo de alternativas a devolver
    
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
        if not reserva.usuario.email:
            logger.warning(f"Usuario {reserva.usuario.username} no tiene email configurado")
            return False

        import base64

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'reserva': reserva,
            'domain_url': domain_url,
            'proxima_clase_info': reserva.get_proxima_clase_info(),
        }

        subject = render_to_string(
            'gravity/emails/confirmacion_reserva_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/confirmacion_reserva_email.html',
            context
        )

        text_message = (
            f"¡Hola {reserva.usuario.first_name or reserva.usuario.username}!\n\n"
            f"Tu reserva ha sido confirmada exitosamente.\n\n"
            f"Detalles:\n"
            f"  Número:  {reserva.numero_reserva}\n"
            f"  Clase:   {reserva.clase.get_nombre_display()}\n"
            f"  Día:     {reserva.clase.dia} a las {reserva.clase.horario.strftime('%H:%M')} hs\n"
            f"  Sede:    {reserva.clase.get_direccion_display()}\n\n"
            f"Esta es una reserva recurrente: asistirás cada {reserva.clase.dia} "
            f"hasta que decidas cancelarla.\n\n"
            f"Gestioná tu reserva en: {domain_url}\n"
            f"Recordá cancelar con al menos 3 horas de anticipación.\n\n"
            f"¡Te esperamos!\n"
            f"El equipo de Pilates Gravity"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de confirmación enviado a {reserva.usuario.email} "
            f"para reserva {reserva.numero_reserva}"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando email de confirmación para reserva {reserva.numero_reserva}: {str(e)}")
        return False

def enviar_recordatorio_clase(reserva, horas_antes=24):
    """
    Envía un recordatorio de clase al usuario.
    Esta función se usa con el cron job de recordatorios.

    Args:
        reserva: Objeto Reserva para recordar
        horas_antes: Número de horas antes de la clase para enviar el recordatorio

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not reserva.usuario.email or not reserva.activa:
            return False

        try:
            if hasattr(reserva.usuario, 'profile') and not reserva.usuario.profile.acepta_recordatorios:
                return False
        except Exception:
            pass

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'reserva': reserva,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/recordatorio_clase_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/recordatorio_clase_email.html',
            context
        )

        text_message = (
            f"¡Hola {reserva.usuario.first_name or reserva.usuario.username}!\n\n"
            f"Te recordamos que mañana tenés clase.\n\n"
            f"Detalles:\n"
            f"  Clase:   {reserva.clase.get_nombre_display()}\n"
            f"  Día:     {reserva.clase.dia} a las {reserva.clase.horario.strftime('%H:%M')} hs\n"
            f"  Sede:    {reserva.clase.get_direccion_display()}\n\n"
            f"Si no podés asistir, cancelá con al menos 3 horas de anticipación.\n"
            f"Gestioná tu reserva en: {domain_url}\n\n"
            f"¡Te esperamos!\n"
            f"El equipo de Pilates Gravity"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Recordatorio enviado a {reserva.usuario.email} "
            f"para reserva {reserva.numero_reserva}"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando recordatorio para reserva {reserva.numero_reserva}: {str(e)}")
        return False

def enviar_email_bienvenida(usuario, is_admin_created=False, password_temporal=None):
    """
    Envía un email de bienvenida a un nuevo usuario.

    Args:
        usuario: Objeto User que se registró
        is_admin_created: Boolean si fue creado por un administrador
        password_temporal: Contraseña temporal si fue creado por admin

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not usuario.email:
            logger.warning(f"Usuario {usuario.username} no tiene email configurado")
            return False

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'usuario': usuario,
            'is_admin_created': is_admin_created,
            'password_temporal': password_temporal,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/bienvenida_subject.txt',
            context
        ).strip()

        text_message = (
            f"¡Hola {usuario.first_name or usuario.username}!\n\n"
            f"Bienvenid@ a Pilates Gravity. Nos alegra que formes parte de nuestra comunidad.\n\n"
            + (
                f"Tus datos de acceso:\n"
                f"  Usuario:    {usuario.username}\n"
                f"  Contraseña: {password_temporal or '(enviada por separado)'}\n\n"
                f"Recomendamos cambiar tu contraseña al ingresar por primera vez.\n\n"
                if is_admin_created else ""
            )
            + f"Visitá nuestro sitio: {domain_url}\n"
            f"WhatsApp: +54 342 511 4448 | pilatesgravity@gmail.com\n\n"
            f"¡Te esperamos!\n"
            f"El equipo de Pilates Gravity"
        )

        html_message = render_to_string(
            'gravity/emails/bienvenida_email.html',
            context
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de bienvenida enviado a {usuario.email} "
            f"(admin_created: {is_admin_created})"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando email de bienvenida para {usuario.username}: {str(e)}")
        return False

# ==============================================================================
# EMAIL DE NOTIFICACIÓN DE CANCELACIÓN A ADMINISTRADORES
# ==============================================================================

def enviar_notificacion_cancelacion_a_admins(reserva, tipo, fecha=None):
    """
    Notifica a los administradores del sistema cuando un cliente cancela una clase.

    Args:
        reserva: Objeto Reserva cancelada
        tipo: 'permanente' o 'temporal'
        fecha: date object (solo para cancelaciones temporales)
    """
    try:
        from django.contrib.auth.models import User

        admins = User.objects.filter(is_staff=True, email__isnull=False).exclude(email='')
        emails_admins = list(admins.values_list('email', flat=True))

        if not emails_admins:
            logger.warning("No hay administradores con email configurado para notificar.")
            return False

        cliente = reserva.get_nombre_completo_usuario()
        clase = reserva.clase.get_nombre_display()
        dia = reserva.clase.dia
        horario = reserva.clase.horario.strftime('%H:%M')
        sede = reserva.clase.get_direccion_corta()
        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        if tipo == 'temporal':
            fecha_str = fecha.strftime('%d/%m/%Y') if fecha else 'fecha desconocida'
            subject = f"Ausencia temporal — {cliente}"
            body = (
                f"El cliente {cliente} registró una ausencia temporal.\n\n"
                f"Clase: {clase}\n"
                f"Día habitual: {dia} a las {horario}\n"
                f"Sede: {sede}\n"
                f"Fecha de ausencia: {fecha_str}\n\n"
                f"El cupo queda libre solo para ese día. "
                f"La reserva sigue activa para las semanas siguientes.\n\n"
                f"— Sistema Pilates Gravity"
            )
        else:
            fecha_str = None
            subject = f"Cancelación permanente — {cliente}"
            body = (
                f"El cliente {cliente} canceló su reserva de forma permanente.\n\n"
                f"Clase: {clase}\n"
                f"Día: {dia} a las {horario}\n"
                f"Sede: {sede}\n"
                f"Número de reserva: {reserva.numero_reserva}\n\n"
                f"El cupo quedó libre definitivamente.\n\n"
                f"— Sistema Pilates Gravity"
            )

        context = {
            'tipo': tipo,
            'cliente': cliente,
            'clase': clase,
            'dia': dia,
            'horario': horario,
            'sede': sede,
            'fecha_str': fecha_str,
            'numero_reserva': reserva.numero_reserva,
            'domain_url': domain_url,
        }

        html_message = render_to_string(
            'gravity/emails/notificacion_cancelacion_admin_email.html',
            context
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=emails_admins,
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Notificación de cancelación ({tipo}) enviada a admins "
            f"por reserva {reserva.numero_reserva}"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando notificación a admins: {str(e)}")
        return False

# ==============================================================================
# EMAIL DE CUMPLEAÑOS
# ==============================================================================

def enviar_email_cumpleanios(usuario):
    """
    Envía un email de cumpleaños al usuario.

    Args:
        usuario: Objeto User cuya fecha de nacimiento coincide con hoy

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not usuario.email:
            logger.warning(f"Usuario {usuario.username} no tiene email configurado")
            return False

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'usuario': usuario,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/cumpleanios_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/cumpleanios_email.html',
            context
        )

        nombre = usuario.first_name or usuario.username
        text_message = (
            f"Hola {nombre},\n\n"
            f"Hoy es un día especial y desde Pilates Gravity queremos acompañarte en él.\n\n"
            f"Gracias por ser parte de nuestra comunidad. Tu presencia y compromiso hacen\n"
            f"que cada clase sea más valiosa. Hoy celebramos contigo.\n\n"
            f"Te esperamos en el estudio cuando quieras.\n\n"
            f"Con afecto,\n"
            f"El equipo de Pilates Gravity\n\n"
            f"Pilates Gravity · La Rioja 3044 y 9 de Julio 3698, Santa Fe\n"
            f"{domain_url}"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de cumpleaños enviado a {usuario.email} "
            f"(usuario: {usuario.username})"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando email de cumpleaños para {usuario.username}: {str(e)}")
        return False

# ==============================================================================
# EMAIL DE MODIFICACIÓN DE RESERVA (por administrador)
# ==============================================================================

def enviar_email_modificacion_reserva(reserva, clase_anterior):
    """
    Envía un email al usuario notificando que un administrador modificó su reserva.

    Args:
        reserva: Objeto Reserva ya actualizado (con la nueva clase)
        clase_anterior: Objeto Clase con la clase original (antes del cambio)

    Returns:
        Boolean: True si el email se envió exitosamente, False en caso contrario
    """
    try:
        if not reserva.usuario.email:
            logger.warning(f"Usuario {reserva.usuario.username} no tiene email configurado")
            return False

        domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')

        context = {
            'reserva': reserva,
            'clase_anterior': clase_anterior,
            'clase_nueva': reserva.clase,
            'usuario': reserva.usuario,
            'domain_url': domain_url,
        }

        subject = render_to_string(
            'gravity/emails/reserva_modificada_subject.txt',
            context
        ).strip()

        html_message = render_to_string(
            'gravity/emails/reserva_modificada_email.html',
            context
        )

        nombre = reserva.usuario.first_name or reserva.usuario.username
        text_message = (
            f"Tu reserva fue modificada por el estudio\n\n"
            f"Hola {nombre},\n\n"
            f"Un administrador realizó un cambio en tu reserva {reserva.numero_reserva}.\n\n"
            f"CLASE ANTERIOR:\n"
            f"  {clase_anterior.get_nombre_display()} — {clase_anterior.dia} "
            f"a las {clase_anterior.horario.strftime('%H:%M')} en {clase_anterior.get_direccion_corta()}\n\n"
            f"NUEVA CLASE:\n"
            f"  {reserva.clase.get_nombre_display()} — {reserva.clase.dia} "
            f"a las {reserva.clase.horario.strftime('%H:%M')} en {reserva.clase.get_direccion_corta()}\n\n"
            f"Pilates Gravity · La Rioja 3044 y 9 de Julio 3698, Santa Fe\n"
            f"pilatesgravity@gmail.com · +54 342 511 4448"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reserva.usuario.email],
        )
        email.attach_alternative(html_message, 'text/html')
        email.send(fail_silently=False)

        logger.info(
            f"Email de modificación de reserva enviado a {reserva.usuario.email} "
            f"— reserva {reserva.numero_reserva}"
        )
        return True

    except Exception as e:
        logger.error(f"Error enviando email de modificación para reserva {reserva.numero_reserva}: {str(e)}")
        return False
