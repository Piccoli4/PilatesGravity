"""
Comando Django: cancelar_reservas_planes_vencidos
Cancela automáticamente las reservas de planes cancelados cuando llega su fecha.
Se debe ejecutar diariamente mediante un cron job.

Uso:
    python manage.py cancelar_reservas_planes_vencidos [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from gravity.models import PlanUsuario, Reserva


class Command(BaseCommand):
    help = 'Cancela las reservas de planes vencidos cuando llega su fecha programada'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular sin hacer cambios en la base de datos',
        )

    def handle(self, *args, **options):
        hoy = timezone.now().date()

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'CANCELACIÓN DE RESERVAS DE PLANES VENCIDOS\n'
                f'{"="*70}\n'
                f'Fecha: {hoy.strftime("%d/%m/%Y")}\n'
                f'Modo: {"SIMULACIÓN (dry-run)" if options["dry_run"] else "PRODUCCIÓN"}\n'
                f'{"="*70}\n'
            )
        )

        # Buscar planes cancelados con fecha de cancelación de reservas <= hoy
        # y que aún no hayan sido procesados
        planes_a_procesar = PlanUsuario.objects.filter(
            activo=False,
            reservas_canceladas=False,
            fecha_cancelacion_reservas__lte=hoy,
        ).select_related('usuario', 'plan')

        if not planes_a_procesar.exists():
            self.stdout.write(
                self.style.WARNING('No hay planes con reservas pendientes de cancelar.')
            )
            return

        planes_procesados = 0
        reservas_canceladas_total = 0
        errores = 0

        for plan_usuario in planes_a_procesar:
            usuario = plan_usuario.usuario
            clases_a_cancelar = plan_usuario.plan.clases_por_semana

            try:
                # Obtener reservas activas del usuario
                reservas_activas = list(
                    Reserva.objects.filter(
                        usuario=usuario,
                        activa=True
                    ).select_related('clase')
                )

                if not reservas_activas:
                    self.stdout.write(
                        f'  ⏭️  {usuario.username:20s} | Sin reservas activas, marcando como procesado'
                    )
                    if not options['dry_run']:
                        with transaction.atomic():
                            plan_usuario.reservas_canceladas = True
                            plan_usuario.save()
                    planes_procesados += 1
                    continue

                # Cancelar exactamente clases_a_cancelar reservas
                canceladas = 0
                nombres_cancelados = []

                if not options['dry_run']:
                    with transaction.atomic():
                        for reserva in reservas_activas:
                            if canceladas >= clases_a_cancelar:
                                break
                            reserva.activa = False
                            reserva.save()
                            nombres_cancelados.append(
                                f'{reserva.clase.get_nombre_display()} '
                                f'{reserva.clase.dia} {reserva.clase.horario.strftime("%H:%M")}'
                            )
                            canceladas += 1

                        plan_usuario.reservas_canceladas = True
                        plan_usuario.save()
                else:
                    # En dry-run solo contar
                    for reserva in reservas_activas:
                        if canceladas >= clases_a_cancelar:
                            break
                        nombres_cancelados.append(
                            f'{reserva.clase.get_nombre_display()} '
                            f'{reserva.clase.dia} {reserva.clase.horario.strftime("%H:%M")}'
                        )
                        canceladas += 1

                reservas_canceladas_total += canceladas
                planes_procesados += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ {usuario.username:20s} | '
                        f'{canceladas} reserva{"s" if canceladas != 1 else ""} cancelada{"s" if canceladas != 1 else ""}: '
                        f'{", ".join(nombres_cancelados)}'
                    )
                )

            except Exception as e:
                errores += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ {usuario.username:20s} | Error: {str(e)}'
                    )
                )

        # Resumen final
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'RESUMEN\n'
                f'{"="*70}\n'
                f'✅ Planes procesados:       {planes_procesados}\n'
                f'🗓️  Reservas canceladas:     {reservas_canceladas_total}\n'
                f'❌ Errores:                 {errores}\n'
                f'{"="*70}\n'
            )
        )

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  MODO SIMULACIÓN: No se realizaron cambios en la base de datos.\n'
                    'Ejecute sin --dry-run para aplicar los cambios.\n'
                )
            )