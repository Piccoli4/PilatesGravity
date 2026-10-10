"""
SEO del sitio público: títulos, descripciones, indexación, datos estructurados,
robots.txt y sitemap.xml.

Los textos de cada página pública se definen acá (no en los templates) para que
<title>, meta description, Open Graph y Twitter usen siempre el mismo texto.
Las páginas que no figuran en PAGINAS_PUBLICAS se marcan como noindex.
"""
import json

from django.conf import settings
from django.http import HttpResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

NOMBRE_SITIO = 'Pilates Gravity'
TELEFONO = '+54 9 342 511-4448'
EMAIL = 'pilatesgravity@gmail.com'
INSTAGRAM = 'https://www.instagram.com/pilatesgravity/'
WHATSAPP = 'https://wa.me/5493425114448'
OG_IMAGEN = 'img/seo/og-pilates-gravity.jpg'
OG_IMAGEN_ALT = 'Sala de Pilates Gravity con reformers y cadillac, Santa Fe'

SEDES = [
    {
        'id': 'sede-central',
        'nombre': 'Pilates Gravity · Sede Central',
        'calle': 'La Rioja 3044',
        'cp': 'S3000',
        'mapa': 'https://www.google.com/maps/place/La+Rioja+3044,+S3000+Santa+Fe+de+la+Vera+Cruz,+Santa+Fe',
        'foto': 'scroll_world/stills/03_cadillac.webp',
    },
    {
        'id': 'sede-2',
        'nombre': 'Pilates Gravity · Sede 2',
        'calle': '9 de Julio 3698',
        'cp': 'S3002',
        'mapa': 'https://www.google.com/maps/search/?api=1&query=9+de+Julio+3698,+Santa+Fe',
        'foto': 'scroll_world/stills/06_final.webp',
    },
]

DESCRIPCION_GENERAL = (
    'Estudio de Pilates Reformer y Cadillac en Santa Fe Capital, con dos sedes: '
    'La Rioja 3044 y 9 de Julio 3698. Grupos reducidos, instructores certificados '
    'y reservas online.'
)

# url_name → textos de la página. 'prioridad' y 'frecuencia' van al sitemap.
PAGINAS_PUBLICAS = {
    'gravity:home': {
        'titulo': 'Pilates Gravity | Pilates Reformer y Cadillac en Santa Fe',
        'descripcion': DESCRIPCION_GENERAL,
        'prioridad': '1.0', 'frecuencia': 'weekly',
    },
    'gravity:precios_publicos': {
        'titulo': 'Precios y planes de Pilates en Santa Fe | Pilates Gravity',
        'descripcion': (
            'Planes mensuales de Pilates Reformer y Cadillac de 1 a 5 clases por semana. '
            'Mirá el precio por clase y elegí el ritmo que mejor te queda en Pilates Gravity, Santa Fe.'
        ),
        'prioridad': '0.9', 'frecuencia': 'monthly',
    },
    'gravity:clases_disponibles': {
        'titulo': 'Horarios y clases disponibles | Pilates Gravity Santa Fe',
        'descripcion': (
            'Consultá los horarios de Pilates Reformer y Cadillac con lugares libres en nuestras '
            'dos sedes de Santa Fe Capital y reservá tu clase online en un par de minutos.'
        ),
        'prioridad': '0.8', 'frecuencia': 'daily',
    },
    'gravity:conoce_mas': {
        'titulo': 'Conocé el estudio | Pilates Gravity Santa Fe',
        'descripcion': (
            'Conocé Pilates Gravity: nuestro método, el equipo de instructores y lo que dicen '
            'nuestros alumnos. Pilates Reformer y Cadillac en Santa Fe Capital.'
        ),
        'prioridad': '0.7', 'frecuencia': 'monthly',
    },
    'gravity:terminos_condiciones': {
        'titulo': 'Términos y condiciones | Pilates Gravity',
        'descripcion': 'Términos y condiciones de uso del sitio y del sistema de reservas de Pilates Gravity.',
        'prioridad': '0.2', 'frecuencia': 'yearly',
    },
    'gravity:politica_privacidad': {
        'titulo': 'Política de privacidad | Pilates Gravity',
        'descripcion': 'Cómo Pilates Gravity recopila, usa y protege tus datos personales.',
        'prioridad': '0.2', 'frecuencia': 'yearly',
    },
}


def site_url():
    return settings.SITE_URL.rstrip('/')


def _nombre_url(request):
    match = getattr(request, 'resolver_match', None)
    if not match or not match.url_name:
        return ''
    return f'{match.namespace}:{match.url_name}' if match.namespace else match.url_name


def datos_estructurados():
    """Grafo JSON-LD del negocio: organización, sitio web y una ficha por sede."""
    base = site_url()
    org_id = f'{base}/#organizacion'
    sedes = [{
        '@type': 'ExerciseGym',
        '@id': f"{base}/#{s['id']}",
        'name': s['nombre'],
        'description': 'Clases de Pilates Reformer y Cadillac en grupos reducidos.',
        'url': f'{base}/#Contacto',
        'image': base + static(s['foto']),
        'telephone': TELEFONO,
        'email': EMAIL,
        'priceRange': '$$',
        'currenciesAccepted': 'ARS',
        'hasMap': s['mapa'],
        'address': {
            '@type': 'PostalAddress',
            'streetAddress': s['calle'],
            'addressLocality': 'Santa Fe',
            'addressRegion': 'Santa Fe',
            'postalCode': s['cp'],
            'addressCountry': 'AR',
        },
        'parentOrganization': {'@id': org_id},
    } for s in SEDES]
    grafo = {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'Organization',
                '@id': org_id,
                'name': NOMBRE_SITIO,
                'url': f'{base}/',
                'logo': base + static('icons/icon-512x512.png'),
                'image': base + static(OG_IMAGEN),
                'description': DESCRIPCION_GENERAL,
                'email': EMAIL,
                'telephone': TELEFONO,
                'sameAs': [INSTAGRAM],
                'areaServed': {'@type': 'City', 'name': 'Santa Fe de la Vera Cruz'},
                'subOrganization': [{'@id': s['@id']} for s in sedes],
                'contactPoint': {
                    '@type': 'ContactPoint',
                    'contactType': 'customer service',
                    'telephone': TELEFONO,
                    'email': EMAIL,
                    'availableLanguage': 'es',
                    'url': WHATSAPP,
                },
            },
            {
                '@type': 'WebSite',
                '@id': f'{base}/#sitio',
                'name': NOMBRE_SITIO,
                'url': f'{base}/',
                'inLanguage': 'es-AR',
                'publisher': {'@id': org_id},
            },
            *sedes,
        ],
    }
    return json.dumps(grafo, ensure_ascii=False)


def seo(request):
    """Context processor: datos de SEO de la página que se está renderizando."""
    base = site_url()
    pagina = PAGINAS_PUBLICAS.get(_nombre_url(request))
    return {
        'seo': {
            'site_url': base,
            'canonical': base + request.path,
            'indexable': pagina is not None,
            'titulo': pagina['titulo'] if pagina else NOMBRE_SITIO,
            'descripcion': pagina['descripcion'] if pagina else DESCRIPCION_GENERAL,
            'imagen': base + static(OG_IMAGEN),
            'imagen_alt': OG_IMAGEN_ALT,
            'json_ld': datos_estructurados() if pagina else '',
        }
    }


@require_GET
@cache_control(max_age=86400, public=True)
def robots_txt(request):
    lineas = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /admin-panel/',
        'Disallow: /api/',
        '',
        f'Sitemap: {site_url()}/sitemap.xml',
        '',
    ]
    return HttpResponse('\n'.join(lineas), content_type='text/plain; charset=utf-8')


@require_GET
@cache_control(max_age=86400, public=True)
def sitemap_xml(request):
    base = site_url()
    urls = []
    for nombre, pagina in PAGINAS_PUBLICAS.items():
        urls.append(
            '  <url>\n'
            f'    <loc>{base}{reverse(nombre)}</loc>\n'
            f"    <changefreq>{pagina['frecuencia']}</changefreq>\n"
            f"    <priority>{pagina['prioridad']}</priority>\n"
            '  </url>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls)
        + '\n</urlset>\n'
    )
    return HttpResponse(xml, content_type='application/xml; charset=utf-8')
