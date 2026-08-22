# Cal.com Booking Assistant (Streamlit)

A chatbot-style Streamlit app that lets a visitor **schedule**, **update (reschedule)**,
or **cancel** a meeting on your Cal.com event type — all through natural chat buttons,
using the Cal.com API v2.

## ⚠️ Security first
Your original message contained a **live Cal.com API key in plain text**. Since it was
shared in this conversation, consider it compromised:
1. Go to Cal.com → **Settings → Developer → API Keys**
2. Delete/refresh that key and generate a new one
3. Put the *new* key only in your local `.env` file — never in chat, code, or GitHub

## Setup

```bash
cd cal_chatbot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with your real API key
```

Fill in `.env`:
```
CAL_API_KEY=cal_live_xxxxxxxxxxxxxxxx
CAL_EVENT_TYPE_ID=6671003        # the numeric ID of your Cal.com event type
TIMEZONE=Asia/Karachi
MEETING_TITLE=Quick Meeting
```

**Finding your Event Type ID:** open the event type in Cal.com's dashboard — the ID is
in the URL (`app.cal.com/event-types/6671003`), or call `GET /v2/event-types` with your
API key to list them.

## Run

```bash
streamlit run app.py
```

## How it works

- `cal_client.py` — all Cal.com API v2 calls (get slots, create booking, list bookings,
  reschedule, cancel), each wrapped so failures raise a single `CalApiError`.
- `app.py` — the chat UI and conversation flow (a small state machine kept in
  `st.session_state`), styled to resemble a dark chat widget.

### Conversation flow
1. Bot asks for name, then email.
2. Bot shows a menu: **Schedule / Update / Cancel / Something else**.
3. **Schedule** → pick a date → bot fetches real open slots from Cal.com → pick a time →
   booking is created (`POST /v2/bookings`).
4. **Update** → bot looks up the visitor's upcoming bookings by email → pick one → pick a
   new date/time → booking is moved (`POST /v2/bookings/{uid}/reschedule`).
5. **Cancel** → same lookup → pick a booking → confirm → booking is cancelled
   (`POST /v2/bookings/{uid}/cancel`).

## Notes
- Booking lookups for update/cancel filter Cal.com's upcoming-bookings list by the
  attendee email the user typed in chat — no login/auth flow beyond that.
- `CAL_EVENT_TYPE_ID` must belong to your Cal.com account and its API key.
- If you get a `404` from Cal.com, double check the `cal-api-version` header requirement
  hasn't changed — Cal.com versions endpoints independently.
