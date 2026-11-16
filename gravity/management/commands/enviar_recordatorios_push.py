"""
Manda los avisos push programados a los alumnos que los activaron: el recordatorio
de clase, el recupero por vencer y el saludo de cumpleaños.

    python manage.py enviar_recordatorios_push [--dry-run]

Se corre con cron cada 15 minutos. Es seguro correrlo de más: cada aviso sale una
sola vez. Cuándo le toca a cada uno está en gravity/recordatorios.py.

    */15 * * * * /ruta/al/entorno/python /ruta/al/proyecto/manage.py enviar_recordatorios_push
"""
from django.core.management.base import BaseCommand

from gravity.push import push_configurado
from gravity.recordatorios import enviar_avisos_recupero, enviar_recordatorios, enviar_saludos_cumpleanios


def _nombre(usuario):
    return usuario.get_full_name() or usuario.username


class Command(BaseCommand):
    help = 'Envía los avisos push programados (recordatorio de clase, recupero por vencer, cumpleaños)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Mostrar a quién le tocaría, sin enviar')

    def handle(self, *args, **options):
        if not push_configurado():
            self.stdout.write('Los avisos push no están configurados (faltan las claves en el .env).')
            return
        simular = options['dry_run']
        marca = '[simulación] ' if simular else ''

        recordatorios = enviar_recordatorios(simular=simular)
        for reserva, fecha in recordatorios:
            self.stdout.write(
                f'{marca}Recordatorio a {_nombre(reserva.usuario)}: '
                f'{reserva.clase.get_nombre_display()} {fecha:%d/%m} {reserva.clase.horario:%H:%M}'
            )

        recuperos = enviar_avisos_recupero(simular=simular)
        for usuario, ausencia in recuperos:
            self.stdout.write(f'{marca}Recupero por vencer a {_nombre(usuario)}: clase del {ausencia.fecha:%d/%m}')

        cumples = enviar_saludos_cumpleanios(simular=simular)
        for usuario in cumples:
            self.stdout.write(f'{marca}Cumpleaños a {_nombre(usuario)}')

        self.stdout.write(
            f'Recordatorios: {len(recordatorios)} · Recuperos por vencer: {len(recuperos)} · '
            f'Cumpleaños: {len(cumples)}'
        )
