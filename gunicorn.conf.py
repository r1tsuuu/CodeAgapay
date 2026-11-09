"""Gunicorn settings. Gunicorn reads this file by itself when it starts in the project folder,
so Render's start command (gunicorn config.wsgi:application) needs no flags.
"""

# Seconds a request may run before the worker is restarted (the default is 30). An AI-written
# lesson or plan is made inside a page request; their AI calls stay within AI_REQUEST_BUDGET
# (50 seconds, config/settings.py), so this leaves room to save and show the page.
timeout = 60
