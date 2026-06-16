# PaperChat

PaperChat is a local paper-reading workspace for Zotero. It opens Zotero papers in a browser, renders the PDF, generates structured reading notes, and lets you chat with an LLM using the paper text as context.

## Features

- Search Zotero papers by title or item key.
- Load papers from Zotero folders or direct PDF paths.
- Render PDFs in the web page with selectable text and zoom controls.
- Generate structured Markdown reading notes.
- Chat continuously with the current paper.
- Select text in the PDF or note and send it into the chat box.
- Look up final publication metadata for arXiv/preprint PDFs using arXiv, Semantic Scholar, Crossref, and OpenAlex.
- Configure OpenAI or DeepSeek API keys from the local UI.
- Open a selected Zotero item from the companion Zotero plugin.

## What Not To Commit

This project was developed inside a Zotero data directory. Do not publish the whole Zotero folder. The `.gitignore` is intentionally strict so Git only sees the app and plugin source files.

Never commit:

- `zotero.sqlite*`
- `storage/`
- `ai_reading/`
- `*.zip` attachment exports
- API keys or `settings.json`
- generated reading notes and chat history

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

Default provider:

```powershell
.\ai_paper_chat\run.ps1
```

DeepSeek:

```powershell
$env:DEEPSEEK_API_KEY="your_deepseek_api_key"
.\ai_paper_chat\run_deepseek.ps1
```

Open the app at:

```text
http://127.0.0.1:8766
```

## Zotero Plugin

The plugin source lives in `zotero_paper_chat_plugin/`.

To package it on Windows:

```powershell
Compress-Archive -Path zotero_paper_chat_plugin\* -DestinationPath paper-chat-zotero.zip -Force
Move-Item paper-chat-zotero.zip paper-chat-zotero.xpi -Force
```

Then install `paper-chat-zotero.xpi` from Zotero's plugin manager.

## Current Limitations

- PaperChat is designed as a local-first tool, not a hosted multi-user service.
- The Zotero plugin currently opens the local service at `http://127.0.0.1:8766`.
- Tag/review backend endpoints exist, but the current UI hides that workflow.
- PDF extraction quality depends on the PDF text layer. Scanned PDFs need OCR first.
- LLM answers depend on the configured model and context limit.
