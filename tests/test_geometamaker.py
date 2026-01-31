import csv
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy
import pygeoprocessing
import shapely
import yaml

from click.testing import CliRunner
from osgeo import gdal
from osgeo import gdal_array
from osgeo import ogr
from osgeo import osr
from pygeoprocessing.geoprocessing_core import DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
from pydantic import ValidationError

REGRESSION_DATA = os.path.join(
    os.path.dirname(__file__), 'data')

# A remote file we can use for testing
REMOTE_FILEPATH = 'https://storage.googleapis.com/releases.naturalcapitalproject.org/invest/3.14.2/data/CoastalBlueCarbon.zip'

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


def create_vector(target_filepath, field_map=None, driver='GEOJSON'):
    attribute_list = None
    if field_map:
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
        driver,
        fields=field_map,
        attribute_list=attribute_list,
        ogr_geom_type=ogr.wkbPoint)


def create_raster(
        numpy_dtype, target_path,
        pixel_size=(1, 1), raster_size=(2, 2), projection_epsg=4326,
        origin=(0, 0), n_bands=2, define_nodata=True):
    driver_name, creation_options = DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
    raster_driver = gdal.GetDriverByName(driver_name)
    nx, ny = raster_size
    gdal_type = gdal_array.NumericTypeCodeToGDALTypeCode(numpy_dtype)
    raster = raster_driver.Create(
        target_path, nx, ny, n_bands, gdal_type)
    raster.SetGeoTransform(
        [origin[0], pixel_size[0], 0, origin[1], 0, pixel_size[1]])

    projection = osr.SpatialReference()
    projection_wkt = None
    if projection_epsg is not None:
        projection.ImportFromEPSG(projection_epsg)
        projection_wkt = projection.ExportToWkt()
    if projection_wkt is not None:
        raster.SetProjection(projection_wkt)

    base_array = numpy.full((nx, ny), 1, dtype=numpy_dtype)

    target_nodata = pygeoprocessing.choose_nodata(numpy_dtype)

    for i in range(n_bands):
        band = raster.GetRasterBand(i + 1)
        if define_nodata:
            band.SetNoDataValue(target_nodata)
        band.WriteArray(base_array)
    band = None
    raster = None


class GeometamakerTests(unittest.TestCase):
    """Tests for geometamaker."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp(
            suffix='\U0001f60e')  # ensure unicode support
        self.patcher = patch('geometamaker.config.platformdirs.user_config_dir')
        self.mock_user_config_dir = self.patcher.start()
        self.mock_user_config_dir.return_value = self.workspace_dir

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        self.patcher.stop()
        shutil.rmtree(self.workspace_dir)

    def test_file_does_not_exist(self):
        """Raises exception if given file does not exist."""
        import geometamaker

        with self.assertRaises(FileNotFoundError):
            _ = geometamaker.describe('foo.tif')

    def test_unsupported_file_format(self):
        """Raises exception if given file format is not supported."""
        import geometamaker

        filepath = os.path.join(self.workspace_dir, 'foo.html')
        with open(filepath, 'w') as file:
            file.write('<html />')

        with self.assertRaises(ValueError) as cm:
            _ = geometamaker.describe(filepath)
        actual_message = str(cm.exception)
        expected_message = 'does not appear to be one of'
        self.assertIn(expected_message, actual_message)

    def test_describe_csv(self):
        """Test setting properties on csv."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'data.csv')
        field_names = ['Strings', 'Ints', 'Reals']
        field_values = ['foo', 1, 0.9]
        with open(datasource_path, 'w') as file:
            writer = csv.writer(file)
            writer.writerow(field_names)
            writer.writerow(field_values)

        resource = geometamaker.describe(datasource_path)
        self.assertEqual(
            len(resource.data_model.fields),
            len(field_names))
        self.assertEqual(resource.get_field_description('Strings').type, 'string')
        self.assertEqual(resource.get_field_description('Ints').type, 'integer')
        self.assertEqual(resource.get_field_description('Reals').type, 'number')

        title = 'title'
        description = 'some abstract'
        units = 'mm'
        resource.set_field_description(
            field_names[1],
            title=title,
            description=description)
        # To demonstrate that properties can be added while preserving others
        resource.set_field_description(
            field_names[1],
            units=units)

        field = [field for field in resource.data_model.fields
                 if field.name == field_names[1]][0]
        self.assertEqual(field.title, title)
        self.assertEqual(field.description, description)
        self.assertEqual(field.units, units)

    def test_describe_bad_csv(self):
        """MetadataControl: CSV with extra item in row does not fail."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'data.csv')
        field_names = ['Strings', 'Ints', 'Reals']
        field_values = ['foo', 1, 0.9, 'extra']
        with open(datasource_path, 'w') as file:
            writer = csv.writer(file)
            writer.writerow(field_names)
            writer.writerow(field_values)

        resource = geometamaker.describe(datasource_path)

        resource.write()
        self.assertEqual(
            len(resource.data_model.fields),
            len(field_names))
        self.assertEqual(resource.get_field_description('Strings').type, 'string')
        self.assertEqual(resource.get_field_description('Ints').type, 'integer')
        self.assertEqual(resource.get_field_description('Reals').type, 'number')

    def test_describe_vector(self):
        """Test basic vector."""
        import geometamaker

        field_map = {
            f'field_{k}': k
            for k in _OGR_TYPES_VALUES_MAP}
        for driver, ext in [
                ('GEOJSON', 'geojson'),
                ('ESRI Shapefile', 'shp'),
                ('GPKG', 'gpkg')]:
            with self.subTest(driver=driver, ext=ext):
                datasource_path = os.path.join(
                    self.workspace_dir, f'vector.{ext}')
                create_vector(datasource_path, field_map, driver)

                resource = geometamaker.describe(datasource_path)
                self.assertTrue(isinstance(
                    resource.spatial, geometamaker.models.SpatialSchema))

                resource.write()
                self.assertTrue(os.path.exists(f'{datasource_path}.yml'))

    def test_describe_vector_no_fields(self):
        """Test metadata for basic vector with no fields."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        create_vector(datasource_path, None)

        resource = geometamaker.describe(datasource_path)
        self.assertEqual(len(resource.data_model.layers[0].table.fields), 0)

    def test_describe_raster(self):
        """Test metadata for basic raster."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, projection_epsg=4326)

        resource = geometamaker.describe(datasource_path)
        self.assertTrue(isinstance(
            resource.spatial, geometamaker.models.SpatialSchema))
        self.assertRegex(
            resource.spatial.crs, r'EPSG:[0-9]*')
        self.assertEqual(
            resource.spatial.crs_units, 'degree')

        resource.write()
        self.assertTrue(os.path.exists(f'{datasource_path}.yml'))

    def test_describe_raster_band_description(self):
        """Test adding extra attribute metadata to raster."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        numpy_type = numpy.int16
        create_raster(numpy_type, datasource_path)
        band_number = 1

        resource = geometamaker.describe(datasource_path)
        title = 'title'
        description = 'some abstract'
        units = 'mm'
        resource.set_band_description(
            band_number,
            title=title,
            description=description)
        # To demonstrate that properties can be added while preserving others
        resource.set_band_description(
            band_number,
            units=units)

        raster_info = pygeoprocessing.get_raster_info(datasource_path)
        self.assertEqual(
            len(resource.data_model.bands), raster_info['n_bands'])
        band_idx = band_number - 1
        band = resource.data_model.bands[band_idx]
        self.assertEqual(band.title, title)
        self.assertEqual(band.description, description)
        self.assertEqual(
            band.gdal_type, gdal.GetDataTypeName(raster_info['datatype']))
        self.assertEqual(band.numpy_type, numpy.dtype(numpy_type).name)
        self.assertEqual(band.nodata, raster_info['nodata'][band_idx])
        self.assertEqual(band.units, units)

    def test_describe_raster_no_projection(self):
        """Test for a raster that is missing a projection."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, projection_epsg=None)

        resource = geometamaker.describe(datasource_path)
        self.assertEqual(resource.spatial.crs, 'unknown')

    def test_describe_raster_no_nodata(self):
        """Test for a raster that has no nodata value."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path,
                      projection_epsg=None, define_nodata=False)

        resource = geometamaker.describe(datasource_path)
        self.assertIsNone(resource.data_model.bands[0].nodata)

    def test_describe_raster_band_with_statistics(self):
        """Test band statistics will be included if they already exist."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)
        raster = gdal.OpenEx(datasource_path)
        band = raster.GetRasterBand(1)
        _ = band.ComputeStatistics(0)
        band = raster = None

        resource = geometamaker.describe(datasource_path)
        self.assertEqual(
            resource.data_model.bands[0].gdal_metadata,
            {'STATISTICS_MINIMUM': '1',
             'STATISTICS_MAXIMUM': '1',
             'STATISTICS_MEAN': '1',
             'STATISTICS_STDDEV': '0',
             'STATISTICS_VALID_PERCENT': '100'})

    def test_describe_raster_band_compute_statistics(self):
        """Test band statistics will be computed if they do not already exist."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)

        resource = geometamaker.describe(datasource_path, compute_stats=True)
        self.assertEqual(
            resource.data_model.bands[0].gdal_metadata,
            {'STATISTICS_MINIMUM': '1',
             'STATISTICS_MAXIMUM': '1',
             'STATISTICS_MEAN': '1',
             'STATISTICS_STDDEV': '0',
             'STATISTICS_VALID_PERCENT': '100'})

    def test_describe_raster_band_compute_statistics_valid_percent(self):
        """Test band statistics will be computed if VALID_PERCENT is missing."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)
        raster = gdal.OpenEx(datasource_path)
        band = raster.GetRasterBand(1)
        # Deliberately set stats metadata that do not include VALID_PERCENT
        band.SetMetadataItem('STATISTICS_MINIMUM', '1')
        band.SetMetadataItem('STATISTICS_MAXIMUM', '1')
        band.SetMetadataItem('STATISTICS_MEAN', '1')
        band.SetMetadataItem('STATISTICS_STDDEV', '0')

        resource = geometamaker.describe(datasource_path, compute_stats=True)
        self.assertEqual(
            resource.data_model.bands[0].gdal_metadata,
            {'STATISTICS_MINIMUM': '1',
             'STATISTICS_MAXIMUM': '1',
             'STATISTICS_MEAN': '1',
             'STATISTICS_STDDEV': '0',
             'STATISTICS_VALID_PERCENT': '100'})

    def test_describe_raster_with_gdal_metadata(self):
        """Test raster metadata will be included if they already exist."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)
        raster = gdal.OpenEx(datasource_path)
        raster.SetMetadataItem('FOO', 'BAR')
        raster = None

        resource = geometamaker.describe(datasource_path)
        self.assertEqual(
            resource.data_model.gdal_metadata,
            {'AREA_OR_POINT': 'Area',  # This exists by default
             'FOO': 'BAR'})

    def test_describe_vector_with_gdal_metadata(self):
        """Test vector metadata will be included if they already exist."""
        import geometamaker

        # Not all GDAL vector formats can store metadata, gpkg can.
        vector_path = os.path.join(self.workspace_dir, "temp.gpkg")
        create_vector(vector_path, driver='GPKG')
        vector = gdal.OpenEx(vector_path, gdal.OF_UPDATE)
        layer = vector.GetLayer()
        vector.SetMetadataItem('a', 'b')
        layer.SetMetadataItem('c', 'd')
        layer = vector = None

        resource = geometamaker.describe(vector_path)
        self.assertEqual(
            resource.data_model.gdal_metadata,
            {'a': 'b'})
        # Right now, geometamaker only supports vectors with one layer
        self.assertEqual(
            resource.data_model.layers[0].gdal_metadata,
            {'c': 'd'})

    def test_describe_zip(self):
        """Test metadata for a zipfile includes list of contents."""
        import zipfile
        import geometamaker

        a_name = 'a.txt'
        dir_name = 'subdir'
        os.makedirs(os.path.join(self.workspace_dir, dir_name))
        b_name = os.path.join(dir_name, 'b.txt')
        a_path = os.path.join(self.workspace_dir, a_name)
        b_path = os.path.join(self.workspace_dir, b_name)
        with open(a_path, 'w') as file:
            file.write('')
        with open(b_path, 'w') as file:
            file.write('')

        zip_filepath = os.path.join(self.workspace_dir, 'data.zip')
        with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(a_path, arcname=a_name)
            zipf.write(b_path, arcname=b_name)
        resource = geometamaker.describe(zip_filepath)
        self.assertEqual(resource.sources, [a_name, b_name.replace('\\', '/')])

    def test_describe_tgz(self):
        """Test metadata for .tgz includes correct sources and compression"""
        import tarfile
        import geometamaker

        tgz_path = os.path.join(self.workspace_dir, "test_tgz.tgz")
        raster_path = os.path.join(self.workspace_dir, "temp.tif")
        vector_path = os.path.join(self.workspace_dir, "temp.geojson")
        create_raster(numpy.int8, raster_path)
        create_vector(vector_path)

        with tarfile.open(tgz_path, 'w:gz') as tar:
            for file_path in [raster_path, vector_path]:
                tar.add(file_path, arcname=os.path.basename(file_path))

        resource = geometamaker.describe(tgz_path)
        self.assertEqual(resource.sources, [os.path.basename(raster_path),
                                            os.path.basename(vector_path)])
        self.assertEqual(resource.compression, "gz")

    def test_set_description(self):
        """Test set and get a description for a resource."""

        import geometamaker

        description = 'foo bar'
        resource = geometamaker.models.Resource()
        resource.set_description(description)
        self.assertEqual(resource.get_description(), description)

    def test_set_citation(self):
        """Test set and get a citation for resource."""

        import geometamaker

        citation = 'foo bar'
        resource = geometamaker.models.Resource()
        resource.set_citation(citation)
        self.assertEqual(resource.get_citation(), citation)

    def test_set_contact(self):
        """Test set and get a contact section for a resource."""

        import geometamaker

        org = 'natcap'
        name = 'nat'
        position = 'boss'
        email = 'abc@def'

        resource = geometamaker.models.Resource()
        resource.set_contact(
            organization=org, individual_name=name,
            position_name=position, email=email)
        contact = resource.get_contact()
        self.assertEqual(contact.organization, org)
        self.assertEqual(contact.individual_name, name)
        self.assertEqual(contact.position_name, position)
        self.assertEqual(contact.email, email)

    def test_set_doi(self):
        """Test set and get a doi."""

        import geometamaker

        doi = '10.foo/bar'
        resource = geometamaker.models.Resource()
        resource.set_doi(doi)
        self.assertEqual(resource.get_doi(), doi)

    def test_set_get_edition(self):
        """Test set and get dataset edition."""

        import geometamaker

        resource = geometamaker.models.Resource()
        version = '3.14'
        resource.set_edition(version)
        self.assertEqual(resource.get_edition(), version)

    def test_set_keywords(self):
        """Test set and get keywords."""

        import geometamaker

        resource = geometamaker.models.Resource()
        resource.set_keywords(['foo', 'bar'])

        self.assertEqual(
            resource.get_keywords(),
            ['foo', 'bar'])

    def test_set_and_get_placenames(self):
        """Test set and get placenames."""

        import geometamaker

        resource = geometamaker.models.Resource()
        resource.set_placenames(['Alaska', 'North Pacific'])

        self.assertEqual(
            resource.get_placenames(),
            ['Alaska', 'North Pacific'])

    def test_set_and_get_license(self):
        """Test set and get license for resource."""
        import geometamaker

        resource = geometamaker.models.Resource()
        title = 'CC-BY-4.0'
        path = 'https://creativecommons.org/licenses/by/4.0/'

        resource.set_license(title=title)

        self.assertEqual(
            resource.get_license().__dict__, {'title': title, 'path': ''})

        resource.set_license(path=path)
        self.assertEqual(
            resource.get_license().__dict__, {'title': '', 'path': path})

        resource.set_license(title=title, path=path)
        self.assertEqual(
            resource.get_license().__dict__, {'title': title, 'path': path})

        resource.set_license()
        self.assertEqual(
            resource.get_license().__dict__, {'title': '', 'path': ''})

    def test_set_and_get_lineage(self):
        """Test set and get lineage of a resource."""
        import geometamaker

        resource = geometamaker.models.Resource()
        statement = 'a lineage statment\n is long and has\n many lines.'

        resource.set_lineage(statement)
        self.assertEqual(resource.get_lineage(), statement)

    def test_lineage_roundtrip(self):
        """Test writing and loading yaml with block indicator."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        numpy_type = numpy.int16
        create_raster(numpy_type, datasource_path)

        resource = geometamaker.describe(datasource_path)

        statement = 'a lineage statment\n is long and has\n many lines.'
        resource.set_lineage(statement)
        resource.write()

        new_resource = geometamaker.describe(datasource_path)
        self.assertEqual(new_resource.get_lineage(), statement)

    def test_set_and_get_purpose(self):
        """Test set and get purpose of resource."""
        import geometamaker

        resource = geometamaker.models.Resource()
        purpose = 'foo'
        resource.set_purpose(purpose)
        self.assertEqual(resource.get_purpose(), purpose)

    def test_set_url(self):
        """Test set and get a url."""

        import geometamaker

        url = 'http://foo/bar'
        resource = geometamaker.models.Resource()
        resource.set_url(url)
        self.assertEqual(resource.get_url(), url)

    def test_preexisting_metadata_document(self):
        """Test reading and ammending an existing Metadata document."""
        import geometamaker

        title = 'Title'
        places_list = ['Here']
        band_name = 'The Band'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        resource.set_title(title)
        resource.set_band_description(1, title=band_name)
        resource.placenames = places_list
        resource.write()

        keyword = 'foo'
        new_resource = geometamaker.describe(datasource_path)
        new_resource.set_keywords([keyword])

        # Attributes retained from the original resource
        self.assertEqual(
            new_resource.get_title(), title)
        self.assertEqual(
            new_resource.get_band_description(1).title, band_name)
        self.assertEqual(
            new_resource.placenames, places_list)
        # And attributes added to the new resource
        self.assertEqual(
            new_resource.get_keywords(), [keyword])

    def test_preexisting_doc_new_bands(self):
        """Test existing metadata document when the raster has new bands."""
        import geometamaker

        band_name = 'The Band'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)
        resource = geometamaker.describe(datasource_path)
        resource.set_band_description(1, title=band_name)
        self.assertEqual(resource.get_band_description(1).numpy_type, 'int16')
        resource.write()

        # The raster is modified after it's original metadata was written
        # There's an extra band, and the datatype has changed
        create_raster(numpy.float32, datasource_path, n_bands=2)

        new_resource = geometamaker.describe(datasource_path)

        band1 = new_resource.get_band_description(1)
        self.assertEqual(band1.title, '')
        self.assertEqual(band1.numpy_type, 'float32')
        band2 = new_resource.get_band_description(2)
        self.assertEqual(band2.title, '')
        self.assertEqual(band2.numpy_type, 'float32')

    def test_preexisting_doc_new_fields(self):
        """Test an existing metadata document for vector with new fields."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        field1_name = 'foo'
        description = 'description'
        field_map = {
            field1_name: list(_OGR_TYPES_VALUES_MAP)[0]}
        create_vector(datasource_path, field_map)
        resource = geometamaker.describe(datasource_path)
        resource.set_field_description(field1_name, description=description)
        self.assertEqual(
            resource.get_field_description(field1_name).type, 'Integer')
        resource.write()

        # Modify the dataset by changing the field type of the
        # existing field. And add a second field.
        field2_name = 'bar'
        new_field_map = {
            field1_name: list(_OGR_TYPES_VALUES_MAP)[2],
            field2_name: list(_OGR_TYPES_VALUES_MAP)[3]}
        create_vector(datasource_path, new_field_map)
        new_resource = geometamaker.describe(datasource_path)

        field1 = new_resource.get_field_description(field1_name)
        # The field type changed, so the description does not carry over
        self.assertEqual(field1.description, '')
        self.assertEqual(field1.type, 'Real')
        field2 = new_resource.get_field_description(field2_name)
        self.assertEqual(field2.type, 'String')

    def test_preexisting_metadata_profile_not_overwritten(self):
        """Test doc with contact info is not overwritten by blank profile."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        resource.set_contact(individual_name='alice')
        resource.write()

        # mocking should mean there is no config, but just to be certain
        config = geometamaker.Config()
        config.delete()

        new_resource = geometamaker.describe(datasource_path)
        self.assertEqual(
            new_resource.contact.individual_name, 'alice')

    def test_preexisting_invalid_doc(self):
        """Test when invalid yaml file already exists."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        target_path = f'{datasource_path}.yml'
        with open(target_path, 'w') as file:
            file.write(yaml.dump({'foo': 'bar'}))
        create_raster(numpy.int16, datasource_path)

        # Describing a dataset that already has an invalid yaml
        # sidecar file should issue a warning.
        with self.assertLogs('geometamaker', level='WARNING') as cm:
            _ = geometamaker.describe(datasource_path)
        msg1 = 'Ignoring an existing YAML document'
        msg2 = 'A subsequent call to `.write()` will replace this file'
        actualMessages = ';'.join(cm.output)
        self.assertIn(msg1, actualMessages)
        self.assertIn(msg2, actualMessages)

    def test_backup_invalid_doc_before_overwriting(self):
        """Backup invalid yaml file instead of overwriting."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        target_yml_path = f'{datasource_path}.yml'
        with open(target_yml_path, 'w') as file:
            file.write(yaml.dump({'foo': 'bar'}))
        create_raster(numpy.int16, datasource_path)

        resource = geometamaker.describe(datasource_path)
        resource.write()
        self.assertTrue(os.path.exists(f'{target_yml_path}.bak'))
        self.assertTrue(os.path.exists(os.path.join(resource.metadata_path)))

    def test_write_to_local_workspace(self):
        """Test write metadata to a different location."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)

        temp_dir = tempfile.mkdtemp(dir=self.workspace_dir)
        resource.write(workspace=temp_dir)

        self.assertTrue(
            os.path.exists(os.path.join(
                temp_dir, f'{os.path.basename(datasource_path)}.yml')))

    def test_describe_remote_datasource(self):
        """Test describe on a file at a public url."""
        import geometamaker

        filepath = REMOTE_FILEPATH
        resource = geometamaker.describe(filepath)
        self.assertEqual(resource.path, filepath)

    def test_validate_valid_document(self):
        """Test validate function returns nothing."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        resource.write()

        msgs = geometamaker.validate(resource.metadata_path)
        self.assertIsNone(msgs)

    def test_validate_invalid_document(self):
        """Test validate function returns messages."""
        import geometamaker
        from geometamaker import utils

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        resource.write()

        # Manually modify the metadata doc
        with open(resource.metadata_path, 'r') as file:
            yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        yaml_dict['foo'] = 'bar'
        yaml_dict['keywords'] = 'not a list'
        with open(resource.metadata_path, 'w') as file:
            file.write(utils.yaml_dump(yaml_dict))

        error = geometamaker.validate(resource.metadata_path)

        self.assertEqual(error.error_count(), 2)
        msg_dict = {', '.join(e['loc']): e['msg'] for e in error.errors()}
        self.assertIn('foo', msg_dict)
        self.assertIn('Extra inputs are not permitted', msg_dict['foo'])
        self.assertIn('keywords', msg_dict)
        self.assertIn('Input should be a valid list', msg_dict['keywords'])

    def test_describe_validate_dir(self):
        """Test describe and validate functions that walk directory tree."""
        import geometamaker

        subdir = os.path.join(self.workspace_dir, 'subdir')
        os.makedirs(subdir)
        raster1 = os.path.join(self.workspace_dir, 'foo.tif')
        txt1 = os.path.join(self.workspace_dir, 'foo.txt')
        raster2 = os.path.join(subdir, 'foo.tif')
        txt2 = os.path.join(subdir, 'foo.txt')

        create_raster(numpy.int16, raster1)
        create_raster(numpy.int16, raster2)
        with open(txt1, 'w') as file:
            file.write('')
        with open(txt2, 'w') as file:
            file.write('')

        # Only 1 eligible file to describe in the root dir
        geometamaker.describe_collection(self.workspace_dir, depth=1,
                                         describe_files=True)
        yaml_files, msgs = geometamaker.validate_dir(self.workspace_dir)
        self.assertEqual(len(yaml_files), 1)

        # 2 eligible files described with default depth
        geometamaker.describe_collection(self.workspace_dir,
                                         describe_files=True)
        yaml_files, msgs = geometamaker.validate_dir(
            self.workspace_dir)
        self.assertEqual(len(yaml_files), 2)

    def test_validate_dir_handles_exception(self):
        """Test validate_dir function handles yaml exceptions."""
        import geometamaker

        yaml_path = os.path.join(self.workspace_dir, 'foo.yml')
        with open(yaml_path, 'w') as file:
            # An example from a yaml file containing some jinja templating.
            # This should raise a yaml.scanner.ScannerError:
            # while scanning for the next token
            # found character '%' that cannot start any token
            file.write('{% set name = "simplejson" %}')

        yaml_files, msgs = geometamaker.validate_dir(self.workspace_dir)
        self.assertEqual(len(yaml_files), 1)
        self.assertEqual(msgs[0], 'is not a readable yaml document')

    def test_describe_collection_with_shapefile(self):
        """Test describe directory containing a multi-file dataset."""
        import geometamaker

        # Create several files with the same root name. Four of them
        # will be components of shapefile. One more will be a CSV.
        # We expect to describe exactly two datasets.
        root_name = 'foo'
        vector_path = os.path.join(self.workspace_dir, f'{root_name}.shp')
        create_vector(vector_path, None, 'ESRI Shapefile')
        csv_path = os.path.join(self.workspace_dir, f'{root_name}.csv')
        with open(csv_path, 'w') as file:
            file.write('a,b,c')

        file_count = 5
        describe_count = 2
        self.assertEqual(len(os.listdir(self.workspace_dir)), file_count)

        with patch.object(
                geometamaker.geometamaker, 'describe',
                wraps=geometamaker.geometamaker.describe) as mock_describe:
            geometamaker.describe_collection(self.workspace_dir,
                                             describe_files=True)

        self.assertEqual(mock_describe.call_count, describe_count)
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_dir, f'{root_name}.shp.yml')))
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_dir, f'{root_name}.csv.yml')))

    def test_describe_collection_with_depth(self):
        """Test describe_collection with depth and exclude_regex parameters"""
        import geometamaker

        collection_path = os.path.join(self.workspace_dir, "collection")
        os.mkdir(collection_path)

        # Create csv in main directory
        csv_path = os.path.join(collection_path, 'table.csv')
        with open(csv_path, 'w') as file:
            file.write('a,b,c')

        # Create csv in main directory (to exclude based on regex)
        csv_path_excluded = os.path.join(collection_path, 'exclude_this.csv')
        with open(csv_path_excluded, 'w') as file:
            file.write('a,b,c')

        # Create hidden csv in main directory (excluded by default)
        csv_path_hidden = os.path.join(collection_path, '.table.csv')
        with open(csv_path_hidden, 'w') as file:
            file.write('a,b,c')

        # Create raster in subdirectory
        subdir1 = os.path.join(collection_path, "subdir1")
        os.mkdir(subdir1)
        raster_path = os.path.join(subdir1, 'raster.tif')
        create_raster(numpy.int16, raster_path)

        metadata = geometamaker.describe_collection(
            collection_path, depth=1, exclude_regex="exclude_this*")
        metadata.write()
        self.assertTrue(os.path.exists(collection_path+"-metadata.yml"))
        # assert that with depth=1, items list only includes csv and
        # subdir and excludes exclude_this.csv
        self.assertEqual(len(metadata.items), 2)

        geometamaker.describe_collection(
            collection_path, depth=1, exclude_regex="exclude_this*",
            describe_files=True)
        self.assertTrue(os.path.exists(csv_path+".yml"))
        self.assertFalse(os.path.exists(raster_path+".yml"))
        self.assertFalse(os.path.exists(csv_path_excluded+".yml"))

        geometamaker.describe_collection(collection_path, depth=2,
                                         describe_files=True)
        self.assertTrue(os.path.exists(raster_path+".yml"))

    def test_describe_collection_existing_yml(self):
        """test `describe_collection` does not overwrite existing attributes"""
        import geometamaker

        # Create collection with 1 item
        collection_path = os.path.join(self.workspace_dir, "collection")
        os.mkdir(collection_path)

        csv_path = os.path.join(collection_path, 'table.csv')
        with open(csv_path, 'w') as file:
            file.write('a,b,c')

        resource = geometamaker.describe_collection(collection_path)

        # Manually edit the metadata description and an item description
        resource.set_description("some description")
        resource.items[0].description = "item 1 description"
        resource.write()

        new_resource = geometamaker.describe_collection(collection_path)

        # check that the manual descriptions are still present
        self.assertEqual(new_resource.get_description(), "some description")
        self.assertEqual(new_resource.items[0].description,
                         "item 1 description")

    def test_describe_collection_preexisting_invalid_yml(self):
        """test `describe_collection` when invalid yaml file already exists."""
        import geometamaker

        collection_path = os.path.join(self.workspace_dir, "collection")
        os.mkdir(collection_path)

        # Setup an incompatible yml file at the expected path
        target_yml_path = f'{collection_path}-metadata.yml'
        with open(target_yml_path, 'w') as file:
            file.write(yaml.dump({'foo': 'bar'}))

        csv_path = os.path.join(collection_path, 'table.csv')
        with open(csv_path, 'w') as file:
            file.write('a,b,c')


        # Describing a collection that already has an invalid yaml
        # sidecar file should issue a warning.
        with self.assertLogs('geometamaker', level='WARNING') as cm:
            _ = geometamaker.describe_collection(collection_path)
        msg1 = 'Ignoring an existing YAML document'
        msg2 = 'A subsequent call to `.write()` will replace this file'
        actualMessages = ';'.join(cm.output)
        self.assertIn(msg1, actualMessages)
        self.assertIn(msg2, actualMessages)

    def test_describe_directory_error(self):
        """Test that `describing` a directory raises useful error"""
        import geometamaker

        with self.assertRaises(ValueError) as cm:
            _ = geometamaker.describe(self.workspace_dir)
        msg = ("If you are trying to create metadata for the files within a "
               "directory and/or the directory itself, please use "
               "`geometamaker.describe_collection` instead.")
        self.assertIn(msg, str(cm.exception))


class ValidationTests(unittest.TestCase):
    """Tests for geometamaker type validation."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        shutil.rmtree(self.workspace_dir)

    def test_init_resource_raises_ValidationError(self):
        import geometamaker

        with self.assertRaises(ValidationError):
            _ = geometamaker.models.Resource(title=0)

        with self.assertRaises(ValidationError):
            _ = geometamaker.models.Profile(license='foo')

    def test_assignment_raises_ValidationError(self):
        import geometamaker

        resource = geometamaker.models.Resource()
        with self.assertRaises(ValidationError):
            resource.title = 0

        profile = geometamaker.models.Profile()
        with self.assertRaises(ValidationError):
            profile.license = 'foo'

    def test_extra_fields_raises_ValidationError(self):
        import geometamaker

        with self.assertRaises(ValidationError):
            _ = geometamaker.models.Resource(foo=0)


class ConfigurationTests(unittest.TestCase):
    """Tests for geometamaker configuration."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        shutil.rmtree(self.workspace_dir)

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_user_configuration(self, mock_user_config_dir):
        """Test existing config populates resource."""
        mock_user_config_dir.return_value = self.workspace_dir
        import geometamaker

        contact = {
            'individual_name': 'bob'
        }
        license = {
            'title': 'CC-BY-4'
        }

        profile = geometamaker.Profile()
        profile.set_contact(**contact)
        profile.set_license(**license)

        config = geometamaker.Config()
        config.save(profile)

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        self.assertEqual(contact['individual_name'],
                         resource.get_contact().individual_name)
        self.assertEqual(license['title'], resource.get_license().title)

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_partial_user_configuration(self, mock_user_config_dir):
        """Test existing config populates resource."""
        mock_user_config_dir.return_value = self.workspace_dir
        import geometamaker
        from geometamaker import models

        contact = {
            'individual_name': 'bob'
        }

        profile = models.Profile()
        profile.set_contact(**contact)
        config = geometamaker.Config()
        config.save(profile)

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        self.assertEqual(contact['individual_name'],
                         resource.get_contact().individual_name)
        # expect a default value for license title
        self.assertEqual('', resource.get_license().title)

    def test_missing_config(self):
        """Test default profile is instantiated if config file is missing."""
        import geometamaker
        config = geometamaker.Config('foo/path')
        self.assertEqual(
            config.profile.contact, geometamaker.models.ContactSchema())
        self.assertEqual(
            config.profile.license, geometamaker.models.LicenseSchema())

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_invalid_config(self, mock_user_config_dir):
        """Test default profile is instantiated if config is invalid."""
        mock_user_config_dir.return_value = self.workspace_dir
        import geometamaker.config

        config_path = os.path.join(
            geometamaker.config.platformdirs.user_config_dir(),
            geometamaker.config.CONFIG_FILENAME)
        with open(config_path, 'w') as file:
            file.write(yaml.dump({'bad': 'data'}))

        config = geometamaker.config.Config()
        self.assertEqual(
            config.profile.contact, geometamaker.models.ContactSchema())
        self.assertEqual(
            config.profile.license, geometamaker.models.LicenseSchema())

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_delete_config(self, mock_user_config_dir):
        """Test delete method of Config."""
        mock_user_config_dir.return_value = self.workspace_dir
        import geometamaker.config

        config_path = os.path.join(
            geometamaker.config.platformdirs.user_config_dir(),
            geometamaker.config.CONFIG_FILENAME)
        with open(config_path, 'w') as file:
            file.write(yaml.dump({'bad': 'data'}))

        config = geometamaker.config.Config()
        config.delete()
        self.assertFalse(os.path.exists(config_path))


class CLITests(unittest.TestCase):
    """Tests for geometamaker Command-Line Interface."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
        shutil.rmtree(self.workspace_dir)

    def test_cli_describe(self):
        """CLI: test describe."""
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        result = runner.invoke(cli.cli, ['describe', datasource_path])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, '')
        self.assertTrue(os.path.exists(f'{datasource_path}.yml'))

    def test_cli_describe_with_stats(self):
        """CLI: test describe with stats option."""
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ['describe', '--stats', '-nw', datasource_path])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('STATISTICS_VALID_PERCENT', result.output)

    def test_cli_describe_remote_file(self):
        """CLI: test describe on a remote file at a URL."""
        from geometamaker import cli

        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ['describe', '--no-write', REMOTE_FILEPATH])
        self.assertEqual(result.exit_code, 0)
        # one of many things expected to print to stdout:
        self.assertIn('last_modified', result.output)

        result = runner.invoke(cli.cli, ['describe', REMOTE_FILEPATH])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Try using the --no-write flag', result.output)

    def test_cli_describe_file_does_not_exist(self):
        """CLI: test describe on files that do not exist."""
        from geometamaker import cli

        runner = CliRunner()
        result = runner.invoke(cli.cli, ['describe', 'foo.tif'])
        self.assertEqual(result.exit_code, 2)
        self.assertIn('does not exist', result.output)

        result = runner.invoke(
            cli.cli, ['describe', '--no-write', 'https://foo.tif'])
        self.assertEqual(result.exit_code, 2)
        self.assertIn('does not exist', result.output)

    def test_cli_describe_prompt_before_overwrite(self):
        """CLI: test describe asks for confirmation when data could be lost."""
        import geometamaker
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        target_path = f'{datasource_path}.yml'
        # Setup an incompatible yml doc at the expected path.
        with open(target_path, 'w') as file:
            file.write(yaml.dump({'foo': 'bar'}))
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        # Describe should prompt for confirmation before overwriting the file
        result = runner.invoke(
            cli.cli, ['describe', datasource_path], input='n\n')
        self.assertEqual(result.exit_code, 1)  # Aborted
        # The incompatible yml doc should still exist.
        with self.assertRaises(ValueError):
            _ = geometamaker.validate(target_path)

        with self.assertLogs('geometamaker', level='WARNING') as cm:
            result = runner.invoke(
                cli.cli, ['describe', datasource_path], input='y\n')
        self.assertEqual(result.exit_code, 0)  # Did not abort.
        # Should have a valid yml doc.
        error = geometamaker.validate(target_path)
        self.assertIsNone(error)
        # Logging for CLI should be filtered
        msg1 = 'Ignoring an existing YAML document'
        msg2 = 'A subsequent call to `.write()` will replace this file'
        actualMessages = ';'.join(cm.output)
        self.assertIn(msg1, actualMessages)
        self.assertNotIn(msg2, actualMessages)

    def test_cli_describe_directory(self):
        """CLI: test describe with a directory."""
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        result = runner.invoke(cli.cli, ['describe', self.workspace_dir])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, '')
        self.assertTrue(os.path.exists(f'{datasource_path}.yml'))
        self.assertTrue(os.path.exists(f'{self.workspace_dir}-metadata.yml'))

    def test_cli_describe_directory_collection_options(self):
        """CLI: test describe with a directory with various options."""
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            ['describe', '--no-write', '--collection-only', self.workspace_dir])
        self.assertEqual(result.exit_code, 0)
        # one of many things expected to print to stdout:
        self.assertIn('last_modified', result.output)
        self.assertFalse(os.path.exists(f'{datasource_path}.yml'))
        self.assertFalse(os.path.exists(f'{self.workspace_dir}-metadata.yml'))

        result = runner.invoke(
            cli.cli,
            ['describe', '--collection-only', self.workspace_dir])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, '')
        self.assertFalse(os.path.exists(f'{datasource_path}.yml'))
        self.assertTrue(os.path.exists(f'{self.workspace_dir}-metadata.yml'))


    def test_cli_validate_valid(self):
        """CLI: test validate creates no output for valid document."""
        from geometamaker import cli

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        _ = runner.invoke(cli.cli, ['describe', datasource_path])
        result = runner.invoke(cli.cli, ['validate', f'{datasource_path}.yml'])
        # print(result)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, '')

    def test_cli_validate_invalid(self):
        """CLI: test validate generates stdout for invalid document."""
        from geometamaker import cli
        from geometamaker import utils

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        runner = CliRunner()
        _ = runner.invoke(cli.cli, ['describe', datasource_path])

        # Manually modify the metadata doc
        document_path = f'{datasource_path}.yml'
        with open(document_path, 'r') as file:
            yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        yaml_dict['foo'] = 'bar'
        yaml_dict['keywords'] = 'not a list'
        with open(document_path, 'w') as file:
            file.write(utils.yaml_dump(yaml_dict))

        result = runner.invoke(cli.cli, ['validate', document_path])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('2 validation errors', result.output)

    def test_cli_validate_recursive(self):
        """CLI: test validate with recursive option."""
        import geometamaker
        from geometamaker import cli

        subdir = os.path.join(self.workspace_dir, 'subdir')
        os.makedirs(subdir)
        raster1 = os.path.join(self.workspace_dir, 'raster1.tif')
        yml1 = os.path.join(self.workspace_dir, 'foo.yml')
        raster2 = os.path.join(subdir, 'raster2.tif')
        yml2 = os.path.join(subdir, 'foo.yml')

        create_raster(numpy.int16, raster1)
        create_raster(numpy.int16, raster2)
        with open(yml1, 'w') as file:
            file.write('')
        with open(yml2, 'w') as file:
            file.write('')

        geometamaker.describe_collection(self.workspace_dir,
                                         describe_files=True)

        runner = CliRunner()
        result = runner.invoke(cli.cli, ['validate', self.workspace_dir])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            u'\u2713' + f' {os.path.relpath(raster1, self.workspace_dir)}.yml',
            result.output)
        self.assertIn(
            u'\u2713' + f' {os.path.relpath(raster2, self.workspace_dir)}.yml',
            result.output)
        self.assertIn(
            u'\u25CB' + f' {os.path.relpath(yml1, self.workspace_dir)}'
            f' does not appear to be a geometamaker document',
            result.output)
        self.assertIn(
            u'\u25CB' + f' {os.path.relpath(yml2, self.workspace_dir)}'
            f' does not appear to be a geometamaker document',
            result.output)

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_cli_config_prompts(self, mock_user_config_dir):
        """CLI: test config inputs can be given via stdin."""
        mock_user_config_dir.return_value = self.workspace_dir
        from geometamaker import cli
        from geometamaker import config

        runner = CliRunner()
        inputs = {
            'individual_name': 'name',
            'email': '',
            'organization': 'org',
            'position_name': 'position',
            'license_title': 'license',
            'license_url': ''
        }
        result = runner.invoke(cli.cli, ['config'],
                               input='\n'.join(inputs.values()) + '\n')
        self.assertEqual(result.exit_code, 0)

        profile = config.Config().profile
        self.assertEqual(profile.contact.individual_name, inputs['individual_name'])
        self.assertEqual(profile.contact.email, inputs['email'])
        self.assertEqual(profile.contact.organization, inputs['organization'])
        self.assertEqual(profile.contact.position_name, inputs['position_name'])
        self.assertEqual(profile.license.title, inputs['license_title'])
        self.assertEqual(profile.license.path, inputs['license_url'])

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_cli_config_print(self, mock_user_config_dir):
        """CLI: test config print callback."""
        mock_user_config_dir.return_value = self.workspace_dir
        from geometamaker import cli
        from geometamaker import config

        runner = CliRunner()
        result = runner.invoke(cli.cli, ['config', '--print'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.rstrip(), str(config.Config()))

    @patch('geometamaker.config.platformdirs.user_config_dir')
    def test_cli_config_delete(self, mock_user_config_dir):
        """CLI: test config delete callback."""
        mock_user_config_dir.return_value = self.workspace_dir
        from geometamaker import cli

        runner = CliRunner()

        # Abort when asked to confirm
        result = runner.invoke(cli.cli, ['config', '--delete'], input='n\n')
        self.assertEqual(result.exit_code, 1)

        # Confirm wih yes
        result = runner.invoke(cli.cli, ['config', '--delete'], input='y\n')
        self.assertEqual(result.exit_code, 0)
