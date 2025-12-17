# PilatesGravity - Sistema Integral de Gestión de Estudio de Pilates

[![Django Version](https://img.shields.io/badge/Django-5.2.1-green.svg)](https://www.djangoproject.com/)
[![Python Version](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg)]()

## Descripción del Proyecto

**PilatesGravity** es una solución empresarial completa desarrollada específicamente para la gestión integral de estudios de Pilates. La aplicación web proporciona un ecosistema robusto que incluye gestión de clientes, sistema de reservas recurrentes, planes de pago flexibles, y herramientas administrativas avanzadas.

### Características Diferenciales

- **Arquitectura Multi-sede**: Soporte nativo para múltiples ubicaciones
- **Sistema de Planes Inteligente**: Gestión automatizada de suscripciones y límites de clases
- **Reservas Recurrentes**: Optimizado para la naturaleza repetitiva del entrenamiento de Pilates
- **Panel Financiero**: Control completo de facturación, pagos y estados de cuenta
- **Diseño Responsivo**: Experiencia optimizada en todos los dispositivos

---

## Funcionalidades del Sistema

### 🎯 Gestión de Clientes y Usuarios

#### Para Estudiantes/Clientes
- **Autenticación Robusta**
  - Registro con validaciones integrales
  - Recuperación de contraseña por email
  - Perfiles extendidos con información médica opcional
  - Sistema de avatares personalizables

- **Gestión de Reservas**
  - Reservas recurrentes (mismo día y horario semanal)
  - Validación en tiempo real de disponibilidad
  - Modificación y cancelación con políticas de tiempo
  - Historial completo de actividad

- **Sistema de Planes**
  - Selección entre múltiples tipos de suscripción
  - Visualización de clases disponibles y utilizadas
  - Gestión de múltiples planes simultáneos
  - Cancelación controlada de suscripciones

### 💼 Panel Administrativo Empresarial

#### Gestión Operativa
- **Dashboard Ejecutivo**
  - Métricas en tiempo real de ocupación
  - Análisis de tendencias por tipo de clase
  - Alertas de clases con alta demanda
  - Estadísticas de nuevos registros

- **Administración de Clases**
  - CRUD completo con validaciones de horarios
  - Gestión multi-sede
  - Control de capacidad por tipo de clase
  - Activación/desactivación sin pérdida de datos

- **Sistema de Usuarios**
  - Gestión completa de perfiles de cliente
  - Herramientas de comunicación directa
  - Control de estados de cuenta
  - Notas administrativas con timestamps

#### Gestión Financiera
- **Sistema de Planes de Pago**
  - Creación y asignación de planes personalizados
  - Seguimiento automático de límites semanales
  - Planes temporales y permanentes
  - Gestión de múltiples suscripciones por cliente

- **Control Financiero**
  - Registro detallado de todos los pagos
  - Estados de cuenta automáticos
  - Historial completo de transacciones
  - Reportes financieros por período

### 📊 Reportes y Análisis
- Ocupación por tipo de clase y día de semana
- Análisis de retención de clientes
- Reportes financieros detallados
- Métricas de crecimiento del negocio

---

## Arquitectura Técnica

### Stack Tecnológico

**Backend**
- **Framework**: Django 5.2.1 (LTS)
- **Base de Datos**: SQLite (desarrollo) / PostgreSQL (producción)
- **Autenticación**: Sistema extendido de Django con perfiles personalizados
- **Email Service**: Configuración SMTP integrada
- **Procesamiento de Archivos**: Pillow para gestión de imágenes

**Frontend**
- **CSS Framework**: Tailwind CSS con configuración personalizada
- **JavaScript**: ES6+ con AJAX para interacciones dinámicas
- **Tipografía**: Fuentes personalizadas + Google Fonts
- **Paleta de Colores**: Esquema corporativo personalizado
- **Responsive Design**: Mobile-first approach

**DevOps y Herramientas**
- **Variables de Entorno**: python-decouple para configuración segura
- **Servidor Web**: Gunicorn + Nginx (producción)
- **Archivos Estáticos**: WhiteNoise para servido eficiente
- **Control de Versiones**: Git con flujo GitFlow

### Estructura del Proyecto

```
PilatesGravity/
├── PilatesGravity/              # Configuración principal del proyecto
│   ├── settings.py              # Configuraciones por ambiente
│   ├── urls.py                  # Rutas principales
│   ├── wsgi.py                  # Configuración WSGI para producción
│   └── asgi.py                  # Configuración ASGI
│
├── gravity/                     # Aplicación principal del negocio
│   ├── migrations/              # Migraciones de base de datos
│   ├── templates/gravity/       # Templates específicos
│   │   ├── admin/              # Panel administrativo
│   │   ├── reservar_clase.html
│   │   ├── mis_planes.html
│   │   └── ...
│   ├── models.py                # Modelos de dominio del negocio
│   ├── views.py                 # Lógica de vistas y APIs
│   ├── forms.py                 # Formularios con validaciones
│   └── urls.py                  # Rutas específicas
│
├── accounts/                    # Gestión de usuarios y autenticación
│   ├── templates/accounts/
│   ├── models.py                # UserProfile y configuraciones
│   ├── views.py                 # Autenticación y gestión de perfiles
│   └── forms.py                 # Formularios de usuario
│
├── templates/                   # Templates globales y componentes
├── static/                     # Archivos estáticos
├── media/                      # Archivos subidos por usuarios
└── requirements.txt            # Dependencias del proyecto
```

---

## Modelos de Datos

### Entidades Principales

#### Sistema de Clases
- **Clase**: Representa una clase con horario fijo semanal
  - Tipo de clase (Reformer, Cadillac, Especial)
  - Día y horario específico
  - Sede correspondiente
  - Control de capacidad y disponibilidad

#### Sistema de Reservas
- **Reserva**: Reserva recurrente de un usuario para una clase específica
  - Relación usuario-clase
  - Estado y timestamps de auditoría
  - Sistema de identificación único

#### Sistema de Planes de Pago
- **PlanPago**: Planes de suscripción disponibles
  - Configuración de límites de clases
  - Precios y descripciones
  - Estado de disponibilidad

- **PlanUsuario**: Asignación de planes a usuarios
  - Control de vigencia temporal
  - Estados activo/inactivo
  - Múltiples planes simultáneos

- **EstadoPagoCliente**: Estado financiero actual
  - Balance de cuenta del cliente
  - Referencia al plan principal
  - Historial de pagos

#### Sistema de Pagos
- **RegistroPago**: Registro detallado de transacciones
  - Información completa de cada pago
  - Tipos de pago y comprobantes
  - Trazabilidad administrativa

### Perfiles de Usuario
- **UserProfile**: Extensión del modelo User de Django
  - Información personal y de contacto
  - Datos relevantes para la práctica de Pilates
  - Configuraciones de usuario y preferencias

---

## Instalación y Configuración

### Requisitos del Sistema

**Ambiente de Desarrollo**
- Python 3.8+ (recomendado 3.11+)
- pip 21.0+
- Git 2.30+
- Node.js 16+ (para Tailwind CSS)

**Ambiente de Producción**
- Ubuntu 22.04 LTS (recomendado)
- PostgreSQL 13+
- Nginx 1.18+
- Supervisord o systemd

### Instalación Local

#### 1. Clonar y Configurar el Proyecto
```bash
# Clonar repositorio
git clone <repository-url>
cd PilatesGravity

# Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt
```

#### 2. Configuración de Variables de Entorno
```bash
# Crear archivo .env basado en .env.example
cp .env.example .env

# Configurar variables necesarias (ver documentación de deployment)
```

#### 3. Inicializar Base de Datos
```bash
# Aplicar migraciones
python manage.py makemigrations
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser
```

#### 4. Ejecutar Servidor de Desarrollo
```bash
python manage.py runserver
```

---

## Configuración para Producción

### Dependencias Principales

Las dependencias están definidas en `requirements.txt`:
- Django 5.2.1
- psycopg2-binary (PostgreSQL)
- Pillow (procesamiento de imágenes)
- python-decouple (variables de entorno)
- gunicorn (servidor WSGI)
- whitenoise (archivos estáticos)

### Variables de Entorno

El sistema utiliza archivos `.env` para configuración sensible:
- Configuraciones de base de datos
- Credenciales de email
- Claves de seguridad
- Configuraciones específicas por ambiente

*Ver documentación de deployment para configuración detallada*

---

## Seguridad y Mejores Prácticas

### Medidas de Seguridad Implementadas

**Autenticación y Autorización**
- Sistema de usuarios robusto con perfiles extendidos
- Control de permisos granular
- Validación de sesiones y protección CSRF
- Políticas de contraseñas configurables

**Validación de Datos**
- Sanitización completa en formularios
- Validaciones tanto en frontend como backend
- Protección contra inyecciones (ORM de Django)
- Escape automático de templates

**Configuración Segura**
- Separación de configuraciones por ambiente
- Variables sensibles en archivos de entorno
- Headers de seguridad configurados
- HTTPS enforced en producción

### Auditoría y Logging
- Campos de auditoría en modelos críticos
- Logging de acciones administrativas
- Registro de cambios en estados financieros
- Monitoreo de accesos al sistema

---

## Testing y Calidad

### Cobertura de Tests
- Tests unitarios para modelos críticos
- Tests de integración para flujos principales
- Tests de formularios y validaciones
- Tests de APIs y endpoints

### Herramientas de Calidad
- Validación de código con herramientas estándar
- Formateo automático de código
- Testing framework integrado
- Factories para datos de prueba

---

## Roadmap de Desarrollo

### Funcionalidades Planificadas
- [ ] Sistema de notificaciones push
- [ ] Integración con calendario externo
- [ ] API REST completa para aplicación móvil
- [ ] Sistema de lista de espera automática
- [ ] Integración con pasarelas de pago
- [ ] Dashboard de analytics avanzado

### Mejoras Técnicas Continuas
- [ ] Containerización completa
- [ ] CI/CD automatizado
- [ ] Monitoring y alertas
- [ ] Optimización de performance
- [ ] Backup automatizado
- [ ] Escalabilidad horizontal

---

## Soporte y Mantenimiento

### Documentación Técnica
- Documentación de APIs disponible
- Diagramas de arquitectura
- Guías de deployment específicas

### Contacto

**Equipo de Desarrollo**
- **Desarrollador Principal**: Guido Augusto Piccoli
- **Email**: piccoli_44@hotmail.com
- **GitHub**: [github.com/Piccoli4](https://github.com/Piccoli4)
- **LinkedIn**: [linkedin.com/in/piccoli-augusto](https://www.linkedin.com/in/piccoli-augusto/)

---

## Licencia y Contribuciones

### Licencia
Este proyecto está licenciado bajo la Licencia MIT. Consulte el archivo `LICENSE` para más detalles.

### Contribuciones
Las contribuciones son bienvenidas siguiendo las pautas del proyecto:

1. Fork del repositorio
2. Crear branch para feature
3. Commit con mensaje descriptivo
4. Push y crear Pull Request
5. Revisión de código antes de merge

---

*Desarrollado para la gestión profesional de estudios de Pilates*  
*Stack: Django | PostgreSQL | Tailwind CSS | Python*