"""Etapa 7 del panel: Asistencia (pasar lista y faltas)."""
import json
from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.baja import anonimizar_cuenta

from .actividad import dar_de_baja_reservas, sueltas_no_canceladas
from .asistencia_admin import lista_del_dia
from .hoy import DIAS
from .models import AusenciaTemporal, CancelacionAdmin, Clase, Inasistencia, NotificacionCancelacion, Reserva


class AsistenciaBase(TestCase):
    """El reloj queda fijo hoy a las 10:00, así los tests no dependen de la hora."""

    def setUp(self):
        hoy = timezone.localdate()
        self.ahora = timezone.make_aware(datetime.combine(hoy, time(10)))
        reloj = mock.patch('django.utils.timezone.now', return_value=self.ahora)
        reloj.start()
        self.addCleanup(reloj.stop)
        self.hoy = hoy
        self.ayer = hoy - timedelta(days=1)
        self.superadmin = User.objects.create_superuser(username='nico', email='nico@test.com', password='clave-123')
        self.equipo = User.objects.create_user(username='diana', first_name='Diana', password='clave-123', is_staff=True)

    def alumno(self, nombre):
        return User.objects.create_user(username=nombre.lower(), password='clave-123', first_name=nombre, last_name='Test')

    def clase(self, fecha, hora=18, tipo='Reformer', creada_hace=60, activa=True):
        clase = Clase.objects.create(tipo=tipo, dia=DIAS[fecha.weekday()], horario=time(hora),
                                     direccion='sede_2', cupo_maximo=5, activa=activa)
        Clase.objects.filter(id=clase.id).update(fecha_creacion=self.ahora - timedelta(days=creada_hace))
        clase.refresh_from_db()
        return clase

    def fija(self, usuario, clase, desde_hace=30):
        reserva = Reserva.objects.create(usuario=usuario, clase=clase)
        Reserva.objects.filter(id=reserva.id).update(fecha_reserva=self.ahora - timedelta(days=desde_hace))
        reserva.refresh_from_db()
        return reserva

    def baja(self, reserva, hace_dias):
        """Baja del alumno registrada hace `hace_dias` días."""
        reserva.activa = False
        reserva.save()
        aviso = NotificacionCancelacion.objects.create(reserva=reserva, tipo='permanente')
        NotificacionCancelacion.objects.filter(id=aviso.id).update(
            fecha_creacion=self.ahora - timedelta(days=hace_dias))

    def suelta(self, usuario, clase, fecha, activa=True, recupero=True):
        return Reserva.objects.create(usuario=usuario, clase=clase, fecha_unica=fecha,
                                      es_recupero=recupero, activa=activa)

    def marcar(self, reserva, fecha, marcar=True, usuario=None):
        self.client.force_login(usuario or self.superadmin)
        return self.client.post(
            reverse('gravity:admin_asistencia_marcar'),
            data=json.dumps({'reserva_id': reserva.id, 'fecha': fecha.isoformat(), 'marcar': marcar}),
            content_type='application/json',
        )


class ListaDelDiaTests(AsistenciaBase):
    def test_un_dia_pasado_se_arma_con_lo_que_habia_ese_dia(self):
        fecha = self.hoy - timedelta(days=7)
        clase = self.clase(fecha)
        ana, bea, caro, dani, eva = (self.alumno(n) for n in ('Ana', 'Bea', 'Caro', 'Dani', 'Eva'))
        self.fija(ana, clase)
        self.fija(bea, clase, desde_hace=2)              # se anotó después: no estaba
        self.baja(self.fija(caro, clase), hace_dias=2)   # se dio de baja después: estaba
        self.baja(self.fija(dani, clase), hace_dias=10)  # ya se había dado de baja
        self.suelta(eva, clase, fecha, activa=False)     # recupero que la limpieza desactivó
        self.clase(fecha, hora=19, creada_hace=3)         # la clase todavía no existía

        [item] = lista_del_dia(fecha)

        self.assertEqual({a['nombre'] for a in item['alumnos']}, {'Ana Test', 'Caro Test', 'Eva Test'})
        self.assertTrue(all(a['marcable'] for a in item['alumnos']))
        self.assertEqual(item['momento'], 'pasada')

    def test_el_no_vino_de_una_reserva_dada_de_baja_se_sigue_viendo(self):
        fecha = self.hoy - timedelta(days=7)
        clase = self.clase(fecha)
        reserva = self.fija(self.alumno('Caro'), clase)
        Inasistencia.objects.create(reserva=reserva, fecha=fecha)
        self.baja(reserva, hace_dias=1)

        [item] = lista_del_dia(fecha)

        self.assertTrue(item['alumnos'][0]['no_vino'])
        self.assertEqual(item['no_vino'], 1)
        self.assertEqual(item['vinieron'], 0)

    def test_avisos_y_cancelaciones_del_estudio(self):
        fecha = self.ayer
        clase = self.clase(fecha)
        ana, bea = self.alumno('Ana'), self.alumno('Bea')
        fija_ana = self.fija(ana, clase)
        AusenciaTemporal.objects.create(reserva=fija_ana, fecha=fecha)
        cancelada = self.suelta(bea, clase, fecha, activa=False)
        CancelacionAdmin.objects.create(reserva=cancelada, admin_user=self.superadmin, motivo='Otro')

        [item] = lista_del_dia(fecha)

        [a] = item['alumnos']
        self.assertTrue(a['avisaron'])
        self.assertFalse(a['marcable'])
        self.assertEqual((item['anotados'], item['avisaron']), (0, 1))

    def test_clase_en_pausa(self):
        clase = self.clase(self.hoy, activa=False)
        self.assertEqual(lista_del_dia(self.hoy), [])
        # Se pausó hace 2 días: la semana pasada se dictaba
        Clase.objects.filter(id=clase.id).update(fecha_modificacion=self.ahora - timedelta(days=2))
        self.assertEqual(len(lista_del_dia(self.hoy - timedelta(days=7))), 1)
        self.assertEqual(lista_del_dia(self.hoy), [])

    def test_hoy_no_se_marca_antes_de_que_empiece(self):
        temprano = self.clase(self.hoy, hora=9)
        tarde = self.clase(self.hoy, hora=18)
        self.fija(self.alumno('Ana'), temprano)
        self.fija(self.alumno('Bea'), tarde)

        por_clase = {item['clase'].id: item for item in lista_del_dia(self.hoy)}

        self.assertEqual(por_clase[temprano.id]['momento'], 'pasada')
        self.assertTrue(por_clase[temprano.id]['alumnos'][0]['marcable'])
        self.assertEqual(por_clase[tarde.id]['momento'], 'proxima')
        self.assertFalse(por_clase[tarde.id]['alumnos'][0]['marcable'])

    def test_mas_de_7_dias_es_solo_lectura(self):
        fecha = self.hoy - timedelta(days=14)
        self.fija(self.alumno('Ana'), self.clase(fecha))
        [item] = lista_del_dia(fecha)
        self.assertFalse(item['marcable'])
        self.assertFalse(item['alumnos'][0]['marcable'])


class MarcarTests(AsistenciaBase):
    def test_marca_y_deshace(self):
        reserva = self.fija(self.alumno('Ana'), self.clase(self.ayer))

        r = self.marcar(reserva, self.ayer)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['estado'], 'no_vino')
        inasistencia = Inasistencia.objects.get(reserva=reserva, fecha=self.ayer)
        self.assertEqual(inasistencia.registrado_por, self.superadmin)

        r = self.marcar(reserva, self.ayer, marcar=False)
        self.assertEqual(r.json()['estado'], 'vino')
        self.assertFalse(Inasistencia.objects.exists())

    def test_se_marca_un_recupero_que_la_limpieza_ya_desactivo(self):
        reserva = self.suelta(self.alumno('Eva'), self.clase(self.ayer), self.ayer, activa=False)
        r = self.marcar(reserva, self.ayer)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Inasistencia.objects.filter(reserva=reserva).exists())

    def test_rechazos(self):
        ana = self.alumno('Ana')
        clase_ayer = self.clase(self.ayer)
        fija = self.fija(ana, clase_ayer)
        de_hoy = self.fija(self.alumno('Bea'), self.clase(self.hoy, hora=18))
        vieja = self.fija(self.alumno('Caro'), self.clase(self.hoy - timedelta(days=8)))
        avisada = self.fija(self.alumno('Dani'), clase_ayer)
        AusenciaTemporal.objects.create(reserva=avisada, fecha=self.ayer)
        nueva = self.fija(self.alumno('Eva'), clase_ayer, desde_hace=0)

        casos = [
            (de_hoy, self.hoy, 'todavía no empezó'),
            (vieja, self.hoy - timedelta(days=8), 'últimos 7 días'),
            (fija, self.hoy - timedelta(days=2), 'no estaba anotado'),   # otro día de la semana
            (avisada, self.ayer, 'avisó'),
            (nueva, self.ayer, 'no estaba anotado'),                     # se anotó hoy
        ]
        for reserva, fecha, texto in casos:
            with self.subTest(texto=texto):
                r = self.marcar(reserva, fecha)
                self.assertEqual(r.status_code, 400)
                self.assertIn(texto, r.json()['error'])
        self.assertFalse(Inasistencia.objects.exists())

    def test_datos_invalidos_no_rompen(self):
        self.client.force_login(self.superadmin)
        url = reverse('gravity:admin_asistencia_marcar')
        for cuerpo in ('no es json', '[]', json.dumps({'reserva_id': 'x', 'fecha': 'ayer'})):
            with self.subTest(cuerpo=cuerpo):
                r = self.client.post(url, data=cuerpo, content_type='application/json')
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_sin_javascript_vuelve_a_la_lista(self):
        reserva = self.fija(self.alumno('Ana'), self.clase(self.ayer))
        self.client.force_login(self.equipo)
        volver = f'{reverse("gravity:admin_asistencia")}?fecha={self.ayer.isoformat()}'
        r = self.client.post(reverse('gravity:admin_asistencia_marcar'), {
            'reserva_id': reserva.id, 'fecha': self.ayer.isoformat(), 'marcar': '1', 'next': volver,
        })
        self.assertRedirects(r, volver, fetch_redirect_response=False)
        self.assertTrue(Inasistencia.objects.filter(reserva=reserva, registrado_por=self.equipo).exists())

        r = self.client.post(reverse('gravity:admin_asistencia_marcar'), {
            'reserva_id': reserva.id, 'fecha': self.ayer.isoformat(), 'marcar': '0', 'next': 'https://otro.com/',
        })
        self.assertRedirects(r, reverse('gravity:admin_asistencia'), fetch_redirect_response=False)
        self.assertFalse(Inasistencia.objects.exists())

    def test_permisos(self):
        reserva = self.fija(self.alumno('Ana'), self.clase(self.ayer))
        self.assertEqual(self.marcar(reserva, self.ayer, usuario=self.equipo).status_code, 200)
        alumna = self.alumno('Bea')
        self.assertEqual(self.marcar(reserva, self.ayer, marcar=False, usuario=alumna).status_code, 302)
        self.assertTrue(Inasistencia.objects.exists())


class PaginasTests(AsistenciaBase):
    def test_pasar_lista(self):
        clase = self.clase(self.ayer)
        self.fija(self.alumno('Ana'), clase)
        self.client.force_login(self.equipo)

        r = self.client.get(reverse('gravity:admin_asistencia'), {'fecha': self.ayer.isoformat()})

        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ana Test')
        self.assertContains(r, f'id="clase-{clase.id}"')
        self.assertContains(r, 'data-as-form')
        self.assertContains(r, 'Marcar que Ana Test no vino')
        self.assertNotContains(r, '3696s')

    def test_fecha_vieja_y_futura(self):
        vieja = self.hoy - timedelta(days=14)
        self.fija(self.alumno('Ana'), self.clase(vieja))
        self.client.force_login(self.superadmin)

        r = self.client.get(reverse('gravity:admin_asistencia'), {'fecha': vieja.isoformat()})
        self.assertContains(r, 'Ana Test')
        self.assertContains(r, 'solo para consultar')
        self.assertNotContains(r, 'data-as-form')

        futura = self.hoy + timedelta(days=2)
        r = self.client.get(reverse('gravity:admin_asistencia'), {'fecha': futura.isoformat()})
        self.assertEqual(r.context['fecha'], futura)
        self.assertContains(r, 'Todavía no pasó')

    def test_los_nombres_se_escapan(self):
        malo = User.objects.create_user(username='malo', first_name='<img src=x onerror=alert(1)>', password='x')
        reserva = self.fija(malo, self.clase(self.ayer))
        AusenciaTemporal.objects.create(reserva=reserva, fecha=self.ayer - timedelta(days=7))
        self.client.force_login(self.superadmin)
        for ruta, datos in (('admin_asistencia', {'fecha': self.ayer.isoformat()}),
                            ('admin_asistencia_ausencias', {'periodo': '30'})):
            with self.subTest(ruta=ruta):
                r = self.client.get(reverse(f'gravity:{ruta}'), datos)
                self.assertNotContains(r, '<img src=x')
                self.assertContains(r, '&lt;img src=x')


class FaltasTests(AsistenciaBase):
    def test_estado_del_recupero(self):
        ana = self.alumno('Ana')
        clase = self.clase(self.hoy, tipo='Reformer')
        reserva = self.fija(ana, clase, desde_hace=60)
        recuperada = AusenciaTemporal.objects.create(reserva=reserva, fecha=self.hoy - timedelta(days=21))
        pendiente = AusenciaTemporal.objects.create(reserva=reserva, fecha=self.hoy - timedelta(days=3))
        vencida = AusenciaTemporal.objects.create(reserva=reserva, fecha=self.hoy - timedelta(days=14))
        # El recupero se reservó después del aviso y dentro del plazo de la primera
        AusenciaTemporal.objects.filter(id__in=[recuperada.id, vencida.id]).update(
            fecha_creacion=self.ahora - timedelta(days=30))
        rec = self.suelta(ana, self.clase(self.hoy, hora=19), self.hoy - timedelta(days=18), activa=False)
        Reserva.objects.filter(id=rec.id).update(fecha_reserva=self.ahora - timedelta(days=25))
        Inasistencia.objects.create(reserva=reserva, fecha=self.hoy - timedelta(days=28), registrado_por=self.equipo)

        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('gravity:admin_asistencia_ausencias'), {'periodo': '30'})

        estados = {f['obj'].id: f['estado'][0] for f in r.context['page_obj'] if f['tipo'] == 'avisada'}
        self.assertEqual(estados[recuperada.id], f'Recuperó el {self.hoy - timedelta(days=18):%d/%m}')
        self.assertEqual(estados[vencida.id], 'No recuperó')
        self.assertEqual(estados[pendiente.id], f'Puede recuperar hasta el {self.hoy + timedelta(days=3):%d/%m}')
        self.assertContains(r, 'No vino sin avisar')
        self.assertContains(r, 'Lo marcó Diana')
        self.assertEqual([t['cantidad'] for t in r.context['tipos']], [3, 1])

    def test_periodos_tipo_y_alumno(self):
        ana, bea = self.alumno('Ana'), self.alumno('Bea')
        clase = self.clase(self.hoy)
        fija_ana, fija_bea = self.fija(ana, clase), self.fija(bea, clase)
        futura = AusenciaTemporal.objects.create(reserva=fija_ana, fecha=self.hoy + timedelta(days=7))
        AusenciaTemporal.objects.create(reserva=fija_bea, fecha=self.hoy - timedelta(days=5))
        Inasistencia.objects.create(reserva=fija_ana, fecha=self.hoy - timedelta(days=5))
        self.client.force_login(self.equipo)
        url = reverse('gravity:admin_asistencia_ausencias')

        def ids(**datos):
            return [(f['tipo'], f['obj'].id) for f in self.client.get(url, datos).context['page_obj']]

        self.assertEqual(len(ids()), 2)                              # 7 días por defecto
        self.assertEqual(ids(periodo='proximas'), [('avisada', futura.id)])
        self.assertEqual(len(ids(tipo='sin_aviso')), 1)
        self.assertEqual(len(ids(alumno=ana.id, periodo='90')), 1)
        self.assertEqual(len(ids(buscar='bea')), 1)
        r = self.client.get(url, {'alumno': ana.id})
        self.assertContains(r, 'Faltas de <strong>Ana Test</strong>', html=False)


class BajasRegistradasTests(AsistenciaBase):
    def test_dar_de_baja_deja_registro(self):
        ana = self.alumno('Ana')
        clase = self.clase(self.hoy)
        fija = self.fija(ana, clase)
        recupero = self.suelta(ana, self.clase(self.hoy, hora=19), self.hoy + timedelta(days=7))

        self.assertEqual(dar_de_baja_reservas(ana.reservas_pilates.all()), 2)

        fija.refresh_from_db()
        self.assertFalse(fija.activa)
        self.assertEqual(fija.fecha_modificacion, self.ahora)
        self.assertEqual(NotificacionCancelacion.objects.filter(tipo='permanente').count(), 2)
        # El recupero cancelado ya no se confunde con uno realizado
        self.assertFalse(sueltas_no_canceladas(Reserva.objects.filter(id=recupero.id)).exists())

    def test_eliminar_la_cuenta_registra_las_bajas(self):
        ana = self.alumno('Ana')
        self.fija(ana, self.clase(self.hoy))
        anonimizar_cuenta(ana)
        self.assertEqual(NotificacionCancelacion.objects.filter(reserva__usuario=ana, tipo='permanente').count(), 1)
