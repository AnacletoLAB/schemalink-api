from __future__ import annotations

import asyncio
import json
from typing import Dict, Any, List, Optional
import logging

import httpx

from .config import OLS4_BASE, CUSTOM_ONTOLOGIES_FILE

# Create named logger for better integration with FastAPI
# Use uvicorn's logger to ensure logs appear in FastAPI output
logger = logging.getLogger("uvicorn.ontologies.service")
logger.setLevel(logging.INFO)


async def fetch_ontology_metadata_only() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{OLS4_BASE}?size=1000", headers={"accept": "application/json"})
    res.raise_for_status()
    payload = res.json()
    if "_embedded" not in payload or "ontologies" not in payload["_embedded"]:
        return []

    ontologies: List[Dict[str, Any]] = []
    for o in payload["_embedded"]["ontologies"]:
        config = o.get("config", {})
        ontology = {
            "id": o["ontologyId"],
            "name": config.get("title", o["ontologyId"]),
            "description": config.get("description", ""),
            "namespace": config.get("fileLocation", ""),
        }
        # Best-effort `annotator` synthesis following web/libs logic (normalize later on client)
        ontology["annotator"] = f"sqlite:obo:{ontology['id']}"
        ontologies.append(ontology)
    return ontologies


async def fetch_terms_for_ontology(
    ontology_id: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> List[str]:
    """Fetch up to `limit` class labels for the ontology, paginating OLS4.

    Notes:
    - We keep only the `label` field for each term to avoid including alternative IDs.
    - We exclude duplicates while preserving order.
    - Uses OLS4 v4 API: /ols4/api/ontologies/{id}/terms
    """
    base_url = f"{OLS4_BASE.replace('/ontologies', '')}/ontologies/{ontology_id}/terms"

    page = 0
    size = 200  # OLS supports page sizes up to a few hundreds; adjust as needed
    collected: List[str] = []
    seen = set()

    while len(collected) < limit:
        params = {"size": size, "page": page, "sort": "label,asc"}
        r = await client.get(base_url, params=params)
        if r.status_code != 200:
            break
        data = r.json()
        batch = [t.get("label", "") for t in data.get("_embedded", {}).get("terms", []) if t.get("label")]
        if not batch:
            break
        for label in batch:
            if label not in seen:
                seen.add(label)
                collected.append(label)
                if len(collected) >= limit:
                    break

        # pagination check
        page_info: Optional[Dict[str, Any]] = data.get("page") if isinstance(data, dict) else None
        if not page_info:
            # If no page info, assume single page
            break
        total_pages = page_info.get("totalPages")
        page += 1
        if isinstance(total_pages, int) and page >= total_pages:
            break

    return collected[:limit]

async def fetch_properties_for_ontology(
    ontology_id: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> List[str]:
    """Fetch ontology properties (object/data annotation properties) labels via OLS4.

    We return only labels, ignoring alternative IDs. De-duplicate and paginate.
    Endpoint: /ols4/api/ontologies/{id}/properties
    """
    base_url = f"{OLS4_BASE.replace('/ontologies', '')}/ontologies/{ontology_id}/properties"
    page = 0
    size = 200
    collected: List[str] = []
    seen = set()
    while len(collected) < limit:
        params = {"size": size, "page": page, "sort": "label,asc"}
        r = await client.get(base_url, params=params)
        if r.status_code != 200:
            break
        data = r.json()
        batch = [p.get("label", "") for p in data.get("_embedded", {}).get("properties", []) if p.get("label")]
        if not batch:
            break
        for label in batch:
            if label not in seen:
                seen.add(label)
                collected.append(label)
                if len(collected) >= limit:
                    break
        page_info: Optional[Dict[str, Any]] = data.get("page") if isinstance(data, dict) else None
        if not page_info:
            break
        total_pages = page_info.get("totalPages")
        page += 1
        if isinstance(total_pages, int) and page >= total_pages:
            break
    return collected[:limit]


def load_custom_ontologies() -> List[Dict[str, Any]]:
    """Load custom ontologies from custom_ontologies.json file."""
    if not CUSTOM_ONTOLOGIES_FILE.exists():
        logger.info("ℹ️  No custom ontologies file found")
        return []
    
    try:
        with CUSTOM_ONTOLOGIES_FILE.open(encoding="utf-8") as fp:
            data = json.load(fp)
        
        custom_ontologies = data.get("ontologies", [])
        if custom_ontologies:
            logger.info(f"📦 Loaded {len(custom_ontologies)} custom ontologies")
        return custom_ontologies
    except Exception as e:
        logger.error(f"❌ Failed to load custom ontologies: {e}")
        return []


async def fetch_all_ontologies() -> List[Dict[str, Any]]:
    logger.info("🔄 Ontologies fetch started")
    metadata = await fetch_ontology_metadata_only()
    try:
        logger.info(f"📋 Ontologies to fetch from OLS4: {len(metadata)}")
    except Exception:
        pass
    results: List[Dict[str, Any]] = []
    batch_size = 6
    total_batches = (len(metadata) + batch_size - 1) // batch_size
    
    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(metadata), batch_size):
            batch_num = (i // batch_size) + 1
            batch = metadata[i:i + batch_size]
            
            logger.info(f"⏳ Processing batch {batch_num}/{total_batches} ({len(batch)} ontologies)")
            
            term_tasks = [fetch_terms_for_ontology(m["id"], client, limit=200) for m in batch]
            prop_tasks = [fetch_properties_for_ontology(m["id"], client, limit=200) for m in batch]
            term_lists, prop_lists = await asyncio.gather(
                asyncio.gather(*term_tasks, return_exceptions=True),
                asyncio.gather(*prop_tasks, return_exceptions=True),
            )
            for m, terms, props in zip(batch, term_lists, prop_lists):
                t = [] if isinstance(terms, Exception) else terms
                p = [] if isinstance(props, Exception) else props
                entry = {**m, "properties": p, "terms": t}
                results.append(entry)
            
            progress_pct = (batch_num / total_batches) * 100
            logger.info(f"📊 Progress: {len(results)}/{len(metadata)} ontologies ({progress_pct:.1f}%)")
    
    # Merge custom ontologies
    custom_ontologies = load_custom_ontologies()
    if custom_ontologies:
        logger.info(f"➕ Merging {len(custom_ontologies)} custom ontologies")
        results.extend(custom_ontologies)
    
    try:
        num_ont = len(results)
        total_terms = sum(len(o.get("terms", [])) for o in results)
        total_props = sum(len(o.get("properties", [])) for o in results)
        logger.info(
            f"✅ Ontologies fetch finished: {num_ont} ontologies, {total_terms} terms, {total_props} properties"
        )
    except Exception:
        pass
    return results


