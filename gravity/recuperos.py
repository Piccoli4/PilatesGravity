"""
Reglas de recupero de clases.

Cada recupero "cubre" una ausencia distinta. Una ausencia puede cubrirse con un
recupero si:
  - el tipo de clase del recupero está permitido para el tipo de la clase que se
    faltó (TIPOS_PERMITIDOS: Cadillac → Cadillac o Reformer; Reformer → Reformer),
  - la fecha del recupero no pasa el plazo de la ausencia (fecha + 6 días), y
  - el recupero se reservó después de avisar la ausencia.

Como las reglas dependen del tipo y del plazo, no alcanza con contar: se arma una
asignación ausencia ↔ recupero (emparejamiento bipartito; son pocos elementos).
"""
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

# Tipo de la clase que se faltó → tipos de clase donde se puede recuperar.
# Los tipos que no figuran (p. ej. Especial) solo se recuperan en su mismo tipo.
TIPOS_PERMITIDOS = {
    'Cadillac': {'Cadillac', 'Reformer'},
    'Reformer': {'Reformer'},
}


def tipos_permitidos(tipo_faltado):
    return TIPOS_PERMITIDOS.get(tipo_faltado, {tipo_faltado})


def _puede_cubrir(ausencia, tipo, fecha, reservado_el):
    return (
        tipo in tipos_permitidos(ausencia.reserva.clase.tipo)
        and fecha <= ausencia.fecha_limite_recupero
        and reservado_el >= ausencia.fecha_creacion
    )


def _emparejar(ausencias, recuperos):
    """
    Máximo emparejamiento recupero → ausencia (algoritmo de Kuhn).
    'recuperos' es una lista de (tipo, fecha, reservado_el).
    Devuelve {índice de recupero: índice de ausencia}.
    """
    asignada_a = {}  # índice de ausencia → índice de recupero

    def buscar(r, vistas):
        tipo, fecha, reservado_el = recuperos[r]
        for a, ausencia in enumerate(ausencias):
            if a in vistas or not _puede_cubrir(ausencia, tipo, fecha, reservado_el):
                continue
            vistas.add(a)
            if a not in asignada_a or buscar(asignada_a[a], vistas):
                asignada_a[a] = r
                return True
        return False

    for r in range(len(recuperos)):
        buscar(r, set())
    return {r: a for a, r in asignada_a.items()}


class EstadoRecuperos:
    """Ausencias vigentes del usuario, cuáles ya están cubiertas y qué recupero se puede sumar."""

    def __init__(self, usuario, ahora=None):
        from .models import AusenciaTemporal, Reserva

        self.ahora = timezone.localtime(ahora or timezone.now())
        hoy = self.ahora.date()

        # Ausencias cuyo plazo de recupero no venció
        self.ausencias = list(
            AusenciaTemporal.objects.filter(
                reserva__usuario=usuario,
                reserva__activa=True,
                reserva__fecha_unica__isnull=True,
                fecha__gte=hoy - timedelta(days=6),
            ).select_related('reserva__clase').order_by('fecha')
        )

        # Recuperos que cuentan: los activos y los que ya se hicieron (la limpieza
        # diaria los desactiva). Los que se cancelaron no cuentan.
        self.recuperos = []
        if self.ausencias:
            desde = min(a.fecha_creacion for a in self.ausencias)
            qs = (
                Reserva.objects.filter(usuario=usuario, es_recupero=True, fecha_unica__isnull=False,
                                       fecha_reserva__gte=desde)
                .exclude(Q(activa=False) & (Q(notificaciones_cancelacion__tipo='permanente')
                                            | Q(cancelaciones_admin__isnull=False)))
                .select_related('clase').distinct()
            )
            self.recuperos = [(r.clase.tipo, r.fecha_unica, r.fecha_reserva) for r in qs]

        self._asignacion = _emparejar(self.ausencias, self.recuperos)
        cubiertas = set(self._asignacion.values())
        self.pendientes = [a for i, a in enumerate(self.ausencias) if i not in cubiertas]
        self._cache = {}

    @property
    def disponibles(self):
        return len(self.pendientes)

    @property
    def tipos_disponibles(self):
        """Tipos de clase donde se puede recuperar alguna ausencia pendiente."""
        tipos = set()
        for a in self.pendientes:
            tipos |= tipos_permitidos(a.reserva.clase.tipo)
        return tipos

    @property
    def fecha_limite(self):
        """Último día en que se puede recuperar alguna ausencia pendiente."""
        return max((a.fecha_limite_recupero for a in self.pendientes), default=None)

    def puede_recuperar(self, tipo, fecha):
        """¿Se puede sumar un recupero de este tipo en esta fecha sin dejar otro sin cubrir?"""
        clave = (tipo, fecha)
        if clave not in self._cache:
            if not self.pendientes:
                self._cache[clave] = False
            else:
                nuevos = self.recuperos + [(tipo, fecha, self.ahora)]
                self._cache[clave] = len(_emparejar(self.ausencias, nuevos)) > len(self._asignacion)
        return self._cache[clave]

    def puede_recuperar_en(self, clase, fecha):
        """Recupero en una clase concreta: tipo y plazo, y que la clase todavía no empezó."""
        inicio = timezone.make_aware(datetime.combine(fecha, clase.horario))
        return inicio > self.ahora and self.puede_recuperar(clase.tipo, fecha)
