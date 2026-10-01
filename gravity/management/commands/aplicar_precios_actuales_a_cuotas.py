"""
Comando Django: aplicar_precios_actuales_a_cuotas
Pasa al precio actual de cada plan las cuotas impagas de un mes que se
generaron con un precio anterior.

Sirve cuando los precios se actualizan después de que el cron del día 1 ya
generó las cuotas del mes: las cuotas quedan con el precio viejo.

Por cada plan busca las cuotas impagas del mes cuyo monto no coincide con el
precio actual. Si todas tienen el mismo monto, ese es el precio anterior y se
actualizan. Si hay montos distintos (ajustes a mano, cancelaciones), el plan
se saltea y se informa, para revisarlo a mano.

Uso:
    python manage.py aplicar_precios_actuales_a_cuotas [--mes YYYY-MM] [--dry-run]

Opciones:
    --mes YYYY-MM : Mes de las cuotas a corregir (por defecto: mes actual)
    --dry-run     : Mostrar qué se cambiaría sin tocar la base de datos
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gravity.models import (
    DeudaMensual,
    ESTADOS_CUOTA_IMPAGA,
    PlanPago,
    aplicar_precio_a_cuotas_del_mes,
    cuotas_con_precio_anterior,
)


class Command(BaseCommand):
    help = 'Pasa al precio actual de cada plan las cuotas impagas del mes generadas con un precio anterior'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mes',
            type=str,
            help='Mes de las cuotas en formato YYYY-MM (por defecto: mes actual)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular sin hacer cambios en la base de datos',
        )

    def handle(self, *args, **options):
        if options['mes']:
            try:
                mes_fecha = datetime.strptime(options['mes'], '%Y-%m').date()
            except ValueError:
                raise CommandError('Formato de mes inválido. Use YYYY-MM (ejemplo: 2026-10)')
            mes = date(mes_fecha.year, mes_fecha.month, 1)
        else:
            hoy = timezone.localtime(timezone.now()).date()
            mes = date(hoy.year, hoy.month, 1)

        dry_run = options['dry_run']

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'CUOTAS CON PRECIO ANTERIOR\n'
                f'{"="*70}\n'
                f'Mes: {mes.strftime("%m/%Y")}\n'
                f'Modo: {"SIMULACIÓN (dry-run)" if dry_run else "PRODUCCIÓN"}\n'
                f'{"="*70}\n'
            )
        )

        total_cuotas = 0
        planes_salteados = 0

        for plan in PlanPago.objects.order_by('clases_por_semana', 'id'):
            montos_viejos = set(
                DeudaMensual.objects.filter(
                    plan_aplicado=plan,
                    mes_año=mes,
                    es_medio_mes=False,
                    estado__in=ESTADOS_CUOTA_IMPAGA,
                    monto_original__gt=0,
                ).exclude(
                    monto_original=plan.precio_mensual
                ).values_list('monto_original', flat=True)
            )

            if not montos_viejos:
                continue

            if len(montos_viejos) > 1:
                planes_salteados += 1
                montos = ', '.join(f'${m}' for m in sorted(montos_viejos))
                self.stdout.write(
                    self.style.WARNING(
                        f'\n⚠️  {plan.nombre} (precio actual ${plan.precio_mensual}): '
                        f'hay cuotas con montos distintos ({montos}). Se saltea, revisar a mano.'
                    )
                )
                continue

            precio_anterior = montos_viejos.pop()
            cuotas = list(cuotas_con_precio_anterior(plan, precio_anterior, mes))

            self.stdout.write(
                f'\n{plan.nombre}: ${precio_anterior} → ${plan.precio_mensual} '
                f'({len(cuotas)} cuota(s))'
            )
            for deuda in cuotas:
                nombre = deuda.usuario.get_full_name() or deuda.usuario.username
                self.stdout.write(f'    {nombre:35s} | {deuda.estado}')

            if not dry_run:
                aplicar_precio_a_cuotas_del_mes(plan, precio_anterior, mes)

            total_cuotas += len(cuotas)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'RESUMEN\n'
                f'{"="*70}\n'
                f'✅ Cuotas {"a actualizar" if dry_run else "actualizadas"}: {total_cuotas}\n'
                f'⚠️  Planes salteados:      {planes_salteados}\n'
                f'{"="*70}\n'
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  MODO SIMULACIÓN: No se realizaron cambios en la base de datos.\n'
                    'Ejecute sin --dry-run para aplicar los cambios.\n'
                )
            )
