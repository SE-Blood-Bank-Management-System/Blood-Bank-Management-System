"""
Management command to seed initial demonstration data for BBMS.
SRS References:
- Section 2.3: User classes (Donor, Hospital, Staff, Administrator)
- Section 4.1 - 4.4: Donor registration, profile, eligibility screening, appointment booking
- Section 4.5 - 4.9: Blood collection, unique Bag ID, blood group, serology testing, quarantine
- Section 4.11 - 4.12: Inventory counts, FEFO expiry
- Section 4.13: Hospital registration and approval
"""
from datetime import date, datetime, time, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from appointments.models import Appointment, AppointmentSlot, BloodBankLocation
from appointments.services import DEFAULT_DAILY_SLOTS, DEFAULT_LOCATIONS_DATA
from core.constants import BloodGroup
from donors.models import MedicalEligibilityResponse, QUESTIONNAIRE_QUESTIONS
from inventory.models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    REQUIRED_SEROLOGY_TESTS,
    SerologyResult,
    SerologyTest,
    SerologyTestType,
)


class Command(BaseCommand):
    help = 'Seeds database with realistic demo accounts, locations, appointment slots, eligibility data, and inventory'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of upcoming days for which appointment slots should be generated (default: 7)',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Wipes existing demo accounts, slots, and blood units before seeding',
        )

    def handle(self, *args, **options):
        days_ahead = options['days']
        should_reset = options['reset']

        self.stdout.write(self.style.NOTICE("Initializing BBMS Demo Seed Data..."))

        if should_reset:
            self.stdout.write(self.style.WARNING("Reset requested. Clearing existing application seed data..."))
            self._reset_data()

        with transaction.atomic():
            users = self._seed_users()
            locations = self._seed_locations()
            slots = self._seed_appointment_slots(locations, days_ahead)
            self._seed_eligibility_and_appointments(users, locations, slots)
            self._seed_blood_units_and_testing(users, locations)

        self.stdout.write(self.style.SUCCESS("\nDemo seed data successfully generated!"))
        self._print_credentials_summary()

    def _reset_data(self):
        """Clears existing application data if requested."""
        SerologyTest.objects.all().delete()
        BloodUnit.objects.all().delete()
        Appointment.objects.all().delete()
        AppointmentSlot.objects.all().delete()
        MedicalEligibilityResponse.objects.all().delete()
        # Keep superusers if created manually, remove demo usernames
        demo_usernames = [
            'admin', 'staff_john', 'staff_mary',
            'donor_jane', 'donor_rahul', 'donor_priya', 'donor_vikram',
            'hospital_city', 'hospital_metro',
            'synth_donor_1', 'synth_donor_2', 'synth_donor_3', 'synth_donor_4', 'synth_donor_5'
        ]
        User.objects.filter(username__in=demo_usernames).delete()
        BloodBankLocation.objects.all().delete()

    def _seed_users(self):
        """Creates the full spectrum of user roles (Admin, Staff, Donor, Hospital)."""
        users = {}

        # 1. Administrator
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@bbms.local',
                'role': User.Role.ADMIN,
                'first_name': 'System',
                'last_name': 'Administrator',
                'phone': '+91-9876543210',
                'is_staff': True,
                'is_superuser': True,
                'is_approved': True,
            }
        )
        admin_user.set_password('AdminPassword@123')
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.role = User.Role.ADMIN
        admin_user.save()
        users['admin'] = admin_user

        # 2. Blood Bank Staff - John (Collection Officer)
        staff_john, _ = User.objects.get_or_create(
            username='staff_john',
            defaults={
                'email': 'staff.john@bbms.local',
                'role': User.Role.STAFF,
                'first_name': 'John',
                'last_name': 'Nurses',
                'phone': '+91-9876543211',
                'is_staff': True,
                'is_approved': True,
            }
        )
        staff_john.set_password('StaffPassword@123')
        staff_john.is_staff = True
        staff_john.role = User.Role.STAFF
        staff_john.save()
        users['staff_john'] = staff_john

        # 3. Blood Bank Staff - Mary (Laboratory Technician)
        staff_mary, _ = User.objects.get_or_create(
            username='staff_mary',
            defaults={
                'email': 'staff.mary@bbms.local',
                'role': User.Role.STAFF,
                'first_name': 'Mary',
                'last_name': 'Technician',
                'phone': '+91-9876543212',
                'is_staff': True,
                'is_approved': True,
            }
        )
        staff_mary.set_password('StaffPassword@123')
        staff_mary.is_staff = True
        staff_mary.role = User.Role.STAFF
        staff_mary.save()
        users['staff_mary'] = staff_mary

        # 4. Donor - Jane (Eligible, Active upcoming booking)
        donor_jane, _ = User.objects.get_or_create(
            username='donor_jane',
            defaults={
                'email': 'donor.jane@bbms.local',
                'role': User.Role.DONOR,
                'first_name': 'Jane',
                'last_name': 'Doe',
                'date_of_birth': date(1995, 5, 15),
                'gender': User.Gender.FEMALE,
                'blood_group': BloodGroup.O_POS,
                'phone': '+91-9876543220',
                'address': '123 MG Road, Bangalore, Karnataka',
                'is_approved': True,
            }
        )
        donor_jane.set_password('DonorPassword@123')
        donor_jane.save()
        users['donor_jane'] = donor_jane

        # 5. Donor - Rahul (Experienced Donor with completed past donations)
        donor_rahul, _ = User.objects.get_or_create(
            username='donor_rahul',
            defaults={
                'email': 'donor.rahul@bbms.local',
                'role': User.Role.DONOR,
                'first_name': 'Rahul',
                'last_name': 'Sharma',
                'date_of_birth': date(1992, 8, 20),
                'gender': User.Gender.MALE,
                'blood_group': BloodGroup.A_POS,
                'phone': '+91-9876543221',
                'address': '45 Residency Road, Bangalore, Karnataka',
                'is_approved': True,
            }
        )
        donor_rahul.set_password('DonorPassword@123')
        donor_rahul.save()
        users['donor_rahul'] = donor_rahul

        # 6. Donor - Priya (Recent Donor - within 90-day cooldown interval)
        donor_priya, _ = User.objects.get_or_create(
            username='donor_priya',
            defaults={
                'email': 'donor.priya@bbms.local',
                'role': User.Role.DONOR,
                'first_name': 'Priya',
                'last_name': 'Patel',
                'date_of_birth': date(1998, 11, 10),
                'gender': User.Gender.FEMALE,
                'blood_group': BloodGroup.B_POS,
                'phone': '+91-9876543222',
                'address': '78 Indiranagar, Bangalore, Karnataka',
                'is_approved': True,
            }
        )
        donor_priya.set_password('DonorPassword@123')
        donor_priya.save()
        users['donor_priya'] = donor_priya

        # 7. Donor - Vikram (Temporarily Ineligible due to recent illness/antibiotics)
        donor_vikram, _ = User.objects.get_or_create(
            username='donor_vikram',
            defaults={
                'email': 'donor.vikram@bbms.local',
                'role': User.Role.DONOR,
                'first_name': 'Vikram',
                'last_name': 'Verma',
                'date_of_birth': date(2000, 1, 12),
                'gender': User.Gender.MALE,
                'blood_group': BloodGroup.AB_POS,
                'phone': '+91-9876543223',
                'address': '12 Koramangala, Bangalore, Karnataka',
                'is_approved': True,
            }
        )
        donor_vikram.set_password('DonorPassword@123')
        donor_vikram.save()
        users['donor_vikram'] = donor_vikram

        # 8. Hospital User - City General Hospital (Approved)
        hospital_city, _ = User.objects.get_or_create(
            username='hospital_city',
            defaults={
                'email': 'hospital.city@bbms.local',
                'role': User.Role.HOSPITAL,
                'hospital_name': 'City General Hospital',
                'license_number': 'HOSP-BLR-2024-001',
                'contact_person': 'Dr. Ramesh Rao',
                'phone': '+91-9876543230',
                'address': 'Victoria Hospital Campus, Fort, Bangalore',
                'is_approved': True,
            }
        )
        hospital_city.set_password('HospitalPassword@123')
        hospital_city.save()
        users['hospital_city'] = hospital_city

        # 9. Hospital User - Metro Specialty Clinic (Pending Approval)
        hospital_metro, _ = User.objects.get_or_create(
            username='hospital_metro',
            defaults={
                'email': 'hospital.metro@bbms.local',
                'role': User.Role.HOSPITAL,
                'hospital_name': 'Metro Specialty Clinic',
                'license_number': 'HOSP-BLR-2026-999',
                'contact_person': 'Dr. Sunita Sen',
                'phone': '+91-9876543231',
                'address': 'Outer Ring Road, Marathahalli, Bangalore',
                'is_approved': False,
            }
        )
        hospital_metro.set_password('HospitalPassword@123')
        hospital_metro.save()
        users['hospital_metro'] = hospital_metro

        self.stdout.write(f"  [+] Configured {len(users)} primary demo user accounts across all roles.")
        return users

    def _seed_locations(self):
        """Creates realistic blood bank centers."""
        locations = {}
        for item in DEFAULT_LOCATIONS_DATA:
            loc, _ = BloodBankLocation.objects.get_or_create(
                name=item['name'],
                defaults={
                    'address': item['address'],
                    'city': item['city'],
                    'contact_number': item['contact_number'],
                    'contact_email': item['contact_email'],
                    'is_active': True,
                }
            )
            locations[item['name']] = loc

        # Also add PES University Health Center if not present
        pes_loc, _ = BloodBankLocation.objects.get_or_create(
            name='PES University Blood Donation Center',
            defaults={
                'address': '100 Feet Ring Road, BSK III Stage',
                'city': 'Bangalore',
                'state': 'Karnataka',
                'contact_number': '+91-80-2672-1983',
                'contact_email': 'bloodbank@pes.edu',
                'is_active': True,
            }
        )
        locations['PES University Blood Donation Center'] = pes_loc
        self.stdout.write(f"  [+] Configured {len(locations)} blood bank locations.")
        return locations

    def _seed_appointment_slots(self, locations, days_ahead):
        """Generates available appointment slots across dates and time bands."""
        today = timezone.localdate()
        created_count = 0
        all_slots = []

        for offset in range(days_ahead + 1):
            slot_date = today + timedelta(days=offset)
            for loc in locations.values():
                for start_t, end_t in DEFAULT_DAILY_SLOTS:
                    slot, created = AppointmentSlot.objects.get_or_create(
                        location=loc,
                        date=slot_date,
                        start_time=start_t,
                        defaults={
                            'end_time': end_t,
                            'max_capacity': 5,
                            'is_active': True,
                        }
                    )
                    all_slots.append(slot)
                    if created:
                        created_count += 1

        self.stdout.write(f"  [+] Generated {created_count} appointment slots across next {days_ahead} days.")
        return all_slots

    def _seed_eligibility_and_appointments(self, users, locations, slots):
        """Seeds eligibility questionnaire responses and bookings."""
        # 1. Jane Doe: Passing eligibility questionnaire
        jane_responses = {
            'feeling_well': 'yes',
            'recent_fever': 'no',
            'antibiotics': 'no',
            'tattoo_piercing': 'no',
            'malaria_travel': 'no',
            'pregnancy': 'no',
            'chronic_blood_conditions': 'no',
        }
        jane_elg, _ = MedicalEligibilityResponse.objects.get_or_create(
            donor=users['donor_jane'],
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            defaults={
                'responses': jane_responses,
                'ineligibility_reason': '',
            }
        )

        # 2. Vikram Verma: Ineligible questionnaire (fever & antibiotics)
        vikram_responses = {
            'feeling_well': 'no',
            'recent_fever': 'yes',
            'antibiotics': 'yes',
            'tattoo_piercing': 'no',
            'malaria_travel': 'no',
            'pregnancy': 'no',
            'chronic_blood_conditions': 'no',
        }
        vikram_reasons = (
            "You must be feeling well and in good health on the day of donation.\n"
            "Recent fever or illness in the last 48 hours.\n"
            "Antibiotics taken within the past 7 days requires a waiting period."
        )
        MedicalEligibilityResponse.objects.get_or_create(
            donor=users['donor_vikram'],
            status=MedicalEligibilityResponse.Status.INELIGIBLE,
            defaults={
                'responses': vikram_responses,
                'ineligibility_reason': vikram_reasons,
            }
        )

        # 3. Rahul & Priya: Passing eligibility
        MedicalEligibilityResponse.objects.get_or_create(
            donor=users['donor_rahul'],
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            defaults={'responses': jane_responses}
        )
        MedicalEligibilityResponse.objects.get_or_create(
            donor=users['donor_priya'],
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            defaults={'responses': jane_responses}
        )

        # 4. Book Jane into tomorrow 10:00 AM slot at Central Blood Bank
        tomorrow = timezone.localdate() + timedelta(days=1)
        central_loc = locations.get('Central City Blood Bank') or list(locations.values())[0]
        jane_slot = AppointmentSlot.objects.filter(
            location=central_loc,
            date=tomorrow,
            start_time=time(10, 0)
        ).first()

        has_active_apt = Appointment.objects.filter(
            donor=users['donor_jane'],
            status__in=['CONFIRMED', 'SCHEDULED']
        ).exists()
        if jane_slot and not has_active_apt:
            Appointment.objects.create(
                donor=users['donor_jane'],
                slot=jane_slot,
                location=jane_slot.location,
                date=jane_slot.date,
                time_slot=jane_slot.time_label,
                status=Appointment.Status.CONFIRMED,
                eligibility_check=jane_elg,
                donor_notes='First-time donor demo appointment',
            )

        # 5. Overbooking Capacity Demonstration Slot:
        # Pre-fill tomorrow 09:00 AM at PES University Center to 5/5 capacity
        pes_loc = locations.get('PES University Blood Donation Center')
        if pes_loc:
            full_slot = AppointmentSlot.objects.filter(
                location=pes_loc,
                date=tomorrow,
                start_time=time(9, 0)
            ).first()

            if full_slot and full_slot.booked_count < full_slot.max_capacity:
                needed = full_slot.max_capacity - full_slot.booked_count
                for i in range(1, needed + 1):
                    synth_user, _ = User.objects.get_or_create(
                        username=f'synth_donor_{i}',
                        defaults={
                            'email': f'synth.donor.{i}@bbms.local',
                            'role': User.Role.DONOR,
                            'first_name': f'DemoDonor{i}',
                            'last_name': 'Test',
                            'date_of_birth': date(1996, 1, 1),
                            'is_approved': True,
                        }
                    )
                    synth_user.set_password('TestPass@123')
                    synth_user.save()
                    Appointment.objects.create(
                        donor=synth_user,
                        slot=full_slot,
                        location=full_slot.location,
                        date=full_slot.date,
                        time_slot=full_slot.time_label,
                        status=Appointment.Status.CONFIRMED,
                        donor_notes='Capacity fill demonstration',
                    )

        self.stdout.write("  [+] Seeded eligibility screenings and scheduled demo appointments.")

    def _seed_blood_units_and_testing(self, users, locations):
        """
        Seeds blood units showcasing the complete lifecycle:
        - Quarantined (newly collected)
        - Available (passed all 4 serology tests)
        - Discarded (failed serology test)
        - Past donations anchoring Rahul's and Priya's 90-day donation interval.
        """
        now = timezone.now()
        staff_john = users['staff_john']
        staff_mary = users['staff_mary']
        rahul = users['donor_rahul']
        priya = users['donor_priya']

        # Unit 1: Fresh Quarantined Unit collected today from Rahul (A+)
        u1, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-001-QNT',
            defaults={
                'donor': rahul,
                'blood_group': BloodGroup.A_POS,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': now - timedelta(hours=2),
                'status': BloodUnitStatus.QUARANTINED,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
                'collection_notes': 'Routine donation; pending serology panel',
                'status_audit_log': (
                    f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] "
                    "Unit collected and placed in Quarantined status by staff_john."
                ),
            }
        )

        # Unit 2: Available A+ Whole Blood from Rahul (120 days ago) -> Satisfies 90-day cooldown!
        u2_date = now - timedelta(days=120)
        u2, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-002-AV1',
            defaults={
                'donor': rahul,
                'blood_group': BloodGroup.A_POS,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': u2_date,
                'expiry_date': u2_date + timedelta(days=42),
                'status': BloodUnitStatus.AVAILABLE,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
                'collection_notes': 'Past successful donation',
            }
        )
        self._ensure_serology_tests(u2, staff_mary, all_pass=True)

        # Unit 3: Available A+ Whole Blood from Rahul (210 days ago) -> 2nd past donation
        u3_date = now - timedelta(days=210)
        u3, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-003-AV2',
            defaults={
                'donor': rahul,
                'blood_group': BloodGroup.A_POS,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': u3_date,
                'expiry_date': u3_date + timedelta(days=42),
                'status': BloodUnitStatus.AVAILABLE,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
            }
        )
        self._ensure_serology_tests(u3, staff_mary, all_pass=True)

        # Unit 4: Available B+ Whole Blood from Priya (30 days ago) -> Inside 90-day cooldown!
        u4_date = now - timedelta(days=30)
        u4, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-004-AV3',
            defaults={
                'donor': priya,
                'blood_group': BloodGroup.B_POS,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': u4_date,
                'expiry_date': u4_date + timedelta(days=42),
                'status': BloodUnitStatus.AVAILABLE,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
            }
        )
        self._ensure_serology_tests(u4, staff_mary, all_pass=True)

        # Unit 5: Available O- Universal Red Cell Unit (Collected 5 days ago, valid for 37 more days)
        u5_date = now - timedelta(days=5)
        u5, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-005-OPR',
            defaults={
                'donor': None,
                'blood_group': BloodGroup.O_NEG,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': u5_date,
                'expiry_date': u5_date + timedelta(days=42),
                'status': BloodUnitStatus.AVAILABLE,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
                'collection_notes': 'Universal donor stock',
            }
        )
        self._ensure_serology_tests(u5, staff_mary, all_pass=True)

        # Unit 6: Available AB+ Platelets (Collected 1 day ago, valid for 4 more days)
        u6_date = now - timedelta(days=1)
        u6, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-006-PLT',
            defaults={
                'donor': None,
                'blood_group': BloodGroup.AB_POS,
                'component_type': ComponentType.PLATELETS,
                'volume_ml': 300,
                'collection_date': u6_date,
                'expiry_date': u6_date + timedelta(days=5),
                'status': BloodUnitStatus.AVAILABLE,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
            }
        )
        self._ensure_serology_tests(u6, staff_mary, all_pass=True)

        # Unit 7: Discarded Unit (Failed HIV serology screen per BBMS-F-027)
        u7_date = now - timedelta(days=3)
        u7, created = BloodUnit.objects.get_or_create(
            bag_id='BAG-DEMO-007-DSC',
            defaults={
                'donor': None,
                'blood_group': BloodGroup.O_POS,
                'component_type': ComponentType.WHOLE_BLOOD,
                'volume_ml': 450,
                'collection_date': u7_date,
                'expiry_date': u7_date + timedelta(days=42),
                'status': BloodUnitStatus.DISCARDED,
                'location': 'Central Blood Bank',
                'collected_by': staff_john,
                'collection_notes': 'Serology failure quarantine disposal',
                'status_audit_log': (
                    f"[{u7_date.strftime('%Y-%m-%d %H:%M:%S')}] Status transitioned from 'Quarantined' to 'Discarded' "
                    "by staff_mary. Reason: Failed serology test(s): HIV"
                ),
            }
        )
        SerologyTest.objects.update_or_create(
            blood_unit=u7,
            test_type=SerologyTestType.HIV,
            defaults={'result': SerologyResult.FAIL, 'tested_by': staff_mary, 'tested_at': u7_date}
        )
        SerologyTest.objects.update_or_create(
            blood_unit=u7,
            test_type=SerologyTestType.HEPATITIS_B,
            defaults={'result': SerologyResult.PASS, 'tested_by': staff_mary, 'tested_at': u7_date}
        )
        SerologyTest.objects.update_or_create(
            blood_unit=u7,
            test_type=SerologyTestType.HEPATITIS_C,
            defaults={'result': SerologyResult.PASS, 'tested_by': staff_mary, 'tested_at': u7_date}
        )
        SerologyTest.objects.update_or_create(
            blood_unit=u7,
            test_type=SerologyTestType.SYPHILIS,
            defaults={'result': SerologyResult.PASS, 'tested_by': staff_mary, 'tested_at': u7_date}
        )

        self.stdout.write("  [+] Seeded blood inventory units (Quarantined, Available, Discarded) & serology records.")

    def _ensure_serology_tests(self, blood_unit, staff_user, all_pass=True):
        """Helper to ensure all 4 mandatory serology tests exist for an available unit."""
        for t_type in REQUIRED_SEROLOGY_TESTS:
            res = SerologyResult.PASS if all_pass else SerologyResult.FAIL
            SerologyTest.objects.update_or_create(
                blood_unit=blood_unit,
                test_type=t_type,
                defaults={
                    'result': res,
                    'tested_by': staff_user,
                    'tested_at': blood_unit.collection_date + timedelta(hours=1),
                    'notes': 'Automated lab panel assay passed',
                }
            )

    def _print_credentials_summary(self):
        """Displays clear demo login information in the terminal."""
        summary = """
================================================================================
                    BBMS SPRINT 1 DEMO SEED ACCOUNTS
================================================================================
Role            Username         Email                       Password
--------------------------------------------------------------------------------
Administrator   admin            admin@bbms.local            AdminPassword@123
Staff (Officer) staff_john       staff.john@bbms.local       StaffPassword@123
Staff (Lab Tech)staff_mary       staff.mary@bbms.local       StaffPassword@123
Donor (Eligible)donor_jane       donor.jane@bbms.local       DonorPassword@123
Donor (History) donor_rahul      donor.rahul@bbms.local      DonorPassword@123
Donor (Cooldown)donor_priya      donor.priya@bbms.local      DonorPassword@123
Donor (Inelig.) donor_vikram     donor.vikram@bbms.local     DonorPassword@123
Hospital (Appr) hospital_city    hospital.city@bbms.local    HospitalPassword@123
Hospital (Pend) hospital_metro   hospital.metro@bbms.local   HospitalPassword@123
================================================================================
Note: For local HTTP demonstration, run with BBMS_SECURE_COOKIES=0
================================================================================
"""
        self.stdout.write(summary)
