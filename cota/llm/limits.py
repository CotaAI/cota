"""Local request limits, never forwarded as provider body parameters."""
from math import isfinite

DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_RETRIES = 0


def request_limits(config):
    timeout = config.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)
    retries = config.get('max_retries', DEFAULT_MAX_RETRIES)
    if type(timeout) not in (int, float) or not isfinite(timeout) or timeout <= 0:
        raise ValueError('endpoints.yml llms.<name>.timeout_seconds must be positive and finite')
    if type(retries) is not int or not 0 <= retries <= 5:
        raise ValueError('endpoints.yml llms.<name>.max_retries must be an integer from 0 to 5')
    if config.get('type') == 'custom' and retries:
        raise ValueError('Custom endpoints do not support automatic max_retries; use 0')
    return timeout, retries
