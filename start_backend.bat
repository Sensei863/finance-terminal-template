@echo off
cd /d "c:\Users\divit\Desktop\Finance Tool"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > backend_startup.log 2>&1
