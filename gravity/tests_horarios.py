"""
Tests de horarios y liquidación de profesoras.

Cubren el cálculo de horas y montos (incluido el respeto del historial cuando
cambia el horario o el valor hora) y el acceso a las pantallas del panel.
"""

from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import horarios as h
from .models import (
    AjusteHorarioProfesora,
    BloqueHorarioProfesora,
    LiquidacionProfesora,
    ValorHoraProfesora,
)

SEPTIEMBRE = date(2026, 9, 1)


class BaseHorariosTest(TestCase):
    """Una profesora con horario de lunes y miércoles, y valor hora cargado."""

    def setUp(self):
        self.superadmin = User.objects.create_user(
            username='nico', password='clave-de-prueba',
            is_staff=True, is_superuser=True,
        )
        self.profesora = User.objects.create_user(
            username='profe', first_name='Ana', last_name='García',
            password='clave-de-prueba', is_staff=True, is_superuser=False,
        )

        BloqueHorarioProfesora.objects.create(
            profesora=self.profesora, dia='Lunes',
            hora_inicio=time(8), hora_fin=time(12),
            sede='sede_principal', vigente_desde=SEPTIEMBRE,
        )
        self.bloque_miercoles = BloqueHorarioProfesora.objects.create(
            profesora=self.profesora, dia='Miércoles',
            hora_inicio=time(16), hora_fin=time(20),
            sede='sede_2', vigente_desde=SEPTIEMBRE,
        )
        ValorHoraProfesora.objects.create(
            profesora=self.profesora, valor_hora=Decimal('1000'),
            vigente_desde=SEPTIEMBRE,
        )

    def resumen_septiembre(self):
        desde, hasta = h.rango_mes(2026, 9)
        return h.resumen_profesora(self.profesora, desde, hasta)


class CalculoHorasTest(BaseHorariosTest):

    def test_horas_y_monto_del_mes(self):
        # Septiembre 2026 tiene 4 lunes y 5 miércoles, de 4 horas cada uno.
        resumen = self.resumen_septiembre()
        self.assertEqual(resumen['horas'], Decimal('36.00'))
        self.assertEqual(resumen['monto'], Decimal('36000.00'))

    def test_horas_semanales_y_de_un_dia(self):
        self.assertEqual(h.horas_semanales(self.profesora, date(2026, 9, 15)), Decimal('8.00'))

        lunes = h.resumen_profesora(self.profesora, date(2026, 9, 7), date(2026, 9, 7))
        self.assertEqual(lunes['horas'], Decimal('4.00'))

        martes = h.resumen_profesora(self.profesora, date(2026, 9, 8), date(2026, 9, 8))
        self.assertEqual(martes['horas'], Decimal('0.00'))

    def test_semana_va_de_lunes_a_domingo(self):
        desde, hasta = h.rango_semana(date(2026, 9, 9))
        self.assertEqual((desde, hasta), (date(2026, 9, 7), date(2026, 9, 13)))
        self.assertEqual(h.resumen_profesora(self.profesora, desde, hasta)['horas'], Decimal('8.00'))

    def test_ausencia_descuenta_el_dia_completo(self):
        AjusteHorarioProfesora.objects.create(
            profesora=self.profesora, fecha=date(2026, 9, 7), tipo='ausencia',
        )
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('32.00'))

    def test_turno_extra_suma_horas(self):
        AjusteHorarioProfesora.objects.create(
            profesora=self.profesora, fecha=date(2026, 9, 5), tipo='extra',
            hora_inicio=time(10), hora_fin=time(12), sede='sede_principal',
        )
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('38.00'))

    def test_reemplazo_pisa_el_horario_habitual(self):
        AjusteHorarioProfesora.objects.create(
            profesora=self.profesora, fecha=date(2026, 9, 9), tipo='reemplazo',
            hora_inicio=time(16), hora_fin=time(18), sede='sede_2',
        )
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('34.00'))

    def test_horas_separadas_por_sede(self):
        por_sede = {s['sede']: s['horas'] for s in self.resumen_septiembre()['por_sede']}
        self.assertEqual(por_sede['sede_principal'], Decimal('16.00'))
        self.assertEqual(por_sede['sede_2'], Decimal('20.00'))

    def test_cambiar_el_horario_no_altera_los_meses_anteriores(self):
        # Desde el 16/9 los miércoles pasan a ser de 2 horas.
        self.bloque_miercoles.vigente_hasta = date(2026, 9, 15)
        self.bloque_miercoles.save()
        BloqueHorarioProfesora.objects.create(
            profesora=self.profesora, dia='Miércoles',
            hora_inicio=time(16), hora_fin=time(18),
            sede='sede_2', vigente_desde=date(2026, 9, 16),
        )

        # Miércoles 2 y 9 con 4 horas, 16, 23 y 30 con 2, más 4 lunes de 4 horas.
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('30.00'))

        desde, hasta = h.rango_mes(2026, 8)
        self.assertEqual(h.resumen_profesora(self.profesora, desde, hasta)['horas'], Decimal('0.00'))

    def test_cada_mes_usa_el_valor_hora_que_regia(self):
        ValorHoraProfesora.objects.filter(profesora=self.profesora).update(
            vigente_hasta=date(2026, 9, 30)
        )
        ValorHoraProfesora.objects.create(
            profesora=self.profesora, valor_hora=Decimal('2000'),
            vigente_desde=date(2026, 10, 1),
        )

        self.assertEqual(self.resumen_septiembre()['monto'], Decimal('36000.00'))

        desde, hasta = h.rango_mes(2026, 10)
        octubre = h.resumen_profesora(self.profesora, desde, hasta)
        self.assertEqual(octubre['horas'], Decimal('32.00'))
        self.assertEqual(octubre['monto'], Decimal('64000.00'))

    def test_sin_valor_hora_el_monto_es_cero_y_queda_avisado(self):
        ValorHoraProfesora.objects.all().delete()
        resumen = self.resumen_septiembre()
        self.assertEqual(resumen['monto'], Decimal('0.00'))
        self.assertTrue(resumen['sin_valor_hora'])

    def test_total_del_estudio(self):
        otra = User.objects.create_user(
            username='profe2', password='clave-de-prueba', is_staff=True,
        )
        BloqueHorarioProfesora.objects.create(
            profesora=otra, dia='Martes', hora_inicio=time(9), hora_fin=time(11),
            sede='sede_principal', vigente_desde=SEPTIEMBRE,
        )
        ValorHoraProfesora.objects.create(
            profesora=otra, valor_hora=Decimal('500'), vigente_desde=SEPTIEMBRE,
        )

        desde, hasta = h.rango_mes(2026, 9)
        general = h.resumen_general(desde, hasta)

        # 36 horas de una y 5 martes de 2 horas de la otra.
        self.assertEqual(general['total_horas'], Decimal('46.00'))
        self.assertEqual(general['total_monto'], Decimal('41000.00'))

    def test_los_superadmins_no_figuran_como_profesoras(self):
        usernames = [p.username for p in h.profesoras_activas()]
        self.assertIn('profe', usernames)
        self.assertNotIn('nico', usernames)


class AccesoPantallasTest(BaseHorariosTest):

    def test_la_profesora_no_entra_al_panel_de_superadmin(self):
        self.client.force_login(self.profesora)
        respuesta = self.client.get(reverse('gravity:admin_profesoras_lista'))
        self.assertEqual(respuesta.status_code, 302)

    def test_un_cliente_no_entra_a_mis_horarios(self):
        cliente = User.objects.create_user(username='alumna', password='clave-de-prueba')
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse('gravity:mis_horarios'))
        self.assertEqual(respuesta.status_code, 302)

    def test_el_superadmin_ve_el_listado_y_la_ficha(self):
        self.client.force_login(self.superadmin)

        listado = self.client.get(reverse('gravity:admin_profesoras_lista'), {'mes': '2026-09'})
        self.assertEqual(listado.status_code, 200)
        self.assertContains(listado, 'Ana García')

        ficha = self.client.get(
            reverse('gravity:admin_profesora_detalle', args=[self.profesora.id]),
            {'mes': '2026-09'},
        )
        self.assertEqual(ficha.status_code, 200)
        self.assertContains(ficha, '36 h')

    def test_el_listado_acepta_los_distintos_periodos(self):
        self.client.force_login(self.superadmin)
        url = reverse('gravity:admin_profesoras_lista')

        for parametros in (
            {'periodo': 'dia', 'fecha': '2026-09-07'},
            {'periodo': 'semana', 'fecha': '2026-09-09'},
            {'periodo': 'mes', 'mes': '2026-09'},
            {'periodo': 'personalizado', 'desde': '2026-09-01', 'hasta': '2026-09-15'},
            {'periodo': 'cualquier-cosa', 'mes': 'no-es-un-mes'},
        ):
            with self.subTest(parametros=parametros):
                self.assertEqual(self.client.get(url, parametros).status_code, 200)

    def test_la_profesora_ve_sus_horarios(self):
        self.client.force_login(self.profesora)
        respuesta = self.client.get(reverse('gravity:mis_horarios'), {'mes': '2026-09'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Mis Horarios')
        self.assertContains(respuesta, '36 h')


class GestionDesdeElPanelTest(BaseHorariosTest):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.superadmin)

    def test_agregar_un_turno_al_horario(self):
        self.client.post(
            reverse('gravity:admin_profesora_horario_agregar', args=[self.profesora.id]),
            {
                'dia': 'Viernes', 'hora_inicio': '09:00', 'hora_fin': '13:00',
                'sede': 'sede_principal', 'vigente_desde': '2026-09-01',
            },
        )
        self.assertTrue(
            BloqueHorarioProfesora.objects.filter(profesora=self.profesora, dia='Viernes').exists()
        )

    def test_no_se_pueden_superponer_dos_turnos_del_mismo_dia(self):
        respuesta = self.client.post(
            reverse('gravity:admin_profesora_horario_agregar', args=[self.profesora.id]),
            {
                'dia': 'Lunes', 'hora_inicio': '11:00', 'hora_fin': '13:00',
                'sede': 'sede_principal', 'vigente_desde': '2026-09-01',
            },
            follow=True,
        )
        self.assertEqual(
            BloqueHorarioProfesora.objects.filter(profesora=self.profesora, dia='Lunes').count(), 1
        )
        self.assertContains(respuesta, 'se superpone')

    def test_no_se_acepta_un_turno_que_termina_antes_de_empezar(self):
        self.client.post(
            reverse('gravity:admin_profesora_horario_agregar', args=[self.profesora.id]),
            {
                'dia': 'Jueves', 'hora_inicio': '15:00', 'hora_fin': '12:00',
                'sede': 'sede_2', 'vigente_desde': '2026-09-01',
            },
        )
        self.assertFalse(
            BloqueHorarioProfesora.objects.filter(profesora=self.profesora, dia='Jueves').exists()
        )

    def test_dar_de_baja_un_turno_lo_cierra_sin_borrarlo(self):
        bloque = BloqueHorarioProfesora.objects.get(profesora=self.profesora, dia='Lunes')
        self.client.post(
            reverse('gravity:admin_profesora_horario_eliminar', args=[self.profesora.id, bloque.id]),
            {'ultimo_dia': '2026-09-15'},
        )
        bloque.refresh_from_db()
        self.assertEqual(bloque.vigente_hasta, date(2026, 9, 15))

    def test_un_turno_que_nunca_rigio_se_borra(self):
        bloque = BloqueHorarioProfesora.objects.create(
            profesora=self.profesora, dia='Jueves', hora_inicio=time(9), hora_fin=time(10),
            sede='sede_2', vigente_desde=date(2026, 10, 1),
        )
        self.client.post(
            reverse('gravity:admin_profesora_horario_eliminar', args=[self.profesora.id, bloque.id]),
            {'ultimo_dia': '2026-09-15'},
        )
        self.assertFalse(BloqueHorarioProfesora.objects.filter(id=bloque.id).exists())

    def test_cargar_un_valor_hora_cierra_el_anterior(self):
        self.client.post(
            reverse('gravity:admin_profesora_valor_hora', args=[self.profesora.id]),
            {'valor_hora': '1500', 'vigente_desde': '2026-10-01', 'observaciones': 'Aumento'},
        )
        anterior = ValorHoraProfesora.objects.get(valor_hora=Decimal('1000'))
        nuevo = ValorHoraProfesora.objects.get(valor_hora=Decimal('1500'))

        self.assertEqual(anterior.vigente_hasta, date(2026, 9, 30))
        self.assertIsNone(nuevo.vigente_hasta)

    def test_no_se_acepta_un_valor_hora_negativo(self):
        self.client.post(
            reverse('gravity:admin_profesora_valor_hora', args=[self.profesora.id]),
            {'valor_hora': '-500', 'vigente_desde': '2026-10-01'},
        )
        self.assertEqual(ValorHoraProfesora.objects.filter(profesora=self.profesora).count(), 1)

    def test_cargar_y_eliminar_un_ajuste(self):
        self.client.post(
            reverse('gravity:admin_profesora_ajuste_crear', args=[self.profesora.id]),
            {'fecha': '2026-09-07', 'tipo': 'ausencia', 'motivo': 'Franco'},
        )
        ajuste = AjusteHorarioProfesora.objects.get(profesora=self.profesora)
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('32.00'))

        self.client.post(
            reverse('gravity:admin_profesora_ajuste_eliminar', args=[self.profesora.id, ajuste.id])
        )
        self.assertEqual(self.resumen_septiembre()['horas'], Decimal('36.00'))

    def test_un_ajuste_con_horario_incompleto_se_rechaza(self):
        self.client.post(
            reverse('gravity:admin_profesora_ajuste_crear', args=[self.profesora.id]),
            {'fecha': '2026-09-05', 'tipo': 'extra', 'sede': 'sede_principal'},
        )
        self.assertFalse(AjusteHorarioProfesora.objects.exists())

    def test_registrar_el_pago_del_mes(self):
        self.client.post(
            reverse('gravity:admin_profesora_liquidar', args=[self.profesora.id]),
            {'mes': '2026-09', 'monto_pagado': '36000', 'fecha_pago': '2026-10-05'},
        )
        liquidacion = LiquidacionProfesora.objects.get(profesora=self.profesora)

        self.assertEqual(liquidacion.mes_año, SEPTIEMBRE)
        self.assertEqual(liquidacion.horas_liquidadas, Decimal('36.00'))
        self.assertEqual(liquidacion.monto_calculado, Decimal('36000.00'))
        self.assertEqual(liquidacion.registrado_por, self.superadmin)

    def test_no_se_liquida_dos_veces_el_mismo_mes(self):
        datos = {'mes': '2026-09', 'monto_pagado': '36000', 'fecha_pago': '2026-10-05'}
        url = reverse('gravity:admin_profesora_liquidar', args=[self.profesora.id])
        self.client.post(url, datos)
        self.client.post(url, datos)
        self.assertEqual(LiquidacionProfesora.objects.count(), 1)

    def test_anular_el_pago_deja_el_mes_pendiente(self):
        self.client.post(
            reverse('gravity:admin_profesora_liquidar', args=[self.profesora.id]),
            {'mes': '2026-09', 'monto_pagado': '36000', 'fecha_pago': '2026-10-05'},
        )
        liquidacion = LiquidacionProfesora.objects.get(profesora=self.profesora)

        self.client.post(
            reverse(
                'gravity:admin_profesora_liquidacion_anular',
                args=[self.profesora.id, liquidacion.id],
            )
        )
        self.assertFalse(LiquidacionProfesora.objects.exists())

    def test_una_profesora_no_puede_tocar_los_horarios(self):
        self.client.force_login(self.profesora)
        self.client.post(
            reverse('gravity:admin_profesora_valor_hora', args=[self.profesora.id]),
            {'valor_hora': '99999', 'vigente_desde': '2026-09-01'},
        )
        self.assertFalse(
            ValorHoraProfesora.objects.filter(valor_hora=Decimal('99999')).exists()
        )
