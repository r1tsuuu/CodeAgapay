"""Checks that curated links still work. Run by the `check_links` command.

Links are never hidden automatically: this only tells curators which ones to look at.
Many sites refuse scripts, so a refusal is "unsure", not broken. A 404 or 410 is broken
straight away. A connection failure may be a blip, so it takes FAILS_TO_BREAK in a row.
"""

from dataclasses import dataclass

import requests
from django.utils import timezone

from .models import Resource

TIMEOUT_SECONDS = 15
FAILS_TO_BREAK = 2
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CodeAgapayLinkCheck/1.0)"}

OK, GONE, FAILED, UNSURE = "ok", "gone", "failed", "unsure"


@dataclass
class Result:
    outcome: str
    note: str


def check_url(url):
    # GET, not HEAD: plenty of sites answer HEAD wrongly. stream=True skips downloading the page.
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, stream=True) as response:
            code = response.status_code
    except requests.RequestException as error:
        return Result(FAILED, type(error).__name__)
    if code < 400:
        return Result(OK, f"HTTP {code}")
    return Result(GONE if code in (404, 410) else UNSURE, f"HTTP {code}")


def record(resource, result):
    """Save a check's result on the resource."""
    if result.outcome == OK:
        resource.failed_checks = 0
        resource.link_status = Resource.LinkStatus.OK
    elif result.outcome == UNSURE:
        resource.link_status = Resource.LinkStatus.UNSURE
    else:
        resource.failed_checks += 1
        broken = result.outcome == GONE or resource.failed_checks >= FAILS_TO_BREAK
        resource.link_status = Resource.LinkStatus.BROKEN if broken else Resource.LinkStatus.UNSURE
    resource.link_note = result.note[:100]
    resource.last_checked = timezone.now()
    resource.save(update_fields=["link_status", "link_note", "failed_checks", "last_checked"])
