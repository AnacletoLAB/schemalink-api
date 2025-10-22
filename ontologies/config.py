from pathlib import Path

# Root folder for persistent ontology assets (separate from legacy)
BASE_DIR = Path(__file__).parent / "data_directory"
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Wrapped JSON cache path
CACHE_FILE = BASE_DIR / "ontologies.json"

# Custom ontologies file (persists through OLS4 refreshes)
CUSTOM_ONTOLOGIES_FILE = BASE_DIR / "custom_ontologies.json"

# Upstream ontology source (OLS4)
OLS4_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies"






