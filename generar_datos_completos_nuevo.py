#!/usr/bin/env python
"""
Script completo para generar datos ficticios para Pilates Gravity
NUEVO SISTEMA DE PAGOS - Versión 2024

Uso: python generar_datos_testing_completo.py
"""

import os
import sys
import django
import random
from datetime import datetime, timedelta, time, date
from decimal import Decimal

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PilatesGravity.settings')
django.setup()

# Importar modelos de Django
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction
from django.utils.crypto import get_random_string
from django.core.exceptions import ValidationError

# Importar modelos de la aplicación
from gravity.models import (
    Clase, Cliente, Reserva, 
    PlanPago, EstadoPagoCliente, RegistroPago
)
from accounts.models import UserProfile

# Colores para mensajes
class Colors:
    SUCCESS = '\033[92m'
    WARNING = '\033[93m' 
    ERROR = '\033[91m'
    INFO = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_success(message):
    print(f"{Colors.SUCCESS}✅ {message}{Colors.END}")

def print_warning(message):
    print(f"{Colors.WARNING}⚠️  {message}{Colors.END}")

def print_error(message):
    print(f"{Colors.ERROR}❌ {message}{Colors.END}")

def print_info(message):
    print(f"{Colors.INFO}ℹ️  {message}{Colors.END}")

def print_bold(message):
    print(f"{Colors.BOLD}{message}{Colors.END}")

def limpiar_datos_existentes():
    """Limpia todos los datos existentes para empezar de cero"""
    print_bold("🧹 Limpiando datos existentes...")
    
    try:
        # Orden correcto para evitar problemas de claves foráneas
        RegistroPago.objects.all().delete()
        EstadoPagoCliente.objects.all().delete()
        PlanPago.objects.all().delete()
        Reserva.objects.all().delete()
        Clase.objects.all().delete()
        Cliente.objects.all().delete()
        
        # Eliminar usuarios no superuser y sus perfiles
        User.objects.filter(is_superuser=False).delete()
        
        print_success("Limpieza completada")
        
    except Exception as e:
        print_error(f"Error durante la limpieza: {str(e)}")
        raise

def crear_administradores():
    """Crea los 2 administradores principales"""
    print_bold("👑 Creando administradores...")
    
    admins_data = [
        {
            'username': 'Nico',
            'first_name': 'Nicolás',
            'last_name': 'Castella',
            'email': 'nicolas@pilatesgravity.com',
            'password': 'admin123'
        },
        {
            'username': 'Cami',
            'first_name': 'Camila',
            'last_name': 'Tibaldo',
            'email': 'camila@pilatesgravity.com',
            'password': 'admin123'
        }
    ]
    
    admins_creados = []
    
    for admin_data in admins_data:
        if User.objects.filter(username=admin_data['username']).exists():
            print_warning(f"Usuario {admin_data['username']} ya existe, saltando...")
            continue
            
        admin = User.objects.create_superuser(
            username=admin_data['username'],
            first_name=admin_data['first_name'],
            last_name=admin_data['last_name'],
            email=admin_data['email'],
            password=admin_data['password']
        )
        
        # Actualizar el perfil automáticamente creado
        try:
            profile = UserProfile.objects.get(user=admin)
            profile.telefono = '11' + str(random.randint(10000000, 99999999))
            profile.sede_preferida = 'cualquiera'
            profile.fecha_nacimiento = date(1990, random.randint(1, 12), random.randint(1, 28))
            profile.tiene_lesiones = False
            profile.descripcion_lesiones = ''
            profile.acepta_marketing = True
            profile.acepta_recordatorios = True
            profile.save()
            print_success(f"Perfil actualizado para {admin_data['username']}")
        except UserProfile.DoesNotExist:
            print_warning(f"No se pudo encontrar perfil para {admin_data['username']}")
        
        admins_creados.append(admin_data)
        print_success(f"Administrador {admin_data['first_name']} {admin_data['last_name']} creado")
        
    return admins_creados

def crear_planes_pago():
    """Crea los planes de pago del nuevo sistema"""
    print_bold("💳 Creando planes de pago...")
    
    planes_data = [
        {
            'nombre': '1 clase semanal',
            'clases_por_semana': 1,
            'precio_mensual': Decimal('30000'),
            'descripcion': 'Plan básico para principiantes'
        },
        {
            'nombre': '2 clases semanales',
            'clases_por_semana': 2,
            'precio_mensual': Decimal('50000'),
            'descripcion': 'Plan intermedio más popular'
        },
        {
            'nombre': '3 clases semanales',
            'clases_por_semana': 3,
            'precio_mensual': Decimal('70000'),
            'descripcion': 'Plan avanzado para usuarios regulares'
        },
        {
            'nombre': '4 clases semanales',
            'clases_por_semana': 4,
            'precio_mensual': Decimal('85000'),
            'descripcion': 'Plan intensivo'
        },
        {
            'nombre': '5 clases semanales',
            'clases_por_semana': 5,
            'precio_mensual': Decimal('100000'),
            'descripcion': 'Plan premium para usuarios avanzados'
        }
    ]
    
    planes_creados = []
    for plan_data in planes_data:
        plan = PlanPago.objects.create(**plan_data)
        planes_creados.append(plan)
        print_success(f"Plan creado: {plan.nombre} - ${plan.precio_mensual}")
    
    return planes_creados

def crear_clases():
    """Crea clases variadas en ambas sedes"""
    print_bold("🤸‍♀️ Creando clases...")
    
    tipos_clase = ['Reformer', 'Cadillac', 'Especial', 'Mat']
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
    sedes = ['sede_principal', 'sede_2']
    
    horarios_manana = ['08:00', '09:00', '10:00', '11:00']
    horarios_tarde = ['14:00', '15:00', '16:00', '17:00', '18:00']
    horarios_noche = ['19:00', '20:00', '21:00']
    
    clases_creadas = []
    
    for sede in sedes:
        for dia in dias_semana:
            if dia == 'Sábado':
                horarios_dia = horarios_manana[:2]
                cantidad_clases = len(horarios_dia)
            else:
                horarios_dia = horarios_manana + horarios_tarde + horarios_noche
                cantidad_clases = random.randint(3, min(6, len(horarios_dia)))
            
            horarios_elegidos = random.sample(horarios_dia, cantidad_clases)
            
            for horario_str in horarios_elegidos:
                tipo = random.choices(tipos_clase, weights=[40, 25, 20, 15])[0]
                
                cupos_por_tipo = {
                    'Reformer': random.randint(8, 12),
                    'Cadillac': random.randint(6, 8),
                    'Especial': random.randint(10, 15),
                    'Mat': random.randint(15, 20)
                }
                
                hora, minuto = map(int, horario_str.split(':'))
                horario_time = time(hora, minuto)
                
                nombre_personalizado = None
                if tipo == 'Especial':
                    nombres_especiales = [
                        'Pilates Prenatal', 'Pilates Terapéutico', 'Pilates Seniors',
                        'Rehabilitación Postural', 'Pilates & Mindfulness', 'Core Intensivo'
                    ]
                    if random.random() < 0.7:
                        nombre_personalizado = random.choice(nombres_especiales)
                
                clase = Clase.objects.create(
                    tipo=tipo,
                    nombre_personalizado=nombre_personalizado,
                    direccion=sede,
                    dia=dia,
                    horario=horario_time,
                    cupo_maximo=cupos_por_tipo[tipo],
                    activa=True
                )
                clases_creadas.append(clase)
    
    print_success(f"Creadas {len(clases_creadas)} clases")
    return clases_creadas

def generar_descripcion_lesiones():
    """Genera descripciones de lesiones realistas"""
    lesiones_comunes = [
        "Dolor lumbar crónico - mejorando con Pilates",
        "Escoliosis leve - trabajo de corrección postural", 
        "Lesión previa de rodilla - rehabilitada",
        "Hipertensión controlada - ejercicio como terapia",
        "Hernias discales L4-L5 - fortalecimiento core",
        "Fibromialgia - ejercicio suave recomendado",
        "Artritis en manos - movilidad articular",
        "Lesión del manguito rotador - en recuperación",
        "Osteoporosis - ejercicios de impacto controlado",
        "Ansiedad - ejercicio como terapia complementaria",
        "Cervicalgia por estrés laboral",
        "Lesión previa de tobillo - totalmente recuperada",
        "Síndrome del túnel carpiano",
        "Contracturas musculares frecuentes",
        "Cifosis postural - corrección con ejercicios"
    ]
    return random.choice(lesiones_comunes)

def crear_usuarios_con_perfiles_variados():
    """Crea usuarios con diferentes perfiles de actividad"""
    print_bold("👥 Creando usuarios con perfiles variados...")
    
    # Usuarios super activos (5 clases semanales)
    usuarios_super_activos = [
        ('Martín', 'González'), ('Lucía', 'Rodríguez'), ('Santiago', 'López')
    ]
    
    # Usuarios muy activos (3-4 clases semanales)  
    usuarios_muy_activos = [
        ('Valentina', 'Martínez'), ('Mateo', 'García'), ('Emma', 'Pérez'),
        ('Benjamín', 'Sánchez'), ('Isabella', 'Romero'), ('Joaquín', 'Torres'),
        ('Olivia', 'Flores'), ('Tomás', 'Rivera')
    ]
    
    # Usuarios moderados (2 clases semanales)
    usuarios_moderados = [
        ('Mia', 'Morales'), ('Lucas', 'Jiménez'), ('Zoe', 'Ruiz'), 
        ('Thiago', 'Herrera'), ('Catalina', 'Medina'), ('Matías', 'Castro'),
        ('Renata', 'Ortega'), ('Sebastián', 'Ramos'), ('Julieta', 'Vargas'),
        ('Diego', 'Silva'), ('Sofía', 'Mendoza'), ('Nicolás', 'Cruz')
    ]
    
    # Usuarios ocasionales (1 clase semanal)
    usuarios_ocasionales = [
        ('Esperanza', 'Delgado'), ('Gabriel', 'Moreno'), ('Abril', 'Gutiérrez'),
        ('Felipe', 'Aguilar'), ('Pilar', 'Vega'), ('Ignacio', 'Ríos'),
        ('Alma', 'Campos'), ('Francisco', 'Herrera'), ('Constanza', 'Silva')
    ]
    
    # Usuarios sin reservas (para testing)
    usuarios_sin_reservas = [
        ('Rafael', 'Torres'), ('Carmen', 'Delgado'), ('Pablo', 'Morales')
    ]
    
    dominios_email = ['gmail.com', 'hotmail.com', 'yahoo.com.ar', 'outlook.com']
    sedes_preferidas = ['sede_principal', 'sede_2', 'cualquiera']
    
    todos_los_usuarios = []
    perfiles_usuarios = [
        (usuarios_super_activos, 5),
        (usuarios_muy_activos, random.choice([3, 4])),
        (usuarios_moderados, 2),
        (usuarios_ocasionales, 1),
        (usuarios_sin_reservas, 0)
    ]
    
    for usuarios_grupo, cantidad_clases in perfiles_usuarios:
        for nombre, apellido in usuarios_grupo:
            username = f"{nombre.lower()}.{apellido.lower()}"
            email = f"{username}@{random.choice(dominios_email)}"
            
            # Crear usuario con fecha de registro variada
            fecha_registro = timezone.now() - timedelta(days=random.randint(30, 365))
            
            usuario = User.objects.create_user(
                username=username,
                first_name=nombre,
                last_name=apellido,
                email=email,
                password='usuario123'
            )
            usuario.date_joined = fecha_registro
            usuario.save()
            
            # Actualizar perfil
            try:
                profile = UserProfile.objects.get(user=usuario)
                profile.telefono = '11' + str(random.randint(10000000, 99999999))
                profile.sede_preferida = random.choice(sedes_preferidas)
                profile.fecha_nacimiento = date(
                    random.randint(1980, 2005), 
                    random.randint(1, 12), 
                    random.randint(1, 28)
                )
                
                tiene_lesiones = random.choice([True, False])
                profile.tiene_lesiones = tiene_lesiones
                profile.descripcion_lesiones = generar_descripcion_lesiones() if tiene_lesiones else ''
                profile.acepta_marketing = random.choice([True, False])
                profile.acepta_recordatorios = random.choice([True, False])
                profile.save()
                
            except UserProfile.DoesNotExist:
                print_warning(f"No se pudo encontrar perfil para {username}")
            
            todos_los_usuarios.append((usuario, cantidad_clases))
    
    print_success(f"Creados {len(todos_los_usuarios)} usuarios con perfiles variados")
    return todos_los_usuarios

def crear_reservas_inteligentes(usuarios_con_perfiles, clases):
    """Crea reservas basadas en los perfiles de usuario"""
    print_bold("📅 Creando reservas inteligentes...")
    
    reservas_creadas = []
    
    for usuario, cantidad_clases_objetivo in usuarios_con_perfiles:
        if cantidad_clases_objetivo == 0:
            continue
            
        # Filtrar clases por sede preferida del usuario
        try:
            profile = UserProfile.objects.get(user=usuario)
            sede_preferida = profile.sede_preferida
        except UserProfile.DoesNotExist:
            sede_preferida = 'cualquiera'
        
        clases_disponibles = clases
        if sede_preferida != 'cualquiera':
            clases_disponibles = [c for c in clases if c.direccion == sede_preferida]
        
        # Seleccionar clases para este usuario
        clases_elegidas = random.sample(
            clases_disponibles, 
            min(cantidad_clases_objetivo, len(clases_disponibles))
        )
        
        for clase in clases_elegidas:
            try:
                reserva = Reserva.objects.create(
                    usuario=usuario,
                    clase=clase,
                    activa=True
                )
                reservas_creadas.append(reserva)
            except Exception as e:
                print_warning(f"Error creando reserva para {usuario.username}: {str(e)}")
    
    print_success(f"Creadas {len(reservas_creadas)} reservas inteligentes")
    return reservas_creadas

def crear_estados_pago_automaticos(usuarios_con_perfiles, planes_pago):
    """Crea estados de pago automáticos para todos los usuarios"""
    print_bold("💰 Creando estados de pago automáticos...")
    
    estados_creados = []
    
    for usuario, cantidad_clases in usuarios_con_perfiles:
        # Crear estado de pago
        estado_pago, created = EstadoPagoCliente.objects.get_or_create(
            usuario=usuario,
            defaults={'activo': True}
        )
        
        # Actualizar plan automáticamente basado en reservas
        estado_pago.actualizar_plan_automatico()
        
        # Simular historial de pagos variado
        if estado_pago.plan_actual:
            # Algunos usuarios al día, otros con deudas, otros con crédito
            situacion = random.choices(
                ['al_dia', 'con_deuda', 'con_credito', 'nuevo_sin_pagos'],
                weights=[40, 30, 20, 10]
            )[0]
            
            if situacion == 'al_dia':
                estado_pago.saldo_actual = Decimal('0')
            elif situacion == 'con_deuda':
                # Simular deuda de 1-3 meses
                meses_deuda = random.randint(1, 3)
                estado_pago.saldo_actual = -(estado_pago.plan_actual.precio_mensual * meses_deuda)
            elif situacion == 'con_credito':
                # Simular crédito (pago adelantado)
                estado_pago.saldo_actual = estado_pago.plan_actual.precio_mensual * Decimal('0.5')
            else:  # nuevo_sin_pagos
                estado_pago.saldo_actual = -(estado_pago.plan_actual.precio_mensual)
            
            # Fecha último pago variada
            if situacion != 'nuevo_sin_pagos':
                dias_desde_ultimo_pago = random.randint(1, 60)
                estado_pago.ultimo_pago = timezone.now().date() - timedelta(days=dias_desde_ultimo_pago)
                estado_pago.monto_ultimo_pago = estado_pago.plan_actual.precio_mensual
        
        # Agregar observaciones ocasionales
        observaciones_posibles = [
            '',
            'Cliente muy puntual con los pagos',
            'Prefiere pagar en efectivo',
            'Solicita recordatorios por WhatsApp',
            'Pago fraccionado acordado',
            'Cliente nuevo - seguimiento especial',
            'Descuento por renovación aplicado',
        ]
        
        estado_pago.observaciones = random.choice(observaciones_posibles)
        estado_pago.save()
        estados_creados.append(estado_pago)
    
    print_success(f"Creados {len(estados_creados)} estados de pago automáticos")
    return estados_creados

def crear_historial_pagos_realistas(estados_pago):
    """Crea un historial de pagos realista para cada cliente"""
    print_bold("📊 Creando historial de pagos realistas...")
    
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        print_error("No hay administradores para registrar pagos")
        return []
    
    tipos_pago = ['efectivo', 'transferencia', 'tarjeta', 'otro']
    estados_pago_opciones = ['confirmado', 'pendiente', 'rechazado']
    
    registros_creados = []
    
    for estado_pago in estados_pago:
        if not estado_pago.plan_actual:
            continue
            
        usuario = estado_pago.usuario
        
        # Calcular cuántos meses generar historial (basado en cuándo se registró)
        meses_desde_registro = (timezone.now().date() - usuario.date_joined.date()).days // 30
        meses_historial = min(meses_desde_registro, random.randint(1, 12))
        
        for mes in range(meses_historial):
            fecha_pago_base = timezone.now().date() - timedelta(days=mes * 30 + random.randint(1, 10))
            
            # Probabilidades de pago según el perfil del cliente
            if estado_pago.saldo_actual >= 0:  # Cliente al día o con crédito
                probabilidad_pago = 0.95
            else:  # Cliente con deuda
                probabilidad_pago = 0.70
            
            if random.random() < probabilidad_pago:
                # Crear registro de pago
                concepto = f"Pago mensual {fecha_pago_base.strftime('%B %Y')}"
                monto_base = estado_pago.plan_actual.precio_mensual
                
                # Ocasionalmente aplicar descuentos o bonificaciones
                if random.random() < 0.1:
                    descuento = random.choice([0.9, 0.85, 0.8])
                    monto_base = monto_base * Decimal(str(descuento))
                    concepto += " (con descuento)"
                
                # Ocasionalmente pagos parciales
                estado_pago_registro = 'confirmado'
                if random.random() < 0.05:
                    monto_base = monto_base * Decimal('0.5')
                    concepto += " (pago parcial)"
                
                # Muy ocasionalmente pagos pendientes o rechazados
                if mes == 0:  # Solo en el mes actual
                    estado_pago_registro = random.choices(
                        estados_pago_opciones,
                        weights=[85, 10, 5]
                    )[0]
                
                try:
                    registro = RegistroPago.objects.create(
                        cliente=usuario,
                        monto=monto_base,
                        fecha_pago=fecha_pago_base,
                        tipo_pago=random.choice(tipos_pago),
                        estado=estado_pago_registro,
                        concepto=concepto,
                        observaciones=generar_observaciones_pago(),
                        comprobante=generar_numero_comprobante() if random.random() < 0.6 else '',
                        registrado_por=admin_user
                    )
                    registros_creados.append(registro)
                    
                except Exception as e:
                    print_warning(f"Error creando registro de pago: {str(e)}")
    
    print_success(f"Creados {len(registros_creados)} registros de pagos realistas")
    return registros_creados

def generar_observaciones_pago():
    """Genera observaciones realistas para los pagos"""
    observaciones = [
        '',
        'Pago completo en término',
        'Transferencia recibida correctamente', 
        'Pago en efectivo - recibo entregado',
        'Débito automático procesado',
        'Pago adelantado - cliente al día',
        'Primera cuota del plan',
        'Renovación mensual',
        'Cliente solicitó comprobante',
        'Pago fraccionado acordado',
    ]
    return random.choice(observaciones)

def generar_numero_comprobante():
    """Genera números de comprobante realistas"""
    tipos = ['REC', 'TRF', 'TC', 'TD']
    tipo = random.choice(tipos)
    numero = random.randint(100000, 999999)
    return f"{tipo}-{numero}"

def crear_algunos_clientes_legacy():
    """Crea algunos clientes del sistema legacy para testing"""
    print_bold("👤 Creando algunos clientes legacy...")
    
    clientes_legacy_data = [
        ('Roberto', 'Fernández'), ('Silvia', 'Giménez'), ('Carlos', 'Navarro'),
        ('Patricia', 'Molina'), ('Gustavo', 'Cabrera')
    ]
    
    clientes_creados = []
    
    for nombre, apellido in clientes_legacy_data:
        cliente = Cliente.objects.create(
            nombre=nombre,
            apellido=apellido,
            email=f"{nombre.lower()}.{apellido.lower()}@email.com",
            telefono=f"11{random.randint(10000000, 99999999)}",
            codigo_verificacion=f"{random.randint(1000, 9999)}"
        )
        clientes_creados.append(cliente)
    
    print_success(f"Creados {len(clientes_creados)} clientes legacy")
    return clientes_creados

def mostrar_resumen_completo(admins, planes_pago, clases, usuarios, estados_pago, registros_pago, reservas):
    """Muestra un resumen completo de todos los datos generados"""
    print('\n' + '='*80)
    print_bold('🎉 DATOS DE TESTING GENERADOS EXITOSAMENTE - PILATES GRAVITY')
    print_bold('SISTEMA DE PAGOS ACTUALIZADO')
    print('='*80)
    
    # Resumen general
    print_bold(f"\n📊 RESUMEN GENERAL:")
    print(f"   • Administradores: {len(admins)}")
    print(f"   • Planes de pago: {len(planes_pago)}")
    print(f"   • Clases totales: {len(clases)}")
    print(f"   • Usuarios registrados: {len(usuarios)}")
    print(f"   • Estados de pago: {len(estados_pago)}")
    print(f"   • Registros de pago: {len(registros_pago)}")
    print(f"   • Reservas activas: {len(reservas)}")
    
    # Información de administradores
    print_bold(f"\n👑 ADMINISTRADORES CREADOS:")
    for admin in admins:
        print(f"   • Usuario: {admin['username']}")
        print(f"     Nombre: {admin['first_name']} {admin['last_name']}")
        print(f"     Email: {admin['email']}")
        print(f"     Password: {admin['password']}")
    
    # Análisis de planes de pago
    print_bold(f"\n💳 PLANES DE PAGO DISPONIBLES:")
    for plan in planes_pago:
        clientes_con_plan = len([e for e in estados_pago if e.plan_actual == plan])
        print(f"   • {plan.nombre}: ${plan.precio_mensual} ({clientes_con_plan} clientes)")
    
    # Análisis de ocupación por clase
    ocupacion_stats = []
    for clase in clases:
        reservas_clase = len([r for r in reservas if r.clase == clase])
        porcentaje = (reservas_clase / clase.cupo_maximo) * 100 if clase.cupo_maximo > 0 else 0
        ocupacion_stats.append(porcentaje)
    
    clases_llenas = len([p for p in ocupacion_stats if p >= 90])
    clases_muy_ocupadas = len([p for p in ocupacion_stats if 70 <= p < 90])
    clases_moderadas = len([p for p in ocupacion_stats if 40 <= p < 70])
    clases_pocas = len([p for p in ocupacion_stats if 10 <= p < 40])
    clases_vacias = len([p for p in ocupacion_stats if p < 10])
    
    print_bold(f"\n📈 OCUPACIÓN DE CLASES:")
    print(f"   • Clases llenas (90-100%): {clases_llenas}")
    print(f"   • Muy ocupadas (70-89%): {clases_muy_ocupadas}")
    print(f"   • Ocupación moderada (40-69%): {clases_moderadas}")
    print(f"   • Pocas reservas (10-39%): {clases_pocas}")
    print(f"   • Prácticamente vacías (0-9%): {clases_vacias}")
    
    # Análisis de estados de pago
    clientes_al_dia = len([e for e in estados_pago if e.saldo_actual >= 0])
    clientes_con_deuda = len([e for e in estados_pago if e.saldo_actual < 0])
    clientes_con_credito = len([e for e in estados_pago if e.saldo_actual > 0])
    
    print_bold(f"\n💰 ANÁLISIS DE ESTADOS DE PAGO:")
    print(f"   • Clientes al día o con crédito: {clientes_al_dia}")
    print(f"   • Clientes con deuda: {clientes_con_deuda}")
    print(f"   • Clientes con crédito a favor: {clientes_con_credito}")
    
    # Análisis de pagos por estado
    pagos_confirmados = len([p for p in registros_pago if p.estado == 'confirmado'])
    pagos_pendientes = len([p for p in registros_pago if p.estado == 'pendiente'])
    pagos_rechazados = len([p for p in registros_pago if p.estado == 'rechazado'])
    
    print_bold(f"\n📊 ESTADO DE PAGOS:")
    print(f"   • Pagos confirmados: {pagos_confirmados}")
    print(f"   • Pagos pendientes: {pagos_pendientes}")
    print(f"   • Pagos rechazados: {pagos_rechazados}")
    
    # Distribución por sede
    clases_sede1 = len([c for c in clases if c.direccion == 'sede_principal'])
    clases_sede2 = len([c for c in clases if c.direccion == 'sede_2'])
    
    print_bold(f"\n🏢 DISTRIBUCIÓN POR SEDE:")
    print(f"   • Sede Principal: {clases_sede1} clases")
    print(f"   • Sede Norte: {clases_sede2} clases")
    
    # Tipos de clase
    tipos_distribucion = {}
    for clase in clases:
        tipos_distribucion[clase.tipo] = tipos_distribucion.get(clase.tipo, 0) + 1
    
    print_bold(f"\n🤸‍♀️ TIPOS DE CLASE:")
    for tipo, cantidad in tipos_distribucion.items():
        print(f"   • {tipo}: {cantidad} clases")
    
    # Escenarios de testing disponibles
    print_bold(f"\n🎯 ESCENARIOS DE TESTING DISPONIBLES:")
    print(f"   ✅ Clientes con diferentes planes (1-5 clases semanales)")
    print(f"   💰 Clientes al día, con deuda y con crédito")
    print(f"   📅 Reservas automáticamente asignadas por perfil")
    print(f"   📊 Historial de pagos realista con diferentes estados")
    print(f"   🏢 Distribución equilibrada entre sedes")
    print(f"   👥 Usuarios con perfiles médicos variados")
    print(f"   💳 Sistema de pagos completamente funcional")
    print(f"   📈 Reportes financieros con datos reales")
    print(f"   🔄 Actualización automática de planes según reservas")
    print(f"   💡 Cálculos automáticos de saldos y deudas")
    
    # URLs de acceso
    print_bold(f"\n🌐 ACCESO AL SISTEMA:")
    print(f"   • Página principal: http://localhost:8000/")
    print(f"   • Panel de administración Django: http://localhost:8000/admin/")
    print(f"   • Panel personalizado: http://localhost:8000/admin-panel/")
    print(f"   • Sistema de reservas: http://localhost:8000/reservar_clase/")
    print(f"   • Sistema de pagos: http://localhost:8000/admin-panel/pagos/")
    
    # Casos de prueba específicos
    print_bold(f"\n🔍 CASOS DE PRUEBA ESPECÍFICOS GENERADOS:")
    
    # Usuario con mayor deuda
    usuario_mayor_deuda = min(estados_pago, key=lambda x: x.saldo_actual, default=None)
    if usuario_mayor_deuda and usuario_mayor_deuda.saldo_actual < 0:
        print(f"   • Mayor deuda: {usuario_mayor_deuda.get_nombre_completo()} "
              f"(${abs(usuario_mayor_deuda.saldo_actual)})")
    
    # Usuario con mayor crédito
    usuario_mayor_credito = max(estados_pago, key=lambda x: x.saldo_actual, default=None)
    if usuario_mayor_credito and usuario_mayor_credito.saldo_actual > 0:
        print(f"   • Mayor crédito: {usuario_mayor_credito.get_nombre_completo()} "
              f"(${usuario_mayor_credito.saldo_actual})")
    
    # Planes más y menos populares
    planes_popularidad = {}
    for estado in estados_pago:
        if estado.plan_actual:
            plan_nombre = estado.plan_actual.nombre
            planes_popularidad[plan_nombre] = planes_popularidad.get(plan_nombre, 0) + 1
    
    if planes_popularidad:
        plan_mas_popular = max(planes_popularidad, key=planes_popularidad.get)
        plan_menos_popular = min(planes_popularidad, key=planes_popularidad.get)
        print(f"   • Plan más popular: {plan_mas_popular} ({planes_popularidad[plan_mas_popular]} usuarios)")
        print(f"   • Plan menos popular: {plan_menos_popular} ({planes_popularidad[plan_menos_popular]} usuarios)")
    
    # Información importante de seguridad
    print('\n' + '⚠️ '*30)
    print_bold('IMPORTANTE - INFORMACIÓN DE SEGURIDAD:')
    print('='*80)
    print_bold('🔐 CONTRASEÑAS:')
    print('   • Administradores: Ver contraseñas arriba (¡CAMBIAR EN PRODUCCIÓN!)')
    print('   • Usuarios regulares: "usuario123"')
    print('   • ¡ESTAS SON CONTRASEÑAS DE TESTING!')
    print('')
    print_bold('📱 DATOS DE CONTACTO:')
    print('   • Teléfonos generados automáticamente')
    print('   • Emails con dominios de ejemplo')
    print('   • Actualizar con datos reales según necesidades')
    print('')
    print_bold('🏦 DATOS FINANCIEROS:')
    print('   • Montos en pesos argentinos')
    print('   • Saldos calculados automáticamente')
    print('   • Estados de pago variados para testing completo')
    print('   • Historial de pagos simulado realistic')
    print('⚠️ '*30)
    
    # Consejos para testing
    print_bold(f"\n💡 CONSEJOS PARA TESTING:")
    print(f"   • Probar registro de nuevos pagos desde admin-panel/pagos/")
    print(f"   • Verificar cálculos automáticos de saldos")
    print(f"   • Testear actualización automática de planes")
    print(f"   • Revisar historial de pagos por cliente")
    print(f"   • Probar configuración de nuevos planes")
    print(f"   • Verificar filtros y búsquedas en el panel")
    print(f"   • Testear edición manual de estados de pago")
    print(f"   • Verificar reportes financieros")
    print(f"   • Probar restricciones de reservas vs pagos")
    print(f"   • Testear diferentes escenarios de deuda/crédito")
    
    print_bold('\n🚀 ¡SISTEMA LISTO PARA TESTING COMPLETO!')
    print('='*80 + '\n')

def main():
    """Función principal que coordina la generación de todos los datos"""
    print_bold('🤸‍♀️ Iniciando generación completa de datos de testing para Pilates Gravity...')
    print_bold('NUEVO SISTEMA DE PAGOS - Versión 2024\n')
    
    try:
        with transaction.atomic():
            # Paso 1: Limpiar datos existentes
            limpiar_datos_existentes()
            
            # Paso 2: Crear administradores
            admins = crear_administradores()
            
            # Paso 3: Crear planes de pago (NUEVO)
            planes_pago = crear_planes_pago()
            
            # Paso 4: Crear clases
            clases = crear_clases()
            
            # Paso 5: Crear usuarios con perfiles específicos
            usuarios_con_perfiles = crear_usuarios_con_perfiles_variados()
            
            # Paso 6: Crear reservas inteligentes
            reservas = crear_reservas_inteligentes(usuarios_con_perfiles, clases)
            
            # Paso 7: Crear estados de pago automáticos (NUEVO)
            estados_pago = crear_estados_pago_automaticos(usuarios_con_perfiles, planes_pago)
            
            # Paso 8: Crear historial de pagos realistas (NUEVO)
            registros_pago = crear_historial_pagos_realistas(estados_pago)
            
            # Paso 9: Crear algunos clientes legacy para compatibilidad
            clientes_legacy = crear_algunos_clientes_legacy()
            
            # Paso 10: Mostrar resumen completo
            usuarios_solo = [usuario for usuario, _ in usuarios_con_perfiles]
            mostrar_resumen_completo(
                admins, planes_pago, clases, usuarios_solo,
                estados_pago, registros_pago, reservas
            )
            
            print_success("¡Generación de datos de testing completada exitosamente!")
            print_info("El nuevo sistema de pagos está listo para probar todas las funcionalidades.")
            
    except Exception as e:
        print_error(f'Error durante la generación: {str(e)}')
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()