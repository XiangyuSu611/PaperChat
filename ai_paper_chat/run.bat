@echo off
cd /d "%~dp0.."
if /I "%PAPER_CHAT_PROVIDER%"=="deepseek" (
  if "%DEEPSEEK_API_KEY%"=="" echo DEEPSEEK_API_KEY is not set. Search and PDF indexing will work, but note/chat will fail until you set it.
) else (
  if "%OPENAI_API_KEY%"=="" echo OPENAI_API_KEY is not set. Search and PDF indexing will work, but note/chat will fail until you set it.
)
python -m uvicorn ai_paper_chat.app:app --host 127.0.0.1 --port 8766
