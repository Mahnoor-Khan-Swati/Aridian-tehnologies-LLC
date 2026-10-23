# HBL AI Assistant - Voice (STT -> RAG -> TTS)

| Step | Model / Service |
|------|-----------------|
| Speech-to-Text | OpenAI `gpt-4o-mini-transcribe-2025-12-15` |
| Question answering | Your existing RAG (Upstash Vector + OpenAI `gpt-4o-mini`) |
| Text-to-Speech | Google Gemini `gemini-3.1-flash-tts-preview` |

## Flow
1. Click the microphone, speak in Urdu or English, click again to stop.
2. `POST /api/stt` -> transcript appears (editable).
3. Click **Send to HBL Assistant** -> `POST /api/chat` (Upstash search + LLM answer).
4. `POST /api/tts` -> Gemini reads the answer aloud (auto-play, or press **Play answer**).

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env   -> then add your keys
uvicorn server:app --reload --port 8000
```
Open **http://localhost:8000** (the microphone works on `localhost` or HTTPS only).

## Keys in `.env`
`OPENAI_API_KEY`, `GEMINI_API_KEY` (https://aistudio.google.com/app/apikey), `UPSTASH_VECTOR_REST_URL`, `UPSTASH_VECTOR_REST_TOKEN`.
Models can be changed with `STT_MODEL`, `GEMINI_TTS_MODEL`, `GEMINI_TTS_VOICE` (default `Kore`).

## Structure
```
server.py            FastAPI: /api/stt, /api/chat, /api/tts, /api/search, /api/health
app.py               Original Streamlit text app (now also speaks answers via Gemini)
src/stt.py           OpenAI transcription
src/tts.py           Gemini TTS -> WAV
src/llm_chain.py     RAG prompt + LLM        (unchanged)
src/vector_store.py  Upstash Vector          (unchanged)
static/              HBL-style web UI (index.html, style.css, app.js)
```
For official HBL information always confirm at www.hbl.com or an HBL branch.
