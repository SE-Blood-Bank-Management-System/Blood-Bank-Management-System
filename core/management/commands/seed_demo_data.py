"""
Alias for seed_data command.
Allows running either `python manage.py seed_data` or `python manage.py seed_demo_data`.
"""
from core.management.commands.seed_data import Command as SeedDataCommand


class Command(SeedDataCommand):
    help = 'Alias for seed_data - seeds database with realistic demo accounts, slots, and inventory'
