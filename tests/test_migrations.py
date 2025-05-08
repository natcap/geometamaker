"""Test cases to ensure graceful migrations from earlier data models.

While geometamaker undergoes pre-1.0 development, the data models
for metadata are subject to change. But we still want to maintain
backwards-compatibility for users with metadata created by earlier
versions. In practice, compatibility is achieved with the
`geometamaker.models.Resource.load` method, which is reponsible for
loading existing metadata documents during `describe` or `validate`.

This test suite, along with data in `tests/data/<version>`
should be used to test that migrations work as expected.

"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch


class MigrationTests(unittest.TestCase):
    """Tests for migrating metadata documents from older data models."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()
        self.patcher = patch('geometamaker.config.platformdirs.user_config_dir')
        self.mock_user_config_dir = self.patcher.start()
        self.mock_user_config_dir.return_value = self.workspace_dir

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        self.patcher.stop()
        shutil.rmtree(self.workspace_dir)

    def test_v0_1_2_vector(self):
        """This vector pre-dates the use of layers."""
        import geometamaker

        vector_path = os.path.join(
            os.path.dirname(__file__), 'data/0.1.2/vector.geojson')
        # with self.assertRaises(FileNotFoundError):
        resource = geometamaker.describe(vector_path)

