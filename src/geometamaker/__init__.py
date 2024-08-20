import importlib.metadata
import os

import platformdirs
import yaml

from .geometamaker import describe


__version__ = importlib.metadata.version('geometamaker')

CONFIG_FILE = os.path.join(
    platformdirs.user_config_dir(), 'geometamaker_profiles.yml')

DEFAULT_PROFILES = {
    'contact': None,
    'license': None
}

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as file:
        file.write(yaml.dump(DEFAULT_PROFILES))
