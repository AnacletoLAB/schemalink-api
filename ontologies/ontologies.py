from __future__ import annotations

from typing import List, Dict, Any, Optional
import logging
import random
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import cache
from . import service

# Create named logger for better integration with FastAPI
# Use uvicorn's logger to ensure logs appear in FastAPI output
logger = logging.getLogger("uvicorn.ontologies")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/ontologies", tags=["ontologies"])


# Refresh state management
class RefreshState:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.in_progress = False
        self.last_started: Optional[datetime] = None
        self.last_completed: Optional[datetime] = None
    
    async def is_in_progress(self) -> bool:
        return self.in_progress


refresh_state = RefreshState()


async def background_refresh():
    """Background refresh task that updates the cache without blocking startup."""
    try:
        logger.info("🚀 Background refresh task started")
        await refresh_all()
        async with refresh_state._lock:
            refresh_state.in_progress = False
            refresh_state.last_completed = datetime.now()
        logger.info("✅ Background refresh completed successfully")
    except Exception as e:
        logger.error(f"❌ Background refresh failed: {e}")
        async with refresh_state._lock:
            refresh_state.in_progress = False


class IdsBody(BaseModel):
    ids: List[str]


@router.get("/list", response_model=List[Dict[str, Any]])
async def list_cached() -> List[Dict[str, Any]]:
    return await cache.load()


@router.post("/by_ids", response_model=List[Dict[str, Any]])
async def by_ids(
    body: IdsBody,
    limit: Optional[int] = Query(None, description="Limit number of terms/properties to return"),
    random_sample: Optional[bool] = Query(False, description="Whether to return random sample of terms/properties")
) -> List[Dict[str, Any]]:
    async with cache.locked_cache() as cached:
        result = []
        for oid in body.ids:
            if oid.lower() in cached:
                ontology = cached[oid.lower()].copy()
                
                # Apply limit and random sampling if specified
                if limit is not None:
                    terms = ontology.get("terms", [])
                    properties = ontology.get("properties", [])
                    
                    if random_sample:
                        # Random sampling
                        ontology["terms"] = random.sample(terms, min(limit, len(terms))) if terms else []
                        ontology["properties"] = random.sample(properties, min(limit, len(properties))) if properties else []
                    else:
                        # Just take first N items
                        ontology["terms"] = terms[:limit]
                        ontology["properties"] = properties[:limit]
                
                result.append(ontology)
        return result


@router.post("/refresh", response_model=Dict[str, Any])
async def trigger_refresh() -> Dict[str, Any]:
    """Manually trigger a full ontologies refresh from OLS4. Always forces a full refresh."""
    try:
        # Check if refresh is already in progress
        if await refresh_state.is_in_progress():
            return {
                "status": "skipped",
                "message": "Refresh already in progress",
                "count": 0
            }
        
        # Set the in_progress flag
        async with refresh_state._lock:
            refresh_state.in_progress = True
            refresh_state.last_started = datetime.now()
        
        try:
            result = await refresh_all(force=True)
            return {
                "status": "success",
                "message": f"Refreshed {len(result)} ontologies",
                "count": len(result)
            }
        finally:
            # Always clear the flag when done
            async with refresh_state._lock:
                refresh_state.in_progress = False
                refresh_state.last_completed = datetime.now()
    except Exception as e:
        logger.error(f"Manual refresh failed: {e}")
        async with refresh_state._lock:
            refresh_state.in_progress = False
        raise HTTPException(status_code=500, detail=str(e))


async def refresh_all(force: bool = False) -> List[Dict[str, Any]]:
    """
    Refresh ontologies from OLS4 and merge with custom ontologies.
    
    Strategy:
    - If OLS4 changes: Do full refresh from OLS4 and merge custom ontologies
    - If only custom ontologies change: Update cache with custom ontologies only (no OLS4 fetch)
    - If nothing changes: Return cached data
    
    Args:
        force: If True, always perform full refresh regardless of metadata changes.
               If False, only refresh when metadata has changed.
    """
    try:
        logger.info("🔄 Ontologies refresh requested" + (" (forced)" if force else ""))
        
        current_cached = await cache.load_as_dict()
        
        # If cache is empty, force full refresh
        if len(current_cached) == 0:
            logger.info("🆕 Cache is empty, forcing full refresh")
            logger.info("⬇️  Fetching full ontology data from OLS4...")
            full = await service.fetch_all_ontologies()
            async with cache.locked_cache() as cached:
                cached.clear()
                for o in full:
                    cached[o["id"].lower()] = o
                logger.info(f"✅ Refresh completed: {len(cached)} ontologies cached")
                return list(cached.values())
        
        # Fetch OLS4 metadata
        new_ols4_metadata = await service.fetch_ontology_metadata_only()
        
        # Load custom ontologies
        custom_ontologies = service.load_custom_ontologies()
        custom_metadata = []
        for o in custom_ontologies:
            custom_metadata.append({
                "id": o.get("id"),
                "name": o.get("name"),
                "description": o.get("description"),
                "namespace": o.get("namespace"),
                "annotator": o.get("annotator"),
            })
        
        # Extract current metadata from cache
        # We need to identify which cached ontologies are custom vs OLS4
        # Strategy: Compare cache against OLS4 to identify custom ontologies
        new_custom_ids = {o.get("id", "").lower() for o in custom_ontologies}
        new_ols4_ids = {o.get("id", "").lower() for o in new_ols4_metadata}
        
        current_ols4_metadata = []
        current_custom_metadata = []
        
        for oid, o in current_cached.items():
            metadata_entry = {
                "id": o.get("id"),
                "name": o.get("name"),
                "description": o.get("description"),
                "namespace": o.get("namespace"),
                "annotator": o.get("annotator"),
            }
            # If it's in new custom ontologies, it's custom
            # If it's in new OLS4 metadata, it's OLS4
            # Otherwise, check if it was likely custom (not in OLS4)
            if oid in new_custom_ids:
                current_custom_metadata.append(metadata_entry)
            elif oid in new_ols4_ids:
                current_ols4_metadata.append(metadata_entry)
            else:
                # This ontology is in cache but not in new OLS4 or new custom
                # It's likely a deleted custom ontology or a removed OLS4 ontology
                # We'll treat it as custom for comparison purposes
                current_custom_metadata.append(metadata_entry)

        import hashlib, json
        
        # Compare OLS4 metadata separately
        current_ols4_hash = hashlib.md5(
            json.dumps(sorted(current_ols4_metadata, key=lambda x: x["id"]), sort_keys=True).encode()
        ).hexdigest()
        new_ols4_hash = hashlib.md5(
            json.dumps(sorted(new_ols4_metadata, key=lambda x: x["id"]), sort_keys=True).encode()
        ).hexdigest()
        
        # Compare custom metadata separately
        current_custom_hash = hashlib.md5(
            json.dumps(sorted(current_custom_metadata, key=lambda x: x["id"]), sort_keys=True).encode()
        ).hexdigest()
        new_custom_hash = hashlib.md5(
            json.dumps(sorted(custom_metadata, key=lambda x: x["id"]), sort_keys=True).encode()
        ).hexdigest()
        
        ols4_changed = current_ols4_hash != new_ols4_hash
        custom_changed = current_custom_hash != new_custom_hash
        
        if force:
            logger.info("🔨 Force refresh requested - performing full refresh")
            logger.info("⬇️  Fetching full ontology data from OLS4...")
            full = await service.fetch_all_ontologies()
            async with cache.locked_cache() as cached:
                cached.clear()
                for o in full:
                    cached[o["id"].lower()] = o
                logger.info(f"✅ Refresh completed: {len(cached)} ontologies cached")
                return list(cached.values())
        elif ols4_changed:
            logger.info("🔄 OLS4 metadata changed - performing full refresh from OLS4")
            logger.info("⬇️  Fetching full ontology data from OLS4...")
            full = await service.fetch_all_ontologies()
            async with cache.locked_cache() as cached:
                cached.clear()
                for o in full:
                    cached[o["id"].lower()] = o
                logger.info(f"✅ Refresh completed: {len(cached)} ontologies cached")
                return list(cached.values())
        elif custom_changed:
            logger.info("🔄 Custom ontologies changed - updating cache with custom ontologies only")
            # Only update custom ontologies in cache, don't fetch from OLS4
            async with cache.locked_cache() as cached:
                # Identify which ontologies in cache are custom (not in OLS4)
                # Remove all custom ontologies (both old and new ones)
                new_custom_ids_set = {o.get("id", "").lower() for o in custom_ontologies}
                ids_to_remove = []
                for oid in cached.keys():
                    # If it's in new custom list, we'll update it
                    # If it's not in OLS4, it's a custom ontology (old or deleted)
                    if oid not in new_ols4_ids:
                        ids_to_remove.append(oid)
                
                for oid in ids_to_remove:
                    del cached[oid]
                
                # Add/update custom ontologies
                for o in custom_ontologies:
                    oid = o.get("id", "").lower()
                    o.setdefault("properties", [])
                    o.setdefault("terms", [])
                    cached[oid] = o
                
                logger.info(f"✅ Updated cache with {len(custom_ontologies)} custom ontologies (removed {len(ids_to_remove)} old custom ontologies)")
                return list(cached.values())
        else:
            logger.info("✅ No changes detected - using cached data")
            return list(current_cached.values())
    except Exception as e:
        logger.error(f"❌ Failed to refresh ontologies: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh ontologies: {e}")





