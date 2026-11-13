"""Which runner a coding panel uses (static/js/code_panel.js) for a track or a code language.

The panel runs Python, JavaScript, HTML (with its CSS and scripts) and SQL in the browser.
CSS on its own and JavaScript that changes a page both run as an HTML preview. Java can't
run in the browser, so its panel is an editor only.
"""

RUNNABLE = {"python", "javascript", "html", "sql"}


def panel_language(language, code=""):
    """The panel language for a track slug or a code language like "css", given the code."""
    language = (language or "").lower()
    if language == "css":
        return "html"
    if language == "javascript" and code.lstrip().startswith("<"):
        return "html"  # a page with a <script>, e.g. "Changing the page"
    if language in RUNNABLE or language == "java":
        return language
    return ""


def can_run(language, code=""):
    """Worth offering "Try this code": the panel can run it and show something."""
    language = (language or "").lower()
    if language == "css":
        return True  # previewed on a sample page
    return panel_language(language, code) in RUNNABLE
