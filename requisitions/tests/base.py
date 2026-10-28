from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from inventory.models import ComponentType
from requisitions.services import submit_requisition


class RequestTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hospital = User.objects.create_user('abhinav_hospital', role=User.Role.HOSPITAL, hospital_name='Abhinav Hospital')
        cls.other = User.objects.create_user('navaneeth_hospital', role=User.Role.HOSPITAL)
        cls.staff = User.objects.create_user('uttam_staff', role=User.Role.STAFF)
        cls.admin_user = User.objects.create_user('akshay_admin', role=User.Role.ADMIN)
        cls.donor = User.objects.create_user('donor', role=User.Role.DONOR)

    def request_data(self, **overrides):
        return {'blood_group': 'O+', 'component_type': ComponentType.RBC, 'quantity': 2,
                'required_by': timezone.localdate() + timedelta(days=2), **overrides}

    def submit(self, actor=None, **overrides):
        return submit_requisition(actor=actor or self.hospital, **self.request_data(**overrides))
