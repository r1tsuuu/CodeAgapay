"""Check the curriculum files in content/curriculum/. Needs no database.

    python manage.py validate_curriculum           shapes and rules (scripts/check.sh runs this)
    python manage.py validate_curriculum --links   also open every active resource link
"""

from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError

from content import curriculum, linkcheck


class Command(BaseCommand):
    help = "Validate content/curriculum/ files; --links also checks resource links."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(curriculum.CURRICULUM_DIR))
        parser.add_argument("--links", action="store_true", help="Open every active resource link (needs internet).")

    def handle(self, *args, dir, links, **options):
        data = curriculum.load(dir)
        errors = curriculum.validate(data)
        for error in errors:
            self.stderr.write(f"  {error}")
        if errors:
            raise CommandError(f"{len(errors)} problem(s) in the curriculum files.")
        topics = sum(len(t["topics"]) for t in data["tracks"])
        self.stdout.write(f"Curriculum {data['version']}: {len(data['tracks'])} tracks, {topics} topics, "
                          f"{len(data['paths'])} paths. Valid.")
        if links:
            self._check_links(data)

    def _check_links(self, data):
        found = list(curriculum.all_resource_urls(data))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(linkcheck.check_url, [url for _, url in found]))
        broken = 0
        for (where, url), result in zip(found, results):
            if result.outcome == linkcheck.OK:
                continue
            label = "BROKEN" if result.outcome == linkcheck.GONE else "check by hand"
            broken += result.outcome == linkcheck.GONE
            self.stdout.write(f"{label}: {where} ({result.note}) {url}")
        self.stdout.write(f"Checked {len(found)} links: {broken} broken.")
        if broken:
            raise CommandError(f"{broken} broken link(s). Fix them in the curriculum files.")
