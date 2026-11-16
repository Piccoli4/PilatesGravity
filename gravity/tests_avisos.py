"""
Avisos push a los alumnos (cambios del estudio, plan, pago, recupero por vencer,
cumpleaños, lugar liberado), la lista de espera y la página para elegir qué recibir.
"""
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .avisos_alumno import (
    anotar_en_espera, avisar_lugar_liberado, avisar_pago_registrado, avisar_reserva_cancelada,
    avisar_reserva_modificada, avisar_solicitud_resuelta,
)
from .models import (
    AusenciaTemporal, AvisoPushEnviado, Clase, ListaEspera, PlanPago, PreferenciasAvisos, Reserva,
    SolicitudCambioPlan,
)
from .push import avisos_apagados, enviar_push_equipo, enviar_push_usuario, guardar_avisos
from .recordatorios import enviar_avisos_recupero, enviar_recordatorios, enviar_saludos_cumpleanios
from .tests_push import CLAVES, PushBase, enviados_por_dispositivo, mensaje_de
from .views import notificar_admins_cancelacion


@CLAVES
class PreferenciasTests(PushBase):
    def setUp(self):
        super().setUp()
        self.suscribir(self.alumna, 1)
        self.suscribir(self.profesora, 2)
        self.suscribir(self.superadmin, 3)

    def test_por_defecto_llegan_todos(self):
        self.assertEqual(avisos_apagados(self.alumna), set())
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_usuario(self.alumna, 'pago', 'Título'), 1)
        self.assertEqual(webpush.call_count, 1)

    def test_el_aviso_apagado_no_llega_y_los_demas_si(self):
        guardar_avisos(self.alumna, ['recordatorio', 'cambios'])
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_push_usuario(self.alumna, 'pago', 'Título'), 0)
            self.assertEqual(enviar_push_usuario(self.alumna, 'cambios', 'Título'), 1)
        self.assertEqual(webpush.call_count, 1)

    def test_alguien_del_equipo_puede_apagar_un_aviso_del_panel(self):
        guardar_avisos(self.profesora, ['eq_recuperos', 'eq_planes'])
        with mock.patch('pywebpush.webpush') as webpush:
            enviar_push_equipo('eq_cancelaciones', 'Título')
        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'3'})
        with mock.patch('pywebpush.webpush') as webpush:
            enviar_push_equipo('eq_recuperos', 'Título')
        self.assertEqual(set(enviados_por_dispositivo(webpush)), {'2', '3'})

    def test_un_alumno_no_puede_guardar_avisos_del_panel(self):
        apagados = guardar_avisos(self.alumna, ['recordatorio', 'eq_cancelaciones'])
        self.assertNotIn('eq_cancelaciones', apagados)
        self.assertNotIn('recordatorio', apagados)
        self.assertIn('pago', apagados)

    def test_el_recordatorio_de_clase_respeta_la_preferencia(self):
        guardar_avisos(self.alumna, ['cambios'])
        ahora = timezone.make_aware(datetime.combine(self.fecha, time(14, 5)))
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_recordatorios(ahora), [])
        webpush.assert_not_called()


@CLAVES
class PaginaAvisosTests(PushBase):
    def test_el_alumno_ve_solo_sus_avisos(self):
        self.client.force_login(self.alumna)
        r = self.client.get(reverse('gravity:avisos'))
        self.assertContains(r, 'Recordatorio de clase')
        self.assertContains(r, 'Se liberó un lugar')
        self.assertNotContains(r, 'Cancelaciones y ausencias')
        self.assertContains(r, 'data-push')

    def test_la_profesora_ve_los_del_panel_pero_no_los_de_superadmin(self):
        self.client.force_login(self.profesora)
        r = self.client.get(reverse('gravity:avisos'))
        self.assertContains(r, 'Cancelaciones y ausencias')
        self.assertNotContains(r, 'Solicitudes de plan')
        self.client.force_login(self.superadmin)
        self.assertContains(self.client.get(reverse('gravity:avisos')), 'Solicitudes de plan')

    def test_guardar_apaga_lo_que_quedo_sin_marcar(self):
        self.client.force_login(self.alumna)
        r = self.client.post(reverse('gravity:avisos'), {'avisos': ['recordatorio', 'cambios', 'lugar']})
        self.assertRedirects(r, reverse('gravity:avisos'))
        self.assertEqual(avisos_apagados(self.alumna), {'recupero', 'plan', 'pago', 'cumple'})
        r = self.client.get(reverse('gravity:avisos'))
        self.assertContains(r, 'value="recordatorio" checked')
        self.assertNotContains(r, 'value="pago" checked')

    def test_volver_a_marcar_lo_enciende(self):
        self.client.force_login(self.alumna)
        self.client.post(reverse('gravity:avisos'), {'avisos': []})
        todos = ['recordatorio', 'cambios', 'lugar', 'recupero', 'plan', 'pago', 'cumple']
        self.client.post(reverse('gravity:avisos'), {'avisos': todos})
        self.assertEqual(avisos_apagados(self.alumna), set())
        self.assertEqual(PreferenciasAvisos.objects.count(), 1)

    def test_pide_sesion(self):
        self.assertEqual(self.client.get(reverse('gravity:avisos')).status_code, 302)

    def test_se_llega_desde_mis_reservas_mi_espacio_y_el_panel(self):
        self.client.force_login(self.alumna)
        self.assertContains(self.client.get(reverse('accounts:mis_reservas')), reverse('gravity:avisos'))
        self.assertContains(self.client.get(reverse('accounts:profile')), reverse('gravity:avisos'))
        self.client.force_login(self.profesora)
        self.assertContains(self.client.get(reverse('gravity:admin_dashboard')), reverse('gravity:avisos'))


@CLAVES
class AvisosDelEstudioTests(PushBase):
    """Lo que hace el estudio y le llega al alumno."""

    def setUp(self):
        super().setUp()
        self.suscribir(self.alumna)
        self.plan = PlanPago.objects.create(
            nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000')
        )

    def test_cancelar_un_horario_fijo(self):
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_cancelada(self.reserva)
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], f'Cancelamos tu horario de los {self.clase.dia.lower()} a las 18:00')
        self.assertEqual(mensaje['url'], reverse('accounts:mis_reservas'))

    def test_cancelar_un_recupero_dice_la_fecha(self):
        recupero = Reserva.objects.create(
            usuario=self.alumna, clase=self.otra_clase(9), fecha_unica=self.fecha, es_recupero=True
        )
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_cancelada(recupero)
        self.assertEqual(mensaje_de(webpush.call_args)['titulo'], f'Cancelamos tu recupero del {self.fecha:%d/%m}')

    def test_cambiar_una_clase_dice_la_nueva(self):
        nueva = self.otra_clase(10)
        Reserva.objects.filter(pk=self.reserva.pk).update(clase=nueva)
        self.reserva.refresh_from_db()
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_modificada(self.reserva, self.clase)
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'Cambiamos una de tus clases')
        self.assertIn('10:00', mensaje['cuerpo'])

    def test_no_llega_si_apago_los_cambios(self):
        guardar_avisos(self.alumna, ['recordatorio'])
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_reserva_cancelada(self.reserva)
        webpush.assert_not_called()

    def test_solicitud_aprobada_y_rechazada(self):
        solicitud = SolicitudCambioPlan.objects.create(
            usuario=self.alumna, plan_actual=None, plan_solicitado=self.plan, estado='aprobada'
        )
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_solicitud_resuelta(solicitud)
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'Aprobamos tu pedido de plan')
        self.assertIn('2 clases semanales', mensaje['cuerpo'])

        solicitud.estado = 'rechazada'
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_solicitud_resuelta(solicitud)
        self.assertEqual(mensaje_de(webpush.call_args)['titulo'], 'No pudimos aprobar tu pedido de plan')

    def test_rechazar_desde_el_panel_le_avisa_al_alumno(self):
        solicitud = SolicitudCambioPlan.objects.create(
            usuario=self.alumna, plan_actual=None, plan_solicitado=self.plan, estado='pendiente'
        )
        self.client.force_login(self.superadmin)
        with mock.patch('pywebpush.webpush') as webpush:
            self.client.post(reverse('gravity:admin_solicitud_plan_rechazar', args=[solicitud.id]))
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'rechazada')
        self.assertEqual(mensaje_de(webpush.call_args)['titulo'], 'No pudimos aprobar tu pedido de plan')

    def test_pago_registrado(self):
        pago = SimpleNamespace(cliente=self.alumna, monto=Decimal('61000'), pk=7)
        with mock.patch('pywebpush.webpush') as webpush:
            avisar_pago_registrado(pago)
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'Registramos tu pago')
        self.assertIn('$61.000', mensaje['cuerpo'])


@CLAVES
class RecuperoPorVencerTests(PushBase):
    def setUp(self):
        super().setUp()
        self.suscribir(self.alumna)
        self.hoy = timezone.localdate()
        # Faltó hace 5 días: el plazo (6 días) vence mañana
        AusenciaTemporal.objects.bulk_create([AusenciaTemporal(reserva=self.reserva, fecha=self.hoy - timedelta(days=5))])
        self.ausencia = AusenciaTemporal.objects.get()

    def a_las(self, hora):
        return timezone.make_aware(datetime.combine(self.hoy, time(hora)))

    def test_avisa_cuando_falta_poco(self):
        with mock.patch('pywebpush.webpush') as webpush:
            enviados = enviar_avisos_recupero(self.a_las(11))
        self.assertEqual(enviados, [(self.alumna, self.ausencia)])
        mensaje = mensaje_de(webpush.call_args)
        self.assertEqual(mensaje['titulo'], 'Te queda 1 día para recuperar tu clase')
        self.assertEqual(mensaje['url'], reverse('gravity:reservar_recupero'))

    def test_una_sola_vez(self):
        with mock.patch('pywebpush.webpush') as webpush:
            enviar_avisos_recupero(self.a_las(11))
            enviar_avisos_recupero(self.a_las(12))
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(AvisoPushEnviado.objects.get().clave, f'recupero-{self.ausencia.pk}')

    def test_no_sale_antes_de_las_diez(self):
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_avisos_recupero(self.a_las(8)), [])
        webpush.assert_not_called()

    def test_no_avisa_si_todavia_falta(self):
        AusenciaTemporal.objects.filter(pk=self.ausencia.pk).update(fecha=self.hoy - timedelta(days=1))
        self.assertEqual(enviar_avisos_recupero(self.a_las(11)), [])

    def test_no_avisa_si_ya_reservo_el_recupero(self):
        Reserva.objects.create(
            usuario=self.alumna, clase=self.otra_clase(9) if self.clase.tipo == 'Cadillac' else Clase.objects.create(
                tipo='Reformer', dia=self.clase.dia, horario=time(9), direccion='sede_principal', cupo_maximo=4),
            fecha_unica=self.hoy + timedelta(days=1), es_recupero=True,
        )
        self.assertEqual(enviar_avisos_recupero(self.a_las(11)), [])

    def test_respeta_la_preferencia(self):
        guardar_avisos(self.alumna, ['recordatorio'])
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_avisos_recupero(self.a_las(11)), [])
        webpush.assert_not_called()


@CLAVES
class CumpleaniosTests(PushBase):
    def setUp(self):
        super().setUp()
        self.suscribir(self.alumna)
        self.hoy = timezone.localdate()
        UserProfile.objects.get_or_create(user=self.alumna)
        UserProfile.objects.filter(user=self.alumna).update(fecha_nacimiento=self.hoy.replace(year=1990))

    def a_las(self, hora):
        return timezone.make_aware(datetime.combine(self.hoy, time(hora)))

    def test_saluda_el_dia_del_cumpleanios_una_sola_vez(self):
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(enviar_saludos_cumpleanios(self.a_las(11)), [self.alumna])
            self.assertEqual(enviar_saludos_cumpleanios(self.a_las(15)), [])
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(mensaje_de(webpush.call_args)['titulo'], '¡Feliz cumpleaños, María!')

    def test_no_saluda_de_madrugada_ni_otro_dia(self):
        self.assertEqual(enviar_saludos_cumpleanios(self.a_las(3)), [])
        otro_dia = self.a_las(11) + timedelta(days=1)
        self.assertEqual(enviar_saludos_cumpleanios(otro_dia), [])


@CLAVES
class ListaDeEsperaTests(PushBase):
    """Una clase de un solo lugar, ocupado por María; Lucía espera lugar."""

    def setUp(self):
        super().setUp()
        Clase.objects.filter(pk=self.clase.pk).update(cupo_maximo=1)
        self.clase.refresh_from_db()
        self.lucia = User.objects.create_user(username='lucia', password='clave-123', first_name='Lucía')
        self.suscribir(self.lucia, 5)
        ListaEspera.objects.create(usuario=self.lucia, clase=self.clase)

    def test_anotarse_y_no_duplicar(self):
        otra = User.objects.create_user(username='ines', password='clave-123')
        self.assertTrue(anotar_en_espera(otra, self.clase)[0])
        self.assertTrue(anotar_en_espera(otra, self.clase)[0])
        self.assertEqual(ListaEspera.objects.filter(usuario=otra).count(), 1)

    def test_quien_ya_tiene_el_horario_no_se_anota(self):
        ok, mensaje = anotar_en_espera(self.alumna, self.clase)
        self.assertFalse(ok)
        self.assertFalse(ListaEspera.objects.filter(usuario=self.alumna).exists())

    def test_si_alguien_avisa_que_no_va_se_avisa_el_lugar_de_ese_dia(self):
        AusenciaTemporal.objects.create(reserva=self.reserva, fecha=self.fecha)
        with mock.patch('pywebpush.webpush') as webpush:
            notificar_admins_cancelacion(self.reserva, tipo='temporal', fecha=self.fecha)
        enviados = enviados_por_dispositivo(webpush)
        self.assertEqual(set(enviados), {'5'})
        self.assertEqual(enviados['5']['titulo'], f'Se liberó un lugar el {self.clase.dia.lower()} {self.fecha:%d/%m}')
        self.assertIn('es_temporal=1', enviados['5']['url'])
        # Sigue en la lista: el lugar era solo por ese día
        self.assertTrue(ListaEspera.objects.filter(usuario=self.lucia).exists())

    def test_si_alguien_deja_el_horario_se_avisa_el_lugar_fijo(self):
        self.client.force_login(self.alumna)
        with mock.patch('pywebpush.webpush') as webpush:
            self.client.post(
                reverse('gravity:cancelar_reserva', args=[self.reserva.numero_reserva]),
                {'confirmar_cancelacion': 'confirmar', 'tipo_cancelacion': 'permanente'},
            )
        mensaje = enviados_por_dispositivo(webpush)['5']
        self.assertEqual(mensaje['titulo'], 'Se liberó un lugar fijo')
        self.assertNotIn('es_temporal', mensaje['url'])
        self.assertIn(reverse('gravity:reservar_clase'), mensaje['url'])

    def test_no_avisa_si_la_clase_sigue_completa(self):
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(avisar_lugar_liberado(self.clase), 0)
            self.assertEqual(avisar_lugar_liberado(self.clase, fecha=self.fecha), 0)
        webpush.assert_not_called()

    def test_no_avisa_por_una_fecha_que_ya_paso(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(activa=False)
        ayer = timezone.localdate() - timedelta(days=1)
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(avisar_lugar_liberado(self.clase, fecha=ayer), 0)
        webpush.assert_not_called()

    def test_respeta_la_preferencia(self):
        guardar_avisos(self.lucia, ['recordatorio'])
        Reserva.objects.filter(pk=self.reserva.pk).update(activa=False)
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(avisar_lugar_liberado(self.clase), 0)
        webpush.assert_not_called()

    def test_al_conseguir_el_horario_sale_de_la_lista(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(activa=False)
        Reserva.objects.create(usuario=self.lucia, clase=self.clase)
        # La clase volvió a llenarse con Lucía; se libera otro lugar más adelante
        Clase.objects.filter(pk=self.clase.pk).update(cupo_maximo=2)
        self.clase.refresh_from_db()
        with mock.patch('pywebpush.webpush') as webpush:
            self.assertEqual(avisar_lugar_liberado(self.clase), 0)
        webpush.assert_not_called()
        self.assertFalse(ListaEspera.objects.filter(usuario=self.lucia).exists())


@CLAVES
class ListaDeEsperaVistasTests(PushBase):
    def setUp(self):
        super().setUp()
        Clase.objects.filter(pk=self.clase.pk).update(cupo_maximo=1)
        self.lucia = User.objects.create_user(username='lucia', password='clave-123', first_name='Lucía')
        self.client.force_login(self.lucia)

    def anotar(self):
        return self.client.post(reverse('gravity:lista_espera_anotar', args=[self.clase.id]))

    def test_sin_avisos_activados_lo_lleva_a_activarlos(self):
        r = self.anotar()
        self.assertRedirects(r, reverse('gravity:avisos'))
        self.assertTrue(ListaEspera.objects.filter(usuario=self.lucia, clase=self.clase).exists())

    def test_con_avisos_vuelve_a_la_grilla(self):
        self.suscribir(self.lucia, 5)
        self.assertRedirects(self.anotar(), reverse('gravity:reservar_clase'), fetch_redirect_response=False)

    def test_con_el_aviso_apagado_se_lo_avisa(self):
        self.suscribir(self.lucia, 5)
        guardar_avisos(self.lucia, ['recordatorio'])
        self.assertRedirects(self.anotar(), reverse('gravity:avisos'))

    def test_salir_de_la_lista(self):
        self.anotar()
        r = self.client.post(
            reverse('gravity:lista_espera_salir', args=[self.clase.id]), {'next': reverse('gravity:avisos')}
        )
        self.assertRedirects(r, reverse('gravity:avisos'))
        self.assertFalse(ListaEspera.objects.exists())

    def test_salir_no_redirige_a_otro_sitio(self):
        self.anotar()
        r = self.client.post(
            reverse('gravity:lista_espera_salir', args=[self.clase.id]), {'next': 'https://otro-sitio.test/'}
        )
        self.assertRedirects(r, reverse('gravity:reservar_clase'), fetch_redirect_response=False)

    def test_la_pagina_de_avisos_muestra_mis_listas(self):
        self.anotar()
        r = self.client.get(reverse('gravity:avisos'))
        self.assertContains(r, reverse('gravity:lista_espera_salir', args=[self.clase.id]))
        self.assertContains(r, '18:00')

    def test_la_grilla_marca_la_clase_completa_y_la_lista(self):
        self.suscribir(self.lucia, 5)
        r = self.client.get(reverse('gravity:reservar_clase'))
        self.assertContains(r, 'id="rcEspera"')
        self.assertContains(r, f'data-clase-id="{self.clase.id}"')
        self.assertContains(r, 'Completa')
        self.anotar()
        self.assertContains(self.client.get(reverse('gravity:reservar_clase')), 'En lista de espera')
