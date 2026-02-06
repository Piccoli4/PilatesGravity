#!/usr/bin/env python
"""
Script COMPLETO para generar datos de prueba para PilatesGravity
Genera todos los datos necesarios en un solo paso:
- Configuración del estudio
- Administradores (Nico y Cami)
- Clientes con perfiles
- Planes de pago
- Clases en ambas sedes
- Planes asignados a usuarios
- Estados de pago
- Registros de pagos históricos
- Deudas mensuales
- Reservas activas

Ejecutar: python generar_datos_prueba.py
"""

import os
import sys
import django
from datetime import datetime, date, timedelta, time
from decimal import Decimal
import random

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PilatesGravity.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Count, Sum, Q
import django.db.models as models

from gravity.models import (
    Clase, Reserva, PlanPago, EstadoPagoCliente, 
    RegistroPago, DeudaMensual, PlanUsuario
)
from accounts.models import UserProfile, ConfiguracionEstudio


def print_header(mensaje):
    """Imprime un encabezado destacado"""
    print("\n" + "="*70)
    print(f"🚀 {mensaje}")
    print("="*70)


def print_success(mensaje):
    """Imprime un mensaje de éxito"""
    print(f"✅ {mensaje}")


def print_separator():
    """Imprime un separador simple"""
    print("-" * 70)


def limpiar_datos():
    """Elimina todos los datos existentes para empezar de cero"""
    print_header("LIMPIANDO BASE DE DATOS")
    
    print("🗑️  Eliminando datos existentes...")
    
    # Eliminar en orden para evitar problemas de claves foráneas
    DeudaMensual.objects.all().delete()
    RegistroPago.objects.all().delete()
    PlanUsuario.objects.all().delete()
    Reserva.objects.all().delete()
    EstadoPagoCliente.objects.all().delete()
    Clase.objects.all().delete()
    PlanPago.objects.all().delete()
    UserProfile.objects.all().delete()
    ConfiguracionEstudio.objects.all().delete()
    User.objects.all().delete()
    
    print_success("Datos eliminados correctamente")


def crear_configuracion_estudio():
    """Crea la configuración básica del estudio"""
    print_header("CREANDO CONFIGURACIÓN DEL ESTUDIO")
    
    config = ConfiguracionEstudio.objects.create(
        nombre_estudio="Pilates Gravity",
        telefono_contacto="+54 342 511 4448",
        email_contacto="info@pilatesgravity.com",
        
        # Configuración sede principal
        sede_principal_activa=True,
        sede_principal_telefono="+54 342 511 4448",
        sede_principal_email="sede1@pilatesgravity.com",
        sede_principal_horarios="Lunes a Viernes: 07:00 - 21:00\nSábados: 09:00 - 15:00",
        sede_principal_capacidad_maxima=4,
        
        # Configuración sede 2
        sede_2_activa=True,
        sede_2_telefono="+54 342 511 4449",
        sede_2_email="sede2@pilatesgravity.com",
        sede_2_horarios="Lunes a Viernes: 08:00 - 20:00\nSábados: 10:00 - 14:00",
        sede_2_capacidad_maxima=3,
        
        # Configuraciones de reservas
        horas_anticipacion_cancelacion=2,
        max_reservas_por_usuario=5,
        
        # Configuraciones de notificaciones
        enviar_recordatorios=True,
        horas_antes_recordatorio=24,
        enviar_marketing_sede_principal=True,
        enviar_marketing_sede_2=True,
        
        # Mensajes
        mensaje_bienvenida="¡Bienvenido a Pilates Gravity! Transformamos cuerpos y mentes a través del Pilates.",
        mensaje_sede_principal="Nuestra sede principal en La Rioja 3044 cuenta con equipos Reformer y Cadillac de última generación.",
        mensaje_sede_2="Nuestra segunda sede en 9 de julio 3696 ofrece un ambiente íntimo y personalizado.",
        
        activo=True
    )
    
    print_success(f"Configuración creada: {config.nombre_estudio}")
    print(f"   📍 Sede Principal: {config.sede_principal_telefono}")
    print(f"   📍 Sede 2: {config.sede_2_telefono}")
    
    return config


def crear_administradores():
    """Crea los usuarios administradores"""
    print_header("CREANDO ADMINISTRADORES")
    
    # Nicolás Castella
    nico = User.objects.create_user(
        username='Nico',
        email='nico@pilatesgravity.com',
        password='admin123',
        first_name='Nicolás',
        last_name='Castella',
        is_staff=True,
        is_superuser=True,
        is_active=True
    )
    
    # Obtener el perfil creado automáticamente por signal y actualizarlo
    nico_profile = UserProfile.objects.get(user=nico)
    nico_profile.telefono = "+543425114448"
    nico_profile.sede_preferida = 'sede_principal'
    nico_profile.fecha_nacimiento = date(1985, 3, 15)
    nico_profile.tiene_lesiones = False
    nico_profile.nivel_experiencia = 'instructor'
    nico_profile.acepta_marketing = True
    nico_profile.acepta_recordatorios = True
    nico_profile.perfil_completado = True
    nico_profile.notas_admin = "Administrador principal - Instructor certificado"
    nico_profile.save()
    
    # Camila Tibaldo
    cami = User.objects.create_user(
        username='Cami',
        email='cami@pilatesgravity.com',
        password='admin123',
        first_name='Camila',
        last_name='Tibaldo',
        is_staff=True,
        is_superuser=True,
        is_active=True
    )
    
    # Obtener el perfil creado automáticamente y actualizarlo
    cami_profile = UserProfile.objects.get(user=cami)
    cami_profile.telefono = "+543425114449"
    cami_profile.sede_preferida = 'sede_2'
    cami_profile.fecha_nacimiento = date(1988, 7, 22)
    cami_profile.tiene_lesiones = False
    cami_profile.nivel_experiencia = 'instructor'
    cami_profile.acepta_marketing = True
    cami_profile.acepta_recordatorios = True
    cami_profile.perfil_completado = True
    cami_profile.notas_admin = "Administradora - Especialista en rehabilitación"
    cami_profile.save()
    
    print_success(f"Administradores creados: {nico.username}, {cami.username}")
    
    return nico, cami


def crear_planes_pago():
    """Crea planes de pago variados"""
    print_header("CREANDO PLANES DE PAGO")
    
    planes = []
    
    # Planes mensuales regulares
    planes_mensuales = [
        {"nombre": "Plan Principiante - 1 Clase Semanal", "clases": 1, "precio": 25000},
        {"nombre": "Plan Básico - 2 Clases Semanales", "clases": 2, "precio": 45000},
        {"nombre": "Plan Intermedio - 3 Clases Semanales", "clases": 3, "precio": 60000},
        {"nombre": "Plan Avanzado - 4 Clases Semanales", "clases": 4, "precio": 70000},
        {"nombre": "Plan Premium - 5 Clases Semanales", "clases": 5, "precio": 80000},
        {"nombre": "Plan Ilimitado", "clases": 10, "precio": 95000},
    ]
    
    for plan_data in planes_mensuales:
        plan = PlanPago.objects.create(
            nombre=plan_data["nombre"],
            clases_por_semana=plan_data["clases"],
            precio_mensual=plan_data["precio"],
            tipo_plan='mensual',
            descripcion=f"Plan mensual de {plan_data['clases']} clase(s) por semana. Pago mensual adelantado.",
            activo=True
        )
        planes.append(plan)
    
    # Planes por clase individual
    planes_individuales = [
        {"nombre": "Clase Individual Reformer", "precio": 8000, "desc": "Clase individual en equipo Reformer"},
        {"nombre": "Clase Individual Cadillac", "precio": 9000, "desc": "Clase individual en equipo Cadillac"},
        {"nombre": "Clase Prenatal", "precio": 10000, "desc": "Clase especial para embarazadas"},
        {"nombre": "Clase de Rehabilitación", "precio": 12000, "desc": "Clase terapéutica post-lesión"},
        {"nombre": "Clase de Evaluación", "precio": 6000, "desc": "Primera clase de evaluación"},
    ]
    
    for plan_data in planes_individuales:
        plan = PlanPago.objects.create(
            nombre=plan_data["nombre"],
            clases_por_semana=0,
            precio_mensual=0,
            tipo_plan='por_clase',
            precio_por_clase=plan_data["precio"],
            descripcion=plan_data["desc"],
            activo=True
        )
        planes.append(plan)
    
    print_success(f"Planes creados: {len(planes)} ({len(planes_mensuales)} mensuales + {len(planes_individuales)} por clase)")
    
    return planes


def crear_clases():
    """Crea clases variadas en ambas sedes"""
    print_header("CREANDO CLASES")
    
    clases = []
    
    # Tipos de clases regulares (Lun-Vie)
    tipos_clases = [
        {"tipo": "Reformer", "cupo": 4},
        {"tipo": "Cadillac", "cupo": 3},
    ]
    
    # Horarios regulares
    horarios_regulares = [
        time(7, 0), time(8, 30), time(10, 0), time(11, 30),
        time(15, 0), time(16, 30), time(18, 0), time(19, 30)
    ]
    
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    
    # Crear clases regulares
    for tipo_data in tipos_clases:
        for dia in dias_semana:
            for horario in horarios_regulares:
                for sede in ['sede_principal', 'sede_2']:
                    clase = Clase.objects.create(
                        tipo=tipo_data["tipo"],
                        direccion=sede,
                        dia=dia,
                        horario=horario,
                        cupo_maximo=tipo_data["cupo"],
                        activa=True
                    )
                    clases.append(clase)
    
    # Clases especiales (incluye sábados)
    clases_especiales = [
        {"nombre": "Pilates Prenatal", "horario": time(9, 0), "dias": ["Martes", "Jueves"]},
        {"nombre": "Pilates para Seniors", "horario": time(10, 30), "dias": ["Lunes", "Miércoles", "Viernes"]},
        {"nombre": "Rehabilitación Postural", "horario": time(14, 0), "dias": ["Sábado"]},
        {"nombre": "Workshop Pilates Avanzado", "horario": time(15, 30), "dias": ["Sábado"]},
        {"nombre": "Evaluación Inicial", "horario": time(16, 0), "dias": ["Lunes", "Miércoles"]},
    ]
    
    for especial in clases_especiales:
        for dia in especial["dias"]:
            for sede in ['sede_principal', 'sede_2']:
                clase = Clase.objects.create(
                    tipo='Especial',
                    nombre_personalizado=especial["nombre"],
                    direccion=sede,
                    dia=dia,
                    horario=especial["horario"],
                    cupo_maximo=3 if especial["nombre"] != "Evaluación Inicial" else 1,
                    activa=True
                )
                clases.append(clase)
    
    print_success(f"Clases creadas: {len(clases)}")
    
    return clases


def crear_clientes():
    """Crea clientes con perfiles realistas y variados"""
    print_header("CREANDO CLIENTES")
    
    nombres = [
        ("María", "González"), ("Juan", "Pérez"), ("Ana", "Martínez"), ("Carlos", "López"),
        ("Laura", "García"), ("Diego", "Rodríguez"), ("Sofía", "Hernández"), ("Pablo", "Torres"),
        ("Valentina", "Flores"), ("Mateo", "Díaz"), ("Isabella", "Ruiz"), ("Santiago", "Morales"),
        ("Camila", "Jiménez"), ("Sebastián", "Castro"), ("Lucía", "Ortega"), ("Nicolás", "Ramos"),
        ("Martina", "Vargas"), ("Tomás", "Mendoza"), ("Emma", "Silva"), ("Benjamín", "Guerrero"),
        ("Olivia", "Medina"), ("Lucas", "Rojas"), ("Mía", "Herrera"), ("Matías", "Aguilar"),
        ("Zoe", "Delgado"), ("Felipe", "Moreno"), ("Amanda", "Peña"), ("Ignacio", "Romero"),
        ("Renata", "Soto"), ("Joaquín", "Contreras"), ("Abril", "Guzmán"), ("Emilio", "Arias"),
        ("Julieta", "Cáceres"), ("Adrián", "Espinoza"), ("Catalina", "Figueroa"), ("Rodrigo", "Navarro"),
        ("Antonella", "Campos"), ("Bruno", "Santana"), ("Isidora", "Vega"), ("Máximo", "Cortés"),
        ("Constanza", "Bravo"), ("Agustín", "Pardo"), ("Florencia", "Muñoz"), ("Vicente", "Sáez"),
        ("Antonia", "Molina"), ("Cristóbal", "Valdés"), ("Magdalena", "Toro"), ("Gaspar", "Araya"),
        ("Esperanza", "Carrasco"), ("Clemente", "Fuentes")
    ]
    
    clientes = []
    niveles_experiencia = ['principiante', 'intermedio', 'avanzado']
    sedes_preferidas = ['cualquiera', 'sede_principal', 'sede_2']
    lesiones_ejemplos = [
        "",
        "Dolor lumbar crónico por trabajo de oficina",
        "Lesión en rodilla derecha - post cirugía de menisco", 
        "Problemas cervicales y contracturas",
        "Escoliosis leve - trabajo correctivo",
        "Fibromialgia en tratamiento",
        "Post-parto - fortalecimiento del core",
        "Artrosis en cadera izquierda",
        "Hernia discal L4-L5 operada hace 1 año"
    ]
    
    for i, (nombre, apellido) in enumerate(nombres):
        # Crear usuario
        username = f"{nombre.lower()}.{apellido.lower()}"
        email = f"{username}@example.com"
        
        cliente = User.objects.create_user(
            username=username,
            email=email,
            password='usuarios123',
            first_name=nombre,
            last_name=apellido,
            is_staff=False,
            is_superuser=False,
            is_active=True
        )
        
        # Datos aleatorios pero realistas para perfil
        telefono = f"+54342{random.randint(400, 599)}{random.randint(1000, 9999)}"
        fecha_nacimiento = date(
            year=random.randint(1970, 2005),
            month=random.randint(1, 12),
            day=random.randint(1, 28)
        )
        
        # Determinar lesiones
        tiene_lesiones = random.choice([True, False, False, False])
        descripcion_lesiones = ""
        if tiene_lesiones:
            descripcion_lesiones = random.choice([l for l in lesiones_ejemplos if l])
        
        # Fecha de primera clase
        fecha_primera = None
        sede_primera = None
        if random.choice([True, True, False]):
            fecha_primera = date.today() - timedelta(days=random.randint(30, 365*2))
            sede_primera = random.choice(['sede_principal', 'sede_2'])
        
        # Obtener y actualizar perfil
        perfil = UserProfile.objects.get(user=cliente)
        perfil.telefono = telefono
        perfil.sede_preferida = random.choice(sedes_preferidas)
        perfil.fecha_nacimiento = fecha_nacimiento
        perfil.tiene_lesiones = tiene_lesiones
        perfil.descripcion_lesiones = descripcion_lesiones
        perfil.nivel_experiencia = random.choice(niveles_experiencia)
        perfil.acepta_marketing = random.choice([True, False])
        perfil.acepta_recordatorios = random.choice([True, True, True, False])
        perfil.notificar_clases_sede_principal = random.choice([True, False])
        perfil.notificar_clases_sede_2 = random.choice([True, False])
        perfil.fecha_primera_clase = fecha_primera
        perfil.sede_primera_clase = sede_primera
        perfil.perfil_completado = random.choice([True, True, False])
        perfil.notas_admin = random.choice([
            "", 
            "Cliente muy comprometido",
            "Requiere atención especial por lesiones",
            "Alumno avanzado - puede ayudar a principiantes",
            "Pago siempre puntual",
            "Familia numerosa - descuentos aplicados"
        ])
        perfil.save()
        
        clientes.append(cliente)
    
    print_success(f"Clientes creados: {len(clientes)} con perfiles completos")
    
    return clientes


def asignar_planes_usuarios(clientes, planes):
    """Asigna planes de pago a los usuarios"""
    print_header("ASIGNANDO PLANES A USUARIOS")
    
    planes_mensuales = [p for p in planes if p.tipo_plan == 'mensual']
    planes_creados = []
    usuarios_con_plan = []
    usuarios_sin_plan = []
    
    for usuario in clientes:
        # 80% tiene plan mensual, 20% sin plan (paga por clase)
        tiene_plan = random.random() < 0.8
        
        if tiene_plan:
            plan_seleccionado = random.choice(planes_mensuales)
            
            # Determinar fechas del plan
            meses_antiguedad = random.choice([0, 1, 2, 3, 4, 5, 6, 8, 12])
            fecha_inicio = date.today() - timedelta(days=30 * meses_antiguedad)
            
            # 90% con plan vigente, 10% vencido
            if random.random() < 0.9:
                fecha_fin = date.today() + timedelta(days=random.randint(15, 45))
            else:
                fecha_fin = date.today() - timedelta(days=random.randint(1, 15))
            
            plan_usuario = PlanUsuario.objects.create(
                usuario=usuario,
                plan=plan_seleccionado,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                activo=True,
                tipo_plan='permanente',
                renovacion_automatica=random.choice([True, True, True, False]),
                observaciones=random.choice([
                    "",
                    "Plan promocional - primer mes",
                    "Cliente referido - descuento aplicado",
                    "Upgrade desde plan básico",
                    "Renovación automática activada"
                ])
            )
            planes_creados.append(plan_usuario)
            usuarios_con_plan.append(usuario)
        else:
            usuarios_sin_plan.append(usuario)
    
    print_success(f"Planes asignados: {len(usuarios_con_plan)} con plan, {len(usuarios_sin_plan)} sin plan")
    
    return usuarios_con_plan, usuarios_sin_plan


def crear_estados_pago(usuarios_con_plan, usuarios_sin_plan):
    """Crea estados de pago variados para todos los usuarios"""
    print_header("CREANDO ESTADOS DE PAGO")
    
    estados_creados = []
    todos_usuarios = usuarios_con_plan + usuarios_sin_plan
    
    for usuario in todos_usuarios:
        tiene_plan = usuario in usuarios_con_plan
        
        # Obtener plan del usuario
        plan_actual = None
        if tiene_plan:
            plan_usuario = PlanUsuario.objects.filter(usuario=usuario, activo=True).first()
            if plan_usuario:
                plan_actual = plan_usuario.plan
        
        # Determinar escenario de pago
        if tiene_plan:
            escenario = random.choices(
                ['al_dia', 'deuda_pequena', 'deuda_grande', 'credito_favor', 'deuda_vencida'],
                weights=[50, 20, 10, 10, 10],
                k=1
            )[0]
        else:
            escenario = random.choices(['al_dia', 'credito_favor'], weights=[70, 30], k=1)[0]
        
        # Crear datos según escenario
        if escenario == 'al_dia':
            saldo_actual = Decimal('0.00')
            ultimo_pago = date.today().replace(day=1)
            monto_ultimo_pago = plan_actual.precio_mensual if plan_actual else Decimal('0.00')
            puede_reservar = True
            ultimo_mes_cobrado = date.today().replace(day=1)
            
        elif escenario == 'deuda_pequena':
            saldo_actual = random.choice([Decimal('-15000.00'), Decimal('-25000.00'), Decimal('-8000.00')])
            ultimo_pago = date.today().replace(day=1) - timedelta(days=30)
            monto_ultimo_pago = plan_actual.precio_mensual if plan_actual else Decimal('0.00')
            puede_reservar = True
            ultimo_mes_cobrado = (date.today().replace(day=1) - timedelta(days=30))
            
        elif escenario == 'deuda_grande':
            saldo_actual = random.choice([Decimal('-50000.00'), Decimal('-75000.00'), Decimal('-120000.00')])
            ultimo_pago = date.today().replace(day=1) - timedelta(days=60)
            monto_ultimo_pago = plan_actual.precio_mensual if plan_actual else Decimal('0.00')
            puede_reservar = False
            ultimo_mes_cobrado = (date.today().replace(day=1) - timedelta(days=60))
            
        elif escenario == 'credito_favor':
            saldo_actual = random.choice([Decimal('10000.00'), Decimal('25000.00'), Decimal('45000.00')])
            ultimo_pago = date.today().replace(day=1)
            monto_ultimo_pago = plan_actual.precio_mensual * 2 if plan_actual else Decimal('20000.00')
            puede_reservar = True
            ultimo_mes_cobrado = date.today().replace(day=1)
            
        elif escenario == 'deuda_vencida':
            saldo_actual = random.choice([Decimal('-45000.00'), Decimal('-60000.00'), Decimal('-90000.00')])
            ultimo_pago = date.today().replace(day=1) - timedelta(days=90)
            monto_ultimo_pago = plan_actual.precio_mensual if plan_actual else Decimal('0.00')
            puede_reservar = False
            ultimo_mes_cobrado = (date.today().replace(day=1) - timedelta(days=45))
        
        # Crear estado de pago con TODOS los campos correctos
        estado = EstadoPagoCliente.objects.create(
            usuario=usuario,
            plan_actual=plan_actual,
            ultimo_pago=ultimo_pago,
            monto_ultimo_pago=monto_ultimo_pago,
            saldo_actual=saldo_actual,
            observaciones=random.choice([
                "",
                "Cliente cumplidor",
                "Requiere seguimiento de pagos",
                "Historial de pagos irregular",
                "Cliente nuevo - primer mes",
                "Acuerdo de pago especial"
            ]),
            activo=True,
            ultimo_mes_cobrado=ultimo_mes_cobrado,
            puede_reservar=puede_reservar,
            fecha_limite_pago=date.today().replace(day=10),
            monto_deuda_mensual=abs(saldo_actual) if saldo_actual < 0 else Decimal('0.00')
        )
        estados_creados.append(estado)
    
    al_dia = sum(1 for e in estados_creados if e.saldo_actual >= 0)
    con_deuda = sum(1 for e in estados_creados if e.saldo_actual < 0 and e.puede_reservar)
    bloqueados = sum(1 for e in estados_creados if not e.puede_reservar)
    
    print_success(f"Estados de pago: {len(estados_creados)} ({al_dia} al día, {con_deuda} con deuda, {bloqueados} bloqueados)")
    
    return estados_creados


def crear_registros_pagos(usuarios_con_plan, administradores):
    """Crea registros de pagos históricos"""
    print_header("CREANDO REGISTROS DE PAGOS HISTÓRICOS")
    
    pagos_creados = []
    tipos_pago = ['efectivo', 'transferencia', 'tarjeta']
    
    for usuario in usuarios_con_plan:
        # Obtener el plan del usuario
        plan_usuario = PlanUsuario.objects.filter(usuario=usuario, activo=True).first()
        if not plan_usuario:
            continue
        
        # Cantidad de pagos históricos (entre 1 y 12 meses)
        meses_pagos = random.randint(1, 12)
        
        for i in range(meses_pagos):
            # Fecha del pago (mes a mes hacia atrás)
            fecha_pago = date.today() - timedelta(days=30 * i)
            
            # Monto (generalmente el precio del plan, a veces con variaciones)
            if random.random() < 0.9:
                monto = plan_usuario.plan.precio_mensual
            else:
                factor = Decimal(str(random.choice([0.5, 1.5, 2.0])))
                monto = (plan_usuario.plan.precio_mensual * factor).quantize(Decimal('0.01'))
            
            # Crear registro de pago
            pago = RegistroPago.objects.create(
                cliente=usuario,
                monto=monto,
                fecha_pago=fecha_pago,
                tipo_pago=random.choice(tipos_pago),
                estado='confirmado',
                concepto=f"Pago mensual {fecha_pago.strftime('%B %Y')}",
                observaciones=random.choice([
                    "",
                    "Pago puntual",
                    "Pago con descuento promocional",
                    "Incluye mes siguiente",
                    "Pago parcial"
                ]),
                comprobante=f"COMP-{random.randint(1000, 9999)}",
                registrado_por=random.choice(administradores)
            )
            pagos_creados.append(pago)
    
    print_success(f"Registros de pago: {len(pagos_creados)}")
    
    return pagos_creados


def crear_deudas_mensuales(usuarios_con_plan):
    """Crea deudas mensuales para los usuarios"""
    print_header("CREANDO DEUDAS MENSUALES")
    
    deudas_creadas = []
    
    # Crear deudas para los últimos 3 meses
    for i in range(3):
        mes_año = date.today().replace(day=1) - timedelta(days=30 * i)
        
        for usuario in usuarios_con_plan:
            # Obtener plan vigente en ese mes
            plan_usuario = PlanUsuario.objects.filter(
                usuario=usuario,
                activo=True,
                fecha_inicio__lte=mes_año
            ).first()
            
            if not plan_usuario:
                continue
            
            # Determinar estado de la deuda
            if i == 0:  # Mes actual
                estados_posibles = ['pendiente', 'pagado', 'parcial']
                estado = random.choices(estados_posibles, weights=[40, 50, 10], k=1)[0]
            elif i == 1:  # Mes anterior
                estados_posibles = ['pagado', 'vencido', 'parcial']
                estado = random.choices(estados_posibles, weights=[70, 20, 10], k=1)[0]
            else:  # Hace 2 meses
                estados_posibles = ['pagado', 'vencido']
                estado = random.choices(estados_posibles, weights=[90, 10], k=1)[0]
            
            # Calcular monto
            monto_original = plan_usuario.plan.precio_mensual
            if estado == 'pagado':
                monto_pendiente = Decimal('0.00')
            elif estado == 'parcial':
                monto_pendiente = monto_original * Decimal('0.5')
            else:  # pendiente o vencido
                monto_pendiente = monto_original
            
            # Fecha de vencimiento (día 10 del mes)
            fecha_vencimiento = mes_año.replace(day=10)
            
            # Crear deuda
            deuda = DeudaMensual.objects.create(
                usuario=usuario,
                mes_año=mes_año,
                plan_aplicado=plan_usuario.plan,
                monto_original=monto_original,
                monto_pendiente=monto_pendiente,
                es_medio_mes=False,
                estado=estado,
                fecha_vencimiento=fecha_vencimiento,
                observaciones=random.choice([
                    "",
                    "Generada automáticamente",
                    "Deuda prorrateada",
                    "Incluye ajuste de precio"
                ])
            )
            deudas_creadas.append(deuda)
    
    pendientes = sum(1 for d in deudas_creadas if d.estado == 'pendiente')
    vencidas = sum(1 for d in deudas_creadas if d.estado == 'vencido')
    pagadas = sum(1 for d in deudas_creadas if d.estado == 'pagado')
    
    print_success(f"Deudas mensuales: {len(deudas_creadas)} ({pendientes} pendientes, {vencidas} vencidas, {pagadas} pagadas)")
    
    return deudas_creadas


def crear_reservas(usuarios_con_plan, usuarios_sin_plan, clases):
    """Crea reservas activas para los usuarios"""
    print_header("CREANDO RESERVAS ACTIVAS")
    
    reservas_creadas = []
    
    for usuario in usuarios_con_plan + usuarios_sin_plan:
        # Verificar si puede reservar
        estado_pago = EstadoPagoCliente.objects.filter(usuario=usuario).first()
        if not estado_pago or not estado_pago.puede_reservar:
            continue
        
        # Obtener plan del usuario
        plan_usuario = PlanUsuario.objects.filter(
            usuario=usuario,
            activo=True,
            fecha_inicio__lte=date.today(),
            fecha_fin__gte=date.today()
        ).first()
        
        # Determinar cuántas clases reservar
        if plan_usuario:
            max_reservas = min(plan_usuario.plan.clases_por_semana, 5)
            cantidad_reservas = random.randint(1, max_reservas)
        else:
            cantidad_reservas = random.randint(1, 2)
        
        # Crear reservas
        clases_reservadas = []
        for _ in range(cantidad_reservas):
            clases_disponibles = [c for c in clases 
                                if c.cupos_disponibles() > 0 
                                and c not in clases_reservadas]
            
            if not clases_disponibles:
                break
            
            clase_seleccionada = random.choice(clases_disponibles)
            clases_reservadas.append(clase_seleccionada)
            
            reserva = Reserva.objects.create(
                usuario=usuario,
                clase=clase_seleccionada,
                activa=True,
                notas=random.choice([
                    "",
                    "Confirmado por teléfono",
                    "Primera clase del usuario",
                    "Reserva recurrente",
                    "Cliente regular"
                ])
            )
            reservas_creadas.append(reserva)
    
    sede_principal = sum(1 for r in reservas_creadas if r.clase.direccion == 'sede_principal')
    sede_2 = sum(1 for r in reservas_creadas if r.clase.direccion == 'sede_2')
    
    print_success(f"Reservas activas: {len(reservas_creadas)} ({sede_principal} sede principal, {sede_2} sede 2)")
    
    return reservas_creadas


def generar_estadisticas_finales():
    """Genera un resumen completo de todos los datos creados"""
    print_header("RESUMEN FINAL")
    
    # Usuarios
    total_usuarios = User.objects.filter(is_staff=False).count()
    print(f"\n👥 USUARIOS: {total_usuarios}")
    
    # Planes
    planes_activos = PlanUsuario.objects.filter(activo=True).count()
    print(f"\n📋 PLANES ACTIVOS: {planes_activos}")
    
    # Estados de pago
    estados = EstadoPagoCliente.objects.all()
    al_dia = estados.filter(saldo_actual__gte=0).count()
    con_deuda = estados.filter(saldo_actual__lt=0, puede_reservar=True).count()
    bloqueados = estados.filter(puede_reservar=False).count()
    
    print(f"\n💳 ESTADOS DE PAGO:")
    print(f"   ✓ Al día: {al_dia}")
    print(f"   ⚠️  Con deuda pendiente: {con_deuda}")
    print(f"   🚫 Bloqueados: {bloqueados}")
    
    # Pagos
    total_pagos = RegistroPago.objects.count()
    monto_total = RegistroPago.objects.aggregate(
        total=Sum('monto')
    )['total'] or Decimal('0.00')
    
    print(f"\n💵 REGISTROS DE PAGO: {total_pagos}")
    print(f"   💰 Monto total registrado: ${monto_total:,.2f}")
    
    # Deudas
    deudas = DeudaMensual.objects.all()
    deudas_pendientes = deudas.filter(estado='pendiente').count()
    deudas_vencidas = deudas.filter(estado='vencido').count()
    deudas_pagadas = deudas.filter(estado='pagado').count()
    
    print(f"\n📅 DEUDAS MENSUALES: {deudas.count()}")
    print(f"   📋 Pendientes: {deudas_pendientes}")
    print(f"   ⚠️  Vencidas: {deudas_vencidas}")
    print(f"   ✓ Pagadas: {deudas_pagadas}")
    
    # Reservas
    reservas_activas = Reserva.objects.filter(activa=True).count()
    print(f"\n📅 RESERVAS ACTIVAS: {reservas_activas}")
    
    # Clases con más reservas
    clases_populares = Clase.objects.filter(activa=True).annotate(
        total_reservas=models.Count('reserva', filter=models.Q(reserva__activa=True))
    ).order_by('-total_reservas')[:5]
    
    print(f"\n🔥 TOP 5 CLASES MÁS POPULARES:")
    for i, clase in enumerate(clases_populares, 1):
        print(f"   {i}. {clase.get_nombre_display()} - {clase.dia} {clase.horario.strftime('%H:%M')} ({clase.total_reservas} reservas)")
    
    print("\n" + "="*70)
    print("✅ BASE DE DATOS LISTA PARA USAR")
    print("="*70)
    print("\n🔑 CREDENCIALES DE ACCESO:")
    print("   👑 Admins: Nico/Cami - password: admin123")
    print("   👥 Clientes: nombre.apellido - password: usuarios123")
    print("\n")


if __name__ == "__main__":
    print("\n" + "🎉"*35)
    print("SCRIPT DE GENERACIÓN DE DATOS DE PRUEBA - PILATES GRAVITY")
    print("🎉"*35)
    print("\n📋 Este script generará:")
    print("   ✓ Configuración del estudio")
    print("   ✓ 2 Administradores (Nico y Cami)")
    print("   ✓ 50 Clientes con perfiles detallados")
    print("   ✓ 11 Planes de pago (6 mensuales + 5 por clase)")
    print("   ✓ ~80 Clases en ambas sedes")
    print("   ✓ Planes asignados a usuarios")
    print("   ✓ Estados de pago variados")
    print("   ✓ Registros de pagos históricos")
    print("   ✓ Deudas mensuales")
    print("   ✓ Reservas activas\n")
    
    try:
        # Paso 1: Limpiar base de datos
        limpiar_datos()
        
        # Paso 2: Crear configuración del estudio
        config = crear_configuracion_estudio()
        
        # Paso 3: Crear administradores
        nico, cami = crear_administradores()
        administradores = [nico, cami]
        
        # Paso 4: Crear planes de pago
        planes = crear_planes_pago()
        
        # Paso 5: Crear clases
        clases = crear_clases()
        
        # Paso 6: Crear clientes
        clientes = crear_clientes()
        
        # Paso 7: Asignar planes a usuarios
        usuarios_con_plan, usuarios_sin_plan = asignar_planes_usuarios(clientes, planes)
        
        # Paso 8: Crear estados de pago
        estados = crear_estados_pago(usuarios_con_plan, usuarios_sin_plan)
        
        # Paso 9: Crear registros de pagos
        pagos = crear_registros_pagos(usuarios_con_plan, administradores)
        
        # Paso 10: Crear deudas mensuales
        deudas = crear_deudas_mensuales(usuarios_con_plan)
        
        # Paso 11: Crear reservas activas
        reservas = crear_reservas(usuarios_con_plan, usuarios_sin_plan, clases)
        
        # Resumen final
        generar_estadisticas_finales()
        
    except Exception as e:
        print(f"\n❌ ERROR DURANTE LA GENERACIÓN: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)