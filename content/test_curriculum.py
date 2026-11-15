"""The curriculum files: validation, import, export, and plans that survive content changes."""

import copy
import json
import tempfile
from io import StringIO
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import get_profile
from learning.models import PlanItem, QuizAttempt
from learning.planner import build_plan

from . import curriculum
from .models import CurriculumRelease, Path, QuizItem, Resource, Topic, Track


def tiny():
    """A small valid curriculum: one live track with two topics, one path."""
    topic = {
        "slug": "py-vars", "title": "Variables", "summary": "Store a value.", "estimated_minutes": 60,
        "resources": [{"title": "Python docs", "url": "https://docs.python.org/3/tutorial/", "kind": "docs"}],
        "tips": ["Name things clearly."],
        "skill_questions": [{"prompt": "What does x = 2 do?", "choices": ["Stores 2", "Prints 2"], "correct_index": 0}],
        "quiz_items": [{"prompt": "x ___ 2", "accepted_answers": ["="]}, {"prompt": "___(x)", "accepted_answers": ["print"]}],
    }
    loops = {**copy.deepcopy(topic), "slug": "py-loops", "title": "Loops", "prerequisites": ["py-vars"]}
    return {
        "version": "test.1",
        "paths": [{"slug": "automation", "title": "Automate", "tagline": "Small tools.", "tracks": ["python"]}],
        "tracks": [{
            "slug": "python", "name": "Python", "is_active": True,
            "project_ideas": [{"title": "Stock counter", "brief": "Count stock.", "done_when": ["It runs."]}],
            "topics": [topic, loops],
        }],
    }


def write(data, directory):
    directory = FilePath(directory)
    (directory / "tracks").mkdir(parents=True, exist_ok=True)
    (directory / "curriculum.json").write_text(json.dumps({"version": data["version"], "paths": data["paths"]}))
    for track in data["tracks"]:
        (directory / "tracks" / f"{track['slug']}.json").write_text(json.dumps(track))


class ValidationTests(TestCase):
    def test_the_repo_curriculum_is_valid(self):
        self.assertEqual(curriculum.validate(curriculum.load()), [])

    def test_tiny_curriculum_is_valid(self):
        self.assertEqual(curriculum.validate(tiny()), [])

    def assertInvalid(self, data, text):
        errors = curriculum.validate(data)
        self.assertTrue(any(text in e for e in errors), errors)

    def test_missing_version(self):
        data = tiny()
        data["version"] = ""
        self.assertInvalid(data, "'version'")

    def test_unknown_prerequisite(self):
        data = tiny()
        data["tracks"][0]["topics"][1]["prerequisites"] = ["nope"]
        self.assertInvalid(data, "prerequisite 'nope'")

    def test_prerequisite_cycle(self):
        data = tiny()
        data["tracks"][0]["topics"][0]["prerequisites"] = ["py-loops"]
        self.assertInvalid(data, "go in a circle")

    def test_duplicate_topic_slug_across_tracks(self):
        data = tiny()
        other = copy.deepcopy(data["tracks"][0])
        other["slug"], other["is_active"] = "java", False
        other["topics"] = [other["topics"][0]]
        data["tracks"].append(other)
        self.assertInvalid(data, "unique across tracks")

    def test_correct_index_out_of_range(self):
        data = tiny()
        data["tracks"][0]["topics"][0]["skill_questions"][0]["correct_index"] = 5
        self.assertInvalid(data, "correct_index")

    def test_quiz_blank_required(self):
        data = tiny()
        data["tracks"][0]["topics"][0]["quiz_items"][0]["prompt"] = "no blank"
        self.assertInvalid(data, "___")

    def test_http_links_refused(self):
        data = tiny()
        data["tracks"][0]["topics"][0]["resources"][0]["url"] = "http://example.com"
        self.assertInvalid(data, "https://")

    def test_unknown_field_is_a_typo(self):
        data = tiny()
        data["tracks"][0]["topics"][0]["sumary"] = "typo"
        self.assertInvalid(data, "unknown field 'sumary'")

    def test_active_track_needs_checkpoint_resource_and_project(self):
        data = tiny()
        track = data["tracks"][0]
        track["project_ideas"] = []
        track["topics"][0]["quiz_items"] = []
        track["topics"][0]["resources"][0]["is_active"] = False
        errors = curriculum.validate(data)
        for text in ("project idea", "checkpoint", "active resource"):
            self.assertTrue(any(text in e for e in errors), (text, errors))

    def test_inactive_track_may_be_incomplete(self):
        data = tiny()
        data["tracks"][0]["is_active"] = False
        data["tracks"][0]["project_ideas"] = []
        self.assertEqual(curriculum.validate(data), [])

    def test_path_must_name_real_tracks(self):
        data = tiny()
        data["paths"][0]["tracks"] = ["cobol"]
        self.assertInvalid(data, "no track 'cobol'")

    def test_command_fails_on_problems(self):
        data = tiny()
        data["version"] = ""
        with tempfile.TemporaryDirectory() as directory:
            write(data, directory)
            with self.assertRaises(CommandError):
                call_command("validate_curriculum", dir=directory, stdout=StringIO(), stderr=StringIO())


class ImportTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def run_import(self, data, dry_run=False):
        write(data, self.dir.name)
        out = StringIO()
        call_command("import_curriculum", dir=self.dir.name, dry_run=dry_run, stdout=out)
        return out.getvalue()

    def test_import_creates_everything_and_records_the_release(self):
        self.run_import(tiny())
        loops = Topic.objects.get(slug="py-loops")
        self.assertEqual(list(loops.prerequisites.values_list("slug", flat=True)), ["py-vars"])
        self.assertEqual(loops.order, 2)
        self.assertEqual(Path.objects.get(slug="automation").ordered_tracks(), [Track.objects.get(slug="python")])
        self.assertEqual(CurriculumRelease.current_version(), "test.1")

    def test_import_twice_changes_nothing(self):
        self.run_import(tiny())
        out = self.run_import(tiny())
        self.assertIn("Nothing to change", out)
        self.assertEqual(CurriculumRelease.objects.count(), 1)

    def test_dry_run_saves_nothing(self):
        self.run_import(tiny(), dry_run=True)
        self.assertFalse(Topic.objects.exists())
        self.assertFalse(CurriculumRelease.objects.exists())

    def test_invalid_files_import_nothing(self):
        data = tiny()
        data["tracks"][0]["topics"][1]["prerequisites"] = ["nope"]
        write(data, self.dir.name)
        with self.assertRaises(CommandError):
            call_command("import_curriculum", dir=self.dir.name, stdout=StringIO(), stderr=StringIO())
        self.assertFalse(Topic.objects.exists())

    def test_edits_update_in_place_and_reset_a_changed_link(self):
        self.run_import(tiny())
        resource = Resource.objects.get(topic__slug="py-vars")
        resource.link_status = Resource.LinkStatus.BROKEN
        resource.save()
        data = tiny()
        data["version"] = "test.2"
        data["tracks"][0]["topics"][0]["resources"][0]["url"] = "https://docs.python.org/3/"
        self.run_import(data)
        resource.refresh_from_db()
        self.assertEqual(resource.url, "https://docs.python.org/3/")
        self.assertEqual(resource.link_status, "")
        self.assertEqual(CurriculumRelease.current_version(), "test.2")

    def test_removed_resource_is_hidden_not_deleted(self):
        self.run_import(tiny())
        data = tiny()
        data["tracks"][0]["topics"][0]["resources"] = [
            {"title": "W3Schools", "url": "https://www.w3schools.com/python/", "kind": "interactive"},
        ]
        data["tracks"][0]["topics"][0]["resources"].append(
            {"title": "Other", "url": "https://example.org/x", "kind": "article", "is_active": False})
        self.run_import(data)
        self.assertEqual(Resource.objects.filter(topic__slug="py-vars").count(), 2)

    def test_answered_quiz_items_and_missing_topics_are_kept(self):
        self.run_import(tiny())
        user = get_user_model().objects.create_user("ana")
        profile = get_profile(user)
        item = QuizItem.objects.filter(topic__slug="py-vars").last()
        QuizAttempt.objects.create(learner=profile, quiz_item=item, answer="x", is_correct=False)
        data = tiny()
        data["tracks"][0]["topics"][0]["quiz_items"] = data["tracks"][0]["topics"][0]["quiz_items"][:1]
        data["tracks"][0]["topics"] = data["tracks"][0]["topics"][:1]
        out = self.run_import(data)
        self.assertTrue(QuizItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(Topic.objects.filter(slug="py-loops").exists())
        self.assertIn("learners have answered it", out)
        self.assertIn("topic py-loops", out)

    def test_export_then_import_is_a_round_trip(self):
        self.run_import(tiny())
        with tempfile.TemporaryDirectory() as out_dir:
            curriculum.export(out_dir, "test.1")
            exported = curriculum.load(out_dir)
            self.assertEqual(curriculum.validate(exported), [])
            self.assertEqual([t["slug"] for t in exported["tracks"][0]["topics"]], ["py-vars", "py-loops"])
            report = curriculum.import_curriculum(exported, "test.1", curriculum.checksum(out_dir))
        self.assertFalse(report.changed, report.as_dict())


class PlansAndVersionsTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        write(tiny(), directory.name)
        call_command("import_curriculum", dir=directory.name, stdout=StringIO())
        self.profile = get_profile(get_user_model().objects.create_user("ana"))
        self.profile.track = Track.objects.get(slug="python")
        self.profile.hours_per_week = 3
        self.profile.save()

    def test_plan_records_the_curriculum_version(self):
        self.assertEqual(build_plan(self.profile).curriculum_version, "test.1")

    def test_a_topic_in_a_plan_cannot_be_deleted(self):
        plan = build_plan(self.profile)
        with self.assertRaises(ProtectedError):
            Topic.objects.get(slug="py-vars").delete()
        self.assertEqual(PlanItem.objects.filter(plan=plan).count(), 2)
