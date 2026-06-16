@echo off
cd /d "%~dp0.."
set PAPER_CHAT_PROVIDER=deepseek
if "%PAPER_CHAT_MODEL%"=="" set PAPER_CHAT_MODEL=deepseek-v4-flash
if "%PAPER_CHAT_API_BASE_URL%"=="" set PAPER_CHAT_API_BASE_URL=https://api.deepseek.com
if "%DEEPSEEK_API_KEY%"=="" (
  echo DEEPSEEK_API_KEY is not set. Set it first:
  echo set DEEPSEEK_API_KEY=your_deepseek_api_key
  echo Search and PDF indexing will work, but note/chat will fail until the key is set.
)
python -m uvicorn ai_paper_chat.app:app --host 127.0.0.1 --port 8766
