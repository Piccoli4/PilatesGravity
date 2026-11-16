"""
Avisos push programados para los alumnos que los activaron en su celular. Los corre
el comando `enviar_recordatorios_push` cada pocos minutos; cada uno sale una sola vez.

Recordatorio de clase:
- ANTICIPACION antes de la clase (4 horas: una hora antes del límite para avisar
  que no va, que es de 3 horas).
- Si eso cae de madrugada (antes de HORA_MINIMA), se manda la noche anterior a las
  HORA_VISPERA, para no despertar a nadie.
- No se manda si el alumno avisó que no va, ni si reservó la clase después del
  momento del recordatorio (ya la tiene presente).

Recupero por vencer: cuando faltan DIAS_AVISO_RECUPERO días o menos para que venza
una clase que el alumno todavía no recuperó.

Cumpleaños: el día del cumpleaños.

Estos dos últimos salen recién a partir de HORA_AVISOS_DEL_DIA.
"""
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from .models import AusenciaTemporal, AvisoPushEnviado, Clase, RecordatorioPush, Reserva
from .push import enviar_push_usuario, push_configurado
from .recuperos import EstadoRecuperos

ANTICIPACION = timedelta(hours=4)
HORA_MINIMA = time(8, 0)
HORA_VISPERA = time(20, 30)
DIAS_AVISO_RECUPERO = 2
HORA_AVISOS_DEL_DIA = time(10, 0)

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


# ------------------------------------------------------------------------------
# Recordatorio de clase
# ------------------------------------------------------------------------------

def inicio_clase(clase, fecha):
    return timezone.make_aware(datetime.combine(fecha, clase.horario))


def momento_recordatorio(inicio):
    """Desde cuándo corresponde mandar el recordatorio de una clase que empieza en `inicio`."""
    momento = timezone.localtime(inicio - ANTICIPACION)
    if momento.time() < HORA_MINIMA:
        vispera = timezone.localtime(inicio).date() - timedelta(days=1)
        return timezone.make_aware(datetime.combine(vispera, HORA_VISPERA))
    return momento


def texto_recordatorio(clase, fecha, ahora):
    """(título, cuerpo) del aviso."""
    cuando = 'Hoy' if fecha == timezone.localdate(ahora) else 'Mañana'
    return (
        f'{cuando} tenés {clase.get_nombre_display()} a las {clase.horario:%H:%M}',
        f'{clase.get_direccion_corta()}. Si no podés ir, avisá desde Mis reservas hasta 3 horas antes.',
    )


def _reservas_para(clases, fecha):
    """Reservas con las que alguien viene a esas clases en esa fecha y tiene los avisos activados."""
    con_avisos = dict(
        activa=True, usuario__is_active=True, usuario__suscripciones_push__isnull=False,
    )
    ausentes = AusenciaTemporal.objects.filter(reserva__clase__in=clases, fecha=fecha).values('reserva_id')
    fijas = Reserva.objects.filter(clase__in=clases, fecha_unica__isnull=True, **con_avisos).exclude(id__in=ausentes)
    sueltas = Reserva.objects.filter(clase__in=clases, fecha_unica=fecha, **con_avisos)
    return (fijas | sueltas).distinct().select_related('usuario', 'clase')


def recordatorios_pendientes(ahora=None):
    """Lista de (reserva, fecha) a los que les toca el recordatorio ahora y todavía no se mandó."""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    pendientes = []
    # Hoy y mañana: el recordatorio más anticipado es el de la noche anterior
    for fecha in (hoy, hoy + timedelta(days=1)):
        clases = []
        for clase in Clase.objects.filter(activa=True, dia=DIAS[fecha.weekday()]):
            inicio = inicio_clase(clase, fecha)
            if ahora < inicio and ahora >= momento_recordatorio(inicio):
                clases.append(clase)
        if not clases:
            continue
        ya_enviados = set(
            RecordatorioPush.objects.filter(fecha=fecha, reserva__clase__in=clases).values_list('reserva_id', flat=True)
        )
        for reserva in _reservas_para(clases, fecha):
            if reserva.id in ya_enviados:
                continue
            if reserva.fecha_reserva > momento_recordatorio(inicio_clase(reserva.clase, fecha)):
                continue
            pendientes.append((reserva, fecha))
    return pendientes


def enviar_recordatorios(ahora=None, simular=False):
    """Manda los recordatorios que tocan. Devuelve la lista de (reserva, fecha) enviados."""
    ahora = ahora or timezone.now()
    if not push_configurado():
        return []
    enviados = []
    for reserva, fecha in recordatorios_pendientes(ahora):
        if simular:
            enviados.append((reserva, fecha))
            continue
        titulo, cuerpo = texto_recordatorio(reserva.clase, fecha, ahora)
        llegaron = enviar_push_usuario(
            reserva.usuario, 'recordatorio', titulo, cuerpo,
            url=reverse('accounts:mis_reservas'),
            etiqueta=f'recordatorio-{reserva.pk}-{fecha:%Y%m%d}',
            esperar=True,
        )
        # Si no salió (sin conexión con Google/Apple), se reintenta en la próxima corrida
        if llegaron:
            RecordatorioPush.objects.get_or_create(reserva=reserva, fecha=fecha)
            enviados.append((reserva, fecha))
    return enviados


# ------------------------------------------------------------------------------
# Recupero por vencer y cumpleaños (una vez, a partir de HORA_AVISOS_DEL_DIA)
# ------------------------------------------------------------------------------

def _con_avisos():
    return User.objects.filter(is_active=True, suscripciones_push__isnull=False).distinct()


def _mandar_una_vez(usuario, clave, tipo, titulo, cuerpo, url, simular):
    """Manda un aviso programado si todavía no salió. Devuelve True si salió (o saldría)."""
    if AvisoPushEnviado.objects.filter(usuario=usuario, clave=clave).exists():
        return False
    if simular:
        return True
    if not enviar_push_usuario(usuario, tipo, titulo, cuerpo, url=url, etiqueta=clave, esperar=True):
        return False
    AvisoPushEnviado.objects.get_or_create(usuario=usuario, clave=clave)
    return True


def enviar_avisos_recupero(ahora=None, simular=False):
    """Avisa a quien tiene una clase para recuperar que vence en DIAS_AVISO_RECUPERO días o menos."""
    ahora = timezone.localtime(ahora or timezone.now())
    if not push_configurado() or ahora.time() < HORA_AVISOS_DEL_DIA:
        return []
    hoy = ahora.date()
    # El plazo vence 6 días después de la ausencia
    desde, hasta = hoy - timedelta(days=6), hoy - timedelta(days=6 - DIAS_AVISO_RECUPERO)
    usuarios = _con_avisos().filter(
        reservas_pilates__ausencias_temporales__fecha__range=(desde, hasta),
    )
    enviados = []
    for usuario in usuarios:
        for ausencia in EstadoRecuperos(usuario, ahora).pendientes:
            dias = (ausencia.fecha_limite_recupero - hoy).days
            if not 0 <= dias <= DIAS_AVISO_RECUPERO:
                continue
            if dias == 0:
                titulo = 'Hoy es el último día para recuperar tu clase'
            elif dias == 1:
                titulo = 'Te queda 1 día para recuperar tu clase'
            else:
                titulo = f'Te quedan {dias} días para recuperar tu clase'
            clase = ausencia.reserva.clase
            cuerpo = (f'La de {clase.get_nombre_display()} del {ausencia.fecha:%d/%m}. '
                      f'Reservá tu recupero antes de que se venza.')
            if _mandar_una_vez(usuario, f'recupero-{ausencia.pk}', 'recupero', titulo, cuerpo,
                               reverse('gravity:reservar_recupero'), simular):
                enviados.append((usuario, ausencia))
    return enviados


def enviar_saludos_cumpleanios(ahora=None, simular=False):
    """Saluda por push a quien cumple años hoy."""
    ahora = timezone.localtime(ahora or timezone.now())
    if not push_configurado() or ahora.time() < HORA_AVISOS_DEL_DIA:
        return []
    hoy = ahora.date()
    cumplen = _con_avisos().filter(
        profile__fecha_nacimiento__month=hoy.month, profile__fecha_nacimiento__day=hoy.day,
    )
    enviados = []
    for usuario in cumplen:
        nombre = usuario.first_name or usuario.username
        if _mandar_una_vez(usuario, f'cumple-{hoy.year}', 'cumple', f'¡Feliz cumpleaños, {nombre}!',
                           'Todo el equipo de Pilates Gravity te desea un gran día.',
                           reverse('accounts:profile'), simular):
            enviados.append(usuario)
    return enviados
