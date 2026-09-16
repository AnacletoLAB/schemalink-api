from typing import Dict, Any, List

PG_TYPES_MAP = {
    "string": "STRING", "integer": "INT", "int": "INT",
    "boolean": "BOOLEAN", "bool": "BOOLEAN",
    "float": "FLOAT", "double": "DOUBLE", "date": "DATE"
}

def _find_original_type_by_caption(nodes: List[Dict[str, Any]], caption: Any, fallback: Any = None):
    """Cerca un nodo per caption (case-insensitive) e ne restituisce l'original_type_name."""
    clean_caption = str(caption).lower()
    return next((n.get("original_type_name") for n in nodes if n.get("caption", "").lower() == clean_caption), fallback)

def convert_internal_representation_to_pgschema_dict(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Trasforma il JSON interno in un dizionario strutturato per PG-Schema."""

    raw_name = graph.get("name", "UntitledGraph")
    safe_name = raw_name.replace(" ", "_")

    pg_schema_dict = {
        "name": safe_name,
        "mode": graph.get("graphTypeMode", "strict").upper(),
        "imports": graph.get("imports", []),
        "nodes": [],
        "abstract_nodes": [],
        "relationships": [],
        "constraints": []
    }
    
    raw_nodes = graph.get("nodes", [])
    relationships = graph.get("relationships", [])

    # --- ORDINAMENTO TOPOLOGICO ---
    # stampo sempre i Padri prima dei Figli
    deps = {n["id"]: set() for n in raw_nodes if "id" in n}
    for rel in relationships:
        if rel.get("relationshipType") in ("INHERITANCE", "EXCLUSIVE INHERITANCE"):
            child = rel.get("fromId")
            parent = rel.get("toId")
            if child in deps and parent in deps:
                deps[child].add(parent)
                
    sorted_node_ids = []
    visited = set()
    
    def visit(n_id):
        if n_id in visited: return
        visited.add(n_id)
        for p_id in deps.get(n_id, []):
            visit(p_id)
        sorted_node_ids.append(n_id)
        
    for n in raw_nodes:
        if "id" in n:
            visit(n["id"])
            
    node_map = {n["id"]: n for n in raw_nodes if "id" in n}
    nodes = [node_map[nid] for nid in sorted_node_ids]

    id_to_node = {n["id"]: n for n in nodes if "id" in n}
    id_to_typename = {}

    for n in nodes:
        node_id = n.get("id")
        if not node_id: 
            continue
            
        caption = n.get("caption", "Unknown")
        orig_var = n.get("original_type_name")

        if not orig_var:
            id_to_typename[node_id] = f"{caption.lower()}Type"
        elif orig_var == caption:
            id_to_typename[node_id] = caption
        else:
            id_to_typename[node_id] = orig_var

    node_parents = {} # id -> targets (ognuno marcato AND/XOR singolarmente)
    all_from_ids = set()
    all_to_ids = set()

    for rel in relationships:
        rel_type = rel.get("relationshipType")
        if rel_type in ("INHERITANCE", "EXCLUSIVE INHERITANCE"):
            from_id = rel.get("fromId")
            to_id = rel.get("toId")

            if from_id in id_to_node and to_id in id_to_node:
                all_from_ids.add(from_id)
                all_to_ids.add(to_id)

                if from_id not in node_parents:
                    node_parents[from_id] = {"targets": []}

                is_required = rel.get("required", True)
                is_exclusive = rel_type == "EXCLUSIVE INHERITANCE"
                node_parents[from_id]["targets"].append({"id": to_id, "required": is_required, "exclusive": is_exclusive})

    seen_type_names = set()

    # NODES
    for node in nodes:
        node_id = node.get("id")
        type_name = id_to_typename.get(node_id, "Unknown")
        caption = node.get("caption", "Unknown")
        
        # 1. Nascondiamo i nodi fittizi e i frammenti logici ("AND", "XOR") generati dal traduttore
        if not node_id or node.get("note") == "reified" or " AND " in type_name or " XOR " in type_name or node.get("kind") == "GHOST":
            continue
            
        # 2. Nascondiamo i nodi base impliciti (es. A, B generati silenziosamente)
        if node_id not in node_parents and type_name == caption and not node.get("properties") and node_id in all_to_ids:
            continue

        if type_name in seen_type_names:
            continue
            
        seen_type_names.add(type_name)
        caption_str = _resolve_inheritance(node_id, node_parents, id_to_typename, id_to_node)
        formatted_node = _format_single_node(node, caption_str, type_name)

        if formatted_node:
            if node.get("abstract"):
                # I tipi ABSTRACT vanno dichiarati come istruzione a parte, non dentro
                # il blocco CREATE GRAPH TYPE (la grammatica PG-Schema non lo permette).
                pg_schema_dict["abstract_nodes"].append(f"CREATE NODE TYPE ABSTRACT {formatted_node}")
            else:
                pg_schema_dict["nodes"].append(formatted_node)

    # RELATIONSHIPS
    formatted_associations = _format_associations(relationships, nodes, id_to_typename)
    if formatted_associations:
        pg_schema_dict["relationships"].extend(formatted_associations)

    # CONSTRAINTS
    pg_schema_dict["constraints"] = _extract_constraintsfull(nodes, relationships)

    return pg_schema_dict

def _format_single_node(node, caption_str: str, type_name: str):
    open_config = node.get("open")
    is_class_open = False
    is_props_open = False
    
    if isinstance(open_config, dict):
        is_class_open = open_config.get("class", False)
        is_props_open = open_config.get("properties", False)
        
    class_open = " OPEN" if is_class_open else ""
    props_str = _format_properties(node.get("properties", {}), is_props_open)

    abstract_prefix = "ABSTRACT " if node.get("abstract") else ""

    return f"({type_name}: {caption_str}{class_open}{props_str})"

def _format_properties(properties_data: Dict[str, Any], is_props_open: bool = False):
    """Formatta le proprietà e i tipi di dato, gestendo clausola OPEN e OPTIONAL."""
    if not properties_data and not is_props_open:
        return ""
    
    props_list = []
    if properties_data:
        for k, v in properties_data.items():
            prop_type = v.get("range", "STRING").upper()
            mapped_type = PG_TYPES_MAP.get(prop_type.lower(), prop_type)
            
            opt_str = "OPTIONAL " if v.get("requiredType") == "optional" else ""
            props_list.append(f"{opt_str}{k} {mapped_type}")

    if is_props_open:
        props_list.append("OPEN")
        
    return " {" + ", ".join(props_list) + "}"

def _format_associations(relationships: list, nodes: list, id_to_typename: dict) -> list:
    grouped_assocs = {}
    formatted_rels = []

    # Archi semplici e provenienti da associazioni reificate
    for rel in relationships:
        if rel.get("relationshipType") != "ASSOCIATION":
            continue
            
        source_var = id_to_typename.get(rel.get("fromId"))
        target_var = id_to_typename.get(rel.get("toId"))
        
        if not source_var or not target_var:
            continue

        rel_type_name = rel.get("type", "unknown")
        current_props = rel.get("properties", {})
        
        # 1. Firma delle proprietà
        props_signature = tuple(sorted((k, v.get("range", "").lower(), v.get("requiredType", "optional"))
            for k, v in current_props.items()
        ))
        
        # 2. CHIAVE RIGIDA: separiamo ogni direttrice 1 a 1
        group_key = (source_var, target_var, rel_type_name, props_signature)
        if group_key not in grouped_assocs:
            grouped_assocs[group_key] = {
                "rel_typename": f"{rel_type_name.lower()}Type",
                "properties": {}, 
                "source": source_var,
                "target": target_var
            }
        
        if current_props:
            grouped_assocs[group_key]["properties"].update(current_props)

    for group_key, data in grouped_assocs.items():
        # 3. Estraiamo la sorgente e la destinazione specifiche dalla chiave
        source_var, target_var, rel_type_name, _ = group_key 
        properties = data["properties"]
        reified_types = []
        primitive_props = [] 
        
        if properties:
            for prop_name, prop_details in properties.items():
                range_val = prop_details.get("range", "").lower()
                is_optional = prop_details.get("requiredType") == "optional"
                
                if range_val not in PG_TYPES_MAP:
                    reified_types.append(f"{prop_name}?" if is_optional else prop_name)
                else:
                    pg_type = PG_TYPES_MAP[range_val]
                    opt_flag = "OPTIONAL" if is_optional else ""
                    primitive_props.append(f"{opt_flag} {prop_name} {pg_type}".strip())
        
        rel_label = " & ".join(reified_types) if reified_types else rel_type_name 
        props_str = f" {{{', '.join(primitive_props)}}}" if primitive_props else ""
        
        # 4. Stampiamo la singola relazione lineare senza |
        formatted_rels.append(f"(:{source_var})-[{data['rel_typename']}: {rel_label}{props_str}]->(:{target_var})")
        
    # Reified nodes
    node_map = {n["id"]: n for n in nodes}
    for node in nodes:
        if node.get("note") == "reified":
            node_id = node["id"]
            props = node.get("properties", {})
            
            source_range = props.get("source", {}).get("range")
            target_range = props.get("target", {}).get("range")

            if not source_range or not target_range:
                continue
            
            source_var = _find_original_type_by_caption(nodes, source_range)
            target_var = _find_original_type_by_caption(nodes, target_range)
            if not source_var or not target_var:
                print(f"WARN: Missing source or target. Association skipped")
                continue
            rel_typename = node.get("original_type_name", f"{node.get('caption', 'unknown').lower()}Type")

            inh_parents = [r for r in relationships if r.get("relationshipType") == "INHERITANCE" and r.get("fromId") == node_id]
            inh_children = [r for r in relationships if r.get("relationshipType") == "INHERITANCE" and r.get("toId") == node_id]
            excl_children = [r for r in relationships if r.get("relationshipType") == "EXCLUSIVE INHERITANCE" and r.get("toId") == node_id]

            primitive_props = []
            reified_labels = []
            
            for p_key, p_val in props.items():
                if p_key in ["source", "target"]:
                    continue

                range_val = p_val.get("range", "").lower()
                is_opt = p_val.get("requiredType") == "optional"
                
                # 2. Se il tipo non è nei primitivi, lo trattiamo come Label dell'AND!
                if range_val not in PG_TYPES_MAP:
                    reified_labels.append(f"{p_key}?" if is_opt else p_key)
                else:
                    pg_t = PG_TYPES_MAP.get(range_val, "STRING")
                    opt_flag = "OPTIONAL " if is_opt else ""
                    primitive_props.append(f"{opt_flag}{p_key} {pg_t}".strip())
                
            props_str = f" {{{', '.join(primitive_props)}}}" if primitive_props else ""

            # CASO A: XOR association (es: Activity -> Deposits|Withdraws)
            if len(excl_children) >= 2:
                children_labels = [node_map[r["fromId"]].get("caption", "") for r in excl_children if r["fromId"] in node_map]
                if len(children_labels) >= 2:
                    label = "|".join(sorted(children_labels))
                    formatted_rels.append(f"(:{source_var})-[{rel_typename}: {label}{props_str}]->(:{target_var})")
                continue
                
            # CASO B: Figlio in Ereditarietà (es: buddyType: friendType)
            if inh_parents:
                parent_node = node_map.get(inh_parents[0]["toId"])
                if parent_node:
                    rel_label = parent_node.get("original_type_name", f"{parent_node.get('caption', 'unknown').lower()}Type")
                    formatted_rels.append(f"(:{source_var})-[{rel_typename}: {rel_label}{props_str}]->(:{target_var})")
                continue
                
            # CASO C: Padre Base Reificato (es: friendType: Friend)
            if inh_children and not inh_parents:
                # 3. Assembliamo le label logiche se ci sono, altrimenti usiamo la caption!
                rel_label = " & ".join(reified_labels) if reified_labels else node.get("caption", "Unknown")
                formatted_rels.append(f"(:{source_var})-[{rel_typename}: {rel_label}{props_str}]->(:{target_var})")
                continue
    return formatted_rels

def _resolve_inheritance(node_id, node_parents, id_to_typename, id_to_node):
    """
    Entry point per la risoluzione dell'ereditarietà.
    Valida il nodo e innesca la costruzione ricorsiva dell'espressione.
    """
    if node_id not in node_parents:
        return id_to_node.get(node_id, {}).get("caption", "Unknown")

    targets = node_parents[node_id]["targets"]
    and_targets = [t for t in targets if not t["exclusive"]]
    xor_targets = [t for t in targets if t["exclusive"]]

    # Un gruppo XOR ha senso solo con almeno due alternative; un singolo target
    # esclusivo senza alternative (e senza altri genitori AND) non esprime nulla.
    if not and_targets and len(xor_targets) < 2:
        return id_to_node.get(node_id, {}).get("caption", "Unknown")

    # Innesca il motore ricorsivo, riusando la divisione AND/XOR già calcolata sopra
    return _build_expression_tree(node_id, node_parents, id_to_typename, id_to_node,
                                   and_targets=and_targets, xor_targets=xor_targets)


def _build_expression_tree(node_id, node_parents, id_to_typename, id_to_node, parent_op=None,
                            and_targets=None, xor_targets=None):
    """
    Helper ricorsivo: naviga l'albero delle dipendenze logiche, risolve i nomi
    e applica le parentesi per rispettare la precedenza degli operatori (es. AND dentro OR).

    I target di un nodo possono essere in parte AND (INHERITANCE) e in parte XOR
    (EXCLUSIVE INHERITANCE): in quel caso il gruppo XOR viene racchiuso tra parentesi
    e trattato come un singolo termine AND-ato con gli altri genitori.
    """
    # CASO BASE: Siamo arrivati a una foglia (nodo base)
    if node_id not in node_parents:
        return id_to_typename.get(node_id, id_to_node.get(node_id, {}).get("caption", "Unknown"))

    targets = node_parents[node_id]["targets"]
    root_type = id_to_typename.get(node_id, "Unknown")

    def resolve(target, sub_op):
        t_id = target["id"]
        t_type = id_to_typename.get(t_id, "Unknown")

        # CASO RICORSIVO: Il target è a sua volta un nodo logico intermedio
        if t_id in node_parents and (" AND " in t_type or " XOR " in t_type):
            sub_expr = _build_expression_tree(t_id, node_parents, id_to_typename, id_to_node, parent_op=sub_op)
        else:
            # Prevenzione dei conflitti di nome: se figlio e radice si chiamano uguale, usiamo la caption pura
            if t_type == root_type:
                sub_expr = id_to_node.get(t_id, {}).get("caption", "Unknown")
            else:
                sub_expr = t_type

        # Gestione dell'opzionalità
        if not target["required"]:
            sub_expr += " ?"

        return sub_expr

    if and_targets is None or xor_targets is None:
        and_targets = [t for t in targets if not t["exclusive"]]
        xor_targets = [t for t in targets if t["exclusive"]]

    if and_targets and len(xor_targets) >= 2:
        # CASO MISTO: genitori obbligatori (AND) + un gruppo di alternative esclusive (XOR)
        and_parts = [resolve(t, "&") for t in and_targets]
        xor_parts = [resolve(t, "|") for t in xor_targets]
        and_parts.append(f"({' | '.join(xor_parts)})")
        expr = " & ".join(and_parts)
        op = "&"
    else:
        # CASO PURO: solo AND, oppure solo XOR (un XOR con un solo target degenera in AND)
        op = "|" if (xor_targets and not and_targets and len(xor_targets) >= 2) else "&"
        merged_targets = and_targets + xor_targets
        expr = f" {op} ".join(resolve(t, op) for t in merged_targets)

    if parent_op and parent_op != op:
        return f"({expr})"

    return expr

def _extract_constraintsfull(nodes: List[Dict[str, Any]], relationships: List[Dict[str, Any]] = None) -> List[str]:
    if relationships is None:
        relationships = []

    generated_constraints = []
    seen_disjoints = set()
    seen_equals = set()
    node_map = {n.get("id"): n for n in nodes if "id" in n}

    # 1. VINCOLI SUI NODI (Identifier, Unique, Property Value, Disjoint)
    for node in nodes:
        node_var = node.get("original_type_name", f"{node.get('caption', 'unknown').lower()}Type")
        alias = "x"

        # A. Properties (Identifier e Unique)
        for prop_name, prop_data in node.get("properties", {}).items():
            if prop_data.get("requiredType") == "identifier":
                generated_constraints.append(f"FOR ({alias}: {node_var}) EXCLUSIVE MANDATORY SINGLETON {alias}.{prop_name}")
            elif prop_data.get("unique") is True:
                generated_constraints.append(f"FOR ({alias}: {node_var}) EXCLUSIVE {alias}.{prop_name}")

        # B. Constraints Array (Value & Disjoint)
        for constraint in node.get("constraints", []):
            c_type = constraint.get("type")

            if c_type == "property_value":
                prop = constraint.get("on")
                op = constraint.get("operator")
                val = constraint.get("value")
                formatted_val = f"'{val}'" if isinstance(val, str) else val
                generated_constraints.append(f"FOR ({alias}: {node_var}) MANDATORY {alias}.{prop} {op} {formatted_val}")

            elif c_type == "disjoint":
                target_caption = constraint.get("node")
                target_var = _find_original_type_by_caption(nodes, target_caption, fallback=f"{str(target_caption).lower()}Type")
                pair = tuple(sorted([node_var, target_var]))
                if pair not in seen_disjoints:
                    seen_disjoints.add(pair)
                    generated_constraints.append(f"FOR ({alias}: {node_var}) MANDATORY ({alias}: !{target_var})")

            elif c_type == "equal":
                prop = constraint.get("on")
                
                if node.get("note") == "reified" and prop in ["source", "target"]:
                    continue

                target_val = constraint.get("target") 
                
                if target_val and "." in target_val:
                    target_caption, target_prop = target_val.split(".", 1)
                    
                    # Recuperiamo la variabile del nodo target
                    target_var = _find_original_type_by_caption(nodes, target_caption, fallback=f"{target_caption.lower()}Type")
                    
                    alias_target = "y"
                    pair = tuple(sorted([f"{node_var}.{prop}", f"{target_var}.{target_prop}"]))
                    if pair not in seen_equals:
                        seen_equals.add(pair)
                        generated_constraints.append(f"FOR ({alias}: {node_var}) MANDATORY {alias_target}.{target_prop} WITHIN ({alias_target}: {target_var}) WHERE {alias_target}.{target_prop} = {alias}.{prop}")
            
    # 2. VINCOLI DI PROPRIETÀ SULLE RELAZIONI (es. OwnsShares percentage > 0)
    for rel in relationships:
        if "constraints" in rel:
            rel_var = rel.get("original_type_name", f"{rel.get('type', 'unknown').lower()}Type")
            alias = "x"
            for constraint in rel.get("constraints", []):
                if constraint.get("type") == "property_value":
                    prop = constraint.get("on")
                    op = constraint.get("operator")
                    val = constraint.get("value")
                    formatted_val = f"'{val}'" if isinstance(val, str) else val
                    generated_constraints.append(f"FOR ({alias}: {rel_var}) MANDATORY {alias}.{prop} {op} {formatted_val}")

    # 3. CARDINALITÀ SU RELAZIONI SEMPLICI (es. Owns, PlaceOfBirth)
    for rel in relationships:
        if rel.get("relationshipType") == "ASSOCIATION":
            min_c = rel.get("target_minimum_cardinality", 0)
            max_c = rel.get("target_maximum_cardinality", "N")
            
            quals = []
            if min_c == 1:
                quals.append("MANDATORY")
            if max_c == 1:
                quals.append("SINGLETON")

            if quals:
                src_node = node_map.get(rel.get("fromId"))
                if src_node:
                    src_var = src_node.get("original_type_name", f"{src_node.get('caption', 'unknown').lower()}Type")
                    rel_var = rel.get("original_type_name", f"{rel.get('type', 'rel').lower()}Type")
                    qual_str = " ".join(quals)
                    
                    # Stampiamo sempre e solo ->() per evitare forzature errate
                    generated_constraints.append(f"FOR (x: {src_var}) {qual_str} y WITHIN (x)-[y: {rel_var}]->()")

    # 4. CARDINALITÀ SU NODI REIFICATI (es. Bestie)
    for node in nodes:
        if node.get("note") == "reified":
            node_caption = node.get("caption", "")
            for c in node.get("constraints", []):
                if c.get("type") == "max_cardinality" and c.get("limit") == 1 and "source" in c.get("attributes", []):
                    # Risale alla relazione padre contenente questa reificazione
                    for rel in relationships:
                        if node_caption in rel.get("properties", {}):
                            src_node = node_map.get(rel.get("fromId"))
                            if src_node:
                                src_var = src_node.get("original_type_name", f"{src_node.get('caption', 'unknown').lower()}Type")
                                rel_var = rel.get("original_type_name", f"{rel.get('type', 'rel').lower()}Type")
                                generated_constraints.append(f"FOR (x: {src_var}) SINGLETON y WITHIN (x)-[y: {rel_var} & {node_caption}]->()")

    return generated_constraints

def dump_pgschema(pgs_schema: Dict[str, Any]) -> str:
    name = pgs_schema.get("name", "UntitledGraph")
    mode = pgs_schema.get("mode", "STRICT")
    imports = pgs_schema.get("imports", [])

    nodes = pgs_schema.get("nodes", [])
    abstract_nodes = pgs_schema.get("abstract_nodes", [])
    relationships = pgs_schema.get("relationships", [])
    constraints = pgs_schema.get("constraints", [])

    imports_str = ""
    if imports:
        imports_str = f" IMPORTS {imports[0]}"

    all_items = nodes + relationships + constraints

    output = []

    for statement in abstract_nodes:
        output.append(statement)

    output.append(f"CREATE GRAPH TYPE {name} {mode}{imports_str} {{")
    
    if all_items:
        indented_elements = [f"    {e}" for e in all_items]
        output.append(",\n".join(indented_elements))
        
    output.append("}")
    return "\n".join(output)

if __name__ == '__main__':
    import sys
    import json
    
    # Controlla se abbiamo passato il nome di un file da terminale
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            # Facciamo girare le funzioni e stampiamo il risultato!
            schema_dict = convert_internal_representation_to_pgschema_dict(json_data)
            final_text = dump_pgschema(schema_dict)
            print(final_text)
            
        except Exception as e:
            print(f"Errore durante l'elaborazione: {e}")
    else:
        print("Errore: Nessun file JSON fornito in input. Passa il nome del file da terminale.")