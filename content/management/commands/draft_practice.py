"""Draft a practice task for existing topics, for curators to review in admin.

    python manage.py draft_practice python
    python manage.py draft_practice python python-loops python-lists

Each topic costs one Groq call. Tasks are saved hidden (Approved unticked), so learners
never see them until a curator checks and approves each one in admin.
Topics that already have a practice task (approved or not) are left alone.
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from content.drafting import DraftError, make_client, request_practice, save_practice
from content.models import Track

from .draft_topic import DEFAULT_DRAFT_MODEL


class Command(BaseCommand):
    help = "Use AI to draft a practice task for existing topics."

    def add_arguments(self, parser):
        parser.add_argument("track", help="Track slug, e.g. python")
        parser.add_argument("slugs", nargs="*", help="Topic slugs (default: every topic in the track)")
        parser.add_argument("--model", default=DEFAULT_DRAFT_MODEL, help="Groq model id")
        parser.add_argument("--dry-run", action="store_true", help="Print drafts without saving")

    def handle(self, *args, track, slugs, model, dry_run, **options):
        if not settings.GROQ_API_KEY:
            raise CommandError("Set GROQ_API_KEY in .env first.")
        try:
            track = Track.objects.get(slug=track)
        except Track.DoesNotExist:
            raise CommandError(f"No track with slug {track!r}.")

        topics = list(track.topics.order_by("order", "title"))
        unknown = set(slugs) - {t.slug for t in topics}
        if unknown:
            raise CommandError(f"Not in {track.name}: {', '.join(sorted(unknown))}")

        client = make_client(settings.GROQ_API_KEY)
        earlier_titles = []
        saved = failed = 0
        for topic in topics:
            if (not slugs or topic.slug in slugs) and not topic.practice_tasks.exists():
                self.stdout.write(f"Drafting practice for {topic.title} ...")
                try:
                    data = request_practice(client, model, topic, earlier_titles)
                    if dry_run:
                        self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
                    else:
                        task = save_practice(topic, data)
                        self.stdout.write(self.style.SUCCESS(f"  saved, {len(task.checklist)} checks"))
                        saved += 1
                except DraftError as error:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"  skipped: {error}"))
                except Exception as error:  # Network or API errors: report and move on.
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"  skipped: Groq call failed ({error})"))
            earlier_titles.append(topic.title)

        if not dry_run:
            self.stdout.write(
                f"\n{saved} drafted, {failed} skipped. Next: check each task in admin "
                "(run the sample answer!), fix anything wrong, then tick Approved."
            )
