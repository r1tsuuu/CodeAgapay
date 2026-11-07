"""Email learners who have gone quiet. Safe to run often: the rules in reminders.py decide who is due."""

from smtplib import SMTPException

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from learning import reminders


class Command(BaseCommand):
    help = "Send reminder emails to learners who have been away for a week."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List who is due without sending or saving.")

    def handle(self, *args, dry_run, **options):
        if not dry_run and not settings.EMAIL_HOST:
            raise CommandError("EMAIL_HOST isn't set, so nothing can be sent. Use --dry-run to see who is due.")
        sent = failed = 0
        for profile in reminders.candidates():
            reminder = reminders.reminder_for(profile)
            if reminder is None:
                continue
            label = f"{profile.user.email}: {reminder.action.title}"
            if dry_run:
                self.stdout.write(f"Would send to {label}")
                sent += 1
                continue
            try:
                reminders.send(reminder)
            except (SMTPException, OSError) as error:
                self.stderr.write(f"Failed for {profile.user.email}: {error}")
                failed += 1
            else:
                self.stdout.write(f"Sent to {label}")
                sent += 1
        self.stdout.write(f"{'Due' if dry_run else 'Sent'}: {sent}. Failed: {failed}.")
        if failed:
            raise CommandError(f"{failed} reminder(s) failed. Run again to retry them.")
