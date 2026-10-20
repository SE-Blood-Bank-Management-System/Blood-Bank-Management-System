# Generated manually for issue #10

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='bloodunit',
            name='collected_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Authorized staff member who recorded this blood collection (SRS BBMS-F-017)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='collected_blood_units',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='bloodunit',
            name='collection_notes',
            field=models.TextField(
                blank=True,
                help_text='Staff notes or clinical observations made during donation (SRS BBMS-F-018)',
            ),
        ),
    ]
