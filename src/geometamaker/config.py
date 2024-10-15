import logging
import os
import pprint
from dataclasses import dataclass

import fsspec
import platformdirs
import yaml


LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(
    platformdirs.user_config_dir(), 'geometamaker_profile.yml')
DEFAULT_PROFILE = {
    'contact': None,
    'license': None
}


# @dataclass()
class Config(object):

    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        """Load a configuration from a file.

        Use a default user profile if none given. Create
        that default profile if necessary.

        """
        self.config_path = config_path
        if not os.path.exists(self.config_path):
            if self.config_path == DEFAULT_CONFIG_PATH:
                print('writing default profile')
                with open(self.config_path, 'w') as file:
                    file.write(yaml.dump(DEFAULT_PROFILE))

        try:
            with open(self.config_path, 'r') as file:
                yaml_string = file.read()
            self.profile = yaml.safe_load(yaml_string)
        except:
            self.profile = None

        # profile: dict = DEFAULT_PROFILE

    # def save(self):
    #     with open(CONFIG_FILE, 'w') as file:
    #         LOGGER.info(f'writing config to {CONFIG_FILE}')
    #         file.write(yaml.dump(self.profile))

    # def __str__(self):
    #     return self.profile


# def load_config(fname):
#     print(fname)
#     if not os.path.exists(fname):
#         with open(fname, 'w') as file:
#             file.write(yaml.dump(DEFAULT_PROFILE))

#     with open(fname, 'r') as file:
#         yaml_string = file.read()
#     self.profile = yaml.safe_load(yaml_string)


# def configure(self, contact=None, license=None, save=False):
#     if contact:
#         self.profile['contact'] = contact
#     if license:
#         self.profile['license'] = license

#     if save:
#         self.save()
