"""
Alumnos desde el panel: alta (con invitación por email o contraseña inicial),
nombre de usuario prolijo, notas internas, enlace de WhatsApp y desactivar.
"""
import logging
import re
import secrets
import unicodedata

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from accounts.invitacion import enviar_invitacion, tiene_invitacion_pendiente
from accounts.models import UserProfile

from .models import CancelacionAdmin, EstadoPagoCliente, PlanUsuario, Reserva

logger = logging.getLogger(__name__)

MOTIVO_BAJA = 'Baja del estudio'


def generar_username(nombre, apellido):
    """"María José Pérez" -> "mariajoseperez" (sin acentos ni espacios), único."""
    texto = unicodedata.normalize('NFKD', f'{nombre}{apellido}').encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]', '', texto.lower())[:30] or 'alumno'
    username, n = base, 1
    while User.objects.filter(username__iexact=username).exists():
        n += 1
        username = f'{base}{n}'
    return username


def generar_clave_inicial():
    """Contraseña fácil de dictar por WhatsApp: "gravity-4821"."""
    return f'gravity-{secrets.randbelow(9000) + 1000}'


def crear_alumno(datos, admin):
    """
    Crea la cuenta. Con email: queda sin contraseña y se manda la invitación.
    Sin email: se genera una contraseña inicial (se muestra una sola vez).
    Devuelve (usuario, clave_inicial o None, invitación enviada).
    """
    clave = None if datos['email'] else generar_clave_inicial()
    with transaction.atomic():
        usuario = User.objects.create_user(
            username=generar_username(datos['nombre'], datos['apellido']),
            email=datos['email'],
            first_name=datos['nombre'],
            last_name=datos['apellido'],
            password=clave,  # None -> sin contraseña usable hasta que use la invitación
        )
        perfil, _ = UserProfile.objects.get_or_create(user=usuario)
        perfil.telefono = datos['telefono']
        if datos.get('notas'):
            perfil.notas_admin = formatear_nota(datos['notas'], admin)
        perfil.save()
    invitado = enviar_invitacion(usuario) if datos['email'] else False
    return usuario, clave, invitado


def formatear_nota(texto, admin):
    """Una nota con fecha y hora de Argentina y quién la escribió."""
    cuando = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')
    return f'[{cuando} - {admin.get_full_name() or admin.username}]: {texto.strip()}'


def agregar_nota(perfil, texto, admin):
    nueva = formatear_nota(texto, admin)
    perfil.notas_admin = f'{perfil.notas_admin}\n\n{nueva}' if perfil.notas_admin else nueva
    perfil.save(update_fields=['notas_admin', 'fecha_actualizacion'])
    return nueva


_NOTA = re.compile(r'^\[(?P<cuando>[^\]]+?) - (?P<quien>[^\]]+)\]:\s*(?P<texto>.*)$', re.S)


def notas_lista(perfil):
    """Las notas guardadas como texto, separadas, de la más nueva a la más vieja."""
    notas = []
    for bloque in (perfil.notas_admin or '').split('\n\n'):
        bloque = bloque.strip()
        if not bloque:
            continue
        m = _NOTA.match(bloque)
        notas.append(m.groupdict() if m else {'cuando': '', 'quien': '', 'texto': bloque})
    return list(reversed(notas))


def whatsapp_url(telefono):
    """wa.me con el número en formato internacional (si es argentino sin código, le agrega 549)."""
    digitos = re.sub(r'\D', '', telefono or '')
    if not digitos:
        return ''
    if not (telefono or '').strip().startswith('+') and not digitos.startswith('54'):
        digitos = '549' + digitos.lstrip('0')
    return f'https://wa.me/{digitos}'


def estado_cuenta(usuario):
    """(clave, texto, tono) del estado de la cuenta."""
    if not usuario.is_active:
        if usuario.username.startswith('eliminado-'):
            return ('eliminado', 'Cuenta eliminada', 'muted')
        return ('desactivado', 'Desactivado', 'warn')
    if tiene_invitacion_pendiente(usuario):
        return ('invitado', 'Invitación pendiente', 'info')
    return ('activo', 'Activo', 'ok')


def que_se_cancela(usuario):
    """Lo que se pierde al desactivar: reservas activas y planes."""
    return {
        'fijas': list(usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=True).select_related('clase')),
        'sueltas': list(usuario.reservas_pilates.filter(activa=True, fecha_unica__isnull=False).select_related('clase')),
        'planes': list(PlanUsuario.objects.filter(usuario=usuario, activo=True).select_related('plan')),
    }


def desactivar_alumno(usuario, admin, avisar=True):
    """
    Desactiva la cuenta: cancela sus reservas (queda registrado como cancelación del
    estudio) y sus planes. Las deudas y los pagos se conservan.
    """
    from .email_service import enviar_email_cancelacion_reserva

    with transaction.atomic():
        reservas = list(Reserva.objects.filter(usuario=usuario, activa=True).select_related('clase'))
        for reserva in reservas:
            reserva.activa = False
            reserva.save()
            CancelacionAdmin.objects.create(
                reserva=reserva, admin_user=admin, motivo=MOTIVO_BAJA,
                motivo_detalle='Se desactivó la cuenta del alumno.', email_enviado=False,
            )
        PlanUsuario.objects.filter(usuario=usuario, activo=True).update(activo=False)
        EstadoPagoCliente.objects.filter(usuario=usuario).update(plan_actual=None, activo=False)
        usuario.is_active = False
        usuario.save(update_fields=['is_active'])

        if avisar and usuario.email and reservas:
            def _avisar():
                try:
                    enviar_email_cancelacion_reserva(
                        reserva=reservas[0], motivo=MOTIVO_BAJA,
                        motivo_detalle='Tu cuenta en Pilates Gravity quedó desactivada y se liberaron tus horarios. '
                                       'Si querés volver, escribinos por WhatsApp.',
                        ofrecer_reemplazo=False, ofrecer_otras_sedes=False,
                    )
                except Exception as e:
                    logger.error(f'No se pudo avisar la baja a {usuario.email}: {e}')
            transaction.on_commit(_avisar)
    return len(reservas)
