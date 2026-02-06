"""
Comando Django: generar_deudas_mensuales
Genera automáticamente las deudas mensuales para todos los usuarios con planes activos.
Se debe ejecutar el día 1 de cada mes mediante un cron job.

Uso:
    python manage.py generar_deudas_mensuales [--mes YYYY-MM] [--force]

Opciones:
    --mes YYYY-MM : Generar deudas para un mes específico (por defecto: mes actual)
    --force       : Regenerar deudas incluso si ya existen (usar con precaución)
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction
from datetime import date, datetime
from decimal import Decimal

from gravity.models import EstadoPagoCliente, DeudaMensual, PlanPago


class Command(BaseCommand):
    help = 'Genera deudas mensuales automáticas para usuarios con planes activos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mes',
            type=str,
            help='Mes para generar deudas en formato YYYY-MM (por defecto: mes actual)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar generación incluso si ya existen deudas para el mes',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular sin hacer cambios en la base de datos',
        )

    def handle(self, *args, **options):
        # Determinar mes para generar deudas
        if options['mes']:
            try:
                mes_fecha = datetime.strptime(options['mes'], '%Y-%m').date()
                primer_dia_mes = date(mes_fecha.year, mes_fecha.month, 1)
            except ValueError:
                raise CommandError('Formato de mes inválido. Use YYYY-MM (ejemplo: 2025-02)')
        else:
            hoy = timezone.now().date()
            primer_dia_mes = date(hoy.year, hoy.month, 1)

        # Fecha de vencimiento: día 10 del mes
        fecha_vencimiento = date(primer_dia_mes.year, primer_dia_mes.month, 10)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'GENERACIÓN DE DEUDAS MENSUALES\n'
                f'{"="*70}\n'
                f'Mes: {primer_dia_mes.strftime("%B %Y")}\n'
                f'Fecha de vencimiento: {fecha_vencimiento.strftime("%d/%m/%Y")}\n'
                f'Modo: {"SIMULACIÓN (dry-run)" if options["dry_run"] else "PRODUCCIÓN"}\n'
                f'{"="*70}\n'
            )
        )

        # Obtener usuarios con planes activos
        estados_con_plan = EstadoPagoCliente.objects.filter(
            plan_actual__isnull=False,
            activo=True
        ).select_related('usuario', 'plan_actual')

        if not estados_con_plan.exists():
            self.stdout.write(
                self.style.WARNING('No se encontraron usuarios con planes activos.')
            )
            return

        deudas_generadas = 0
        deudas_existentes = 0
        errores = 0
        monto_total_generado = Decimal('0')

        for estado_cliente in estados_con_plan:
            usuario = estado_cliente.usuario
            plan = estado_cliente.plan_actual

            try:
                # Verificar si ya existe una deuda para este mes
                deuda_existente = DeudaMensual.objects.filter(
                    usuario=usuario,
                    mes_año=primer_dia_mes
                ).first()

                if deuda_existente and not options['force']:
                    deudas_existentes += 1
                    self.stdout.write(
                        f'  ⏭️  {usuario.username:20s} | Ya tiene deuda del mes (${deuda_existente.monto_original})'
                    )
                    continue

                # Calcular monto a cobrar
                monto_a_cobrar = plan.precio_mensual

                if not options['dry_run']:
                    with transaction.atomic():
                        # Si existe y es force, eliminar la anterior
                        if deuda_existente and options['force']:
                            deuda_existente.delete()

                        # Crear nueva deuda
                        nueva_deuda = DeudaMensual.objects.create(
                            usuario=usuario,
                            mes_año=primer_dia_mes,
                            plan_aplicado=plan,
                            monto_original=monto_a_cobrar,
                            monto_pendiente=monto_a_cobrar,
                            es_medio_mes=False,
                            estado='pendiente',
                            fecha_vencimiento=fecha_vencimiento,
                            observaciones=f'Deuda mensual generada automáticamente - Plan: {plan.nombre}'
                        )

                        # Actualizar estado del cliente
                        estado_cliente.saldo_actual -= monto_a_cobrar
                        estado_cliente.monto_deuda_mensual = monto_a_cobrar
                        estado_cliente.fecha_limite_pago = fecha_vencimiento
                        estado_cliente.puede_reservar = True  # Empieza el mes pudiendo reservar
                        estado_cliente.save()

                deudas_generadas += 1
                monto_total_generado += monto_a_cobrar

                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ {usuario.username:20s} | ${monto_a_cobrar:>8.2f} | Plan: {plan.nombre}'
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
                f'✅ Deudas generadas:     {deudas_generadas}\n'
                f'⏭️  Deudas ya existentes: {deudas_existentes}\n'
                f'❌ Errores:              {errores}\n'
                f'💰 Monto total generado: ${monto_total_generado:,.2f}\n'
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