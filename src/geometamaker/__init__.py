import importlib.metadata

from .geometamaker import describe
from .config import init_config
from .config import configure

init_config()
__version__ = importlib.metadata.version('geometamaker')
