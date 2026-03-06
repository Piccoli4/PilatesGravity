# PilatesGravity — Sistema de Gestión para Estudio de Pilates

[![Django Version](https://img.shields.io/badge/Django-5.2.1-green.svg)](https://www.djangoproject.com/)
[![Python Version](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg)]()

## Descripción

**PilatesGravity** es un sistema web integral desarrollado para la gestión operativa de un estudio de Pilates con dos sedes. Cubre el ciclo completo del negocio: desde la reserva de clases y la gestión de planes, hasta el control financiero mensual y las comunicaciones automáticas con los clientes.

---

## Funcionalidades

### Para clientes

- **Autenticación completa** — registro, inicio de sesión, recuperación de contraseña por email
- **Reservas recurrentes** — el cliente reserva un día y horario fijo semanal; la reserva se mantiene activa hasta que decida cancelarla
- **Ausencias temporales** — permite avisar que no asistirá una semana puntual sin perder su lugar; el cupo se libera solo para esa fecha
- **Gestión de planes** — visualización del plan activo, clases disponibles por semana y estado de cuenta
- **Perfil de usuario** — información personal y datos opcionales relevantes para la práctica

### Para administradores

- **Dashboard ejecutivo** — métricas de ocupación, nuevos registros, y panel de notificaciones de cancelaciones pendientes de lectura
- **Gestión de clases** — alta, edición y baja de clases con validaciones de horario, tipo y sede. Las clases inactivas se conservan sin perder historial
- **Gestión de clientes** — activar/desactivar cuentas, notas administrativas con timestamps, historial completo de reservas y pagos
- **Gestión financiera** — registro de pagos, estados de cuenta automáticos y seguimiento de deudas por cliente
- **Notificaciones de cancelación** — cada cancelación permanente o temporal genera una notificación visible en el panel hasta que un administrador la marque como leída

---

## Sistema de Pagos

El modelo financiero funciona con deudas mensuales automáticas:

- El día 1 de cada mes se genera una `DeudaMensual` para cada cliente con plan activo
- La fecha límite de pago es el **día 10** de cada mes
- Las deudas soportan estados: `pendiente`, `parcial`, `pagado`, `vencido`
- El balance del cliente se calcula como `total_pagado - total_deudas_generadas`
- Los clientes con deudas vencidas quedan con acceso restringido al sistema
- Dos comandos de gestión (`generar_deudas_mensuales` y `verificar_deudas_vencidas`) se ejecutan automáticamente vía cron

---

## Sistema de Emails

Se envían 6 tipos de emails transaccionales vía **Gmail SMTP**:

| Email | Cuándo se envía |
|---|---|
| Bienvenida | Al registrarse un nuevo cliente |
| Confirmación de reserva | Al confirmar una reserva exitosamente |
| Cancelación de reserva | Al cancelar una reserva (permanente o por el admin) |
| Confirmación de pago | Al registrar un pago desde el panel admin |
| Recordatorio de clase | Automático vía cron job antes de cada clase |
| Despedida | Al desactivar la cuenta de un cliente |

---

## Arquitectura y Modelos de Datos

### Modelos principales

**`Clase`** — clase con horario fijo semanal
- Tipos: Reformer, Cadillac, Especial (con nombre personalizado)
- Sedes: Sede Principal (La Rioja 3044) y Sede 2 (9 de julio 3698)
- Días: lunes a viernes; sábados solo para clases especiales
- Control de cupo y estado activo/inactivo

**`Reserva`** — reserva recurrente de un usuario a una clase
- Número de reserva único autogenerado
- Ventana de modificación/cancelación: mínimo 3 horas antes de la clase
- Registro de auditoría completo

**`AusenciaTemporal`** — ausencia puntual sin cancelar la reserva recurrente
- Libera el cupo solo para esa fecha
- Vinculada a la reserva activa

**`NotificacionCancelacion`** — registro de cancelaciones para el panel admin
- Tipos: permanente o temporal
- Estado de lectura por administrador (ManyToMany)

**`PlanPago`** — planes disponibles en el estudio
- Configurables: clases por semana y precio mensual

**`PlanUsuario`** — asignación de un plan a un cliente
- Vigencia por fechas (inicio y fin)
- Estados: activo, inactivo, vencido, pendiente

**`DeudaMensual`** — deuda mensual generada automáticamente
- Soporte de pago parcial y completo
- Vencimiento fijo: día 10 de cada mes

**`RegistroPago`** — registro detallado de cada transacción

**`UserProfile`** — extensión del modelo `User` de Django
- Creado automáticamente vía signal `post_save`
- Información de contacto y datos complementarios para la práctica

---

## Stack Tecnológico

**Backend**
- Python 3.13
- Django 5.2.1
- PostgreSQL (producción) / SQLite (desarrollo)
- Gunicorn (servidor WSGI)

**Frontend**
- Tailwind CSS con paleta personalizada (`principal`, `secundario`, `fondo`, `blanco`)
- Tipografía: Cinzel (encabezados) + Google Fonts
- JavaScript ES6+ — sistema de modales personalizados (reemplazo de `confirm()` nativo)
- Diseño responsive, mobile-first

**Infraestructura**
- Nginx como proxy reverso
- Certbot / Let's Encrypt para HTTPS
- python-decouple para variables de entorno
- Cron jobs para automatización mensual

---

## Estructura del Proyecto

```
PilatesGravity/
├── PilatesGravity/          # Configuración principal
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── gravity/                 # App principal del negocio
│   ├── models.py            # Clase, Reserva, Planes, Pagos, Deudas
│   ├── views.py             # Vistas de clientes y administradores
│   ├── forms.py             # Formularios con validaciones
│   ├── urls.py
│   └── templates/gravity/
│       ├── admin/           # Panel administrativo
│       └── ...              # Templates de clientes
│
├── accounts/                # Autenticación y perfiles
│   ├── models.py            # UserProfile
│   ├── views.py
│   └── templates/accounts/
│
├── templates/               # Templates globales y componentes
├── static/                  # CSS, JS, imágenes
├── media/                   # Archivos subidos
└── requirements.txt
```

---

## Instalación local

### Requisitos

- Python 3.13+
- Node.js 18+ (para compilar Tailwind CSS)
- Git

### Pasos

```bash
# Clonar el repositorio
git clone https://github.com/Piccoli4/PilatesGravity.git
cd PilatesGravity

# Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# Instalar dependencias Python
pip install -r requirements.txt

# Instalar dependencias de Node (Tailwind)
npm install

# Configurar variables de entorno
cp .env.example .env
# Editar .env con los valores correspondientes

# Aplicar migraciones
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser

# Compilar CSS de Tailwind
npm run build-css-prod

# Iniciar servidor de desarrollo
python manage.py runserver
```

---

## Despliegue en Producción

El stack de producción recomendado es:

- **Ubuntu 24.04 LTS** (VPS limpio, sin panel de control)
- **Nginx** como proxy reverso
- **Gunicorn** como servidor WSGI
- **PostgreSQL** como base de datos
- **Certbot** para certificados SSL

Las variables sensibles se gestionan con `python-decouple` a través de un archivo `.env` en el servidor.

### Cron jobs necesarios

```bash
# Generar deudas el 1° de cada mes a las 00:05
5 0 1 * * /ruta/al/entorno/python manage.py generar_deudas_mensuales

# Verificar deudas vencidas diariamente a las 08:00
0 8 * * * /ruta/al/entorno/python manage.py verificar_deudas_vencidas
```

---

## Roadmap

- [ ] Sistema de lista de espera automática
- [ ] Integración con pasarela de pago online
- [ ] API REST para aplicación móvil
- [ ] Notificaciones push
- [ ] Dashboard de analytics avanzado
- [ ] CI/CD automatizado

---

## Desarrollador

**Guido Augusto Piccoli**
- GitHub: [github.com/Piccoli4](https://github.com/Piccoli4)
- LinkedIn: [linkedin.com/in/piccoli-augusto](https://www.linkedin.com/in/piccoli-augusto/)
- Email: piccoli_44@hotmail.com
- Porfolio: [piccoliaugusto.com.ar](https://piccoliaugusto.com.ar/)
---

*Stack: Python 3.13 · Django 5.2 · PostgreSQL · Tailwind CSS*