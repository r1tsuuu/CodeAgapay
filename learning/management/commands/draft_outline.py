"""Try the AI plan outline prompt and see what it writes and what it costs.

    python manage.py draft_outline --path make-a-website --experience none --hours 3 --weeks 8 \\
        --goal "a page for our org" --project "an event page"
    python manage.py draft_outline --learner ana@example.com
    python manage.py draft_outline --learner ana@example.com --save

One AI call (two if the first reply has no usable lessons). Nothing is saved
unless --save is given with --learner; saved outlines appear in admin for review.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.models import LearnerProfile
from assistant.service import ai_available
from content.models import Path
from learning.outline import build_messages, generate_outline, load_prompt, project_ideas


class Command(BaseCommand):
    help = "Draft an AI plan outline for a learner, or for made-up answers."

    def add_arguments(self, parser):
        parser.add_argument("--learner", help="Username or email of an existing learner")
        parser.add_argument("--path", help="Path slug, e.g. make-a-website (when not using --learner)")
        parser.add_argument("--experience", choices=[c for c, _ in LearnerProfile.Experience.choices], default="none")
        parser.add_argument("--hours", type=int, default=3, help="Hours per week")
        parser.add_argument("--weeks", type=int, help="Weeks until their target date")
        parser.add_argument("--goal", default="")
        parser.add_argument("--project", default="", help="The learner's own project idea")
        parser.add_argument("--hint-style", choices=[c for c, _ in LearnerProfile.HintStyle.choices], default="")
        parser.add_argument("--save", action="store_true", help="Save it for review in admin (needs --learner)")
        parser.add_argument("--show-prompt", action="store_true", help="Print the messages sent, and stop")
        parser.add_argument("--raw", action="store_true",
                            help="Also print the model's reply before checks, with hidden characters as \\u codes")

    def handle(self, *args, **opts):
        if opts["save"] and not opts["learner"]:
            raise CommandError("--save needs --learner: made-up answers have no learner to save under.")
        profile, project = self._profile(opts)

        if opts["show_prompt"]:
            messages, version = build_messages(profile, project, project_ideas(profile))
            for message in messages:
                self.stdout.write(self.style.MIGRATE_HEADING(f"--- {message['role']} ({version})"))
                self.stdout.write(message["content"])
            return
        if not ai_available():
            raise CommandError("Set GROQ_API_KEY (or the Cloudflare keys) in .env first.")

        self.stdout.write(f"Drafting an outline with prompt {load_prompt()[1]} ...")
        record = generate_outline(profile, project, save=opts["save"])
        if record is None:
            raise CommandError("The AI didn't return a usable outline. Try again, or check the provider keys.")
        if opts["raw"]:
            self.stdout.write(self.style.MIGRATE_HEADING("--- model reply, before checks"))
            self.stdout.write(json.dumps(record.raw, indent=2, ensure_ascii=True))
            self.stdout.write(self.style.MIGRATE_HEADING("--- after checks"))
        self.stdout.write(json.dumps(record.data, indent=2, ensure_ascii=False))
        for repair in record.repairs:
            self.stdout.write(self.style.WARNING(f"Repaired: {repair}"))
        self.stdout.write(self.style.SUCCESS(
            f"{record.model}: {record.prompt_tokens} tokens in, {record.completion_tokens} out"
            + (" · saved for review in admin" if opts["save"] else " · not saved")
        ))

    def _profile(self, opts):
        """An existing learner, or an unsaved one built from the options."""
        if opts["learner"]:
            user = get_user_model().objects.filter(
                Q(username=opts["learner"]) | Q(email=opts["learner"])
            ).first()
            if user is None or not hasattr(user, "learner_profile"):
                raise CommandError(f"No learner {opts['learner']!r}.")
            profile = user.learner_profile
            return profile, opts["project"] or profile.goal_text
        if not opts["path"]:
            raise CommandError("Give --learner, or --path with made-up answers.")
        path = Path.objects.filter(slug=opts["path"]).first()
        if path is None:
            slugs = ", ".join(Path.objects.values_list("slug", flat=True)) or "none loaded"
            raise CommandError(f"No path {opts['path']!r}. Paths: {slugs}")
        profile = LearnerProfile(
            path=path, track=path.first_track(), experience=opts["experience"], hours_per_week=opts["hours"],
            target_weeks=opts["weeks"], goal_text=opts["goal"], hint_style=opts["hint_style"],
        )
        return profile, opts["project"]
