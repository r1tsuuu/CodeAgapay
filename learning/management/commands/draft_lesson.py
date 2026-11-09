"""Try the AI lesson prompt and see what it writes and what it costs.

    python manage.py draft_lesson --title "Your first HTML page" --track HTML \\
        --can "Create a page with headings and a list" --earlier "What is a web page?"
    python manage.py draft_lesson --outline 3 --lesson L2
    python manage.py draft_lesson --outline 3 --lesson L2 --struggled "nesting tags" --save

One AI call (two if the first reply is unusable). Nothing is saved unless --save is
given with --outline; saved lessons appear in admin for review, as a new version.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from assistant.service import ai_available
from learning.lessons import LessonSpec, build_messages, generate_lesson, spec_from_outline
from learning.models import PlanOutline
from learning.outline import load_prompt


class Command(BaseCommand):
    help = "Draft an AI lesson from a saved outline, or from a lesson typed in by hand."

    def add_arguments(self, parser):
        parser.add_argument("--outline", type=int, help="ID of a saved plan outline (see admin)")
        parser.add_argument("--lesson", help='Lesson key in that outline, e.g. "L2"')
        parser.add_argument("--title", help="Lesson title (when not using --outline)")
        parser.add_argument("--can", default="", help='"You will be able to ..." line')
        parser.add_argument("--track", default="Python", help="Track name(s), e.g. HTML or \"HTML, CSS\"")
        parser.add_argument("--level", choices=["beginner", "intermediate", "advanced"], default="beginner")
        parser.add_argument("--kind", choices=["foundation", "recap", "core", "optional"], default="core")
        parser.add_argument("--minutes", type=int, default=25)
        parser.add_argument("--earlier", default="", help='Earlier lesson titles, separated by "|"')
        parser.add_argument("--project", default="")
        parser.add_argument("--taglish", action="store_true")
        parser.add_argument("--struggled", action="append", default=[],
                            help="What the learner struggled with (repeatable); asks for a different way of teaching")
        parser.add_argument("--save", action="store_true", help="Save as the lesson's new version (needs --outline)")
        parser.add_argument("--show-prompt", action="store_true", help="Print the messages sent, and stop")
        parser.add_argument("--raw", action="store_true",
                            help="Also print the model's reply before checks, with hidden characters as \\u codes")

    def handle(self, *args, **opts):
        outline, spec = self._spec(opts)
        if opts["save"] and outline is None:
            raise CommandError("--save needs --outline: a typed-in lesson has no outline to belong to.")

        if opts["show_prompt"]:
            messages, version = build_messages(spec)
            for message in messages:
                self.stdout.write(self.style.MIGRATE_HEADING(f"--- {message['role']} ({version})"))
                self.stdout.write(message["content"])
            return
        if not ai_available():
            raise CommandError("Set GROQ_API_KEY (or the Cloudflare keys) in .env first.")

        self.stdout.write(f"Drafting {spec.key} \"{spec.title}\" with prompt {load_prompt('lesson')[1]} ...")
        record = generate_lesson(spec, outline, save=opts["save"])
        if record is None:
            raise CommandError("The AI didn't return a usable lesson. Try again, or check the provider keys.")
        if opts["raw"]:
            self.stdout.write(self.style.MIGRATE_HEADING("--- model reply, before checks"))
            self.stdout.write(json.dumps(record.raw, indent=2, ensure_ascii=True))
            self.stdout.write(self.style.MIGRATE_HEADING("--- after checks"))
        self.stdout.write(json.dumps(record.data, indent=2, ensure_ascii=False))
        for repair in record.repairs:
            self.stdout.write(self.style.WARNING(f"Repaired: {repair}"))
        for flag in record.flags:
            self.stdout.write(self.style.ERROR(f"Flagged for review: {flag}"))
        saved = f" · saved as version {record.version}" if opts["save"] else " · not saved"
        self.stdout.write(self.style.SUCCESS(
            f"{record.model}: {record.prompt_tokens} tokens in, {record.completion_tokens} out{saved}"
        ))

    def _spec(self, opts):
        if opts["outline"]:
            outline = PlanOutline.objects.select_related("learner__path").filter(pk=opts["outline"]).first()
            if outline is None:
                raise CommandError(f"No outline {opts['outline']}.")
            try:
                return outline, spec_from_outline(outline, opts["lesson"] or "L1", opts["struggled"])
            except KeyError:
                raise CommandError(f"No lesson {opts['lesson']!r} in outline {outline.pk}.")
        if not opts["title"]:
            raise CommandError("Give --outline (and --lesson), or --title for a typed-in lesson.")
        return None, LessonSpec(
            key="L1", title=opts["title"], can=opts["can"], minutes=opts["minutes"], kind=opts["kind"],
            level=opts["level"], path="Learn to code", tracks=opts["track"],
            earlier=[t.strip() for t in opts["earlier"].split("|") if t.strip()],
            project=opts["project"], taglish=opts["taglish"], struggled=opts["struggled"],
        )
