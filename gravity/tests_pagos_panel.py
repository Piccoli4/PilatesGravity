"""Etapa 6 del panel: lista para cobrar, registrar pago, cancelar plan y planes."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CancelacionAdmin, Clase, EstadoPagoCliente, PlanPago, PlanUsuario, RegistroPago, Reserva


class PagosBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.superadmin = User.objects.create_superuser(username='nico', email='nico@test.com', password='clave-123', first_name='Nico')
        self.equipo = User.objects.create_user(username='diana', password='clave-123', is_staff=True, first_name='Diana')
        self.plan = PlanPago.objects.create(nombre='2 clases', clases_por_semana=2, precio_mensual=Decimal('60000'))
        self.client.force_login(self.equipo)

    def alumno(self, nombre, saldo=None, **extra):
        u = User.objects.create_user(username=nombre.lower(), password='x-clave-123', first_name=nombre,
                                     email=f'{nombre.lower()}@test.com', **extra)
        if saldo is not None:
            EstadoPagoCliente.objects.create(usuario=u, saldo_actual=Decimal(saldo), activo=True, plan_actual=self.plan)
        return u


class ListaParaCobrarTests(PagosBase):
    def test_por_defecto_muestra_quienes_deben_de_mayor_a_menor(self):
        poco = self.alumno('Poco', '-5000')
        mucho = self.alumno('Mucho', '-60000')
        self.alumno('Aldia', '0')
        self.alumno('Inactiva', '-90000', is_active=False)
        estados_antes = EstadoPagoCliente.objects.count()

        r = self.client.get(reverse('gravity:admin_pagos_vista_principal'))

        self.assertEqual([f['usuario'] for f in r.context['filas']], [mucho, poco])
        self.assertEqual(r.context['clientes_con_deuda'], 2)
        self.assertEqual(EstadoPagoCliente.objects.count(), estados_antes)  # ya no crea registros al mirar
        self.assertIsNone(r.context['ingresos_mes'])

    def test_filtros_y_busqueda(self):
        self.alumno('Ana', '2000')
        self.alumno('Bea')
        r = self.client.get(reverse('gravity:admin_pagos_vista_principal'), {'estado': 'a_favor'})
        self.assertEqual([f['usuario'].first_name for f in r.context['filas']], ['Ana'])
        r = self.client.get(reverse('gravity:admin_pagos_vista_principal'), {'estado': 'todos', 'buscar': 'be'})
        self.assertEqual([f['usuario'].first_name for f in r.context['filas']], ['Bea'])


class RegistrarPagoTests(PagosBase):
    def test_sugiere_montos_y_el_recibo_es_opcional(self):
        ana = self.alumno('Ana', '-60000')
        url = reverse('gravity:admin_pagos_registrar_pago', args=[ana.id])
        r = self.client.get(url)
        self.assertEqual([s['monto'] for s in r.context['sugerencias']], [Decimal('60000'), Decimal('60000'), Decimal('54000')])
        meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        self.assertEqual(r.context['form'].initial['concepto'], f'Cuota {meses[self.hoy.month - 1]} {self.hoy.year}')

        datos = {'monto': '30000', 'fecha_pago': self.hoy.isoformat(), 'tipo_pago': 'efectivo', 'concepto': 'Cuota'}
        r = self.client.post(url, datos)
        self.assertRedirects(r, reverse('gravity:admin_pagos_editar_estado_cliente', args=[ana.id]), fetch_redirect_response=False)
        self.assertEqual(RegistroPago.objects.get(cliente=ana).registrado_por, self.equipo)
        self.assertEqual(mail.outbox, [])

        self.client.post(url, dict(datos, enviar_recibo='on'))
        self.assertEqual(len(mail.outbox), 1)


class CancelarPlanTests(PagosBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.superadmin)
        self.ana = self.alumno('Ana', '0')
        self.plan1 = PlanPago.objects.create(nombre='1 clase', clases_por_semana=1, precio_mensual=Decimal('40000'))
        fin = self.hoy + timedelta(days=30)
        self.pu2 = PlanUsuario.objects.create(usuario=self.ana, plan=self.plan, fecha_inicio=self.hoy, fecha_fin=fin)
        self.reservas = []
        for i, dia in enumerate(['Lunes', 'Miércoles', 'Viernes']):
            clase = Clase.objects.create(tipo='Reformer', dia=dia, horario=time(9 + i), direccion='sede_2', cupo_maximo=5)
            self.reservas.append(Reserva.objects.create(usuario=self.ana, clase=clase))

    def test_con_otro_plan_sugiere_cancelar_solo_las_que_sobran(self):
        PlanUsuario.objects.create(usuario=self.ana, plan=self.plan1, fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=30))
        url = reverse('gravity:admin_cancelar_plan_usuario', args=[self.pu2.id])

        r = self.client.get(url)
        self.assertEqual(r.context['sugeridas'], {self.reservas[1].id, self.reservas[2].id})

        self.client.post(url, {'elegir': '1', 'reservas': [self.reservas[2].id]})
        activas = set(Reserva.objects.filter(usuario=self.ana, activa=True).values_list('id', flat=True))
        self.assertEqual(activas, {self.reservas[0].id, self.reservas[1].id})
        self.assertTrue(CancelacionAdmin.objects.filter(reserva=self.reservas[2], motivo='Baja del plan').exists())
        self.pu2.refresh_from_db()
        self.assertFalse(self.pu2.activo)

    def test_sin_otro_plan_cancela_todas(self):
        self.client.post(reverse('gravity:admin_cancelar_plan_usuario', args=[self.pu2.id]))
        self.assertFalse(Reserva.objects.filter(usuario=self.ana, activa=True).exists())


class PlanesTests(PagosBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.superadmin)

    def test_no_elimina_un_plan_que_tuvo_alumnos(self):
        ana = self.alumno('Ana')
        PlanUsuario.objects.create(usuario=ana, plan=self.plan, fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=30), activo=False)
        self.client.post(reverse('gravity:admin_pagos_configurar_planes'), {'eliminar_plan': self.plan.id})
        self.assertTrue(PlanPago.objects.filter(pk=self.plan.pk).exists())

    def test_un_error_al_editar_deja_ese_plan_abierto(self):
        r = self.client.post(reverse('gravity:admin_pagos_configurar_planes'), {
            'editar_plan': self.plan.id, 'nombre': self.plan.nombre, 'clases_por_semana': 9,
            'precio_mensual': '60000', 'descripcion': '', 'activo': 'True',
        })
        fila = next(f for f in r.context['filas'] if f['plan'] == self.plan)
        self.assertTrue(fila['abierto'])
        self.assertTrue(fila['form'].errors)

    def test_la_cuenta_tiene_las_correcciones_solo_para_el_superadmin(self):
        ana = self.alumno('Ana', '-1000')
        url = reverse('gravity:admin_pagos_editar_estado_cliente', args=[ana.id])
        self.assertContains(self.client.get(url), 'id="dlg-saldo"')
        self.client.force_login(self.equipo)
        self.assertNotContains(self.client.get(url), 'id="dlg-saldo"')
