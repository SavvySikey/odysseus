import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DATA_DIR = Path(os.getenv("ODYSSEUS_DATA_DIR", "/app/data"))
UPLOAD_ROOT = DATA_DIR / "uploads"
MANIFEST = UPLOAD_ROOT / "uploads.json"
PINS_FILE = DATA_DIR / "library_pins.json"

TEXT_EXTS = {
    ".txt", ".md", ".json", ".jsonl", ".yaml", ".yml",
    ".csv", ".log", ".py", ".sh", ".conf", ".ini"
}

STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "please", "can", "you", "use", "using", "read", "find", "search",
    "library", "uploaded", "uploads", "upload", "json", "file", "files",
    "document", "documents", "docs", "what", "where", "when", "again"
}

_CHUNK_CACHE: Dict[str, Dict[str, Any]] = {}


def _tokens(text: str) -> List[str]:
    raw = re.findall(r"[A-Za-z0-9_\-.]+", (text or "").lower())
    return [t for t in raw if len(t) > 2 and t not in STOP]


def _load_json_file(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _save_json_file(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _iter_records(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        if "id" in obj and ("path" in obj or "name" in obj or "original_name" in obj):
            yield obj
        for value in obj.values():
            yield from _iter_records(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_records(item)


def load_upload_records() -> List[Dict[str, Any]]:
    manifest = _load_json_file(MANIFEST, {})
    return list(_iter_records(manifest))


def _is_text_upload(record: Dict[str, Any]) -> bool:
    name = str(record.get("name") or record.get("original_name") or record.get("id") or "")
    ext = Path(name).suffix.lower()
    mime = str(record.get("mime") or "").lower()

    if ext in TEXT_EXTS:
        return True

    if mime.startswith("text/") or mime in {
        "application/json",
        "application/octet-stream",
        "application/yaml",
        "application/x-yaml",
    }:
        return True

    return False


def _resolve_path(record: Dict[str, Any]) -> Optional[Path]:
    raw_path = str(record.get("path") or "")
    upload_id = str(record.get("id") or "")

    candidates: List[Path] = []

    if raw_path.startswith("/"):
        candidates.append(Path(raw_path))

    if upload_id:
        candidates.extend(UPLOAD_ROOT.rglob(upload_id))

    name = str(record.get("name") or record.get("original_name") or "")
    if name:
        candidates.extend(UPLOAD_ROOT.rglob(name))

    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return p
        except Exception:
            continue

    return None


def _record_label(record: Dict[str, Any]) -> str:
    return str(record.get("name") or record.get("original_name") or record.get("id") or "unknown")


def find_uploads(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    terms = _tokens(query)
    if not terms:
        terms = [query.lower().strip()] if query.strip() else []

    matches = []
    for record in load_upload_records():
        if not _is_text_upload(record):
            continue

        blob = " ".join(str(record.get(k, "")) for k in ("id", "name", "original_name", "mime")).lower()
        score = sum(1 for t in terms if t and t in blob)

        if query.lower().strip() in blob:
            score += 5

        if score > 0:
            matches.append((score, record))

    matches.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in matches[:limit]]


def get_pins(session_id: str) -> List[str]:
    data = _load_json_file(PINS_FILE, {})
    pins = data.get(str(session_id), [])
    return [p for p in pins if isinstance(p, str)]


def set_pins(session_id: str, pins: List[str]) -> None:
    data = _load_json_file(PINS_FILE, {})
    clean = []
    for p in pins:
        if p not in clean:
            clean.append(p)
    data[str(session_id)] = clean
    _save_json_file(PINS_FILE, data)


def pin_library(session_id: str, query: str) -> str:
    matches = find_uploads(query, limit=5)
    if not matches:
        return f"No matching library upload found for: {query}"

    record = matches[0]
    upload_id = str(record.get("id") or "")
    if not upload_id:
        return f"Matched {_record_label(record)}, but it has no upload id. Rude little file."

    pins = get_pins(session_id)
    if upload_id not in pins:
        pins.append(upload_id)
        set_pins(session_id, pins)

    return f"Pinned library file: {_record_label(record)}"


def unpin_library(session_id: str, query: str) -> str:
    pins = get_pins(session_id)

    if query.strip().lower() == "all":
        set_pins(session_id, [])
        return "Unpinned all library files for this chat."

    matches = find_uploads(query, limit=10)
    match_ids = {str(r.get("id") or "") for r in matches}

    new_pins = [p for p in pins if p not in match_ids]
    removed = len(pins) - len(new_pins)
    set_pins(session_id, new_pins)

    if removed:
        return f"Unpinned {removed} library file(s)."

    return f"No pinned library file matched: {query}"


def list_pins(session_id: str) -> str:
    pins = get_pins(session_id)
    records = {str(r.get("id") or ""): r for r in load_upload_records()}

    if not pins:
        return "No library files pinned for this chat."

    lines = ["Pinned library files for this chat:"]
    for upload_id in pins:
        record = records.get(upload_id)
        if record:
            lines.append(f"- {_record_label(record)} ({upload_id})")
        else:
            lines.append(f"- {upload_id} (missing from upload manifest)")

    return "\n".join(lines)


def maybe_handle_library_pin_command(session_id: str, message: str) -> Optional[str]:
    msg = (message or "").strip()

    m = re.match(r"^(?:pin|attach)\s+library\s+(.+)$", msg, re.I)
    if m:
        queries = [q.strip() for q in re.split(r"[,;\n]+", m.group(1)) if q.strip()]
        return "\n".join(pin_library(session_id, q) for q in queries)

    m = re.match(r"^unpin\s+library\s+(.+)$", msg, re.I)
    if m:
        queries = [q.strip() for q in re.split(r"[,;\n]+", m.group(1)) if q.strip()]
        return "\n".join(unpin_library(session_id, q) for q in queries)

    if re.match(r"^(?:list\s+library\s+pins|library\s+pins|pinned\s+library)$", msg, re.I):
        return list_pins(session_id)

    return None


def _read_text(path: Path, limit: int = 2_000_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _split_chunks(text: str, size: int = 1400, overlap: int = 250) -> List[str]:
    text = text.strip()
    if not text:
        return []

    chunks = []
    i = 0
    n = len(text)

    while i < n:
        j = min(i + size, n)
        chunks.append(text[i:j])
        if j >= n:
            break
        i = max(i + 1, j - overlap)

    return chunks


def _chunks_for_record(record: Dict[str, Any]) -> List[str]:
    upload_id = str(record.get("id") or "")
    path = _resolve_path(record)
    if not upload_id or not path:
        return []

    try:
        stat = path.stat()
        sig = f"{stat.st_size}:{int(stat.st_mtime)}"
    except Exception:
        return []

    cached = _CHUNK_CACHE.get(upload_id)
    if cached and cached.get("sig") == sig:
        return cached.get("chunks") or []

    text = _read_text(path)

    # Pretty-print JSON once into the cache, because raw minified JSON is misery in curly braces.
    if path.suffix.lower() in {".json", ".jsonl"}:
        try:
            obj = json.loads(text)
            text = json.dumps(obj, indent=2, ensure_ascii=False)
        except Exception:
            pass

    chunks = _split_chunks(text)
    _CHUNK_CACHE[upload_id] = {
        "sig": sig,
        "name": _record_label(record),
        "chunks": chunks,
        "cached_at": time.time(),
    }
    return chunks


def build_pinned_library_context(session_id: str, message: str, k: int = 8, max_chars: int = 14_000) -> str:
    pins = get_pins(session_id)
    if not pins:
        return ""

    terms = _tokens(message)
    if not terms:
        return ""

    records = {str(r.get("id") or ""): r for r in load_upload_records()}
    scored: List[Tuple[int, str, int, str]] = []

    for upload_id in pins:
        record = records.get(upload_id)
        if not record:
            continue

        name = _record_label(record)
        name_blob = name.lower()
        chunks = _chunks_for_record(record)

        for idx, chunk in enumerate(chunks):
            lower = chunk.lower()
            score = 0
            score += sum(8 for t in terms if t in name_blob)
            score += sum(min(lower.count(t), 6) for t in terms)

            if score > 0:
                scored.append((score, name, idx + 1, chunk))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)

    parts = [
        "[Pinned Library Context]",
        "The snippets below were automatically retrieved from library files pinned to this chat.",
        "Use them as source context. If the answer is not present here, say the pinned library did not contain enough retrieved context.",
        "",
    ]

    used = 0
    for score, name, idx, chunk in scored[:k]:
        block = f"[Library file: {name} :: chunk {idx} :: score {score}]\n{chunk.strip()}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)

    return "\n".join(parts).strip()
