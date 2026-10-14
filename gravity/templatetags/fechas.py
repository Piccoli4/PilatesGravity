"""Filtros para nombrar fechas de clases dentro de una frase."""
from django import template
from django.utils import timezone

register = template.Library()

DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


@register.filter
def dia_frase(fecha, preposicion=''):
    """
    Nombra una fecha para usarla en medio de una oración.

        hoy                 -> hoy            | "de": de hoy
        mañana              -> mañana         | "de": de mañana
        otro día            -> el jueves 15 de octubre | "de": del jueves 15 de octubre
    """
    if not fecha:
        return ''
    dias = (fecha - timezone.localdate()).days
    if dias in (0, 1):
        texto = 'hoy' if dias == 0 else 'mañana'
        return f'de {texto}' if preposicion == 'de' else texto
    texto = f'{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}'
    return f'del {texto}' if preposicion == 'de' else f'el {texto}'
