from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class StatusHistoryMigrationTests(TransactionTestCase):
    def test_existing_units_keep_legacy_history_and_receive_quarantine_start(self):
        executor = MigrationExecutor(connection)
        old_target = [('inventory', '0003_serologytest')]
        new_target = [('inventory', '0004_quarantine_status_history')]
        try:
            executor.migrate(old_target)
            old_apps = executor.loader.project_state(old_target).apps
            old_unit = old_apps.get_model('inventory', 'BloodUnit')
            collected = timezone.now() - timedelta(days=4)
            unit = old_unit.objects.create(
                bag_id='LEGACY-QUARANTINE', blood_group='O+', status='Quarantined',
                collection_date=collected, status_audit_log='Earlier staff transition recorded.',
            )
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            new_apps = executor.loader.project_state(new_target).apps
            imported = new_apps.get_model('inventory', 'BloodUnit').objects.get(pk=unit.pk)
            self.assertEqual(imported.quarantined_at, collected)
            self.assertEqual(imported.status_audit_log, 'Earlier staff transition recorded.')
            self.assertEqual(new_apps.get_model('inventory', 'StatusChange').objects.count(), 0)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
