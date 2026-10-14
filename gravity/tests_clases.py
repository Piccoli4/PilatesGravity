"""Etapa 3 del panel: lista, alta, edición, pausa y eliminación de clases."""
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.mi_espacio import reservas_alumno, resumen_alumno

from .hoy import DIAS
from .models import AusenciaTemporal, CancelacionAdmin, Clase, Reserva


class ClasesBase(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.equipo = User.objects.create_user(username='diana', password='clave-123', is_staff=True, first_name='Diana')
        self.client.force_login(self.equipo)
        # Una clase que se dicta mañana, para tener fechas futuras claras
        self.manana = self.hoy + timedelta(days=1)
        if self.manana.weekday() == 6:
            self.manana += timedelta(days=1)
        self.clase = Clase.objects.create(tipo='Reformer', dia=DIAS[self.manana.weekday()], horario=time(18),
                                          direccion='sede_2', cupo_maximo=5)

    def alumno(self, nombre, email=True):
        return User.objects.create_user(username=nombre.lower(), password='clave-123', first_name=nombre,
                                        last_name='Test', email=f'{nombre.lower()}@test.com' if email else '')

    def datos(self, **cambios):
        datos = {'tipo': 'Reformer', 'direccion': 'sede_2', 'dia': self.clase.dia,
                 'horario': '18:00', 'cupo_maximo': '5', 'activa': 'on'}
        datos.update(cambios)
        return datos


class CrearClaseTests(ClasesBase):
    def test_crea_y_lleva_al_detalle(self):
        r = self.client.post(reverse('gravity:admin_clase_crear'), self.datos(dia='Lunes', horario='09:30', cupo_maximo='8'))
        clase = Clase.objects.get(dia='Lunes', horario=time(9, 30))
        self.assertRedirects(r, reverse('gravity:admin_clase_detalle', args=[clase.id]), fetch_redirect_response=False)
        self.assertTrue(clase.activa)

    def test_valida_horario_cupo_y_duplicados(self):
        url = reverse('gravity:admin_clase_crear')
        r = self.client.post(url, self.datos(dia='Lunes', horario='05:00'))
        self.assertIn('horario', r.context['form'].errors)
        r = self.client.post(url, self.datos(dia='Lunes', cupo_maximo='0'))
        self.assertIn('cupo_maximo', r.context['form'].errors)
        r = self.client.post(url, self.datos())  # igual a la que ya existe
        self.assertContains(r, 'Ya existe')
        r = self.client.post(url, self.datos(dia='Sábado'))
        self.assertIn('dia', r.context['form'].errors)
        self.assertEqual(Clase.objects.count(), 1)

    def test_especial_necesita_nombre_y_las_demas_no_lo_guardan(self):
        url = reverse('gravity:admin_clase_crear')
        r = self.client.post(url, self.datos(tipo='Especial', dia='Sábado', horario='10:00'))
        self.assertIn('nombre_personalizado', r.context['form'].errors)
        self.client.post(url, self.datos(dia='Lunes', horario='10:00', nombre_personalizado='Sobra'))
        self.assertIsNone(Clase.objects.get(dia='Lunes', horario=time(10)).nombre_personalizado)

    def test_crear_otra_igual_precarga_los_datos(self):
        r = self.client.get(reverse('gravity:admin_clase_crear'), {'tipo': 'Cadillac', 'dia': 'Martes', 'horario': '19:00'})
        self.assertEqual(r.context['form'].initial['tipo'], 'Cadillac')
        self.assertContains(r, 'value="19:00"')


class EditarClaseTests(ClasesBase):
    def test_el_cupo_no_baja_de_los_horarios_fijos(self):
        for nombre in ('Ana', 'Bea', 'Caro'):
            Reserva.objects.create(usuario=self.alumno(nombre), clase=self.clase)
        r = self.client.post(reverse('gravity:admin_clase_editar', args=[self.clase.id]), self.datos(cupo_maximo='2'))
        self.assertContains(r, '3 alumnos con horario fijo')
        self.clase.refresh_from_db()
        self.assertEqual(self.clase.cupo_maximo, 5)

    def test_cambiar_el_horario_avisa_y_conserva_los_recuperos(self):
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase)
        recupero = Reserva.objects.create(usuario=self.alumno('Bea'), clase=self.clase,
                                          fecha_unica=self.manana, es_recupero=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('gravity:admin_clase_editar', args=[self.clase.id]),
                             self.datos(horario='19:00', avisar='on'))
        self.clase.refresh_from_db()
        self.assertEqual(self.clase.horario, time(19))
        recupero.refresh_from_db()
        self.assertTrue(recupero.activa)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['ana@test.com', 'bea@test.com'])

    def test_cambiar_el_dia_cancela_recuperos_y_avisos_futuros(self):
        fija = Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase)
        AusenciaTemporal.objects.create(reserva=fija, fecha=self.manana)
        recupero = Reserva.objects.create(usuario=self.alumno('Bea'), clase=self.clase,
                                          fecha_unica=self.manana, es_recupero=True)
        otro_dia = 'Lunes' if self.clase.dia != 'Lunes' else 'Martes'

        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse('gravity:admin_clase_editar', args=[self.clase.id]),
                                 self.datos(dia=otro_dia, avisar='on'), follow=True)

        recupero.refresh_from_db()
        self.assertFalse(recupero.activa)
        self.assertTrue(CancelacionAdmin.objects.filter(reserva=recupero, motivo='Cambio de horario de la clase').exists())
        self.assertFalse(AusenciaTemporal.objects.filter(reserva=fija).exists())
        fija.refresh_from_db()
        self.assertTrue(fija.activa)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['ana@test.com', 'bea@test.com'])
        self.assertContains(r, 'Se cancelaron 1 recupero')

    def test_sin_tildar_no_manda_emails(self):
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('gravity:admin_clase_editar', args=[self.clase.id]), self.datos(horario='20:00'))
        self.assertEqual(mail.outbox, [])


class PausarYEliminarTests(ClasesBase):
    def test_pausar_conserva_las_reservas_y_se_pueden_cancelar(self):
        ana = self.alumno('Ana')
        fija = Reserva.objects.create(usuario=ana, clase=self.clase)

        self.client.post(reverse('gravity:admin_clase_toggle_status', args=[self.clase.id]))

        self.clase.refresh_from_db()
        fija.refresh_from_db()
        self.assertFalse(self.clase.activa)
        self.assertTrue(fija.activa)
        # El alumno ve su horario "en pausa" y no figura como próxima clase
        self.assertIsNone(resumen_alumno(ana)['proxima'])
        mis = reservas_alumno(ana)
        self.assertTrue(mis['horarios'][0]['pausada'])
        self.assertEqual(mis['agenda'], [])
        # Y se puede cancelar aunque la clase esté en pausa
        fija.activa = False
        fija.save()
        # Pero no se puede reservar una clase en pausa
        with self.assertRaises(Exception):
            Reserva.objects.create(usuario=self.alumno('Bea'), clase=self.clase)

    def test_solo_se_elimina_si_nunca_tuvo_reservas(self):
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase, activa=False)
        r = self.client.get(reverse('gravity:admin_clase_eliminar', args=[self.clase.id]))
        self.assertContains(r, 'no se puede eliminar')
        self.client.post(reverse('gravity:admin_clase_eliminar', args=[self.clase.id]))
        self.assertTrue(Clase.objects.filter(pk=self.clase.pk).exists())

        nueva = Clase.objects.create(tipo='Cadillac', dia='Lunes', horario=time(8), direccion='sede_2', cupo_maximo=4)
        r = self.client.post(reverse('gravity:admin_clase_eliminar', args=[nueva.id]))
        self.assertRedirects(r, reverse('gravity:admin_clases_lista'), fetch_redirect_response=False)
        self.assertFalse(Clase.objects.filter(pk=nueva.pk).exists())


class ListaYDetalleTests(ClasesBase):
    def test_la_lista_agrupa_por_dia_y_por_defecto_muestra_activas(self):
        Clase.objects.create(tipo='Cadillac', dia='Lunes', horario=time(8), direccion='sede_2', cupo_maximo=4, activa=False)
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase)
        # una clase única futura no cuenta como lugar fijo
        Reserva.objects.create(usuario=self.alumno('Bea'), clase=self.clase, fecha_unica=self.manana)

        r = self.client.get(reverse('gravity:admin_clases_lista'))
        self.assertEqual([d['dia'] for d in r.context['dias']], [self.clase.dia])
        item = r.context['dias'][0]['clases'][0]
        self.assertEqual((item['fijos'], item['libres']), (1, 4))
        self.assertEqual(r.context['conteo'], {'activas': 1, 'pausadas': 1, 'todas': 2})

        r = self.client.get(reverse('gravity:admin_clases_lista'), {'estado': 'pausadas'})
        self.assertEqual([d['dia'] for d in r.context['dias']], ['Lunes'])

    def test_el_detalle_muestra_quien_viene_y_las_proximas_semanas(self):
        Reserva.objects.create(usuario=self.alumno('Ana'), clase=self.clase)
        Reserva.objects.create(usuario=self.alumno('Bea'), clase=self.clase, fecha_unica=self.manana, es_recupero=True)

        r = self.client.get(reverse('gravity:admin_clase_detalle', args=[self.clase.id]))

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['proxima']['vienen'], 2)
        self.assertEqual(len(r.context['semanas']), 4)
        self.assertContains(r, 'Ana Test')
        self.assertContains(r, 'Recupero')
