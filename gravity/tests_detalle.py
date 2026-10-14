"""Detalle de reserva (/reserva/<número>/)."""
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AusenciaTemporal, Clase, Reserva

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


class DetalleReservaTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.client.force_login(self.alumna)
        hoy = timezone.localtime(timezone.now()).date()
        self.fecha = hoy + timedelta(days=3 if (hoy + timedelta(days=3)).weekday() != 6 else 4)
        self.clase = Clase.objects.create(tipo='Reformer', dia=DIAS[self.fecha.weekday()], horario=time(18),
                                          direccion='sede_2', cupo_maximo=5)
        self.fija = Reserva.objects.create(usuario=self.alumna, clase=self.clase)

    def url(self, reserva):
        return reverse('gravity:detalle_reserva', args=[reserva.numero_reserva])

    def test_horario_fijo(self):
        response = self.client.get(self.url(self.fija))
        self.assertContains(response, 'Horario fijo')
        self.assertContains(response, f'Todos los {self.clase.dia.lower()}')
        self.assertContains(response, 'Avisar que no voy')
        self.assertContains(response, 'Dar de baja este horario')
        self.assertEqual(len(response.context['d']['fechas']), 4)

    def test_deshacer_aviso_vuelve_al_detalle(self):
        ausencia = AusenciaTemporal.objects.create(reserva=self.fija, fecha=self.fecha)
        response = self.client.get(self.url(self.fija))
        self.assertContains(response, 'Deshacer aviso')
        response = self.client.post(reverse('gravity:cancelar_ausencia', args=[ausencia.id]),
                                    {'next': self.url(self.fija)})
        self.assertRedirects(response, self.url(self.fija), fetch_redirect_response=False)

    def test_recupero(self):
        recupero = Reserva.objects.create(usuario=self.alumna, clase=Clase.objects.create(
            tipo='Reformer', dia=self.clase.dia, horario=time(9), direccion='sede_principal', cupo_maximo=5),
            es_recupero=True, fecha_unica=self.fecha)
        response = self.client.get(self.url(recupero))
        self.assertContains(response, 'Recupero')
        self.assertContains(response, 'No usa clases del plan')
        self.assertContains(response, 'Cancelar recupero')

    def test_reserva_de_otra_persona_o_inactiva(self):
        otra = User.objects.create_user(username='otra', password='clave-de-prueba-123')
        ajena = Reserva.objects.create(usuario=otra, clase=self.clase)
        self.assertRedirects(self.client.get(self.url(ajena)), reverse('accounts:mis_reservas'),
                             fetch_redirect_response=False)
        Reserva.objects.filter(pk=self.fija.pk).update(activa=False)
        self.assertRedirects(self.client.get(self.url(self.fija)), reverse('accounts:mis_reservas'),
                             fetch_redirect_response=False)

    def test_pide_iniciar_sesion(self):
        self.client.logout()
        response = self.client.get(self.url(self.fija))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
