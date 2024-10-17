import logging
import os

import platformdirs

from . import models


LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(
    platformdirs.user_config_dir(), 'geometamaker_profile.yml')


class Config(object):

    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        """Load a Profile from a config file.

        Use a default user profile if none given. Create
        that default profile if necessary.

        """
        self.config_path = config_path

        try:
            self.profile = models.Profile.load(self.config_path)
        except FileNotFoundError as err:
            LOGGER.debug(err)
            pass
        # TypeError from an invalid profile should not be caught
        # TODO: any reason to init an empty profile?
        #     self.profile = models.Profile()

    def save(self, profile):
        """Save a Profile as the default user profile.

        Args:
            profile (geometamaker.models.Profile)
        """
        LOGGER.info(f'writing config to {self.config_path}')
        profile.write(self.config_path)
