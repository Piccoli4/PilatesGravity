"""Página /links/ para la bio de redes."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LinksTests(TestCase):
    def test_sin_sesion(self):
        response = self.client.get(reverse('gravity:links'))
        self.assertContains(response, 'Reservar clase')
        self.assertContains(response, reverse('gravity:clases_disponibles'))
        self.assertContains(response, reverse('gravity:precios_publicos'))
        self.assertContains(response, 'Ingresar')
        self.assertContains(response, 'Sede Central')
        self.assertContains(response, '9 de Julio 3696')
        self.assertContains(response, 'wa.me/5493425114448?text=')
        self.assertNotContains(response, 'Sede Norte')
        self.assertContains(response, 'noindex')

    def test_con_sesion_muestra_mi_espacio(self):
        alumna = User.objects.create_user(username='lucia', password='clave-de-prueba-123', first_name='Lucía')
        self.client.force_login(alumna)
        response = self.client.get(reverse('gravity:links'))
        self.assertContains(response, 'Mi espacio')
        self.assertContains(response, 'Hola, Lucía')
        self.assertContains(response, reverse('accounts:profile'))
