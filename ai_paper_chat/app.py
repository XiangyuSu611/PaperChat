from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
ZOTERO_DIR = Path(os.environ.get("ZOTERO_DIR", ROOT)).resolve()
DATA_DIR = Path(os.environ.get("PAPER_CHAT_DATA", ROOT / "ai_reading" / "papers")).resolve()
SETTINGS_PATH = DATA_DIR.parent / "settings.json"
BASE_URL = os.environ.get("PAPER_CHAT_BASE_URL", "http://127.0.0.1:8766").rstrip("/")
PROVIDER = os.environ.get("PAPER_CHAT_PROVIDER", "openai").strip().lower()
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4.1-mini",
    "deepseek": "deepseek-v4-flash",
}
MODEL_OPTIONS_BY_PROVIDER = {
    "openai": [
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
        {"id": "gpt-4.1", "label": "GPT-4.1"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
    ],
    "deepseek": [
        {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
        {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
    ],
}
DEFAULT_API_BASE_BY_PROVIDER = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
}
DEFAULT_KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
DEFAULT_MODEL = os.environ.get(
    "PAPER_CHAT_MODEL", DEFAULT_MODEL_BY_PROVIDER.get(PROVIDER, "gpt-4.1-mini")
)
CHAT_API_BASE_URL = os.environ.get(
    "PAPER_CHAT_API_BASE_URL", DEFAULT_API_BASE_BY_PROVIDER.get(PROVIDER, DEFAULT_API_BASE_BY_PROVIDER["openai"])
).rstrip("/")
CHAT_API_KEY_ENV = os.environ.get(
    "PAPER_CHAT_API_KEY_ENV", DEFAULT_KEY_ENV_BY_PROVIDER.get(PROVIDER, "OPENAI_API_KEY")
)
BUNDLED_PYTHON = Path(
    os.environ.get(
        "CODEX_BUNDLED_PYTHON",
        r"C:\Users\xiangyu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    )
)

TITLE_FIELD = "title"
MAX_NOTE_CHARS = 52000
MAX_CHAT_CHARS = 28000
MAX_CHAT_FULL_TEXT_CHARS = int(os.environ.get("PAPER_CHAT_FULL_TEXT_CHARS", "1000000"))


app = FastAPI(title="Paper Chat")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SearchResponse(BaseModel):
    matches: list[dict[str, Any]]


class LoadRequest(BaseModel):
    key: Optional[str] = None
    query: Optional[str] = None
    pdf_path: Optional[str] = None


class NoteRequest(BaseModel):
    paper_id: str
    provider: Optional[str] = None
    model: Optional[str] = None


class ChatRequest(BaseModel):
    paper_id: str
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None


class PaperStateRequest(BaseModel):
    status: str = "unread"
    tags: list[str] = []
    archive_collection_key: Optional[str] = None
    archive_collection_path: Optional[str] = None


class LLMKeyRequest(BaseModel):
    provider: str
    api_key: str


def safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:80] or "paper"


def now_ts() -> int:
    return int(time.time())


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_settings() -> dict[str, Any]:
    settings = read_json(SETTINGS_PATH, {}) or {}
    settings.setdefault("llm_api_keys", {})
    return settings


def write_settings(settings: dict[str, Any]) -> None:
    write_json(SETTINGS_PATH, settings)


def configured_api_key(provider: str) -> str:
    settings = read_settings()
    saved = (settings.get("llm_api_keys") or {}).get(provider)
    if saved:
        return str(saved)
    env_name = DEFAULT_KEY_ENV_BY_PROVIDER.get(provider, CHAT_API_KEY_ENV)
    return os.environ.get(env_name, "")


def save_configured_api_key(provider: str, api_key: str) -> None:
    selected = provider.strip().lower()
    if selected not in DEFAULT_KEY_ENV_BY_PROVIDER:
        raise HTTPException(400, f"Unsupported provider: {selected}")
    cleaned = api_key.strip()
    if not cleaned or set(cleaned) == {"*"}:
        raise HTTPException(400, "Enter a real API key before saving")
    settings = read_settings()
    settings.setdefault("llm_api_keys", {})
    settings["llm_api_keys"][selected] = cleaned
    write_settings(settings)


def entry_url(paper_id: str) -> str:
    return f"{BASE_URL}/?paper={safe_id(paper_id)}"


def write_url_shortcut(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")


def create_entry_files(pdir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    url = entry_url(metadata["paper_id"])
    metadata["entry_url"] = url

    local_shortcut = pdir / "Paper Chat.url"
    write_url_shortcut(local_shortcut, url)
    metadata["entry_shortcut_path"] = str(local_shortcut)

    pdf_path = Path(metadata.get("pdf_path", ""))
    if metadata.get("source") == "zotero" and pdf_path.exists():
        zotero_shortcut = pdf_path.parent / "Paper Chat.url"
        write_url_shortcut(zotero_shortcut, url)
        metadata["zotero_shortcut_path"] = str(zotero_shortcut)
    return metadata


def connect_zotero() -> tuple[sqlite3.Connection, Path | None]:
    db_path = ZOTERO_DIR / "zotero.sqlite"
    if not db_path.exists():
        raise HTTPException(404, f"zotero.sqlite not found at {db_path}")
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2)
        con.execute("select count(*) from items").fetchone()
        return con, None
    except sqlite3.Error:
        tmpdir = Path(tempfile.mkdtemp(prefix="paper_chat_zotero_"))
        base = tmpdir / "zotero.sqlite"
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if src.exists():
                shutil.copy2(src, Path(str(base) + suffix))
        con = sqlite3.connect(base)
        con.execute("select count(*) from items").fetchone()
        return con, tmpdir


def get_field_id(cur: sqlite3.Cursor, field_name: str) -> int | None:
    row = cur.execute(
        "select fieldID from fieldsCombined where fieldName = ? limit 1", (field_name,)
    ).fetchone()
    return row[0] if row else None


def item_value(cur: sqlite3.Cursor, item_id: int, field_id: int | None) -> str:
    if field_id is None:
        return ""
    row = cur.execute(
        """
        select v.value
        from itemData d
        join itemDataValues v on v.valueID = d.valueID
        where d.itemID = ? and d.fieldID = ?
        limit 1
        """,
        (item_id, field_id),
    ).fetchone()
    return row[0] if row else ""


def resolve_attachment_path(attachment_key: str, zotero_path: str | None) -> str | None:
    if not zotero_path:
        return None
    if zotero_path.startswith("storage:"):
        return str(ZOTERO_DIR / "storage" / attachment_key / zotero_path.split(":", 1)[1])
    return zotero_path


def attachments_for(cur: sqlite3.Cursor, item_id: int, title_fid: int | None) -> list[dict[str, Any]]:
    rows = cur.execute(
        """
        select ai.itemID, ai.key, a.contentType, a.path, a.linkMode
        from itemAttachments a
        join items ai on ai.itemID = a.itemID
        where a.parentItemID = ? or a.itemID = ?
        order by case when a.contentType = 'application/pdf' then 0 else 1 end, ai.key
        """,
        (item_id, item_id),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for aid, key, content_type, path, link_mode in rows:
        resolved = resolve_attachment_path(key, path)
        out.append(
            {
                "key": key,
                "title": item_value(cur, aid, title_fid),
                "content_type": content_type,
                "link_mode": link_mode,
                "path": path,
                "resolved_path": resolved,
                "exists": bool(resolved and Path(resolved).exists()),
            }
        )
    return out


def item_record(cur: sqlite3.Cursor, item_id: int, title_fid: int | None) -> dict[str, Any] | None:
    row = cur.execute(
        """
        select i.itemID, i.key, t.typeName, i.dateAdded, i.dateModified
        from items i
        join itemTypes t on t.itemTypeID = i.itemTypeID
        where i.itemID = ?
        """,
        (item_id,),
    ).fetchone()
    if not row:
        return None
    iid, key, item_type, date_added, date_modified = row
    if item_type == "attachment":
        parent = cur.execute(
            "select parentItemID from itemAttachments where itemID = ?", (iid,)
        ).fetchone()
        if parent and parent[0]:
            return item_record(cur, parent[0], title_fid)
    return {
        "item_id": iid,
        "key": key,
        "type": item_type,
        "title": item_value(cur, iid, title_fid),
        "date_added": date_added,
        "date_modified": date_modified,
        "attachments": attachments_for(cur, iid, title_fid),
    }


def zotero_search(query: str | None = None, key: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    con, tmpdir = connect_zotero()
    try:
        cur = con.cursor()
        title_fid = get_field_id(cur, TITLE_FIELD)
        if key:
            row = cur.execute("select itemID from items where key = ? limit 1", (key,)).fetchone()
            return [item_record(cur, row[0], title_fid)] if row else []
        if not query:
            return []
        rows = cur.execute(
            """
            select distinct i.itemID
            from items i
            join itemTypes t on t.itemTypeID = i.itemTypeID
            join itemData d on d.itemID = i.itemID and d.fieldID = ?
            join itemDataValues v on v.valueID = d.valueID
            where t.typeName not in ('attachment', 'note', 'annotation')
              and v.value like ?
            order by i.dateModified desc
            limit ?
            """,
            (title_fid, f"%{query}%", limit),
        ).fetchall()
        return [r for row in rows if (r := item_record(cur, row[0], title_fid))]
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def zotero_collections() -> list[dict[str, Any]]:
    con, tmpdir = connect_zotero()
    try:
        cur = con.cursor()
        rows = cur.execute(
            """
            select collectionID, collectionName, parentCollectionID, key
            from collections
            order by collectionName collate nocase
            """
        ).fetchall()
        by_id = {
            row[0]: {
                "collection_id": row[0],
                "name": row[1],
                "parent_id": row[2],
                "key": row[3],
            }
            for row in rows
        }

        def collection_path(collection_id: int) -> str:
            parts = []
            seen = set()
            current = by_id.get(collection_id)
            while current and current["collection_id"] not in seen:
                seen.add(current["collection_id"])
                parts.append(current["name"])
                current = by_id.get(current["parent_id"])
            return " / ".join(reversed(parts))

        collections = []
        for collection_id, collection in by_id.items():
            count = cur.execute(
                "select count(*) from collectionItems where collectionID = ?",
                (collection_id,),
            ).fetchone()[0]
            collections.append(
                {
                    "key": collection["key"],
                    "name": collection["name"],
                    "path": collection_path(collection_id),
                    "item_count": count,
                }
            )
        collections.sort(key=lambda item: item["path"].lower())
        return collections
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def zotero_collection_items(collection_key: str, limit: int = 200) -> dict[str, Any]:
    con, tmpdir = connect_zotero()
    try:
        cur = con.cursor()
        title_fid = get_field_id(cur, TITLE_FIELD)
        collection = cur.execute(
            """
            select collectionID, collectionName, key
            from collections
            where key = ?
            limit 1
            """,
            (collection_key,),
        ).fetchone()
        if not collection:
            raise HTTPException(404, "Zotero collection not found")
        collection_id, name, key = collection
        rows = cur.execute(
            """
            select ci.itemID
            from collectionItems ci
            join items i on i.itemID = ci.itemID
            left join itemTypes t on t.itemTypeID = i.itemTypeID
            where ci.collectionID = ?
              and coalesce(t.typeName, '') not in ('note', 'annotation')
            order by ci.orderIndex asc, i.dateModified desc
            limit ?
            """,
            (collection_id, limit),
        ).fetchall()
        items = []
        seen = set()
        for (item_id,) in rows:
            record = item_record(cur, item_id, title_fid)
            if record and record["key"] not in seen:
                seen.add(record["key"])
                items.append(record)
        return {"collection": {"key": key, "name": name}, "matches": items}
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def choose_pdf(record: dict[str, Any]) -> dict[str, Any] | None:
    for attachment in record.get("attachments", []):
        if attachment.get("content_type") == "application/pdf" and attachment.get("exists"):
            return attachment
    for attachment in record.get("attachments", []):
        if attachment.get("resolved_path", "").lower().endswith(".pdf") and attachment.get("exists"):
            return attachment
    return None


def extract_pdf_text(pdf_path: Path) -> str:
    script = APP_DIR / "extract_pdf_text.py"
    python = BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [str(python), str(script), str(pdf_path)],
        cwd=str(APP_DIR),
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr.strip() or "PDF text extraction failed")
    text = proc.stdout.strip()
    if len(text) < 100:
        raise HTTPException(422, "PDF text extraction produced too little text")
    return text


def chunk_text(text: str, size: int = 1800, overlap: int = 220) -> list[dict[str, Any]]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[dict[str, Any]] = []
    start = 0
    idx = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        cut = normalized.rfind("\n\n", start, end)
        if cut > start + size * 0.55:
            end = cut
        body = normalized[start:end].strip()
        if body:
            chunks.append({"id": idx, "start": start, "end": end, "text": body})
            idx += 1
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def write_chunks(path: Path, chunks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def read_chunks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_chat_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]", text.lower())


def retrieve(chunks: list[dict[str, Any]], query: str, top_k: int = 8) -> list[dict[str, Any]]:
    terms = tokenize(query)
    if not terms:
        return chunks[:top_k]
    term_counts: dict[str, int] = {}
    for term in terms:
        term_counts[term] = term_counts.get(term, 0) + 1
    scored = []
    for chunk in chunks:
        text = chunk["text"].lower()
        score = 0.0
        for term, count in term_counts.items():
            hits = text.count(term)
            if hits:
                score += (1 + math.log(hits + 1)) * count
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]] or chunks[:top_k]


def unique_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    unique = []
    for chunk in chunks:
        chunk_id = int(chunk["id"])
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        unique.append(chunk)
    return unique


def paper_dir(paper_id: str) -> Path:
    return DATA_DIR / safe_id(paper_id)


def load_paper_bundle(paper_id: str) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not loaded yet")
    chunks = read_chunks(pdir / "chunks.jsonl")
    if not chunks:
        raise HTTPException(404, "Paper chunks not found")
    return pdir, metadata, chunks


def default_paper_state() -> dict[str, Any]:
    return {
        "status": "unread",
        "tags": [],
        "archive_collection_key": "",
        "archive_collection_path": "",
        "updated_at": None,
    }


def read_paper_state(pdir: Path) -> dict[str, Any]:
    state = default_paper_state()
    state.update(read_json(pdir / "paper_state.json", {}) or {})
    return state


def write_paper_state(pdir: Path, req: PaperStateRequest) -> dict[str, Any]:
    tags = []
    seen = set()
    for tag in req.tags:
        cleaned = re.sub(r"\s+", " ", tag).strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            tags.append(cleaned)
    state = {
        "status": req.status.strip() or "unread",
        "tags": tags,
        "archive_collection_key": (req.archive_collection_key or "").strip(),
        "archive_collection_path": (req.archive_collection_path or "").strip(),
        "updated_at": now_ts(),
    }
    write_json(pdir / "paper_state.json", state)
    return state


def sync_zotero_tags(metadata: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    zotero_key = metadata.get("zotero_key")
    if not zotero_key:
        raise HTTPException(400, "This paper was not loaded from Zotero, so it has no Zotero item key")
    cleaned_tags = []
    seen = set()
    for tag in tags:
        cleaned = re.sub(r"\s+", " ", str(tag)).strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            cleaned_tags.append(cleaned)
    if not cleaned_tags:
        raise HTTPException(400, "No tags to sync")

    url = f"http://127.0.0.1:23119/api/users/0/items/{zotero_key}"
    try:
      get_req = urllib.request.Request(url, headers={"Zotero-API-Version": "3"})
      with urllib.request.urlopen(get_req, timeout=5) as resp:
          item = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            503,
            "Zotero local API is unavailable. Open Zotero and make sure the local API/Connector server is enabled.",
        ) from exc

    data = item.get("data", {})
    version = str(data.get("version") or item.get("version") or "")
    existing = data.get("tags") or []
    merged = []
    tag_names = set()
    for tag_obj in existing:
        name = str(tag_obj.get("tag", "")).strip()
        if name and name.lower() not in tag_names:
            tag_names.add(name.lower())
            merged.append(tag_obj)
    added = []
    for tag in cleaned_tags:
        if tag.lower() not in tag_names:
            tag_names.add(tag.lower())
            merged.append({"tag": tag, "type": 0})
            added.append(tag)

    if not added:
        return {"synced": True, "added": [], "message": "All tags already exist in Zotero"}

    patch_req = urllib.request.Request(
        url,
        data=json.dumps({"tags": merged}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Version": "3",
            **({"If-Unmodified-Since-Version": version} if version else {}),
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(patch_req, timeout=8) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(exc.code, detail or exc.reason)
    except Exception as exc:
        raise HTTPException(503, f"Failed to sync tags to Zotero: {exc}") from exc
    return {"synced": True, "added": added, "status": status}


def provider_config(provider: Optional[str] = None) -> dict[str, Any]:
    selected = (provider or PROVIDER or "openai").strip().lower()
    if selected not in DEFAULT_API_BASE_BY_PROVIDER:
        raise HTTPException(400, f"Unsupported provider: {selected}")
    key_env = (
        CHAT_API_KEY_ENV
        if selected == PROVIDER and os.environ.get("PAPER_CHAT_API_KEY_ENV")
        else DEFAULT_KEY_ENV_BY_PROVIDER[selected]
    )
    api_base = (
        CHAT_API_BASE_URL
        if selected == PROVIDER and os.environ.get("PAPER_CHAT_API_BASE_URL")
        else DEFAULT_API_BASE_BY_PROVIDER[selected]
    )
    model = DEFAULT_MODEL if selected == PROVIDER else DEFAULT_MODEL_BY_PROVIDER[selected]
    return {
        "id": selected,
        "api_base_url": api_base.rstrip("/"),
        "key_env": key_env,
        "default_model": model,
        "models": MODEL_OPTIONS_BY_PROVIDER[selected],
        "api_key_present": bool(configured_api_key(selected)),
    }


def provider_options() -> list[dict[str, Any]]:
    return [provider_config(provider) for provider in MODEL_OPTIONS_BY_PROVIDER]


def llm_chat(messages: list[dict[str, str]], provider: Optional[str] = None, model: Optional[str] = None) -> str:
    config = provider_config(provider)
    api_key = configured_api_key(config["id"])
    if not api_key:
        raise HTTPException(400, f"{config['key_env']} is not set in this terminal")
    payload = {"model": model or config["default_model"], "messages": messages, "temperature": 0.2}
    req = urllib.request.Request(
        f"{config['api_base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if "invalid_api_key" in detail:
            detail = f"Invalid {config['key_env']}. Set a valid key in this terminal and restart the app."
        else:
            detail = re.sub(r"sk-[^\"\\s]+", "sk-***", detail)
        raise HTTPException(exc.code, detail)
    except urllib.error.URLError as exc:
        raise HTTPException(502, str(exc))
    return data["choices"][0]["message"]["content"]


NOTE_SYSTEM_PROMPT = """你是一个严谨的论文阅读助手。请基于给定论文内容生成结构化阅读笔记。
目标是准确、容易理解、便于后续复习，不要为了填满模板而编造。
默认中文解释，关键技术术语可以保留英文。区分论文主张和你的推断。

输出规则：
1. 最上方必须给出 Take Away，用 2-4 个要点概括论文最核心的任务、方法洞察和实验结论。
2. 固定章节保留；数量可变的小节只输出论文中有明确证据的条目。
3. 所有编号必须连续，例如 2.2.1、2.2.2、2.2.3；禁止输出 2.2.X、2.3.X、3.X 或任何带 X 的占位编号。
4. 如果某个固定小节论文没有明确说明，保留标题并写“未明确说明”或“不适用”。
5. 每个 technical challenge 要说明：之前方法怎么做、失败在哪里、技术原因是什么。
6. 每个 contribution / module 要说明：具体做法、动机、优势或 insight。
7. 重要事实、方法描述、实验结论和 limitation 后面尽量给出原文页码引用，格式必须是 [p.N]，例如 [p.3]。
8. 页码引用必须来自论文内容中的 [Page N] 标记；不确定页码时不要编造。
9. 尽量使用短句和清楚的因果关系；不要写空泛评价。"""

NOTE_TEMPLATE = """# {title}

## Take Away

## Abstract
### 1.1 Task
### 1.2 Technical challenge for previous methods
### 1.3 Key insight / motivation for solving the challenge
### 1.4 Experiment

## Introduction
### 2.1 Task and application
### 2.2 Technical challenge for previous methods
#### 2.2.1 Technical challenge 1
#### 2.2.2 Technical challenge 2
### 2.3 Our pipeline for solving the challenge
#### 2.3.1 Key innovation / contribution
#### 2.3.2 Contribution 1
#### 2.3.3 Contribution 2

## Method
### 3.1 Overview
#### 3.1.1 Task, input, and output
#### 3.1.2 Method / first step / second step
#### 3.1.3 Technical advantage
### 3.2 Module 1
#### 3.2.1 Motivation
#### 3.2.2 Input
#### 3.2.3 Output
#### 3.2.4 Method
#### 3.2.5 Benefit
### 3.3 Module 2

## Experiments
### 4.1 Setting
### 4.2 Comparison experiments
### 4.3 Ablation studies

## Limitations
"""


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    selected = provider_config(PROVIDER)
    return {
        "zotero_dir": str(ZOTERO_DIR),
        "data_dir": str(DATA_DIR),
        "provider": selected["id"],
        "model": selected["default_model"],
        "base_url": BASE_URL,
        "chat_api_base_url": selected["api_base_url"],
        "api_key_env": selected["key_env"],
        "api_key_present": selected["api_key_present"],
        "providers": provider_options(),
    }


@app.post("/api/settings/llm-key")
def set_llm_key(req: LLMKeyRequest) -> dict[str, Any]:
    selected = req.provider.strip().lower()
    save_configured_api_key(selected, req.api_key)
    return {"provider": provider_config(selected)}


@app.get("/api/search", response_model=SearchResponse)
def search(q: str = "") -> dict[str, Any]:
    return {"matches": zotero_search(query=q, limit=20)}


@app.get("/api/collections")
def collections() -> dict[str, Any]:
    return {"collections": zotero_collections()}


@app.get("/api/collections/{collection_key}/items")
def collection_items(collection_key: str) -> dict[str, Any]:
    return zotero_collection_items(collection_key)


@app.post("/api/load")
def load_paper(req: LoadRequest) -> dict[str, Any]:
    ensure_data_dir()
    metadata: dict[str, Any]
    pdf_path: Path
    if req.pdf_path:
        pdf_path = Path(req.pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            raise HTTPException(404, f"PDF not found: {pdf_path}")
        paper_id = safe_id(pdf_path.stem)
        metadata = {
            "paper_id": paper_id,
            "title": pdf_path.stem,
            "source": "pdf_path",
            "pdf_path": str(pdf_path),
            "loaded_at": now_ts(),
        }
    else:
        matches = zotero_search(query=req.query, key=req.key, limit=5)
        if not matches:
            raise HTTPException(404, "No Zotero match found")
        record = matches[0]
        attachment = choose_pdf(record)
        if not attachment:
            raise HTTPException(404, "No existing PDF attachment found for this item")
        pdf_path = Path(attachment["resolved_path"]).resolve()
        paper_id = safe_id(record["key"])
        metadata = {
            "paper_id": paper_id,
            "title": record.get("title") or record["key"],
            "source": "zotero",
            "zotero_key": record["key"],
            "attachment_key": attachment["key"],
            "pdf_path": str(pdf_path),
            "loaded_at": now_ts(),
        }

    text = extract_pdf_text(pdf_path)
    chunks = chunk_text(text)
    pdir = paper_dir(metadata["paper_id"])
    pdir.mkdir(parents=True, exist_ok=True)
    metadata = create_entry_files(pdir, metadata)
    write_json(pdir / "metadata.json", metadata)
    (pdir / "paper_text.txt").write_text(text, encoding="utf-8")
    write_chunks(pdir / "chunks.jsonl", chunks)
    if not (pdir / "note.md").exists():
        (pdir / "note.md").write_text("", encoding="utf-8")
    return {"metadata": metadata, "chunk_count": len(chunks)}


@app.post("/api/paper/{paper_id}/entry")
def create_entry(paper_id: str) -> dict[str, Any]:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not found")
    metadata = create_entry_files(pdir, metadata)
    write_json(pdir / "metadata.json", metadata)
    return {"metadata": metadata}


@app.get("/api/paper/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not found")
    note = (pdir / "note.md").read_text(encoding="utf-8") if (pdir / "note.md").exists() else ""
    history_path = pdir / "chat_history.jsonl"
    history = read_chat_history(history_path)
    state = read_paper_state(pdir)
    return {"metadata": metadata, "note": note, "history": history, "state": state}


@app.post("/api/paper/{paper_id}/state")
def update_paper_state(paper_id: str, req: PaperStateRequest) -> dict[str, Any]:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not found")
    return {"state": write_paper_state(pdir, req)}


@app.post("/api/paper/{paper_id}/sync-zotero-tags")
def sync_paper_tags_to_zotero(paper_id: str) -> dict[str, Any]:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not found")
    state = read_paper_state(pdir)
    return sync_zotero_tags(metadata, state.get("tags", []))


@app.get("/api/paper/{paper_id}/pdf")
def get_paper_pdf(paper_id: str) -> FileResponse:
    pdir = paper_dir(paper_id)
    metadata = read_json(pdir / "metadata.json")
    if not metadata:
        raise HTTPException(404, "Paper not found")
    pdf_path = Path(metadata.get("pdf_path", "")).resolve()
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(404, "PDF not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )


@app.get("/api/paper/{paper_id}/preview.pdf")
def get_paper_pdf_preview(paper_id: str) -> FileResponse:
    return get_paper_pdf(paper_id)


@app.post("/api/note")
def generate_note(req: NoteRequest) -> dict[str, Any]:
    pdir, metadata, chunks = load_paper_bundle(req.paper_id)
    full_text = (pdir / "paper_text.txt").read_text(encoding="utf-8")
    clipped = full_text[:MAX_NOTE_CHARS]
    messages = [
        {"role": "system", "content": NOTE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请按照下面模板骨架生成论文阅读笔记。固定章节保留；"
                "technical challenge、contribution、module 等数量可变的小节按论文证据增减，编号必须连续，禁止使用 X 占位。\n\n"
                f"{NOTE_TEMPLATE.format(title=metadata.get('title', req.paper_id))}\n\n"
                "论文内容如下：\n\n"
                f"{clipped}"
            ),
        },
    ]
    note = llm_chat(messages, req.provider, req.model)
    (pdir / "note.md").write_text(note, encoding="utf-8")
    return {"note": note}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    pdir, metadata, chunks = load_paper_bundle(req.paper_id)
    history_path = pdir / "chat_history.jsonl"
    history = read_chat_history(history_path)
    recent_history = history[-6:]
    retrieval_query = "\n".join(
        [turn.get("question", "") for turn in recent_history[-3:]] + [req.message]
    )
    selected = unique_chunks(chunks[:2] + retrieve(chunks, retrieval_query, top_k=12))
    context = "\n\n".join(
        f"[chunk {chunk['id']}]\n{chunk['text']}" for chunk in selected
    )[:MAX_CHAT_CHARS]
    full_text_path = pdir / "paper_text.txt"
    full_text = full_text_path.read_text(encoding="utf-8") if full_text_path.exists() else ""
    paper_text_for_chat = full_text[:MAX_CHAT_FULL_TEXT_CHARS]
    paper_text_label = "论文原文全文" if len(paper_text_for_chat) == len(full_text) else "论文原文截断版"
    note_path = pdir / "note.md"
    note = note_path.read_text(encoding="utf-8")[:12000] if note_path.exists() else ""
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是论文对话助手。必须优先基于给定论文原文、相关原文片段和阅读笔记回答；"
                "如果证据不足，明确说证据不足。回答用中文，关键术语保留英文。"
                "对话是连续的：回答当前问题时要结合前面的用户问题和你的回答。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"论文标题：{metadata.get('title')}\n\n"
                f"{paper_text_label}：\n{paper_text_for_chat}\n\n"
                f"已生成笔记：\n{note}\n\n"
                f"当前轮次检索到的相关原文片段：\n{context}"
            ),
        },
    ]
    for turn in recent_history:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if question:
            messages.append({"role": "user", "content": question})
        if answer:
            messages.append({"role": "assistant", "content": answer[:5000]})
    messages.append({"role": "user", "content": req.message})
    answer = llm_chat(messages, req.provider, req.model)
    turn = {
        "time": now_ts(),
        "question": req.message,
        "answer": answer,
        "chunks": [chunk["id"] for chunk in selected],
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    return {"answer": answer, "chunks": selected}
