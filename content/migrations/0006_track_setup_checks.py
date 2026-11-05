"""Give the existing tracks the small "check it works" step that ends their setup.

Only fills a blank setup_check on tracks that exist, so empty databases (tests) stay empty.
"""

from django.db import migrations

CHECKS = {
    "python": 'Run a file containing print("Hello!") and see Hello! printed.',
    "html": "Open your index.html in a browser and see your name as a heading.",
    "css": "Link style.css to your page and see your heading change colour.",
    "javascript": 'Type console.log("Hello!") in the browser console and see Hello! printed.',
    "sql": "Run SELECT * FROM movies; in the first SQLBolt exercise and see rows come back.",
    "java": "Run a Hello.java file that prints your name.",
}


def seed(apps, schema_editor):
    Track = apps.get_model("content", "Track")
    for track in Track.objects.filter(slug__in=CHECKS, setup_check=""):
        track.setup_check = CHECKS[track.slug]
        track.save(update_fields=["setup_check"])


class Migration(migrations.Migration):
    dependencies = [("content", "0005_topic_intro_and_setup_check")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
