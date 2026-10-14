"""Reglas de recupero (tipo de clase, plazo, qué recupero cubre cada ausencia) y la vista /reservar-recupero/."""
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AusenciaTemporal, Clase, NotificacionCancelacion, Reserva
from .recuperos import EstadoRecuperos

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


class RecuperosBase(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.client.force_login(self.alumna)
        self.ahora = timezone.localtime(timezone.now())
        self.hoy = self.ahora.date()
        # Fecha futura que no sea domingo, dentro del plazo de una ausencia de ayer
        self.fecha = self.hoy + timedelta(days=2 if (self.hoy + timedelta(days=2)).weekday() != 6 else 3)

    def clase(self, tipo, fecha=None, hora=18):
        fecha = fecha or self.fecha
        return Clase.objects.create(tipo=tipo, dia=DIAS[fecha.weekday()], horario=time(hora), direccion='sede_2', cupo_maximo=5)

    def faltar(self, tipo, dias_atras=1):
        fecha = self.hoy - timedelta(days=dias_atras)
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase(tipo, fecha, hora=7))
        return AusenciaTemporal.objects.create(reserva=reserva, fecha=fecha)

    def recupero(self, tipo, activa=True, fecha=None):
        fecha = fecha or self.fecha
        return Reserva.objects.create(usuario=self.alumna, clase=self.clase(tipo, fecha, hora=20), es_recupero=True,
                                      fecha_unica=fecha, activa=activa)


class ReglasRecuperoTests(RecuperosBase):
    def test_reformer_solo_se_recupera_en_reformer(self):
        self.faltar('Reformer')
        estado = EstadoRecuperos(self.alumna)
        self.assertTrue(estado.puede_recuperar('Reformer', self.fecha))
        self.assertFalse(estado.puede_recuperar('Cadillac', self.fecha))

    def test_cadillac_se_recupera_en_cadillac_o_reformer(self):
        self.faltar('Cadillac')
        estado = EstadoRecuperos(self.alumna)
        self.assertTrue(estado.puede_recuperar('Reformer', self.fecha))
        self.assertTrue(estado.puede_recuperar('Cadillac', self.fecha))

    def test_cada_recupero_cubre_la_ausencia_que_corresponde(self):
        """Faltó a Cadillac y a Reformer y ya recuperó en Cadillac: lo que queda es Reformer."""
        self.faltar('Cadillac', dias_atras=1)
        self.faltar('Reformer', dias_atras=2)
        self.recupero('Cadillac')
        estado = EstadoRecuperos(self.alumna)
        self.assertEqual(estado.disponibles, 1)
        self.assertTrue(estado.puede_recuperar('Reformer', self.fecha))
        self.assertFalse(estado.puede_recuperar('Cadillac', self.fecha))

    def test_un_recupero_ya_hecho_sigue_contando(self):
        self.faltar('Reformer', dias_atras=3)
        self.recupero('Reformer', activa=False, fecha=self.hoy - timedelta(days=1))  # la limpieza diaria lo desactivó
        self.assertEqual(EstadoRecuperos(self.alumna).disponibles, 0)

    def test_un_recupero_cancelado_no_cuenta(self):
        self.faltar('Reformer')
        cancelado = self.recupero('Reformer', activa=False)
        NotificacionCancelacion.objects.create(reserva=cancelado, tipo='permanente')
        self.assertEqual(EstadoRecuperos(self.alumna).disponibles, 1)

    def test_no_pasa_el_plazo(self):
        ausencia = self.faltar('Reformer', dias_atras=1)
        estado = EstadoRecuperos(self.alumna)
        self.assertTrue(estado.puede_recuperar('Reformer', ausencia.fecha_limite_recupero))
        self.assertFalse(estado.puede_recuperar('Reformer', ausencia.fecha_limite_recupero + timedelta(days=1)))

    def test_clase_de_hoy_hasta_que_empieza(self):
        self.faltar('Reformer')
        estado = EstadoRecuperos(self.alumna)
        if self.hoy.weekday() == 6 or self.ahora.hour >= 23:
            self.skipTest('Necesita un día con clases y que falte al menos una hora para la medianoche')
        mas_tarde = Clase.objects.create(tipo='Reformer', dia=DIAS[self.hoy.weekday()], horario=time(23, 59),
                                         direccion='sede_2', cupo_maximo=5)
        self.assertTrue(estado.puede_recuperar_en(mas_tarde, self.hoy))
        if self.ahora.hour >= 1:
            temprano = Clase.objects.create(tipo='Reformer', dia=DIAS[self.hoy.weekday()], horario=time(0, 0),
                                            direccion='sede_2', cupo_maximo=5)
            self.assertFalse(estado.puede_recuperar_en(temprano, self.hoy))


class ReservarRecuperoViewTests(RecuperosBase):
    def test_sin_ausencias_vuelve_a_mis_reservas(self):
        response = self.client.get(reverse('gravity:reservar_recupero'))
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)

    def test_grilla_y_reserva(self):
        self.faltar('Reformer')
        reformer = self.clase('Reformer', hora=10)
        cadillac = self.clase('Cadillac', hora=11)
        url = reverse('gravity:reservar_recupero')

        response = self.client.get(url)
        ids = {s['clase'].id for col in response.context['grilla']['columnas'] for s in col['slots']}
        self.assertIn(reformer.id, ids)
        self.assertNotIn(cadillac.id, ids)
        self.assertContains(response, 'Tenés 1 clase para recuperar')

        # Cadillac no corresponde a una ausencia de Reformer
        self.client.post(url, {'clase_id': cadillac.id, 'fecha': self.fecha.isoformat()})
        self.assertFalse(Reserva.objects.filter(usuario=self.alumna, es_recupero=True).exists())

        response = self.client.post(url, {'clase_id': reformer.id, 'fecha': self.fecha.isoformat()})
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)
        recupero = Reserva.objects.get(usuario=self.alumna, es_recupero=True)
        self.assertEqual((recupero.clase, recupero.fecha_unica), (reformer, self.fecha))

        # Ya no quedan recuperos
        response = self.client.get(url)
        self.assertRedirects(response, reverse('accounts:mis_reservas'), fetch_redirect_response=False)

    def test_fecha_que_no_coincide_con_el_dia_de_la_clase(self):
        self.faltar('Reformer')
        reformer = self.clase('Reformer', hora=10)
        otra_fecha = self.fecha + timedelta(days=1)
        self.client.post(reverse('gravity:reservar_recupero'), {'clase_id': reformer.id, 'fecha': otra_fecha.isoformat()})
        self.assertFalse(Reserva.objects.filter(usuario=self.alumna, es_recupero=True).exists())
