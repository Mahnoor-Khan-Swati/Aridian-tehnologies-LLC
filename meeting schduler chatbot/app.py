"""
Cal.com Booking Assistant - a Streamlit chatbot that can schedule, update
(reschedule) and cancel meetings on a Cal.com event type, using the Cal.com
API v2.

Run with:  streamlit run app.py
Configure via a .env file (see .env.example).
"""

import streamlit as st
from dotenv import load_dotenv
import os

load_dotenv()

import cal_client as cal  # noqa: E402  (import after load_dotenv so env vars are set)

EVENT_TYPE_ID = os.getenv("CAL_EVENT_TYPE_ID", "")
BUSINESS_NAME = os.getenv("MEETING_TITLE", "Quick Meeting")

st.set_page_config(page_title="Booking Assistant", page_icon="🗓️", layout="centered")

# ---------- Dark chat-bubble styling (loosely matches the reference screenshots) ----------
st.markdown("""
<style>
.stApp { background-color: #0e0e10; }
.stChatMessage { background-color: transparent; }
div[data-testid="stChatMessageContent"] {
    background-color: #262629;
    border-radius: 14px;
    padding: 6px 4px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_state():
    defaults = {
        "history": [],          # [(role, text)]
        "stage": "ask_name",
        "name": "",
        "email": "",
        "flow": None,           # "schedule" | "update" | "cancel"
        "picked_date": None,
        "picked_slot_label": None,
        "picked_slot_iso": None,
        "my_bookings": [],
        "picked_booking": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


def bot(text):
    st.session_state.history.append(("assistant", text))


def user(text):
    st.session_state.history.append(("user", text))


def reset_flow():
    st.session_state.flow = None
    st.session_state.picked_date = None
    st.session_state.picked_slot_label = None
    st.session_state.picked_slot_iso = None
    st.session_state.my_bookings = []
    st.session_state.picked_booking = None
    st.session_state.stage = "menu"


# ---------------------------------------------------------------------------
# First greeting
# ---------------------------------------------------------------------------
if not st.session_state.history:
    bot(f"Hi! Welcome to {BUSINESS_NAME} scheduling assistant. 👋\n\nI can help you **schedule**, "
        f"**update**, or **cancel** an appointment.\n\nTo get started, may I have your name?")

# ---------------------------------------------------------------------------
# Render chat history
# ---------------------------------------------------------------------------
for role, text in st.session_state.history:
    with st.chat_message(role):
        st.markdown(text)

stage = st.session_state.stage


# ---------------------------------------------------------------------------
# Helper: render a quick-reply button row, return the clicked label or None
# ---------------------------------------------------------------------------
def quick_replies(options, key_prefix):
    cols = st.columns(len(options))
    clicked = None
    for col, opt in zip(cols, options):
        if col.button(opt, key=f"{key_prefix}_{opt}"):
            clicked = opt
    return clicked


import datetime as _dt  # noqa: E402


def date_picker(key_prefix):
    """
    Renders a real calendar date-picker (click to open, scroll/click through
    months, or type the date) plus a confirm button.
    Returns the picked date as an ISO string ("YYYY-MM-DD") once confirmed,
    otherwise None.
    """
    picked = st.date_input(
        "Pick a date",
        value=_dt.date.today(),
        min_value=_dt.date.today(),
        key=f"{key_prefix}_date_input",
        label_visibility="collapsed",
    )
    if st.button("Check availability", key=f"{key_prefix}_check_btn"):
        return picked.isoformat()
    return None


# ---------------------------------------------------------------------------
# Stage: ask_name / ask_email  -> handled through chat_input
# ---------------------------------------------------------------------------
if stage in ("ask_name", "ask_email"):
    prompt = st.chat_input("Type your answer...")
    if prompt:
        user(prompt)
        if stage == "ask_name":
            st.session_state.name = prompt.strip()
            bot(f"Thanks, {st.session_state.name}! What's your email address?")
            st.session_state.stage = "ask_email"
        else:
            st.session_state.email = prompt.strip()
            bot("Got it! How can I help you today?")
            st.session_state.stage = "menu"
        st.rerun()

# ---------------------------------------------------------------------------
# Stage: menu
# ---------------------------------------------------------------------------
elif stage == "menu":
    choice = quick_replies(
        ["Schedule an appointment", "Update my appointment", "Cancel my appointment", "Something else"],
        "menu",
    )
    if choice:
        user(choice)
        if choice == "Schedule an appointment":
            st.session_state.flow = "schedule"
            bot("Great! Which day would you like to come in?")
            st.session_state.stage = "schedule_pick_date"
        elif choice == "Update my appointment":
            st.session_state.flow = "update"
            st.session_state.stage = "load_bookings"
        elif choice == "Cancel my appointment":
            st.session_state.flow = "cancel"
            st.session_state.stage = "load_bookings"
        else:
            bot("No problem — just type your question below and I'll do my best to help.")
            st.session_state.stage = "freeform"
        st.rerun()

# ---------------------------------------------------------------------------
# SCHEDULE FLOW
# ---------------------------------------------------------------------------
elif stage == "schedule_pick_date":
    picked = date_picker("sched")
    if picked:
        user(picked)
        st.session_state.picked_date = picked
        try:
            slots = cal.get_available_slots(EVENT_TYPE_ID, picked, picked)
        except cal.CalApiError as e:
            bot(f"⚠️ Couldn't fetch availability: {e}")
            st.session_state.stage = "menu"
            st.rerun()
        day_slots = slots.get(picked, [])
        if not day_slots:
            bot(f"Sorry, there's no availability on **{picked}** (weekends only show availability on weekdays). Please pick a **Monday-Friday**.")
        else:
            st.session_state["_day_slots"] = day_slots
            bot(f"✅ Meeting is available on **{picked}**! Here are the open times — pick one to book:")
            st.session_state.stage = "schedule_pick_slot"
        st.rerun()

elif stage == "schedule_pick_slot":
    day_slots = st.session_state.get("_day_slots", [])
    labels = [lbl for lbl, _ in day_slots]
    choice = quick_replies(labels, "slot")
    if choice:
        iso = dict(day_slots)[choice]
        user(choice)
        st.session_state.picked_slot_label = choice
        st.session_state.picked_slot_iso = iso
        try:
            cal.create_booking(EVENT_TYPE_ID, iso, st.session_state.name, st.session_state.email)
            bot(f"✅ Your appointment is confirmed for **{choice}** on **{st.session_state.picked_date}**. "
                f"You'll get a confirmation email at {st.session_state.email}.")
        except cal.CalApiError as e:
            bot(f"⚠️ Couldn't book that slot: {e}")
        bot("Anything else I can help with?")
        reset_flow()
        st.rerun()

# ---------------------------------------------------------------------------
# LOAD MY BOOKINGS (shared by update + cancel)
# ---------------------------------------------------------------------------
elif stage == "load_bookings":
    try:
        bookings = cal.list_bookings_for_email(st.session_state.email)
    except cal.CalApiError as e:
        bot(f"⚠️ Couldn't fetch your bookings: {e}")
        reset_flow()
        st.rerun()
    if not bookings:
        bot("I couldn't find any upcoming bookings under that email.")
        reset_flow()
        st.rerun()
    else:
        st.session_state.my_bookings = bookings
        verb = "update" if st.session_state.flow == "update" else "cancel"
        bot(f"Here are your upcoming bookings. Which one would you like to {verb}?")
        st.session_state.stage = "pick_booking"
        st.rerun()

elif stage == "pick_booking":
    bookings = st.session_state.my_bookings
    labels = [f"{b.get('title', 'Meeting')} — {b.get('start', '')[:16].replace('T', ' ')}" for b in bookings]
    choice = quick_replies(labels, "bk")
    if choice:
        idx = labels.index(choice)
        st.session_state.picked_booking = bookings[idx]
        user(choice)
        if st.session_state.flow == "cancel":
            st.session_state.stage = "cancel_confirm"
            bot(f"Just to confirm — cancel **{choice}**?")
        else:
            bot("Which new day would you like instead?")
            st.session_state.stage = "update_pick_date"
        st.rerun()

# ---------------------------------------------------------------------------
# UPDATE (RESCHEDULE) FLOW
# ---------------------------------------------------------------------------
elif stage == "update_pick_date":
    picked = date_picker("upd")
    if picked:
        user(picked)
        st.session_state.picked_date = picked
        try:
            slots = cal.get_available_slots(EVENT_TYPE_ID, picked, picked)
        except cal.CalApiError as e:
            bot(f"⚠️ Couldn't fetch availability: {e}")
            reset_flow()
            st.rerun()
        day_slots = slots.get(picked, [])
        if not day_slots:
            bot(f"Sorry, there's no availability on **{picked}** (weekends only show availability on weekdays). Please pick a **Monday-Friday**.")
        else:
            st.session_state["_day_slots"] = day_slots
            bot(f"✅ Meeting is available on **{picked}**! Pick a new time:")
            st.session_state.stage = "update_pick_slot"
        st.rerun()

elif stage == "update_pick_slot":
    day_slots = st.session_state.get("_day_slots", [])
    labels = [lbl for lbl, _ in day_slots]
    choice = quick_replies(labels, "uslot")
    if choice:
        iso = dict(day_slots)[choice]
        user(choice)
        booking_uid = st.session_state.picked_booking.get("uid")
        try:
            cal.reschedule_booking(booking_uid, iso, reason="Attendee requested a new time")
            bot(f"✅ Your appointment has been moved to **{choice}** on **{st.session_state.picked_date}**.")
        except cal.CalApiError as e:
            bot(f"⚠️ Couldn't reschedule: {e}")
        bot("Anything else I can help with?")
        reset_flow()
        st.rerun()

# ---------------------------------------------------------------------------
# CANCEL FLOW
# ---------------------------------------------------------------------------
elif stage == "cancel_confirm":
    choice = quick_replies(["Yes, cancel it", "No, keep it"], "cancelconf")
    if choice:
        user(choice)
        if choice == "Yes, cancel it":
            booking_uid = st.session_state.picked_booking.get("uid")
            try:
                cal.cancel_booking(booking_uid, reason="Cancelled by attendee via chatbot")
                bot("✅ Your appointment has been cancelled.")
            except cal.CalApiError as e:
                bot(f"⚠️ Couldn't cancel: {e}")
        else:
            bot("No changes made — your booking is still active.")
        bot("Anything else I can help with?")
        reset_flow()
        st.rerun()

# ---------------------------------------------------------------------------
# Freeform / fallback
# ---------------------------------------------------------------------------
elif stage == "freeform":
    prompt = st.chat_input("Type your message...")
    if prompt:
        user(prompt)
        bot("I've noted that. For bookings, tap below to go back to the menu.")
        st.session_state.stage = "menu"
        st.rerun()

# Always offer a way back to the main menu once a flow finishes
if stage == "menu" and len(st.session_state.history) > 2:
    pass  # menu buttons already rendered above
