from django.urls import path
from .views import (
    home, reservar_clase, conoce_mas,
    dias_disponibles, horarios_disponibles, 
    verificar_disponibilidad, modificar_reserva,
    eliminar_reserva, buscar_reservas_usuario,
    clases_disponibles_api, clases_disponibles, detalle_reserva,
    sedes_disponibles,
    # NUEVAS IMPORTACIONES PARA ADMINISTRADOR
    admin_dashboard, admin_clases_lista, admin_clase_crear, admin_clase_editar,
    admin_clase_eliminar, admin_clase_detalle, admin_reservas_lista,
    admin_reserva_cancelar, admin_usuarios_lista, admin_usuario_detalle,
    admin_agregar_cliente_no_registrado, admin_clientes_no_registrados_lista,
    admin_reportes
)
from django.views.generic import TemplateView

app_name = 'gravity'

urlpatterns = [
    # Páginas principales
    path('', home, name='home'),
    path('reservar_clase/', reservar_clase, name='reservar_clase'),
    path('conoce-mas/', conoce_mas, name='conoce_mas'),
    path('clases-disponibles/', clases_disponibles, name='clases_disponibles'),
    
    # Gestión de reservas
    path('buscar-reservas/', buscar_reservas_usuario, name='buscar_reservas_usuario'),
    path('reserva/<str:numero_reserva>/', detalle_reserva, name='detalle_reserva'),
    path('reserva/<str:numero_reserva>/modificar/', modificar_reserva, name='modificar_reserva'),
    path('reserva/<str:numero_reserva>/eliminar/', eliminar_reserva, name='eliminar_reserva'),
    
    # Páginas informativas
    path('politica-de-privacidad/', TemplateView.as_view(template_name='gravity/politica_privacidad.html'), name='politica_privacidad'),
    path('terminos_condiciones/', TemplateView.as_view(template_name='gravity/terminos_condiciones.html'), name='terminos_condiciones'),

    # API endpoints para AJAX
    path('api/sedes-disponibles/', sedes_disponibles, name='sedes_disponibles'),
    path('api/dias-disponibles/', dias_disponibles, name='dias_disponibles'),
    path('api/horarios-disponibles/', horarios_disponibles, name='horarios_disponibles'),
    path('api/verificar-disponibilidad/', verificar_disponibilidad, name='verificar_disponibilidad'),
    path('api/clases-disponibles/', clases_disponibles_api, name='clases_disponibles_api'),

    # ==============================================================================
    # URLS DEL PANEL DE ADMINISTRACIÓN
    # ==============================================================================
    
    # Dashboard principal del administrador
    path('admin-panel/', admin_dashboard, name='admin_dashboard'),
    
    # Gestión de clases
    path('admin-panel/clases/', admin_clases_lista, name='admin_clases_lista'),
    path('admin-panel/clases/crear/', admin_clase_crear, name='admin_clase_crear'),
    path('admin-panel/clases/<int:clase_id>/editar/', admin_clase_editar, name='admin_clase_editar'),
    path('admin-panel/clases/<int:clase_id>/eliminar/', admin_clase_eliminar, name='admin_clase_eliminar'),
    path('admin-panel/clases/<int:clase_id>/detalle/', admin_clase_detalle, name='admin_clase_detalle'),
    
    # Gestión de reservas
    path('admin-panel/reservas/', admin_reservas_lista, name='admin_reservas_lista'),
    path('admin-panel/reservas/<int:reserva_id>/cancelar/', admin_reserva_cancelar, name='admin_reserva_cancelar'),
    
    # Gestión de usuarios registrados
    path('admin-panel/usuarios/', admin_usuarios_lista, name='admin_usuarios_lista'),
    path('admin-panel/usuarios/<int:usuario_id>/', admin_usuario_detalle, name='admin_usuario_detalle'),
    
    # Gestión de clientes no registrados
    path('admin-panel/agregar-cliente/', admin_agregar_cliente_no_registrado, name='admin_agregar_cliente_no_registrado'),
    path('admin-panel/clientes-no-registrados/', admin_clientes_no_registrados_lista, name='admin_clientes_no_registrados_lista'),
    
    # Reportes y estadísticas
    path('admin-panel/reportes/', admin_reportes, name='admin_reportes'),
]