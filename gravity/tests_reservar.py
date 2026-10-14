"""Tests de /reservar_clase/: grilla semanal, estados de cada horario y validación de cupos."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AusenciaTemporal, Clase, PlanPago, PlanUsuario, Reserva

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


class ReservarBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localtime(timezone.now()).date()
        # Un día con clases dentro de 2 o 3 días (los domingos no hay clases)
        offset = 2 if (self.hoy + timedelta(days=2)).weekday() != 6 else 3
        self.fecha = self.hoy + timedelta(days=offset)
        self.dia = DIAS[self.fecha.weekday()]

        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.otra = User.objects.create_user(username='otra', password='clave-de-prueba-123')
        self.client.force_login(self.alumna)
        self.url = reverse('gravity:reservar_clase')

        plan = PlanPago.objects.create(nombre='3 clases semanales', clases_por_semana=3, precio_mensual=Decimal('70000'))
        PlanUsuario.objects.create(usuario=self.alumna, plan=plan, fecha_inicio=self.hoy - timedelta(days=2),
                                   fecha_fin=self.hoy + timedelta(days=25))

    def clase(self, hora, cupo=5, sede='sede_2'):
        return Clase.objects.create(tipo='Reformer', dia=self.dia, horario=time(hora), direccion=sede, cupo_maximo=cupo)

    def estados(self, response):
        return {s['clase'].id: s['estado'] for col in response.context['grilla']['columnas'] for s in col['slots']}

    def datos(self, clase, temporal=False):
        return {'tipo_clase': clase.tipo, 'sede': clase.direccion, 'dia': clase.dia,
                'horario': clase.horario.strftime('%H:%M'), 'es_temporal': 'true' if temporal else 'false'}


class ReservarClaseTests(ReservarBase):
    def test_estados_de_la_grilla(self):
        libre = self.clase(8)
        mia = self.clase(9)
        Reserva.objects.create(usuario=self.alumna, clase=mia)
        llena = self.clase(10, cupo=1)
        Reserva.objects.create(usuario=self.otra, clase=llena)
        suelta = self.clase(11, cupo=1)
        r = Reserva.objects.create(usuario=self.otra, clase=suelta)
        AusenciaTemporal.objects.create(reserva=r, fecha=self.fecha)

        response = self.client.get(self.url)
        estados = self.estados(response)
        self.assertEqual(estados[libre.id], 'libre')
        self.assertEqual(estados[mia.id], 'tuya')
        self.assertEqual(estados[llena.id], 'completa')
        self.assertEqual(estados[suelta.id], 'solo_fecha')
        self.assertTrue(response.context['puede_reservar'])

    def test_reservar_horario_fijo(self):
        clase = self.clase(8)
        response = self.client.post(self.url, self.datos(clase))
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)
        reserva = Reserva.objects.get(usuario=self.alumna)
        self.assertIsNone(reserva.fecha_unica)

    def test_no_se_sobrevende_un_horario_lleno(self):
        """Clase llena con un lugar suelto esa semana: como horario fijo no, una sola vez sí."""
        clase = self.clase(11, cupo=1)
        r = Reserva.objects.create(usuario=self.otra, clase=clase)
        AusenciaTemporal.objects.create(reserva=r, fecha=self.fecha)

        response = self.client.post(self.url, self.datos(clase))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no tiene lugares fijos')
        self.assertFalse(Reserva.objects.filter(usuario=self.alumna).exists())

        response = self.client.post(self.url, self.datos(clase, temporal=True))
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)
        self.assertEqual(Reserva.objects.get(usuario=self.alumna).fecha_unica, self.fecha)

    def test_preseleccion_desde_clases_disponibles(self):
        clase = self.clase(8)
        response = self.client.get(self.url, {'tipo': 'Reformer', 'sede': 'sede_2', 'dia': self.dia, 'horario': '08:00'})
        self.assertContains(response, 'data-pre-horario="08:00"')
        self.assertContains(response, f'data-pre-dia="{self.dia}"')

    def test_sin_plan_la_grilla_es_solo_para_mirar(self):
        PlanUsuario.objects.all().delete()
        self.clase(8)
        response = self.client.get(self.url)
        self.assertFalse(response.context['puede_reservar'])
        self.assertContains(response, 'Para reservar necesitás un plan')


class CupoSueltoYRecuperoTests(ReservarBase):
    """Lugares sueltos y recuperos desde la grilla de Reservar clase."""

    def faltar_a(self, tipo):
        ayer = self.hoy - timedelta(days=1)
        clase = Clase.objects.create(tipo=tipo, dia=DIAS[ayer.weekday()], horario=time(7), direccion='sede_2', cupo_maximo=5)
        reserva = Reserva.objects.create(usuario=self.alumna, clase=clase)
        return AusenciaTemporal.objects.create(reserva=reserva, fecha=ayer)

    def test_url_vieja_de_cupo_temporal_abre_la_grilla(self):
        clase = self.clase(11, cupo=1)
        response = self.client.get(reverse('gravity:reservar_cupo_temporal', args=[clase.id, self.fecha.isoformat()]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('gravity:reservar_clase'), response.url)
        self.assertIn('es_temporal=1', response.url)
        self.assertIn('horario=11%3A00', response.url)

    def test_una_vez_con_ausencia_pendiente_es_recupero_aunque_el_plan_este_completo(self):
        self.faltar_a('Cadillac')
        # Completa las 3 clases del plan con horarios fijos
        for hora in (6, 7, 8):
            Reserva.objects.create(usuario=self.alumna, clase=self.clase(hora + 10, sede='sede_principal'))
        clase = self.clase(9)

        response = self.client.get(self.url)
        self.assertFalse(response.context['puede_reservar'])
        slot = next(s for col in response.context['grilla']['columnas'] for s in col['slots'] if s['clase'] == clase)
        self.assertTrue(slot['recupero'])

        # Como horario fijo no (plan completo); una sola vez sí, como recupero
        self.client.post(self.url, self.datos(clase))
        self.assertFalse(Reserva.objects.filter(usuario=self.alumna, clase=clase).exists())
        response = self.client.post(self.url, self.datos(clase, temporal=True))
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)
        reserva = Reserva.objects.get(usuario=self.alumna, clase=clase)
        self.assertTrue(reserva.es_recupero)
        self.assertEqual(reserva.fecha_unica, self.fecha)

    def test_reformer_faltado_no_se_recupera_en_cadillac(self):
        self.faltar_a('Reformer')
        cadillac = Clase.objects.create(tipo='Cadillac', dia=self.dia, horario=time(9), direccion='sede_2', cupo_maximo=5)
        self.client.post(self.url, {'tipo_clase': 'Cadillac', 'sede': 'sede_2', 'dia': self.dia,
                                    'horario': '09:00', 'es_temporal': 'true'})
        reserva = Reserva.objects.get(usuario=self.alumna, clase=cadillac)
        self.assertFalse(reserva.es_recupero)  # usa una clase del plan

    def test_limite_semanal_en_la_semana_de_la_clase(self):
        lunes = self.hoy - timedelta(days=self.hoy.weekday()) if self.hoy.weekday() != 6 else self.hoy + timedelta(days=1)
        PlanUsuario.objects.update(plan=PlanPago.objects.create(nombre='1 clase', clases_por_semana=1,
                                                                 precio_mensual=Decimal('45000')))
        Reserva.objects.create(usuario=self.alumna, clase=self.clase(8), fecha_unica=lunes + timedelta(days=1))
        clase = self.clase(9)
        self.assertFalse(Reserva.usuario_puede_reservar(self.alumna, clase)[0])
        self.assertTrue(Reserva.usuario_puede_reservar(self.alumna, clase, fecha=lunes + timedelta(days=8))[0])
