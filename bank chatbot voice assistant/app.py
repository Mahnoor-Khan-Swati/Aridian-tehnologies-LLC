"""

app.py

======

HBL Banking Information Voice Assistant

Features:

- One custom green microphone

- Urdu, Roman Urdu and English conversation

- Direct responses for greetings and small talk

- HBL document-based answers for banking questions

- OpenAI STT and Cartesia Sonic-3.6 TTS

- Cached audio for common greetings

- Safe live transcript

- Text chat, document search and FAQs

"""

import base64

import hashlib

import html

import logging

import os

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import re

import time

from pathlib import Path

import streamlit as st

import streamlit.components.v1 as components

from src.config import config, validate_config

from src.document_loader import load_pdf

from src.text_splitter import split_documents
from src.audio_cache import get_common_reply_audio

from src.vector_store import (

    get_vector_store,

    is_index_empty,

    index_documents,

    get_retriever,

)

from src.llm_chain import (

    get_llm,

    get_prompt,

    generate_answer_stream,

    enforce_masculine_grammar,

)

from src.stt import transcribe_audio

from src.tts import (

    generate_audio,

    concat_wavs,

    warmup,

    VOICE,

    MODEL,

)

# ==========================================================

# 1. PAGE CONFIGURATION

# ==========================================================

st.set_page_config(

    page_title="HBL Banking Information Assistant",

    page_icon="🏦",

    layout="wide",

    initial_sidebar_state="expanded",

)

PROJECT_ROOT = Path(__file__).resolve().parent

QUICK_AUDIO_FOLDER = (

    PROJECT_ROOT / "static" / "quick_replies"

)

# ==========================================================

# 2. NAVIGATION AND FAQs

# ==========================================================

NAV = [

    ("live", "Live Call", ":material/call:"),

    ("text", "Text Chat", ":material/chat_bubble:"),

    ("search", "Document Search", ":material/description:"),

    ("faq", "FAQs", ":material/help:"),

    ("about", "About", ":material/info:"),

]

FAQS = [

    "How can I open an account at HBL?",

    "What are the debit card charges?",

    "What documents are required to open an account?",

    "How can I report a lost or stolen card?",

    "What are the HBL contact details?",

    "مجھے ایچ بی ایل میں اکاؤنٹ کھولنے کا طریقہ بتائیں۔",

]

# ==========================================================

# 3. CSS

# ==========================================================

CSS = """

<style>

@import url(

'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Naskh+Arabic:wght@400;500;600&display=swap'

);

:root {

    --green: #08765D;

    --dark-green: #064C3D;

    --light-green: #E5F4EE;

    --background: #F0F8F5;

    --border: #D5E9E0;

    --text: #172F28;

    --muted: #658076;

}

html,

body,

.stApp {

    font-family: Inter, sans-serif;

}

.stApp {

    background: var(--background);

    color: var(--text);

}

.block-container {

    max-width: 1180px;

    padding-top: 1rem;

}

/* SIDEBAR */

section[data-testid="stSidebar"] {

    background: linear-gradient(

        180deg,

        #075B49,

        #043E32

    );

}

.logo {

    text-align: center;

    color: white;

    padding: 20px 0;

}

.logo b {

    display: block;

    font-size: 38px;

    letter-spacing: 3px;

}

.logo small {

    font-size: 12px;

    line-height: 1.6;

}

section[data-testid="stSidebar"] .stButton button {

    width: 100%;

    justify-content: flex-start;

    background: transparent;

    border: none;

    color: white;

    border-radius: 10px;

}

section[data-testid="stSidebar"] .stButton button:hover {

    background: rgba(255,255,255,.15);

}

/* TOP BANNER */

.banner {

    display: flex;

    align-items: center;

    gap: 15px;

    background: #E1F1EB;

    border: 1px solid #CEE5DA;

    border-radius: 15px;

    padding: 18px 24px;

    margin-bottom: 15px;

}

.banner-icon {

    font-size: 30px;

}

.banner-title {

    font-size: 22px;

    font-weight: 800;

    color: var(--text);

}

.banner-subtitle {

    font-size: 13px;

    color: var(--muted);

}

/* MAIN CARDS */

.st-key-live_call,

.st-key-live_transcript,

.st-key-other_card {

    background: white;

    border: 1px solid var(--border);

    border-radius: 26px;

    padding: 26px 30px;

    box-shadow: 0 8px 30px rgba(5,74,55,.035);

}

/* LIVE CALL */

.live-eyebrow {

    color: var(--green);

    font-size: 12px;

    font-weight: 800;

    letter-spacing: 1.5px;

}

.live-title {

    font-size: 28px;

    font-weight: 800;

    color: var(--text);

    margin-top: 8px;

}

.live-subtitle {

    color: var(--muted);

    font-size: 14px;

    margin-top: 5px;

}

/* KEEP THE EXISTING CUSTOM MICROPHONE */

.st-key-live_call iframe {

    width: 100% !important;

    border: 0 !important;

    background: #fff !important;

}

.st-key-live_call {

    overflow: hidden;

}

/* TRANSCRIPT */

.transcript-heading {

    display: flex;

    justify-content: space-between;

    color: #587367;

    font-size: 13px;

    font-weight: 800;

    letter-spacing: 1px;

    margin-bottom: 20px;

}

.chat-bubble {

    padding: 15px 20px;

    border-radius: 24px;

    max-width: 85%;

    margin: 14px 0;

    line-height: 1.8;

    overflow-wrap: anywhere;

    font-family:

        'Noto Naskh Arabic',

        Inter,

        sans-serif;

}

.chat-bubble.customer {

    background: var(--green);

    color: white;

    margin-left: auto;

}

.chat-bubble.agent {

    background: #F4FAF7;

    color: var(--text);

    border: 1px solid var(--border);

    margin-right: auto;

}

.chat-bubble small {

    display: block;

    font-family: Inter, sans-serif;

    font-size: 11px;

    font-weight: 800;

    margin-bottom: 5px;

    opacity: .7;

}

/* BUTTONS */

.stApp button[kind="primary"] {

    background: var(--green);

    border-color: var(--green);

    color: white;

}

</style>

"""

st.markdown(

    CSS,

    unsafe_allow_html=True,

)

# ==========================================================

# 4. SESSION STATE

# ==========================================================

DEFAULT_STATE = {

    "view": "live",

    "live_active": False,

    "live_started": None,

    "live_call_id": None,

    "live_messages": [],

    "live_last_hash": None,

    "live_audio": None,

    "live_audio_id": 0,

    "live_error": None,

    "last_component_event": None,

    "text_messages": [],

}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:

        st.session_state[key] = value

# ==========================================================

# 5. SAFE MESSAGE HANDLING

# ==========================================================

def message_to_text(message) -> str:

    """

    Safely extract text from a string, dictionary,

    list or other message value.

    Fixes:

        AttributeError:

        'dict' object has no attribute 'replace'

    """

    if message is None:

        return ""

    if isinstance(message, str):

        return message

    if isinstance(message, dict):

        for key in (

            "text",

            "content",

            "message",

            "answer",

            "response",

        ):

            value = message.get(key)

            if value is not None:

                return message_to_text(value)

        return str(message)

    if isinstance(message, list):

        parts = [

            message_to_text(item)

            for item in message

        ]

        return " ".join(

            part

            for part in parts

            if part

        )

    return str(message)

def add_message(role: str, message):

    """

    Store transcript messages as plain strings.

    """

    text = message_to_text(message).strip()

    if text:

        st.session_state.live_messages.append(

            (role, text)

        )

# ==========================================================

# 6. DIRECT GREETINGS AND DAILY-LIFE CONVERSATION

# ==========================================================

def normalize_message(message: str) -> str:

    """

    Normalize punctuation and spaces.

    Examples:

        Hello!!! -> hello

        How are you? -> how are you

        Assalam-o-Alaikum -> assalam o alaikum

    """

    text = message.strip().lower()

    text = re.sub(

        r"[^\w\s\u0600-\u06FF]",

        " ",

        text,

    )

    return " ".join(text.split())

def get_greeting_response(

    question: str,

) -> str | None:

    """

    Directly answer greetings and simple small talk.

    If the question is about banking, return None.

    Banking questions must use HBL documents.

    """

    text = normalize_message(question)



    greetings = {

        # ======================================================

        # ENGLISH GREETINGS

        # ======================================================

        "hello": (

            "Hello! I'm your HBL Banking Information Assistant. "

            "How can I help you?"

        ),

        "hi": (

            "Hi! How can I help you?"

        ),

        "hey": (

            "Hello! How can I help you?"

        ),

        "hello there": (

            "Hello! How can I help you?"

        ),

        "hi there": (

            "Hi there! How can I help you?"

        ),

        "good morning": (

            "Good morning! How can I help you?"

        ),

        "good afternoon": (

            "Good afternoon! How can I help you?"

        ),

        "good evening": (

            "Good evening! How can I help you?"

        ),



        # ======================================================

        # ENGLISH SMALL TALK

        # ======================================================

        "how are you": (

            "I'm doing well, thank you! How are you?"

        ),

        "how are you doing": (

            "I'm doing well, thanks! How about you?"

        ),

        "how r u": (

            "I'm good, thanks! How can I help you?"

        ),

        "how are you today": (

            "I'm doing well, thank you! "

            "How can I help you today?"

        ),

        "im fine": (

            "That's good to hear! What can I help you with?"

        ),

        "i am fine": (

            "Glad to hear that! How can I help you?"

        ),

        "i am good": (

            "That's great! What can I help you with?"

        ),

        "what is your name": (

            "I'm your HBL Banking Information Assistant."

        ),

        "who are you": (

            "I'm your HBL Banking Information Assistant. "

            "How can I help you?"

        ),

        "thank you": (

            "You're welcome! Is there anything else "

            "I can help you with?"

        ),

        "thanks": (

            "You're welcome!"

        ),

        "thank you so much": (

            "You're very welcome!"

        ),

        "bye": (

            "Goodbye! Have a great day."

        ),

        "goodbye": (

            "Goodbye! Take care."

        ),

        "see you": (

            "See you! Take care."

        ),



        # ======================================================

        # ROMAN URDU GREETINGS

        # Replies are in Urdu script for natural Urdu TTS.

        # ======================================================

        "assalam o alaikum": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "assalam alaikum": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "assalamu alaikum": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "asalam o alaikum": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "salam": (

            "وعلیکم السلام! جی فرمائیے۔"

        ),

        "salaam": (

            "وعلیکم السلام! جی فرمائیے۔"

        ),



        # ======================================================

        # ROMAN URDU SMALL TALK

        # ======================================================

        "aap kaisi hain": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "ap kaisi hain": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "aap kaise hain": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "ap kaise hain": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "kya haal hai": (

            "جی، میں ٹھیک ہوں، شکریہ! آپ سنائیے؟"

        ),

        "kia haal hai": (

            "جی، میں ٹھیک ہوں، شکریہ! آپ سنائیے؟"

        ),

        "main theek hoon": (

            "بہت اچھا! بتائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "shukriya": (

            "جی، خوشی ہوئی! "

            "کیا میں آپ کی مزید مدد کر سکتا ہوں؟"

        ),

        "bohat shukriya": (

            "آپ کا بہت شکریہ! "

            "کیا میں آپ کی مزید مدد کر سکتا ہوں؟"

        ),

        "allah hafiz": (

            "اللہ حافظ! اپنا خیال رکھیے۔"

        ),

        "khuda hafiz": (

            "خدا حافظ! اپنا خیال رکھیے۔"

        ),



        # ======================================================

        # URDU GREETINGS

        # ======================================================

        "السلام علیکم": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "اسلام علیکم": (

            "وعلیکم السلام! جی فرمائیے، "

            "میں آپ کی کیا مدد کر سکتا ہوں؟"

        ),

        "سلام": (

            "وعلیکم السلام! جی فرمائیے۔"

        ),



        # ======================================================

        # URDU SMALL TALK

        # ======================================================

        "آپ کیسی ہیں": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "آپ کیسے ہیں": (

            "جی، میں ٹھیک ہوں، شکریہ! "

            "آپ سنائیے؟"

        ),

        "کیا حال ہے": (

            "جی، میں ٹھیک ہوں، شکریہ! آپ بتائیے؟"

        ),

        "شکریہ": (

            "آپ کا شکریہ! "

            "کیا میں آپ کی مزید مدد کر سکتا ہوں؟"

        ),

        "بہت شکریہ": (

            "آپ کا بہت شکریہ!"

        ),

        "اللہ حافظ": (

            "اللہ حافظ! اپنا خیال رکھیے۔"

        ),

    }



    return greetings.get(text)


def get_quick_reply_audio(text: str) -> bytes:

    """Generate and cache Cartesia WAV audio for short replies."""

    cache_key = (

        f"cartesia-sonic-3.6|{MODEL}|{VOICE}|{text}"

    )

    audio_id = hashlib.sha256(

        cache_key.encode("utf-8")

    ).hexdigest()

    QUICK_AUDIO_FOLDER.mkdir(

        parents=True,

        exist_ok=True,

    )

    audio_path = (

        QUICK_AUDIO_FOLDER

        / f"cartesia_{audio_id}.wav"

    )

    if audio_path.exists():

        cached = audio_path.read_bytes()

        if cached.startswith(b"RIFF") and cached[8:12] == b"WAVE":

            return cached

        audio_path.unlink()

    audio_buffer = generate_audio(text)

    audio_bytes = audio_buffer.getvalue()

    if not audio_bytes.startswith(b"RIFF") or audio_bytes[8:12] != b"WAVE":

        raise ValueError("Cartesia TTS did not return WAV audio")

    audio_path.write_bytes(

        audio_bytes

    )

    return audio_bytes

# ==========================================================

# 8. NAVIGATION AND CHAT HISTORY

# ==========================================================

def navigate(view: str):

    st.session_state.view = view

def format_chat_history(

    current_question: str = "",

) -> str:

    """

    Format recent messages for the LLM.

    """

    if st.session_state.view == "live":

        messages = (

            st.session_state.live_messages

        )

    else:

        messages = (

            st.session_state.text_messages

        )

    recent = list(

        messages[-6:]

    )

    # Avoid sending the current question twice.

    if recent and current_question:

        last_role, last_message = recent[-1]

        if (

            last_role == "customer"

            and message_to_text(last_message)

            == current_question

        ):

            recent = recent[:-1]

    if not recent:

        return "None"

    lines = []

    for role, message in recent:

        role_name = (

            "User"

            if role == "customer"

            else "Assistant"

        )

        lines.append(

            f"{role_name}: "

            f"{message_to_text(message)}"

        )

    return "\n".join(lines)

# ==========================================================

# 9. CONFIG VALIDATION

# ==========================================================

missing_keys = validate_config()

if missing_keys:

    st.error(

        "Missing keys in `.env`: "

        + ", ".join(missing_keys)

    )

    st.stop()

# ==========================================================

# 10. RAG SETUP

# ==========================================================

@st.cache_resource(show_spinner=False)
def warm_tts():
    """Cartesia Sonic-3.6 TTS warmup (server start par)."""
    warmup()
    return True


try:
    warm_tts()
except Exception:
    logging.exception("Cartesia TTS warmup failed")


@st.cache_resource(show_spinner=False)

def setup_rag():

    """

    Initialize the HBL document database

    only when it is needed.

    Greetings will not call this function.

    """

    store = get_vector_store()

    if is_index_empty(store):

        documents = load_pdf(

            config.pdf_path

        )

        chunks = split_documents(

            documents

        )

        index_documents(

            store,

            chunks,

        )

    return (
        get_retriever(store),
        get_llm(),
        get_prompt(),
    )


@st.cache_data(show_spinner=False)
def get_cached_thinking_fillers() -> list[dict]:
    """Empty list: component mein filler disabled hai (sirf jawab ki awaaz chalti hai)."""
    return []


def generate_rag_answer(

    question: str,

) -> str:

    """

    Answer banking questions using HBL documents.

    """

    retriever, llm, prompt = setup_rag()

    documents = retriever.invoke(

        question

    )

    if not documents:

        return (

            "I could not find this information "

            "in the provided HBL documents."

        )

    chat_history = format_chat_history(

        question

    )

    answer_parts = []

    try:

        stream = generate_answer_stream(

            llm,

            prompt,

            question,

            documents,

            chat_history=chat_history,

        )

        for piece in stream:

            content = (

                piece.content

                if hasattr(piece, "content")

                else piece

            )

            if content is not None:

                answer_parts.append(

                    message_to_text(content)

                )

    except Exception:

        logging.exception(

            "HBL answer generation failed."

        )

        return (

            "Sorry, I could not prepare "

            "an answer right now. "

            "Please try again."

        )

    answer = "".join(

        answer_parts

    ).strip()

    final_ans = answer or "I could not find the answer in the provided HBL documents."
    return enforce_masculine_grammar(final_ans)


def generate_rag_answer_stream(question: str):
    """Yield answer chunks in real-time as they stream from LLM."""
    retriever, llm, prompt = setup_rag()
    documents = retriever.invoke(question)
    if not documents:
        yield "I could not find this information in the provided HBL documents."
        return
    chat_history = format_chat_history(question)
    for piece in generate_answer_stream(
        llm,
        prompt,
        question,
        documents,
        chat_history=chat_history,
    ):
        content = piece.content if hasattr(piece, "content") else piece
        if content is not None:
            yield message_to_text(content)


def generate_rag_answer_and_audio(question: str) -> tuple[str, bytes]:
    """Sentence-Level Streaming Pipeline: Concurrently generates TTS as sentences finish."""
    retriever, llm, prompt = setup_rag()
    documents = retriever.invoke(question)

    if not documents:
        ans = "I could not find this information in the provided HBL documents."
        return ans, generate_audio(ans).getvalue()

    chat_history = format_chat_history(question)

    try:
        from concurrent.futures import ThreadPoolExecutor
        
        executor = ThreadPoolExecutor(max_workers=1)
        sentence_futures = []
        collected_sentences = []
        current_buf = ""
        delimiters = re.compile(r'([.?!۔؟\n]+)')

        stream = generate_answer_stream(
            llm,
            prompt,
            question,
            documents,
            chat_history=chat_history,
        )

        for piece in stream:
            content = piece.content if hasattr(piece, "content") else piece
            if content is None:
                continue
            token_str = message_to_text(content)
            current_buf += token_str

            parts = delimiters.split(current_buf)
            if len(parts) > 1:
                sent = enforce_masculine_grammar((parts[0] + parts[1]).strip())
                if len(sent) > 12:
                    collected_sentences.append(sent)
                    sentence_futures.append(executor.submit(generate_audio, sent))
                    current_buf = "".join(parts[2:])

        remainder = enforce_masculine_grammar(current_buf.strip())
        if remainder:
            collected_sentences.append(remainder)
            sentence_futures.append(executor.submit(generate_audio, remainder))

        full_answer = enforce_masculine_grammar(" ".join(collected_sentences).strip())
        if not full_answer:
            full_answer = "Sorry, I could not prepare an answer right now. Please try again."
            return full_answer, generate_audio(full_answer).getvalue()

        audio_wav_chunks = []
        for fut in sentence_futures:
            try:
                buf = fut.result()
                val = buf.getvalue()
                if val:
                    audio_wav_chunks.append(val)
            except Exception as e:
                logging.warning("Sentence audio generation error: %s", e)

        executor.shutdown(wait=False)

        if audio_wav_chunks:
            combined_wav = concat_wavs(audio_wav_chunks)
            return full_answer, combined_wav
        else:
            return full_answer, generate_audio(full_answer).getvalue()

    except Exception:
        logging.exception("Streaming RAG and audio failed; using fallback.")
        fallback_ans = generate_rag_answer(question)
        return fallback_ans, generate_audio(fallback_ans).getvalue()


def answer_question(

    question: str,

) -> tuple[str, bool]:

    """

    Returns:

        answer

        is_greeting

    Greetings bypass retrieval and the LLM.

    """

    direct_answer = (

        get_greeting_response(question)

    )

    if direct_answer is not None:

        return direct_answer, True

    return generate_rag_answer(question), False

# ==========================================================

# 12. PROCESS ONE VOICE QUESTION (STREAMING PIPELINE)

# ==========================================================

def process_voice_question(

    audio_bytes: bytes,

):

    """Audio -> STT -> Parallel Sentence-level RAG Streaming -> Combined TTS Audio"""

    fingerprint = hashlib.sha256(

        audio_bytes

    ).hexdigest()

    # Ignore duplicate recordings.

    if (

        fingerprint

        == st.session_state.live_last_hash

    ):

        return

    st.session_state.live_last_hash = fingerprint

    st.session_state.live_error = None

    # Ignore empty or extremely short recordings.

    if len(audio_bytes) < 3500:

        st.session_state.live_error = (

            "Recording was too short. "

            "Please try speaking again."

        )

        st.session_state.live_audio = None

        st.session_state.live_audio_id += 1

        return

    # --------------------------------------

    # 1. SPEECH TO TEXT

    # --------------------------------------

    try:

        question = transcribe_audio(

            audio_bytes,

            language=None,

        )

    except Exception as err:

        logging.exception(

            "Speech recognition failed: %s", err

        )

        err_str = str(err)

        if "api key" in err_str.lower() or "401" in err_str or "unauthorized" in err_str.lower():

            st.session_state.live_error = (

                "OpenAI API key missing/invalid. Add valid OPENAI_API_KEY in .env"

            )

        else:

            st.session_state.live_error = (

                f"Speech recognition error: {err_str[:60]}"

            )

        st.session_state.live_audio = None

        st.session_state.live_audio_id += 1

        return

    question = message_to_text(question).strip()

    if not question:

        st.session_state.live_error = (

            "I could not recognize your question. "

            "Please try again."

        )

        st.session_state.live_audio = None

        st.session_state.live_audio_id += 1

        return

    add_message(

        "customer",

        question,

    )

    # --------------------------------------

    # 2. GREETING OR BANKING QUESTION (STREAMING PIPELINE)

    # --------------------------------------

    try:

        direct_answer = get_greeting_response(question)

        if direct_answer is not None:

            answer = direct_answer

            audio_bytes = get_quick_reply_audio(answer)

        else:

            answer, audio_bytes = generate_rag_answer_and_audio(question)

    except Exception:

        logging.exception(

            "Question processing failed."

        )

        answer = (

            "Sorry, I could not process "

            "your question right now. "

            "Please try again."

        )

        try:

            audio_bytes = generate_audio(answer).getvalue()

        except Exception:

            audio_bytes = None

    answer = enforce_masculine_grammar(message_to_text(answer).strip())

    if not answer:

        answer = (

            "Sorry, I could not process "

            "your question right now. "

            "Please try again."

        )

        try:

            audio_bytes = generate_audio(answer).getvalue()

        except Exception:

            audio_bytes = None

    add_message(

        "agent",

        answer,

    )

    # --------------------------------------

    # 3. TEXT TO SPEECH PLAYBACK

    # --------------------------------------

    st.session_state.live_audio = audio_bytes

    st.session_state.live_error = None

    st.session_state.live_audio_id += 1

# ==========================================================

# 13. START AND END CALL

# ==========================================================

def start_live_call(

    call_id: str,

):

    """

    Start a new call and play the greeting.

    """

    st.session_state.live_active = True

    st.session_state.live_started = (

        time.monotonic()

    )

    st.session_state.live_call_id = call_id

    st.session_state.live_messages = []

    st.session_state.live_last_hash = None

    st.session_state.live_error = None

    st.session_state.live_audio = None

    greeting_text = (

        "السلام علیکم! ایچ بی ایل بینکنگ "

        "انفارمیشن اسسٹنٹ میں خوش آمدید۔ "

        "میں آپ کو بینکنگ سے متعلق معلومات "

        "فراہم کرنے کے لیے یہاں موجود ہوں۔ "

        "براہِ کرم بتائیے، آج میں آپ کی "

        "کس طرح مدد کر سکتا ہوں؟"

    )

    add_message(

        "agent",

        greeting_text,

    )

    try:

        st.session_state.live_audio = get_quick_reply_audio(greeting_text)

        if not st.session_state.live_audio:

            raise ValueError("Cartesia returned empty greeting audio")

    except Exception:

        logging.exception(

            "Greeting audio failed."

        )

        st.session_state.live_audio = None

        st.session_state.live_error = (

            "The call started, but greeting "

            "audio could not be played."

        )

    # Never reset to 1; reply IDs must

    # remain unique across calls.

    st.session_state.live_audio_id += 1

def end_live_call():

    """

    End the current call.

    """

    st.session_state.live_active = False

    st.session_state.live_started = None

    st.session_state.live_call_id = None

    st.session_state.live_audio = None

    st.session_state.live_error = None

    st.session_state.live_last_hash = None

# ==========================================================

# 14. SAFE LIVE TRANSCRIPT

# ==========================================================

def show_transcript():

    """

    Show the conversation without crashing

    if a message is a dictionary.

    """

    with st.container(

        key="live_transcript"

    ):

        st.markdown(

            '<div class="transcript-heading">'

            '<span>LIVE TRANSCRIPT</span>'

            '<span>URDU / ENGLISH</span>'

            '</div>',

            unsafe_allow_html=True,

        )

        if not st.session_state.live_messages:

            st.caption(

                "Your conversation will appear "

                "here when you start speaking."

            )

        for item in (

            st.session_state.live_messages

        ):

            # Support existing tuple messages.

            if (

                isinstance(item, (tuple, list))

                and len(item) >= 2

            ):

                role = item[0]

                message = item[1]

            # Support dictionary messages.

            elif isinstance(item, dict):

                role = item.get(

                    "role",

                    "agent",

                )

                message = item

            else:

                role = "agent"

                message = item

            label = (

                "AGENT"

                if role in ("agent", "assistant")

                else "CUSTOMER"

            )

            # Always convert message to text

            # before calling html.escape().

            safe_message = (

                html.escape(

                    message_to_text(message)

                )

                .replace("\n", "<br>")

            )

            if not safe_message:

                continue

            bubble_role = (

                "agent"

                if label == "AGENT"

                else "customer"

            )

            st.markdown(

                f'<div class="chat-bubble '

                f'{bubble_role}" dir="auto">'

                f'<small>{label}</small>'

                f'{safe_message}'

                '</div>',

                unsafe_allow_html=True,

            )

# ==========================================================

# 15. CUSTOM VOICE COMPONENT

# ==========================================================

COMPONENT_DIR = (

    PROJECT_ROOT / "voice_component"

)

COMPONENT_INDEX = (

    COMPONENT_DIR / "index.html"

)

voice_component = None

if COMPONENT_INDEX.is_file():

    voice_component = (

        components.declare_component(

            "hbl_reactive_voice",

            path=str(COMPONENT_DIR),

        )

    )

# ==========================================================

# 16. SIDEBAR

# ==========================================================

with st.sidebar:

    st.markdown(

        '<div class="logo">'

        '<b>HBL</b>'

        '<small>'

        'Habib Bank Limited<br>'

        'Banking Information Assistant'

        '</small>'

        '</div>',

        unsafe_allow_html=True,

    )

    for key, label, icon in NAV:

        st.button(

            label,

            key=f"nav_{key}",

            icon=icon,

            use_container_width=True,

            on_click=navigate,

            args=(key,),

        )

# ==========================================================

# 17. TOP BANNER

# ==========================================================

view = st.session_state.view

PAGE_INFO = {

    "live": (

        "📞",

        "HBL Live Voice",

        "A call-style banking information assistant.",

    ),

    "text": (

        "💬",

        "Text Chat",

        "Ask questions in Urdu or English.",

    ),

    "search": (

        "📄",

        "Document Search",

        "Search the HBL knowledge base.",

    ),

    "faq": (

        "❓",

        "FAQs",

        "Frequently asked questions.",

    ),

    "about": (

        "ℹ️",

        "About",

        "About the HBL Assistant.",

    ),

}

page_icon, page_title, page_subtitle = (

    PAGE_INFO[view]

)

st.markdown(

    '<div class="banner">'

    f'<div class="banner-icon">{page_icon}</div>'

    '<div>'

    f'<div class="banner-title">{page_title}</div>'

    f'<div class="banner-subtitle">'

    f'{page_subtitle}'

    '</div>'

    '</div>'

    '</div>',

    unsafe_allow_html=True,

)

# ==========================================================

# 18. LIVE CALL

# ==========================================================

if view == "live":

    with st.container(

        key="live_call"

    ):

        st.markdown(

            '<div class="live-eyebrow">'

            'HBL ASSISTANT · LIVE'

            '</div>'

            '<div class="live-title">'

            'Voice conversation'

            '</div>'

            '<div class="live-subtitle">'

            'Speak in Urdu or English. '

            'Simple greetings receive direct replies. '

            'Banking questions are answered using '

            'the HBL knowledge base.'

            '</div>',

            unsafe_allow_html=True,

        )

        if voice_component is None:

            st.error(

                "The custom microphone component "

                "was not found. Please check "

                "'voice_component/index.html'."

            )

        else:

            # Encode the latest response for

            # the existing browser component.

            reply_audio = ""

            if st.session_state.live_audio:

                reply_audio = (

                    base64.b64encode(

                        st.session_state.live_audio

                    ).decode("ascii")

                )

            browser_event = voice_component(

                reply_id=(

                    st.session_state.live_audio_id

                ),

                reply_audio=reply_audio,

                reply_mime="audio/wav",

                reply_error=(

                    st.session_state.live_error

                    or ""

                ),

                fillers=get_cached_thinking_fillers(),

                key="hbl_reactive_voice_component",

                default=None,

            )

            # ----------------------------------

            # HANDLE EVENTS

            # ----------------------------------

            if isinstance(browser_event, dict):

                event_type = browser_event.get(

                    "type"

                )

                call_id = str(

                    browser_event.get(

                        "call_id",

                        ""

                    )

                )

                event_id = (

                    browser_event.get("event_id")

                )

                if not event_id:

                    if event_type == "turn":

                        audio_value = str(

                            browser_event.get(

                                "wav_base64",

                                ""

                            )

                        )

                        audio_hash = hashlib.sha256(

                            audio_value.encode("utf-8")

                        ).hexdigest()

                        event_id = (

                            f"turn:{call_id}:{audio_hash}"

                        )

                    else:

                        event_id = (

                            f"{event_type}:{call_id}"

                        )

                event_id = str(event_id)

                # Ignore duplicate browser events.

                if (

                    event_id

                    != st.session_state.last_component_event

                ):

                    st.session_state.last_component_event = (

                        event_id

                    )

                    # --------------------------

                    # START CALL

                    # --------------------------

                    if event_type == "start":

                        start_live_call(

                            call_id

                        )

                        st.rerun()

                    # --------------------------

                    # END CALL

                    # --------------------------

                    elif (

                        event_type == "end"

                        and call_id

                        == st.session_state.live_call_id

                    ):

                        end_live_call()

                        st.rerun()

                    # --------------------------

                    # CUSTOMER VOICE TURN

                    # --------------------------

                    elif (

                        event_type == "turn"

                        and st.session_state.live_active

                        and call_id

                        == st.session_state.live_call_id

                    ):

                        try:

                            encoded = browser_event.get(

                                "wav_base64",

                                ""

                            )

                            if (

                                not isinstance(

                                    encoded,

                                    str,

                                )

                                or not encoded

                                or len(encoded) > 3_000_000

                            ):

                                raise ValueError(

                                    "Recording is missing "

                                    "or too large."

                                )

                            audio_bytes = (

                                base64.b64decode(

                                    encoded,

                                    validate=True,

                                )

                            )

                            process_voice_question(

                                audio_bytes

                            )

                        except Exception:

                            logging.exception(

                                "Voice turn failed."

                            )

                            st.session_state.live_audio = (

                                None

                            )

                            st.session_state.live_error = (

                                "The voice request failed. "

                                "Please try again."

                            )

                            st.session_state.live_audio_id += 1

                        st.rerun()

    # Keep transcript outside the microphone card.

    show_transcript()

    st.caption(

        "Your question is sent after a pause. "

        "Use headphones to reduce echo. "

        "Microphone access requires localhost "

        "or HTTPS."

    )

# ==========================================================

# 19. TEXT CHAT

# ==========================================================

elif view == "text":

    with st.container(

        key="other_card"

    ):

        question = st.text_input(

            "Ask your question:",

            placeholder=(

                "Hello, or ask an HBL banking question..."

            ),

            key="text_question",

        )

        if st.button(

            "Send Question",

            type="primary",

        ):

            question = question.strip()

            if not question:

                st.warning(

                    "Please enter a question."

                )

            else:

                st.session_state.text_messages.append(

                    ("customer", question)

                )

                direct_answer = (

                    get_greeting_response(

                        question

                    )

                )

                if direct_answer is not None:

                    # No database search.

                    answer = direct_answer

                else:
                    with st.chat_message("agent"):
                        answer = st.write_stream(
                            generate_rag_answer_stream(question)
                        )

                st.session_state.text_messages.append(

                    ("agent", answer)

                )

        for role, message in (

            st.session_state.text_messages

        ):

            text = message_to_text(

                message

            )

            if role == "customer":

                with st.chat_message("user"):

                    st.write(text)

            else:

                with st.chat_message("assistant"):

                    st.write(text)

# ==========================================================

# 20. DOCUMENT SEARCH

# ==========================================================

elif view == "search":

    with st.container(

        key="other_card"

    ):

        query = st.text_input(

            "Search HBL documents:",

            placeholder="Debit card charges",

        )

        if query.strip():

            try:

                retriever, _, _ = setup_rag()

                documents = retriever.invoke(

                    query

                )

                if not documents:

                    st.info(

                        "No relevant information "

                        "was found."

                    )

                for index, document in enumerate(

                    documents,

                    start=1,

                ):

                    with st.expander(

                        f"Result {index}"

                    ):

                        st.write(

                            document.page_content

                        )

            except Exception:

                logging.exception(

                    "Document search failed."

                )

                st.error(

                    "Document search is currently "

                    "unavailable."

                )

# ==========================================================

# 21. FAQs

# ==========================================================

elif view == "faq":

    with st.container(

        key="other_card"

    ):

        st.subheader(

            "Frequently Asked Questions"

        )

        for question in FAQS:

            faq_key = hashlib.md5(

                question.encode("utf-8")

            ).hexdigest()

            if st.button(

                question,

                key=f"faq_{faq_key}",

                use_container_width=True,

            ):

                with st.spinner(

                    "Searching HBL documents..."

                ):

                    answer = generate_rag_answer(

                        question

                    )

                st.write(

                    answer

                )

# ==========================================================

# 22. ABOUT

# ==========================================================

elif view == "about":

    with st.container(

        key="other_card"

    ):

        st.subheader(

            "About HBL Banking Information Assistant"

        )

        st.write(

            "This assistant uses "

            "Retrieval-Augmented Generation "

            "to answer banking questions "

            "from the provided HBL documents."

        )

        st.write(

            "Simple greetings are answered "

            "directly without searching the "

            "document database. Banking questions "

            "use HBL document retrieval, an LLM "

            "and text-to-speech."

        )

        st.info(

            "This is an educational demonstration. "

            "Confirm official banking information "

            "with HBL. This assistant does not "

            "access personal customer accounts "

            "or perform banking transactions."

        )
