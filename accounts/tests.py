from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gravity.models import AusenciaTemporal, Clase, PlanPago, PlanUsuario, Reserva

from .mi_espacio import DIAS as DIAS_SEMANA, _cuando, _proxima_fecha
from .models import UserProfile


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alumna', password='clave-de-prueba-123', first_name='Lucía')
        self.url = reverse('accounts:logout')

    def test_get_con_sesion_muestra_confirmacion(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lucía')
        self.assertContains(response, 'data-loading-text="Cerrando sesión..."')
        # Sigue con la sesión abierta hasta confirmar
        self.assertIn('_auth_user_id', self.client.session)

    def test_get_sin_sesion_ofrece_iniciar_sesion(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ya saliste')
        self.assertContains(response, reverse('accounts:login'))

    def test_post_cierra_sesion_y_vuelve_a_la_home_con_aviso(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('gravity:home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        mensajes = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn('Cerraste sesión. ¡Te esperamos en la próxima clase!', mensajes)


class LoginLoaderTests(TestCase):
    def test_login_incluye_velo_de_carga(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'id="authLoader"')
        self.assertContains(response, 'data-loading-text="Ingresando..."')


def crear_clase(**kwargs):
    datos = dict(tipo='Reformer', dia='Lunes', horario=time(18), direccion='sede_2', cupo_maximo=9)
    datos.update(kwargs)
    return Clase.objects.create(**datos)


class ProximaFechaTests(TestCase):
    """Lunes 12/10/2026 a las 10:00."""

    def setUp(self):
        self.ahora = timezone.make_aware(datetime(2026, 10, 12, 10, 0))
        self.hoy = self.ahora.date()
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')

    def test_clase_de_hoy_que_todavia_no_empezo(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(horario=time(18)))
        self.assertEqual(_proxima_fecha(reserva, self.ahora), self.hoy)

    def test_clase_de_hoy_que_ya_paso_va_a_la_semana_siguiente(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(horario=time(9)))
        self.assertEqual(_proxima_fecha(reserva, self.ahora), self.hoy + timedelta(days=7))

    def test_saltea_las_ausencias_avisadas(self):
        reserva = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia='Miércoles'))
        AusenciaTemporal.objects.create(reserva=reserva, fecha=self.hoy + timedelta(days=2))
        self.assertEqual(_proxima_fecha(reserva, self.ahora), self.hoy + timedelta(days=9))

    def test_recupero_de_fecha_unica(self):
        manana = self.hoy + timedelta(days=1)
        reserva = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia='Martes'),
                                         fecha_unica=manana, es_recupero=True)
        self.assertEqual(_proxima_fecha(reserva, self.ahora), manana)
        ayer = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia='Domingo'),
                                      fecha_unica=self.hoy - timedelta(days=1), es_recupero=True)
        self.assertIsNone(_proxima_fecha(ayer, self.ahora))

    def test_textos_de_cuando(self):
        self.assertEqual(_cuando(self.hoy, self.hoy), 'Hoy')
        self.assertEqual(_cuando(self.hoy + timedelta(days=1), self.hoy), 'Mañana')
        self.assertEqual(_cuando(self.hoy + timedelta(days=3), self.hoy), 'Jueves 15/10')


class MiEspacioViewTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123',
                                               first_name='Lucía', last_name='Gómez')
        self.client.force_login(self.alumna)
        self.url = reverse('accounts:profile')

    def test_sin_plan_ni_reservas(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Hola, Lucía')
        self.assertContains(response, 'Todavía no tenés clases reservadas')
        self.assertContains(response, 'Todavía no tenés un plan activo')
        self.assertContains(response, 'Completá tu ficha')

    def test_con_plan_y_reservas(self):
        hoy = timezone.localtime(timezone.now()).date()
        plan = PlanPago.objects.create(nombre='2 clases semanales', clases_por_semana=2,
                                       precio_mensual=Decimal('61000'))
        PlanUsuario.objects.create(usuario=self.alumna, plan=plan, fecha_inicio=hoy,
                                   fecha_fin=hoy + timedelta(days=30), renovacion_automatica=False)
        Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia='Jueves', direccion='sede_principal'))

        response = self.client.get(self.url)
        self.assertNotContains(response, 'Todavía no tenés un plan activo')
        self.assertContains(response, '2 clases semanales')
        self.assertContains(response, '1 de 2')
        self.assertContains(response, 'Podés sumar 1 horario más')
        self.assertContains(response, 'Sede Central')
        self.assertContains(response, 'Avisar que no voy')

    def test_datos_invalidos_dejan_el_formulario_abierto(self):
        response = self.client.post(self.url, {'first_name': '', 'last_name': 'Gómez',
                                               'email': 'no-es-email', 'telefono': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'me-data is-editing')

    def test_guardar_datos(self):
        response = self.client.post(self.url, {'first_name': 'Lu', 'last_name': 'Gómez',
                                               'email': 'lu@example.com', 'telefono': ''})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.alumna.refresh_from_db()
        self.assertEqual(self.alumna.first_name, 'Lu')


class MiFichaTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123', first_name='Lucía')
        self.client.force_login(self.alumna)
        self.url = reverse('accounts:profile_complete')
        self.datos = {
            'telefono': '3425114448', 'fecha_nacimiento': '1990-03-14',
            'nivel_experiencia': 'intermedio', 'tiene_lesiones': 'False',
            'descripcion_lesiones': '', 'acepta_recordatorios': 'on', 'sede_preferida': 'sede_2',
        }

    def test_primera_vez_es_un_recorrido_sin_respuesta_de_salud_marcada(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'is-wizard')
        self.assertContains(response, 'Omitir por ahora')
        self.assertNotContains(response, 'value="False"\n                                   checked')
        self.assertNotContains(response, 'fecha_primera_clase')

    def test_salud_es_obligatoria(self):
        datos = dict(self.datos)
        del datos['tiene_lesiones']
        response = self.client.post(self.url, datos)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paso_inicial'], 2)
        self.assertContains(response, 'Elegí una opción para continuar.')

    def test_lesion_sin_descripcion_vuelve_al_paso_2(self):
        datos = dict(self.datos, tiene_lesiones='True')
        response = self.client.post(self.url, datos)
        self.assertEqual(response.context['paso_inicial'], 2)
        self.assertEqual(response.content.decode().count('Contanos brevemente qué lesión o condición tenés.</small>'), 2)

    def test_completar_la_ficha(self):
        response = self.client.post(self.url, self.datos)
        self.assertRedirects(response, reverse('accounts:profile'), fetch_redirect_response=False)
        perfil = self.alumna.profile
        perfil.refresh_from_db()
        self.assertTrue(perfil.perfil_completado)
        self.assertEqual(perfil.sede_preferida, 'sede_2')
        self.assertEqual(perfil.nivel_experiencia, 'intermedio')
        self.assertFalse(perfil.tiene_lesiones)

    def test_responder_no_borra_una_descripcion_vieja(self):
        perfil = self.alumna.profile
        perfil.tiene_lesiones = True
        perfil.descripcion_lesiones = 'Rodilla'
        perfil.save()
        self.client.post(self.url, self.datos)
        perfil.refresh_from_db()
        self.assertEqual(perfil.descripcion_lesiones, '')

    def test_edicion_es_una_sola_pagina(self):
        perfil = self.alumna.profile
        perfil.perfil_completado = True
        perfil.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, 'id="fichaPasos"')
        self.assertEqual(response.context['form']['tiene_lesiones'].value(), False)
        self.assertContains(response, 'Guardar cambios')
        self.assertContains(response, 'Volver a Mi espacio')

    def test_guardar_con_foto_existente_y_quitarla(self):
        perfil = self.alumna.profile
        UserProfile.objects.filter(pk=perfil.pk).update(avatar='avatars/no-existe.jpg', perfil_completado=True)
        # Guardar sin subir otra foto no revisa la existente
        response = self.client.post(self.url, self.datos)
        self.assertEqual(response.status_code, 302)
        perfil.refresh_from_db()
        self.assertEqual(perfil.avatar.name, 'avatars/no-existe.jpg')
        # Quitarla
        self.client.post(self.url, dict(self.datos, quitar_avatar='on'))
        perfil.refresh_from_db()
        self.assertFalse(perfil.avatar)


class MisReservasTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123', first_name='Lucía')
        self.client.force_login(self.alumna)
        self.url = reverse('accounts:mis_reservas')
        self.hoy = timezone.localtime(timezone.now()).date()
        # Clase fija dentro de 3 días a las 18 (siempre a más de 3 h; los domingos no hay clases)
        self.offset = 3 if (self.hoy + timedelta(days=3)).weekday() != 6 else 4
        dia = DIAS_SEMANA[(self.hoy + timedelta(days=self.offset)).weekday()]
        self.fija = Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia=dia, horario=time(18)))

    def test_agenda_muestra_dos_semanas_del_horario_fijo(self):
        response = self.client.get(self.url)
        agenda = response.context['r']['agenda']
        fechas = [a['fecha'] for a in agenda]
        self.assertEqual(fechas, [self.hoy + timedelta(days=self.offset), self.hoy + timedelta(days=self.offset + 7)])
        self.assertTrue(agenda[0]['es_proxima'])
        self.assertFalse(agenda[1]['es_proxima'])
        self.assertContains(response, 'Avisar que no voy')
        self.assertContains(response, 'Dar de baja')

    def test_avisar_ausencia_vuelve_a_mis_reservas(self):
        response = self.client.post(
            reverse('gravity:cancelar_reserva', args=[self.fija.numero_reserva]),
            {'confirmar_cancelacion': 'confirmar', 'tipo_cancelacion': 'temporal', 'next': self.url},
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        ausencia = AusenciaTemporal.objects.get(reserva=self.fija)
        self.assertEqual(ausencia.fecha, self.hoy + timedelta(days=self.offset))

        response = self.client.get(self.url)
        self.assertTrue(response.context['r']['agenda'][0]['ausencia'])
        self.assertContains(response, 'Avisaste que no venís')
        self.assertContains(response, 'Listo, avisamos que no venís')

        # Deshacer el aviso también vuelve a Mis reservas
        response = self.client.post(reverse('gravity:cancelar_ausencia', args=[ausencia.id]), {'next': self.url})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(AusenciaTemporal.objects.filter(reserva=self.fija).exists())

    def test_next_externo_se_ignora(self):
        response = self.client.post(
            reverse('gravity:cancelar_reserva', args=[self.fija.numero_reserva]),
            {'confirmar_cancelacion': 'no', 'next': 'https://otro-sitio.com/'},
        )
        self.assertRedirects(response, reverse('gravity:detalle_reserva', args=[self.fija.numero_reserva]),
                             fetch_redirect_response=False)

    def test_historial_con_estados(self):
        self.client.post(
            reverse('gravity:cancelar_reserva', args=[self.fija.numero_reserva]),
            {'confirmar_cancelacion': 'confirmar', 'tipo_cancelacion': 'permanente', 'next': self.url},
        )
        Reserva.objects.create(usuario=self.alumna, clase=crear_clase(dia='Martes'), es_recupero=True,
                               fecha_unica=self.hoy - timedelta(days=2), activa=False)
        response = self.client.get(self.url)
        estados = {h['estado'] for h in response.context['r']['historial']}
        self.assertEqual(estados, {'Dada de baja', 'Recupero realizado'})
        self.assertContains(response, 'Todavía no tenés un horario fijo')


class PuedeModificarseFechaUnicaTests(TestCase):
    def test_recupero_usa_su_fecha_real(self):
        alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        ahora = timezone.localtime(timezone.now())
        # Un recupero dentro de 2 días: se puede cancelar aunque su día de la semana sea hoy y ya haya pasado la hora
        dia_hoy = DIAS_SEMANA[ahora.weekday()]
        clase = crear_clase(dia=dia_hoy, horario=time(0, 30))
        reserva = Reserva.objects.create(usuario=alumna, clase=clase, es_recupero=True,
                                         fecha_unica=ahora.date() + timedelta(days=7))
        self.assertTrue(reserva.puede_modificarse()[0])
        Reserva.objects.filter(pk=reserva.pk).update(fecha_unica=ahora.date() - timedelta(days=1))
        reserva.refresh_from_db()
        self.assertEqual(reserva.puede_modificarse(), (False, 'La clase ya pasó.'))


class AvisoReservaConfirmadaTests(TestCase):
    """El aviso de Mis reservas llega con forma distinta según de dónde vino la reserva."""

    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.client.force_login(self.alumna)

    def ver_con(self, aviso):
        session = self.client.session
        session['reserva_exitosa'] = aviso
        session.save()
        return self.client.get(reverse('accounts:mis_reservas'))

    def test_las_tres_formas(self):
        base = {'clase': 'Pilates Reformer', 'dia': 'Lunes', 'horario': '09:00', 'sede': 'La Rioja 3044'}
        response = self.ver_con(dict(base, tipo='recupero', fecha='19/10/2026'))
        self.assertContains(response, '¡Recupero confirmado!')
        self.assertContains(response, 'Lunes 19/10/2026')
        response = self.ver_con(dict(base, tipo='temporal', fecha_unica='20/10/2026'))
        self.assertContains(response, 'Lunes 20/10/2026')
        response = self.ver_con(dict(base, tipo='recurrente', fecha_unica=None))
        self.assertContains(response, 'Todos los lunes')


class CambiarPasswordTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='alumna', password='clave-actual-123')
        self.client.force_login(self.alumna)
        self.url = reverse('accounts:cambiar_password')

    def enviar(self, actual='clave-actual-123', nueva='otra-clave-456', repetida=None):
        return self.client.post(self.url, {'password_actual': actual, 'password_nueva': nueva,
                                           'password_confirmacion': nueva if repetida is None else repetida})

    def test_cambia_y_mantiene_la_sesion(self):
        response = self.enviar()
        self.assertRedirects(response, reverse('accounts:profile'), fetch_redirect_response=False)
        self.alumna.refresh_from_db()
        self.assertTrue(self.alumna.check_password('otra-clave-456'))
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)

    def test_errores_sin_volver_a_escribir_las_contrasenas(self):
        response = self.enviar(actual='mal', nueva='otra-clave-456', repetida='distinta-789')
        self.assertContains(response, 'La contraseña actual no es correcta.')
        self.assertContains(response, 'Las contraseñas no coinciden.')
        self.assertNotContains(response, 'otra-clave-456')
        self.assertNotContains(response, 'distinta-789')

    def test_mismas_reglas_que_al_registrarse(self):
        for invalida in ('12345678', 'abc', 'password'):  # solo números, corta, muy común
            response = self.enviar(nueva=invalida)
            self.assertIn('password_nueva', response.context['form'].errors, invalida)
            self.assertFalse(User.objects.get(pk=self.alumna.pk).check_password(invalida))
        response = self.enviar(nueva='clave-actual-123')
        self.assertContains(response, 'tiene que ser distinta de la actual')


class EliminarCuentaTests(TestCase):
    def setUp(self):
        from gravity.models import Clase, PlanPago, PlanUsuario
        self.alumna = User.objects.create_user(username='lucia', password='clave-actual-123', first_name='Lucía',
                                               last_name='Gómez', email='lucia@example.com')
        perfil = self.alumna.profile
        perfil.telefono = '3425114448'
        perfil.tiene_lesiones = True
        perfil.descripcion_lesiones = 'Rodilla'
        perfil.save()
        self.plan = PlanPago.objects.create(nombre='2 clases semanales', clases_por_semana=2, precio_mensual=Decimal('61000'))
        hoy = timezone.localtime(timezone.now()).date()
        PlanUsuario.objects.create(usuario=self.alumna, plan=self.plan, fecha_inicio=hoy - timedelta(days=5),
                                   fecha_fin=hoy + timedelta(days=20))
        Reserva.objects.create(usuario=self.alumna, clase=Clase.objects.create(
            tipo='Reformer', dia='Lunes', horario=time(18), direccion='sede_2', cupo_maximo=5))
        self.client.force_login(self.alumna)
        self.url = reverse('accounts:eliminar_cuenta')
        self.deuda('pagado', '0')

    def deuda(self, estado, pendiente):
        from gravity.models import DeudaMensual
        hoy = timezone.localtime(timezone.now()).date()
        # La cuota del mes la genera sola la señal al crear la reserva; acá se fija su estado
        DeudaMensual.objects.update_or_create(
            usuario=self.alumna, mes_año=hoy.replace(day=1),
            defaults=dict(plan_aplicado=self.plan, monto_original=Decimal('61000'),
                          monto_pendiente=Decimal(pendiente), estado=estado, fecha_vencimiento=hoy.replace(day=10)),
        )

    def test_anonimiza_y_conserva_los_pagos(self):
        from gravity.models import DeudaMensual, PlanUsuario
        response = self.client.post(self.url, {'password': 'clave-actual-123', 'confirmacion': 'eliminar'})
        self.assertRedirects(response, reverse('gravity:home'), fetch_redirect_response=False)

        usuario = User.objects.get(pk=self.alumna.pk)
        self.assertEqual(usuario.get_full_name(), 'Alumno eliminado (Lucía Gómez)')
        self.assertEqual((usuario.email, usuario.username, usuario.is_active), ('', f'eliminado-{usuario.pk}', False))
        self.assertFalse(usuario.has_usable_password())
        perfil = UserProfile.objects.get(user=usuario)
        self.assertEqual((perfil.telefono, perfil.tiene_lesiones, perfil.descripcion_lesiones), (None, False, ''))
        self.assertFalse(usuario.reservas_pilates.filter(activa=True).exists())
        self.assertFalse(PlanUsuario.objects.filter(usuario=usuario, activo=True).exists())
        self.assertTrue(DeudaMensual.objects.filter(usuario=usuario).exists())  # los pagos quedan
        # La sesión se cerró y no se puede volver a entrar
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(self.client.login(username='lucia', password='clave-actual-123'))

    def test_manda_el_email_de_despedida(self):
        from django.core import mail
        self.client.post(self.url, {'password': 'clave-actual-123', 'confirmacion': 'eliminar'})
        despedidas = [m for m in mail.outbox if m.to == ['lucia@example.com'] and 'pronto' in m.body]
        self.assertEqual(len(despedidas), 1)

    def test_pide_contrasena_y_la_palabra(self):
        self.client.post(self.url, {'password': 'mal', 'confirmacion': 'ELIMINAR'})
        self.client.post(self.url, {'password': 'clave-actual-123', 'confirmacion': 'borrar'})
        self.assertTrue(User.objects.get(pk=self.alumna.pk).is_active)

    def test_bloqueada_con_deuda(self):
        self.deuda('vencido', '61000')
        response = self.client.get(self.url)
        self.assertContains(response, 'Antes tenés que regularizar $61.000 pendientes')
        self.client.post(self.url, {'password': 'clave-actual-123', 'confirmacion': 'ELIMINAR'})
        self.assertTrue(User.objects.get(pk=self.alumna.pk).is_active)

    def test_bloqueada_para_el_equipo(self):
        User.objects.filter(pk=self.alumna.pk).update(is_staff=True)
        response = self.client.get(self.url)
        self.assertContains(response, 'Las cuentas del equipo no se eliminan desde acá')
        self.client.post(self.url, {'password': 'clave-actual-123', 'confirmacion': 'ELIMINAR'})
        self.assertTrue(User.objects.get(pk=self.alumna.pk).is_active)


class RecuperarPasswordTests(TestCase):
    def setUp(self):
        self.alumna = User.objects.create_user(username='Lucia.G', password='clave-vieja-123', first_name='Lucía',
                                               email='lucia@example.com')

    def test_email_desconocido_no_se_revela(self):
        from django.core import mail
        response = self.client.post(reverse('accounts:password_reset'), {'email': 'nadie@example.com'})
        self.assertRedirects(response, reverse('accounts:password_reset_done'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        response = self.client.get(reverse('accounts:password_reset_done'))
        self.assertContains(response, 'Si <strong>nadie@example.com</strong> está registrado')

    def test_circuito_completo(self):
        import re
        from django.core import mail
        self.client.post(reverse('accounts:password_reset'), {'email': 'lucia@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, 'Creá tu nueva contraseña · Pilates Gravity')
        html = email.alternatives[0][0]
        self.assertIn('Lucia.G', html)
        self.assertIn('Crear nueva contraseña', html)

        enlace = re.search(r'https?://[^/\s]+(/accounts/password-reset-confirm/[^\s"<]+)', email.body).group(1)
        response = self.client.get(enlace, follow=True)
        self.assertContains(response, 'Elegí tu nueva contraseña')
        self.assertContains(response, 'Lucia.G')
        url_form = response.redirect_chain[-1][0]

        # Error: no vuelve a escribir las contraseñas en la página
        response = self.client.post(url_form, {'new_password1': 'nueva-clave-789', 'new_password2': 'otra-cosa-000'})
        self.assertContains(response, 'Las contraseñas no coinciden.')
        self.assertNotContains(response, 'nueva-clave-789')

        response = self.client.post(url_form, {'new_password1': 'nueva-clave-789', 'new_password2': 'nueva-clave-789'})
        self.assertRedirects(response, reverse('accounts:password_reset_complete'), fetch_redirect_response=False)
        self.assertTrue(self.client.login(username='Lucia.G', password='nueva-clave-789'))

    def test_enlace_vencido(self):
        response = self.client.get(reverse('accounts:password_reset_confirm', args=['MQ', 'token-invalido']))
        self.assertContains(response, 'Este enlace ya no sirve')


class ComentariosDePlantillaTests(TestCase):
    """Los comentarios {# #} de Django son de una sola línea: si ocupan varias, se ven en la página."""

    def test_no_hay_comentarios_multilinea(self):
        import pathlib
        import re
        from django.conf import settings
        raiz = pathlib.Path(settings.BASE_DIR)
        malos = [
            str(p.relative_to(raiz))
            for p in raiz.rglob('*.html')
            if 'node_modules' not in p.parts and '.claude' not in p.parts
            and any('\n' in m for m in re.findall(r'\{#(.*?)#\}', p.read_text(encoding='utf-8', errors='ignore'), flags=re.S))
        ]
        self.assertEqual(malos, [], 'Usá {% comment %} para comentarios de varias líneas')

    def test_mis_reservas_no_muestra_el_comentario(self):
        alumna = User.objects.create_user(username='alumna', password='clave-de-prueba-123')
        self.client.force_login(alumna)
        self.assertNotContains(self.client.get(reverse('accounts:mis_reservas')), 'Modal para confirmar acciones')
