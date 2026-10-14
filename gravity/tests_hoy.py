"""Etapa 2 del panel: "Hoy", Actividad y Estadísticas."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .hoy import DIAS, clases_del_dia, dias_navegables, elegir_fecha
from .models import (
    AusenciaTemporal,
    CancelacionAdmin,
    Clase,
    NotificacionCancelacion,
    Reserva,
    SolicitudCambioPlan,
    PlanPago,
)


class HoyBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.superadmin = User.objects.create_superuser(username='nico', email='nico@test.com', password='clave-123')
        self.equipo = User.objects.create_user(username='diana', password='clave-123', is_staff=True)

    def alumno(self, nombre):
        return User.objects.create_user(username=nombre.lower(), password='clave-123', first_name=nombre, last_name='Test')

    def clase(self, fecha, hora=18, tipo='Reformer', cupo=5):
        return Clase.objects.create(tipo=tipo, dia=DIAS[fecha.weekday()], horario=time(hora),
                                    direccion='sede_2', cupo_maximo=cupo)

    def suelta(self, usuario, clase, fecha, activa=True, recupero=True):
        return Reserva.objects.create(usuario=usuario, clase=clase, fecha_unica=fecha,
                                      es_recupero=recupero, activa=activa)


class ClasesDelDiaTests(HoyBase):
    def test_cuenta_quien_viene_ese_dia(self):
        fecha = self.hoy - timedelta(days=7)
        clase = self.clase(fecha)
        ana, bea, caro, dani = (self.alumno(n) for n in ('Ana', 'Bea', 'Caro', 'Dani'))
        Reserva.objects.create(usuario=ana, clase=clase)
        fija_bea = Reserva.objects.create(usuario=bea, clase=clase)
        AusenciaTemporal.objects.create(reserva=fija_bea, fecha=fecha)
        # Recupero que ya se hizo: el comando de limpieza lo dejó inactivo, pero cuenta
        self.suelta(caro, clase, fecha, activa=False)
        # Recupero que el alumno canceló: no cuenta
        cancelado = self.suelta(dani, clase, fecha, activa=False)
        NotificacionCancelacion.objects.create(reserva=cancelado, tipo='permanente')

        [item] = clases_del_dia(fecha)

        self.assertEqual(item['vienen'], 2)
        self.assertEqual(item['avisaron'], 1)
        self.assertEqual(item['sueltas'], 1)
        nombres = {a['nombre']: a for a in item['alumnos']}
        self.assertNotIn('Dani Test', nombres)
        self.assertIn(('Recupero', 'ok'), nombres['Caro Test']['marcas'])
        self.assertIn(('Avisó que no viene', 'warn'), nombres['Bea Test']['marcas'])
        self.assertEqual(item['momento'], 'pasada')

    def test_marca_salud_cumple_y_primera_clase(self):
        fecha = self.hoy  # la fecha de primera clase no puede ser futura
        clase = self.clase(fecha)
        eva = self.alumno('Eva')
        perfil = UserProfile.objects.get(user=eva)
        perfil.tiene_lesiones = True
        perfil.descripcion_lesiones = 'Hernia de disco'
        perfil.fecha_primera_clase = fecha
        perfil.fecha_nacimiento = fecha.replace(year=1990)
        perfil.save()
        Reserva.objects.create(usuario=eva, clase=clase)

        [item] = clases_del_dia(fecha)
        textos = [t for t, _ in item['alumnos'][0]['marcas']]
        self.assertEqual(textos, ['Primera clase', 'Cumple años', 'Salud'])

    def test_elige_el_dia_pedido_o_el_proximo_con_clases(self):
        manana = self.hoy + timedelta(days=1)
        chips = dias_navegables(self.hoy, {DIAS[manana.weekday()]})
        self.assertEqual(len(chips), 7)
        self.assertEqual([c['texto'] for c in chips[:2]], ['Hoy', 'Mañana'])
        self.assertEqual(elegir_fecha('', self.hoy, chips), manana)
        pasado = (self.hoy + timedelta(days=3)).isoformat()
        self.assertEqual(elegir_fecha(pasado, self.hoy, chips).isoformat(), pasado)
        self.assertEqual(elegir_fecha('2001-01-01', self.hoy, chips), manana)


class PantallaHoyTests(HoyBase):
    def test_el_equipo_ve_las_clases_y_no_la_plata(self):
        clase = self.clase(self.hoy + timedelta(days=1), hora=9)
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=clase)
        self.client.force_login(self.equipo)

        r = self.client.get(reverse('gravity:admin_dashboard'), {'fecha': (self.hoy + timedelta(days=1)).isoformat()})

        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ana Test')
        self.assertContains(r, '09:00')
        self.assertIsNone(r.context['mes'])
        self.assertNotContains(r, 'Plata de')

    def test_el_superadmin_ve_la_plata_del_mes(self):
        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertContains(r, 'Plata de')

    def test_sin_clases_lo_dice(self):
        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertContains(r, 'No hay clases')


class ActividadTests(HoyBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.equipo)
        self.alumna = self.alumno('Lia')

    def test_un_recupero_que_se_hizo_figura_como_realizado(self):
        fecha = self.hoy - timedelta(days=2)
        self.suelta(self.alumna, self.clase(fecha), fecha, activa=False)
        r = self.client.get(reverse('gravity:admin_historial_actividad'))
        self.assertContains(r, 'Lia Test reservó un recupero')
        self.assertContains(r, 'Realizada')
        self.assertNotContains(r, '>Cancelada<')

    def test_cancelar_un_recupero_no_es_dejar_el_horario_fijo(self):
        fecha = self.hoy + timedelta(days=3)
        recupero = self.suelta(self.alumna, self.clase(fecha), fecha)
        recupero.activa = False
        recupero.save()
        NotificacionCancelacion.objects.create(reserva=recupero, tipo='permanente')

        r = self.client.get(reverse('gravity:admin_historial_actividad'))
        self.assertContains(r, f'Lia Test canceló su recupero del {fecha:%d/%m}')
        self.assertNotContains(r, 'dejó su horario fijo')

    def test_por_defecto_muestra_los_ultimos_30_dias(self):
        fija = Reserva.objects.create(usuario=self.alumna, clase=self.clase(self.hoy))
        aviso = NotificacionCancelacion.objects.create(reserva=fija, tipo='temporal', fecha_ausencia=self.hoy)
        NotificacionCancelacion.objects.filter(pk=aviso.pk).update(fecha_creacion=timezone.now() - timedelta(days=60))

        r = self.client.get(reverse('gravity:admin_historial_actividad'))
        self.assertEqual(r.context['total_eventos'], 0)
        r = self.client.get(reverse('gravity:admin_historial_actividad'), {'dias': '90'})
        self.assertEqual(r.context['total_eventos'], 1)

    def test_la_cancelacion_del_estudio_muestra_quien_y_el_motivo(self):
        fija = Reserva.objects.create(usuario=self.alumna, clase=self.clase(self.hoy))
        CancelacionAdmin.objects.create(reserva=fija, admin_user=self.superadmin, motivo='Clase suspendida')
        r = self.client.get(reverse('gravity:admin_historial_actividad'), {'tipo': 'cancelacion_admin'})
        self.assertContains(r, 'Se canceló el horario fijo de Lia Test')
        self.assertContains(r, 'Clase suspendida')


class EstadisticasTests(HoyBase):
    def test_los_recuperos_que_pasaron_no_son_bajas(self):
        alumna = self.alumno('Mia')
        ayer = self.hoy - timedelta(days=1)
        clase = self.clase(ayer)
        self.suelta(alumna, clase, ayer, activa=False)                      # recupero hecho
        self.suelta(alumna, self.clase(ayer, hora=10), ayer, activa=False, recupero=False)  # clase única hecha
        fija = Reserva.objects.create(usuario=alumna, clase=self.clase(self.hoy, hora=8))
        fija.activa = False
        fija.save()                                                         # baja de horario fijo
        self.client.force_login(self.superadmin)

        r = self.client.get(reverse('gravity:admin_reportes'), {'periodo': '7'})

        self.assertEqual(r.context['bajas'], 1)
        self.assertEqual(r.context['recuperos'], 1)
        self.assertEqual(r.context['clases_extra'], 1)
        self.assertContains(r, 'id="plata"')

    def test_el_equipo_no_ve_plata_ni_el_aviso_de_solicitudes(self):
        plan = PlanPago.objects.create(nombre='2 clases', clases_por_semana=2, precio_mensual=Decimal('61000'))
        SolicitudCambioPlan.objects.create(usuario=self.alumno('Ivi'), plan_solicitado=plan)
        self.client.force_login(self.equipo)

        r = self.client.get(reverse('gravity:admin_reportes'))

        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'id="plata"')
        self.assertNotContains(r, 'solicitud de cambio de plan sin resolver')
        self.assertNotContains(r, reverse('gravity:admin_solicitudes_plan_lista'))

    def test_exporta_csv(self):
        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('gravity:admin_reportes_exportar'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Clases únicas', r.content.decode('utf-8-sig'))
