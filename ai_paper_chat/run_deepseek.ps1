$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$env:PAPER_CHAT_PROVIDER = "deepseek"
if (-not $env:PAPER_CHAT_MODEL) {
  $env:PAPER_CHAT_MODEL = "deepseek-v4-flash"
}
if (-not $env:PAPER_CHAT_API_BASE_URL) {
  $env:PAPER_CHAT_API_BASE_URL = "https://api.deepseek.com"
}

if (-not $env:DEEPSEEK_API_KEY) {
  Write-Host "DEEPSEEK_API_KEY is not set. Set it first:"
  Write-Host '$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"'
  Write-Host "Search and PDF indexing will work, but note/chat will fail until the key is set."
}

python -m uvicorn ai_paper_chat.app:app --host 127.0.0.1 --port 8766
