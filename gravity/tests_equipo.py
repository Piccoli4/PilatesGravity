"""Etapa 8 del panel: Equipo (accesos, horarios, horas hasta hoy y pagos)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.invitacion import enlace_invitacion

from . import horarios as h
from .models import (
    AjusteHorarioProfesora,
    BloqueHorarioProfesora,
    Clase,
    LiquidacionProfesora,
    ValorHoraProfesora,
)

# Lunes 12 de octubre de 2026, 10:00
AHORA = timezone.make_aware(datetime(2026, 10, 12, 10, 0))
SEPTIEMBRE = date(2026, 9, 1)


class EquipoBase(TestCase):
    def setUp(self):
        reloj = mock.patch('django.utils.timezone.now', return_value=AHORA)
        reloj.start()
        self.addCleanup(reloj.stop)
        self.superadmin = User.objects.create_superuser(username='nico', email='nico@test.com', password='clave-123')
        self.profe = User.objects.create_user(username='ana', first_name='Ana', last_name='García',
                                              email='ana@test.com', password='clave-123', is_staff=True)
        # Lunes de 8 a 12 desde septiembre, a $1000 la hora
        self.bloque = BloqueHorarioProfesora.objects.create(
            profesora=self.profe, dia='Lunes', hora_inicio=time(8), hora_fin=time(12),
            sede='sede_principal', vigente_desde=SEPTIEMBRE)
        ValorHoraProfesora.objects.create(profesora=self.profe, valor_hora=Decimal('1000'), vigente_desde=SEPTIEMBRE)
        self.client.force_login(self.superadmin)

    def ficha(self, usuario, **params):
        return self.client.get(reverse('gravity:admin_profesora_detalle', args=[usuario.id]), params)


class HastaHoyTests(EquipoBase):
    def test_el_mes_en_curso_separa_lo_trabajado_de_la_proyeccion(self):
        desde, hasta = h.rango_mes(2026, 10)
        resumen = h.resumen_hasta_hoy(self.profe, desde, hasta)
        # Lunes 5 y 12 ya pasaron (el de hoy cuenta); faltan el 19 y el 26
        self.assertEqual(resumen['horas'], Decimal('8.00'))
        self.assertEqual(resumen['proyeccion_horas'], Decimal('16.00'))
        self.assertTrue(resumen['en_curso'])

        r = self.ficha(self.profe)
        self.assertContains(r, 'Trabajadas hasta hoy')
        self.assertContains(r, 'A fin de mes')
        self.assertContains(r, 'se registra desde el 31/10')

    def test_el_pago_de_un_mes_que_no_termino_no_se_registra(self):
        self.client.post(reverse('gravity:admin_profesora_liquidar', args=[self.profe.id]),
                         {'mes': '2026-10', 'monto_pagado': '8000', 'fecha_pago': '2026-10-12'})
        self.assertFalse(LiquidacionProfesora.objects.exists())

        self.client.post(reverse('gravity:admin_profesora_liquidar', args=[self.profe.id]),
                         {'mes': '2026-09', 'monto_pagado': '16000', 'fecha_pago': '2026-10-05'})
        self.assertTrue(LiquidacionProfesora.objects.filter(mes_año=SEPTIEMBRE).exists())

    def test_la_lista_muestra_hasta_hoy_y_el_pago(self):
        r = self.client.get(reverse('gravity:admin_profesoras_lista'))
        self.assertContains(r, 'Ana García')
        self.assertContains(r, 'Horas hasta hoy')
        self.assertContains(r, 'Mes en curso')
        r = self.client.get(reverse('gravity:admin_profesoras_lista'), {'mes': '2026-09'})
        self.assertContains(r, 'Falta pagar')

    def test_mis_horarios(self):
        self.client.force_login(self.profe)
        r = self.client.get(reverse('gravity:mis_horarios'))
        self.assertContains(r, 'Trabajadas hasta hoy')
        self.assertContains(r, 'Te corresponden')
        self.assertNotContains(r, 'Registrar el pago')


class MesPagadoTests(EquipoBase):
    def test_un_cambio_en_un_mes_pagado_avisa_y_muestra_la_diferencia(self):
        self.client.post(reverse('gravity:admin_profesora_liquidar', args=[self.profe.id]),
                         {'mes': '2026-09', 'monto_pagado': '16000', 'fecha_pago': '2026-10-05'})
        r = self.client.post(reverse('gravity:admin_profesora_horario_agregar', args=[self.profe.id]), {
            'modo': 'fecha', 'origen': 'libre', 'fecha': '2026-09-05',
            'hora_inicio': '10:00', 'hora_fin': '12:00', 'sede': 'sede_principal',
        }, follow=True)
        self.assertContains(r, 'ya está pagado')
        r = self.ficha(self.profe, mes='2026-09')
        self.assertContains(r, 'Después del pago cambió algo')
        self.assertEqual(r.context['diferencia'][1], Decimal('2000.00'))
        self.assertEqual(r.context['meses_pagados'], ['2026-09'])


class TurnosTests(EquipoBase):
    def test_un_turno_puntual_no_se_puede_superponer(self):
        r = self.client.post(reverse('gravity:admin_profesora_horario_agregar', args=[self.profe.id]), {
            'modo': 'fecha', 'origen': 'libre', 'fecha': '2026-10-19',
            'hora_inicio': '11:00', 'hora_fin': '13:00', 'sede': 'sede_principal',
        }, follow=True)
        self.assertFalse(AjusteHorarioProfesora.objects.exists())
        self.assertContains(r, 'se superpone')

    def test_otro_horario_tampoco(self):
        AjusteHorarioProfesora.objects.create(profesora=self.profe, fecha=date(2026, 10, 19), tipo='extra',
                                              hora_inicio=time(14), hora_fin=time(15), sede='sede_2')
        self.client.post(reverse('gravity:admin_profesora_dia_editar', args=[self.profe.id]), {
            'accion': 'otro_horario', 'fecha': '2026-10-19', 'bloque_id': self.bloque.id,
            'hora_inicio': '13:00', 'hora_fin': '15:00',
        })
        self.assertFalse(AjusteHorarioProfesora.objects.filter(tipo='reemplazo').exists())
        # Correr el mismo turno dentro de su horario sí se puede
        self.client.post(reverse('gravity:admin_profesora_dia_editar', args=[self.profe.id]), {
            'accion': 'otro_horario', 'fecha': '2026-10-19', 'bloque_id': self.bloque.id,
            'hora_inicio': '09:00', 'hora_fin': '12:00',
        })
        self.assertTrue(AjusteHorarioProfesora.objects.filter(tipo='reemplazo').exists())

    def test_un_valor_hora_viejo_no_queda_abierto(self):
        ValorHoraProfesora.objects.filter(profesora=self.profe).update(vigente_hasta=date(2026, 9, 30))
        ValorHoraProfesora.objects.create(profesora=self.profe, valor_hora=Decimal('1500'), vigente_desde=date(2026, 10, 1))
        self.client.post(reverse('gravity:admin_profesora_valor_hora', args=[self.profe.id]),
                         {'valor_hora': '1200', 'vigente_desde': '2026-09-15'})
        nuevo = ValorHoraProfesora.objects.get(valor_hora=Decimal('1200'))
        self.assertEqual(nuevo.vigente_hasta, date(2026, 9, 30))
        self.assertEqual(ValorHoraProfesora.objects.get(valor_hora=Decimal('1000')).vigente_hasta, date(2026, 9, 14))

    def test_el_turno_sigue_a_su_clase(self):
        clase = Clase.objects.create(tipo='Reformer', dia='Miércoles', horario=time(18), direccion='sede_2', cupo_maximo=5)
        bloque = BloqueHorarioProfesora.objects.create(
            profesora=self.profe, dia='Miércoles', hora_inicio=time(18), hora_fin=time(19, 30),
            sede='sede_2', clase=clase, vigente_desde=SEPTIEMBRE)
        clase.dia, clase.horario, clase.direccion = 'Jueves', time(19), 'sede_principal'
        clase.save()

        movidas = h.mover_turnos_de_la_clase(clase)

        self.assertEqual(movidas, [self.profe])
        bloque.refresh_from_db()
        self.assertEqual(bloque.vigente_hasta, date(2026, 10, 11))
        nuevo = BloqueHorarioProfesora.objects.get(clase=clase, vigente_hasta__isnull=True)
        self.assertEqual((nuevo.dia, nuevo.hora_inicio, nuevo.hora_fin, nuevo.sede, nuevo.vigente_desde),
                         ('Jueves', time(19), time(20, 30), 'sede_principal', date(2026, 10, 12)))
        # Septiembre no cambia: los miércoles se siguen contando
        self.assertEqual(h.resumen_profesora(self.profe, date(2026, 9, 2), date(2026, 9, 2))['horas'], Decimal('1.50'))

    def test_si_ya_se_dio_hoy_el_turno_nuevo_empieza_manana(self):
        clase = Clase.objects.create(tipo='Reformer', dia='Lunes', horario=time(7), direccion='sede_2', cupo_maximo=5)
        bloque = BloqueHorarioProfesora.objects.create(
            profesora=self.profe, dia='Lunes', hora_inicio=time(7), hora_fin=time(8),
            sede='sede_2', clase=clase, vigente_desde=SEPTIEMBRE)
        clase.horario = time(13)
        clase.save()
        h.mover_turnos_de_la_clase(clase)
        bloque.refresh_from_db()
        self.assertEqual(bloque.vigente_hasta, date(2026, 10, 12))
        self.assertEqual(BloqueHorarioProfesora.objects.get(clase=clase, vigente_hasta__isnull=True).vigente_desde,
                         date(2026, 10, 13))

    def test_editar_la_clase_avisa_y_mueve_el_turno(self):
        clase = Clase.objects.create(tipo='Reformer', dia='Miércoles', horario=time(18), direccion='sede_2', cupo_maximo=5)
        BloqueHorarioProfesora.objects.create(
            profesora=self.profe, dia='Miércoles', hora_inicio=time(18), hora_fin=time(19),
            sede='sede_2', clase=clase, vigente_desde=SEPTIEMBRE)
        url = reverse('gravity:admin_clase_editar', args=[clase.id])
        self.assertContains(self.client.get(url), 'La da Ana García')
        r = self.client.post(url, {'tipo': 'Reformer', 'direccion': 'sede_2', 'dia': 'Miércoles',
                                   'horario': '19:00', 'cupo_maximo': 5, 'activa': 'on'}, follow=True)
        self.assertContains(r, 'El turno de Ana García pasó al horario nuevo')
        self.assertTrue(BloqueHorarioProfesora.objects.filter(clase=clase, hora_inicio=time(19)).exists())
        # En la ficha, el turno coincide con la clase
        self.assertNotContains(self.ficha(self.profe, ver='horario'), 'La clase ahora es')


class AltasTests(EquipoBase):
    def test_sumar_a_alguien_nuevo_con_invitacion(self):
        r = self.client.post(reverse('gravity:admin_equipo_sumar'), {
            'modo': 'nueva', 'nombre': 'maría josé', 'apellido': 'Pérez', 'email': 'MJ@test.com', 'telefono': '',
        })
        nueva = User.objects.get(email='mj@test.com')
        self.assertEqual(nueva.username, 'mariajoseperez')
        self.assertEqual((nueva.first_name, nueva.last_name), ('María José', 'Pérez'))
        self.assertTrue(nueva.is_staff)
        self.assertFalse(nueva.is_superuser)
        self.assertFalse(nueva.has_usable_password())
        self.assertRedirects(r, reverse('gravity:admin_profesora_detalle', args=[nueva.id]) + '?ver=horario',
                             fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('equipo', mail.outbox[0].body)

        # Al crear su contraseña entra directo al panel
        self.client.logout()
        enlace = enlace_invitacion(nueva).split('/accounts/')[1]
        r = self.client.post('/accounts/' + enlace, {'new_password1': 'Pilates-2026!', 'new_password2': 'Pilates-2026!'})
        self.assertRedirects(r, reverse('gravity:admin_dashboard'), fetch_redirect_response=False)

    def test_sin_email_se_muestra_la_contrasena_una_vez(self):
        self.client.post(reverse('gravity:admin_equipo_sumar'), {
            'modo': 'nueva', 'nombre': 'Lola', 'apellido': 'Díaz', 'email': '', 'telefono': '342 511 4448',
        })
        nueva = User.objects.get(username='loladiaz')
        self.assertTrue(nueva.has_usable_password())
        r = self.ficha(nueva, ver='acceso')
        self.assertContains(r, 'gravity-')
        self.assertNotContains(self.ficha(nueva, ver='acceso'), 'gravity-')

    def test_email_repetido(self):
        r = self.client.post(reverse('gravity:admin_equipo_sumar'), {
            'modo': 'nueva', 'nombre': 'Otra', 'apellido': 'Ana', 'email': 'ana@test.com',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ese email ya lo usa')
        self.assertFalse(User.objects.filter(first_name='Otra').exists())

    def test_sumar_una_alumna_que_ya_tiene_cuenta(self):
        alumna = User.objects.create_user(username='bea', first_name='Bea', last_name='Luna', password='clave-123')
        r = self.client.get(reverse('gravity:admin_equipo_sumar'), {'buscar': 'luna'})
        self.assertContains(r, 'Bea Luna')
        self.client.post(reverse('gravity:admin_equipo_sumar'), {'modo': 'alumna', 'usuario_id': alumna.id})
        alumna.refresh_from_db()
        self.assertTrue(alumna.is_staff)
        self.assertTrue(alumna.has_usable_password())

    def test_editar_datos(self):
        self.client.post(reverse('gravity:admin_equipo_datos', args=[self.profe.id]), {
            'nombre': 'Ana Laura', 'apellido': 'García', 'email': 'ana.laura@test.com', 'telefono': '3425114448',
        })
        self.profe.refresh_from_db()
        self.assertEqual((self.profe.first_name, self.profe.email), ('Ana Laura', 'ana.laura@test.com'))
        self.assertEqual(self.profe.profile.telefono, '3425114448')


class QuitarAccesoTests(EquipoBase):
    def quitar(self, como):
        return self.client.post(reverse('gravity:admin_eliminar_admin_restringido', args=[self.profe.id]),
                                {'como': como, 'ultimo_dia': '2026-10-12'})

    def test_desactivar_conserva_el_historial(self):
        self.quitar('desactivar')
        self.profe.refresh_from_db()
        self.bloque.refresh_from_db()
        self.assertFalse(self.profe.is_active)
        self.assertTrue(self.profe.is_staff)                     # no pasa a figurar en Alumnos
        self.assertEqual(self.bloque.vigente_hasta, date(2026, 10, 12))
        self.assertEqual(self.ficha(self.profe).status_code, 200)
        self.assertNotContains(self.client.get(reverse('gravity:admin_usuarios_lista'), {'filtro': 'desactivados'}), 'Ana García')

        # El mes pasado sigue sumando su costo; la lista por defecto la muestra porque trabajó
        r = self.client.get(reverse('gravity:admin_profesoras_lista'), {'mes': '2026-09'})
        self.assertContains(r, 'Ana García')
        self.assertContains(r, 'Cuenta desactivada')
        self.assertEqual(r.context['total_monto'], Decimal('16000.00'))

        # Devolverle el acceso
        self.client.post(reverse('gravity:admin_equipo_reactivar', args=[self.profe.id]))
        self.profe.refresh_from_db()
        self.assertTrue(self.profe.is_active and self.profe.is_staff)

    def test_que_siga_como_alumna(self):
        self.quitar('alumna')
        self.profe.refresh_from_db()
        self.assertTrue(self.profe.is_active)
        self.assertFalse(self.profe.is_staff)
        self.assertEqual(self.ficha(self.profe).status_code, 200)
        r = self.client.get(reverse('gravity:admin_profesoras_lista'), {'estado': 'sin_acceso'})
        self.assertContains(r, 'Sigue como alumna')
        # Ya no entra al panel
        self.client.force_login(self.profe)
        self.assertEqual(self.client.get(reverse('gravity:admin_dashboard')).status_code, 302)

    def test_sin_horas_en_el_periodo_no_aparece_en_la_lista(self):
        self.quitar('desactivar')
        r = self.client.get(reverse('gravity:admin_profesoras_lista'), {'mes': '2026-12'})
        self.assertEqual(r.context['filas'], [])
        self.assertEqual(r.context['cantidad_sin_acceso'], 1)


class PermisosYDireccionesTests(EquipoBase):
    def test_el_equipo_no_entra(self):
        self.client.force_login(self.profe)
        for url in (reverse('gravity:admin_profesoras_lista'), reverse('gravity:admin_equipo_sumar'),
                    reverse('gravity:admin_profesora_detalle', args=[self.profe.id])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_un_alumno_comun_no_tiene_ficha_de_equipo(self):
        alumno = User.objects.create_user(username='beto', password='clave-123')
        self.assertEqual(self.ficha(alumno).status_code, 404)
        self.assertEqual(self.ficha(self.superadmin).status_code, 404)

    def test_direcciones_viejas(self):
        r = self.client.get('/admin-panel/profesoras/?mes=2026-09')
        self.assertRedirects(r, reverse('gravity:admin_profesoras_lista') + '?mes=2026-09', fetch_redirect_response=False)
        r = self.client.get(reverse('gravity:admin_gestionar_admins'))
        self.assertRedirects(r, reverse('gravity:admin_profesoras_lista'), fetch_redirect_response=False)

    def test_el_menu_tiene_equipo(self):
        r = self.client.get(reverse('gravity:admin_profesoras_lista'))
        self.assertEqual(r.context['panel']['titulo'], 'Equipo')

    def test_el_panel_ya_no_carga_tailwind(self):
        r = self.client.get(reverse('gravity:admin_dashboard'))
        self.assertNotContains(r, 'tailwind-output.css')
        self.assertNotContains(r, 'admin_legacy.css')
        self.assertNotContains(r, 'pn-legacy')
