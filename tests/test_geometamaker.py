import csv
import os
import shutil
import tempfile
import unittest

import numpy
from osgeo import gdal
from osgeo import gdal_array
from osgeo import ogr
from osgeo import osr
import pygeoprocessing
from pygeoprocessing.geoprocessing_core import DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
import shapely
import yaml

REGRESSION_DATA = os.path.join(
    os.path.dirname(__file__), 'data')

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
        pixel_size=(1, 1), projection_epsg=4326,
        origin=(0, 0), n_bands=2):
    driver_name, creation_options = DEFAULT_GTIFF_CREATION_TUPLE_OPTIONS
    raster_driver = gdal.GetDriverByName(driver_name)
    ny, nx = (2, 2)
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

    base_array = numpy.full((2, 2), 1, dtype=numpy_dtype)
    target_nodata = pygeoprocessing.choose_nodata(numpy_dtype)

    for i in range(n_bands):
        band = raster.GetRasterBand(i + 1)
        band.SetNoDataValue(target_nodata)
        band.WriteArray(base_array)
    band = None
    raster = None


class MetadataControlTests(unittest.TestCase):
    """Tests for geometamaker."""

    def setUp(self):
        """Override setUp function to create temp workspace directory."""
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Override tearDown function to remove temporary directory."""
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
            len(resource.schema.fields),
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

        field = [field for field in resource.schema.fields
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
            len(resource.schema.fields),
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
        self.assertEqual(len(resource.schema.fields), 0)

    def test_describe_raster(self):
        """Test metadata for basic raster."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)

        resource = geometamaker.describe(datasource_path)
        self.assertTrue(isinstance(
            resource.spatial, geometamaker.models.SpatialSchema))

        resource.write()
        self.assertTrue(os.path.exists(f'{datasource_path}.yml'))

    def test_raster_attributes(self):
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
            len(resource.schema.bands), raster_info['n_bands'])
        band_idx = band_number - 1
        band = resource.schema.bands[band_idx]
        self.assertEqual(band.title, title)
        self.assertEqual(band.description, description)
        self.assertEqual(band.gdal_type, raster_info['datatype'])
        self.assertEqual(band.numpy_type, numpy.dtype(numpy_type).name)
        self.assertEqual(band.nodata, raster_info['nodata'][band_idx])
        self.assertEqual(band.units, units)

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
        statement = 'a lineage statment'

        resource.set_lineage(statement)
        self.assertEqual(resource.get_lineage(), statement)

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
        keyword = 'foo'
        band_name = 'The Band'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        resource = geometamaker.describe(datasource_path)
        resource.set_title(title)
        resource.set_band_description(1, title=band_name)
        resource.write()

        new_resource = geometamaker.describe(datasource_path)
        new_resource.set_keywords([keyword])

        self.assertEqual(
            new_resource.get_title(), title)
        self.assertEqual(
            new_resource.get_band_description(1).title, band_name)
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

    def test_preexisting_incompatible_doc(self):
        """Test when yaml file not created by geometamaker already exists."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        target_path = f'{datasource_path}.yml'
        with open(target_path, 'w') as file:
            file.write(yaml.dump({'foo': 'bar'}))
        create_raster(numpy.int16, datasource_path)

        # Describing a dataset that already has an incompatible yaml
        # sidecar file should log a warning.
        with self.assertLogs('geometamaker', level='WARNING') as cm:
            resource = geometamaker.describe(datasource_path)
        expected_message = 'exists but is not compatible with'
        self.assertIn(expected_message, ''.join(cm.output))

        # After writing new doc, check it has expected property
        resource.write()
        with open(target_path, 'r') as file:
            yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        self.assertIn('metadata_version', yaml_dict)
        self.assertIn('geometamaker', yaml_dict['metadata_version'])

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
