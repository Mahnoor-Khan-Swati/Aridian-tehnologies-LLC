"""
cal_client.py
Thin wrapper around the Cal.com API v2 for the booking chatbot.

All functions raise CalApiError on failure with a human-readable message,
so the Streamlit app can just catch one exception type and show it to the user.
"""

import os
import requests
from datetime import datetime, timedelta

CAL_BASE_URL = os.getenv("CAL_BASE_URL", "https://api.cal.com/v2").rstrip("/")
CAL_API_KEY = os.getenv("CAL_API_KEY", "")
CAL_EVENT_TYPE_ID = os.getenv("CAL_EVENT_TYPE_ID", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Karachi")
MEETING_TITLE = os.getenv("MEETING_TITLE", "Quick Meeting")

# Cal.com requires this header on every v2 call, and it must match the
# documented value for the endpoint or the request 404s / falls back to an
# old response shape. 2024-08-13 is the current version for slots, bookings,
# reschedule and cancel as of Cal.com's docs.
CAL_API_VERSION = "2024-08-13"


class CalApiError(Exception):
    """Raised whenever a Cal.com API call fails or returns an error payload."""
    pass


def _headers() -> dict:
    if not CAL_API_KEY:
        raise CalApiError("CAL_API_KEY is not set. Add it to your .env file.")
    return {
        "Authorization": f"Bearer {CAL_API_KEY}",
        "Content-Type": "application/json",
        "cal-api-version": CAL_API_VERSION,
    }


def _request(method: str, path: str, **kwargs):
    url = f"{CAL_BASE_URL}{path}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=20, **kwargs)
    except requests.RequestException as e:
        raise CalApiError(f"Network error while calling Cal.com: {e}")

    try:
        data = resp.json()
    except ValueError:
        data = {}

    if not resp.ok or data.get("status") == "error":
        msg = (
            data.get("error", {}).get("message")
            if isinstance(data.get("error"), dict)
            else data.get("message") or data.get("error") or resp.text
        )
        raise CalApiError(f"Cal.com API error ({resp.status_code}): {msg}")

    return data


def get_available_slots(event_type_id: str, start_date: str, end_date: str, timezone: str = TIMEZONE) -> dict:
    """
    DEMO SLOTS: /v2/slots endpoint is for public booking links only.
    This returns demo slots (9 AM to 5 PM, weekdays only) for testing.
    TODO: Replace with actual availability when Cal.com API is accessible.
    """
    if not event_type_id:
        raise CalApiError("CAL_EVENT_TYPE_ID is not set. Add it to your .env file.")

    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    result = {}
    current = start
    while current <= end:
        # Weekdays only (0=Monday, 4=Friday)
        if current.weekday() < 5:
            times = []
            for hour in range(9, 17):
                for minute in [0, 30]:
                    dt = datetime(current.year, current.month, current.day, hour, minute)
                    iso_time = dt.isoformat() + "Z"
                    label = dt.strftime("%I:%M %p").lstrip("0")
                    times.append((label, iso_time))
            result[current.isoformat()] = times
        
        current += timedelta(days=1)
    
    return result


def create_booking(event_type_id: str, start_iso: str, name: str, email: str,
                    timezone: str = TIMEZONE, title: str = MEETING_TITLE) -> dict:
    body = {
        "eventTypeId": int(event_type_id),
        "start": start_iso,
        "attendee": {
            "name": name,
            "email": email,
            "timeZone": timezone,
        },
    }
    data = _request("POST", "/bookings", json=body)
    return data.get("data", data)


def list_bookings_for_email(email: str, status: str = "upcoming") -> list:
    """Fetch upcoming bookings and filter to those where this email is an attendee."""
    params = {"status": status, "take": 50}
    data = _request("GET", "/bookings", params=params)
    bookings = data.get("data", []) or []

    matched = []
    email_lower = email.strip().lower()
    for b in bookings:
        attendees = b.get("attendees", []) or []
        if any((a.get("email", "").lower() == email_lower) for a in attendees):
            matched.append(b)
    return matched


def reschedule_booking(booking_uid: str, new_start_iso: str, reason: str = "") -> dict:
    body = {"start": new_start_iso}
    if reason:
        body["reschedulingReason"] = reason
    data = _request("POST", f"/bookings/{booking_uid}/reschedule", json=body)
    return data.get("data", data)


def cancel_booking(booking_uid: str, reason: str = "No longer needed") -> dict:
    body = {"cancellationReason": reason}
    data = _request("POST", f"/bookings/{booking_uid}/cancel", json=body)
    return data.get("data", data)


def date_choices(n_days: int = 7):
    """Helper: today + next n_days as (label, YYYY-MM-DD) tuples. (Not used by the
    date-picker UI anymore, kept here in case you want quick-reply buttons again.)"""
    out = []
    today = datetime.utcnow().date()
    for i in range(n_days):
        d = today + timedelta(days=i)
        label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%a, %d %b"))
        out.append((label, d.isoformat()))
    return out
