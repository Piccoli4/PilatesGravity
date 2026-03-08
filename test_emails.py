"""
Script de prueba: envía los 7 emails a las direcciones indicadas.
Ejecutar desde el shell de Django:
    exec(open('test_emails.py', encoding='utf-8').read())
"""

from types import SimpleNamespace
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

DESTINATARIOS = ['piccoli_44@hotmail.com', 'piccoliga4@gmail.com']
domain_url = getattr(settings, 'SITE_URL', 'https://pilatesgravity.com.ar')


# ------------------------------------------------------------------------------
# Objetos simulados
# ------------------------------------------------------------------------------

usuario = SimpleNamespace(
    username='Piccoli',
    first_name='Gastón',
    last_name='Piccoli',
    email='piccoli_44@hotmail.com',
)

clase = SimpleNamespace(
    get_nombre_display=lambda: 'Pilates Reformer',
    get_direccion_display=lambda: 'La Rioja 3044',
    get_direccion_corta=lambda: 'Sede Principal',
    dia='Lunes',
    horario=SimpleNamespace(strftime=lambda fmt: '09:00'),
)

reserva = SimpleNamespace(
    numero_reserva='RES-000001',
    activa=True,
    usuario=usuario,
    clase=clase,
    get_proxima_clase_info=lambda: {'fecha': '10/03/2025', 'dias_restantes': 3},
    get_nombre_completo_usuario=lambda: 'Gastón Piccoli',
)

plan = SimpleNamespace(nombre='Plan 2 veces por semana')

estado_pago = SimpleNamespace(
    saldo_actual=0,
    plan_actual=plan,
)

pago = SimpleNamespace(
    id=1,
    cliente=usuario,
    monto=25000,
    concepto='Cuota mensual marzo 2025',
    get_tipo_pago_display=lambda: 'Transferencia',
    get_estado_display=lambda: 'Confirmado',
    fecha_pago=SimpleNamespace(strftime=lambda fmt: '01/03/2025'),
    fecha_registro=SimpleNamespace(strftime=lambda fmt: '01/03/2025 10:00'),
    comprobante=None,
)

base = {'usuario': usuario, 'domain_url': domain_url}


# ------------------------------------------------------------------------------
# Función de envío
# ------------------------------------------------------------------------------

def enviar_test(subject, template, context):
    try:
        html = render_to_string(template, context)
        msg = EmailMultiAlternatives(
            subject=f"[TEST] {subject}",
            body=f"Email de prueba — {subject}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=DESTINATARIOS,
        )
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        print(f'  ✓  {subject}')
    except Exception as e:
        print(f'  ✗  {subject} — ERROR: {e}')


# ------------------------------------------------------------------------------
# Envío de los 7 emails
# ------------------------------------------------------------------------------

print('\nEnviando emails de prueba...\n')

enviar_test('Bienvenida', 'gravity/emails/bienvenida_email.html',
    {**base, 'is_admin_created': False, 'password_temporal': None})

enviar_test('Confirmación de reserva', 'gravity/emails/confirmacion_reserva_email.html',
    {**base, 'reserva': reserva, 'proxima_clase_info': reserva.get_proxima_clase_info()})

enviar_test('Recordatorio de clase', 'gravity/emails/recordatorio_clase_email.html',
    {**base, 'reserva': reserva, 'horas_antes': 24})

enviar_test('Reserva cancelada', 'gravity/emails/reserva_cancelada_email.html',
    {**base, 'reserva': reserva, 'motivo': 'Decisión del alumno',
     'motivo_detalle': None, 'ofrecer_reemplazo': False, 'clases_alternativas': []})

enviar_test('Confirmación de pago', 'gravity/emails/confirmacion_pago_email.html',
    {**base, 'pago': pago, 'estado_pago': estado_pago,
     'saldo_anterior': 0, 'saldo_actual': 0, 'plan_actual': plan})

enviar_test('Cumpleaños', 'gravity/emails/cumpleanios_email.html', base)

enviar_test('Despedida', 'gravity/emails/despedida_email.html', base)

print('\nListo. Revisá ambas bandejas de entrada.\n')
