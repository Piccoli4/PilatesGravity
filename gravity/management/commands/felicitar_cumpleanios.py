"""
Comando Django: felicitar_cumpleanios
Busca usuarios cuya fecha de nacimiento coincide con el día de hoy (sin importar el año)
y les envía un email de cumpleaños.
Se debe ejecutar una vez por día mediante un cron job.

Uso:
    python manage.py felicitar_cumpleanios [--dry-run]

Opciones:
    --dry-run : Simular sin enviar emails

Prueba desde shell de Django (sin MagicMock):
    python manage.py shell
    >>> from types import SimpleNamespace
    >>> from django.contrib.auth.models import User
    >>> usuario = User.objects.get(username='nombre_de_usuario')
    >>> from gravity.email_service import enviar_email_cumpleanios
    >>> enviar_email_cumpleanios(usuario)

    # Para probar el comando completo en dry-run:
    >>> from django.test.utils import override_settings
    >>> from django.core.management import call_command
    >>> call_command('felicitar_cumpleanios', dry_run=True)
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from gravity.email_service import enviar_email_cumpleanios


class Command(BaseCommand):
    help = 'Envía emails de cumpleaños a los usuarios que cumplen años hoy'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular sin enviar emails',
        )

    def handle(self, *args, **options):
        hoy = timezone.now().date()

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'FELICITACIONES DE CUMPLEAÑOS\n'
                f'{"="*70}\n'
                f'Fecha actual: {hoy.strftime("%d/%m/%Y")}\n'
                f'Modo: {"SIMULACIÓN (dry-run)" if options["dry_run"] else "PRODUCCIÓN"}\n'
                f'{"="*70}\n'
            )
        )

        # Buscar usuarios con fecha de nacimiento cargada que cumplan hoy
        usuarios_cumpleanios = User.objects.filter(
            profile__fecha_nacimiento__month=hoy.month,
            profile__fecha_nacimiento__day=hoy.day,
            is_active=True,
        ).select_related('profile').exclude(email='')

        if not usuarios_cumpleanios.exists():
            self.stdout.write(
                self.style.SUCCESS('No hay usuarios que cumplan años hoy.')
            )
            return

        emails_enviados = 0
        emails_omitidos = 0
        errores = 0

        for usuario in usuarios_cumpleanios:
            try:
                self.stdout.write(
                    f'  → {usuario.username:25s} | {usuario.email}'
                )

                if not options['dry_run']:
                    resultado = enviar_email_cumpleanios(usuario)

                    if resultado:
                        emails_enviados += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'     Email enviado correctamente.'
                            )
                        )
                    else:
                        emails_omitidos += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f'     Email omitido (sin dirección o error interno).'
                            )
                        )
                else:
                    emails_enviados += 1

            except Exception as e:
                errores += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'     Error procesando {usuario.username}: {str(e)}'
                    )
                )

        # Resumen final
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'RESUMEN\n'
                f'{"="*70}\n'
                f'Emails {"simulados" if options["dry_run"] else "enviados"}:  {emails_enviados}\n'
                f'Emails omitidos:  {emails_omitidos}\n'
                f'Errores:          {errores}\n'
                f'{"="*70}\n'
            )
        )

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    '\nMODO SIMULACIÓN: No se enviaron emails.\n'
                    'Ejecute sin --dry-run para enviar.\n'
                )
            )
