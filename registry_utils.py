"""
Utility functions for enum and regex registry operations.
"""
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List

# Path to data directory
DATA_DIR = Path(__file__).parent / "data"

# Import custom ontologies file path from ontologies config
from ontologies.config import CUSTOM_ONTOLOGIES_FILE

logger = logging.getLogger("uvicorn.registry_utils")

# Lock for custom ontologies operations to prevent race conditions
_custom_ontologies_lock = asyncio.Lock()


def load_json_file(filename: str) -> Dict[str, Any]:
    """Load JSON file from data directory"""
    filepath = DATA_DIR / filename
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # Return empty dict if file is corrupted or can't be read
            return {}
    return {}


def save_json_file(filename: str, data: Dict[str, Any]) -> None:
    """Save JSON file to data directory"""
    # Ensure data directory exists
    DATA_DIR.mkdir(exist_ok=True)
    
    filepath = DATA_DIR / filename
    # Write to temporary file first, then rename (atomic operation)
    temp_filepath = filepath.with_suffix('.tmp')
    
    try:
        with open(temp_filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Atomic rename
        temp_filepath.replace(filepath)
    except IOError as e:
        # Clean up temp file if something goes wrong
        if temp_filepath.exists():
            temp_filepath.unlink()
        raise


def is_admin(username: str) -> bool:
    """Check if user is admin (username === 'schemalink')"""
    return username == "schemalink"


async def save_custom_ontologies(ontologies: List[Dict[str, Any]]) -> None:
    """
    Save custom ontologies to custom_ontologies.json file with atomic operation and lock.
    Uses asyncio.Lock() to prevent race conditions during concurrent modifications.
    """
    async with _custom_ontologies_lock:
        # Ensure directory exists
        CUSTOM_ONTOLOGIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first, then rename (atomic operation)
        temp_filepath = CUSTOM_ONTOLOGIES_FILE.with_suffix('.tmp')
        
        try:
            data = {"ontologies": ontologies}
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Atomic rename
            temp_filepath.replace(CUSTOM_ONTOLOGIES_FILE)
            logger.info(f"💾 Saved {len(ontologies)} custom ontologies")
        except IOError as e:
            logger.error(f"❌ Failed to save custom ontologies: {e}")
            # Clean up temp file if something goes wrong
            if temp_filepath.exists():
                temp_filepath.unlink()
            raise


async def load_and_modify_custom_ontologies(modify_func):
    """
    Load custom ontologies, apply a modification function, and save atomically.
    This ensures the entire load-modify-save operation is protected by a lock,
    preventing race conditions where concurrent requests could overwrite each other's changes.
    
    Args:
        modify_func: A function that takes a list of ontologies and returns the modified list
        
    Returns:
        The modified list of ontologies
    """
    from ontologies.service import load_custom_ontologies
    
    async with _custom_ontologies_lock:
        # Load within the lock to ensure we have the latest data
        ontologies = load_custom_ontologies()
        # Apply modification
        modified_ontologies = modify_func(ontologies)
        # Save within the same lock
        CUSTOM_ONTOLOGIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_filepath = CUSTOM_ONTOLOGIES_FILE.with_suffix('.tmp')
        
        try:
            data = {"ontologies": modified_ontologies}
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_filepath.replace(CUSTOM_ONTOLOGIES_FILE)
            logger.info(f"💾 Saved {len(modified_ontologies)} custom ontologies")
            return modified_ontologies
        except IOError as e:
            logger.error(f"❌ Failed to save custom ontologies: {e}")
            if temp_filepath.exists():
                temp_filepath.unlink()
            raise


async def update_cache_with_custom_ontology(ontology: Dict[str, Any], operation: str = "upsert"):
    """
    Update the ontology cache with a custom ontology change.
    
    Args:
        ontology: The ontology dictionary to add/update/remove
        operation: "upsert" to add/update, "delete" to remove
    """
    from ontologies import cache
    
    try:
        ontology_id = ontology.get("id", "").lower() if ontology.get("id") else ""
        
        # Validate ontology_id is not empty
        if not ontology_id:
            logger.warning("⚠️  Cannot update cache: ontology ID is empty")
            return
        
        async with cache.locked_cache() as cached:
            if operation == "delete":
                if ontology_id in cached:
                    del cached[ontology_id]
                    logger.info(f"🗑️  Removed custom ontology '{ontology_id}' from cache")
                else:
                    logger.debug(f"ℹ️  Custom ontology '{ontology_id}' not found in cache (may have been removed already)")
            else:  # upsert
                # Ensure properties and terms are set
                ontology.setdefault("properties", [])
                ontology.setdefault("terms", [])
                cached[ontology_id] = ontology.copy()
                logger.info(f"🔄 Updated cache with custom ontology '{ontology_id}'")
    except Exception as e:
        logger.error(f"❌ Failed to update cache with custom ontology: {e}", exc_info=True)
        # Don't raise - cache update failure shouldn't break CRUD operations

