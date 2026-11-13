"""Avisos push al equipo: quién los recibe, qué dicen y las rutas del panel para activarlos."""
import json
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from .models import Clase, NotificacionCancelacion, Reserva, SuscripcionPush
from .push import enviar_push_equipo, guardar_suscripcion
from .views import notificar_admins_cancelacion

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

CLAVES = override_settings(
    VAPID_PUBLIC_KEY='clave-publica-de-prueba',
    VAPID_PRIVATE_KEY='clave-privada-de-prueba',
    PUSH_EN_SEGUNDO_PLANO=False,
)


def datos_navegador(n=1):
    """Lo que entrega el navegador al activar los avisos."""
    return {
        'endpoint': f'https://push.ejemplo.test/dispositivo-{n}',
        'keys': {'p256dh': f'clave-{n}', 'auth': f'secreto-{n}'},
    }


class PushBase(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            username='nico', email='nico@test.com', password='clave-123', first_name='Nico'
        )
        self.profesora = User.objects.create_user(
            username='diana', password='clave-123', first_name='Diana', is_staff=True
        )
        self.alumna = User.objects.create_user(
            username='maria', password='clave-123', first_name='María', last_name='Sosa'
        )
        # Una clase a 3 días (nunca domingo), así la alumna está a tiempo de cancelar
        dia = timezone.localtime(timezone.now()).date() + timedelta(days=3)
        if dia.weekday() == 6:
            dia += timedelta(days=1)
        self.clase = Clase.objects.create(
            tipo='Reformer', dia=DIAS[dia.weekday()], horario=time(18), direccion='sede_principal', cupo_maximo=9
        )
        self.reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)

    def suscribir(self, usuario, n=1):
        return guardar_suscripcion(usuario, datos_navegador(n), 'Navegador de prueba')


@CLAVES
class EnvioAlEquipoTests(PushBase):
    def test_llega_a_cada_dispositivo_del_equipo_y_no_a_los_alumnos(self):
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)
        self.suscribir(self.alumna, 3)

        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_push_equipo('Título', 'Cuerpo', '/admin-panel/')

        self.assertEqual(enviados, 2)
        destinos = {c.kwargs['subscription_info']['endpoint'] for c in webpush.call_args_list}
        self.assertEqual(destinos, {datos_navegador(1)['endpoint'], datos_navegador(2)['endpoint']})

    def test_quien_dejo_de_ser_del_equipo_no_recibe_mas(self):
        self.suscribir(self.profesora)
        self.profesora.is_staff = False
        self.profesora.save()

        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_equipo('Título'), 0)
        webpush.assert_not_called()

    def test_se_borra_el_dispositivo_que_ya_no_existe(self):
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)
        respuesta_410 = mock.Mock(status_code=410)

        def responder(**kwargs):
            if kwargs['subscription_info']['endpoint'].endswith('-1'):
                raise WebPushException('Gone', response=respuesta_410)

        with mock.patch('pywebpush.webpush', side_effect=responder):
            enviados = enviar_push_equipo('Título')

        self.assertEqual(enviados, 1)
        self.assertEqual(list(SuscripcionPush.objects.values_list('usuario__username', flat=True)), ['diana'])

    def test_un_error_del_servicio_no_rompe_ni_borra_nada(self):
        self.suscribir(self.superadmin)
        with mock.patch('pywebpush.webpush', side_effect=Exception('sin conexión')):
            self.assertEqual(enviar_push_equipo('Título'), 0)
        self.assertEqual(SuscripcionPush.objects.count(), 1)

    @override_settings(VAPID_PRIVATE_KEY='')
    def test_sin_claves_no_se_manda_nada(self):
        self.suscribir(self.superadmin)
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_equipo('Título'), 0)
        webpush.assert_not_called()


@CLAVES
class CancelacionDelAlumnoTests(PushBase):
    def mensaje(self, webpush):
        return json.loads(webpush.call_args.kwargs['data'])

    def test_la_baja_avisa_por_push_y_no_manda_correo(self):
        self.suscribir(self.superadmin)

        with mock.patch('pywebpush.webpush') as webpush:
            notificar_admins_cancelacion(self.reserva, tipo='permanente')

        mensaje = self.mensaje(webpush)
        self.assertEqual(mensaje['titulo'], 'María Sosa dejó su horario fijo')
        self.assertIn('Reformer', mensaje['cuerpo'])
        self.assertIn('18:00', mensaje['cuerpo'])
        self.assertEqual(mensaje['url'], reverse('gravity:admin_usuario_detalle', args=[self.alumna.id]))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificacionCancelacion.objects.count(), 1)

    def test_la_ausencia_dice_que_dia_no_va(self):
        self.suscribir(self.superadmin)
        fecha = timezone.localtime(timezone.now()).date() + timedelta(days=3)

        with mock.patch('pywebpush.webpush') as webpush:
            notificar_admins_cancelacion(self.reserva, tipo='temporal', fecha=fecha)

        self.assertEqual(self.mensaje(webpush)['titulo'], f'María Sosa avisó que no va el {fecha:%d/%m}')

    def test_cancelar_desde_la_cuenta_del_alumno_dispara_el_aviso(self):
        self.suscribir(self.profesora)
        self.client.force_login(self.alumna)

        with mock.patch('pywebpush.webpush') as webpush:
            r = self.client.post(
                reverse('gravity:cancelar_reserva', args=[self.reserva.numero_reserva]),
                {'confirmar_cancelacion': 'confirmar', 'tipo_cancelacion': 'permanente'},
            )

        self.assertEqual(r.status_code, 302)
        self.reserva.refresh_from_db()
        self.assertFalse(self.reserva.activa)
        self.assertEqual(webpush.call_count, 1)

    def test_si_el_push_falla_la_cancelacion_igual_queda_en_el_panel(self):
        self.suscribir(self.superadmin)
        with mock.patch('gravity.push._enviar', side_effect=Exception('roto')):
            notificar_admins_cancelacion(self.reserva, tipo='permanente')
        self.assertEqual(NotificacionCancelacion.objects.count(), 1)


@CLAVES
class RutasDelPanelTests(PushBase):
    def post(self, ruta, datos=None):
        return self.client.post(reverse(f'gravity:{ruta}'), json.dumps(datos or {}), content_type='application/json')

    def test_el_equipo_activa_los_avisos_en_su_dispositivo(self):
        self.client.force_login(self.profesora)
        r = self.post('admin_push_activar', datos_navegador())
        self.assertEqual(r.json(), {'ok': True})
        suscripcion = SuscripcionPush.objects.get()
        self.assertEqual(suscripcion.usuario, self.profesora)
        self.assertEqual(suscripcion.p256dh, 'clave-1')

    def test_activar_dos_veces_el_mismo_dispositivo_no_lo_duplica(self):
        self.client.force_login(self.profesora)
        self.post('admin_push_activar', datos_navegador())
        self.client.force_login(self.superadmin)
        self.post('admin_push_activar', datos_navegador())
        # El celular quedó a nombre de quien lo activó último
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.superadmin)

    def test_un_alumno_no_puede_suscribirse(self):
        self.client.force_login(self.alumna)
        r = self.post('admin_push_activar', datos_navegador())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SuscripcionPush.objects.count(), 0)

    def test_datos_incompletos_se_rechazan(self):
        self.client.force_login(self.profesora)
        for datos in ({}, {'endpoint': 'https://push.ejemplo.test/x'}, {'endpoint': 'http://sin-https.test/x', 'keys': {'p256dh': 'a', 'auth': 'b'}}):
            with self.subTest(datos=datos):
                self.assertEqual(self.post('admin_push_activar', datos).status_code, 400)
        self.assertEqual(SuscripcionPush.objects.count(), 0)

    def test_desactivar_borra_solo_el_dispositivo_propio(self):
        self.suscribir(self.profesora, 1)
        self.suscribir(self.superadmin, 2)
        self.client.force_login(self.profesora)

        self.post('admin_push_desactivar', {'endpoint': datos_navegador(2)['endpoint']})
        self.assertEqual(SuscripcionPush.objects.count(), 2)

        self.post('admin_push_desactivar', {'endpoint': datos_navegador(1)['endpoint']})
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.superadmin)

    def test_la_prueba_llega_solo_a_quien_la_pide(self):
        self.suscribir(self.profesora, 1)
        self.suscribir(self.superadmin, 2)
        self.client.force_login(self.profesora)

        with mock.patch('pywebpush.webpush') as webpush:
            r = self.post('admin_push_probar')

        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(webpush.call_args.kwargs['subscription_info']['endpoint'], datos_navegador(1)['endpoint'])

    def test_el_panel_ofrece_activar_los_avisos(self):
        self.client.force_login(self.profesora)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertContains(r, 'id="pn-push"')
        self.assertContains(r, 'data-clave="clave-publica-de-prueba"')

    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_sin_claves_el_panel_no_ofrece_avisos(self):
        self.client.force_login(self.profesora)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertNotContains(r, 'id="pn-push"')
        self.assertEqual(self.post('admin_push_activar', datos_navegador()).status_code, 503)


class ServiceWorkerTests(TestCase):
    def test_el_service_worker_muestra_los_avisos(self):
        r = self.client.get('/sw.js')
        self.assertContains(r, "addEventListener('push'")
        self.assertContains(r, "addEventListener('notificationclick'")
