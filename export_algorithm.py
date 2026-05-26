import yaml
from typing import Dict, Any, List


def _find_node(nodes, node_id):
    """Return the caption of a given node (by id)."""
    for n in nodes:
        if n["id"] == node_id:
            return n["caption"]
    return None


def _merge_if(target: Dict[str, Any], source: Dict[str, Any], keys):
    """Copy selected keys from source to target if they exist and are non-empty."""
    for key in keys:
        if key in source and source[key] not in (None, "", {}, []):
            target[key] = source[key]


def _normalize_ontology_token(token: str) -> str:
    """Normalize ontology specifier to canonical form (matching webapp logic)."""
    raw = (token or "").strip().lower()
    if not raw:
        return ""
    tokens = [t.strip() for t in raw.split(":") if t.strip()]
    # Find last purely alphabetic token
    last_alpha = ""
    for t in reversed(tokens):
        if t.isalpha():
            last_alpha = t
            break
    if not last_alpha:
        return raw
    # If OBO referenced, normalize to sqlite:obo:{id}
    if "obo" in tokens or raw.startswith("obo:") or ":obo:" in raw:
        return f"sqlite:obo:{last_alpha}"
    return raw


def _ontologies_to_id_prefixes(ontologies: List[Dict]) -> List[str]:
    """Convert ontologies list to id_prefixes array."""
    if not ontologies:
        return []
    return [o.get("id", "").upper() for o in ontologies if isinstance(o, dict) and o.get("id")]


def _ontologies_to_annotators(ontologies: List[Dict]) -> str:
    """Convert ontologies list to annotators string (matching webapp format)."""
    if not ontologies:
        return ""
    # Use the 'annotator' field, normalize it
    annotators = []
    for o in ontologies:
        if isinstance(o, dict) and o.get("annotator"):
            normalized = _normalize_ontology_token(o["annotator"])
            if normalized:
                annotators.append(normalized)
    return ", ".join(annotators)


def _ontologies_to_prefixes(ontologies: List[Dict]) -> Dict[str, str]:
    """Convert ontologies list to prefixes dict."""
    if not ontologies:
        return {}
    prefixes = {}
    for o in ontologies:
        if isinstance(o, dict) and o.get("id") and o.get("namespace"):
            prefixes[o["id"].upper()] = o["namespace"]
    return prefixes


def convert_internal_representation_to_yaml(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Convert internal graph to LinkML YAML schema dict."""
    metadata = graph.get("metadata", {})
    nodes = graph.get("nodes", [])
    relationships = graph.get("relationships", [])
    default_range = metadata.get("default_range", None)

    classes: Dict[str, Dict[str, Any]] = {}

    # Build class stubs from nodes
    for node in nodes:
        class_name = node["caption"]
        classes[class_name] = {"attributes": {}}
        _merge_if(classes[class_name], node, ["description", "annotations", "is_a", "tree_root"])
        
        # Add ontologies as id_prefixes and annotations.annotators
        node_ontologies = node.get("ontologies", [])
        if node_ontologies:
            id_prefixes = _ontologies_to_id_prefixes(node_ontologies)
            if id_prefixes:
                classes[class_name]["id_prefixes"] = id_prefixes
            annotators = _ontologies_to_annotators(node_ontologies)
            if annotators:
                if "annotations" not in classes[class_name]:
                    classes[class_name]["annotations"] = {}
                classes[class_name]["annotations"]["annotators"] = annotators

        # Reconstruct is_a from inheritance edges when not stored on node
        if "is_a" not in classes[class_name]:
            for rel in relationships:
                if (rel.get("relationshipType") == "INHERITANCE" and
                    rel.get("fromId") == node["id"]):
                    parent_caption = _find_node(nodes, rel.get("toId"))
                    if parent_caption:
                        classes[class_name]["is_a"] = parent_caption
                        break

    # Add attributes from relationships (skip inheritance relationships)
    for rel in relationships:
        # Skip inheritance relationships - they are handled via is_a
        if rel.get("relationshipType") == "INHERITANCE":
            continue
            
        source_class = _find_node(nodes, rel["fromId"])
        target_class = _find_node(nodes, rel["toId"])
        rel_type = rel.get("type", "")
        if not source_class or not target_class or not rel_type:
            continue

        attr_entry: Dict[str, Any] = {}

        # range - always include for relationship attributes
        attr_entry["range"] = target_class

        # description
        if rel.get("description"):
            attr_entry["description"] = rel["description"]

        multivalued = rel.get("multivalued", False)
        if multivalued:
            attr_entry["multivalued"] = True

        # inlined - explicitly set True or False for relationship attributes
        inlined = rel.get("inlined", False)
        attr_entry["inlined"] = inlined
        
        if rel.get("inlined_as_list", False):
            attr_entry["inlined_as_list"] = True

        # required
        required = rel.get("required", False)
        if required is not None:
            attr_entry["required"] = required

        # cardinality
        if rel.get("minimum_cardinality") is not None:
            attr_entry["minimum_cardinality"] = rel["minimum_cardinality"]
        if rel.get("maximum_cardinality") is not None:
            attr_entry["maximum_cardinality"] = rel["maximum_cardinality"]

        max_cardinality = rel.get("maximum_cardinality")
        if isinstance(max_cardinality, int):
            attr_entry["maximum_cardinality"] = max_cardinality

        # ontologies for relationship
        rel_ontologies = rel.get("ontologies", [])
        if rel_ontologies:
            annotators = _ontologies_to_annotators(rel_ontologies)
            if annotators:
                attr_entry["annotations"] = {"annotators": annotators}

        classes[source_class]["attributes"][rel_type] = attr_entry

        # Handle bidirectional navigation: add reverse attribute to target class
        navigation = rel.get("navigation", "").lower()
        if navigation == "none":
            reverse_attr_entry: Dict[str, Any] = {}
            reverse_attr_entry["range"] = source_class
            
            if rel.get("description"):
                reverse_attr_entry["description"] = rel["description"]
            if multivalued:
                reverse_attr_entry["multivalued"] = True
            reverse_attr_entry["inlined"] = inlined
            if rel.get("inlined_as_list", False):
                reverse_attr_entry["inlined_as_list"] = True
            if required is not None:
                reverse_attr_entry["required"] = required
            if rel.get("minimum_cardinality") is not None:
                reverse_attr_entry["minimum_cardinality"] = rel["minimum_cardinality"]
            if isinstance(rel.get("maximum_cardinality"), int):
                reverse_attr_entry["maximum_cardinality"] = rel["maximum_cardinality"]
            if rel_ontologies:
                annotators = _ontologies_to_annotators(rel_ontologies)
                if annotators:
                    reverse_attr_entry["annotations"] = {"annotators": annotators}
                    
            classes[target_class]["attributes"][rel_type] = reverse_attr_entry

    # Add attributes from node properties
    for node in nodes:
        class_name = node["caption"]
        props = node.get("properties", {})
        for prop, spec in props.items():
            attr_entry: Dict[str, Any] = {}

            # Always include range for properties
            if "range" in spec:
                attr_entry["range"] = spec["range"]
            else:
                attr_entry["range"] = "string"

            if spec.get("identifier", False):
                attr_entry["identifier"] = True

            inlined = spec.get("inlined", False)
            if inlined:
                attr_entry["inlined"] = True
            if spec.get("inlined_as_list", False):
                attr_entry["inlined_as_list"] = True

            multivalued = spec.get("multivalued", False)
            if multivalued:
                attr_entry["multivalued"] = True

            # Pattern for regex validation
            if spec.get("pattern"):
                attr_entry["pattern"] = spec["pattern"]

            _merge_if(
                attr_entry,
                spec,
                [
                    "description",
                    "annotations",
                    "required",
                    "minimum_value",
                    "maximum_value",
                    "minimum_cardinality",
                    "maximum_cardinality",
                ],
            )

            max_p = spec.get("maximum_cardinality")
            if isinstance(max_p, int):
                attr_entry["maximum_cardinality"] = max_p

            classes[class_name]["attributes"][prop] = attr_entry

    # Collect ontology-based prefixes from all nodes and relationships
    all_ontologies = []
    for node in nodes:
        all_ontologies.extend(node.get("ontologies", []))
    for rel in relationships:
        all_ontologies.extend(rel.get("ontologies", []))
    ontology_prefixes = _ontologies_to_prefixes(all_ontologies)

    # Build prefixes - merge defaults with ontology-based and metadata prefixes
    prefixes = {
        "linkml": "https://w3id.org/linkml/",
        "rdf": "https://www.w3.org/1999/02/22-rdf-syntax-ns#",
        **ontology_prefixes,
        **metadata.get("prefixes", {}),
    }

    # Build imports - use provided or defaults
    imports = metadata.get("imports", [])
    if not imports:
        imports = [{"linkml": "types"}]

    yaml_schema: Dict[str, Any] = {
        "id": metadata.get("id"),
        "default_range": metadata.get("default_range"),
        "name": metadata.get("name"),
        "title": metadata.get("title"),
        "description": metadata.get("description"),
        "imports": imports,
        "prefixes": prefixes,
        "classes": classes,
    }

    # Add optional fields if present
    if metadata.get("license"):
        yaml_schema["license"] = metadata["license"]
    if metadata.get("keywords"):
        yaml_schema["keywords"] = metadata["keywords"]
    if metadata.get("default_prefix"):
        yaml_schema["default_prefix"] = metadata["default_prefix"]
    if metadata.get("enums"):
        yaml_schema["enums"] = metadata["enums"]

    # Remove empty fields (but keep prefixes and imports even if default)
    yaml_schema = {k: v for k, v in yaml_schema.items() if v not in (None, "", {})}

    return yaml_schema


def dump_yaml_schema(yaml_schema: Dict[str, Any]) -> str:
    """Serialize schema dict to YAML string."""
    return yaml.safe_dump(yaml_schema, sort_keys=False)


