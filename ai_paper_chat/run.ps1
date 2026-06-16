$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$provider = if ($env:PAPER_CHAT_PROVIDER) { $env:PAPER_CHAT_PROVIDER } else { "openai" }
$keyEnv = if ($provider -eq "deepseek") { "DEEPSEEK_API_KEY" } else { "OPENAI_API_KEY" }

if (-not [System.Environment]::GetEnvironmentVariable($keyEnv)) {
  Write-Host "$keyEnv is not set. Search and PDF indexing will work, but note/chat will fail until you set it."
}

python -m uvicorn ai_paper_chat.app:app --host 127.0.0.1 --port 8766
