"""Create an administrator using environment credentials, never defaults."""

import os

from django.core.management.base import BaseCommand, CommandError

from booking.models import User


class Command(BaseCommand):
    help = "Create admin from ADMIN_USERNAME and ADMIN_PASSWORD."

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        if not username or not password:
            raise CommandError("Set ADMIN_USERNAME and ADMIN_PASSWORD.")
        if User.objects.filter(username=username).exists():
            raise CommandError("User already exists; no credentials changed.")
        User.objects.create_superuser(
            username=username, password=password, role="admin"
        )
        self.stdout.write(self.style.SUCCESS("Administrator created."))
