"""
Genera el par de claves para los avisos push del panel.

    python manage.py generar_claves_push

Muestra dos líneas para pegar en el .env. Se hace una sola vez por servidor:
si se cambian las claves, todo el equipo tiene que volver a activar los avisos.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.management.base import BaseCommand


def _b64(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b'=').decode()


class Command(BaseCommand):
    help = 'Genera las claves VAPID para los avisos push del panel'

    def handle(self, *args, **options):
        if settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY:
            self.stdout.write(self.style.WARNING(
                'Ya hay claves cargadas en el .env. Si las reemplazás, el equipo '
                'tiene que volver a activar los avisos en cada celular.\n'
            ))

        clave = ec.generate_private_key(ec.SECP256R1())
        privada = clave.private_numbers().private_value.to_bytes(32, 'big')
        publica = clave.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )

        self.stdout.write('Agregá estas dos líneas al archivo .env y reiniciá la app:\n')
        self.stdout.write(f'VAPID_PUBLIC_KEY={_b64(publica)}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={_b64(privada)}')
