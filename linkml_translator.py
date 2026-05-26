verbose = False
test = False
detect=False
import sys
import numpy as np
import os
import yaml
import json
import pprint
pp = pprint.PrettyPrinter(depth=8, sort_dicts=False)
from pathlib import Path
import pickle
from typing import Dict, Any, Optional, Union, List, Tuple, Set


def load_ontologies_dict(
    pkl_path: str | Path = Path("ontologies") / "data_directory" / "ontologies_dict.pkl"
) -> dict[str, dict]:
    base_dir = Path(__file__).resolve().parent
    pkl_path = Path(pkl_path)
    if not pkl_path.is_absolute():
        pkl_path = base_dir / pkl_path

    def normalize_loaded_ontologies(raw_data: Any) -> dict[str, dict]:
        if isinstance(raw_data, dict):
            return {str(k).lower(): v for k, v in raw_data.items() if isinstance(v, dict)}

        if isinstance(raw_data, list):
            out: dict[str, dict] = {}
            for entry in raw_data:
                if isinstance(entry, dict) and entry.get("id"):
                    out[str(entry["id"]).lower()] = entry
            return out

        return {}

    try:
        with pkl_path.open("rb") as f:
            loaded = pickle.load(f)
        normalized = normalize_loaded_ontologies(loaded)
        if normalized:
            return normalized
    except (FileNotFoundError, OSError, pickle.UnpicklingError, EOFError, ValueError):
        pass

    json_path = pkl_path.with_name("ontologies.json")
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and isinstance(data.get("ontologies"), list):
            return {
                str(entry["id"]).lower(): entry
                for entry in data["ontologies"]
                if isinstance(entry, dict) and entry.get("id")
            }
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass

    return {}


# In[6]:


def set_onto_entry(onto_id, onto_name, onto_description, onto_namespace, onto_annotator):
    return {"id": onto_id, 
            "name": onto_name, 
            "description": onto_description,
            "namespace": onto_namespace, 
            "annotator": onto_annotator}


# In[7]:


def comma_string_to_list(value):
    if not isinstance(value, str):
        return value
    if "," not in value:
        #return value
        return [value] #se vogliamo una lista di un solo elemento come id_prefixes
    return [item.strip() for item in value.split(",") if item.strip()]

def fix_yaml_lists(data):
    KEYS_TO_FIX = {
        "id_prefixes",
        "annotators",
        "prompt.example",
        "prompt.examples",
        "example",
        "examples"
    }
    if isinstance(data, dict):
        for key, value in list(data.items()):
            if key in KEYS_TO_FIX:
                data[key] = comma_string_to_list(value)
            else:
                fix_yaml_lists(value)
    elif isinstance(data, list):
        for item in data:
            fix_yaml_lists(item)
    return data

def fix_yaml(yaml_content):
    data = yaml.safe_load(yaml_content)
    fixed_data = fix_yaml_lists(data)
    return fixed_data


def load_yaml_source(yaml_input):
    if isinstance(yaml_input, (dict, list)):
        return yaml_input

    if hasattr(yaml_input, "read"):
        return yaml.safe_load(yaml_input.read())

    if isinstance(yaml_input, (str, os.PathLike)):
        try:
            yaml_path = Path(yaml_input)
            if yaml_path.exists() and yaml_path.is_file():
                with yaml_path.open("r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
        except (OSError, TypeError, ValueError):
            pass

        return yaml.safe_load(str(yaml_input))

    raise TypeError(
        f"Unsupported YAML input type: {type(yaml_input).__name__}. Expected str, path, dict/list, or file-like object."
    )


# In[8]:


### non serve più?
def collect_ontologies_from_yaml(yaml_file, ontodictk):
    data = load_yaml_source(yaml_file)
    #print('data:',data)
    ontok = set()
    ontomis = set()
    # Per sicurezza trasformiamo le chiavi in minuscolo
    ontodictk = {key.lower() for key in ontodictk}
    #print('ontodictk:',ontodictk)

    def normalize_id(value):
        return str(value).split(":")[-1].lower()

    def check_value(value):
        oid = normalize_id(value)
        if oid in ontodictk:
            ontok.add(oid)
        else:
            ontomis.add(oid)
    classes = data.get("classes", {})
    
    #print('classes:',classes)
    for class_name, class_data in classes.items():
        if not isinstance(class_data, dict):
            continue
        # Controlla id_prefixes
        for prefix in class_data.get("id_prefixes", []):
            check_value(prefix)
        # Controlla annotations -> annotators
        annotations = class_data.get("annotations", {})
        if isinstance(annotations, dict):
            for annotator in annotations.get("annotators", []):
                check_value(annotator)
    return [ontok, ontomis]


# In[9]:


def collect_ontologies_from_yaml2(yaml_file, ontodictk):
    data = load_yaml_source(yaml_file)
    #print('data:',data)
    ontok = set()
    ontomis = set()  
    ontodictbyc = {}
    # Per sicurezza trasformiamo le chiavi in minuscolo
    ontodictk = {key.lower() for key in ontodictk}
    #print('ontodictk:',ontodictk)

    def normalize_id(value):
        return str(value).split(":")[-1].lower()

    def check_value(value):
        oid = normalize_id(value)
        if oid in ontodictk:
            ontok.add(oid)
            ontoclass.add(oid)
        else:
            ontomis.add(oid)
            
    classes = data.get("classes", {})
    #print('classes:',classes)
    for class_name, class_data in classes.items():
        ontoclass = set()
        if not isinstance(class_data, dict):
            continue       
        # Controlla id_prefixes
        for prefix in class_data.get("id_prefixes", []):
            check_value(prefix)
        # Controlla annotations -> annotators
        annotations = class_data.get("annotations", {})
        if isinstance(annotations, dict):
            for annotator in annotations.get("annotators", []):
                check_value(annotator)
        ontodictbyc[class_name] = list(ontoclass)            
    return [ontok, ontomis, ontodictbyc]


# In[10]:


def collect_examples_from_yaml(yaml_file):
    data = load_yaml_source(yaml_file)
    #print('data:',data)
    spexample = set()
    ex_cases = ["prompt.example","prompt.examples","example","examples"]  
    exdictbyc = {}
    classes = data.get("classes", {})
    #print('classes:',classes)
    for class_name, class_data in classes.items():
        #exclass = set()
        if not isinstance(class_data, dict):
            continue
        annotations = class_data.get("annotations", {})
        if isinstance(annotations, dict):
            for exc in ex_cases:
                for ex in annotations.get(exc, []):
                    spexample.add(ex)    
        exdictbyc[class_name] = list(spexample)        
    return exdictbyc


# In[11]:


def collect_examples_from_dict(ann_dict):
    data = ann_dict
    spexample = set()
    ex_cases = ["prompt.example","prompt.examples","example","examples"]
    for exc in ex_cases:
        for ex in data.get(exc, []):
            spexample.add(ex)
    return list(spexample)


# In[12]:


def make_ontologies_entry(ontok, ontodict):
    ontologies = []
    ontokl = list(ontok)
    ontokl.sort()
    for i in range(len(ontokl)):
        el = ontodict.get(ontokl[i])
        if not el:
            continue
        onto_entry = set_onto_entry(el["id"],el["name"],el["description"],el["namespace"],el["annotator"])
        ontologies.append(onto_entry)
    return ontologies


# In[13]:


def doc_examples(excode):
    match excode:
        case "test_1":
            document = """
ToDo
"""
            return document       

def save_ex(excode):
    document = doc_examples(excode)
    doc = yaml.safe_load(document)
    yaml_string = yaml.safe_dump(doc, default_flow_style=False)
    json_string = json.dumps(doc, indent=4)
    with open(excode+".yaml", "w") as f:
        yaml.dump(doc, f, default_flow_style=False)
    yaml_object = yaml.safe_load(open(get_path_input_file(excode+'.yaml'), 'r'))
    json_object = convert(excode+'.yaml')
    fname = get_path_input_file(excode+'.json')
    with open(fname, 'r') as openfile:
        json_object = json.load(openfile)

def set_ex_case(setcode):
    match setcode:
        case 1:
            save_ex("test_1")
            current_case = "test_1.yaml"
            return current_case


# In[14]:


def load_yaml_data(yaml_content): # file_name with .yaml extension
    # qui devo creare fixed.yaml e usare questo TODO
    json_object = convert(yaml_content)
    return json_object

def yaml_to_json(yaml_content):
    # Accepts a YAML string, a Python dict/list, or a file-like object and
    # returns a JSON string.
    # If a dict/list is provided, just dump it to JSON.
    if isinstance(yaml_content, (dict, list)):
        return json.dumps(yaml_content, indent=4)

    # If it's a file-like object, read its contents
    if hasattr(yaml_content, "read"):
        yaml_str = yaml_content.read()
    else:
        yaml_str = yaml_content

    yaml_data = yaml.safe_load(yaml_str)
    return json.dumps(yaml_data, indent=4)

def convert(yaml_data):
    # Convert YAML input (string, dict/list, or file-like) to Python object.
    if isinstance(yaml_data, (dict, list)):
        return yaml_data

    if hasattr(yaml_data, "read"):
        yaml_str = yaml_data.read()
    else:
        yaml_str = yaml_data

    return yaml.safe_load(yaml_str)


def to_json_compatible(value):
    if isinstance(value, dict):
        return {k: to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_json_compatible(v) for v in value]
    if isinstance(value, tuple):
        return [to_json_compatible(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value

def get_path_input_file(file_name, subdir_name = None):
    if subdir_name:
        path_input_file = os.path.abspath(os.getcwd()) + "\\" + subdir_name + "\\" + file_name
    else:
        path_input_file = os.path.abspath(file_name)
    return path_input_file


# In[15]:


def initialize_positions(num_nodes, width, height, fixed_nodes=None):
    """Genera posizioni casuali iniziali per i nodi non fissi."""
    positions = np.random.rand(num_nodes, 2) * [width, height]
    if fixed_nodes is not None:
        for idx, coord in fixed_nodes.items():
            positions[idx] = coord  # Imposta le posizioni fisse
    return positions

def compute_repulsion(positions, repulsion_strength, node_radius, fixed_mask):
    """Calcola le forze di repulsione tra i nodi, considerando la loro dimensione."""
    num_nodes = len(positions)
    forces = np.zeros_like(positions)

    for i in range(num_nodes):
        if fixed_mask[i]:  # I nodi fissi non si spostano
            continue
        for j in range(num_nodes):
            if i == j:
                continue
            delta = positions[i] - positions[j]
            distance = np.linalg.norm(delta) + 1e-6  # Evita divisioni per zero
            min_distance = 4 * node_radius  # Distanza minima tra i centri dei nodi

            if distance < min_distance:  # Se troppo vicini, aumenta la repulsione
                force_magnitude = repulsion_strength / (distance ** 2) + 100
            else:
                force_magnitude = repulsion_strength / (distance ** 2)

            force_direction = delta / distance
            forces[i] += force_magnitude * force_direction

    return forces

def update_positions(positions, forces, width, height, fixed_mask):
    """Aggiorna le posizioni dei nodi basandosi sulle forze calcolate."""
    for i in range(len(positions)):
        if not fixed_mask[i]:  # I nodi fissi non si spostano
            positions[i] += forces[i]
    positions = np.clip(positions, 0, [width, height])  # Mantieni i nodi nell'area
    return positions

def calculate_node_positions(num_nodes, width=900, height=600, iterations=100, repulsion_strength=100, node_radius=50, fixed_nodes=None):
    """
    Genera posizioni per `num_nodes` nodi, permettendo di fissare alcune posizioni, evitando collisioni con i nodi fissi.
    Args:
        fixed_nodes (dict): Dizionario con {indice: [x, y]} per i nodi fissi.
    Returns:
        dict: Un dizionario con le coordinate x, y dei nodi.
    """
    if num_nodes <= 0:
        raise ValueError("Il numero di nodi deve essere maggiore di 0.")

    fixed_nodes = fixed_nodes or {}
    fixed_mask = np.array([i in fixed_nodes for i in range(num_nodes)])
    positions = initialize_positions(num_nodes, width, height, fixed_nodes)

    for _ in range(iterations):
        forces = compute_repulsion(positions, repulsion_strength, node_radius, fixed_mask)
        positions = update_positions(positions, forces, width, height, fixed_mask)

    return {i: {'x': positions[i, 0], 'y': positions[i, 1]} for i in range(num_nodes)}


# In[16]:


def key_exists(dictionary, key):
    return key in dictionary
    
def key_does_not_exist(dictionary, key):
    return key not in dictionary


# In[17]:


def set_node(id, caption, style, properties, description, position, onto):
    return {"id": id, 
            "caption": caption,
            "style": style,
            "properties": properties,  
            "description": description, 
            "position": position,
            "entityType": "node",
            "ontologies": onto, #[],
            "examples": []}

def set_node2(id, caption, style, properties, description, position, onto, ex):
    return {"id": id, 
            "caption": caption,
            "style": style,
            "properties": properties,  
            "description": description, 
            "position": position,
            "entityType": "node",
            "ontologies": onto, #[],
            "examples": ex} #[]}

def set_property(klist,vlist,ck):
    props_out = {}
    p = len(klist)
    for q in range(p):
        print(klist[q],vlist[q]) if test else None 
        props_out[klist[q]] = vlist[q]
    print('props_out:',props_out) if test else None
    r = props_out.get('range',False)
    rq = props_out.get('requiredType',False)
    if r:
        if r not in ck:
            reqv = props_out.get("required", False)
            if rq not in ['identifier']:
                props_out["requiredType"] = "required" if reqv else "optional"      
    print('props_out:',props_out) if test else None
    return props_out

def set_metadata(klist, vlist, exclude=None):
    mdata = {}
    p = len(klist)
    #print(p)
    for q in range(p):
        #print(klist[q],vlist[q]) if verbose else None 
        if (klist[q] != exclude):
            mdata[klist[q]] = vlist[q]
    return mdata


# In[18]:


def get_node_captions(ndata):
        ncaps = set()
        for node in ndata.get('nodes', []):
            if node.get('caption'):
                ncaps.add(node.get('caption'))
        return ncaps


# In[19]:


def get_class_names(json_obj):
    return list(json_obj["classes"].keys()) 
    
def get_class_attr_names(class_name, json_obj):
    return list(json_obj["classes"][class_name]["attributes"].keys())  
    
def get_class_attr_name_field_keys(class_name, attr_name, json_obj):
    return list(json_obj["classes"][class_name]["attributes"][attr_name].keys())    
    
def get_class_attr_name_field_vals(class_name, attr_name, json_obj):
    return list(json_obj["classes"][class_name]["attributes"][attr_name].values())   
    
def get_class_attr_name_field_val(class_name, attr_name, fname, json_obj):
    return str(json_obj["classes"][class_name]["attributes"][attr_name][fname])

def find_node_by_caption(data, caption):
    for node in data.get('nodes', []):
        if node.get('caption') == caption:
            return node
    return None

def str_to_bool(s):
    return s.lower() == "true"


# In[20]:


def filter_dict_by_value_type(data, mode):
    """
    Filters a dictionary based on the type of its nested values.
    
    Parameters:
    - data (dict): The input dictionary.
    - mode (int): If 1, return items where nested values are NOT lists.
                  If 2, return items where nested values ARE lists.
    
    Returns:
    - dict: Filtered dictionary.
    """
    result = {}
    for key, subdict in data.items():
        if isinstance(subdict, dict):
            filtered_subdict = {
                k: v for k, v in subdict.items()
                if (mode == 1 and not isinstance(v, list)) or
                   (mode == 2 and isinstance(v, list))
            }
            if filtered_subdict:
                result[key] = filtered_subdict
    return result


# In[21]:


def insert_into_dict(d, dkey, dvalue):
    if dkey not in d:
        d[dkey] = dvalue
    elif isinstance(d[dkey], list):
        d[dkey].append(dvalue)
    else:
        d[dkey] = [d[dkey], dvalue]

def get_refs_to(json_obj):
    refs_to = {}
    n = get_class_names(json_obj)
    for i in range(len(n)):
        if('attributes' in json_obj["classes"][n[i]].keys()):
            nprops = get_class_attr_names(n[i],json_obj)   #list(json_object["classes"][n[i]]["attributes"].keys())
            #print(nprops)
            for j in range(len(nprops)):
                r_to = get_class_attr_name_field_val(n[i],nprops[j], 'range',json_obj)
                #print(r_to)
                if ((r_to in n) and not(str_to_bool(get_class_attr_name_field_val(n[i],nprops[j], 'inlined',json_obj)))): # we consider only inlined false
                    if (n[i] in refs_to.keys()): 
                        #refs_to[n[i]][r_to] = nprops[j]
                        insert_into_dict(refs_to[n[i]], r_to, nprops[j])
                    else:
                        #refs_to[n[i]] = {r_to: nprops[j]}    
                        refs_to[n[i]] = {}
                        insert_into_dict(refs_to[n[i]], r_to, nprops[j])
    return refs_to

def get_refs_to_i(json_obj):
    refs_to_i = {}
    n = get_class_names(json_obj)
    for i in range(len(n)):
        if('attributes' in json_obj["classes"][n[i]].keys()):
            nprops = get_class_attr_names(n[i],json_obj)   #list(json_object["classes"][n[i]]["attributes"].keys())
            #print(nprops)
            for j in range(len(nprops)):
                r_to_i = get_class_attr_name_field_val(n[i],nprops[j], 'range',json_obj)
                #print(r_to)
                if ((r_to_i in n) and (str_to_bool(get_class_attr_name_field_val(n[i],nprops[j], 'inlined',json_obj)))): # we consider only inlined true
                    if (n[i] in refs_to_i.keys()): 
                        #refs_to_i[n[i]][r_to_i] = nprops[j]
                        insert_into_dict(refs_to_i[n[i]], r_to_i, nprops[j])
                    else:
                        #refs_to_i[n[i]] = {r_to_i: nprops[j]}    
                        refs_to_i[n[i]] = {}
                        insert_into_dict(refs_to_i[n[i]], r_to_i, nprops[j])
    return refs_to_i

def get_referred_by(refs_to):
    referred_by = {}
    k = list(refs_to.keys())
    #print('k',k)
    k_vals = list(refs_to.values())
    #print('k_vals',k_vals)
    for i in range(len(k)): 
        #print(k[i])
        for j in range(len(k_vals[i])):
            #print(k_vals[i])
            #print(list(k_vals[i].keys())[j], 'referred by', k[i], 'using', list(k_vals[i].values())[j])
            this_class = list(k_vals[i].keys())[j]
            r_by = k[i]
            by_prop = list(k_vals[i].values())[j]
            if (this_class in referred_by.keys()): 
                referred_by[this_class][r_by] = by_prop
            else:
                referred_by[this_class] = {r_by: by_prop}
    return referred_by 

def get_referred_by_i(refs_to_i):
    referred_by_i = {}
    k = list(refs_to_i.keys())
    #print('k',k)
    k_vals = list(refs_to_i.values())
    #print('k_vals',k_vals)
    for i in range(len(k)): 
        #print(k[i])
        for j in range(len(k_vals[i])):
            #print(k_vals[i])
            #print(list(k_vals[i].keys())[j], 'referred by', k[i], 'using', list(k_vals[i].values())[j])
            this_class = list(k_vals[i].keys())[j]
            r_by_i = k[i]
            by_prop = list(k_vals[i].values())[j]
            if (this_class in referred_by_i.keys()): 
                referred_by_i[this_class][r_by_i] = by_prop
            else:
                referred_by_i[this_class] = {r_by_i: by_prop}
    return referred_by_i   

def get_not_ref_attr(json_obj,refs_to_keys):
    not_ref_attr = {}
    n = get_class_names(json_obj)
    #print(n)
    for i in range(len(n)):
        #print(n[i])
        if('attributes' in json_obj["classes"][n[i]].keys()):
            nprops = get_class_attr_names(n[i],json_obj)   #list(json_object["classes"][n[i]]["attributes"].keys())
            #print(nprops)
            for j in range(len(nprops)):
                r_to = get_class_attr_name_field_val(n[i],nprops[j], 'range',json_obj)
                #print(r_to)
                if ((r_to not in n) and (n[i] in refs_to_keys)): # we consider only inlined false
                    if (n[i] in not_ref_attr.keys()): 
                        not_ref_attr[n[i]][nprops[j]] = r_to
                    else:
                        not_ref_attr[n[i]] = {nprops[j]: r_to}    
    return not_ref_attr


# In[22]:


def del_ref(ref_dict,ref_key,int_key=None):
    if len(ref_dict[ref_key]) == 0: # == {}
        del ref_dict[ref_key]
    else:
        if int_key: # the internal key of the element to be deleted
            del ref_dict[ref_key][int_key]
        else: # you want delete the element and all its internal elements
            del ref_dict[ref_key]
    return ref_dict

def group_keys_by_value_length(input_dict):
    result = {}
    for key, value in input_dict.items():
        length = len(value)
        group_key = length if length < 3 else 3
        result.setdefault(group_key, []).append(key)
    return result

def find_key_index(key_list, target_key):
    try:
        return key_list.index(target_key)
    except ValueError:
        return None


# In[23]:


def set_isa_relationship(id, fromId, toId):
    return {#"entityType": entityType, 
            "id": id, 
            "fromId": fromId, 
            "toId": toId,
            "relationshipType": "INHERITANCE", 
            "entityType": "relationship",
            "style": {}, 
            "properties": {}}


# In[24]:


def set_relationship(id, type, fromId, toId):
    return {#"entityType": entityType, 
            "id": id, 
            "type": type, 
            "fromId": fromId, 
            "toId": toId,
            "relationshipType": "ASSOCIATION", 
            "entityType": "relationship",
            "style": {}, 
            "properties": {}, 
            #"cardinality": "",
            "source_minimum_cardinality": 0, # required false
            "source_maximum_cardinality": 1, # multivalued false
            "target_minimum_cardinality": 0,
            "target_maximum_cardinality": "N",
            "description": "",
            "ontologies": [],
            "examples": []}

def set_relationship2(id, type, fromId, toId, ex):
    return {#"entityType": entityType, 
            "id": id, 
            "type": type, 
            "fromId": fromId, 
            "toId": toId,
            "relationshipType": "ASSOCIATION", 
            "entityType": "relationship",
            "style": {}, 
            "properties": {}, 
            #"cardinality": "",
            "source_minimum_cardinality": 0, # required false
            "source_maximum_cardinality": 1, # multivalued false
            "target_minimum_cardinality": 0,
            "target_maximum_cardinality": "N",
            "description": "",
            "ontologies": [],
            "examples": ex} #[]}


# In[25]:


def set_node_id():
    return {"description": "",
             "requiredType": "identifier",
             "range": "string"}


# In[26]:


# NB nodes' captions are UNIQUE?
def nodeid_by_caption(nlist, caption):
    nodeid = False
    for k in range(len(nlist)):
        if nlist[k]["caption"] == caption:
            nodeid = nlist[k]["id"]
            return nodeid
    return nodeid

def find_position_by_id(entity_list, entity_id):
    for i in range(len(entity_list)):
        if entity_list[i].get('id') == entity_id:
            return i
    return None  # If entity_id is not found

def check_size(container,element,threshold=1):
    try:
        size = len(container)
        #print(f"Container's size: {size}")
        if size > threshold:
            raise ValueError(f"{element} could be inline referred only by one node")
    except ValueError as e:
        print(f"Exception: {e}")



def normalize_inlined_attributes(repr_dict):
    """
    Per ogni attributo con:
      - inlined == True
      - range uguale al caption di una classe/nodo

    applica queste trasformazioni:
      - sostituisce "required" con "requiredType":
            "required" se required == True
            "optional" altrimenti
      - aggiunge "collectionType": "list" se multivalued == True
      - rimuove: required, multivalued, inlined_as_list

    La trasformazione viene applicata:
      - alle properties dei nodes
      - alle properties annidate dentro le relationships
      - ad eventuali dict annidati ricorsivamente
    """
    class_names = {
        node["caption"]
        for node in repr_dict.get("nodes", [])
        if "caption" in node
    }

    def is_class_range(attr_dict):
        return (
            isinstance(attr_dict, dict)
            and attr_dict.get("inlined") is True
            and attr_dict.get("range") in class_names
        )
    
    def is_c_range(attr_dict):
        return (
            isinstance(attr_dict, dict)
            and attr_dict.get("range") in class_names
        )

    def transform_attribute(attr_dict):
        required_value = attr_dict.get("required", False)
        attr_dict["requiredType"] = "required" if required_value else "optional"

        if attr_dict.get("multivalued") is True:
            #attr_dict["collectionType"] = "list"
            ec = attr_dict.get("exact_cardinality", False)
            minc = attr_dict.get("minimum_cardinality", False)
            maxc = attr_dict.get("maximum_cardinality", False)
            if (ec or minc or maxc):       
                print(ec,minc,maxc) if verbose else None
                attr_dict["collectionType"] = "array"
                #adim = get_a_dim(ec,minc,maxc)
                attr_dict["minDimensions"] = 0
                attr_dict["maxDimensions"] = 'N'
                if (maxc and (not minc) and (not ec)): # solo max
                    if(maxc > 0):
                        attr_dict["maxDimensions"] = maxc
                    else:
                        attr_dict["collectionType"] = "list"
                if (minc and (not maxc) and (not ec)): # solo min
                    if(minc > 0):
                        attr_dict["minDimensions"] = minc
                    else:
                        attr_dict["collectionType"] = "list"
                #if (ec and (not maxc) and (not minc)): # solo ec
                if (ec): # ec vince
                    if(ec > 0):
                        attr_dict["minDimensions"] = ec
                        attr_dict["maxDimensions"] = ec
                    else:
                        attr_dict["collectionType"] = "list"
                if (maxc and minc and (not ec)): # solo min e max
                    if((minc > maxc) or (maxc < minc) or (minc < 0) or (maxc < 1)):
                        attr_dict["minDimensions"] = minc
                        attr_dict["maxDimensions"] = maxc   
                    else:
                        attr_dict["collectionType"] = "list"
            else:
                attr_dict["collectionType"] = "list"
                
        attr_dict.pop("required", None)
        attr_dict.pop("multivalued", None)
        attr_dict.pop("inlined", None)
        attr_dict.pop("inlined_as_list", None)
        attr_dict.pop("exact_cardinality", None)
        attr_dict.pop("minimum_cardinality", None)
        attr_dict.pop("maximum_cardinality", None)        

    def visit(obj):
        if isinstance(obj, dict):
            # se questo dict è un attributo target, trasformalo
            if is_class_range(obj):
                transform_attribute(obj)

            if is_c_range(obj):
                obj.pop("identifier", None)

            # continua la visita ricorsiva
            for value in obj.values():
                visit(value)

        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    visit(repr_dict)
    return repr_dict

# In[28]:


def save_file(file_name, repr, repr_type="i", subdir_name = None):
    if repr_type == "i":
        if subdir_name:
            fname = os.path.abspath(os.getcwd()) + "\\" + subdir_name + "\\" + file_name + "_internal_representation.json"
        else:
            fname = os.path.abspath(os.getcwd()) +  "\\" + file_name + "_internal_representation.json"
    else:
        if subdir_name:
            fname = os.path.abspath(os.getcwd()) + "\\" + subdir_name + "\\" + file_name + "_visual_representation.json"
        else:
            fname = os.path.abspath(os.getcwd()) +  "\\" + file_name + "_visual_representation.json"
    #print(fname)
    with open(fname, "w") as file:
        json.dump(repr,file, indent=4)

def get_visualization(repr):
    my_copy = repr.copy()
    mk = list(my_copy["metadata"].keys())
    mv = list(my_copy["metadata"].values())
    exclude_list = [] # QUALI CAMPI METADATA DEVONO ESSERE ESCLUSI?
    #print(mk,mv,exclude_list) if test else None
    for t in range(len(mk)):
        if(mk[t] not in exclude_list):
            my_copy[mk[t]] = repr["metadata"][mk[t]]
    #my_copy["style"] = repr["metadata"]["style"] # general style
    #my_copy["description"] = repr["metadata"]["description"] # schema description
    #my_copy["license"] = "https://creativecommons.org/publicdomain/zero/1.0/" # schema license
    # diagram name is not stored
    del my_copy["metadata"]
    #return json.dumps(my_copy, indent=4)
    my_copy = normalize_inlined_attributes(my_copy)
    return my_copy


# In[29]:


def init_translation(json_object,obyc,ebyc):
    classesk = json_object['classes'].keys()
    print(classesk) if test else None
    d_style={ 
    "font-family": "sans-serif",
    "background-color": "#ffffff",
    "background-image": "",
    "background-size": "100%",
    "class-color": "#ffffff",
    "border-width": 4,
    "border-color": "#000000",
    "radius": 50,
    "class-padding": 5,
    "class-margin": 2,
    "outside-position": "auto",
    "class-icon-image": "",
    "class-background-image": "",
    "icon-position": "inside",
    "icon-size": 64,
    "class-name-position": "inside",
    "class-name-max-width": 200,
    "class-name-color": "#000000",
    "class-name-font-size": 50,
    "class-name-font-weight": "normal",
    "label-position": "inside",
    "label-display": "pill",
    "label-color": "#000000",
    "label-background-color": "#ffffff",
    "label-border-color": "#000000",
    "label-border-width": 4,
    "label-font-size": 40,
    "label-padding": 5,
    "label-margin": 4,
    "detail-position": "inline",
    "detail-orientation": "parallel",
    "arrow-width": 5,
    "arrow-color": "#000000",
    "margin-start": 5,
    "margin-end": 5,
    "margin-peer": 20,
    "attachment-start": "normal",
    "attachment-end": "normal",
    "relationship-icon-image": "",
    "type-color": "#000000",
    "type-background-color": "#ffffff",
    "type-border-color": "#000000",
    "type-border-width": 0,
    "type-font-size": 16,
    "type-padding": 5,
    "attribute-position": "outside",
    "attribute-alignment": "colon",
    "attribute-color": "#000000",
    "attribute-font-size": 16,
    "attribute-font-weight": "normal"
    }
    d_out = {
    "metadata": [],
    "nodes": [],
    "relationships": []
    }
    if key_exists(json_object,"metadata"):
        d_out["metadata"] = json_object["metadata"]
        if key_does_not_exist(json_object["metadata"],"style"):
            d_out["metadata"]["style"] = d_style
    else:
        mattrs = list(json_object.keys())
        mvals = list(json_object.values())
        d_out["metadata"] = set_metadata(mattrs,mvals,"classes")
        if key_does_not_exist(json_object,"style"):
            d_out["metadata"]["style"] = d_style
    n = list(json_object["classes"].keys())
    print(n) if verbose else None
    num_nodes = len(n)
    positions = calculate_node_positions(num_nodes)
    for i in range(len(n)):
        class_children = json_object["classes"][n[i]].keys()
        print('class_children:',class_children) if verbose else None
        if ('description' in class_children):
            #d_out["nodes"].append(set_node("n" + str(i),n[i],{},{},json_object["classes"][n[i]]["description"],positions[i],obyc[n[i]]))
            d_out["nodes"].append(set_node2("n" + str(i),n[i],{},{},json_object["classes"][n[i]]["description"],positions[i],obyc[n[i]],ebyc[n[i]]))
        else:
            #d_out["nodes"].append(set_node("n" + str(i),n[i],{},{},'',positions[i],obyc[n[i]]))
            d_out["nodes"].append(set_node2("n" + str(i),n[i],{},{},'',positions[i],obyc[n[i]],ebyc[n[i]]))
        # RIEMPIRE ONTOLOGIE ED ESEMPI PER NODI
        if ('attributes' in class_children):
            nprops = list(json_object["classes"][n[i]]["attributes"].keys())
            for j in range(len(nprops)):
                nattrs = list(json_object["classes"][n[i]]["attributes"][nprops[j]].keys())
                nvals = list(json_object["classes"][n[i]]["attributes"][nprops[j]].values())
                print('nprops[j]:',nprops[j],'nattrs:',nattrs,'nvals:',nvals) if verbose else None
                print('---',nprops[j],nattrs,nvals) if verbose else None
                d_out["nodes"][i]["properties"][nprops[j]] = set_property(nattrs,nvals,classesk)       
        if (('is_a' in class_children) and (json_object["classes"][n[i]]["is_a"] not in ["NamedEntity","namedEntity","Namedentity","namedentity"])):
            d_out["nodes"][i]["is_a"] = json_object["classes"][n[i]]["is_a"]
        if ('mixins' in class_children):
            d_out["nodes"][i]["mixins"] = json_object["classes"][n[i]]["mixins"]
    return(d_out)


# In[30]:


def get_rel_card(array_dict):
    card = {}
    if("exact_cardinality" in array_dict): 
        card["source_minimum_cardinality"] = array_dict["exact_cardinality"]
        card["source_maximum_cardinality"] = array_dict["exact_cardinality"]    
    else:
        card["source_minimum_cardinality"] = array_dict["minimum_cardinality"]
        card["source_maximum_cardinality"] = array_dict["maximum_cardinality"]                                                
    return card


# In[31]:


def transform_case_1_1(subset_node, int_repr,referred_caption,referred_val,idr): 
    print('START FUNCTION -> transform_case_1_1') if (verbose or detect) else None
    #source_card = True
    snprops = list(subset_node["properties"][referred_val].keys())
    print('snprops:',snprops)  if verbose else None
    rel_id = "n"+str(idr) 
    from_node = subset_node["id"]
    to_node = nodeid_by_caption(int_repr["nodes"],referred_caption) #
#    to_node = subset_node["properties"][referred_val]["range"])
    print('rel_id:',rel_id,'from_node',from_node,'--- to_node',to_node, ' --- snprops:', snprops) if verbose else None
    type = referred_val
    print('type:',type) if verbose else None
    #print('rel_id:',rel_id,'from_node',from_node,'--- to_node',to_node, ' --- snprops:', snprops) if verbose else None
    int_repr["relationships"].append(set_relationship(rel_id,type,from_node,to_node)) # imposta "source_minimum_cardinality": 0 e "source_maximum_cardinality": 1
    pos_rel = find_position_by_id(int_repr["relationships"],rel_id)
    if subset_node["properties"][referred_val].get("required"):
        int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=1
    if subset_node["properties"][referred_val].get("multivalued"):
        int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
    for j in range(len(snprops)):
        #if (snprops[j]!="range"):
        if (snprops[j] not in ["range","inlined","required","multivalued","dict_card","annotations"]):
            int_repr["relationships"][pos_rel][snprops[j]] = subset_node["properties"][referred_val][snprops[j]]
        if (snprops[j] in ["dict_card"]):
            array_d = subset_node["properties"][referred_val][snprops[j]]
            acard = {}
            #acard = get_array_card(array_d)
            acard = get_rel_card(array_d)
            print(acard) if verbose else None
            int_repr["relationships"][pos_rel]["source_minimum_cardinality"] = acard["source_minimum_cardinality"]
            int_repr["relationships"][pos_rel]["source_maximum_cardinality"] = acard["source_maximum_cardinality"]
        if (snprops[j] in ["annotations"]):
            #print('###1',snprops[j])
            #print('###2',subset_node["properties"][referred_val][snprops[j]])
            #print('###3',collect_examples_from_dict(subset_node["properties"][referred_val][snprops[j]]))
            # POSSONO ESSERCI ONTOLOGIE?
            int_repr["relationships"][pos_rel]['examples'] = collect_examples_from_dict(subset_node["properties"][referred_val][snprops[j]]) #collect_examples_from_dict(int_repr["relationships"][pos_rel][snprops[j]])
    int_repr["relationships"][pos_rel]["navigation"] = "Directional"
    #del int_repr["nodes"][i]["properties"][referred_val]
    print('int_repr["relationships"][pos_rel]:',int_repr["relationships"][pos_rel]) if verbose else None
    pos_node = find_position_by_id(int_repr["nodes"],subset_node["id"])
    del int_repr["nodes"][pos_node]["properties"][referred_val] # cancello il caso referred_val: a 
    print('END FUNCTION -> transform_case_1_1') if (verbose or detect) else None
    return int_repr


# In[32]:


def test_card_case_5_1(current_node_vals,current_node_caption, int_repr): # deve essere 1,1 per trasformare la clase in relazione
    current_node_data = find_node_by_caption(int_repr, current_node_caption)
    cnprops = list(current_node_vals.values())
    for i in range(len(cnprops)):
        if current_node_data["properties"][cnprops[i]].get("required"):
            s_i_min=1
        else:
            return False
        if not current_node_data["properties"][cnprops[i]].get("multivalued"):
            s_i_max=1
        else:
            return False
    return True


# In[33]:


def transform_case_5_1(current_node_vals,current_node_data, int_repr,idr,reif=True): #case 5_1
    print('START FUNCTION -> transform_case_5_1') if (verbose or detect) else None
    pos_node = find_position_by_id(int_repr["nodes"],current_node_data["id"])
    if(reif):
        int_repr["nodes"][pos_node]["reification"] = True
        int_repr["nodes"][pos_node]["style"]["border-color"] = "#d33115"
    cnprops = list(current_node_vals.values())
    for i in range(len(cnprops)):
        #print(i,cnprops[i],current_node_data["properties"][cnprops[i]])
        rel_id = "n"+str(idr)
        #from_node = nodeid_by_caption(int_repr["nodes"],current_node_data["properties"][cnprops[i]]["range"])
        #to_node = current_node_data["id"]
        from_node = current_node_data["id"] 
        to_node = nodeid_by_caption(int_repr["nodes"],current_node_data["properties"][cnprops[i]]["range"])
        print('rel_id:',rel_id,'from_node',from_node,'--- to_node',to_node, ' --- cnprops:', cnprops) if verbose else None
        type = cnprops[i]
        int_repr["relationships"].append(set_relationship(rel_id,type,from_node,to_node))
        #print(set_relationship(rel_id,type,from_node,to_node))
        pos_rel = find_position_by_id(int_repr["relationships"],rel_id)
        if current_node_data["properties"][cnprops[i]].get("required"):
            int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=1
        if current_node_data["properties"][cnprops[i]].get("multivalued"):
            int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
        scnprops = list(current_node_data["properties"][cnprops[i]].keys())
        for j in range(len(scnprops)):
            #if (scnprops[j]!="range"):
            if (scnprops[j] not in ["range","inlined","required","multivalued","dict_card","annotations"]):
                int_repr["relationships"][pos_rel][scnprops[j]] = current_node_data["properties"][cnprops[i]][scnprops[j]]
            if (scnprops[j] in ["dict_card"]):
                array_d = current_node_data["properties"][cnprops[i]][scnprops[j]]
                acard = {}
                #acard = get_array_card(array_d)
                acard = get_rel_card(array_d)
                print(acard) if verbose else None
                int_repr["relationships"][pos_rel]["source_minimum_cardinality"] = acard["source_minimum_cardinality"]
                int_repr["relationships"][pos_rel]["source_maximum_cardinality"] = acard["source_maximum_cardinality"]
            if (scnprops[j] in ["annotations"]):
                # POSSONO ESSERCI ONTOLOGIE?
                int_repr["relationships"][pos_rel]['examples'] = collect_examples_from_dict(current_node_data["properties"][cnprops[i]][scnprops[j]]) #int_repr["relationships"][pos_rel][scnprops[j]])
#        int_repr["relationships"][pos2]['relationshipType'] = 'REIFICATION' # PROPOSTA!
        #print(int_repr["relationships"][pos2])
#        if current_node_data["properties"][cnprops[i]].get("required"):
#            int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=1
#        if current_node_data["properties"][cnprops[i]].get("multivalued"):
#            int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
        int_repr["relationships"][pos_rel]["navigation"] = "Directional"
        del int_repr["nodes"][pos_node]["properties"][cnprops[i]]
        idr+=1
    print('END FUNCTION -> transform_case_5_1') if (verbose or detect) else None
    return [int_repr, idr]


# In[34]:


def get_subset_node_info(int_repr, current_node_caption,referred_val):
    current_node_data = find_node_by_caption(int_repr, current_node_caption)
    subset_node = {key: current_node_data[key] for key in ('id', 'caption')}
    subset_node['properties'] = {referred_val: current_node_data['properties'][referred_val]}
    #print('subset_node:',subset_node)
    return subset_node


# In[35]:


def transform_case_1_4(subset_node, subset_node2,  int_repr, referred_val, idr): # case 1_4
    print('START FUNCTION -> transform_case_1_4') if (verbose or detect) else None
    snprops = list(subset_node["properties"][referred_val].keys())
    snprops2 = list(subset_node2["properties"][referred_val].keys())
    print('snprops:', snprops) if verbose else None
    print('snprops2:', snprops2) if verbose else None
    referred_caption = subset_node["properties"][referred_val]["range"]
    rel_id = "n"+str(idr) 
    from_node = subset_node['id']
    to_node = subset_node2['id']#subset_node["properties"][referred_val]["range"])
    print('rel_id:',rel_id,'from_node',from_node,'--- to_node',to_node, ' --- snprops:', snprops) if verbose else None
    type = referred_val
    int_repr["relationships"].append(set_relationship(rel_id,type,from_node,to_node))  
    pos_rel = find_position_by_id(int_repr["relationships"],rel_id)
    #int_repr["nodes"][pos]["navigation"] = "none"
    if subset_node["properties"][referred_val].get("required"):
        int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=1
    if subset_node["properties"][referred_val].get("multivalued"):
        int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
    if subset_node2["properties"][referred_val].get("required"):
        int_repr["relationships"][pos_rel]["target_minimum_cardinality"]=1
    if not subset_node2["properties"][referred_val].get("multivalued"):
        int_repr["relationships"][pos_rel]["target_maximum_cardinality"]=1
    for j in range(len(snprops)):
        #if (snprops[j]!="range"):
        if (snprops[j] not in ["range","inlined","required","multivalued","dict_card","description","annotations"]):
            int_repr["relationships"][pos_rel][snprops[j]] = subset_node["properties"][referred_val][snprops[j]]
        if (snprops[j] in ["description"]):
            int_repr["relationships"][pos_rel]["properties"]["description_from"] = subset_node["properties"][referred_val][snprops[j]]
        if (snprops[j] in ["dict_card"]):
            array_d = subset_node["properties"][referred_val][snprops[j]]
            acard = {}
            #acard = get_array_card(array_d)
            acard = get_rel_card(array_d)
            print(acard) if verbose else None
            int_repr["relationships"][pos_rel]["source_minimum_cardinality"] = acard["source_minimum_cardinality"]
            int_repr["relationships"][pos_rel]["source_maximum_cardinality"] = acard["source_maximum_cardinality"]
        if (snprops[j] in ["annotations"]):
            # POSSONO ESSERCI ONTOLOGIE?
            int_repr["relationships"][pos_rel]['examples'] = collect_examples_from_dict(subset_node["properties"][referred_val][snprops[j]]) #int_repr["relationships"][pos_rel][snprops[j]])
    for j2 in range(len(snprops2)):
        #if (snprops[j]!="range"):
        if (snprops2[j2] not in ["range","inlined","required","multivalued","dict_card","description","annotations"]):# DA TENERE O COMMENTARE?
            int_repr["relationships"][pos_rel][snprops[j2]] = subset_node2["properties"][referred_val][snprops[j2]]
        if (snprops2[j2] in ["description"]):
            int_repr["relationships"][pos_rel]["properties"]["description_to"] = subset_node2["properties"][referred_val][snprops[j2]]
        if (snprops2[j2] in ["dict_card"]):
            array_d2 = subset_node2["properties"][referred_val][snprops[j2]]
            acard2 = {}
            #acard = get_array_card(array_d)
            acard2 = get_rel_card(array_d2)
            print(acard2) if verbose else None
            int_repr["relationships"][pos_rel]["target_minimum_cardinality"] = acard2["source_minimum_cardinality"]
            int_repr["relationships"][pos_rel]["target_maximum_cardinality"] = acard2["source_maximum_cardinality"]
        if (snprops2[j2] in ["annotations"]):
            # POSSONO ESSERCI ONTOLOGIE?
            int_repr["relationships"][pos_rel]['examples'] += collect_examples_from_dict(subset_node2["properties"][referred_val][snprops[j2]]) #int_repr["relationships"][pos_rel][snprops[j2]])
            #DEVE DIVENTARE SET?
            int_repr["relationships"][pos_rel]['examples'] = list(set(int_repr["relationships"][pos_rel]['examples']))
#    if subset_node["properties"][referred_val].get("required"):
#        int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=1
#    if subset_node["properties"][referred_val].get("multivalued"):
#        int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
#    if subset_node2["properties"][referred_val].get("required"):
#        int_repr["relationships"][pos_rel]["target_minimum_cardinality"]=1
#    if not subset_node2["properties"][referred_val].get("multivalued"):
#        int_repr["relationships"][pos_rel]["target_maximum_cardinality"]=1
    int_repr["relationships"][pos_rel]["navigation"] = "None"
    pos_node1 = find_position_by_id(int_repr["nodes"],subset_node["id"])
    del int_repr["nodes"][pos_node1]["properties"][referred_val]
    pos_node2 = find_position_by_id(int_repr["nodes"],subset_node2["id"])
    del int_repr["nodes"][pos_node2]["properties"][referred_val]
    print('END FUNCTION -> transform_case_1_4') if (verbose or detect) else None
    return int_repr


# In[36]:


def test_card_case_1_3(refs_to,current_node_caption,int_repr): # deve essere 1,1 per trasformare la clase in relazione
    current_node_data = find_node_by_caption(int_repr, current_node_caption)
    pos = find_position_by_id(int_repr["nodes"],current_node_data["id"])
    refs_to_1_referred_caption = list(refs_to[current_node_caption].keys())[0]
    refs_to_1_referred_val = list(refs_to[current_node_caption].values())[0]
    refs_to_2_referred_caption = list(refs_to[current_node_caption].keys())[1]
    refs_to_2_referred_val = list(refs_to[current_node_caption].values())[1]
    if int_repr["nodes"][pos]["properties"][refs_to_1_referred_val].get("required"):
        s1_min = 1
    else:
        return False
    if not int_repr["nodes"][pos]["properties"][refs_to_1_referred_val].get("multivalued"):
        s1_max = 1
    else:
        return False
    if int_repr["nodes"][pos]["properties"][refs_to_2_referred_val].get("required"):
        s2_min = 1
    else:
        return False
    if not int_repr["nodes"][pos]["properties"][refs_to_2_referred_val].get("multivalued"):
        s2_max = 1
    else:
        return False
    return True


# In[37]:


def transform_case_1_3(refs_to,current_node_caption,int_repr,idr): #cases 1_3, 3_2 and 5_3
    print('START FUNCTION -> transform_case_1_3') if (verbose or detect) else None
    current_node_data = find_node_by_caption(int_repr, current_node_caption)
    pos_node = find_position_by_id(int_repr["nodes"],current_node_data["id"])
    refs_to_1_referred_caption = list(refs_to[current_node_caption].keys())[0]
    refs_to_1_referred_val = list(refs_to[current_node_caption].values())[0]
    refs_to_2_referred_caption = list(refs_to[current_node_caption].keys())[1]
    refs_to_2_referred_val = list(refs_to[current_node_caption].values())[1]
    rel_id = "n"+str(idr)
    from_node = nodeid_by_caption(int_repr["nodes"],refs_to_1_referred_caption)
    to_node = nodeid_by_caption(int_repr["nodes"],refs_to_2_referred_caption)
    type = current_node_data["caption"].lower()
    int_repr["relationships"].append(set_relationship(rel_id,type,from_node,to_node))
    pos_rel = find_position_by_id(int_repr["relationships"],rel_id)
    scnprops = list(current_node_data["properties"].keys())
    print('scnprops:',scnprops) if (verbose or detect) else None
    for j in range(len(scnprops)):
        print(current_node_data["properties"][scnprops[j]]) if (verbose or detect) else None
#        if key_does_not_exist(int_repr["relationships"][0],'properties'): # non dovrebbe servire più
#            int_repr["relationships"][pos_rel]["properties"] = {}
        if ((scnprops[j]!=refs_to_1_referred_val) and (scnprops[j]!=refs_to_2_referred_val)):
            int_repr["relationships"][pos_rel]["properties"][scnprops[j]] = current_node_data["properties"][scnprops[j]]      
    #int_repr["nodes"][pos]["properties"][refs_to_1_referred_val]
    int_repr["relationships"][pos_rel]["source_minimum_cardinality"]=0
    int_repr["relationships"][pos_rel]["source_maximum_cardinality"]='N'
    int_repr["relationships"][pos_rel]["target_minimum_cardinality"]=0
    int_repr["relationships"][pos_rel]["target_maximum_cardinality"]='N'
    int_repr["relationships"][pos_rel]['examples'] = current_node_data["examples"]
    int_repr["relationships"][pos_rel]['ontologies'] = current_node_data["ontologies"] # DA COPIARE??????????
    #int_repr["relationships"][pos2]["navigation"] = "directional"
    int_repr["relationships"][pos_rel]["navigation"] = "Directional"
    del int_repr["nodes"][pos_node]
    print('END FUNCTION -> transform_case_1_3') if (verbose or detect) else None
    return int_repr


# In[38]:


def save_json_to_file(data, ifilename):
    """
    Saves a JSON-serializable Python object to a file.

    Parameters:
    - data: The Python object (e.g., dict or list) to save.
    - filename: The name of the file to save the data to.
    """
    try:
        if not isinstance(ifilename, (str, os.PathLike)):
            return

        path_input_file = os.path.abspath(ifilename)
        filename = os.path.dirname(path_input_file) + "\\" + os.path.basename(path_input_file).split('.')[0] + ".json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        #print(f"JSON data successfully saved to '{filename}'") if verbose else None
    except Exception as e:
        print(f"Failed to save JSON data: {e}")


# In[39]:


def make_consistent_dict_card(input_dict_card):
    consistent_dict_card = input_dict_card.copy()
    consistent_dict_card["required"] = False
    consistent_dict_card["multivalued"] = False
    if("exact_cardinality" in input_dict_card):#.keys()):
        val = input_dict_card["exact_cardinality"]
        if (isinstance(val, int) and val >= 0):
            if (val == 0):
                if (input_dict_card["required"]):
                    consistent_dict_card["required"] = True
                    consistent_dict_card["exact_cardinality"] = 1
                else:
                    # val == 0 and required == False
                    consistent_dict_card = {}
                    consistent_dict_card["ERROR"] = 'val == 0 and required == False'
            else: 
                #val > 0
                consistent_dict_card["required"] = True
                if (val > 1):
                    consistent_dict_card["multivalued"] = True
        else:
            # val < 0 or not isinstance(val, int)
            consistent_dict_card = {}
            consistent_dict_card["ERROR"] = 'val < 0 or not isinstance(val, int)'
        consistent_dict_card.pop("minimum_cardinality", None)
        consistent_dict_card.pop("maximum_cardinality", None)
    else:
        if ("minimum_cardinality" in input_dict_card):
            if("maximum_number_dimensions" in input_dict_card):
                # caso sia min che max
                val1 = input_dict_card["minimum_cardinality"]
                val2 = input_dict_card["maximum_cardinality"]
                if (isinstance(val2, int) and val2 > 0):
                    if (isinstance(val1, int) and val1 >= 0):
                        if (val1 == 0):
                            if (input_dict_card["required"]):
                                consistent_dict_card["required"] = True
                                consistent_dict_card["minimum_cardinality"] = 1
                            #else:
                                # val1 == 0 and required == False
                        else: 
                            #val1 > 0
                            consistent_dict_card["required"] = True
                        if (val2 < val1):
                            consistent_dict_card = {}
                            consistent_dict_card["ERROR"] = 'val2 < val1'
                        else:
                            # val2 >= val1
                            if (val2 > 1):
                                consistent_dict_card["multivalued"] = True
                    else:
                        # val1 < 0 or not isinstance(val1, int)  
                        consistent_dict_card = {}
                        consistent_dict_card["ERROR"] = 'val1 < 0 or not isinstance(val1, int)'
                else:
                    # val2 <= 0 or not isinstance(val2, int)
                    consistent_dict_card = {}
                    consistent_dict_card["ERROR"] = 'val2 <= 0 or not isinstance(val2, int)'
            else:
                # caso solo min
                val1 = input_dict_card["minimum_cardinality"]
                if (isinstance(val1, int) and val1 >= 0):
                    if (val1 == 0):
                        if (input_dict_card["required"]):
                            consistent_dict_card["required"] = True
                            consistent_dict_card["minimum_cardinality"] = 1
                        #else:
                            # val1 == 0 and required == False
                    else: 
                        #val1 > 0
                        consistent_dict_card["required"] = True
                    consistent_dict_card["multivalued"] = True
                    consistent_dict_card["maximum_cardinality"] = 'N'
                else:
                    # val1 < 0 or not isinstance(val1, int)
                    consistent_dict_card = {}
                    consistent_dict_card["ERROR"] = '(val2 missing) val1 < 0 or not isinstance(val1, int)'
        else:
            # caso no min (solo max)
            val2 = input_dict_card["maximum_cardinality"]
            if (isinstance(val2, int) and val2 > 0):
                if (input_dict_card["required"]):
                    consistent_dict_card["required"] = True
                    consistent_dict_card["minimum_cardinality"] = 1
                else:
                    consistent_dict_card["minimum_cardinality"] = 0                      
            else:
                # val2 <= 0 or not isinstance(val2, int)
                consistent_dict_card = {}
                consistent_dict_card["ERROR"] = '(val1 missing) val2 <= 0 or not isinstance(val2, int)'
    return consistent_dict_card


# In[40]:


def json_fix(json_object):
    # Helper to replace None with {}
    def replace_nulls(obj):
        if isinstance(obj, dict):
            return {k: replace_nulls(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_nulls(item) for item in obj]
        elif obj is None:
            return {}
        else:
            return obj
    # Fix missing name, title and description
    first_level_keys = list(json_object.keys())
    if 'name' not in first_level_keys:
        json_object['name'] = ''
    if 'title' not in first_level_keys:
        json_object['title'] = ''
    if 'description' not in first_level_keys:
        json_object['description'] = ''
    # Replace nulls throughout the JSON
    json_object = replace_nulls(json_object)
    # fix range
    for cname in get_class_names(json_object):
        #print(cname) if verbose else None
        if 'attributes' in json_object['classes'][cname]:
            for cattrname in get_class_attr_names(cname, json_object):
                #print(cattrname) if verbose else None
                cattrfieldskeys = get_class_attr_name_field_keys(cname, cattrname, json_object)
                #cattrfieldsvals = get_class_attr_name_field_vals(cname, cattrname, json_object)
                print('cattrfieldskeys:',cattrfieldskeys) if verbose else None
                #print('cattrfieldsvals:',cattrfieldsvals) if verbose else None
                if 'identifier' in cattrfieldskeys:
#                    json_object['classes'][cname]['attributes'].pop('cattrname', None)
#                    json_object['classes'][cname]['attributes'][cattrname] = set_node_id()
                    json_object['classes'][cname]['attributes'][cattrname].pop('identifier', None)
                    json_object['classes'][cname]['attributes'][cattrname]['requiredType'] = 'identifier'
                if 'range' not in cattrfieldskeys:
                    json_object['classes'][cname]['attributes'][cattrname]['range'] = 'string'
                if ('range' in cattrfieldskeys and
                    get_class_attr_name_field_val(cname, cattrname, 'range', json_object) in get_class_names(json_object)):
                    if 'inlined' not in cattrfieldskeys:
                        json_object['classes'][cname]['attributes'][cattrname]['inlined'] = False
                    else:
                        if json_object['classes'][cname]['attributes'][cattrname]['inlined']: # == True
#                            if 'inlined_as_list' not in cattrfieldskeys:
#                                json_object['classes'][cname]['attributes'][cattrname]['inlined_as_list'] = True
#                            else: # presente ma potrebbe essere falso
#                                todo
                            # To force inlining as a list, set inlined_as_list to true
                            # To force inlining as a dictionary, set inlined_as_list to false
                            if json_object['classes'][cname]['attributes'][cattrname].get("multivalued"):
                                json_object['classes'][cname]['attributes'][cattrname]['inlined_as_list'] = True
                    if not json_object['classes'][cname]['attributes'][cattrname].get("inlined"):
                        # aggiungere id in classe riferita
#"properties": {
#       "id": {
#         "description": "",
#         "requiredType": "identifier",
#         "range": "string"
#       }
#     },                           
                        refcname = json_object['classes'][cname]['attributes'][cattrname]['range']
                        if 'attributes' in json_object['classes'][refcname]:
                            add_id = True
                            for refcattrname in get_class_attr_names(refcname, json_object):
                                print('refcattrname:',refcattrname) if verbose else None
                                refcattrfieldskeys = get_class_attr_name_field_keys(refcname, refcattrname, json_object)
                                refcattrfieldsvals = get_class_attr_name_field_vals(refcname, refcattrname, json_object)
                                print('refcattrfieldskeys:',refcattrfieldskeys) if verbose else None
                                print('refcattrfieldsvals:',refcattrfieldsvals) if verbose else None
                                if 'identifier' in refcattrfieldsvals:
                                    # è presente come identifier: true (possibile?) deve essere trasformato
                                    add_id = False
                                    #json_object['classes'][cname]['attributes'][cattrname].pop('array', None)
                            if add_id:
                                json_object['classes'][refcname]['attributes']['id'] = set_node_id()
                        else:
                            # no attributes level
                            json_object['classes'][refcname]['attributes'] = {}
                            json_object['classes'][refcname]['attributes']['id'] = set_node_id()
                    #if 'minimum_cardinality' not in cattrfieldskeys:
                    #    json_object['classes'][cname]['attributes'][cattrname]['minimum_cardinality'] = 0
                    if 'required' not in cattrfieldskeys: ###
                        json_object['classes'][cname]['attributes'][cattrname]['required'] = False ###
                    if 'multivalued' not in cattrfieldskeys: ###
                        json_object['classes'][cname]['attributes'][cattrname]['multivalued'] = False ###
                    #if (('exact_cardinality' in cattrfieldskeys) or ('minimum_cardinality' in cattrfieldskeys) or ('maximum_cardinality' in cattrfieldskeys)):
                    if ((('exact_cardinality' in cattrfieldskeys) or ('minimum_cardinality' in cattrfieldskeys) or ('maximum_cardinality' in cattrfieldskeys)) and(json_object['classes'][cname]['attributes'][cattrname]['inlined'] is False)):               
                        dict_card = {}
                        if json_object['classes'][cname]['attributes'][cattrname].get('exact_cardinality'):
                            dict_card['exact_cardinality'] = json_object['classes'][cname]['attributes'][cattrname].get('exact_cardinality')
                        if json_object['classes'][cname]['attributes'][cattrname].get('minimum_cardinality'):
                            dict_card['minimum_cardinality'] = json_object['classes'][cname]['attributes'][cattrname].get('minimum_cardinality')
                        if json_object['classes'][cname]['attributes'][cattrname].get('maximum_cardinality'):
                            dict_card['maximum_cardinality'] = json_object['classes'][cname]['attributes'][cattrname].get('maximum_cardinality')                        
                        dict_card['required'] = json_object['classes'][cname]['attributes'][cattrname]['required'] 
                        dict_card['multivalued'] = json_object['classes'][cname]['attributes'][cattrname]['multivalued'] 
                        print('dict_card:',dict_card) if verbose else None
                        is_consistent = make_consistent_dict_card(dict_card)
                        print('is_consistent:',is_consistent) if verbose else None
                        if ('ERROR' in is_consistent.keys()):
                            if json_object['classes'][cname]['attributes'][cattrname].get('exact_cardinality'):
                                del_ref(json_object['classes'][cname]['attributes'],cattrname,int_key='exact_cardinality')
                            if json_object['classes'][cname]['attributes'][cattrname].get('minimum_cardinality'):
                                del_ref(json_object['classes'][cname]['attributes'],cattrname,int_key='minimum_cardinality')
                            if json_object['classes'][cname]['attributes'][cattrname].get('maximum_cardinality'):
                                del_ref(json_object['classes'][cname]['attributes'],cattrname,int_key='maximum_cardinality')
                        else:
                            # update values   
                            json_object['classes'][cname]['attributes'][cattrname]['required'] = is_consistent.pop('required', None) #array_card['required']
                            json_object['classes'][cname]['attributes'][cattrname]['multivalued'] = is_consistent.pop('multivalued', None) #array_card['multivalued']
                            #json_object['classes'][cname]['attributes'][cattrname].pop('array', None)
                            json_object['classes'][cname]['attributes'][cattrname]['dict_card'] = is_consistent.copy()
        else:
            print('class', cname, 'has no attributes!') if verbose else None
            #json_object['classes'][cname]['attributes']={}
            #print(json_object['classes'][cname])
    return json_object

def get_isa(i_repr):
    is_a = {}
    n = list(get_node_captions(i_repr))
    for i in range(len(n)):
        #print(i, n[i], i_repr["nodes"][i].keys())
        if('is_a' in i_repr["nodes"][i].keys()):
            is_a[i_repr["nodes"][i]['caption']] = i_repr["nodes"][i]['is_a']
    return is_a

def get_isa2(i_repr):
    is_a = {}
    n = list(get_node_captions(i_repr))
    for i in range(len(n)):
        print(i, n[i], i_repr["nodes"][i].keys()) if verbose else None
        is_a_set = set()
        if('is_a' in i_repr["nodes"][i].keys()):
            #is_a[i_repr["nodes"][i]['caption']] = i_repr["nodes"][i]['is_a']
            is_a_set.add(i_repr["nodes"][i]['is_a'])
        if('mixins' in i_repr["nodes"][i].keys()):
            mlist = i_repr["nodes"][i]['mixins']
            print('mlist:',mlist) if verbose else None
            for j in range(len(mlist)):
                if(mlist[j] in n):
                    is_a_set.add(mlist[j])
        is_a[i_repr["nodes"][i]['caption']] = is_a_set
    return is_a
# In[42]:


def transform_isa(i_repr,i_dict,cont_rel=0):
    isa_d = i_dict #get_isa(i_repr)
    r_id = cont_rel
    for k, v in isa_d.items():
        s_id = "n"+str(r_id) 
        r_from = nodeid_by_caption(i_repr["nodes"],k)
        r_to = nodeid_by_caption(i_repr["nodes"],v)
        i_repr['relationships'].append(set_isa_relationship(s_id, r_from, r_to))
        r_id +=1
    n = list(get_node_captions(i_repr))
    for i in range(len(n)):
        if('is_a' in i_repr["nodes"][i].keys()):
            i_repr["nodes"][i].pop("is_a", None)
    return [i_repr,r_id]


def transform_isa2(i_repr,i_dict,cont_rel=0):
    isa_d = i_dict #get_isa(i_repr)
    r_id = cont_rel
    for k, v in isa_d.items():
        s_id = "n"+str(r_id) 
        r_from = nodeid_by_caption(i_repr["nodes"],k)
        for z in v:
            r_to = nodeid_by_caption(i_repr["nodes"],z)
            i_repr['relationships'].append(set_isa_relationship(s_id, r_from, r_to))
            r_id +=1
    n = list(get_node_captions(i_repr))
    for i in range(len(n)):
        if('is_a' in i_repr["nodes"][i].keys()):
            i_repr["nodes"][i].pop("is_a", None)
        if('mixins' in i_repr["nodes"][i].keys()):
            i_repr["nodes"][i].pop("mixins", None)
    return [i_repr,r_id]


# start with a test case (if you pass input_type 1 or True) or load a .yaml file
# python yaml_to_json_v1a.py 1 1 -> one of the examples
# python yaml_to_json_v1a.py 1_1.yaml -> load and process .yaml file
def translate_linkml_oo(yaml_content: str, return_visual: bool = True) -> Dict[str, Any]:
    my_output = []
    json_object = {}
    #yaml_content = yaml.safe_load(yaml_content)
    current_case = fix_yaml(yaml_content)
    #print('--- current_case:', current_case)
    json_object = load_yaml_data(current_case)
    #print('--- json_object:', json_object) 
#    my_output.append(json_object)
#    my_output.append(current_case)
#    return  my_output
#start_ list = start_computation(1,1)
#json_object = start_list[0]
#current_case = start_list[1]
    ontologies_dict = load_ontologies_dict()
    ontodictk = set(ontologies_dict.keys())
    #ontok, ontomis = collect_ontologies_from_yaml(current_case, ontodictk)
    ontok, ontomis, ontobyc = collect_ontologies_from_yaml2(current_case, ontodictk)
    exbyc = collect_examples_from_yaml(current_case)
    #print("Trovate:", ontok," ---  Mancanti:", ontomis) 
    #print('--- exbyc:', exbyc) 
    json_object["ontologies"] = make_ontologies_entry(ontok, ontologies_dict)
    json_object = json_fix(json_object)
    #print('json_object fixed',json_object) if verbose else None
    #print('--- json_object fixed:', json_object) 
    #save_json_to_file(json_object, current_case)
    #print(json.dumps(json_object, indent=4)) if (verbose or detect) else None
    int_repr = {}
    int_repr = init_translation(json_object,ontobyc,exbyc)
    print('--- int_repr:', int_repr) if (verbose or detect) else None
    idr = 0
    print('idr:',idr) if verbose else None
    refs_to= {}
    refs_to = get_refs_to(json_object)
    print('refs_to:',refs_to) if verbose else None
    # double values case
    refs_to_no_list= {}
    refs_to_no_list = filter_dict_by_value_type(refs_to, 1) # items where nested values are not lists
    refs_to_list= {}
    refs_to_list = filter_dict_by_value_type(refs_to, 2) # items where nested values ARE lists
    uneraseble = set() # uneraseble.add('new_node')
    # ISA
    isa_dict = get_isa2(int_repr)
    if len(isa_dict):
        uneraseble = {x for s in isa_dict.values() for x in s} #set(isa_dict.values())
        isa_tresult = transform_isa2(int_repr,isa_dict) #transform_isa(int_repr,isa_dict)
        idr = isa_tresult[1]
        int_repr = isa_tresult[0]
        print('--- int_repr ISA fixed:') if verbose else None
        pp.pprint(int_repr) if verbose else None
    print('refs_to_no_list:',refs_to_no_list) if (verbose or detect) else None
    print('refs_to_list:',refs_to_list) if (verbose or detect) else None
    if (refs_to == refs_to_no_list): # CASO NO MULTIPLI RIFERIMENTI
        print('No multiple values!') if (verbose or detect) else None
        refs_to_i= {}
        refs_to_i = get_refs_to_i(json_object)
        referred_by= {}
        referred_by = get_referred_by(refs_to)
        referred_by_i= {}
        referred_by_i = get_referred_by_i(refs_to_i)
        attrs= {}
        attrs = get_not_ref_attr(json_object,refs_to.keys())
        warning = {}
    else: # CASO MULTIPLI RIFERIMENTI
        # refs_to: {'Class1': {'Class2': ['a', 'b', 'c']}}
        # refs_to_no_list: {}
        # refs_to_list: {'Class1': {'Class2': ['a', 'b', 'c']}}
        print('Multiple values!') if (verbose or detect) else None
        #uneraseble = set(refs_to_list.keys()) | {inner_key for v in refs_to_list.values() for inner_key in v.keys()}
        uneraseble = uneraseble | set(refs_to_list.keys()) | {inner_key for v in refs_to_list.values() for inner_key in v.keys()}
        print('uneraseble:',uneraseble) if (verbose or detect) else None 
        ncap = list(refs_to.keys())
        nvals = list(refs_to.values())
        print('ncap:',ncap) if verbose else None # ncap: ['Class1']
        print('nvals:',nvals) if verbose else None # nvals: [{'Class2': ['a', 'b', 'c']}]
        for i in range(len(ncap)):
            print('i:',i) if verbose else None # i: 0
            print('ncap[i]',ncap[i]) if verbose else None # ncap[i] Class1
            print('nvals[i]',nvals[i]) if verbose else None # nvals[i] {'Class2': ['a', 'b', 'c']}
            print('len(nvals[i]',len(nvals[i])) if verbose else None # len(nvals[i] 1
            for j in range(len(nvals[i])):
                incap = list(nvals[i].keys())[j]
                invals = list(nvals[i].values())[j]
                print('j',j) if verbose else None # j 0
                print('incap',incap) if verbose else None # incap Class2
                print('invals',invals) if verbose else None # invals ['a', 'b', 'c']
                print('len(invals)',len(invals)) if verbose else None # len(invals) 3
                #print(isinstance(invals, list)) if verbose else None
                if(isinstance(invals, list)):
                    for k in range(len(invals)):
                        print('k',k) if verbose else None # k 0
                        print('from:',ncap[i],'to:',incap,'by:',invals[k]) if verbose else None # from: Class1 to: Class2 by: a
                        subset_node = get_subset_node_info(int_repr,ncap[i], invals[k])
                        print('subset_node:',subset_node) if verbose else None
                        # subset_node: {'id': 'n0', 'caption': 'Class1', 'properties': {'a': {'description': 'attr desc', 'inlined': False, 
                        # 'multivalued': True, 'range': 'Class2', 'required': False, 'minimum_cardinality': 0}}}
                        referred_caption = incap
                        referred_val = invals[k]
                        print('referred_caption:',referred_caption,'referred_val:',referred_val,'idr:',idr) if verbose else None
                        # referred_caption: Class2 referred_val: a idr: 0
                        int_repr = transform_case_1_1(subset_node,int_repr,referred_caption,referred_val,idr)
                        idr += 1 
        refs_to = refs_to_no_list
        refs_to_i= {}
        refs_to_i = get_refs_to_i(json_object)
        referred_by= {}
        referred_by = get_referred_by(refs_to)
        referred_by_i= {}
        referred_by_i = get_referred_by_i(refs_to_i)
        attrs= {}
        attrs = get_not_ref_attr(json_object,refs_to.keys())
        warning = {}
        uneraseble.update({
            cls
            for src, targets in refs_to_i.items()
            for dst in targets
            if dst in refs_to_i and src in refs_to_i[dst]
            for cls in (src, dst)
        })
    # end double values case
    #refs_to = get_refs_to(json_object)
    #refs_to_i = get_refs_to_i(json_object)
    #referred_by = get_referred_by(refs_to)
    #referred_by_i = get_referred_by_i(refs_to_i)
    #attrs = get_not_ref_attr(json_object,refs_to.keys())
    #warning = {}
    print('refs_to:',refs_to) if (verbose or detect) else None
    print('refs_to_i:',refs_to_i) if (verbose or detect) else None
    print('referred_by:',referred_by) if (verbose or detect) else None
    print('referred_by_i:',referred_by_i) if (verbose or detect) else None
    print('attrs:',attrs) if (verbose or detect) else None
    print('warning:',warning) if (verbose or detect) else None
    print('START') if (verbose or detect) else None
    print('initial refs_to:',refs_to) if verbose else None
    print('initial referred_by_i:',referred_by_i) if verbose else None
    print('initial attrs:',attrs) if verbose else None
    print('initial warning:',warning) if verbose else None
    while((refs_to) and (refs_to != warning)):
        refs_to_by_value_length = group_keys_by_value_length(refs_to)
        print('refs_to_by_value_length:',refs_to_by_value_length) if (verbose or detect) else None
        if key_exists(refs_to_by_value_length,3): # at least one node referring to 3 or more elements
            print('CASE AT LEAST 3') if (verbose or detect) else None
            ncap = list(refs_to.keys())
            nvals = list(refs_to.values())
            print('ncap:',ncap,'nvals:',nvals) if verbose else None  
            for u in range(len(refs_to_by_value_length[3])):
                i = find_key_index(ncap,refs_to_by_value_length[3][u])
                current_node_caption = ncap[i]
                current_node_vals = nvals[i]
                print('current_node_caption:',current_node_caption,'current_node_vals:',current_node_vals) if (verbose or detect) else None
                print('number_of_current_node_vals:',len(current_node_vals)) if verbose else None
                if not test_card_case_5_1(current_node_vals,current_node_caption, int_repr):
                        uneraseble.add(current_node_caption) 
                if ((current_node_caption not in refs_to_i) and (current_node_caption not in referred_by_i) and (current_node_caption not in uneraseble)):
                    print('case 5_1') if (verbose or detect) else None
                    current_node_data = find_node_by_caption(int_repr, current_node_caption)
                    #int_repr = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr)
                    transform_result = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr)
                    int_repr = transform_result[0]
                    idr = transform_result[1]
                    #idr += len(s1)                
                    del refs_to[current_node_caption] # ref_to must be updated
                    if key_exists(warning,current_node_caption): # warning must be updated
                        del warning[current_node_caption]
                    print('actual refs_to:',refs_to) if verbose else None
                    print('actual referred_by_i:',referred_by_i) if verbose else None
                else:
                    print('case 5_1_b') if (verbose or detect) else None
                    current_node_data = find_node_by_caption(int_repr, current_node_caption)
                    #int_repr = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr)
                    transform_result = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr,False)
                    int_repr = transform_result[0]
                    idr = transform_result[1]
                    #idr += len(s1)                
                    del refs_to[current_node_caption] # ref_to must be updated
                    if key_exists(warning,current_node_caption): # warning must be updated
                        del warning[current_node_caption]
                    print('actual refs_to:',refs_to) if verbose else None
                    print('actual referred_by_i:',referred_by_i) if verbose else None            
            print('actual warning:',warning) if (verbose or detect) else None
        else:
            if key_exists(refs_to_by_value_length,2): # at least one node referring to 2 elements
                print('CASE 2') if (verbose or detect) else None
                ncap = list(refs_to.keys())
                nvals = list(refs_to.values())
                print('ncap:',ncap,'nvals:',nvals) if verbose else None
                for u in range(len(refs_to_by_value_length[2])):
                    i = find_key_index(ncap,refs_to_by_value_length[2][u])
                    current_node_caption = ncap[i]
                    current_node_vals = nvals[i]
                    print('current_node_caption:',current_node_caption,'current_node_vals:',current_node_vals) if (verbose or detect) else None
                    print('number_of_current_node_vals:',len(current_node_vals)) if verbose else None
                    if(current_node_caption in referred_by_i.keys()):
                        uneraseble.add(current_node_caption)    
                    # test card se non passa aggiungi in uneraseble
                    if not test_card_case_1_3(refs_to,current_node_caption,int_repr):
                        uneraseble.add(current_node_caption) 
                    if(current_node_caption not in uneraseble):
                        if key_exists(attrs,current_node_caption):
                            if key_exists(refs_to_i,current_node_caption):
                                print('case 5_3') if (verbose or detect) else None
                                int_repr = transform_case_1_3(refs_to,current_node_caption,int_repr,idr)
                                idr += 1
                                del_ref(refs_to,current_node_caption)
                                #del_ref(refs_to_i,current_node_caption)
                                if key_exists(warning,current_node_caption): # warning must be updated
                                    del_ref(warning,current_node_caption)
                                print('actual refs_to:',refs_to) if (verbose or detect) else None
                                print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                            else:
                                print('case 3_2') if (verbose or detect) else None
                                int_repr = transform_case_1_3(refs_to,current_node_caption,int_repr,idr)
                                idr += 1
                                del_ref(refs_to,current_node_caption)
                                if key_exists(warning,current_node_caption): # warning must be updated
                                    del_ref(warning,current_node_caption)
                                print('actual refs_to:',refs_to) if (verbose or detect) else None
                                print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                        else:
                            print('case 1_3') if (verbose or detect) else None
                            int_repr = transform_case_1_3(refs_to,current_node_caption,int_repr,idr)
                            idr += 1
                            del_ref(refs_to,current_node_caption)
                            if key_exists(warning,current_node_caption): # warning must be updated
                                del_ref(warning,current_node_caption)
                            print('actual refs_to:',refs_to) if (verbose or detect) else None
                            print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                    else: # il nodo non deve diventare una relazione
                        print('case 5_1_b') if (verbose or detect) else None
                        current_node_data = find_node_by_caption(int_repr, current_node_caption)
                        transform_result = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr,False)
                        int_repr = transform_result[0]
                        idr = transform_result[1]
                        del refs_to[current_node_caption] # ref_to must be updated
                        if key_exists(warning,current_node_caption): # warning must be updated
                            del warning[current_node_caption]
                        print('actual refs_to:',refs_to) if verbose else None
                        print('actual referred_by_i:',referred_by_i) if verbose else None   
                print('actual warning:',warning) if (verbose or detect) else None
            else:
                if key_exists(refs_to_by_value_length,1): # at least one node referring to 1 element
                    print('CASE 1') if (verbose or detect) else None
                    ncap = list(refs_to.keys())
                    nvals = list(refs_to.values())
                    print('ncap:',ncap,'nvals:',nvals) if verbose else None
                    already_covered_set = set()
                    print('refs_to_by_value_length[1]:',refs_to_by_value_length[1]) if verbose else None
                    for u in range(len(refs_to_by_value_length[1])):
                        i = find_key_index(ncap,refs_to_by_value_length[1][u])
                        current_node_caption = ncap[i]
                        #if current_node_caption not in refs_to: ###
                        #    continue ###
                        if(current_node_caption not in already_covered_set):
                            current_node_vals = nvals[i]
                            print('current_node_caption:',current_node_caption,'current_node_vals:',current_node_vals) if (verbose or detect) else None
                            print('number_of_current_node_vals:',len(current_node_vals)) if verbose else None
                            #referred_caption = list(list(refs_to.values())[i].keys())[0]
                            #referred_val = list(list(refs_to.values())[i].values())[0]
                            referred_caption = list(current_node_vals.keys())[0] ###
                            referred_val = list(current_node_vals.values())[0] ###
                            print('referred_caption:',referred_caption,'referred_val:',referred_val) if verbose else None
                            if key_exists(refs_to,referred_caption): # referred_caption -> something
                                if(referred_caption in refs_to_by_value_length[1]): # card(something) == 1
                                    if key_exists(refs_to[referred_caption], current_node_caption): # referred_caption -> current_caption
                                        if (referred_val == refs_to[referred_caption][current_node_caption]): # same node caption
                                            print('case 1_4') if (verbose or detect) else None
                                            subset_node = get_subset_node_info(int_repr, current_node_caption,referred_val)
                                            subset_node2 = get_subset_node_info(int_repr, referred_caption,referred_val)
                                            print('subset_node:',subset_node) if verbose else None
                                            print('subset_node2:',subset_node2) if verbose else None
                                            int_repr = transform_case_1_4(subset_node,subset_node2,int_repr,referred_val,idr)
                                            idr += 1                                        
                                            del_ref(refs_to,current_node_caption)
                                            del_ref(refs_to,referred_caption)
                                            already_covered_set.add(referred_caption) # we have consumed two elements
                                            if key_exists(warning,current_node_caption): # warning must be updated
                                                    #del warning[current_node_caption]
                                                del_ref(warning,current_node_caption)
                                            if key_exists(warning,referred_caption): # warning must be updated
                                                    #del warning[referred_caption]
                                                del_ref(warning,referred_caption)
                                            print('actual refs_to:',refs_to) if (verbose or detect) else None
                                            print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                                        else: # different node caption
                                            print('case double 1_1_a') if (verbose or detect) else None
                                            subset_node = get_subset_node_info(int_repr, current_node_caption,referred_val)
                                            print('subset_node:',subset_node) if verbose else None
                                            print('referred_caption:',referred_caption,'referred_val:',referred_val,'idr:',idr) if verbose else None
                                            int_repr = transform_case_1_1(subset_node,int_repr,referred_caption,referred_val,idr)
                                            idr += 1  
                                            referred_val2 = refs_to[referred_caption][current_node_caption]
                                            subset_node2 = get_subset_node_info(int_repr, referred_caption,referred_val2)
                                            print('subset_node2:',subset_node2) if verbose else None
                                            print('referred_caption2:',current_node_caption,'referred_val2:',referred_val2,'idr:',idr) if verbose else None
                                            int_repr = transform_case_1_1(subset_node2,int_repr,current_node_caption,referred_val2,idr)
                                            idr += 1  
                                            del refs_to[current_node_caption] # ref_to must be updated
                                            del refs_to[referred_caption]
                                            already_covered_set.add(referred_caption)
                                            if key_exists(warning,current_node_caption): # warning must be updated
                                                del warning[current_node_caption]
                                            if key_exists(warning,referred_caption): # warning must be updated
                                                del warning[referred_caption]
                                            print('actual refs_to:',refs_to) if (verbose or detect) else None
                                            print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                                    else: # referred_caption -> a single node different from current_caption
                                        print('case double 1_1_b') if (verbose or detect) else None
                                        subset_node = get_subset_node_info(int_repr, current_node_caption,referred_val)
                                        print('subset_node:',subset_node) if verbose else None
                                        print('referred_caption:',referred_caption,'referred_val:',referred_val,'idr:',idr) if verbose else None
                                        int_repr = transform_case_1_1(subset_node,int_repr,referred_caption,referred_val,idr)
                                        idr += 1  
                                        second_node_caption = referred_caption
                                        second_referred_caption = list(refs_to[referred_caption].keys())[0] 
                                        second_referred_val = list(refs_to[referred_caption].values())[0]
                                        subset_node2 = get_subset_node_info(int_repr, second_node_caption,second_referred_val)
                                        print('subset_node2:',subset_node2) if verbose else None
                                        print('second_referred_caption:',second_referred_caption,'second_referred_val:',second_referred_val,'idr:',idr) if verbose else None
                                        int_repr = transform_case_1_1(subset_node2,int_repr,second_referred_caption,second_referred_val,idr)
                                        idr += 1 
                                        del refs_to[current_node_caption] # ref_to must be updated
                                        del refs_to[referred_caption]
                                        already_covered_set.add(referred_caption)
                                        if key_exists(warning,current_node_caption): # warning must be updated
                                            del warning[current_node_caption]
                                        if key_exists(warning,referred_caption): # warning must be updated
                                            del warning[referred_caption]
                                        print('actual refs_to:',refs_to) if (verbose or detect) else None
                                        print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                                else: # card(something) > 1
                                    print('WARNING:',current_node_caption,'referred_caption:',referred_caption,'points to a more than a single element') if (verbose or detect) else None
                                    if key_does_not_exist(warning,current_node_caption):
                                        warning[current_node_caption] = current_node_vals
                            else: # referred_caption -> none
                                #if key_does_not_exist(referred_by,current_node_caption): # should not be referred to by any element
                                if key_exists(referred_by_i,current_node_caption): # current_node is inlined referred by
                                    #check_size(referred_by_i[current_node_caption],current_node_caption) # should be inline referred by exactly one element
                                    #print(len(referred_by_i[current_node_caption]))  
                                    if(current_node_caption not in group_keys_by_value_length(referred_by_i)[1]):
                                        uneraseble.add(current_node_caption)    
                                    uneraseble.add(current_node_caption) # eliminiamo i casi 3_1 e 5_2 e li trattiamo sempre come ramo else
                                    if(current_node_caption not in uneraseble):
                                        if key_exists(refs_to_i,current_node_caption): # current_node inline refers to
                                            #check_size(refs_to_i[current_node_caption],current_node_caption) # should be inline refers to exactly one element
                                            print('case 5_2') if (verbose or detect) else None
                                            #int_repr = transform_case_3_1(referred_by_i,current_node_caption,int_repr,referred_caption,referred_val,idr)
                                            idr += 1 
                                            del refs_to[current_node_caption] 
                                            del refs_to_i[current_node_caption] 
                                            del referred_by_i[current_node_caption]
                                            print('actual refs_to:',refs_to) if (verbose or detect) else None
                                            print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                                        else:
                                            print('case 3_1') if (verbose or detect) else None
                                            #print('BEFORE',int_repr)
                                            #int_repr = transform_case_3_1(referred_by_i,current_node_caption,int_repr,referred_caption,referred_val,idr)
                                            #print('AFTER',int_repr)
                                            idr += 1 
                                            del refs_to[current_node_caption] # ref_to must be updated
                                            del referred_by_i[current_node_caption]
                                            print('actual refs_to:',refs_to) if (verbose or detect) else None
                                            print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
                                    else:
                                        print('case 5_1_b') if (verbose or detect) else None
                                        current_node_data = find_node_by_caption(int_repr, current_node_caption)
                                        transform_result = transform_case_5_1(current_node_vals,current_node_data, int_repr,idr,False)
                                        int_repr = transform_result[0]
                                        idr = transform_result[1]
                                        del refs_to[current_node_caption] # ref_to must be updated
                                        if key_exists(warning,current_node_caption): # warning must be updated
                                            del warning[current_node_caption]
                                        print('actual refs_to:',refs_to) if verbose else None
                                        print('actual referred_by_i:',referred_by_i) if verbose else None                                           
                                else:
                                    print('case 1_1') if (verbose or detect) else None
                                    subset_node = get_subset_node_info(int_repr, current_node_caption,referred_val)
                                    print('subset_node:',subset_node) if verbose else None
                                    print('referred_caption:',referred_caption,'referred_val:',referred_val,'idr:',idr) if verbose else None
                                    int_repr = transform_case_1_1(subset_node,int_repr,referred_caption,referred_val,idr)
                                    idr += 1                                
                                    del refs_to[current_node_caption] # ref_to must be updated
                                    if key_exists(warning,current_node_caption): # warning must be updated
                                        del warning[current_node_caption]
                                    print('actual refs_to:',refs_to) if (verbose or detect) else None
                                    print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None                            
                    print('actual warning:',warning) if (verbose or detect) else None  
                else:
                    if key_does_not_exist(warning,current_node_caption):
                        warning[current_node_caption] = current_node_vals
                    print('actual refs_to:',refs_to) if (verbose or detect) else None
                    print('actual referred_by_i:',referred_by_i) if (verbose or detect) else None
    print('final warning:',warning) if (verbose or detect) else None
    print('END') if (verbose or detect) else None
    print('refs_to:',refs_to) if (verbose or detect) else None
    print('refs_to_i:',refs_to_i) if (verbose or detect) else None
    print('referred_by:',referred_by) if (verbose or detect) else None
    print('referred_by_i:',referred_by_i) if (verbose or detect) else None
    print('--- final int_repr:') if (verbose or detect) else None
    print('final int_repr:', int_repr) if (verbose or detect) else None
    #save_file(current_case[:-5],int_repr)
    #save_file(str(current_case)[:-5], int_repr)
    visual_repr = get_visualization(int_repr)
    print('--- visual_repr:') if (verbose or detect) else None
    pp.pprint(visual_repr) if (verbose or detect) else None
    #save_file(current_case[:-5],visual_repr,"v")
    #save_file(str(current_case)[:-5],visual_repr,"v")
    print('--- visual_repr:', visual_repr)
    return visual_repr
#    return 'OK'

