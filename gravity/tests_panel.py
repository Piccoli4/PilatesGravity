"""Base del panel de administración: menú por rol, bandeja de actividad y permisos del equipo."""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Testimonio

from .models import (
    Clase,
    EstadoPagoCliente,
    NotificacionCancelacion,
    PlanPago,
    PlanUsuario,
    RegistroPago,
    Reserva,
    SolicitudCambioPlan,
)
from .panel import seccion_actual


class PanelBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localtime(timezone.now()).date()
        self.superadmin = User.objects.create_superuser(
            username='nico', email='nico@test.com', password='clave-123', first_name='Nico'
        )
        self.equipo = User.objects.create_user(
            username='diana', password='clave-123', first_name='Diana', last_name='Paz', is_staff=True
        )
        self.alumna = User.objects.create_user(
            username='avril', password='clave-123', first_name='Avril', last_name='Sosa'
        )
        self.plan = PlanPago.objects.create(
            nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000')
        )
        self.clase = Clase.objects.create(
            tipo='Reformer', dia='Miércoles', horario=time(10), direccion='sede_principal', cupo_maximo=9
        )

    def entrar(self, usuario):
        self.client.force_login(usuario)


class SeccionActualTests(TestCase):
    def test_cada_ruta_marca_su_seccion(self):
        casos = {
            'admin_dashboard': 'hoy',
            'admin_clase_detalle': 'clases',
            'admin_clases_lista': 'clases',
            'admin_reservar_para_usuario_cliente': 'reservas',
            'admin_reserva_cancelar': 'reservas',
            'admin_usuario_detalle': 'alumnos',
            'admin_agregar_usuario': 'nuevo_alumno',
            'admin_pagos_editar_estado_cliente': 'pagos',
            'admin_pagos_por_admin': 'pagos_admin',
            'admin_asistencia_ausencias': 'asistencia',
            'admin_profesora_detalle': 'equipo',
            'admin_equipo_sumar': 'equipo',
            'admin_solicitudes_plan_lista': 'solicitudes',
            'admin_testimonios_lista': 'testimonios',
            'admin_gestionar_admins': 'equipo',
            'mis_horarios': 'mis_horarios',
        }
        for ruta, seccion in casos.items():
            with self.subTest(ruta=ruta):
                self.assertEqual(seccion_actual(ruta), seccion)


class MenuPorRolTests(PanelBase):
    def test_superadmin_ve_las_secciones_para_resolver_y_el_equipo(self):
        self.entrar(self.superadmin)
        r = self.client.get(reverse('gravity:admin_clases_lista'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Solicitudes de plan')
        self.assertContains(r, reverse('gravity:admin_profesoras_lista'))
        self.assertNotContains(r, 'Accesos del equipo')
        self.assertContains(r, 'class="ad-tabbar"')
        self.assertTrue(r.context['panel']['ve_ingresos'])

    def test_el_equipo_no_ve_lo_que_no_puede_usar(self):
        self.entrar(self.equipo)
        r = self.client.get(reverse('gravity:admin_clases_lista'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Solicitudes de plan')
        self.assertNotContains(r, reverse('gravity:admin_testimonios_lista'))
        self.assertNotContains(r, reverse('gravity:admin_profesoras_lista'))
        self.assertContains(r, reverse('gravity:mis_horarios'))
        self.assertFalse(r.context['panel']['ve_ingresos'])
        self.assertEqual(r.context['panel']['rol'], 'Equipo')

    def test_la_seccion_actual_queda_marcada(self):
        self.entrar(self.superadmin)
        r = self.client.get(reverse('gravity:admin_clase_detalle', args=[self.clase.id]))
        self.assertEqual(r.context['panel']['titulo'], 'Clases')
        self.assertTrue(r.context['panel']['mas_activo'])

    def test_fuera_del_panel_no_se_calcula(self):
        self.entrar(self.superadmin)
        r = self.client.get(reverse('gravity:home'))
        self.assertNotIn('panel', r.context)

    def test_las_paginas_del_panel_cargan_con_la_base_nueva(self):
        self.entrar(self.superadmin)
        for ruta in ('admin_dashboard', 'admin_asistencia', 'admin_reservas_lista', 'admin_usuarios_lista',
                     'admin_pagos_vista_principal', 'admin_reportes', 'admin_historial_actividad',
                     'admin_profesoras_lista', 'admin_equipo_sumar', 'admin_testimonios_lista',
                     'admin_solicitudes_plan_lista', 'admin_agregar_usuario', 'admin_pagos_configurar_planes'):
            with self.subTest(ruta=ruta):
                r = self.client.get(reverse(f'gravity:{ruta}'))
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'id="ad-bandeja"')


class BandejaTests(PanelBase):
    def test_muestra_la_actividad_y_se_marca_como_vista(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)
        NotificacionCancelacion.objects.create(
            reserva=reserva, tipo='temporal', fecha_ausencia=self.hoy + timedelta(days=2)
        )
        self.entrar(self.equipo)

        r = self.client.get(reverse('gravity:admin_clases_lista'))
        self.assertEqual(r.context['panel']['notificaciones']['sin_leer'], 1)
        self.assertContains(r, 'Avril Sosa avisó que no va')
        self.assertContains(r, 'data-bandeja-dot')

        self.client.post(reverse('gravity:admin_marcar_notificaciones_leidas'), '{}',
                         content_type='application/json')
        r = self.client.get(reverse('gravity:admin_clases_lista'))
        self.assertEqual(r.context['panel']['notificaciones']['sin_leer'], 0)
        self.assertNotContains(r, 'data-bandeja-dot>')

    def test_las_solicitudes_de_plan_solo_le_aparecen_al_superadmin(self):
        SolicitudCambioPlan.objects.create(usuario=self.alumna, plan_solicitado=self.plan)
        Testimonio.objects.create(usuario=self.alumna, texto='Me encanta.', aprobado=False)

        self.entrar(self.equipo)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertEqual(r.context['panel']['pendientes_total'], 0)
        self.assertNotContains(r, 'solicitud de plan')
        self.assertNotContains(r, 'Avril Sosa</span> solicita')

        self.entrar(self.superadmin)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertEqual(r.context['panel']['pendientes'], {'solicitudes': 1, 'testimonios': 1})
        self.assertContains(r, '1 solicitud de plan')


class PermisosDelEquipoTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.estado = EstadoPagoCliente.objects.create(usuario=self.alumna, plan_actual=self.plan, activo=True)
        self.entrar(self.equipo)

    def test_no_puede_cambiar_precios_ni_crear_planes(self):
        r = self.client.post(reverse('gravity:admin_pagos_configurar_planes'), {
            'editar_plan': self.plan.id, 'nombre': self.plan.nombre, 'clases_por_semana': 2,
            'precio_mensual': '1000', 'descripcion': '', 'activo': 'True',
        })
        self.assertRedirects(r, reverse('gravity:admin_dashboard'), fetch_redirect_response=False)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.precio_mensual, Decimal('61000'))

    def test_no_entra_a_testimonios(self):
        r = self.client.get(reverse('gravity:admin_testimonios_lista'))
        self.assertRedirects(r, reverse('gravity:admin_dashboard'), fetch_redirect_response=False)

    def test_no_puede_cancelar_el_plan_de_un_alumno(self):
        plan_usuario = PlanUsuario.objects.create(
            usuario=self.alumna, plan=self.plan, fecha_inicio=self.hoy, fecha_fin=self.hoy + timedelta(days=30)
        )
        reserva = Reserva.objects.create(usuario=self.alumna, clase=self.clase)

        r = self.client.post(reverse('gravity:admin_cancelar_plan_usuario', args=[plan_usuario.id]))

        self.assertEqual(r.status_code, 302)
        plan_usuario.refresh_from_db()
        reserva.refresh_from_db()
        self.assertTrue(plan_usuario.activo)
        self.assertTrue(reserva.activa)
        r = self.client.get(reverse('gravity:admin_usuario_detalle', args=[self.alumna.id]))
        self.assertNotContains(r, 'onclick="confirmarCancelarPlan(')

    def test_ve_la_deuda_del_alumno_pero_no_los_ingresos_del_estudio(self):
        RegistroPago.objects.bulk_create([RegistroPago(
            cliente=self.alumna, monto=Decimal('61000'), fecha_pago=self.hoy,
            tipo_pago='efectivo', estado='confirmado', concepto='Cuota',
        )])

        r = self.client.get(reverse('gravity:admin_pagos_vista_principal'))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['ingresos_mes'])
        self.assertFalse(r.context['puede_configurar_planes'])
        self.assertNotContains(r, reverse('gravity:admin_pagos_configurar_planes'))

        r = self.client.get(reverse('gravity:admin_pagos_historial_cliente', args=[self.alumna.id]))
        self.assertEqual(r.context['total_pagado'], Decimal('61000'))
        self.assertEqual(len(r.context['pagos']), 1)

        r = self.client.get(reverse('gravity:admin_reportes'))
        self.assertFalse(r.context['puede_ver_pagos'])

    def test_ve_la_cuenta_del_alumno_pero_no_cambia_el_plan(self):
        otro = PlanPago.objects.create(nombre='3 clases semanales', clases_por_semana=3, precio_mensual=Decimal('70000'))

        r = self.client.get(reverse('gravity:admin_pagos_editar_estado_cliente', args=[self.alumna.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Estado de la cuenta')
        self.assertNotContains(r, 'Guardar plan y configuración')

        r = self.client.post(reverse('gravity:admin_pagos_editar_estado_cliente', args=[self.alumna.id]),
                             {'plan_actual': otro.id, 'activo': 'on', 'puede_reservar': 'on'})
        self.assertEqual(r.status_code, 302)
        self.estado.refresh_from_db()
        self.assertEqual(self.estado.plan_actual, self.plan)
        self.assertFalse(PlanUsuario.objects.filter(usuario=self.alumna, plan=otro).exists())

    def test_puede_registrar_un_pago(self):
        r = self.client.get(reverse('gravity:admin_pagos_registrar_pago', args=[self.alumna.id]))
        self.assertEqual(r.status_code, 200)

    def test_el_superadmin_sigue_viendo_los_ingresos(self):
        self.entrar(self.superadmin)
        r = self.client.get(reverse('gravity:admin_pagos_vista_principal'))
        self.assertIsNotNone(r.context['ingresos_mes'])
        self.assertContains(r, reverse('gravity:admin_pagos_configurar_planes'))
        r = self.client.get(reverse('gravity:admin_reportes'))
        self.assertTrue(r.context['puede_ver_pagos'])
