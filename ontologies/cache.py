"""
Ontology cache with atomic update support.
Uses blue-green pattern: write to temp file, then atomic swap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Any, AsyncIterator

from .config import CACHE_FILE

# Create named logger for better integration with FastAPI
# Use uvicorn's logger to ensure logs appear in FastAPI output
logger = logging.getLogger("uvicorn.ontologies.cache")
logger.setLevel(logging.INFO)

CACHE_FILE_NEW = CACHE_FILE.with_suffix('.new.json')
ONTOLOGIES_DICT_PKL_FILE = CACHE_FILE.with_name("ontologies_dict.pkl")
_lock = asyncio.Lock()


def build_ontologies_dict(
    json_path: str | Path = CACHE_FILE,
    pkl_path: str | Path | None = ONTOLOGIES_DICT_PKL_FILE,
) -> dict[str, dict]:
    """Build dictionary keyed by ontology ID and optionally persist it as pickle."""
    json_path = Path(json_path)

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    ontologies_list = data.get("ontologies", []) if isinstance(data, dict) else []
    ontologies_dict = {
        ontology["id"]: ontology
        for ontology in ontologies_list
        if isinstance(ontology, dict) and "id" in ontology
    }

    if pkl_path is not None:
        pkl_path = Path(pkl_path)
        pkl_path.parent.mkdir(parents=True, exist_ok=True)
        with pkl_path.open("wb") as f:
            pickle.dump(ontologies_dict, f)
        logger.info(f"Updated ontology dictionary pickle: {pkl_path}")

    return ontologies_dict


def _ensure_file() -> None:
    if not CACHE_FILE.exists():
        CACHE_FILE.write_text(json.dumps({"ontologies": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        build_ontologies_dict()
    elif not ONTOLOGIES_DICT_PKL_FILE.exists():
        build_ontologies_dict()


def _unwrap(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict) and "ontologies" in data and isinstance(data["ontologies"], list):
        return data["ontologies"]
    if isinstance(data, list):
        # backward-compat (legacy unwrapped array)
        return data
    return []


def _wrap(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"ontologies": items}


async def load() -> List[Dict[str, Any]]:
    """Load ontologies from cache file."""
    _ensure_file()
    with CACHE_FILE.open(encoding="utf-8") as fp:
        raw = json.load(fp)
    items = _unwrap(raw)
    return items


async def load_as_dict() -> Dict[str, Dict[str, Any]]:
    """Load ontologies as dictionary keyed by lowercase ID."""
    _ensure_file()
    with CACHE_FILE.open(encoding="utf-8") as fp:
        raw = json.load(fp)
    items = _unwrap(raw)
    dct: Dict[str, Dict[str, Any]] = {}
    seen = set()
    for o in items:
        if not isinstance(o, dict) or "id" not in o:
            continue
        oid = o["id"]
        if isinstance(oid, str) and oid.startswith("{'id':"):
            continue
        key = str(oid).lower()
        if key not in seen:
            seen.add(key)
            dct[key] = o
    return dct


async def is_empty() -> bool:
    """Check if cache is empty."""
    _ensure_file()
    with CACHE_FILE.open(encoding="utf-8") as fp:
        raw = json.load(fp)
    return len(_unwrap(raw)) == 0


async def atomic_update(new_ontologies: List[Dict[str, Any]]) -> None:
    """Atomically update cache: write to temp file, then atomic swap."""
    async with _lock:
        cleaned = _deduplicate_and_clean(new_ontologies)
        
        try:
            with CACHE_FILE_NEW.open("w", encoding="utf-8") as fp:
                json.dump(_wrap(cleaned), fp, ensure_ascii=False, indent=2)
            
            CACHE_FILE_NEW.replace(CACHE_FILE)
            build_ontologies_dict()
            
        except Exception as e:
            logger.error(f"Cache update failed: {e}")
            if CACHE_FILE_NEW.exists():
                CACHE_FILE_NEW.unlink()
            raise


def _deduplicate_and_clean(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for o in items:
        if not isinstance(o, dict) or "id" not in o:
            continue
        oid = o["id"]
        if isinstance(oid, str) and oid.startswith("{'id':"):
            continue
        key = str(oid).lower()
        if key not in seen:
            seen.add(key)
            o.setdefault("properties", [])
            o.setdefault("terms", [])
            result.append(o)
    return result


@asynccontextmanager
async def locked_cache() -> AsyncIterator[Dict[str, Dict[str, Any]]]:
    """Legacy context manager for cache access."""
    await _lock.acquire()
    try:
        if not CACHE_FILE.exists():
            CACHE_FILE.write_text(json.dumps({"ontologies": []}, ensure_ascii=False, indent=2), encoding="utf-8")
            build_ontologies_dict()
        with CACHE_FILE.open(encoding="utf-8") as fp:
            raw = json.load(fp)
        items = _unwrap(raw)

        dct: Dict[str, Dict[str, Any]] = {}
        seen = set()
        for o in items:
            if not isinstance(o, dict) or "id" not in o:
                continue
            oid = o["id"]
            if isinstance(oid, str) and oid.startswith("{'id':"):
                continue
            key = str(oid).lower()
            if key not in seen:
                seen.add(key)
                o.setdefault("properties", [])
                o.setdefault("terms", [])
                dct[key] = o

        original_snapshot = list(dct.values())

        yield dct

        new_snapshot = list(dct.values())
        if new_snapshot != original_snapshot:
            with CACHE_FILE.open("w", encoding="utf-8") as fp:
                json.dump(_wrap(new_snapshot), fp, ensure_ascii=False, indent=2)
            build_ontologies_dict()
    finally:
        _lock.release()





