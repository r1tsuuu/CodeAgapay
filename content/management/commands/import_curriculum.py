"""Make the database match the curriculum files. Safe to run on production, and to run twice.

    python manage.py import_curriculum --dry-run   show what would change, save nothing
    python manage.py import_curriculum

Never deletes topics, or questions and tasks learners have answered (it lists them instead).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content import curriculum


class DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Load content/curriculum/ into the database (validated first)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(curriculum.CURRICULUM_DIR))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dir, dry_run, **options):
        try:
            data = curriculum.load_valid(dir)
        except curriculum.CurriculumError as error:
            for line in error.errors:
                self.stderr.write(f"  {line}")
            raise CommandError("The curriculum files have problems; nothing was imported.") from None
        try:
            with transaction.atomic():
                report = curriculum.import_curriculum(data, data["version"], curriculum.checksum(dir))
                if dry_run:
                    raise DryRun
        except DryRun:
            pass
        for bucket in ("created", "updated", "removed"):
            counts = getattr(report, bucket)
            if counts:
                self.stdout.write(f"{bucket.title()}: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
        for line in report.kept:
            self.stdout.write(f"Kept {line}")
        if not report.changed:
            self.stdout.write("Nothing to change.")
        self.stdout.write(("Dry run: nothing saved. " if dry_run else "") + f"Curriculum {data['version']}.")
