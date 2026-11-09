"""Optional chat application. Core Cota and Channels never import this package."""


def create_app(*args, **kwargs):
    from .app import create_app as factory
    return factory(*args, **kwargs)
