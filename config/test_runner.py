"""The test runner: every run starts from the safe defaults, whatever the shell or .env says.

A PowerShell window left with AI_PLANS=True, or a real GROQ_API_KEY in .env, must never change
what the tests check or make them call a real AI. Tests that need the AI or AI plans turn them on
themselves with override_settings, and mock every call.
"""

from django.conf import settings
from django.test.runner import DiscoverRunner

SAFE_DEFAULTS = {
    "AI_PLANS": False,
    "AI_OUTLINES": False,
    "GROQ_API_KEY": "",
    "CF_ACCOUNT_ID": "",
    "CF_API_TOKEN": "",
}


class Runner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        for name, value in SAFE_DEFAULTS.items():
            setattr(settings, name, value)
