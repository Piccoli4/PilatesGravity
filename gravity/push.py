"""
Avisos push al equipo: la notificación que aparece en el celular aunque el panel
esté cerrado (como las de WhatsApp).

Cada persona del equipo activa los avisos desde la campana del panel, una vez por
dispositivo; eso guarda una SuscripcionPush. Acá se arma y se manda el aviso a
todos los dispositivos suscriptos de quienes hoy son del equipo.

Necesita las claves VAPID_PUBLIC_KEY y VAPID_PRIVATE_KEY en el .env (se generan
con `python manage.py generar_claves_push`). Sin ellas no se manda nada y el
panel no ofrece activar los avisos.
"""
import json
import logging
import threading

from django.conf import settings
from django.db import connection

from .models import SuscripcionPush

logger = logging.getLogger(__name__)

# Cuánto guarda el aviso el servicio de Google/Apple si el celular está apagado
# o sin señal. Pasado ese tiempo ya no sirve: se ve en el panel.
VIGENCIA_SEGUNDOS = 12 * 60 * 60
ESPERA_SEGUNDOS = 8


def push_configurado():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _contacto():
    """Quién manda los avisos (lo piden Google y Apple): la dirección del sitio."""
    sitio = (getattr(settings, 'SITE_URL', '') or '').rstrip('/')
    return sitio if sitio.startswith('https://') else 'https://pilatesgravity.com.ar'


def guardar_suscripcion(usuario, datos, dispositivo=''):
    """
    Guarda (o actualiza) el dispositivo desde el que se activaron los avisos.
    `datos` es lo que entrega el navegador: {'endpoint': ..., 'keys': {'p256dh': ..., 'auth': ...}}.
    Devuelve la suscripción, o None si los datos no sirven.
    """
    if not isinstance(datos, dict):
        return None
    endpoint = datos.get('endpoint')
    claves = datos.get('keys')
    if not isinstance(endpoint, str) or not isinstance(claves, dict):
        return None
    p256dh, auth = claves.get('p256dh'), claves.get('auth')
    if not (isinstance(p256dh, str) and isinstance(auth, str) and p256dh and auth):
        return None
    if not endpoint.startswith('https://') or len(endpoint) > 1000 or len(p256dh) > 200 or len(auth) > 100:
        return None

    # Si en ese celular antes entraba otra persona, los avisos pasan a quien los activó ahora
    suscripcion, _ = SuscripcionPush.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'usuario': usuario,
            'p256dh': p256dh,
            'auth': auth,
            'dispositivo': (dispositivo or '')[:300],
        },
    )
    return suscripcion


def _mandar(suscripciones, mensaje, cerrar_conexion=False):
    """Manda el aviso a cada dispositivo y borra los que ya no existen. Devuelve cuántos salieron."""
    from pywebpush import WebPushException, webpush

    enviados = 0
    vencidas = []
    for s in suscripciones:
        try:
            webpush(
                subscription_info={'endpoint': s.endpoint, 'keys': {'p256dh': s.p256dh, 'auth': s.auth}},
                data=mensaje,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                # pywebpush modifica este diccionario: uno nuevo por envío
                vapid_claims={'sub': _contacto()},
                ttl=VIGENCIA_SEGUNDOS,
                timeout=ESPERA_SEGUNDOS,
                headers={'Urgency': 'high'},
            )
            enviados += 1
        except WebPushException as e:
            estado = getattr(e.response, 'status_code', None)
            if estado in (404, 410):
                # La persona desactivó los avisos o desinstaló la app en ese dispositivo
                vencidas.append(s.pk)
            else:
                logger.error(f"Error enviando aviso push (suscripción {s.pk}, estado {estado}): {e}")
        except Exception as e:
            logger.error(f"Error enviando aviso push (suscripción {s.pk}): {e}")

    try:
        if vencidas:
            SuscripcionPush.objects.filter(pk__in=vencidas).delete()
    except Exception as e:
        logger.error(f"Error borrando suscripciones push vencidas: {e}")
    finally:
        if cerrar_conexion:
            connection.close()
    return enviados


def _enviar(suscripciones, titulo, cuerpo, url, etiqueta, esperar):
    if not push_configurado():
        return 0
    suscripciones = list(suscripciones)
    if not suscripciones:
        return 0
    mensaje = json.dumps({
        'titulo': titulo,
        'cuerpo': cuerpo,
        'url': url or '/admin-panel/',
        'etiqueta': etiqueta or '',
    })
    if esperar or not getattr(settings, 'PUSH_EN_SEGUNDO_PLANO', True):
        return _mandar(suscripciones, mensaje)
    # En segundo plano: quien disparó el aviso (el alumno que cancela) no espera
    # a que respondan los servidores de Google o Apple.
    threading.Thread(target=_mandar, args=(suscripciones, mensaje, True), daemon=True).start()
    return len(suscripciones)


def _del_equipo():
    return SuscripcionPush.objects.filter(usuario__is_staff=True, usuario__is_active=True)


def enviar_push_equipo(titulo, cuerpo='', url='', etiqueta=''):
    """Aviso a todos los dispositivos suscriptos del equipo. No falla nunca: si algo sale mal, queda en el log."""
    try:
        return _enviar(_del_equipo(), titulo, cuerpo, url, etiqueta, esperar=False)
    except Exception as e:
        logger.error(f"Error preparando el aviso push al equipo: {e}")
        return 0


def enviar_push_prueba(usuario):
    """Aviso de prueba a los dispositivos de una persona. Devuelve a cuántos llegó el envío."""
    return _enviar(
        _del_equipo().filter(usuario=usuario),
        'Los avisos funcionan',
        'Así te va a llegar cuando un alumno cancele o avise que no va.',
        '/admin-panel/', 'prueba', esperar=True,
    )
