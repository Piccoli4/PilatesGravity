"""
Altas y bajas del equipo (las personas que usan el panel sin ser superadmin).

- Sumar a alguien nuevo: como un alumno nuevo, con invitación por email para que
  elija su contraseña (sin email, contraseña inicial que se muestra una sola vez).
- Sumar a una alumna que ya tiene cuenta: pasa a tener acceso al panel.
- Quitar el acceso: se cierran sus turnos desde el día elegido y, según se elija, se
  desactiva la cuenta (sigue siendo del equipo, sin acceso) o sigue como alumna. En
  los dos casos su historial de horas y pagos queda en Equipo y se puede reactivar.
"""
from django.contrib.auth.models import User
from django.db import transaction

from accounts.invitacion import enviar_invitacion
from accounts.models import UserProfile

from .alumnos_admin import generar_clave_inicial, generar_username
from .horarios import cerrar_turnos


def crear_integrante(datos):
    """Devuelve (usuario, clave inicial o None, invitación enviada)."""
    clave = None if datos['email'] else generar_clave_inicial()
    with transaction.atomic():
        usuario = User.objects.create_user(
            username=generar_username(datos['nombre'], datos['apellido']),
            email=datos['email'],
            first_name=datos['nombre'],
            last_name=datos['apellido'],
            password=clave,  # None -> sin contraseña usable hasta que use la invitación
            is_staff=True,
        )
        perfil, _ = UserProfile.objects.get_or_create(user=usuario)
        perfil.telefono = datos.get('telefono') or perfil.telefono
        perfil.save()
    invitado = enviar_invitacion(usuario) if datos['email'] else False
    return usuario, clave, invitado


def alumnas_para_sumar(buscar, limite=8):
    """Cuentas de alumnos activas que coinciden con la búsqueda (para sumarlas al equipo)."""
    if len(buscar) < 2:
        return []
    from django.db.models import Q

    qs = User.objects.filter(is_active=True, is_staff=False, is_superuser=False).exclude(
        username__startswith='eliminado-')
    for palabra in buscar.split():
        qs = qs.filter(Q(first_name__icontains=palabra) | Q(last_name__icontains=palabra)
                       | Q(username__icontains=palabra) | Q(email__icontains=palabra))
    return list(qs.select_related('profile').order_by('first_name', 'last_name')[:limite])


def sumar_alumna(usuario):
    usuario.is_staff = True
    usuario.save(update_fields=['is_staff'])


@transaction.atomic
def quitar_acceso(usuario, ultimo_dia, como='desactivar'):
    """
    `como`: 'desactivar' (la cuenta no entra más) o 'alumna' (pierde solo el panel).
    Devuelve cuántos turnos se cerraron.
    """
    cerrados = cerrar_turnos(usuario, ultimo_dia)
    if como == 'alumna':
        usuario.is_staff = False
        usuario.is_active = True
    else:
        usuario.is_staff = True  # sigue siendo del equipo, sin acceso: no aparece en Alumnos
        usuario.is_active = False
    usuario.save(update_fields=['is_staff', 'is_active'])
    return cerrados


def devolver_acceso(usuario):
    usuario.is_staff = True
    usuario.is_active = True
    usuario.save(update_fields=['is_staff', 'is_active'])
