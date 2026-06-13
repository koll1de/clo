@echo off
REM Start Clipmaker.ai and open it in the browser.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

REM Make sure the Ollama server (local LLM) is running.
curl -s http://127.0.0.1:11434 >nul 2>&1
if errorlevel 1 (
    echo Starting Ollama...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    timeout /t 3 >nul
)

echo Starting Clipmaker.ai at http://localhost:8000 ...
start "" http://localhost:8000
call .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
