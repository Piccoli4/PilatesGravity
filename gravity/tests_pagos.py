"""
Tests del circuito de correcciones de la cuenta de un cliente.

Reproducen los dos problemas reales que aparecieron en producción:
  * un saldo a favor fantasma después de un cambio de plan;
  * un pago cargado con un cero de más ($550.000 en vez de $55.000).
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AjusteSaldo,
    DeudaMensual,
    EstadoPagoCliente,
    PlanPago,
    RegistroPago,
    recalcular_estado_pagos,
)


def primer_dia(fecha):
    return date(fecha.year, fecha.month, 1)


def restar_meses(fecha, meses):
    mes = fecha.month - meses
    año = fecha.year
    while mes <= 0:
        mes += 12
        año -= 1
    return date(año, mes, 1)


class CorreccionesCuentaTests(TestCase):
    def setUp(self):
        self.hoy = timezone.localtime(timezone.now()).date()
        self.admin = User.objects.create_superuser(
            username='nico', email='nico@test.com', password='clave123'
        )
        self.cliente = User.objects.create_user(
            username='camila', email='camila@test.com', password='clave123',
            first_name='Camila', last_name='Coutinho'
        )
        self.plan3 = PlanPago.objects.create(
            nombre='3 clases semanales', clases_por_semana=3, precio_mensual=Decimal('70000')
        )
        self.plan2 = PlanPago.objects.create(
            nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000')
        )
        self.estado = EstadoPagoCliente.objects.create(
            usuario=self.cliente, plan_actual=self.plan2, activo=True
        )
        self.client.force_login(self.admin)

    # ---------------------------------------------------------------- helpers
    def crear_cuota(self, mes, plan, monto, pendiente=None, estado='pendiente'):
        return DeudaMensual.objects.create(
            usuario=self.cliente,
            mes_año=mes,
            plan_aplicado=plan,
            monto_original=Decimal(monto),
            monto_pendiente=Decimal(monto) if pendiente is None else Decimal(pendiente),
            fecha_vencimiento=date(mes.year, mes.month, 10),
            estado=estado,
        )

    def crear_pago(self, monto, fecha, tipo='efectivo', concepto='Pago cuota'):
        # bulk_create para armar el escenario sin disparar la lógica de save()
        pago = RegistroPago(
            cliente=self.cliente, monto=Decimal(monto), fecha_pago=fecha,
            tipo_pago=tipo, estado='confirmado', concepto=concepto,
        )
        RegistroPago.objects.bulk_create([pago])
        return RegistroPago.objects.get(fecha_pago=fecha, monto=Decimal(monto))

    def saldo(self):
        self.estado.refresh_from_db()
        return self.estado.saldo_actual

    # ------------------------------------------------------------------ tests
    def test_saldo_es_pagos_mas_correcciones_menos_cuotas(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000')
        self.crear_pago('61000', self.hoy)

        resultado = recalcular_estado_pagos(self.cliente)

        self.assertEqual(resultado['saldo'], Decimal('0'))
        self.assertEqual(DeudaMensual.objects.get().estado, 'pagado')

    def test_corregir_saldo_a_favor_fantasma_deja_la_cuenta_al_dia(self):
        """Caso Camila: pagó $2.000 más de lo que suman sus cuotas."""
        mes_pasado = restar_meses(self.hoy, 1)
        self.crear_cuota(mes_pasado, self.plan2, '61000', pendiente='0', estado='pagado')
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000', pendiente='0', estado='pagado')
        self.crear_pago('63000', date(mes_pasado.year, mes_pasado.month, 5))
        self.crear_pago('61000', self.hoy)
        recalcular_estado_pagos(self.cliente)
        self.assertEqual(self.saldo(), Decimal('2000'))

        respuesta = self.client.post(
            reverse('gravity:admin_corregir_saldo', args=[self.cliente.id]),
            {'situacion': 'al_dia', 'motivo': 'El cambio de plan le descontó $2.000 de más.'},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.saldo(), Decimal('0'))

        correccion = AjusteSaldo.objects.get(tipo=AjusteSaldo.TIPO_CORRECCION_SALDO)
        self.assertEqual(correccion.monto, Decimal('-2000'))
        self.assertEqual(correccion.saldo_anterior, Decimal('2000'))
        self.assertEqual(correccion.saldo_nuevo, Decimal('0'))
        self.assertEqual(correccion.admin_que_ajusto, self.admin)

    def test_corregir_saldo_puede_dejar_al_cliente_debiendo(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000', pendiente='0', estado='pagado')
        self.crear_pago('61000', self.hoy)
        recalcular_estado_pagos(self.cliente)

        self.client.post(
            reverse('gravity:admin_corregir_saldo', args=[self.cliente.id]),
            {'situacion': 'debe', 'monto': '10000', 'motivo': 'Le faltó pagar la diferencia.'},
        )

        self.assertEqual(self.saldo(), Decimal('-10000'))
        cuota = DeudaMensual.objects.get()
        self.assertEqual(cuota.monto_pendiente, Decimal('10000'))
        self.assertEqual(cuota.estado, 'parcial')

    def test_corregir_pago_mal_cargado(self):
        """Caso Aixa: se cargaron $550.000 en vez de $55.000."""
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '55000', pendiente='0', estado='pagado')
        pago = self.crear_pago('550000', self.hoy)
        recalcular_estado_pagos(self.cliente)
        self.assertEqual(self.saldo(), Decimal('495000'))

        respuesta = self.client.post(
            reverse('gravity:admin_pago_editar', args=[pago.id]),
            {
                'monto': '55000',
                'fecha_pago': self.hoy.strftime('%Y-%m-%d'),
                'tipo_pago': 'efectivo',
                'concepto': 'Pago septiembre',
                'motivo': 'Se cargó un cero de más.',
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        pago.refresh_from_db()
        self.assertEqual(pago.monto, Decimal('55000'))
        self.assertEqual(self.saldo(), Decimal('0'))
        self.assertEqual(DeudaMensual.objects.get().estado, 'pagado')
        self.estado.refresh_from_db()
        self.assertEqual(self.estado.monto_ultimo_pago, Decimal('55000'))
        self.assertTrue(AjusteSaldo.objects.filter(tipo='pago_editado').exists())

    def test_anular_pago_lo_saca_de_la_cuenta_sin_borrarlo(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '55000', pendiente='0', estado='pagado')
        pago = self.crear_pago('55000', self.hoy)
        recalcular_estado_pagos(self.cliente)

        self.client.post(
            reverse('gravity:admin_pago_anular', args=[pago.id]),
            {'motivo': 'El pago era de otra clienta.'},
        )

        pago.refresh_from_db()
        self.assertEqual(pago.estado, 'rechazado')
        self.assertEqual(self.saldo(), Decimal('-55000'))
        self.assertEqual(DeudaMensual.objects.get().monto_pendiente, Decimal('55000'))

    def test_cambiar_monto_de_una_cuota_recalcula_la_cuenta(self):
        cuota = self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000')
        self.crear_pago('55000', self.hoy)
        recalcular_estado_pagos(self.cliente)
        self.assertEqual(self.saldo(), Decimal('-6000'))

        self.client.post(
            reverse('gravity:admin_ajustar_deuda_especial', args=[cuota.id]),
            {'monto_ajustado': '55000', 'motivo': 'Pagó en efectivo, va con descuento.'},
        )

        cuota.refresh_from_db()
        self.assertEqual(cuota.monto_original, Decimal('55000'))
        self.assertEqual(cuota.estado, 'pagado')
        self.assertEqual(self.saldo(), Decimal('0'))

    def test_eliminar_cuota_que_no_correspondia(self):
        cuota = self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000')
        recalcular_estado_pagos(self.cliente)
        self.assertEqual(self.saldo(), Decimal('-61000'))

        self.client.post(
            reverse('gravity:admin_eliminar_deuda', args=[cuota.id]),
            {'motivo': 'Estaba de baja ese mes.'},
        )

        self.assertFalse(DeudaMensual.objects.exists())
        self.assertEqual(self.saldo(), Decimal('0'))

    def test_recalcular_no_cambia_una_cuenta_sana(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000', pendiente='0', estado='pagado')
        self.crear_pago('61000', self.hoy)
        recalcular_estado_pagos(self.cliente)

        self.client.post(reverse('gravity:admin_recalcular_cuenta', args=[self.cliente.id]))

        self.assertEqual(self.saldo(), Decimal('0'))
        self.assertFalse(AjusteSaldo.objects.exists())

    def test_registrar_pago_en_efectivo_aplica_el_descuento_del_plan(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000')

        RegistroPago.objects.create(
            cliente=self.cliente, monto=Decimal('55000'), fecha_pago=self.hoy,
            tipo_pago='efectivo', estado='confirmado', concepto='Pago del mes',
            registrado_por=self.admin,
        )

        cuota = DeudaMensual.objects.get()
        self.assertEqual(cuota.monto_original, Decimal('55000'))
        self.assertEqual(cuota.estado, 'pagado')
        self.assertEqual(self.saldo(), Decimal('0'))

    def test_admin_comun_no_puede_corregir_saldos(self):
        empleada = User.objects.create_user(
            username='diana', email='diana@test.com', password='clave123', is_staff=True
        )
        self.client.force_login(empleada)

        respuesta = self.client.post(
            reverse('gravity:admin_corregir_saldo', args=[self.cliente.id]),
            {'situacion': 'al_dia', 'motivo': 'probando'},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(AjusteSaldo.objects.exists())

    def test_la_pantalla_de_la_cuenta_carga(self):
        self.crear_cuota(primer_dia(self.hoy), self.plan2, '61000')
        self.crear_pago('61000', self.hoy)
        recalcular_estado_pagos(self.cliente)

        respuesta = self.client.get(
            reverse('gravity:admin_pagos_editar_estado_cliente', args=[self.cliente.id])
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Estado de la cuenta')
        self.assertContains(respuesta, 'Corregir el saldo')

class PagosPorAdministradoraTests(TestCase):
    """
    Pantalla de superadmin con los pagos que cargó cada administradora.
    """

    def setUp(self):
        self.nico = User.objects.create_superuser(
            username='nico', email='nico@test.com', password='clave123',
            first_name='Nicolás', last_name='Piccoli'
        )
        self.ana = User.objects.create_user(
            username='ana', email='ana@test.com', password='clave123',
            first_name='Ana', last_name='Gómez', is_staff=True
        )
        self.bea = User.objects.create_user(
            username='bea', email='bea@test.com', password='clave123',
            first_name='Bea', last_name='López', is_staff=True
        )
        self.cliente1 = User.objects.create_user(
            username='sofia', email='sofia@test.com', password='clave123',
            first_name='Sofía', last_name='Ruiz'
        )
        self.cliente2 = User.objects.create_user(
            username='marta', email='marta@test.com', password='clave123',
            first_name='Marta', last_name='Díaz'
        )

        # Pagos de un mes cerrado, para que el período no dependa de la fecha de hoy
        self.desde = date(2026, 4, 1)
        self.hasta = date(2026, 4, 30)

        self.crear_pago(self.ana, self.cliente1, '10000', date(2026, 4, 5), 'efectivo')
        self.crear_pago(self.ana, self.cliente2, '5000', date(2026, 4, 6), 'efectivo')
        self.crear_pago(self.ana, self.cliente1, '20000', date(2026, 4, 5), 'transferencia')
        self.crear_pago(self.bea, self.cliente2, '30000', date(2026, 4, 7), 'transferencia')
        self.anulado = self.crear_pago(
            self.ana, self.cliente1, '7000', date(2026, 4, 5), 'efectivo', estado='rechazado'
        )
        self.sin_autor = self.crear_pago(None, self.cliente1, '1000', date(2026, 4, 8), 'otro')
        # Fuera del período: no tiene que contar
        self.crear_pago(self.ana, self.cliente1, '99000', date(2026, 3, 5), 'efectivo')

        self.client.force_login(self.nico)

    # ---------------------------------------------------------------- helpers
    def crear_pago(self, admin, cliente, monto, fecha, tipo, estado='confirmado'):
        # bulk_create para no disparar el recálculo de la cuenta del cliente
        pago = RegistroPago(
            cliente=cliente, monto=Decimal(monto), fecha_pago=fecha, tipo_pago=tipo,
            estado=estado, concepto='Pago mensual', registrado_por=admin,
        )
        RegistroPago.objects.bulk_create([pago])
        return RegistroPago.objects.get(
            cliente=cliente, monto=Decimal(monto), fecha_pago=fecha, tipo_pago=tipo
        )

    def pedir(self, **extra):
        parametros = {
            'periodo': 'personalizado',
            'desde': self.desde.isoformat(),
            'hasta': self.hasta.isoformat(),
        }
        parametros.update(extra)
        return self.client.get(reverse('gravity:admin_pagos_por_admin'), parametros)

    def fila_de(self, respuesta, usuario):
        for fila in respuesta.context['filas']:
            if fila['admin'] == usuario:
                return fila
        self.fail(f'No hay fila para {usuario}')

    def tipo_de(self, fila, clave):
        return next(t for t in fila['tipos'] if t['clave'] == clave)

    # ------------------------------------------------------------------ tests
    def test_resumen_separa_efectivo_de_transferencia_por_administradora(self):
        respuesta = self.pedir()

        ana = self.fila_de(respuesta, self.ana)
        self.assertEqual(ana['cantidad'], 3)
        self.assertEqual(ana['monto'], Decimal('35000'))
        self.assertEqual(self.tipo_de(ana, 'efectivo')['cantidad'], 2)
        self.assertEqual(self.tipo_de(ana, 'efectivo')['monto'], Decimal('15000'))
        self.assertEqual(self.tipo_de(ana, 'transferencia')['cantidad'], 1)
        self.assertEqual(self.tipo_de(ana, 'transferencia')['monto'], Decimal('20000'))

        bea = self.fila_de(respuesta, self.bea)
        self.assertEqual(bea['cantidad'], 1)
        self.assertEqual(bea['monto'], Decimal('30000'))
        self.assertEqual(self.tipo_de(bea, 'efectivo')['cantidad'], 0)

    def test_los_anulados_no_suman_en_el_total_y_se_muestran_aparte(self):
        respuesta = self.pedir()

        ana = self.fila_de(respuesta, self.ana)
        self.assertEqual(ana['anulados_cantidad'], 1)
        self.assertEqual(ana['anulados_monto'], Decimal('7000'))
        self.assertNotIn(Decimal('7000'), [t['monto'] for t in ana['tipos']])

        totales = respuesta.context['totales']
        self.assertEqual(totales['cantidad'], 5)
        self.assertEqual(totales['monto'], Decimal('66000'))
        self.assertEqual(totales['anulados_cantidad'], 1)

    def test_los_superadmins_y_los_pagos_sin_autor_aparecen_en_el_resumen(self):
        respuesta = self.pedir()

        self.assertIn(self.nico, [fila['admin'] for fila in respuesta.context['filas']])
        sin_autor = [fila for fila in respuesta.context['filas'] if fila['es_sin_registrar']]
        self.assertEqual(len(sin_autor), 1)
        self.assertEqual(sin_autor[0]['monto'], Decimal('1000'))
        self.assertTrue(respuesta.context['hay_sin_registrar'])

    def test_el_periodo_de_un_dia_solo_trae_los_pagos_de_ese_dia(self):
        respuesta = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'dia', 'fecha': '2026-04-07'},
        )

        totales = respuesta.context['totales']
        self.assertEqual(totales['cantidad'], 1)
        self.assertEqual(totales['monto'], Decimal('30000'))
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 1)

    def test_el_periodo_de_una_semana_toma_de_lunes_a_domingo(self):
        # El 8/4/2026 es miércoles: la semana va del lunes 6 al domingo 12
        respuesta = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'semana', 'fecha': '2026-04-08'},
        )

        self.assertEqual(respuesta.context['desde'], date(2026, 4, 6))
        self.assertEqual(respuesta.context['hasta'], date(2026, 4, 12))
        self.assertEqual(respuesta.context['totales']['cantidad'], 3)

    def test_el_periodo_de_un_mes_no_trae_los_pagos_de_otros_meses(self):
        respuesta = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'mes', 'mes': '2026-03'},
        )

        self.assertEqual(respuesta.context['desde'], date(2026, 3, 1))
        self.assertEqual(respuesta.context['hasta'], date(2026, 3, 31))
        self.assertEqual(respuesta.context['totales']['cantidad'], 1)
        self.assertEqual(respuesta.context['totales']['monto'], Decimal('99000'))

    def test_el_rango_al_reves_se_da_vuelta_solo(self):
        respuesta = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'personalizado', 'desde': '2026-04-30', 'hasta': '2026-04-01'},
        )

        self.assertEqual(respuesta.context['desde'], date(2026, 4, 1))
        self.assertEqual(respuesta.context['hasta'], date(2026, 4, 30))
        self.assertEqual(respuesta.context['totales']['cantidad'], 5)

    def test_filtrar_por_administradora_deja_solo_sus_pagos(self):
        respuesta = self.pedir(admin=str(self.bea.id))

        self.assertEqual(len(respuesta.context['filas']), 1)
        self.assertEqual(respuesta.context['filas'][0]['admin'], self.bea)
        self.assertEqual(respuesta.context['totales']['monto'], Decimal('30000'))
        for pago in respuesta.context['page_obj']:
            self.assertEqual(pago.registrado_por, self.bea)

    def test_filtrar_por_forma_de_pago(self):
        respuesta = self.pedir(tipo='efectivo')

        self.assertEqual(respuesta.context['totales']['cantidad'], 2)
        self.assertEqual(respuesta.context['totales']['monto'], Decimal('15000'))
        for pago in respuesta.context['page_obj']:
            self.assertEqual(pago.tipo_pago, 'efectivo')

    def test_buscar_por_cliente(self):
        respuesta = self.pedir(buscar='Marta')

        self.assertEqual(respuesta.context['page_obj'].paginator.count, 2)
        for pago in respuesta.context['page_obj']:
            self.assertEqual(pago.cliente, self.cliente2)

    def test_se_puede_mirar_por_fecha_de_carga(self):
        # El pago se cobró en abril pero se cargó al sistema en mayo
        RegistroPago.objects.filter(id=self.sin_autor.id).update(
            fecha_registro=timezone.make_aware(datetime(2026, 5, 2, 10, 0))
        )

        por_pago = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'mes', 'mes': '2026-05', 'criterio': 'pago'},
        )
        self.assertEqual(por_pago.context['totales']['cantidad'], 0)

        por_carga = self.client.get(
            reverse('gravity:admin_pagos_por_admin'),
            {'periodo': 'mes', 'mes': '2026-05', 'criterio': 'carga'},
        )
        self.assertEqual(por_carga.context['totales']['cantidad'], 1)
        self.assertEqual(por_carga.context['totales']['monto'], Decimal('1000'))

    def test_la_pantalla_carga_y_muestra_a_las_administradoras(self):
        respuesta = self.pedir()

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Pagos por Administradora')
        self.assertContains(respuesta, 'Ana Gómez')
        self.assertContains(respuesta, 'Bea López')

    def test_un_admin_comun_no_puede_entrar(self):
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('gravity:admin_pagos_por_admin'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin-panel/', respuesta['Location'])
