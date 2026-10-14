"""Etapa 4 del panel: lista de reservas, reservar para un alumno, cambiar y cancelar."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AusenciaTemporal, CancelacionAdmin, Clase, NotificacionCancelacion, PlanPago, PlanUsuario, Reserva,
)
from .reservas_admin import DIAS, proximas_fechas


class ReservasBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.admin = User.objects.create_user(username='nico', password='clave-123', first_name='Nico', is_staff=True)
        self.client.force_login(self.admin)
        self.alumna = User.objects.create_user(username='avril', password='clave-123', first_name='Avril',
                                               last_name='Sosa', email='avril@test.com')
        self.manana = self.hoy + timedelta(days=1)
        if self.manana.weekday() == 6:
            self.manana += timedelta(days=1)
        self.clase = self.crear_clase(self.manana)

    def crear_clase(self, fecha, hora=18, cupo=5, tipo='Reformer'):
        return Clase.objects.create(tipo=tipo, dia=DIAS[fecha.weekday()], horario=time(hora),
                                    direccion='sede_2', cupo_maximo=cupo)

    def dar_plan(self, clases=1):
        plan = PlanPago.objects.create(nombre=f'{clases} clase', clases_por_semana=clases, precio_mensual=Decimal('50000'))
        PlanUsuario.objects.create(usuario=self.alumna, plan=plan, fecha_inicio=self.hoy - timedelta(days=1),
                                   fecha_fin=self.hoy + timedelta(days=30))


class ListaReservasTests(ReservasBase):
    def test_pestanas_y_estado_real_del_historial(self):
        Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        Reserva.objects.create(usuario=self.alumna, clase=self.crear_clase(self.manana, hora=9), fecha_unica=self.manana)
        ayer = self.hoy - timedelta(days=1)
        # Recupero que ya se hizo (lo desactivó el comando de limpieza)
        Reserva.objects.create(usuario=self.alumna, clase=self.crear_clase(ayer, hora=10), fecha_unica=ayer,
                               es_recupero=True, activa=False)
        # Horario fijo cancelado por el estudio
        cancelada = Reserva.objects.create(usuario=self.alumna, clase=self.crear_clase(ayer, hora=11))
        cancelada.activa = False
        cancelada.save()
        CancelacionAdmin.objects.create(reserva=cancelada, admin_user=self.admin, motivo='Otro')

        r = self.client.get(reverse('gravity:admin_reservas_lista'))
        self.assertEqual([p['cantidad'] for p in r.context['pestanas']], [1, 1, 2])

        r = self.client.get(reverse('gravity:admin_reservas_lista'), {'ver': 'historial'})
        estados = sorted(f['estado'][0] for f in r.context['filas'])
        self.assertEqual(estados, ['Cancelada por el estudio', 'Realizada'])

    def test_buscador_y_filtros(self):
        Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        otra = User.objects.create_user(username='pilar', password='x-clave-123', first_name='Pilar')
        Reserva.objects.create(usuario=otra, clase=self.crear_clase(self.manana, hora=8))
        r = self.client.get(reverse('gravity:admin_reservas_lista'), {'usuario': 'avri'})
        self.assertEqual(len(r.context['filas']), 1)
        r = self.client.get(reverse('gravity:admin_reservas_lista'), {'sede': 'sede_principal'})
        self.assertEqual(len(r.context['filas']), 0)


class CambiarReservaTests(ReservasBase):
    def test_mueve_un_horario_fijo_aunque_el_plan_este_completo(self):
        self.dar_plan(1)
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        nueva = self.crear_clase(self.hoy + timedelta(days=3), hora=10)

        r = self.client.post(reverse('gravity:admin_reserva_modificar', args=[reserva.id]), {'nueva_clase': nueva.id})

        reserva.refresh_from_db()
        self.assertEqual(reserva.clase, nueva)
        self.assertRedirects(r, reverse('gravity:admin_usuario_detalle', args=[self.alumna.id]), fetch_redirect_response=False)

    def test_no_pasa_a_una_clase_sin_lugar(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        llena = self.crear_clase(self.manana, hora=7, cupo=1)
        Reserva.objects.create(usuario=self.admin, clase=llena)
        r = self.client.post(reverse('gravity:admin_reserva_modificar', args=[reserva.id]), {'nueva_clase': llena.id})
        self.assertContains(r, 'no tiene lugares fijos libres')
        reserva.refresh_from_db()
        self.assertEqual(reserva.clase, self.clase)

    def test_un_recupero_cambia_de_clase_y_de_fecha(self):
        recupero = Reserva.objects.create(usuario=self.alumna, clase=self.clase, fecha_unica=self.manana, es_recupero=True)
        otra_fecha = self.hoy + timedelta(days=4)
        if otra_fecha.weekday() == 6:
            otra_fecha += timedelta(days=1)
        nueva = self.crear_clase(otra_fecha, hora=9)
        fecha = proximas_fechas(nueva)[1]

        self.client.post(reverse('gravity:admin_reserva_modificar', args=[recupero.id]),
                         {'nueva_clase': nueva.id, 'fecha': fecha.isoformat()})

        recupero.refresh_from_db()
        self.assertEqual((recupero.clase, recupero.fecha_unica), (nueva, fecha))
        self.assertEqual(DIAS[recupero.fecha_unica.weekday()], nueva.dia)


class CancelarReservaTests(ReservasBase):
    def test_avisar_la_ausencia_de_una_fecha(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        fecha = proximas_fechas(self.clase)[1]
        destino = reverse('gravity:admin_clase_detalle', args=[self.clase.id])

        r = self.client.post(reverse('gravity:admin_reserva_cancelar', args=[reserva.id]),
                             {'alcance': 'fecha', 'fecha': fecha.isoformat(), 'next': destino})

        self.assertRedirects(r, destino, fetch_redirect_response=False)
        reserva.refresh_from_db()
        self.assertTrue(reserva.activa)
        self.assertTrue(AusenciaTemporal.objects.filter(reserva=reserva, fecha=fecha).exists())
        aviso = NotificacionCancelacion.objects.get(reserva=reserva)
        self.assertEqual(aviso.tipo, 'temporal')
        self.assertIn(self.admin, aviso.leida_por.all())

    def test_dar_de_baja_y_no_seguir_un_next_externo(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        r = self.client.post(reverse('gravity:admin_reserva_cancelar', args=[reserva.id]),
                             {'alcance': 'baja', 'motivo': 'Pedido del alumno', 'next': 'https://otro-sitio.com/'})
        self.assertRedirects(r, reverse('gravity:admin_usuario_detalle', args=[self.alumna.id]), fetch_redirect_response=False)
        reserva.refresh_from_db()
        self.assertFalse(reserva.activa)

    def test_la_pantalla_no_escribe_un_next_peligroso(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        r = self.client.get(reverse('gravity:admin_reserva_cancelar', args=[reserva.id]), {'next': 'javascript:alert(1)'})
        self.assertNotContains(r, 'javascript:alert')


class ReservarParaAlumnoTests(ReservasBase):
    def test_un_recupero_va_a_la_fecha_elegida(self):
        fecha = proximas_fechas(self.clase)[2]
        self.client.post(reverse('gravity:admin_reservar_para_usuario'), {
            'usuario': self.alumna.id, 'clase': self.clase.id, 'tipo_reserva': 'recupero', 'fecha': fecha.isoformat(),
        })
        reserva = Reserva.objects.get(usuario=self.alumna)
        self.assertEqual((reserva.fecha_unica, reserva.es_recupero, reserva.creado_por), (fecha, True, self.admin))

    def test_no_reserva_una_fecha_sin_lugar(self):
        clase = self.crear_clase(self.manana, hora=7, cupo=1)
        Reserva.objects.create(usuario=self.admin, clase=clase)
        r = self.client.post(reverse('gravity:admin_reservar_para_usuario'), {
            'usuario': self.alumna.id, 'clase': clase.id, 'tipo_reserva': 'temporal',
            'fecha': proximas_fechas(clase)[0].isoformat(),
        })
        self.assertContains(r, 'no tiene lugar')
        self.assertFalse(Reserva.objects.filter(usuario=self.alumna).exists())

    def test_muestra_el_plan_y_los_recuperos_del_alumno(self):
        self.dar_plan(1)
        Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        r = self.client.get(reverse('gravity:admin_reservar_para_usuario'), {'alumno': self.alumna.id})
        self.assertTrue(r.context['info']['plan_completo'])
        self.assertContains(r, 'usa 1 de 1 esta semana')
        self.assertContains(r, 'data-clases-plan="1"')
