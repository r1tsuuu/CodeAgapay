"""A practice task for every topic, so Practice stops saying "Soon" (content/drafts/practice.json).

Written for the coding panel: each has starter code to edit and run, a sample answer that was
run and checked, and a checklist. A topic that already has an approved task keeps it, and a
topic that doesn't exist (a fresh test database) is skipped. Run twice, nothing changes.
"""

import json
from pathlib import Path

from django.db import migrations

TASKS = Path(__file__).resolve().parent.parent / "drafts" / "practice.json"


def load(apps, schema_editor):
    Topic = apps.get_model("content", "Topic")
    PracticeTask = apps.get_model("content", "PracticeTask")
    for slug, task in json.loads(TASKS.read_text(encoding="utf-8")).items():
        topic = Topic.objects.filter(slug=slug).first()
        if topic is None or PracticeTask.objects.filter(topic=topic, approved=True).exists():
            continue
        PracticeTask.objects.create(
            topic=topic, prompt=task["prompt"], starter_code=task["starter_code"],
            sample_answer=task["sample_answer"], checklist=task["checklist"], approved=True,
            order=PracticeTask.objects.filter(topic=topic).count() + 1,
        )


class Migration(migrations.Migration):
    dependencies = [("content", "0011_unlock_tracks")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
