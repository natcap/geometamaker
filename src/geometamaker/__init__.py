import importlib.metadata
import typing

__version__ = importlib.metadata.version('geometamaker')

__all__ = ('describe', 'describe_collection', 'validate', 'validate_dir', 'Config', 'Profile')

# Map names to modules
_MODULE_MAP = {
    'describe': '.geometamaker',
    'describe_collection': '.geometamaker',
    'validate': '.geometamaker',
    'validate_dir': '.geometamaker',
    'Config': '.config',
    'Profile': '.models'
}

def __getattr__(name: str) -> typing.Any:
    """This function only runs when someone types `from geometamaker import X`."""
    if name in _MODULE_MAP:
        module = importlib.import_module(_MODULE_MAP[name], __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")