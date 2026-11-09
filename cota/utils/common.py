"""Configuration merge and CLI route inspection used by current Cota."""
import logging

logger = logging.getLogger(__name__)


def list_routes(app):
    """Describe all HTTP methods without depending on private router fields."""
    output = {}
    for route in app.router.routes:
        path = '/' + route.path.lstrip('/')
        methods = ', '.join(sorted(route.methods))
        output[route.name] = f'{path:50s} {methods:30s} {route.name}'
    logger.debug('Available web server routes:\n%s', '\n'.join(output[key] for key in sorted(output)))
    return output


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
