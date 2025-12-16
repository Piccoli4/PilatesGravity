from django.urls import path
from .views import (
    home, reservar_clase, conoce_mas,
    dias_disponibles, horarios_disponibles,
    verificar_disponibilidad, modificar_reserva,
    cancelar_reserva, buscar_reservas_usuario,
    clases_disponibles_api, clases_disponibles, detalle_reserva,
    sedes_disponibles,
    # IMPORTACIONES PARA ADMINISTRADOR
    admin_dashboard, admin_clases_lista, admin_clase_crear, admin_clase_editar,
    admin_clase_eliminar, admin_clase_detalle,
    admin_reservas_lista, admin_reserva_cancelar, admin_usuarios_lista, admin_usuario_detalle,
    admin_usuario_toggle_status, admin_usuario_add_note, admin_agregar_usuario,
    admin_reportes,
    # IMPORTACIONES PARA SISTEMA DE PAGOS
    admin_pagos_registrar_pago, admin_pagos_vista_principal, admin_pagos_registrar_pago, admin_pagos_historial_cliente,
    admin_pagos_configurar_planes, admin_pagos_editar_estado_cliente,
    # IMPORTACIONES PARA PLANES DE PAGO
    mis_planes, seleccionar_plan, cancelar_plan
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
    path('reserva/<str:numero_reserva>/cancelar/', cancelar_reserva, name='cancelar_reserva'),
    
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
    
    # Gestión de usuarios
    path('admin-panel/usuarios/', admin_usuarios_lista, name='admin_usuarios_lista'),
    path('admin-panel/usuarios/<int:usuario_id>/', admin_usuario_detalle, name='admin_usuario_detalle'),
    path('admin-panel/usuarios/<int:usuario_id>/toggle-status/', admin_usuario_toggle_status, name='admin_usuario_toggle_status'),
    path('admin-panel/usuarios/<int:usuario_id>/add-note/', admin_usuario_add_note, name='admin_usuario_add_note'),
    
    # # Agregar usuarios al sistema
    path('admin-panel/agregar-cliente/', admin_agregar_usuario, name='admin_agregar_usuario'),
    
    # Reportes y estadísticas
    path('admin-panel/reportes/', admin_reportes, name='admin_reportes'),

    # ==============================================================================
    # URLS DEL SISTEMA DE PAGOS
    # ==============================================================================
    
    path('admin-panel/pagos/', admin_pagos_vista_principal, name='admin_pagos_vista_principal'),
    path('admin-panel/pagos/registrar/<int:cliente_id>/', admin_pagos_registrar_pago, name='admin_pagos_registrar_pago'),
    path('admin-panel/pagos/historial/<int:cliente_id>/', admin_pagos_historial_cliente, name='admin_pagos_historial_cliente'),
    path('admin-panel/pagos/configurar-planes/', admin_pagos_configurar_planes, name='admin_pagos_configurar_planes'),
    path('admin-panel/pagos/editar-estado/<int:cliente_id>/', admin_pagos_editar_estado_cliente, name='admin_pagos_editar_estado_cliente'),

    # Gestión de planes de pago
    path('planes/', mis_planes, name='mis_planes'),
    path('seleccionar-plan/', seleccionar_plan, name='seleccionar_plan'),
    path('planes/<int:plan_id>/cancelar/', cancelar_plan, name='cancelar_plan'),
]