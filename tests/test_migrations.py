"""Test cases to ensure graceful migrations from earlier data models.

While geometamaker undergoes pre-1.0 development, the data models
for metadata are subject to change. But we still want to maintain
backwards-compatibility for users with metadata created by earlier
versions. In practice, compatibility is achieved with the
`geometamaker.models.Resource.load` method, which is reponsible for
loading existing metadata documents during `describe`.

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

    def test_vector_resource_without_layers(self):
        """This document pre-dates the use of layers."""
        import geometamaker

        vector_path = os.path.join(
            os.path.dirname(__file__), 'data/0.1.2/vector.geojson')
        yml_path = f'{vector_path}.yml'
        with self.assertRaises(ValueError):
            geometamaker.load(yml_path)
        with self.assertWarns(FutureWarning):
            resource = geometamaker.describe(vector_path)
            self.assertEqual(len(resource.data_model.layers), 1)

    def test_spatial_model_with_crs_string(self):
        """This document pre-dates the use of models.CoordinateReferenceSystem."""
        import geometamaker

        vector_path = os.path.join(
            os.path.dirname(__file__), 'data/0.3.3/vector.geojson')
        yml_path = f'{vector_path}.yml'
        with self.assertRaises(ValueError):
            geometamaker.load(yml_path)
        with self.assertWarns(FutureWarning):
            resource = geometamaker.describe(vector_path)
            self.assertTrue(resource.spatial.crs)
