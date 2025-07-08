import logging
import os

import platformdirs
from pydantic import ValidationError

from . import models


LOGGER = logging.getLogger('geometamaker')

CONFIG_FILENAME = 'geometamaker_profile.yml'


class Config(object):
    """Encapsulates user-settings such as a metadata Profile."""

    def __init__(self, config_path=None):
        """Load a Profile from a config file.

        Use a default user profile if none given.

        Args:
            config_path (str): path to a local yaml file

        """
        if config_path is None:
            self.config_path = os.path.join(
                platformdirs.user_config_dir(), CONFIG_FILENAME)
        else:
            self.config_path = config_path
        self.profile = models.Profile()

        try:
            self.profile = models.Profile.load(self.config_path)
        except FileNotFoundError:
            LOGGER.debug(f'config file does not exist at {self.config_path}')
        # an invalid profile should raise a ValidationError
        except ValidationError as err:
            LOGGER.warning('', exc_info=err)
            LOGGER.warning(
                f'{self.config_path} contains an inavlid profile. '
                'It will be ignored. You may wish to delete() it.')

    def __repr__(self):
        """Represent config as a string."""
        return f'Config(config_path={self.config_path} profile={self.profile})'

    def save(self, profile):
        """Save a Profile to a local config file.

        Args:
            profile (geometamaker.models.Profile)
        """
        LOGGER.info(f'writing profile to {self.config_path}')
        profile.write(self.config_path)

    def delete(self):
        """Delete the config file."""
        try:
            os.remove(self.config_path)
            LOGGER.info(f'removed {self.config_path}')
        except FileNotFoundError as error:
            LOGGER.debug(error)
