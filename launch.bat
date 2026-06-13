@echo off
REM Start Clipmaker.ai and open it in the browser.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

REM Start the Ollama server only if it's actually installed. It's the local LLM, used
REM only when a provider in config.yaml is set to 'ollama'. With the Anthropic provider
REM it isn't needed, so a missing Ollama must NOT stop launch.
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
if not exist "%OLLAMA_EXE%" (
    echo Ollama not installed - skipping ^(using the Anthropic provider^).
) else (
    curl -s http://127.0.0.1:11434 >nul 2>&1
    if errorlevel 1 (
        echo Starting Ollama...
        start "" "%OLLAMA_EXE%"
        timeout /t 3 >nul
    )
)

echo Starting Clipmaker.ai at http://localhost:8000 ...
start "" http://localhost:8000
REM --reload: picks up code/UI changes automatically (no manual restart needed)
call .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
