"""
Invitación para alumnos que crea el estudio desde el panel.

La cuenta se crea sin contraseña y al alumno le llega un enlace para elegir la
suya. El enlace dura 7 días y sirve una sola vez (el token depende de la
contraseña: cuando la elige, deja de valer). Si vence, puede pedir uno nuevo con
"Olvidé mi contraseña" o el estudio se lo reenvía desde la ficha.
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_encode

logger = logging.getLogger(__name__)

DIAS_VALIDEZ = 7


class InvitacionTokenGenerator(PasswordResetTokenGenerator):
    """Como el de recuperar contraseña, pero con otra sal y 7 días de validez."""
    key_salt = 'accounts.invitacion.InvitacionTokenGenerator'

    def check_token(self, user, token):
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split('-')
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            return False
        return (self._num_seconds(self._now()) - ts) <= DIAS_VALIDEZ * 24 * 60 * 60


invitacion_token = InvitacionTokenGenerator()


def enlace_invitacion(usuario):
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    ruta = reverse('accounts:invitacion', args=[uid, invitacion_token.make_token(usuario)])
    return settings.SITE_URL.rstrip('/') + ruta


def tiene_invitacion_pendiente(usuario):
    """Cuenta creada por el estudio que todavía no eligió su contraseña."""
    return usuario.is_active and not usuario.has_usable_password()


def enviar_invitacion(usuario):
    """Manda el email de bienvenida con el enlace para crear la contraseña."""
    if not usuario.email:
        return False
    contexto = {
        'usuario': usuario,
        'enlace': enlace_invitacion(usuario),
        'dias': DIAS_VALIDEZ,
        'domain_url': settings.SITE_URL.rstrip('/'),
    }
    try:
        email = EmailMultiAlternatives(
            subject='Te damos la bienvenida a Pilates Gravity · Creá tu contraseña',
            body=render_to_string('accounts/invitacion_email.txt', contexto),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[usuario.email],
        )
        email.attach_alternative(render_to_string('accounts/invitacion_email.html', contexto), 'text/html')
        email.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error(f'No se pudo mandar la invitación a {usuario.email}: {e}')
        return False
