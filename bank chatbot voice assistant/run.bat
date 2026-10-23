@echo off
echo Starting HBL Voice Assistant (FastAPI + Web UI)...
start http://127.0.0.1:8000
if exist .\venv312\Scripts\python.exe (
    .\venv312\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
) else (
    python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
)
pause

