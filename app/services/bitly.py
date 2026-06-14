"""Bitly v4 API client — DESIGN.md §8.1."""
import os

import requests

BASE = "https://api-ssl.bitly.com/v4"
TIMEOUT = 15


class BitlyError(Exception):
    pass


def _headers():
    token = os.environ.get("BITLY_API_TOKEN")
    if not token:
        raise BitlyError("BITLY_API_TOKEN is not configured in .env")
    return {"Authorization": f"Bearer {token}"}


def shorten(long_url, domain=None, custom_backhalf=None):
    """Create a short link. Returns {'link', 'id', 'raw'}.

    A custom back-half is created in a **single** ``POST /v4/bitlinks`` call
    using the ``keyword`` field, so Bitly does not also create a throwaway
    random bitlink (the old two-call /shorten + /custom_bitlinks flow made two
    links and consumed two from the monthly quota). Without a custom back-half
    we use the simpler ``/shorten`` endpoint.
    """
    payload = {"long_url": long_url}
    if domain:
        payload["domain"] = domain
    # Optional: pin a specific Bitly group. If unset, the token's default
    # group is used (same behaviour as before).
    group = os.environ.get("BITLY_GROUP_GUID")
    if group:
        payload["group_guid"] = group

    if custom_backhalf:
        payload["keyword"] = custom_backhalf
        endpoint = "/bitlinks"
    else:
        endpoint = "/shorten"

    r = requests.post(
        f"{BASE}{endpoint}", json=payload, headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code not in (200, 201):
        if custom_backhalf:
            raise BitlyError(
                f"Bitly rejected the custom back-half '{custom_backhalf}' "
                f"({r.status_code}): {r.text[:300]}"
            )
        raise BitlyError(f"Bitly {endpoint} failed ({r.status_code}): {r.text[:300]}")
    data = r.json()
    return {"link": data["link"], "id": data["id"], "raw": data}


def get_clicks(bitly_id, unit="hour", units=-1):
    """Per-unit click counts for a bitlink. units=-1 → full history."""
    r = requests.get(
        f"{BASE}/bitlinks/{bitly_id}/clicks",
        params={"unit": unit, "units": units},
        headers=_headers(),
        timeout=20,
    )
    if r.status_code == 429:
        raise BitlyError("Bitly rate limit reached (HTTP 429)")
    if r.status_code != 200:
        raise BitlyError(f"Bitly clicks failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def get_metric(bitly_id, metric):
    """metric: countries | cities | referrers | devices."""
    r = requests.get(
        f"{BASE}/bitlinks/{bitly_id}/{metric}", headers=_headers(), timeout=20
    )
    if r.status_code != 200:
        raise BitlyError(f"Bitly {metric} failed ({r.status_code}): {r.text[:300]}")
    return r.json()
