"""Filtros de formato para las pantallas de administración."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter
def pesos(valor):
    """
    Formatea un monto al estilo argentino y sin decimales.

        61000    -> 61.000
        -2000.4  -> -2.000
    """
    if valor is None or valor == '':
        return '0'

    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return valor

    entero = int(numero.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return '{:,}'.format(entero).replace(',', '.')


@register.filter
def horas(valor):
    """
    Formatea una cantidad de horas sin decimales inútiles.

        8.00  -> 8
        7.50  -> 7,5
        6.25  -> 6,25
    """
    if valor is None or valor == '':
        return '0'

    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return valor

    texto = format(numero.quantize(Decimal('0.01')).normalize(), 'f')
    return texto.replace('.', ',')
