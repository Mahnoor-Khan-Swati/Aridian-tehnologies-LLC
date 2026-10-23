"""
server.py
=========
FastAPI backend for the HBL Voice Assistant (call-style).

Low-latency design
------------------
  POST /api/turn  (audio WAV)  ->  NDJSON stream:
        {"type":"transcript", "text": ...}            # STT khatam hote hi
        {"type":"sentence", "text": ..., "audio": b64 WAV}   # har jumla bante hi
        {"type":"done", "answer": ..., "timings": {...}}
  - Greeting / small talk: LLM aur database ke baghair foran jawab.
  - Banking sawal: Upstash retrieve -> LLM stream -> har jumla Cartesia Sonic-3.6 se awaaz
    banta hai aur foran browser ko chala jata hai (poore jawab ka intezar nahi).
  - Cartesia Sonic-3.6 TTS, RAG, fillers, greeting audio startup par pehle se tayyar.

Run:  uvicorn server:app --port 8000   ->  http://localhost:8000
"""
import base64
import json
import logging
import os
import random
import re
import threading
import time
import webbrowser
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import config, validate_config
from src.document_loader import load_pdf
from src.llm_chain import (
    enforce_masculine_grammar,
    generate_answer,
    generate_answer_stream,
    get_llm,
    get_prompt,
)
from src.smalltalk import CALL_GREETING, GREETINGS, get_greeting_response
from src.stt import transcribe_audio
from src.text_splitter import split_documents
from src.tts import MODEL as TTS_MODEL, generate_audio, warmup
from src.vector_store import get_retriever, get_vector_store, index_documents, is_index_empty

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hbl-voice-server")

BASE_DIR = Path(__file__).resolve().parent
FILLER_FILE = BASE_DIR / "filler.json"
FILLER_CATS = ("searching_information", "tool_processing", "understanding_customer")

app = FastAPI(title="HBL Bank Assistant")

_retriever = None
_llm = None
_prompt = None
_rag_lock = threading.Lock()
_tts_pool = ThreadPoolExecutor(max_workers=3)      # Parallel synthesis for low-latency streaming
_filler_audio: dict[str, list[bytes]] = {}
_tts_ready = False


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _get_rag():
    """Retriever + LLM ek baar banao, phir reuse."""
    global _retriever, _llm, _prompt
    if _retriever is None:
        with _rag_lock:
            if _retriever is None:
                store = get_vector_store()
                if is_index_empty(store):
                    index_documents(store, split_documents(load_pdf(config.pdf_path)))
                _retriever = get_retriever(store)
                _llm, _prompt = get_llm(), get_prompt()
    return _retriever, _llm, _prompt


def _pages(docs):
    return [d.metadata.get("page") + 1 if isinstance(d.metadata.get("page"), int) else None for d in docs]


def _to_text(piece) -> str:
    content = piece.content if hasattr(piece, "content") else piece
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_to_text(c) for c in content)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content)


def _fmt_history(history: list[dict]) -> str:
    lines = []
    for m in history[-6:]:
        who = "User" if m.get("role") == "customer" else "Assistant"
        text = str(m.get("text", "")).strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines) if lines else "None"


def _ev(**kw) -> bytes:
    return (json.dumps(kw, ensure_ascii=False) + "\n").encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# Jumla toornay ke qaayede:
#   ۔ ؟ ? !  -> foran;   "." sirf jab uske baad space ho (2.5 ya Rs.500 na tootay);   newline
#   Pehla jumla jaldi shuru karne ke liye "،" ya "," par bhi toot sakta hai (>= 20 chars)
_END = re.compile(r"[۔؟?!]+|\.(?=\s)|\n")
_COMMA = re.compile(r"[،,](?=\s)")
_MIN_SENT = 12
_MIN_FIRST_COMMA = 20


def _pop_sentence(buf: str, first: bool):
    for m in _END.finditer(buf):
        end = m.end()
        if len(buf[:end].strip()) >= _MIN_SENT:
            return buf[:end].strip(), buf[end:]
    if first:
        for m in _COMMA.finditer(buf):
            end = m.end()
            if len(buf[:end].strip()) >= _MIN_FIRST_COMMA:
                return buf[:end].strip(), buf[end:]
    return None, buf


def _prepare_tts():
    """Background: Warmup greeting + 1 filler per category (instant start, no API spam)."""
    global _tts_ready
    try:
        t0 = time.time()
        warmup()
        generate_audio(CALL_GREETING)
        _tts_ready = True
        if FILLER_FILE.exists():
            fillers = json.loads(FILLER_FILE.read_text(encoding="utf-8"))["fillers"]
            for cat in FILLER_CATS:
                lines = fillers.get(cat, [])
                _filler_audio[cat] = []
                for line in lines[:3]:
                    try:
                        _filler_audio[cat].append(generate_audio(line).getvalue())
                    except Exception:
                        pass
        logger.info("TTS ready in %.1fs", time.time() - t0)
    except Exception:
        logger.exception("TTS warmup failed")


@app.on_event("startup")
def startup():
    missing = validate_config()
    if missing:
        logger.warning("Missing .env keys: %s", ", ".join(missing))
    threading.Thread(target=_prepare_tts, daemon=True).start()
    threading.Thread(target=_get_rag, daemon=True).start()

    def _open_browser():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8000")
    threading.Thread(target=_open_browser, daemon=True).start()


# ----------------------------------------------------------------------------
# models
# ----------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str


class TTSRequest(BaseModel):
    text: str


class SearchRequest(BaseModel):
    query: str


# ----------------------------------------------------------------------------
# CALL: one request = STT -> (small talk | RAG stream) -> TTS stream
# ----------------------------------------------------------------------------
def _turn_stream(data: bytes, filename: str, content_type: str, history: list[dict], language: Optional[str]):
    t0 = time.time()
    timings: dict[str, float] = {}

    # 1) Speech -> text
    try:
        text = transcribe_audio(data, filename=filename, content_type=content_type, language=language)
    except Exception as e:
        logger.exception("STT failed")
        yield _ev(type="error", message=f"Speech-to-text failed: {e}")
        return
    text = (text or "").strip()
    timings["stt"] = round(time.time() - t0, 2)
    if len(text) < 2:
        yield _ev(type="empty")
        return
    yield _ev(type="transcript", text=text)

    # 2) Greeting / small talk -> foran (no LLM, no DB)
    direct = get_greeting_response(text)
    if direct is not None:
        try:
            wav = generate_audio(direct).getvalue()
            timings["first_audio"] = round(time.time() - t0, 2)
            yield _ev(type="sentence", text=direct, audio=_b64(wav))
        except Exception as e:
            logger.exception("TTS failed")
            yield _ev(type="error", message=f"Text-to-speech failed: {e}")
            return
        yield _ev(type="done", answer=direct, timings=timings)
        return

    # 3) Banking question -> RAG
    yield _ev(type="searching")
    try:
        retriever, llm, prompt = _get_rag()
        t1 = time.time()
        docs = retriever.invoke(text)
        timings["retrieve"] = round(time.time() - t1, 2)
        if not docs:
            msg = "معذرت، مجھے یہ معلومات ایچ بی ایل کے دستاویزات میں نہیں ملیں۔"
            yield _ev(type="sentence", text=msg, audio=_b64(generate_audio(msg).getvalue()))
            yield _ev(type="done", answer=msg, timings=timings)
            return

        stream = generate_answer_stream(llm, prompt, text, docs, chat_history=_fmt_history(history))

        pending: deque = deque()        # (text, future) - tartib barqarar rakhta hai
        full_parts: list[str] = []
        buf = ""
        first = True
        got_token = False
        first_audio_logged = False

        def ready_events(block: bool):
            nonlocal first_audio_logged
            while pending and (block or pending[0][1].done()):
                sent_text, fut = pending.popleft()
                try:
                    wav = fut.result()
                except Exception:
                    logger.exception("TTS failed for a sentence")
                    continue
                if not first_audio_logged:
                    timings["first_audio"] = round(time.time() - t0, 2)
                    first_audio_logged = True
                yield _ev(type="sentence", text=sent_text, audio=_b64(wav))

        def submit(sentence: str):
            sentence = enforce_masculine_grammar(sentence).strip()
            if not sentence:
                return
            full_parts.append(sentence)
            pending.append((sentence, _tts_pool.submit(lambda s=sentence: generate_audio(s).getvalue())))

        t2 = time.time()
        for piece in stream:
            tok = _to_text(piece)
            if not tok:
                continue
            if not got_token:
                timings["llm_first_token"] = round(time.time() - t2, 2)
                got_token = True
            buf += tok
            while True:
                sent, buf = _pop_sentence(buf, first)
                if sent is None:
                    break
                submit(sent)
                first = False
            yield from ready_events(block=False)

        if buf.strip():
            submit(buf)
        yield from ready_events(block=True)

        answer = " ".join(full_parts).strip()
        if not answer:
            answer = "معذرت، مجھے اس وقت جواب نہیں مل سکا۔ براہِ کرم دوبارہ کوشش کریں۔"
            yield _ev(type="sentence", text=answer, audio=_b64(generate_audio(answer).getvalue()))
        timings["total"] = round(time.time() - t0, 2)
        logger.info("TURN timings: %s", timings)
        yield _ev(type="done", answer=answer, timings=timings)

    except Exception as e:
        logger.exception("Turn failed")
        yield _ev(type="error", message=f"Could not generate an answer: {e}")


@app.post("/api/turn")
def turn(
    audio: UploadFile = File(...),
    history: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    data = audio.file.read()
    if len(data) < 800:
        raise HTTPException(400, "Recording is too short.")
    if len(data) > 24 * 1024 * 1024:
        raise HTTPException(413, "Recording is too large (max ~24 MB).")
    if not config.openai_api_key:
        raise HTTPException(500, "OPENAI_API_KEY is not set in .env")
    if os.getenv("DEBUG_SAVE_AUDIO") == "1":          # diagnose: aakhri recording suniye
        Path("debug_audio").mkdir(exist_ok=True)
        Path("debug_audio/last_turn.wav").write_bytes(data)
    language = (language or "").strip() or None
    try:
        hist = json.loads(history) if history else []
        if not isinstance(hist, list):
            hist = []
    except Exception:
        hist = []

    gen = _turn_stream(
        data,
        audio.filename or "speech.wav",
        audio.content_type or "audio/wav",
        hist,
        language,
    )
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/greeting")
def greeting():
    """Call shuru hote hi bolne wala greeting (cache se instant)."""
    wav = generate_audio(CALL_GREETING).getvalue()
    return {"text": CALL_GREETING, "audio": _b64(wav)}


@app.get("/api/filler")
def filler(cat: str = "searching_information"):
    raise HTTPException(404, "Filler disabled")


# ----------------------------------------------------------------------------
# Text chat / search / tts (baqi pages)
# ----------------------------------------------------------------------------
@app.post("/api/stt")
def stt(audio: UploadFile = File(...), language: Optional[str] = Form(None)):
    data = audio.file.read()
    if len(data) < 800:
        raise HTTPException(400, "Recording is too short.")
    try:
        text = transcribe_audio(
            data,
            filename=audio.filename or "speech.wav",
            content_type=audio.content_type or "audio/wav",
            language=language,
        )
    except Exception as e:
        logger.exception("STT failed")
        raise HTTPException(502, f"Speech-to-text failed: {e}")
    if not text:
        raise HTTPException(422, "I could not hear any speech. Please try again.")
    return {"text": text}


@app.post("/api/chat")
def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is required")
    direct = get_greeting_response(question)
    if direct is not None:
        return {"answer": direct, "pages": []}
    try:
        retriever, llm, prompt = _get_rag()
        docs = retriever.invoke(question)
        answer = generate_answer(llm, prompt, question, docs)
    except Exception as e:
        logger.exception("Chat failed")
        raise HTTPException(502, f"Could not generate an answer: {e}")
    return {"answer": enforce_masculine_grammar(answer), "pages": _pages(docs)}


@app.post("/api/tts")
def tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "text is required")
    t0 = time.time()
    try:
        wav = generate_audio(req.text)
    except Exception as e:
        logger.exception("TTS failed")
        raise HTTPException(502, f"Text-to-speech failed: {e}")
    logger.info("TTS %.2fs for %d chars", time.time() - t0, len(req.text))
    return Response(content=wav.getvalue(), media_type="audio/wav")


@app.post("/api/search")
def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(400, "query is required")
    try:
        retriever, _, _ = _get_rag()
        docs = retriever.invoke(req.query)
    except Exception as e:
        raise HTTPException(502, f"Search failed: {e}")
    return JSONResponse({"results": [{"page": p, "text": d.page_content} for d, p in zip(docs, _pages(docs))]})


@app.get("/api/health")
def health():
    return {"status": "ok", "stt": config.stt_model, "tts": TTS_MODEL, "tts_ready": _tts_ready}


app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000)

