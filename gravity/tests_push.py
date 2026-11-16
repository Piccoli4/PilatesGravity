"""Avisos push: al equipo (novedades de los alumnos) y a los alumnos (recordatorio de clase)."""
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from accounts.models import Testimonio

from .models import (
    AusenciaTemporal, Clase, NotificacionCancelacion, NotificacionCancelacionPlan, PlanPago,
    RecordatorioPush, Reserva, SolicitudCambioPlan, SuscripcionPush,
)
from .panel import (
    avisar_plan_cancelado_al_equipo, avisar_reserva_suelta_al_equipo, avisar_solicitud_plan, avisar_testimonio,
)
from .push import enviar_push_equipo, guardar_suscripcion
from .recordatorios import enviar_recordatorios, momento_recordatorio, recordatorios_pendientes
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


def mensaje_de(llamada):
    return json.loads(llamada.kwargs['data'])


def enviados_por_dispositivo(webpush):
    """{número de dispositivo: mensaje} de todo lo que salió."""
    return {c.kwargs['subscription_info']['endpoint'][-1]: mensaje_de(c) for c in webpush.call_args_list}


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
        self.fecha = timezone.localtime(timezone.now()).date() + timedelta(days=3)
        if self.fecha.weekday() == 6:
            self.fecha += timedelta(days=1)
        self.clase = Clase.objects.create(
            tipo='Reformer', dia=DIAS[self.fecha.weekday()], horario=time(18),
            direccion='sede_principal', cupo_maximo=9,
        )
        self.reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)

    def suscribir(self, usuario, n=1):
        return guardar_suscripcion(usuario, datos_navegador(n), 'Navegador de prueba')

    def otra_clase(self, hora):
        return Clase.objects.create(
            tipo='Cadillac', dia=self.clase.dia, horario=time(hora), direccion='sede_principal', cupo_maximo=4
        )


@CLAVES
class EnvioAlEquipoTests(PushBase):
    def test_llega_a_cada_dispositivo_del_equipo_y_no_a_los_alumnos(self):
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)
        self.suscribir(self.alumna, 3)

        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_push_equipo('eq_cancelaciones', 'Título', 'Cuerpo', '/admin-panel/')

        self.assertEqual(enviados, 2)
        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'1', '2'})

    def test_lo_que_resuelven_los_superadmins_no_le_llega_al_resto_del_equipo(self):
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)

        with mock.patch('pywebpush.webpush') as webpush:
            enviar_push_equipo('eq_solicitudes', 'Título')

        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'1'})

    def test_quien_dejo_de_ser_del_equipo_no_recibe_mas(self):
        self.suscribir(self.profesora)
        self.profesora.is_staff = False
        self.profesora.save()

        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_equipo('eq_cancelaciones', 'Título'), 0)
        webpush.assert_not_called()

    def test_se_borra_el_dispositivo_que_ya_no_existe(self):
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)
        respuesta_410 = mock.Mock(status_code=410)

        def responder(**kwargs):
            if kwargs['subscription_info']['endpoint'].endswith('-1'):
                raise WebPushException('Gone', response=respuesta_410)

        with mock.patch('pywebpush.webpush', side_effect=responder):
            enviados = enviar_push_equipo('eq_cancelaciones', 'Título')

        self.assertEqual(enviados, 1)
        self.assertEqual(list(SuscripcionPush.objects.values_list('usuario__username', flat=True)), ['diana'])

    def test_un_error_del_servicio_no_rompe_ni_borra_nada(self):
        self.suscribir(self.superadmin)
        with mock.patch('pywebpush.webpush', side_effect=Exception('sin conexión')):
            self.assertEqual(enviar_push_equipo('eq_cancelaciones', 'Título'), 0)
        self.assertEqual(SuscripcionPush.objects.count(), 1)

    @override_settings(VAPID_PRIVATE_KEY='')
    def test_sin_claves_no_se_manda_nada(self):
        self.suscribir(self.superadmin)
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_equipo('eq_cancelaciones', 'Título'), 0)
        webpush.assert_not_called()


@CLAVES
class CancelacionDelAlumnoTests(PushBase):
    def test_la_baja_avisa_por_push_y_no_manda_correo(self):
        self.suscribir(self.superadmin)

        with mock.patch('pywebpush.webpush') as webpush:
            notificar_admins_cancelacion(self.reserva, tipo='permanente')

        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'María Sosa dejó su horario fijo')
        self.assertIn('Reformer', mensaje['cuerpo'])
        self.assertIn('18:00', mensaje['cuerpo'])
        self.assertEqual(mensaje['url'], reverse('gravity:admin_usuario_detalle', args=[self.alumna.id]))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificacionCancelacion.objects.count(), 1)

    def test_la_ausencia_dice_que_dia_no_va(self):
        self.suscribir(self.superadmin)

        with mock.patch('pywebpush.webpush') as webpush:
            notificar_admins_cancelacion(self.reserva, tipo='temporal', fecha=self.fecha)

        self.assertEqual(mensaje_de(webpush.call_args)['titulo'], f'María Sosa avisó que no va el {self.fecha:%d/%m}')

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
class OtrosAvisosAlEquipoTests(PushBase):
    """Recuperos, planes, solicitudes y testimonios."""

    def setUp(self):
        super().setUp()
        self.plan = PlanPago.objects.create(
            nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000')
        )
        self.suscribir(self.superadmin, 1)
        self.suscribir(self.profesora, 2)

    def test_el_recupero_avisa_a_todo_el_equipo(self):
        recupero = Reserva.objects.create(
            usuario=self.alumna, clase=self.otra_clase(9), fecha_unica=self.fecha, es_recupero=True
        )

        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_suelta_al_equipo(recupero)

        enviados = enviados_por_dispositivo(webpush)
        self.assertEqual(set(enviados), {'1', '2'})
        self.assertEqual(enviados['1']['titulo'], f'María Sosa recupera el {self.fecha:%d/%m}')
        self.assertIn('09:00', enviados['1']['cuerpo'])

    def test_la_clase_unica_se_cuenta_distinto_que_el_recupero(self):
        unica = Reserva.objects.create(usuario=self.alumna, clase=self.otra_clase(9), fecha_unica=self.fecha)
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_suelta_al_equipo(unica)
        self.assertEqual(
            mensaje_de(webpush.call_args)['titulo'], f'María Sosa tomó una clase única el {self.fecha:%d/%m}'
        )

    def test_un_horario_fijo_nuevo_no_avisa(self):
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_suelta_al_equipo(self.reserva)
        webpush.assert_not_called()

    def test_el_plan_cancelado_avisa_a_todo_el_equipo(self):
        aviso = NotificacionCancelacionPlan.objects.create(usuario=self.alumna, plan=self.plan)
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_plan_cancelado_al_equipo(aviso)
        enviados = enviados_por_dispositivo(webpush)
        self.assertEqual(set(enviados), {'1', '2'})
        self.assertEqual(enviados['2']['titulo'], 'María Sosa canceló su plan')
        self.assertEqual(enviados['2']['cuerpo'], '2 clases semanales')

    def test_la_solicitud_de_plan_avisa_solo_a_los_superadmins(self):
        solicitud = SolicitudCambioPlan.objects.create(
            usuario=self.alumna, plan_actual=None, plan_solicitado=self.plan, estado='pendiente'
        )
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_solicitud_plan(solicitud)
        enviados = enviados_por_dispositivo(webpush)
        self.assertEqual(set(enviados), {'1'})
        self.assertEqual(enviados['1']['titulo'], 'María Sosa pidió un plan')
        self.assertIn('estado=pendiente', enviados['1']['url'])

    def test_el_cambio_de_plan_dice_de_cual_a_cual(self):
        otro = PlanPago.objects.create(nombre='3 clases semanales', clases_por_semana=3, precio_mensual=Decimal('80000'))
        solicitud = SolicitudCambioPlan.objects.create(
            usuario=self.alumna, plan_actual=self.plan, plan_solicitado=otro, estado='pendiente'
        )
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_solicitud_plan(solicitud)
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'María Sosa pidió cambiar de plan')
        self.assertIn('De "2 clases semanales" a "3 clases semanales"', mensaje['cuerpo'])

    def test_pedir_un_plan_desde_la_cuenta_dispara_el_aviso(self):
        self.client.force_login(self.alumna)
        with mock.patch('pywebpush.webpush') as webpush:
            self.client.post(reverse('gravity:seleccionar_plan'), {'plan_id': self.plan.id})
        self.assertEqual(SolicitudCambioPlan.objects.count(), 1)
        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'1'})

    def test_el_testimonio_avisa_solo_a_los_superadmins(self):
        self.client.force_login(self.alumna)
        with mock.patch('pywebpush.webpush') as webpush:
            self.client.post(
                reverse('accounts:guardar_testimonio'),
                {'texto': 'Me encanta venir a Gravity, fue la mejor decisión que tomé este año.'},
            )
        self.assertEqual(Testimonio.objects.count(), 1)
        enviados = enviados_por_dispositivo(webpush)
        self.assertEqual(set(enviados), {'1'})
        self.assertEqual(enviados['1']['titulo'], 'María Sosa dejó un testimonio')

    def test_un_testimonio_ya_aprobado_no_avisa(self):
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_testimonio(Testimonio(usuario=self.alumna, aprobado=True))
        webpush.assert_not_called()


@CLAVES
class RecordatorioDeClaseTests(PushBase):
    """La clase de la base es a las 18:00: el recordatorio toca desde las 14:00 de ese día."""

    def setUp(self):
        super().setUp()
        self.suscribir(self.alumna)

    def a_las(self, hora, minuto=0, fecha=None):
        return timezone.make_aware(datetime.combine(fecha or self.fecha, time(hora, minuto)))

    def test_se_manda_cuatro_horas_antes_y_no_antes(self):
        self.assertEqual(recordatorios_pendientes(self.a_las(13, 55)), [])
        self.assertEqual(recordatorios_pendientes(self.a_las(14, 5)), [(self.reserva, self.fecha)])

    def test_el_aviso_dice_que_clase_y_a_que_hora(self):
        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_recordatorios(self.a_las(14, 5))
        self.assertEqual(enviados, [(self.reserva, self.fecha)])
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], f'Hoy tenés {self.clase.get_nombre_display()} a las 18:00')
        self.assertIn('3 horas antes', mensaje['cuerpo'])
        self.assertEqual(mensaje['url'], reverse('accounts:mis_reservas'))
        self.assertEqual(webpush.call_args.kwargs['subscription_info']['endpoint'], datos_navegador(1)['endpoint'])

    def test_no_se_repite(self):
        with mock.patch('pywebpush.webpush') as webpush:
            enviar_recordatorios(self.a_las(14, 5))
            enviar_recordatorios(self.a_las(14, 20))
            enviar_recordatorios(self.a_las(17, 50))
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(RecordatorioPush.objects.count(), 1)

    def test_si_el_envio_falla_se_reintenta_en_la_proxima_corrida(self):
        with mock.patch('pywebpush.webpush', side_effect=Exception('sin conexión')):
            self.assertEqual(enviar_recordatorios(self.a_las(14, 5)), [])
        self.assertEqual(RecordatorioPush.objects.count(), 0)
        with mock.patch('pywebpush.webpush') as webpush:
            enviar_recordatorios(self.a_las(14, 20))
        self.assertEqual(webpush.call_count, 1)

    def test_no_se_manda_despues_de_que_empezo_la_clase(self):
        self.assertEqual(recordatorios_pendientes(self.a_las(18, 0)), [])

    def test_no_se_manda_a_quien_aviso_que_no_va(self):
        AusenciaTemporal.objects.create(reserva=self.reserva, fecha=self.fecha)
        self.assertEqual(recordatorios_pendientes(self.a_las(14, 5)), [])

    def test_avisar_que_falta_otro_dia_no_frena_el_recordatorio(self):
        AusenciaTemporal.objects.create(reserva=self.reserva, fecha=self.fecha + timedelta(days=7))
        self.assertEqual(recordatorios_pendientes(self.a_las(14, 5)), [(self.reserva, self.fecha)])

    def test_no_se_manda_si_la_reserva_esta_cancelada(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(activa=False)
        self.assertEqual(recordatorios_pendientes(self.a_las(14, 5)), [])

    def test_no_se_manda_a_quien_no_activo_los_avisos(self):
        SuscripcionPush.objects.all().delete()
        self.assertEqual(recordatorios_pendientes(self.a_las(14, 5)), [])

    def test_no_se_manda_si_reservo_despues_del_momento_del_recordatorio(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(fecha_reserva=self.a_las(15))
        self.assertEqual(recordatorios_pendientes(self.a_las(15, 10)), [])

    def test_con_dos_celulares_llega_a_los_dos_y_cuenta_como_uno(self):
        self.suscribir(self.alumna, 2)
        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_recordatorios(self.a_las(14, 5))
        self.assertEqual(len(enviados), 1)
        self.assertEqual(webpush.call_count, 2)

    def test_la_clase_de_la_maniana_se_recuerda_la_noche_anterior(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(clase=self.otra_clase(7))
        self.reserva.refresh_from_db()
        vispera = self.fecha - timedelta(days=1)

        self.assertEqual(momento_recordatorio(self.a_las(7)), self.a_las(20, 30, vispera))
        self.assertEqual(recordatorios_pendientes(self.a_las(20, 20, vispera)), [])
        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_recordatorios(self.a_las(20, 35, vispera))
        self.assertEqual(enviados, [(self.reserva, self.fecha)])
        self.assertEqual(
            mensaje_de(webpush.call_args)['titulo'],
            f'Mañana tenés {self.reserva.clase.get_nombre_display()} a las 07:00',
        )

    def test_el_recupero_tambien_se_recuerda(self):
        recupero = Reserva.objects.create(
            usuario=self.alumna, clase=self.otra_clase(16), fecha_unica=self.fecha, es_recupero=True
        )
        self.assertEqual(recordatorios_pendientes(self.a_las(12, 5)), [(recupero, self.fecha)])

    @override_settings(VAPID_PRIVATE_KEY='')
    def test_sin_claves_no_se_manda_nada(self):
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_recordatorios(self.a_las(14, 5)), [])
        webpush.assert_not_called()


@CLAVES
class RutasTests(PushBase):
    def post(self, ruta, datos=None):
        return self.client.post(reverse(f'gravity:{ruta}'), json.dumps(datos or {}), content_type='application/json')

    def test_el_equipo_activa_los_avisos_en_su_dispositivo(self):
        self.client.force_login(self.profesora)
        r = self.post('push_activar', datos_navegador())
        self.assertEqual(r.json(), {'ok': True})
        suscripcion = SuscripcionPush.objects.get()
        self.assertEqual(suscripcion.usuario, self.profesora)
        self.assertEqual(suscripcion.p256dh, 'clave-1')

    def test_un_alumno_activa_sus_recordatorios(self):
        self.client.force_login(self.alumna)
        r = self.post('push_activar', datos_navegador())
        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.alumna)

    def test_sin_sesion_no_se_puede_suscribir(self):
        r = self.post('push_activar', datos_navegador())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SuscripcionPush.objects.count(), 0)

    def test_activar_dos_veces_el_mismo_dispositivo_no_lo_duplica(self):
        self.client.force_login(self.profesora)
        self.post('push_activar', datos_navegador())
        self.client.force_login(self.superadmin)
        self.post('push_activar', datos_navegador())
        # El celular quedó a nombre de quien lo activó último
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.superadmin)

    def test_datos_incompletos_se_rechazan(self):
        self.client.force_login(self.profesora)
        casos = (
            {},
            {'endpoint': 'https://push.ejemplo.test/x'},
            {'endpoint': 'http://sin-https.test/x', 'keys': {'p256dh': 'a', 'auth': 'b'}},
        )
        for datos in casos:
            with self.subTest(datos=datos):
                self.assertEqual(self.post('push_activar', datos).status_code, 400)
        self.assertEqual(SuscripcionPush.objects.count(), 0)

    def test_desactivar_borra_solo_el_dispositivo_propio(self):
        self.suscribir(self.profesora, 1)
        self.suscribir(self.superadmin, 2)
        self.client.force_login(self.profesora)

        self.post('push_desactivar', {'endpoint': datos_navegador(2)['endpoint']})
        self.assertEqual(SuscripcionPush.objects.count(), 2)

        self.post('push_desactivar', {'endpoint': datos_navegador(1)['endpoint']})
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.superadmin)

    def test_la_prueba_llega_solo_a_quien_la_pide(self):
        self.suscribir(self.profesora, 1)
        self.suscribir(self.superadmin, 2)
        self.client.force_login(self.profesora)

        with mock.patch('pywebpush.webpush') as webpush:
            r = self.post('push_probar')

        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'1'})

    def test_la_prueba_del_alumno_habla_de_sus_clases(self):
        self.suscribir(self.alumna)
        self.client.force_login(self.alumna)
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(self.post('push_probar').json(), {'ok': True})
        self.assertIn('recordatorio', mensaje_de(webpush.call_args)['cuerpo'])

    def test_el_panel_ofrece_activar_los_avisos(self):
        self.client.force_login(self.profesora)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertContains(r, 'id="pn-push"')
        self.assertContains(r, 'data-clave="clave-publica-de-prueba"')
        self.assertContains(r, 'js/push_avisos.js')

    def test_mis_reservas_ofrece_activar_los_recordatorios(self):
        self.client.force_login(self.alumna)
        r = self.client.get(reverse('accounts:mis_reservas'))
        self.assertContains(r, 'class="me-push"')
        self.assertContains(r, 'data-clave="clave-publica-de-prueba"')
        self.assertContains(r, 'js/push_avisos.js')

    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_sin_claves_no_se_ofrecen_avisos(self):
        self.client.force_login(self.profesora)
        self.assertNotContains(self.client.get(reverse('gravity:admin_dashboard')), 'id="pn-push"')
        self.assertEqual(self.post('push_activar', datos_navegador()).status_code, 503)
        self.client.force_login(self.alumna)
        self.assertNotContains(self.client.get(reverse('accounts:mis_reservas')), 'class="me-push"')


class ServiceWorkerTests(TestCase):
    def test_el_service_worker_muestra_los_avisos(self):
        r = self.client.get('/sw.js')
        self.assertContains(r, "addEventListener('push'")
        self.assertContains(r, "addEventListener('notificationclick'")
