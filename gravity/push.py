"""
Avisos push: la notificación que aparece en el celular aunque la app esté cerrada
(como las de WhatsApp).

Cada persona los activa una vez por dispositivo y eso guarda una SuscripcionPush:
el equipo, desde la campana del panel; los alumnos, desde "Mis reservas".
- Al equipo le llegan las novedades de los alumnos (los textos se arman en panel.py).
- A los alumnos, el recordatorio de su clase (gravity/recordatorios.py).

Necesita las claves VAPID_PUBLIC_KEY y VAPID_PRIVATE_KEY en el .env (se generan
con `python manage.py generar_claves_push`). Sin ellas no se manda nada y no se
ofrece activar los avisos.
"""
import json
import logging
import threading
from functools import wraps

from django.conf import settings
from django.db import connection

from .models import PreferenciasAvisos, SuscripcionPush

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Tipos de aviso. Cada persona puede apagar los que no quiere desde "Avisos"
# (PreferenciasAvisos guarda solo los apagados: uno nuevo nace encendido).
# (clave, nombre, explicación)
# ------------------------------------------------------------------------------
AVISOS_ALUMNO = [
    ('recordatorio', 'Recordatorio de clase', 'Unas horas antes de cada clase.'),
    ('cambios', 'Cambios en mis clases', 'Si el estudio cancela o cambia una de tus clases.'),
    ('lugar', 'Se liberó un lugar', 'Cuando se libera un lugar en una clase en la que estás en lista de espera.'),
    ('recupero', 'Recupero por vencer', 'Unos días antes de que se te venza una clase para recuperar.'),
    ('plan', 'Respuesta a mis pedidos de plan', 'Cuando aprobamos o rechazamos un cambio de plan que pediste.'),
    ('pago', 'Pago registrado', 'Cuando cargamos un pago tuyo.'),
    ('cumple', 'Saludo de cumpleaños', 'Un saludo el día de tu cumpleaños.'),
]
AVISOS_EQUIPO = [
    ('eq_cancelaciones', 'Cancelaciones y ausencias', 'Cuando un alumno deja un horario o avisa que no va.'),
    ('eq_recuperos', 'Recuperos y clases únicas', 'Cuando un alumno reserva un recupero o una clase única.'),
    ('eq_planes', 'Planes cancelados', 'Cuando un alumno cancela su plan.'),
]
AVISOS_SUPERADMIN = [
    ('eq_solicitudes', 'Solicitudes de plan', 'Cuando un alumno pide un plan o un cambio de plan.'),
    ('eq_testimonios', 'Testimonios para revisar', 'Cuando un alumno deja un testimonio.'),
]
_SOLO_SUPERADMIN = {clave for clave, _n, _e in AVISOS_SUPERADMIN}


def grupos_de_avisos(usuario):
    """Los avisos que puede recibir una persona, agrupados: [(título, [(clave, nombre, explicación)])]."""
    grupos = []
    if usuario.is_staff:
        del_panel = AVISOS_EQUIPO + (AVISOS_SUPERADMIN if usuario.is_superuser else [])
        grupos.append(('Del panel', del_panel))
        grupos.append(('De mis clases', AVISOS_ALUMNO))
    else:
        grupos.append(('', AVISOS_ALUMNO))
    return grupos


def avisos_apagados(usuario):
    preferencias = PreferenciasAvisos.objects.filter(usuario=usuario).first()
    return set(preferencias.desactivados) if preferencias else set()


def guardar_avisos(usuario, encendidos):
    """Guarda qué avisos quiere recibir: los que no están en `encendidos` quedan apagados."""
    disponibles = [clave for _t, avisos in grupos_de_avisos(usuario) for clave, _n, _e in avisos]
    apagados = [clave for clave in disponibles if clave not in set(encendidos)]
    PreferenciasAvisos.objects.update_or_create(usuario=usuario, defaults={'desactivados': apagados})
    return apagados


def _quienes_apagaron(tipo):
    return [
        p.usuario_id for p in PreferenciasAvisos.objects.exclude(desactivados=[])
        if tipo in p.desactivados
    ]

# Cuánto guarda el aviso el servicio de Google/Apple si el celular está apagado
# o sin señal. Pasado ese tiempo ya no sirve: se ve en el panel.
VIGENCIA_SEGUNDOS = 12 * 60 * 60
ESPERA_SEGUNDOS = 8


def push_configurado():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def clave_publica():
    """Clave con la que el navegador se suscribe ('' = avisos apagados en este servidor)."""
    return settings.VAPID_PUBLIC_KEY if push_configurado() else ''


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
        'url': url or '/',
        'etiqueta': etiqueta or '',
    })
    if esperar or not getattr(settings, 'PUSH_EN_SEGUNDO_PLANO', True):
        return _mandar(suscripciones, mensaje)
    # En segundo plano: quien disparó el aviso (el alumno que cancela) no espera
    # a que respondan los servidores de Google o Apple.
    threading.Thread(target=_mandar, args=(suscripciones, mensaje, True), daemon=True).start()
    return len(suscripciones)


def _del_equipo(tipo):
    suscripciones = SuscripcionPush.objects.filter(usuario__is_staff=True, usuario__is_active=True)
    if tipo in _SOLO_SUPERADMIN:
        suscripciones = suscripciones.filter(usuario__is_superuser=True)
    return suscripciones.exclude(usuario_id__in=_quienes_apagaron(tipo))


def enviar_push_equipo(tipo, titulo, cuerpo='', url='', etiqueta=''):
    """
    Aviso a los dispositivos del equipo que tienen encendido ese tipo de aviso (los de
    AVISOS_SUPERADMIN, solo a los superadmins, que son quienes los resuelven).
    No falla nunca: si algo sale mal, queda en el log.
    """
    try:
        return _enviar(_del_equipo(tipo), titulo, cuerpo, url, etiqueta, esperar=False)
    except Exception as e:
        logger.error(f"Error preparando el aviso push al equipo: {e}")
        return 0


def enviar_push_usuario(usuario, tipo, titulo, cuerpo='', url='', etiqueta='', esperar=False):
    """
    Aviso a los dispositivos de una persona, si tiene encendido ese tipo de aviso.
    Devuelve a cuántos salió. No falla nunca.
    """
    try:
        if not usuario.is_active or tipo in avisos_apagados(usuario):
            return 0
        return _enviar(SuscripcionPush.objects.filter(usuario=usuario), titulo, cuerpo, url, etiqueta, esperar)
    except Exception as e:
        logger.error(f"Error preparando el aviso push para el usuario {usuario.pk}: {e}")
        return 0


def enviar_push_prueba(usuario):
    """Aviso de prueba a los dispositivos de una persona. Devuelve a cuántos llegó el envío."""
    if usuario.is_staff:
        cuerpo, url = 'Así te va a llegar cada novedad de los alumnos.', '/admin-panel/'
    else:
        cuerpo, url = 'Así te va a llegar el recordatorio antes de cada clase.', '/'
    return _enviar(
        SuscripcionPush.objects.filter(usuario=usuario),
        'Los avisos funcionan', cuerpo, url, 'prueba', esperar=True,
    )


def aviso_seguro(funcion):
    """Para las funciones que arman un aviso: si fallan, no rompen la acción que lo disparó."""
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error enviando el aviso push ({funcion.__name__}): {e}")
            return 0
    return envoltura
