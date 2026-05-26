from __future__ import annotations

import asyncio
import json
import random
import logging
from typing import Dict, Any, List

import httpx

from .config import OLS4_BASE, CUSTOM_ONTOLOGIES_FILE

logger = logging.getLogger("uvicorn.ontologies.service")
logger.setLevel(logging.INFO)

# Constants
PAGE_SIZE = 200
MAX_RANDOM_PAGES_TERMS = 20
MAX_RANDOM_PAGES_PROPERTIES = 15
DEFINING_TERMS_RATIO = 0.9


async def fetch_ontology_metadata_only() -> List[Dict[str, Any]]:
    """Fetch ontology metadata from OLS4 without terms/properties."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{OLS4_BASE}?size=1000", headers={"accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    
    if "_embedded" not in payload or "ontologies" not in payload["_embedded"]:
        return []

    ontologies: List[Dict[str, Any]] = []
    for ontology_data in payload["_embedded"]["ontologies"]:
        config = ontology_data.get("config", {})
        ontology = {
            "id": ontology_data["ontologyId"],
            "name": config.get("title", ontology_data["ontologyId"]),
            "description": config.get("description", ""),
            "namespace": config.get("fileLocation", ""),
            "annotator": f"sqlite:obo:{ontology_data['ontologyId']}",
        }
        ontologies.append(ontology)
    return ontologies


async def fetch_terms_for_ontology(
    ontology_id: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> List[str]:
    """Fetch class labels using random sampling, targeting 90% defining and 10% imported terms."""
    base_url = f"{OLS4_BASE.replace('/ontologies', '')}/ontologies/{ontology_id}/terms"
    
    response = await client.get(base_url, params={"size": PAGE_SIZE, "page": 0})
    if response.status_code != 200:
        return []
    
    data = response.json()
    page_info = data.get("page", {})
    total_pages = page_info.get("totalPages", 1)
    total_elements = page_info.get("totalElements", 0)
    
    if total_elements == 0:
        return []
    
    page_0_data = data.get("_embedded", {}).get("terms", [])
    defining_terms: List[str] = []
    imported_terms: List[str] = []
    seen = set()
    
    defining_target = int(limit * DEFINING_TERMS_RATIO)
    imported_target = limit - defining_target
    
    all_pages = list(range(total_pages))
    random.shuffle(all_pages)
    
    pages_fetched = 0
    max_pages_to_fetch = min(MAX_RANDOM_PAGES_TERMS, total_pages)
    
    for page in all_pages:
        if (len(defining_terms) >= defining_target and len(imported_terms) >= imported_target) or \
           pages_fetched >= max_pages_to_fetch:
            break
        
        if page == 0:
            terms_data = page_0_data
        else:
            response = await client.get(base_url, params={"size": PAGE_SIZE, "page": page})
            if response.status_code != 200:
                continue
            page_data = response.json()
            terms_data = page_data.get("_embedded", {}).get("terms", [])
        
        for term in terms_data:
            label = term.get("label", "")
            if not label or label in seen:
                continue
            
            seen.add(label)
            is_defining = term.get("is_defining_ontology", True)
            
            if is_defining and len(defining_terms) < defining_target:
                defining_terms.append(label)
            elif not is_defining and len(imported_terms) < imported_target:
                imported_terms.append(label)
            
            if len(defining_terms) >= defining_target and len(imported_terms) >= imported_target:
                break
        
        pages_fetched += 1
    
    combined = defining_terms[:defining_target] + imported_terms[:imported_target]
    random.shuffle(combined)
    return combined[:limit]

async def fetch_properties_for_ontology(
    ontology_id: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> List[str]:
    """Fetch property labels using random sampling from OLS4."""
    base_url = f"{OLS4_BASE.replace('/ontologies', '')}/ontologies/{ontology_id}/properties"
    
    response = await client.get(base_url, params={"size": PAGE_SIZE, "page": 0})
    if response.status_code != 200:
        return []
    
    data = response.json()
    page_info = data.get("page", {})
    total_pages = page_info.get("totalPages", 1)
    total_elements = page_info.get("totalElements", 0)
    
    if total_elements == 0:
        return []
    
    page_0_data = data.get("_embedded", {}).get("properties", [])
    collected: List[str] = []
    seen = set()
    
    all_pages = list(range(total_pages))
    random.shuffle(all_pages)
    
    pages_fetched = 0
    max_pages_to_fetch = min(MAX_RANDOM_PAGES_PROPERTIES, total_pages)
    
    for page in all_pages:
        if len(collected) >= limit or pages_fetched >= max_pages_to_fetch:
            break
        
        if page == 0:
            props_data = page_0_data
        else:
            response = await client.get(base_url, params={"size": PAGE_SIZE, "page": page})
            if response.status_code != 200:
                continue
            page_data = response.json()
            props_data = page_data.get("_embedded", {}).get("properties", [])
        
        for prop in props_data:
            label = prop.get("label", "")
            if label and label not in seen:
                seen.add(label)
                collected.append(label)
                if len(collected) >= limit:
                    break
        
        pages_fetched += 1
    
    random.shuffle(collected)
    return collected[:limit]


def load_custom_ontologies() -> List[Dict[str, Any]]:
    """Load custom ontologies from JSON file."""
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
    """Fetch all ontologies with their terms and properties."""
    logger.info("🔄 Ontologies fetch started")
    metadata = await fetch_ontology_metadata_only()
    logger.info(f"📋 Ontologies to fetch from OLS4: {len(metadata)}")
    
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
            
            for metadata_item, terms, props in zip(batch, term_lists, prop_lists):
                terms_list = [] if isinstance(terms, Exception) else terms
                props_list = [] if isinstance(props, Exception) else props
                entry = {**metadata_item, "properties": props_list, "terms": terms_list}
                results.append(entry)
            
            progress_pct = (batch_num / total_batches) * 100
            logger.info(f"📊 Progress: {len(results)}/{len(metadata)} ontologies ({progress_pct:.1f}%)")
    
    custom_ontologies = load_custom_ontologies()
    if custom_ontologies:
        logger.info(f"➕ Merging {len(custom_ontologies)} custom ontologies")
        results.extend(custom_ontologies)
    
    num_ont = len(results)
    total_terms = sum(len(o.get("terms", [])) for o in results)
    total_props = sum(len(o.get("properties", [])) for o in results)
    logger.info(
        f"✅ Ontologies fetch finished: {num_ont} ontologies, {total_terms} terms, {total_props} properties"
    )
    return results


