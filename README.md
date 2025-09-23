# Pilates Gravity - Sistema de Gestión de Reservas

Una aplicación web moderna y completa desarrollada en Django para la gestión integral de un estudio de Pilates. Permite a los usuarios registrarse, reservar clases recurrentes y gestionar su perfil, mientras que los administradores pueden manejar clases, reservas y obtener reportes detallados.

## Características Principales

### Para Usuarios
- **Registro y Autenticación Completa**
  - Sistema de registro con validaciones
  - Login/logout seguro
  - Recuperación de contraseña por email
  - Perfiles de usuario extendidos con información médica opcional

- **Sistema de Reservas Inteligente**
  - Reservas recurrentes (mismo día y horario cada semana)
  - Validación automática de cupos disponibles
  - Sistema de modificación y cancelación con restricciones de tiempo
  - Búsqueda de reservas por nombre de usuario

- **Gestión de Perfil**
  - Información personal completa
  - Historial médico opcional para Pilates
  - Preferencias de notificaciones
  - Avatar personalizable

### Para Administradores
- **Panel de Administración Completo**
  - Dashboard con estadísticas en tiempo real
  - Gestión completa de clases (crear, editar, activar/desactivar)
  - Administración de reservas con cancelación sin restricciones
  - Gestión de usuarios registrados

- **Sistema de Usuarios**
  - Agregar usuarios asignandole directamente una clases

- **Reportes y Estadísticas**
  - Estadísticas por tipo de clase
  - Análisis por día de la semana
  - Reportes de ocupación
  - Usuarios nuevos por período

## Arquitectura Técnica

### Backend
- **Framework**: Django 5.2.1
- **Base de Datos**: SQLite (desarrollo) / PostgreSQL (producción recomendada)
- **Autenticación**: Sistema de usuarios de Django extendido
- **Gestión de Archivos**: Pillow para procesamiento de imágenes

### Frontend
- **CSS Framework**: Tailwind CSS
- **JavaScript**: Vanilla JS con AJAX para interacciones dinámicas
- **Responsive Design**: Completamente adaptable a móviles

### Estructura del Proyecto
```
PilatesGravity/
├── PilatesGravity/          # Configuración principal
│   ├── settings.py          # Configuraciones del proyecto
│   ├── urls.py             # URLs principales
│   └── wsgi.py             # Configuración WSGI
├── gravity/                 # App principal del estudio
│   ├── models.py           # Modelos de Clase, Reserva, Cliente
│   ├── views.py            # Vistas públicas y de administrador
│   ├── forms.py            # Formularios con validaciones completas
│   └── urls.py             # URLs de la aplicación
├── accounts/                # App de gestión de usuarios
│   ├── models.py           # UserProfile y configuraciones
│   ├── views.py            # Vistas de autenticación y perfil
│   ├── forms.py            # Formularios de usuario
│   └── urls.py             # URLs de cuentas
├── templates/               # Templates HTML
├── static/                  # Archivos estáticos
└── media/                   # Archivos subidos por usuarios
```

## 🚀 Instalación y Configuración

### Requisitos Previos
- Python 3.8+
- pip
- Git

### Instalación Local

1. **Clonar el repositorio**
   ```bash
   git clone https://github.com/tu-usuario/PilatesGravity.git
   cd PilatesGravity
   ```

2. **Crear entorno virtual**
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```

3. **Instalar dependencias**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar base de datos**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Crear superusuario**
   ```bash
   python manage.py createsuperuser
   ```

6. **Ejecutar servidor de desarrollo**
   ```bash
   python manage.py runserver
   ```

7. **Acceder a la aplicación**
   - Aplicación principal: `http://localhost:8000`
   - Panel de administración: `http://localhost:8000/admin-panel/`

### Configuración de Email (Opcional)
Para funcionalidad completa de recuperación de contraseñas, configura en `settings.py`:

```python
EMAIL_HOST_USER = 'tu-email@gmail.com'
EMAIL_HOST_PASSWORD = 'tu-app-password'
```

## 🗂️ Modelos de Datos

### Principales
- **Clase**: Tipos de Pilates (Reformer, Cadillac) con horarios y cupos
- **Reserva**: Sistema de reservas recurrentes con validaciones
- **UserProfile**: Perfiles extendidos con información médica opcional
- **ConfiguracionEstudio**: Configuraciones globales del sistema

### Características de los Modelos
- Validaciones completas a nivel de modelo y formulario
- Campos de auditoría (fechas de creación/modificación)
- Relaciones optimizadas para consultas eficientes
- Sistema de permisos granular

## 🎯 Funcionalidades Avanzadas

### Sistema de Reservas
- **Reservas Recurrentes**: Los usuarios reservan un día y horario fijo cada semana
- **Validación de Cupos**: Control automático de disponibilidad
- **Restricciones de Tiempo**: Cancelaciones/modificaciones con 12 horas de anticipación
- **Sin Duplicados**: Un usuario no puede tener múltiples reservas para la misma clase

### APIs AJAX
- Carga dinámica de días disponibles por tipo de clase
- Horarios disponibles con información de cupos en tiempo real
- Verificación de disponibilidad antes de confirmar reserva

### Validaciones Integrales
- Validaciones tanto en frontend (JavaScript) como backend (Django)
- Mensajes de error específicos y útiles
- Formularios con campos dependientes

## 🛡️ Seguridad

- **Autenticación Robusta**: Sistema de usuarios de Django
- **Validación de Permisos**: Decoradores personalizados para administradores
- **Sanitización de Datos**: Validaciones completas en formularios
- **CSRF Protection**: Protección integrada de Django
- **Configuración Segura**: Separación de configuraciones por ambiente

## 📊 Panel de Administración

### Dashboard Principal
- Estadísticas en tiempo real
- Clases más populares
- Reservas recientes
- Alertas de clases casi llenas

### Gestión de Clases
- CRUD completo de clases
- Activación/desactivación sin eliminación
- Validación de conflictos de horarios
- Vista detallada con lista de asistentes

### Gestión de Reservas
- Lista filtrable de todas las reservas
- Cancelación administrativa sin restricciones
- Búsqueda por usuario, clase, día

### Reportes
- Estadísticas por tipo de clase
- Análisis de ocupación por día
- Usuarios nuevos por período
- Exportación de datos

## 🎨 Diseño y UX

### Responsive Design
- Totalmente adaptable desde móviles hasta desktop
- Navegación intuitiva
- Formularios optimizados para dispositivos táctiles

### Interfaz de Usuario
- Diseño limpio con Tailwind CSS
- Mensajes de feedback claros
- Loading states para operaciones AJAX
- Validación en tiempo real

## 🔄 Estados de la Aplicación

### Usuarios
- **No registrado**: Puede ver clases disponibles y registrarse
- **Registrado**: Puede hacer reservas y gestionar perfil
- **Administrador**: Acceso completo al panel de administración

### Reservas
- **Activa**: Reserva válida y recurrente
- **Cancelada**: Reserva cancelada por usuario o administrador

### Clases
- **Activa**: Disponible para nuevas reservas
- **Inactiva**: No aparece en formularios de reserva (soft delete)

## 🚀 Próximas Mejoras

### Funcionalidades Planificadas
- [ ] Sistema de notificaciones por email automáticas
- [ ] Integración con calendario (Google Calendar)
- [ ] Sistema de pagos online
- [ ] App móvil nativa
- [ ] Sistema de lista de espera
- [ ] Integración con WhatsApp
- [ ] Reportes más avanzados con gráficos
- [ ] Sistema de promociones y descuentos

### Mejoras Técnicas
- [ ] Tests unitarios e integración
- [ ] Dockerización completa
- [ ] CI/CD pipeline
- [ ] Monitoreo y logging
- [ ] Cache con Redis
- [ ] API REST completa

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📝 Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## 📞 Contacto

**Desarrollador: GAP**
- Email: [piccoli_44@hotmail.com]
- GitHub: [https://github.com/Piccoli4]
- LinkedIn: [https://www.linkedin.com/in/piccoli-augusto/]

**Cliente: Pilates Gravity**
- Email: pilatesgravity@gmail.com
- Teléfono: +54 342 511 4448
- Ubicación: Capital, Santa Fe, Argentina

---

Desarrollado con ❤️ por GAP para la comunidad de Pilates Gravity usando Django y Tailwind CSS.