"""Load unreviewed content from a file in content/drafts/ for curators to check.

    python manage.py load_drafts content/drafts/html.json

Safe on a database with curated content: it only adds things, finds tracks and topics by
slug, and skips anything already there. Run it twice and nothing changes.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content.drafting import DraftError, save_draft
from content.models import ProjectIdea, QuizItem, Resource, SetupStep, Topic, Track


class Command(BaseCommand):
    help = "Add draft topics, setup steps, project ideas and quiz items from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("file", help="e.g. content/drafts/html.json")
        parser.add_argument(
            "--allow-active-track", action="store_true",
            help="Save into a track learners can already see (drafts go live before review)",
        )

    @transaction.atomic
    def handle(self, *args, file, allow_active_track, **options):
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        try:
            track = Track.objects.get(slug=data["track"])
        except Track.DoesNotExist:
            raise CommandError(f"No track with slug {data['track']!r}. Create it in admin first.")
        if track.is_active and not allow_active_track:
            raise CommandError(
                f"{track.name} is live, so drafts would reach learners before review. "
                "Deactivate it in admin first, or pass --allow-active-track."
            )
        added = self._setup_steps(track, data) + self._project_ideas(track, data)
        added += self._topics(track, data) + self._quiz_items(track, data)
        self.stdout.write(f"{track.name}: added {added}. Review them in admin before the track goes live.")

    def _setup_steps(self, track, data):
        steps = data.get("setup_steps", [])
        if track.setup_steps.exists():
            return 0
        for order, step in enumerate(steps, 1):
            SetupStep.objects.create(track=track, order=order, **step)
        return len(steps)

    def _project_ideas(self, track, data):
        added = 0
        for order, idea in enumerate(data.get("project_ideas", []), 1):
            if not track.project_ideas.filter(title=idea["title"]).exists():
                ProjectIdea.objects.create(track=track, order=order, **idea)
                added += 1
        return added

    def _topics(self, track, data):
        added = 0
        previous = Topic.objects.filter(track=track).order_by("order", "title").last()
        for draft in data.get("topics", []):
            if track.topics.filter(title=draft["title"]).exists():
                continue
            try:
                previous, _ = save_draft(track, draft["title"], draft, prerequisite=previous)
            except DraftError as error:
                raise CommandError(str(error))
            for order, resource in enumerate(draft.get("resources", []), 1):
                Resource.objects.create(topic=previous, order=order, **resource)
            added += 1
        return added

    def _quiz_items(self, track, data):
        added = 0
        for item in data.get("quiz_items", []):
            try:
                topic = track.topics.get(slug=item["topic"])
            except Topic.DoesNotExist:
                self.stderr.write(f"Skipped {item['prompt']!r}: no topic {item['topic']!r} in {track.name}.")
                continue
            if not topic.quiz_items.filter(prompt=item["prompt"]).exists():
                quiz_item = QuizItem(
                    topic=topic, prompt=item["prompt"],
                    accepted_answers=item["accepted_answers"], hint=item.get("hint", ""),
                )
                quiz_item.full_clean()
                quiz_item.save()
                added += 1
        return added
