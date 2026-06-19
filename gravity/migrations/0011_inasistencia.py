import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gravity', '0010_cancelacionadmin'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Inasistencia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(help_text='Fecha específica en que el cliente no asistió sin avisar', verbose_name='Fecha de la clase')),
                ('fecha_registro', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')),
                ('observacion', models.CharField(blank=True, max_length=255, verbose_name='Observación')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inasistencias_registradas', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
                ('reserva', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inasistencias', to='gravity.reserva', verbose_name='Reserva')),
            ],
            options={
                'verbose_name': 'Inasistencia',
                'verbose_name_plural': 'Inasistencias',
                'ordering': ['-fecha'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='inasistencia',
            unique_together={('reserva', 'fecha')},
        ),
    ]
