from typing import List,Any,Dict,Text,Optional
from collections import defaultdict, deque
from sanic import Sanic
import hashlib
import logging


logger = logging.getLogger(__name__)

def subclasses(cls: Any) -> List[Any]:
    return cls.__subclasses__() + [
        g for s in cls.__subclasses__() for g in subclasses(s)
    ]

def list_routes(app: Sanic) -> Dict[Text, Text]:
    """List all the routes of a sanic application. Mainly used for debugging."""
    from urllib.parse import unquote

    output = {}

    def find_route(suffix: Text, path: Text) -> Optional[Text]:
        for name, (uri, _) in app.router.routes_names.items():
            if name.split(".")[-1] == suffix and uri == path:
                return name
        return None

    for route in app.router.routes:
        endpoint = route.parts
        if endpoint[:-1] in app.router.routes_all and endpoint[-1] == "/":
            continue

        options = {}
        for arg in route._params:
            options[arg] = f"[{arg}]"

        handlers = [(next(iter(route.methods)), route.name.replace("cota_server.", ""))]

        for method, name in handlers:
            full_endpoint = "/" + "/".join(endpoint)
            line = unquote(f"{full_endpoint:50s} {method:30s} {name}")
            output[name] = line

    url_table = "\n".join(output[url] for url in sorted(output))
    logger.debug(f"Available web server routes: \n{url_table}")
    return output

def update_existing_keys(target_dict, source_dict):
     for key in source_dict:
        if key in target_dict:
            target_dict[key] = source_dict[key]

def all_keys_filled(dictionary):
    return all(value is not None and value != '' for value in dictionary.values())

def first_empty_key(dictionary):
    for key, value in dictionary.items():
        if value is None or value == "":
            return key
    return None

def merge_dicts(default_dict, update_dict):
    """
    Recursively merges two dictionaries.

    Args:
        default_dict (dict): The first dictionary.
        update_dict (dict): The second dictionary.

    Returns:
        dict: The merged dictionary.
    """
    for key in update_dict:
        if key in default_dict:
            if isinstance(default_dict[key], dict) and isinstance(update_dict[key], dict):
                merge_dicts(default_dict[key], update_dict[key])
            else:
                default_dict[key] = update_dict[key]
        else:
            default_dict[key] = update_dict[key]
    return default_dict

def is_dag(tasks):
    graph = defaultdict(list)
    in_degree = defaultdict(int)

    for task in tasks:
        name = task['name']
        dependencies = task['dependencies']
        in_degree[name] = 0
        for dep in dependencies:
            graph[dep].append(name)
            in_degree[name] += 1

    queue = deque()
    for node in in_degree:
        if in_degree[node] == 0:
            queue.append(node)

    visited_nodes = 0
    while queue:
        node = queue.popleft()
        visited_nodes += 1
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If the number of visited nodes equals the number of nodes in the graph, then there is no cycle
    return visited_nodes == len(in_degree)

def hash_str(s):
    # use SHA-256 algorithm
    sha256 = hashlib.sha256()
    sha256.update(s.encode('utf-8'))
    return sha256.hexdigest()
