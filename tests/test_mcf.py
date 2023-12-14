import os
import shutil
import tempfile
import unittest

from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError
import numpy
from osgeo import gdal
from osgeo import gdal_array
from osgeo import ogr
from osgeo import osr
from pygeometa.core import MCFValidationError
import pygeoprocessing
from pygeoprocessing.geoprocessing_core import DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
import shapely

# This is the complete list of types, but some are
# exceedingly rare and do not match easily to python types
# so I'm not sure if we need to support them all.
# _VALID_OGR_TYPES = (
#     set([getattr(ogr, x) for x in dir(ogr) if 'OFT' in x]))

_OGR_TYPES_VALUES_MAP = {
    ogr.OFTInteger: 0,
    ogr.OFTInteger64: 0,
    ogr.OFTReal: 0.0,
    ogr.OFTString: ''
}


def create_vector(target_filepath, field_map):
    attribute_list = [{
        k: _OGR_TYPES_VALUES_MAP[v]
        for k, v in field_map.items()
    }]
    projection = osr.SpatialReference()
    projection.ImportFromEPSG(3116)
    pygeoprocessing.shapely_geometry_to_vector(
        [shapely.geometry.Point(1, -1)],
        target_filepath,
        projection.ExportToWkt(),
        'GEOJSON',
        fields=field_map,
        attribute_list=attribute_list,
        ogr_geom_type=ogr.wkbPoint)


def create_raster(
        numpy_dtype, target_path,
        pixel_size=(1, 1), projection_epsg=4326,
        origin=(0, 0)):
    driver_name, creation_options = DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
    raster_driver = gdal.GetDriverByName(driver_name)
    ny, nx = (2, 2)
    n_bands = 2
    gdal_type = gdal_array.NumericTypeCodeToGDALTypeCode(numpy_dtype)
    new_raster = raster_driver.Create(
        target_path, nx, ny, n_bands, gdal_type)
    new_raster.SetGeoTransform(
        [origin[0], pixel_size[0], 0, origin[1], 0, pixel_size[1]])

    projection = osr.SpatialReference()
    projection_wkt = None
    if projection_epsg is not None:
        projection.ImportFromEPSG(projection_epsg)
        projection_wkt = projection.ExportToWkt()
    if projection_wkt is not None:
        new_raster.SetProjection(projection_wkt)

    base_array = numpy.full((2, 2), 1, dtype=numpy_dtype)
    target_nodata = pygeoprocessing.choose_nodata(numpy_dtype)

    band_1 = new_raster.GetRasterBand(1)
    band_1.SetNoDataValue(target_nodata)
    band_1.WriteArray(base_array)
    band_1 = None
    band_2 = new_raster.GetRasterBand(2)
    band_2.SetNoDataValue(target_nodata)
    band_2.WriteArray(base_array)
    band_2 = None
    new_raster = None


class MCFTests(unittest.TestCase):
    """Tests for pygeometadata.mcf."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        shutil.rmtree(self.workspace_dir)

    def test_vector_MCF(self):
        """MCF: validate basic vector MCF."""
        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        field_map = {
            f'field_{k}': k
            for k in _OGR_TYPES_VALUES_MAP}
        create_vector(datasource_path, field_map)

        mcf = MCF(datasource_path)
        try:
            mcf.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')
        mcf.write()

    def test_raster_MCF(self):
        """MCF: validate basic raster MCF."""
        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        mcf = MCF(datasource_path)
        try:
            mcf.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')
        mcf.write()

    def test_vector_attributes(self):
        """MCF: validate vector with extra attribute metadata."""
        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        field_name = 'foo'
        field_map = {
            field_name: list(_OGR_TYPES_VALUES_MAP)[0]}
        create_vector(datasource_path, field_map)

        mcf = MCF(datasource_path)
        title = 'title'
        abstract = 'some abstract'
        units = 'mm'
        mcf.describe_field(
            field_name,
            title=title,
            abstract=abstract)
        # To demonstrate that properties can be added while preserving others
        mcf.describe_field(
            field_name,
            units=units)
        try:
            mcf.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')

        attr = [attr for attr in mcf.mcf['content_info']['attributes']
                if attr['name'] == field_name][0]
        self.assertEqual(attr['title'], title)
        self.assertEqual(attr['abstract'], abstract)
        self.assertEqual(attr['units'], units)

    def test_raster_attributes(self):
        """MCF: validate raster with extra attribute metadata."""
        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        band_number = 1

        mcf = MCF(datasource_path)
        name = 'name'
        title = 'title'
        abstract = 'some abstract'
        units = 'mm'
        mcf.describe_band(
            band_number,
            name=name,
            title=title,
            abstract=abstract)
        # To demonstrate that properties can be added while preserving others
        mcf.describe_band(
            band_number,
            units=units)
        try:
            mcf.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')

        attr = mcf.mcf['content_info']['attributes'][band_number - 1]
        self.assertEqual(attr['name'], name)
        self.assertEqual(attr['title'], title)
        self.assertEqual(attr['abstract'], abstract)
        self.assertEqual(attr['units'], units)

    def test_add_keywords(self):
        """MCF: add keywords to default section."""

        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        mcf.set_keywords(['foo', 'bar'])

        self.assertEqual(
            mcf.mcf['identification']['keywords']['default']['keywords'],
            ['foo', 'bar'])

    def test_add_keywords_to_section(self):
        """MCF: add keywords to named section."""

        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        mcf.set_keywords(['foo', 'bar'], section='first')
        mcf.set_keywords(['baz'], section='second')

        self.assertEqual(
            mcf.mcf['identification']['keywords']['first']['keywords'],
            ['foo', 'bar'])
        self.assertEqual(
            mcf.mcf['identification']['keywords']['second']['keywords'],
            ['baz'])

    def test_overwrite_keywords(self):
        """MCF: overwrite keywords in existing section."""

        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        mcf.set_keywords(['foo', 'bar'])
        mcf.set_keywords(['baz'])

        self.assertEqual(
            mcf.mcf['identification']['keywords']['default']['keywords'],
            ['baz'])

    def test_keywords_raises_type_error(self):
        """MCF: keywords raises TypeError."""

        from pygeometadata.mcf import MCF

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        with self.assertRaises(TypeError):
            mcf.set_keywords('foo', 'bar')

    def test_preexisting_mcf(self):
        """MCF: test reading and ammending an existing MCF."""
        from pygeometadata.mcf import MCF
        title = 'Title'
        keyword = 'foo'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        mcf.set_title(title)
        mcf.write()

        new_mcf = MCF(datasource_path)
        new_mcf.set_keywords([keyword])

        self.assertEqual(
            new_mcf.mcf['identification']['title'], title)
        self.assertEqual(
            new_mcf.mcf['identification']['keywords']['default']['keywords'],
            [keyword])

    def test_invalid_preexisting_mcf(self):
        """MCF: test overwriting an existing invalid MCF."""
        from pygeometadata.mcf import MCF
        title = 'Title'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mcf = MCF(datasource_path)
        mcf.set_title(title)

        # delete a required property and ensure invalid MCF
        del mcf.mcf['mcf']
        with self.assertRaises(ValidationError):
            mcf.validate()
        mcf.write()  # intentionally writing an invalid MCF

        new_mcf = MCF(datasource_path)

        # The new MCF should not have values from the invalid MCF
        self.assertEqual(
            new_mcf.mcf['identification']['title'], '')

        try:
            new_mcf.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')
        try:
            new_mcf.write()
        except Exception as e:
            self.fail(
                'unexpected write error occurred\n'
                f'{e}')
