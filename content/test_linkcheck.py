from io import StringIO
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .linkcheck import FAILED, GONE, OK, UNSURE, Result, check_url, record
from .models import Resource, Topic, Track

Status = Resource.LinkStatus


def response(code):
    fake = MagicMock(status_code=code)
    fake.__enter__.return_value = fake
    return fake


class CheckUrlTests(TestCase):
    def outcome(self, code):
        with patch("content.linkcheck.requests.get", return_value=response(code)):
            return check_url("https://example.test").outcome

    def test_success_is_ok(self):
        self.assertEqual(self.outcome(200), OK)

    def test_not_found_and_gone_are_gone(self):
        self.assertEqual(self.outcome(404), GONE)
        self.assertEqual(self.outcome(410), GONE)

    def test_refusals_and_server_errors_are_unsure(self):
        for code in (401, 403, 429, 500, 503):
            self.assertEqual(self.outcome(code), UNSURE, code)

    def test_connection_problems_fail_without_raising(self):
        for error in (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError):
            with patch("content.linkcheck.requests.get", side_effect=error()):
                self.assertEqual(check_url("https://example.test").outcome, FAILED)

    def test_never_downloads_the_page(self):
        with patch("content.linkcheck.requests.get", return_value=response(200)) as get:
            check_url("https://example.test")
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertGreater(get.call_args.kwargs["timeout"], 0)


class LinkMixin:
    def setUp(self):
        track = Track.objects.create(name="Python", slug="python")
        self.topic = Topic.objects.create(track=track, title="Loops", slug="loops")
        self.resource = Resource.objects.create(topic=self.topic, title="Docs", url="https://example.test/a")


class RecordTests(LinkMixin, TestCase):
    def apply(self, outcome, note="x"):
        record(self.resource, Result(outcome, note))
        self.resource.refresh_from_db()
        return self.resource.link_status

    def test_ok_saves_the_time(self):
        self.assertEqual(self.apply(OK), Status.OK)
        self.assertIsNotNone(self.resource.last_checked)

    def test_gone_is_broken_at_once(self):
        self.assertEqual(self.apply(GONE, "HTTP 404"), Status.BROKEN)
        self.assertEqual(self.resource.link_note, "HTTP 404")

    def test_one_connection_failure_is_only_unsure(self):
        self.assertEqual(self.apply(FAILED), Status.UNSURE)

    def test_two_connection_failures_in_a_row_are_broken(self):
        self.apply(FAILED)
        self.assertEqual(self.apply(FAILED), Status.BROKEN)

    def test_success_resets_the_failures(self):
        self.apply(FAILED)
        self.apply(OK)
        self.assertEqual(self.resource.failed_checks, 0)
        self.assertEqual(self.apply(FAILED), Status.UNSURE)

    def test_a_refusal_never_becomes_broken(self):
        for _ in range(5):
            self.assertEqual(self.apply(UNSURE), Status.UNSURE)
        self.assertEqual(self.resource.failed_checks, 0)

    def test_stays_visible_to_learners(self):
        self.apply(GONE)
        self.assertTrue(self.resource.is_active)


class CheckLinksCommandTests(LinkMixin, TestCase):
    def run_command(self, *args, code=200):
        out = StringIO()
        with patch("content.linkcheck.requests.get", return_value=response(code)) as get:
            call_command("check_links", *args, stdout=out)
        return out.getvalue(), get

    def test_records_results_and_reports_problems(self):
        output, _ = self.run_command(code=404)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.link_status, Status.BROKEN)
        self.assertIn("Broken: Loops / Docs (HTTP 404) https://example.test/a", output)
        self.assertIn("Checked 1: 0 OK, 0 to check by hand, 1 broken.", output)

    def test_skips_inactive_resources(self):
        self.resource.is_active = False
        self.resource.save()
        _, get = self.run_command()
        get.assert_not_called()

    def test_track_option_limits_the_check(self):
        other = Track.objects.create(name="SQL", slug="sql")
        topic = Topic.objects.create(track=other, title="Select", slug="select")
        Resource.objects.create(topic=topic, title="SQL docs", url="https://example.test/b")
        _, get = self.run_command("--track", "sql")
        self.assertEqual([c.args[0] for c in get.call_args_list], ["https://example.test/b"])

    def test_admin_can_filter_by_link_status(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))
        self.run_command(code=404)
        page = self.client.get(reverse("admin:content_resource_changelist"), {"link_status__exact": "broken"})
        self.assertContains(page, "Docs")
        self.assertContains(page, "HTTP 404")
