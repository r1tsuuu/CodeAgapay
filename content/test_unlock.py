"""The migration that fills and opens the tracks that showed "Coming soon" (content 0011)."""

import importlib
import json
from pathlib import Path

from django.apps import apps
from django.test import TestCase

from content.models import QuizItem, Topic, Track

unlock = importlib.import_module("content.migrations.0011_unlock_tracks")
DRAFTS = Path(__file__).resolve().parent / "drafts"


class UnlockTracksTests(TestCase):
    def setUp(self):
        for order, slug in enumerate(unlock.TRACKS, 2):
            Track.objects.create(name=slug.upper(), slug=slug, order=order, is_active=False)

    def test_fills_and_opens_every_track(self):
        unlock.load(apps, None)
        for slug in unlock.TRACKS:
            track = Track.objects.get(slug=slug)
            self.assertTrue(track.is_active, slug)
            self.assertEqual(track.topics.count(), 5, slug)
            self.assertTrue(track.setup_steps.exists(), slug)
            self.assertTrue(track.project_ideas.exists(), slug)

    def test_topics_are_complete_and_chained(self):
        unlock.load(apps, None)
        topics = list(Topic.objects.filter(track__slug="sql").order_by("order"))
        self.assertEqual(topics[0].title, "Reading data with SELECT")
        for before, after in zip(topics, topics[1:]):
            self.assertEqual(list(after.prerequisites.all()), [before])
        for topic in topics:
            self.assertTrue(topic.intro_approved)
            self.assertEqual(topic.resources.count(), 2)
            self.assertEqual(topic.skill_questions.count(), 2)
            self.assertEqual(topic.quiz_items.count(), 4)
            topic.full_clean()
        for item in QuizItem.objects.filter(topic__track__slug__in=unlock.TRACKS):
            item.full_clean()  # every prompt has its ___ blank

    def test_running_twice_adds_nothing(self):
        unlock.load(apps, None)
        count = Topic.objects.count()
        unlock.load(apps, None)
        self.assertEqual(Topic.objects.count(), count)

    def test_keeps_existing_topics(self):
        html = Track.objects.get(slug="html")
        Topic.objects.create(track=html, title="Page structure", slug="html-page-structure", order=1, summary="Mine")
        unlock.load(apps, None)
        self.assertEqual(Topic.objects.get(slug="html-page-structure").summary, "Mine")
        self.assertEqual(html.topics.count(), 5)

    def test_skips_tracks_that_dont_exist(self):
        Track.objects.filter(slug="java").delete()
        unlock.load(apps, None)
        self.assertFalse(Track.objects.filter(slug="java").exists())

    def test_draft_files_have_five_topics_each(self):
        for slug in unlock.TRACKS:
            data = json.loads((DRAFTS / f"{slug}.json").read_text(encoding="utf-8"))
            self.assertEqual(data["track"], slug)
            self.assertEqual(len(data["topics"]), 5, slug)
