"""Etapa 5 del panel: lista y ficha de alumnos, alta con invitación, datos, notas, baja y solicitudes."""
import re
from datetime import date, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.invitacion import InvitacionTokenGenerator
from accounts.models import UserProfile

from .models import (
    CancelacionAdmin, Clase, EstadoPagoCliente, NotificacionCancelacion, PlanPago, PlanUsuario, Reserva,
    SolicitudCambioPlan,
)


class AlumnosBase(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='nico', email='nico@test.com', password='clave-123', first_name='Nico')
        self.equipo = User.objects.create_user(username='diana', password='clave-123', is_staff=True, first_name='Diana')
        self.client.force_login(self.equipo)

    def alumno(self, nombre, **extra):
        return User.objects.create_user(username=nombre.lower(), password='clave-123', first_name=nombre,
                                        last_name='Test', email=f'{nombre.lower()}@test.com', **extra)


class ListaAlumnosTests(AlumnosBase):
    def test_por_defecto_oculta_eliminados_y_desactivados(self):
        self.alumno('Ana')
        self.alumno('Bea', is_active=False)
        User.objects.create_user(username='eliminado-99', first_name='Alumno eliminado (Caro)', is_active=False)

        r = self.client.get(reverse('gravity:admin_usuarios_lista'))
        self.assertEqual([f['usuario'].first_name for f in r.context['filas']], ['Ana'])
        cantidades = {c['clave']: c['cantidad'] for c in r.context['chips']}
        self.assertEqual((cantidades['desactivados'], cantidades['eliminados']), (1, 1))

        r = self.client.get(reverse('gravity:admin_usuarios_lista'), {'filtro': 'eliminados'})
        self.assertEqual(len(r.context['filas']), 1)

    def test_busca_por_telefono_y_filtra_deudores(self):
        ana = self.alumno('Ana')
        perfil = UserProfile.objects.get(user=ana)
        perfil.telefono = '3425114448'
        perfil.save()
        self.alumno('Bea')
        EstadoPagoCliente.objects.create(usuario=ana, saldo_actual=Decimal('-5000'), activo=True)

        r = self.client.get(reverse('gravity:admin_usuarios_lista'), {'busqueda': '342 511'})
        self.assertEqual([f['usuario'] for f in r.context['filas']], [ana])
        r = self.client.get(reverse('gravity:admin_usuarios_lista'), {'filtro': 'con_deuda'})
        self.assertEqual([f['usuario'] for f in r.context['filas']], [ana])
        self.assertContains(r, 'Debe $5.000')


class AltaConInvitacionTests(AlumnosBase):
    def crear(self, **datos):
        base = {'nombre': 'maría josé', 'apellido': 'pérez', 'telefono': '342 511-4448', 'email': 'MAJO@test.com'}
        base.update(datos)
        return self.client.post(reverse('gravity:admin_agregar_usuario'), base)

    def test_con_email_manda_la_invitacion_y_no_tiene_contrasena(self):
        r = self.crear(notas='Viene por la espalda')
        alumno = User.objects.get(email='majo@test.com')
        self.assertRedirects(r, reverse('gravity:admin_usuario_detalle', args=[alumno.id]), fetch_redirect_response=False)
        self.assertEqual((alumno.username, alumno.first_name, alumno.last_name), ('mariajoseperez', 'María José', 'Pérez'))
        self.assertFalse(alumno.has_usable_password())
        self.assertEqual(alumno.profile.telefono, '3425114448')
        self.assertIn('Viene por la espalda', alumno.profile.notas_admin)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/invitacion/', mail.outbox[0].body)
        r = self.client.get(reverse('gravity:admin_usuario_detalle', args=[alumno.id]))
        self.assertContains(r, 'Todavía no creó su contraseña')

    def test_no_repite_email(self):
        self.alumno('Ana')
        r = self.crear(email='ANA@test.com')
        self.assertContains(r, 'Ese email ya lo usa Ana Test')

    def test_sin_email_muestra_la_contrasena_una_sola_vez(self):
        self.crear(email='')
        alumno = User.objects.get(username='mariajoseperez')
        self.assertTrue(alumno.has_usable_password())
        url = reverse('gravity:admin_usuario_detalle', args=[alumno.id])
        r = self.client.get(url)
        clave = r.context['clave_inicial']
        self.assertTrue(alumno.check_password(clave))
        self.assertContains(r, clave)
        self.assertNotContains(self.client.get(url), clave)
        self.assertEqual(mail.outbox, [])


class InvitacionTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='lia', email='lia@test.com', first_name='Lía')
        self.token = InvitacionTokenGenerator().make_token(self.alumna)
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        self.url = reverse('accounts:invitacion', args=[urlsafe_base64_encode(force_bytes(self.alumna.pk)), self.token])

    def test_crea_la_contrasena_entra_y_el_enlace_deja_de_servir(self):
        r = self.client.post(self.url, {'new_password1': 'reformer-2026', 'new_password2': 'reformer-2026'})
        self.assertRedirects(r, reverse('accounts:profile_complete'), fetch_redirect_response=False)
        self.alumna.refresh_from_db()
        self.assertTrue(self.alumna.check_password('reformer-2026'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.alumna.pk)
        self.client.logout()
        r = self.client.get(self.url)
        self.assertFalse(r.context['validlink'])

    def test_vence_a_los_7_dias(self):
        with mock.patch.object(InvitacionTokenGenerator, '_now', return_value=timezone.now().replace(tzinfo=None) + timedelta(days=8)):
            r = self.client.get(self.url)
        self.assertFalse(r.context['validlink'])
        self.assertContains(r, 'Este enlace ya no sirve')

    def test_olvide_mi_contrasena_tambien_sirve_para_una_cuenta_invitada(self):
        self.client.post(reverse('accounts:password_reset'), {'email': 'lia@test.com'})
        self.assertEqual(len(mail.outbox), 1)


class FichaYDatosTests(AlumnosBase):
    def test_editar_datos_y_primera_clase(self):
        ana = self.alumno('Ana')
        url = reverse('gravity:admin_usuario_editar', args=[ana.id])
        datos = {'first_name': 'Ana', 'last_name': 'Test', 'telefono': '(342) 511 4448', 'email': 'ana@test.com',
                 'tiene_lesiones': 'si', 'descripcion_lesiones': '', 'fecha_primera_clase': '2025-03-10',
                 'sede_primera_clase': 'sede_2'}
        r = self.client.post(url, datos)
        self.assertContains(r, 'Contá brevemente qué lesión')
        datos['descripcion_lesiones'] = 'Rodilla derecha'
        self.client.post(url, datos)
        perfil = UserProfile.objects.get(user=ana)
        self.assertEqual((perfil.telefono, perfil.fecha_primera_clase, perfil.sede_primera_clase, perfil.tiene_lesiones),
                         ('3425114448', date(2025, 3, 10), 'sede_2', True))

    def test_las_notas_llevan_la_hora_de_argentina(self):
        ana = self.alumno('Ana')
        self.client.post(reverse('gravity:admin_usuario_add_note', args=[ana.id]), {'nota': 'Pagó en efectivo'})
        r = self.client.get(reverse('gravity:admin_usuario_detalle', args=[ana.id]))
        nota = r.context['notas'][0]
        self.assertEqual((nota['texto'], nota['quien']), ('Pagó en efectivo', 'Diana'))
        ahora = timezone.localtime(timezone.now())
        self.assertTrue(nota['cuando'].startswith(ahora.strftime('%d/%m/%Y %H')))

    def test_la_ficha_carga(self):
        ana = self.alumno('Ana')
        clase = Clase.objects.create(tipo='Reformer', dia='Lunes', horario=time(18), direccion='sede_2', cupo_maximo=5)
        Reserva.objects.create(usuario=ana, clase=clase)
        r = self.client.get(reverse('gravity:admin_usuario_detalle', args=[ana.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['horarios']), 1)
        self.assertNotContains(r, 'Desactivar la cuenta')  # es del superadmin


class DesactivarTests(AlumnosBase):
    def test_solo_el_superadmin_y_cancela_reservas_y_plan(self):
        ana = self.alumno('Ana')
        clase = Clase.objects.create(tipo='Reformer', dia='Lunes', horario=time(18), direccion='sede_2', cupo_maximo=5)
        reserva = Reserva.objects.create(usuario=ana, clase=clase)
        plan = PlanPago.objects.create(nombre='1 clase', clases_por_semana=1, precio_mensual=Decimal('40000'))
        hoy = timezone.localdate()
        PlanUsuario.objects.create(usuario=ana, plan=plan, fecha_inicio=hoy, fecha_fin=hoy + timedelta(days=30))
        url = reverse('gravity:admin_usuario_toggle_status', args=[ana.id])

        self.client.post(url)
        ana.refresh_from_db()
        self.assertTrue(ana.is_active)  # el equipo no puede

        self.client.force_login(self.superadmin)
        self.assertContains(self.client.get(url), '1 horario fijo')
        self.client.post(url)
        ana.refresh_from_db()
        reserva.refresh_from_db()
        self.assertFalse(ana.is_active)
        self.assertFalse(reserva.activa)
        self.assertTrue(CancelacionAdmin.objects.filter(reserva=reserva, motivo='Baja del estudio').exists())
        self.assertFalse(PlanUsuario.objects.filter(usuario=ana, activo=True).exists())

        self.client.post(url)
        ana.refresh_from_db()
        self.assertTrue(ana.is_active)


class SolicitudesTests(AlumnosBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.superadmin)
        self.ana = self.alumno('Ana')
        self.plan2 = PlanPago.objects.create(nombre='2 clases', clases_por_semana=2, precio_mensual=Decimal('60000'))
        self.plan1 = PlanPago.objects.create(nombre='1 clase', clases_por_semana=1, precio_mensual=Decimal('40000'))

    def test_aprobar_registra_la_baja_de_los_horarios_liberados(self):
        clase = Clase.objects.create(tipo='Reformer', dia='Lunes', horario=time(18), direccion='sede_2', cupo_maximo=5)
        reserva = Reserva.objects.create(usuario=self.ana, clase=clase)
        solicitud = SolicitudCambioPlan.objects.create(usuario=self.ana, plan_actual=self.plan2, plan_solicitado=self.plan1)
        solicitud.reservas_a_cancelar.add(reserva)

        self.client.post(reverse('gravity:admin_solicitud_plan_aprobar', args=[solicitud.id]))

        reserva.refresh_from_db()
        self.assertFalse(reserva.activa)
        self.assertTrue(NotificacionCancelacion.objects.filter(reserva=reserva, tipo='permanente').exists())

    def test_rechazar_avisa_por_email_con_el_motivo(self):
        solicitud = SolicitudCambioPlan.objects.create(usuario=self.ana, plan_solicitado=self.plan2)
        self.client.post(reverse('gravity:admin_solicitud_plan_rechazar', args=[solicitud.id]),
                         {'motivo_rechazo': 'No hay cupo en la tarde'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('No hay cupo en la tarde', mail.outbox[0].body)

    def test_la_lista_abre_en_pendientes(self):
        SolicitudCambioPlan.objects.create(usuario=self.ana, plan_solicitado=self.plan2)
        resuelta = SolicitudCambioPlan.objects.create(usuario=self.alumno('Bea'), plan_solicitado=self.plan2, estado='rechazada')
        r = self.client.get(reverse('gravity:admin_solicitudes_plan_lista'))
        self.assertEqual(r.context['estado_filtro'], 'pendiente')
        self.assertNotIn(resuelta, list(r.context['solicitudes']))
