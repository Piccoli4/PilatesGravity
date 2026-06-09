"""
Comando Django: limpiar_reservas_fecha_unica
Cancela automáticamente las reservas de recupero y clase única
cuyo horario ya pasó hace más de 1 hora.
Se debe ejecutar cada hora mediante un cron job.

Uso:
    python manage.py limpiar_reservas_fecha_unica [--dry-run]
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from gravity.models import Reserva


class Command(BaseCommand):
    help = 'Cancela recuperos y clases únicas cuyo horario ya terminó'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular sin hacer cambios en la base de datos',
        )

    def handle(self, *args, **options):
        ahora = timezone.localtime(timezone.now())
        hoy = ahora.date()

        # Reservas de fecha única de días anteriores (siempre vencidas)
        anteriores = Reserva.objects.filter(activa=True, fecha_unica__lt=hoy)

        # Reservas de fecha única de hoy cuyo horario pasó hace más de 1 hora
        candidatas_hoy = Reserva.objects.filter(
            activa=True,
            fecha_unica=hoy,
        ).select_related('clase')

        ids_vencidas_hoy = [
            r.id for r in candidatas_hoy
            if ahora >= timezone.make_aware(
                datetime.combine(hoy, r.clase.horario)
            ) + timedelta(hours=1)
        ]

        total = anteriores.count() + len(ids_vencidas_hoy)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[DRY-RUN] Se cancelarían {total} reserva(s) de fecha única:'
            ))
            for r in anteriores:
                self.stdout.write(
                    f'  - {r.usuario.get_full_name()} | {r.clase.get_nombre_display()} '
                    f'{r.clase.dia} {r.clase.horario.strftime("%H:%M")} | '
                    f'fecha_unica={r.fecha_unica} | '
                    f'{"recupero" if r.es_recupero else "clase única"}'
                )
            for r in candidatas_hoy.filter(id__in=ids_vencidas_hoy):
                self.stdout.write(
                    f'  - {r.usuario.get_full_name()} | {r.clase.get_nombre_display()} '
                    f'{r.clase.dia} {r.clase.horario.strftime("%H:%M")} | '
                    f'fecha_unica={r.fecha_unica} | '
                    f'{"recupero" if r.es_recupero else "clase única"}'
                )
            return

        if total == 0:
            self.stdout.write('No hay reservas de fecha única vencidas.')
            return

        anteriores.update(activa=False)
        if ids_vencidas_hoy:
            Reserva.objects.filter(id__in=ids_vencidas_hoy).update(activa=False)

        self.stdout.write(self.style.SUCCESS(
            f'✅ {total} reserva(s) de fecha única canceladas.'
        ))