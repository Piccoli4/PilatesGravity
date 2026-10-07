"""
Tests contra reservas duplicadas.

Reproducen el problema real de producción (05/10/2026): el admin cargó una reserva
desde el celular, el email de confirmación se enviaba dentro de la transacción y
tardó ~11 s; volvió a tocar "Confirmar" y el segundo POST no vio la reserva todavía
sin confirmar, creando un duplicado.
"""
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import Clase, Reserva


def crear_clase(**kwargs):
    datos = dict(tipo='Reformer', dia='Miércoles', horario=time(10),
                 direccion='sede_principal', cupo_maximo=9)
    datos.update(kwargs)
    return Clase.objects.create(**datos)


class ConstraintsReservaTests(TestCase):
    """La base de datos rechaza duplicados aunque se saltee clean()."""

    def setUp(self):
        self.alumna = User.objects.create_user(username='avril', password='clave123')
        self.clase = crear_clase()

    def test_no_permite_dos_reservas_permanentes_activas(self):
        Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        # bulk_create no llama a save()/clean(): simula la carrera entre dos requests
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reserva.objects.bulk_create([
                Reserva(usuario=self.alumna, clase=self.clase, numero_reserva='DUPLIC01')
            ])

    def test_permite_nueva_reserva_si_la_anterior_esta_cancelada(self):
        Reserva.objects.create(usuario=self.alumna, clase=self.clase, activa=False)
        Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        self.assertEqual(Reserva.objects.filter(usuario=self.alumna, activa=True).count(), 1)

    def test_fecha_unica_permite_fechas_distintas_y_rechaza_la_misma(self):
        hoy = timezone.localtime(timezone.now()).date()
        Reserva.objects.create(usuario=self.alumna, clase=self.clase, fecha_unica=hoy)
        Reserva.objects.create(usuario=self.alumna, clase=self.clase,
                               fecha_unica=hoy + timedelta(days=7))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reserva.objects.bulk_create([
                Reserva(usuario=self.alumna, clase=self.clase, fecha_unica=hoy,
                        numero_reserva='DUPLIC02')
            ])


class AdminReservarParaUsuarioTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='nico', password='clave123', first_name='Nico', is_staff=True
        )
        self.alumna = User.objects.create_user(username='avril', password='clave123')
        self.clase = crear_clase()
        self.url = reverse('gravity:admin_reservar_para_usuario_clase', args=[self.clase.id])
        self.datos = {'clase': self.clase.id, 'usuario': self.alumna.id,
                      'tipo_reserva': 'recurrente'}
        self.client.force_login(self.admin)

    def test_guarda_quien_creo_la_reserva(self):
        self.client.post(self.url, self.datos)
        reserva = Reserva.objects.get(usuario=self.alumna)
        self.assertEqual(reserva.creado_por, self.admin)

    def test_segundo_envio_no_duplica(self):
        self.client.post(self.url, self.datos)
        respuesta = self.client.post(self.url, self.datos, follow=True)
        self.assertEqual(Reserva.objects.filter(usuario=self.alumna, activa=True).count(), 1)
        self.assertContains(respuesta, 'ya tiene una reserva activa')

    def test_detalle_de_clase_muestra_quien_creo_la_reserva(self):
        self.client.post(self.url, self.datos)
        otra = User.objects.create_user(username='pilar', password='clave123')
        Reserva.objects.create(usuario=otra, clase=self.clase, creado_por=otra)

        respuesta = self.client.get(reverse('gravity:admin_clase_detalle', args=[self.clase.id]))
        self.assertContains(respuesta, 'por Nico')
        self.assertContains(respuesta, 'por el alumno')


class AdminReservaEmailFueraDeTransaccionTests(TransactionTestCase):
    """El email se envía con la reserva ya confirmada (fuera de cualquier transacción)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='nico', password='clave123', is_staff=True
        )
        self.alumna = User.objects.create_user(
            username='avril', password='clave123', email='avril@test.com'
        )
        self.clase = crear_clase()
        self.client.force_login(self.admin)

    def test_email_se_envia_despues_del_commit(self):
        estado = {}

        def email_falso(reserva):
            estado['en_transaccion'] = connection.in_atomic_block
            return True

        with mock.patch('gravity.views.enviar_email_confirmacion_reserva_detallado',
                        side_effect=email_falso):
            self.client.post(
                reverse('gravity:admin_reservar_para_usuario_clase', args=[self.clase.id]),
                {'clase': self.clase.id, 'usuario': self.alumna.id,
                 'tipo_reserva': 'recurrente', 'notificar_usuario': 'on'},
            )

        self.assertIn('en_transaccion', estado, 'No se llamó al envío de email')
        self.assertFalse(estado['en_transaccion'])
