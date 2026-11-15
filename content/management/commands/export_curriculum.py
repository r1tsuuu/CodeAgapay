"""Write the database's curriculum to content/curriculum/, e.g. after quick fixes in admin.

    DATABASE_URL="<production url>" python manage.py export_curriculum
    python manage.py export_curriculum --release 2026.11.20

Then review the diff with git and commit it, so the files stay the source of truth.
"""

from django.core.management.base import BaseCommand

from content import curriculum


class Command(BaseCommand):
    help = "Export paths, tracks and topics from the database to content/curriculum/."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(curriculum.CURRICULUM_DIR))
        parser.add_argument("--release", help="A new version string; default keeps the files' current one.")

    def handle(self, *args, dir, release, **options):
        written = curriculum.export(dir, release)
        self.stdout.write(f"Wrote curriculum.json and {len(written)} track files to {dir}. Review with git diff.")
