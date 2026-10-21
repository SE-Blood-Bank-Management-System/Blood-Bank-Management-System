# Generated manually for issue #12

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0002_bloodunit_collected_by_bloodunit_collection_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='bloodunit',
            name='status_audit_log',
            field=models.TextField(
                blank=True,
                help_text='Audit log of status transitions and serology outcomes (SRS BBMS-F-029)',
            ),
        ),
        migrations.CreateModel(
            name='SerologyTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('test_type', models.CharField(
                    choices=[
                        ('HIV', 'HIV'),
                        ('Hepatitis B', 'Hepatitis B'),
                        ('Hepatitis C', 'Hepatitis C'),
                        ('Syphilis', 'Syphilis'),
                    ],
                    help_text='Specific serological screening assay (SRS BBMS-F-024)',
                    max_length=20,
                )),
                ('result', models.CharField(
                    choices=[('Pass', 'Pass'), ('Fail', 'Fail')],
                    help_text='Test outcome: Pass or Fail (SRS BBMS-F-025)',
                    max_length=10,
                )),
                ('tested_at', models.DateTimeField(
                    default=django.utils.timezone.now,
                    help_text='Timestamp when test result was recorded (SRS BBMS-F-029)',
                )),
                ('notes', models.TextField(
                    blank=True,
                    help_text='Laboratory notes or assay optical density / reagent kit details',
                )),
                ('blood_unit', models.ForeignKey(
                    help_text='Blood unit tested (SRS BBMS-F-024)',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='serology_tests',
                    to='inventory.bloodunit',
                )),
                ('tested_by', models.ForeignKey(
                    blank=True,
                    help_text='Authorized staff member who conducted or recorded the test (SRS BBMS-F-029)',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='conducted_serology_tests',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Serology Test',
                'verbose_name_plural': 'Serology Tests',
                'ordering': ['blood_unit', 'test_type'],
                'unique_together': {('blood_unit', 'test_type')},
            },
        ),
    ]
