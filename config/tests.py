from django.test import TestCase


class SmokeTests(TestCase):
    def test_admin_login_page_loads(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)

    def test_404_page_is_friendly(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user("ana"))
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)

    def test_500_page_renders_without_context(self):
        from django.template.loader import render_to_string
        self.assertIn("Something went wrong", render_to_string("500.html"))


class HealthTests(TestCase):
    def test_health_needs_no_login_and_reports_the_database(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_health_says_503_when_the_database_fails(self):
        from unittest import mock

        with mock.patch("config.health.connection.cursor", side_effect=RuntimeError("down")), \
                self.assertLogs("config.health", "ERROR"):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("down", response.content.decode())


class LoggingTests(TestCase):
    def test_log_lines_are_json_and_secrets_are_redacted(self):
        import json
        import logging

        from django.test import override_settings

        from config.logging import JsonFormatter, RedactSecrets

        with override_settings(GROQ_API_KEY="gsk_live_secret_value"):
            record = logging.LogRecord("x", logging.WARNING, __file__, 1, "key is %s", ("gsk_live_secret_value",), None)
            RedactSecrets().filter(record)
            line = json.loads(JsonFormatter().format(record))
        self.assertEqual(line["level"], "WARNING")
        self.assertEqual(line["message"], "key is [redacted]")
