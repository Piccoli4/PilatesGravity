from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SITE_URL='https://pilatesgravity.com.ar')
class SeoTests(TestCase):
    def test_home_tiene_metadatos_completos(self):
        html = self.client.get(reverse('gravity:home')).content.decode()
        self.assertIn('<title>Pilates Gravity | Pilates Reformer y Cadillac en Santa Fe</title>', html)
        self.assertIn('<meta name="description"', html)
        self.assertIn('<link rel="canonical" href="https://pilatesgravity.com.ar/">', html)
        self.assertIn('<meta property="og:image" content="https://pilatesgravity.com.ar/static/img/seo/og-pilates-gravity.jpg">', html)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', html)
        self.assertIn('"@type": "ExerciseGym"', html)
        self.assertIn('"@type": "FAQPage"', html)
        self.assertEqual(html.count('<h1'), 1)
        self.assertIn('index, follow', html)

    def test_cada_pagina_publica_tiene_su_titulo(self):
        html = self.client.get(reverse('gravity:precios_publicos')).content.decode()
        self.assertIn('<title>Precios y planes de Pilates en Santa Fe | Pilates Gravity</title>', html)
        self.assertIn('<link rel="canonical" href="https://pilatesgravity.com.ar/precios/">', html)

    def test_descripciones_y_titulos_no_se_cortan(self):
        from gravity.seo import PAGINAS_PUBLICAS
        for nombre, pagina in PAGINAS_PUBLICAS.items():
            self.assertLessEqual(len(pagina['descripcion']), 160, nombre)
            self.assertLessEqual(len(pagina['titulo']), 60, nombre)

    def test_paginas_privadas_no_se_indexan(self):
        html = self.client.get(reverse('accounts:login')).content.decode()
        self.assertIn('<meta name="robots" content="noindex, follow">', html)
        self.assertNotIn('rel="canonical"', html)

    def test_robots_y_sitemap(self):
        robots = self.client.get('/robots.txt')
        self.assertEqual(robots['Content-Type'], 'text/plain; charset=utf-8')
        self.assertIn('Sitemap: https://pilatesgravity.com.ar/sitemap.xml', robots.content.decode())
        self.assertIn('Disallow: /admin-panel/', robots.content.decode())

        sitemap = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('<loc>https://pilatesgravity.com.ar/</loc>', sitemap)
        self.assertIn('<loc>https://pilatesgravity.com.ar/precios/</loc>', sitemap)
        self.assertNotIn('admin-panel', sitemap)
