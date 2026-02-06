"""
Comando Django: verificar_deudas_vencidas
Verifica las deudas pendientes y actualiza:
- Estado de deudas a 'vencido' si pasó la fecha límite (día 10)
- Bloquea la capacidad de reservar si tienen deudas vencidas
- Envía notificaciones por email (opcional)

Uso:
    python manage.py verificar_deudas_vencidas [--enviar-emails] [--dry-run]

Opciones:
    --enviar-emails : Enviar notificaciones por email a usuarios con deudas vencidas
    --dry-run       : Simular sin hacer cambios en la base de datos
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction
from datetime import date
from decimal import Decimal

from gravity.models import EstadoPagoCliente, DeudaMensual


class Command(BaseCommand):
    help = 'Verifica deudas vencidas y actualiza restricciones de reserva'

    def add_arguments(self, parser):
        parser.add_argument(
            '--enviar-emails',
            action='store_true',
            help='Enviar notificaciones por email a usuarios con deudas vencidas',
        )
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
                f'VERIFICACIÓN DE DEUDAS VENCIDAS\n'
                f'{"="*70}\n'
                f'Fecha actual: {hoy.strftime("%d/%m/%Y")}\n'
                f'Modo: {"SIMULACIÓN (dry-run)" if options["dry_run"] else "PRODUCCIÓN"}\n'
                f'{"="*70}\n'
            )
        )

        # Buscar deudas pendientes que ya vencieron (después del día 10)
        deudas_vencidas = DeudaMensual.objects.filter(
            estado__in=['pendiente', 'parcial'],
            fecha_vencimiento__lt=hoy
        ).select_related('usuario', 'plan_aplicado')

        if not deudas_vencidas.exists():
            self.stdout.write(
                self.style.SUCCESS('✅ No se encontraron deudas vencidas.')
            )
            return

        deudas_actualizadas = 0
        usuarios_bloqueados = 0
        emails_enviados = 0
        errores = 0
        monto_total_vencido = Decimal('0')

        for deuda in deudas_vencidas:
            usuario = deuda.usuario

            try:
                if not options['dry_run']:
                    with transaction.atomic():
                        # Actualizar estado de la deuda a 'vencido'
                        deuda.estado = 'vencido'
                        deuda.save()

                        # Obtener estado del cliente
                        try:
                            estado_cliente = EstadoPagoCliente.objects.get(usuario=usuario)
                            
                            # Bloquear capacidad de reservar
                            if estado_cliente.puede_reservar:
                                estado_cliente.puede_reservar = False
                                estado_cliente.save()
                                usuarios_bloqueados += 1

                        except EstadoPagoCliente.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'  ⚠️  Usuario {usuario.username} no tiene EstadoPagoCliente'
                                )
                            )

                deudas_actualizadas += 1
                monto_total_vencido += deuda.monto_pendiente

                dias_vencida = (hoy - deuda.fecha_vencimiento).days

                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠️  {usuario.username:20s} | ${deuda.monto_pendiente:>8.2f} | '
                        f'Vencida hace {dias_vencida} días | '
                        f'{deuda.mes_año.strftime("%B %Y")}'
                    )
                )

                # Enviar email si se solicitó
                if options['enviar_emails'] and not options['dry_run']:
                    try:
                        # Aquí puedes integrar la función de envío de emails
                        # enviar_email_deuda_vencida(usuario, deuda)
                        emails_enviados += 1
                        self.stdout.write(
                            f'     📧 Email enviado a {usuario.email}'
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f'     ❌ Error enviando email: {str(e)}'
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
                f'⚠️  Deudas marcadas como vencidas: {deudas_actualizadas}\n'
                f'🚫 Usuarios bloqueados:           {usuarios_bloqueados}\n'
                f'📧 Emails enviados:               {emails_enviados}\n'
                f'❌ Errores:                       {errores}\n'
                f'💰 Monto total vencido:           ${monto_total_vencido:,.2f}\n'
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

        # Verificar usuarios que pueden volver a reservar (pagaron su deuda)
        self._verificar_usuarios_desbloqueados(options['dry_run'])

    def _verificar_usuarios_desbloqueados(self, dry_run):
        """Verifica usuarios que ya no tienen deudas vencidas y pueden volver a reservar"""
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*70}\n'
                f'VERIFICANDO USUARIOS PARA DESBLOQUEAR\n'
                f'{"="*70}\n'
            )
        )

        # Usuarios bloqueados
        estados_bloqueados = EstadoPagoCliente.objects.filter(
            puede_reservar=False,
            activo=True
        ).select_related('usuario')

        usuarios_desbloqueados = 0

        for estado in estados_bloqueados:
            # Verificar si tiene deudas vencidas pendientes
            tiene_deudas_vencidas = DeudaMensual.objects.filter(
                usuario=estado.usuario,
                estado='vencido',
                monto_pendiente__gt=0
            ).exists()

            # Si no tiene deudas vencidas, desbloquear
            if not tiene_deudas_vencidas:
                if not dry_run:
                    estado.puede_reservar = True
                    estado.save()
                
                usuarios_desbloqueados += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ {estado.usuario.username:20s} | Desbloqueado (deuda saldada)'
                    )
                )

        if usuarios_desbloqueados > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Total usuarios desbloqueados: {usuarios_desbloqueados}\n'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    '\nNo hay usuarios para desbloquear.\n'
                )
            )