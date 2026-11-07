"""Check every active resource link and record the result for curators in admin."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand

from content.linkcheck import check_url, record
from content.models import Resource

WORKERS = 8


class Command(BaseCommand):
    help = "Check active resource links. Results show in admin under Resources, filtered by link status."

    def add_arguments(self, parser):
        parser.add_argument("--track", help="Only check this track (its slug).")

    def handle(self, *args, track, **options):
        resources = Resource.objects.filter(is_active=True).select_related("topic")
        if track:
            resources = resources.filter(topic__track__slug=track)
        resources = list(resources)
        # Only the web requests run in threads; the database saves stay on this one.
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = pool.map(check_url, [r.url for r in resources])
            for resource, result in zip(resources, results):
                record(resource, result)
        counts = Counter(r.link_status for r in resources)
        for resource in resources:
            if resource.link_status != Resource.LinkStatus.OK:
                self.stdout.write(
                    f"{resource.get_link_status_display()}: {resource.topic.title} / "
                    f"{resource.title} ({resource.link_note}) {resource.url}"
                )
        self.stdout.write(
            f"Checked {len(resources)}: {counts['ok']} OK, {counts['unsure']} to check by hand, "
            f"{counts['broken']} broken."
        )
