"""
Panel de administración: quién ve qué, el menú y la bandeja de notificaciones.

Hay dos niveles:
- Superadmin (is_superuser, Nico y Cami): todo.
- Equipo (is_staff sin superusuario; son las profesoras): usa clases, reservas,
  alumnos, asistencia y los pagos de cada alumno (ve deudas y saldos para cobrar
  bien). No ve los ingresos del estudio ni configura planes, corrige cuentas,
  cancela planes, resuelve solicitudes o testimonios, ni gestiona el equipo.

El menú y la bandeja salen de acá para que la base del panel y las vistas
usen las mismas reglas.
"""
import logging
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from accounts.models import Testimonio

from .models import (
    NotificacionCancelacion,
    NotificacionCancelacionPlan,
    NotificacionPlanAdicional,
    Reserva,
    SolicitudCambioPlan,
)
from .push import aviso_seguro, clave_publica, enviar_push_equipo

logger = logging.getLogger(__name__)


def es_superadmin(user):
    return bool(user.is_authenticated and user.is_superuser)


def ve_ingresos_estudio(user):
    """Los ingresos del estudio (del mes, facturación, finanzas de reportes) son solo del superadmin."""
    return es_superadmin(user)


def puede_corregir_cuentas(user):
    """Configurar planes, corregir saldos, pagos y cuotas, cambiar o cancelar planes."""
    return es_superadmin(user)


# ------------------------------------------------------------------------------
# Menú
# ------------------------------------------------------------------------------

# Cada sección del panel: qué rutas la marcan como activa (por prefijo del nombre).
_RUTAS = {
    'hoy': ('admin_dashboard',),
    'asistencia': ('admin_asistencia',),
    'clases': ('admin_clase',),
    'reservas': ('admin_reserva',),
    'alumnos': ('admin_usuario',),
    'nuevo_alumno': ('admin_agregar_usuario',),
    'pagos': (
        'admin_pagos_vista', 'admin_pagos_registrar', 'admin_pagos_historial',
        'admin_pagos_configurar', 'admin_pagos_editar', 'admin_ajustar_deuda',
        'admin_generar_deuda', 'admin_corregir_saldo', 'admin_recalcular',
        'admin_pago_', 'admin_eliminar_deuda', 'admin_cancelar_plan',
    ),
    'solicitudes': ('admin_solicitud',),
    'testimonios': ('admin_testimonio',),
    'estadisticas': ('admin_reportes',),
    'historial': ('admin_historial_actividad',),
    'equipo': ('admin_profesora', 'admin_equipo', 'admin_gestionar_admins', 'admin_eliminar_admin'),
    'mis_horarios': ('mis_horarios',),
    'pagos_admin': ('admin_pagos_por_admin',),
}


def seccion_actual(url_name):
    """Clave de la sección del menú a la que pertenece una ruta ('' si ninguna)."""
    if not url_name:
        return ''
    # 'admin_pagos_por_admin' empieza igual que las de Pagos: se revisa primero
    if url_name.startswith('admin_pagos_por_admin'):
        return 'pagos_admin'
    for clave, prefijos in _RUTAS.items():
        if url_name.startswith(prefijos):
            return clave
    return ''


def _item(clave, texto, ruta, icono, actual, badge=0):
    return {
        'clave': clave,
        'texto': texto,
        'url': reverse(f'gravity:{ruta}'),
        'icono': icono,
        'activo': clave == actual,
        'badge': badge,
    }


def menu_panel(user, actual, pendientes):
    """Secciones del menú lateral (y de "Más" en el celular) según el rol."""
    superadmin = es_superadmin(user)

    secciones = [
        {'titulo': '', 'items': [
            _item('hoy', 'Hoy', 'admin_dashboard', 'casa', actual),
            _item('asistencia', 'Asistencia', 'admin_asistencia', 'asistencia', actual),
        ]},
        {'titulo': 'Gestión', 'items': [
            _item('clases', 'Clases', 'admin_clases_lista', 'calendario', actual),
            _item('reservas', 'Reservas', 'admin_reservas_lista', 'reserva', actual),
            _item('alumnos', 'Alumnos', 'admin_usuarios_lista', 'alumnos', actual),
            _item('nuevo_alumno', 'Nuevo alumno', 'admin_agregar_usuario', 'alumno_nuevo', actual),
            _item('pagos', 'Pagos', 'admin_pagos_vista_principal', 'pagos', actual),
        ]},
    ]

    if superadmin:
        secciones.append({'titulo': 'Para resolver', 'items': [
            _item('solicitudes', 'Solicitudes de plan', 'admin_solicitudes_plan_lista',
                  'solicitud', actual, pendientes['solicitudes']),
            _item('testimonios', 'Testimonios', 'admin_testimonios_lista',
                  'testimonio', actual, pendientes['testimonios']),
        ]})

    secciones.append({'titulo': 'Estudio', 'items': [
        _item('estadisticas', 'Estadísticas', 'admin_reportes', 'estadisticas', actual),
        _item('historial', 'Actividad', 'admin_historial_actividad', 'historial', actual),
    ]})

    if superadmin:
        equipo = [
            _item('equipo', 'Equipo', 'admin_profesoras_lista', 'reloj', actual),
            _item('pagos_admin', 'Cobros por admin', 'admin_pagos_por_admin', 'torta', actual),
        ]
    else:
        equipo = [_item('mis_horarios', 'Mis horarios', 'mis_horarios', 'reloj', actual)]
    secciones.append({'titulo': 'Equipo', 'items': equipo})

    return secciones


# Accesos fijos de la barra inferior en el celular (el resto va en "Más")
ACCESOS_CELULAR = ('hoy', 'asistencia', 'alumnos')


# ------------------------------------------------------------------------------
# Bandeja de notificaciones
# ------------------------------------------------------------------------------

def _nombre(usuario):
    return usuario.get_full_name() or usuario.username


def _hace(fecha, ahora):
    return 'hace ' + timesince(fecha, ahora, depth=1)


def _url_alumno(usuario):
    if usuario.is_staff:
        return ''
    return reverse('gravity:admin_usuario_detalle', args=[usuario.id])


def _clase_corta(clase):
    return f'{clase.get_nombre_display()} · {clase.dia} {clase.horario:%H:%M} · {clase.get_direccion_corta()}'


def texto_cancelacion(n):
    """
    Cómo se cuenta una NotificacionCancelacion: (título, tipo, ícono).
    Lo usan la bandeja del panel y el aviso push, para que digan lo mismo.
    """
    alumno = n.reserva.usuario
    if n.tipo == 'permanente' and n.reserva.fecha_unica:
        que = 'su recupero' if n.reserva.es_recupero else 'su clase única'
        return f'{_nombre(alumno)} canceló {que} del {n.reserva.fecha_unica:%d/%m}', 'baja', 'baja'
    if n.tipo == 'permanente':
        return f'{_nombre(alumno)} dejó su horario fijo', 'baja', 'baja'
    fecha = f' el {n.fecha_ausencia:%d/%m}' if n.fecha_ausencia else ''
    return f'{_nombre(alumno)} avisó que no va{fecha}', 'aviso', 'ausencia'


# ------------------------------------------------------------------------------
# Avisos push al equipo (el envío está en push.py; acá, qué dice cada uno)
# ------------------------------------------------------------------------------

def _url_o_panel(usuario):
    return _url_alumno(usuario) or reverse('gravity:admin_dashboard')


@aviso_seguro
def avisar_cancelacion_al_equipo(n):
    """Un alumno dejó su horario, canceló un recupero o avisó que no va (NotificacionCancelacion)."""
    titulo, _tipo, _icono = texto_cancelacion(n)
    return enviar_push_equipo(
        'eq_cancelaciones', titulo, _clase_corta(n.reserva.clase),
        url=_url_o_panel(n.reserva.usuario), etiqueta=f'cancelacion-{n.pk}',
    )


@aviso_seguro
def avisar_reserva_suelta_al_equipo(reserva):
    """Un alumno reservó un recupero o una clase única (cambia quién viene ese día)."""
    if not reserva.fecha_unica:
        return 0
    accion = 'recupera' if reserva.es_recupero else 'tomó una clase única'
    return enviar_push_equipo(
        'eq_recuperos', f'{_nombre(reserva.usuario)} {accion} el {reserva.fecha_unica:%d/%m}',
        _clase_corta(reserva.clase),
        url=_url_o_panel(reserva.usuario), etiqueta=f'reserva-{reserva.pk}',
    )


@aviso_seguro
def avisar_plan_cancelado_al_equipo(n):
    """Un alumno canceló su plan (NotificacionCancelacionPlan)."""
    return enviar_push_equipo(
        'eq_planes', f'{_nombre(n.usuario)} canceló su plan',
        n.plan.nombre if n.plan else '',
        url=_url_o_panel(n.usuario), etiqueta=f'plan-baja-{n.pk}',
    )


@aviso_seguro
def avisar_solicitud_plan(solicitud):
    """Un alumno pidió un plan o un cambio de plan: lo resuelven los superadmins."""
    plan = solicitud.plan_solicitado.nombre if solicitud.plan_solicitado else 'un plan'
    if solicitud.plan_actual:
        titulo = f'{_nombre(solicitud.usuario)} pidió cambiar de plan'
        cuerpo = f'De "{solicitud.plan_actual.nombre}" a "{plan}". Espera tu aprobación.'
    else:
        titulo = f'{_nombre(solicitud.usuario)} pidió un plan'
        cuerpo = f'{plan}. Espera tu aprobación.'
    return enviar_push_equipo(
        'eq_solicitudes', titulo, cuerpo,
        url=reverse('gravity:admin_solicitudes_plan_lista') + '?estado=pendiente',
        etiqueta=f'solicitud-{solicitud.pk}',
    )


@aviso_seguro
def avisar_testimonio(testimonio):
    """Un alumno dejó (o editó) un testimonio que espera aprobación: lo revisan los superadmins."""
    if testimonio.aprobado:
        return 0
    return enviar_push_equipo(
        'eq_testimonios', f'{_nombre(testimonio.usuario)} dejó un testimonio',
        'No se publica hasta que lo apruebes.',
        url=reverse('gravity:admin_testimonios_lista') + '?estado=pendientes',
        etiqueta=f'testimonio-{testimonio.pk}',
    )


def pendientes_panel(user):
    """Cosas para resolver (solo el superadmin las resuelve)."""
    if not es_superadmin(user):
        return {'solicitudes': 0, 'testimonios': 0}
    return {
        'solicitudes': SolicitudCambioPlan.objects.filter(estado='pendiente').count(),
        'testimonios': Testimonio.objects.filter(aprobado=False).count(),
    }


def notificaciones_panel(request, limite=40):
    """
    Actividad de los alumnos que el admin todavía no vio: bajas de horario, avisos
    de ausencia, planes cancelados o sumados, recuperos y clases únicas.

    Las bajas, avisos y planes se marcan como leídos por admin (leida_por); los
    recuperos y clases únicas, en la sesión.
    """
    user = request.user
    ahora = timezone.now()
    hace_7 = ahora - timedelta(days=7)
    hace_30 = ahora - timedelta(days=30)
    items = []

    cancelaciones = NotificacionCancelacion.objects.filter(
        fecha_creacion__gte=hace_7
    ).exclude(leida_por=user).select_related('reserva__clase', 'reserva__usuario')
    for n in cancelaciones:
        alumno = n.reserva.usuario
        titulo, tipo, icono = texto_cancelacion(n)
        items.append({
            'tipo': tipo, 'icono': icono, 'titulo': titulo,
            'detalle': _clase_corta(n.reserva.clase),
            'fecha': n.fecha_creacion, 'url': _url_alumno(alumno),
        })

    planes_cancelados = NotificacionCancelacionPlan.objects.filter(
        fecha_creacion__gte=hace_30
    ).exclude(leida_por=user).select_related('usuario', 'plan')
    for n in planes_cancelados:
        items.append({
            'tipo': 'plan_baja', 'icono': 'plan',
            'titulo': f'{_nombre(n.usuario)} canceló su plan',
            'detalle': n.plan.nombre if n.plan else 'Plan eliminado',
            'fecha': n.fecha_creacion, 'url': _url_alumno(n.usuario),
        })

    planes_sumados = NotificacionPlanAdicional.objects.filter(
        fecha_creacion__gte=hace_30
    ).exclude(leida_por=user).select_related('usuario', 'plan')
    for n in planes_sumados:
        items.append({
            'tipo': 'plan_alta', 'icono': 'plan',
            'titulo': f'{_nombre(n.usuario)} sumó un plan',
            'detalle': n.plan.nombre if n.plan else 'Plan eliminado',
            'fecha': n.fecha_creacion, 'url': _url_alumno(n.usuario),
        })

    vistos = request.session.get('recuperos_vistos', [])
    sueltas = Reserva.objects.filter(
        activa=True, fecha_unica__isnull=False, fecha_reserva__gte=hace_7,
    ).exclude(id__in=vistos).select_related('usuario', 'clase')
    ids_sueltas = []
    for r in sueltas:
        ids_sueltas.append(r.id)
        accion = 'recupera' if r.es_recupero else 'tomó una clase única'
        items.append({
            'tipo': 'recupero' if r.es_recupero else 'extra', 'icono': 'recupero',
            'titulo': f'{_nombre(r.usuario)} {accion} el {r.fecha_unica:%d/%m}',
            'detalle': _clase_corta(r.clase),
            'fecha': r.fecha_reserva, 'url': _url_alumno(r.usuario),
        })

    items.sort(key=lambda i: i['fecha'], reverse=True)
    for item in items:
        item['hace'] = _hace(item['fecha'], ahora)

    return {
        'items': items[:limite],
        'sin_leer': len(items),
        'ids_sueltas': ids_sueltas,
    }


# ------------------------------------------------------------------------------
# Context processor
# ------------------------------------------------------------------------------

def contexto_panel(request):
    """
    Variables de la base del panel (`panel.*`). Solo se calculan en /admin-panel/
    y para el equipo, así el resto del sitio no paga estas consultas.
    """
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_staff):
        return {}
    if not request.path.startswith('/admin-panel/'):
        return {}

    match = getattr(request, 'resolver_match', None)
    actual = seccion_actual(match.url_name if match else '')
    pendientes = pendientes_panel(user)
    secciones = menu_panel(user, actual, pendientes)

    por_clave = {item['clave']: item for s in secciones for item in s['items']}
    accesos = [por_clave[c] for c in ACCESOS_CELULAR]
    activo = por_clave.get(actual)
    # "Más" queda marcado cuando la sección actual no está en la barra inferior
    mas_activo = bool(actual) and actual not in ACCESOS_CELULAR

    return {
        'panel': {
            'superadmin': es_superadmin(user),
            've_ingresos': ve_ingresos_estudio(user),
            'rol': 'Superadmin' if es_superadmin(user) else 'Equipo',
            'secciones': secciones,
            'accesos_celular': accesos,
            'mas_activo': mas_activo,
            'titulo': activo['texto'] if activo else 'Panel',
            'pendientes': pendientes,
            'pendientes_total': pendientes['solicitudes'] + pendientes['testimonios'],
            'notificaciones': notificaciones_panel(request),
            # Clave pública para activar los avisos push ('' = avisos apagados en este servidor)
            'push_clave': clave_publica(),
        }
    }
