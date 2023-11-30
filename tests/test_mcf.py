import os
import shutil
import tempfile
import unittest

from osgeo import ogr
from osgeo import osr
import pygeoprocessing
import shapely


def create_vector(target_filepath):
    projection = osr.SpatialReference()
    projection.ImportFromEPSG(3116)
    pygeoprocessing.shapely_geometry_to_vector(
        [shapely.geometry.Point(1, -1)],
        target_filepath,
        projection.ExportToWkt(),
        'GEOJSON',
        fields={'field_a': ogr.OFTReal},
        attribute_list=[{'field_a': 0.99}],
        ogr_geom_type=ogr.wkbPoint)


class MCFTests(unittest.TestCase):
    """Tests for the Carbon Model."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        shutil.rmtree(self.workspace_dir)

    def test_MCF(self):
        """MCF."""
        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        create_vector(datasource_path)

        mcf = MCF(datasource_path)
