"""Tests del circuito de planes del alumno: Mis planes, elegir, cambiar y dar de baja."""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Clase, PlanPago, PlanUsuario, Reserva, SolicitudCambioPlan
from .views import politica_baja_plan


def crear_clase(dia, hora=18):
    return Clase.objects.create(tipo='Reformer', dia=dia, horario=time(hora), direccion='sede_2', cupo_maximo=9)


class PlanesBase(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.client.force_login(self.alumna)
        self.hoy = timezone.localtime(timezone.now()).date()
        self.plan1 = PlanPago.objects.create(nombre='1 clase semanal', clases_por_semana=1, precio_mensual=Decimal('45000'))
        self.plan2 = PlanPago.objects.create(nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000'))
        self.plan3 = PlanPago.objects.create(nombre='3 clases semanales', clases_por_semana=3, precio_mensual=Decimal('70000'))

    def dar_plan(self, plan):
        return PlanUsuario.objects.create(usuario=self.alumna, plan=plan, fecha_inicio=self.hoy - timedelta(days=3),
                                          fecha_fin=self.hoy + timedelta(days=20))

    def reservar(self, *dias):
        return [Reserva.objects.create(usuario=self.alumna, clase=crear_clase(d)) for d in dias]


class MisPlanesTests(PlanesBase):
    def test_sin_plan(self):
        response = self.client.get(reverse('gravity:mis_planes'))
        self.assertContains(response, 'Todavía no tenés un plan activo')
        self.assertContains(response, reverse('gravity:seleccionar_plan'))

    def test_con_plan_muestra_precios_y_uso(self):
        self.dar_plan(self.plan2)
        self.reservar('Lunes')
        response = self.client.get(reverse('gravity:mis_planes'))
        self.assertContains(response, '2 clases semanales')
        self.assertContains(response, '$61.000')
        self.assertContains(response, '$55.000')  # 10% off redondeado al millar
        self.assertContains(response, '1 de 2')
        self.assertContains(response, 'Cambiar de plan')
        self.assertContains(response, 'Si das de baja tu plan hoy')


class PoliticaBajaTests(TestCase):
    def test_tramos(self):
        self.assertEqual(politica_baja_plan(date(2026, 10, 4))['tipo'], 'sin_cargo')
        self.assertEqual(politica_baja_plan(date(2026, 10, 5))['tipo'], 'medio_mes')
        self.assertEqual(politica_baja_plan(date(2026, 10, 9))['tipo'], 'medio_mes')
        self.assertEqual(politica_baja_plan(date(2026, 10, 10))['tipo'], 'mes_completo')


class SeleccionarPlanTests(PlanesBase):
    def test_muestra_precio_de_lista_y_efectivo(self):
        response = self.client.get(reverse('gravity:seleccionar_plan'))
        self.assertContains(response, '$45.000')
        self.assertContains(response, '$41.000')  # 40.500 → 41.000

    def test_enviar_solicitud(self):
        response = self.client.post(reverse('gravity:seleccionar_plan'), {'plan_id': self.plan2.id})
        self.assertRedirects(response, reverse('gravity:mis_planes'), fetch_redirect_response=False)
        self.assertTrue(SolicitudCambioPlan.objects.filter(usuario=self.alumna, plan_solicitado=self.plan2,
                                                           estado='pendiente').exists())


class CambiarPlanTests(PlanesBase):
    def test_bajar_de_plan_pide_liberar_horarios(self):
        self.dar_plan(self.plan3)
        lunes, miercoles, viernes = self.reservar('Lunes', 'Miércoles', 'Viernes')
        url = reverse('gravity:modificar_plan')

        response = self.client.get(url)
        planes = {p.id: p for p in response.context['planes_disponibles']}
        self.assertEqual(planes[self.plan2.id].a_ceder, 1)
        self.assertEqual(planes[self.plan1.id].a_ceder, 2)

        # Sin marcar horarios no se envía
        response = self.client.post(url, {'plan_id': self.plan2.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['plan_elegido_id'], self.plan2.id)
        self.assertFalse(SolicitudCambioPlan.objects.exists())

        # Marcando uno, sí
        response = self.client.post(url, {'plan_id': self.plan2.id, 'reservas': [miercoles.id]})
        self.assertRedirects(response, reverse('gravity:mis_planes'), fetch_redirect_response=False)
        solicitud = SolicitudCambioPlan.objects.get()
        self.assertEqual(list(solicitud.reservas_a_cancelar.all()), [miercoles])

    def test_bajar_de_plan_sin_liberar_si_los_horarios_entran(self):
        self.dar_plan(self.plan3)
        self.reservar('Lunes')
        response = self.client.post(reverse('gravity:modificar_plan'), {'plan_id': self.plan2.id})
        self.assertRedirects(response, reverse('gravity:mis_planes'), fetch_redirect_response=False)
        self.assertFalse(SolicitudCambioPlan.objects.get().reservas_a_cancelar.exists())

    def test_url_vieja_del_paso_2_redirige(self):
        response = self.client.get(reverse('gravity:elegir_reservas_downgrade'))
        self.assertRedirects(response, reverse('gravity:modificar_plan'), fetch_redirect_response=False)


class DarDeBajaPlanTests(PlanesBase):
    def test_muestra_consecuencias(self):
        plan = self.dar_plan(self.plan2)
        self.reservar('Lunes', 'Jueves')
        response = self.client.get(reverse('gravity:cancelar_plan', args=[plan.id]))
        self.assertContains(response, 'Se cancelan ya mismo tus 2 reservas')
        self.assertContains(response, politica_baja_plan(self.hoy)['texto'].lower())
        self.assertContains(response, 'name="confirmar_cancelacion" value="confirmar"')


class MasElegidoTests(PlanesBase):
    """El "Más elegido" de Precios y Elegí tu ritmo es el plan con más alumnos vigentes."""

    def alumno_con(self, plan, activo=True, vencido=False, nombre=None):
        u = User.objects.create_user(username=nombre or f'a{User.objects.count()}', is_active=activo)
        fin = self.hoy - timedelta(days=1) if vencido else self.hoy + timedelta(days=20)
        PlanUsuario.objects.create(usuario=u, plan=plan, fecha_inicio=self.hoy - timedelta(days=40), fecha_fin=fin)

    def destacados(self):
        from .views import anotar_planes
        return [p for p in anotar_planes(PlanPago.objects.all()) if p.destacado]

    def test_marca_el_plan_con_mas_alumnos(self):
        self.alumno_con(self.plan3)
        self.alumno_con(self.plan3)
        self.alumno_con(self.plan1)
        self.assertEqual(self.destacados(), [self.plan3])

    def test_no_cuentan_planes_vencidos_ni_cuentas_desactivadas(self):
        self.alumno_con(self.plan1)
        self.alumno_con(self.plan3, vencido=True)
        self.alumno_con(self.plan3, activo=False)
        self.assertEqual(self.destacados(), [self.plan1])

    def test_si_empatan_gana_el_mas_barato(self):
        self.alumno_con(self.plan2)
        self.alumno_con(self.plan3)
        self.assertEqual(self.destacados(), [self.plan2])

    def test_sin_alumnos_no_destaca_ninguno(self):
        self.assertEqual(self.destacados(), [])

    def test_se_ve_en_precios(self):
        self.alumno_con(self.plan2)
        response = self.client.get(reverse('gravity:precios_publicos'))
        self.assertContains(response, 'Más elegido', count=1)
