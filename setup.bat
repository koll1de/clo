@echo off
REM One-time setup for Clipmaker.ai
setlocal
cd /d "%~dp0"

echo ============================================
echo  Clipmaker.ai setup
echo ============================================

echo.
echo [1/4] Creating Python virtual environment...
if not exist ".venv" (
    python -m venv .venv
)

echo.
echo [2/4] Upgrading pip...
call .venv\Scripts\python.exe -m pip install --upgrade pip

echo.
echo [3/4] Installing Python dependencies (this downloads GPU libraries, ~1-2 GB)...
call .venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo [4/4] Pulling the local LLM model via Ollama...
ollama pull qwen3:30b

echo.
echo Done. Run launch.bat to start the app.
pause
