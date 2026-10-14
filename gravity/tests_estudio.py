"""Página "El estudio" (/conoce-mas/)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Testimonio


class ConoceMasTests(TestCase):
    def test_secciones_y_sedes(self):
        response = self.client.get(reverse('gravity:conoce_mas'))
        self.assertContains(response, 'Conocé Pilates Gravity')
        self.assertContains(response, 'Ladder Barrel')
        self.assertContains(response, '9 de Julio 3696')
        self.assertContains(response, 'La Rioja 3044')
        self.assertNotContains(response, 'Lo que cuentan nuestros alumnos')  # sin testimonios no hay sección

    def test_testimonios_con_nombre_e_inicial(self):
        lucia = User.objects.create_user(username='lucia', password='x-clave-123', first_name='Lucía María', last_name='gómez')
        Testimonio.objects.create(usuario=lucia, texto='Me cambió la postura.', aprobado=True)
        ex = User.objects.create_user(username='ex', password='x-clave-123', first_name='Ana', last_name='Ruiz', is_active=False)
        Testimonio.objects.create(usuario=ex, texto='No debería verse.', aprobado=True)
        pendiente = User.objects.create_user(username='pend', password='x-clave-123', first_name='Sol')
        Testimonio.objects.create(usuario=pendiente, texto='Todavía no aprobado.', aprobado=False)

        response = self.client.get(reverse('gravity:conoce_mas'))
        self.assertContains(response, 'Lucía G.')
        self.assertNotContains(response, 'gómez')
        self.assertContains(response, 'Me cambió la postura.')
        self.assertNotContains(response, 'No debería verse.')
        self.assertNotContains(response, 'Todavía no aprobado.')
