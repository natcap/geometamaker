import csv
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
        """MetadataControl: raises exception if given file does not exist."""
        import geometamaker

        with self.assertRaises(FileNotFoundError):
            _ = geometamaker.describe('foo.tif')

    # def test_blank_geometamaker.describe(self):
    #     """MetadataControl: template has expected properties."""
    #     import geometamaker

    #     target_filepath = os.path.join(self.workspace_dir, 'mcf.yml')

    #     mc = geometamaker.describe()
    #     mc.validate()
    #     mc._write_mcf(target_filepath)

    #     with open(target_filepath, 'r') as file:
    #         actual = yaml.safe_load(file)
    #     with open(os.path.join(REGRESSION_DATA, 'template.yml'), 'r') as file:
    #         expected = yaml.safe_load(file)

    #     self.assertEqual(actual, expected)

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

    def test_set_contact_validates(self):
        """MetadataControl: invalid type raises ValidationError."""

        import geometamaker

        postalcode = 55555  # should be a string
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        with self.assertRaises(ValidationError):
            mc.set_contact(postalcode=postalcode)

    def test_set_doi(self):
        """MetadataControl: set and get a doi."""

        import geometamaker

        doi = '10.foo/bar'
        mc = geometamaker.describe()
        mc.set_doi(doi)
        self.assertEqual(mc.get_doi(), doi)

    def test_set_get_edition(self):
        """MetadataControl: set and get dataset edition."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        version = '3.14'
        mc.set_edition(version)
        self.assertEqual(mc.get_edition(), version)

    def test_set_edition_validates(self):
        """MetadataControl: test set edition raises ValidationError."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        version = 3.14  # should be a string
        with self.assertRaises(ValidationError):
            mc.set_edition(version)

    def test_set_keywords(self):
        """MetadataControl: set keywords to default section."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        mc.set_keywords(['foo', 'bar'])

        self.assertEqual(
            mc.mcf['identification']['keywords']['default']['keywords'],
            ['foo', 'bar'])

    def test_set_keywords_to_section(self):
        """MetadataControl: set keywords to named section."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        mc.set_keywords(['foo', 'bar'], section='first')
        mc.set_keywords(['baz'], section='second')

        self.assertEqual(
            mc.mcf['identification']['keywords']['first']['keywords'],
            ['foo', 'bar'])
        self.assertEqual(
            mc.mcf['identification']['keywords']['second']['keywords'],
            ['baz'])

    def test_overwrite_keywords(self):
        """MetadataControl: overwrite keywords in existing section."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        mc.set_keywords(['foo', 'bar'])
        mc.set_keywords(['baz'])

        self.assertEqual(
            mc.mcf['identification']['keywords']['default']['keywords'],
            ['baz'])

    def test_keywords_raises_validation_error(self):
        """MetadataControl: set keywords validates."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        with self.assertRaises(ValidationError):
            mc.set_keywords('foo', 'bar')

    def test_set_and_get_license(self):
        """MetadataControl: set purpose of dataset."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        name = 'CC-BY-4.0'
        url = 'https://creativecommons.org/licenses/by/4.0/'

        mc.set_license(name=name)
        self.assertEqual(
            mc.mcf['identification']['accessconstraints'],
            'license')
        self.assertEqual(mc.get_license(), {'name': name, 'url': ''})

        mc.set_license(url=url)
        self.assertEqual(mc.get_license(), {'name': '', 'url': url})

        mc.set_license(name=name, url=url)
        self.assertEqual(mc.get_license(), {'name': name, 'url': url})

        mc.set_license()
        self.assertEqual(mc.get_license(), {'name': '', 'url': ''})
        self.assertEqual(
            mc.mcf['identification']['accessconstraints'],
            'otherRestrictions')

    def test_set_license_validates(self):
        """MetadataControl: test set license raises ValidationError."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        name = 4.0  # should be a string
        with self.assertRaises(ValidationError):
            mc.set_license(name=name)
        with self.assertRaises(ValidationError):
            mc.set_license(url=name)

    def test_set_and_get_lineage(self):
        """MetadataControl: set lineage of dataset."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        statement = 'a lineage statment'

        mc.set_lineage(statement)
        self.assertEqual(mc.get_lineage(), statement)

    def test_set_lineage_validates(self):
        """MetadataControl: test set lineage raises ValidationError."""

        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        lineage = ['some statement']  # should be a string
        with self.assertRaises(ValidationError):
            mc.set_lineage(lineage)

    def test_set_and_get_purpose(self):
        """MetadataControl: set purpose of dataset."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        purpose = 'foo'
        mc.set_purpose(purpose)
        self.assertEqual(mc.get_purpose(), purpose)

    def test_set_url(self):
        """MetadataControl: set and get a url."""

        import geometamaker

        url = 'http://foo/bar'
        mc = geometamaker.describe()
        mc.set_url(url)
        self.assertEqual(mc.get_url(), url)

    def test_preexisting_mc_raster(self):
        """MetadataControl: test reading and ammending an existing MCF raster."""
        import geometamaker

        title = 'Title'
        keyword = 'foo'
        band_name = 'The Band'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        mc.set_title(title)
        mc.set_band_description(1, name=band_name)
        mc.write()

        new_mc = geometamaker.describe(datasource_path)
        new_mc.set_keywords([keyword])

        self.assertEqual(new_mc.mcf['metadata']['hierarchylevel'], 'dataset')
        self.assertEqual(
            new_mc.get_title(), title)
        self.assertEqual(
            new_mc.get_band_description(1)['name'], band_name)
        self.assertEqual(
            new_mc.get_keywords()['keywords'], [keyword])

    def test_preexisting_mc_raster_new_bands(self):
        """MetadataControl: test existing MCF when the raster has new bands."""
        import geometamaker

        band_name = 'The Band'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path, n_bands=1)
        mc = geometamaker.describe(datasource_path)
        mc.set_band_description(1, name=band_name)
        self.assertEqual(mc.get_band_description(1)['type'], 'integer')
        mc.write()

        # The raster is modified after it's original metadata was written
        # There's an extra band, and the datatype has changed
        create_raster(numpy.float32, datasource_path, n_bands=2)

        new_mc = geometamaker.describe(datasource_path)

        band1 = new_mc.get_band_description(1)
        self.assertEqual(band1['name'], band_name)
        self.assertEqual(band1['type'], 'number')
        band2 = new_mc.get_band_description(2)
        self.assertEqual(band2['name'], '')
        self.assertEqual(band2['type'], 'number')

    def test_preexisting_mc_vector(self):
        """MetadataControl: test reading and ammending an existing MCF vector."""
        import geometamaker

        title = 'Title'
        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        field_name = 'foo'
        description = 'description'
        field_map = {
            field_name: list(_OGR_TYPES_VALUES_MAP)[0]}
        create_vector(datasource_path, field_map)
        mc = geometamaker.describe(datasource_path)
        mc.set_title(title)
        mc.set_field_description(field_name, abstract=description)
        mc.write()

        new_mc = geometamaker.describe(datasource_path)

        self.assertEqual(new_mc.mcf['metadata']['hierarchylevel'], 'dataset')
        self.assertEqual(
            new_mc.get_title(), title)
        self.assertEqual(
            new_mc.get_field_description(field_name)['abstract'], description)

    def test_preexisting_mc_vector_new_fields(self):
        """MetadataControl: test an existing MCF for vector with new fields."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'vector.geojson')
        field1_name = 'foo'
        description = 'description'
        field_map = {
            field1_name: list(_OGR_TYPES_VALUES_MAP)[0]}
        create_vector(datasource_path, field_map)
        mc = geometamaker.describe(datasource_path)
        mc.set_field_description(field1_name, abstract=description)
        self.assertEqual(
            mc.get_field_description(field1_name)['type'], 'integer')
        mc.write()

        # Modify the dataset by changing the field type of the
        # existing field. And add a second field.
        field2_name = 'bar'
        new_field_map = {
            field1_name: list(_OGR_TYPES_VALUES_MAP)[2],
            field2_name: list(_OGR_TYPES_VALUES_MAP)[3]}
        create_vector(datasource_path, new_field_map)
        new_mc = geometamaker.describe(datasource_path)

        field1 = new_mc.get_field_description(field1_name)
        self.assertEqual(field1['abstract'], description)
        self.assertEqual(field1['type'], 'number')
        field2 = new_mc.get_field_description(field2_name)
        self.assertEqual(field2['type'], 'string')

    def test_invalid_preexisting_mcf(self):
        """MetadataControl: test overwriting an existing invalid MetadataControl."""
        import geometamaker
        title = 'Title'
        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)
        mc.set_title(title)

        # delete a required property and ensure invalid MetadataControl
        del mc.mcf['mcf']
        with self.assertRaises(ValidationError):
            mc.validate()
        mc.write()  # intentionally writing an invalid MetadataControl

        new_mc = geometamaker.describe(datasource_path)

        # The new MetadataControl should not have values from the invalid MetadataControl
        self.assertEqual(
            new_mc.mcf['identification']['title'], '')

        try:
            new_mc.validate()
        except (MCFValidationError, SchemaError) as e:
            self.fail(
                'unexpected validation error occurred\n'
                f'{e}')
        try:
            new_mc.write()
        except Exception as e:
            self.fail(
                'unexpected write error occurred\n'
                f'{e}')

    def test_write_to_local_workspace(self):
        """MetadataControl: test write metadata to a different location."""
        import geometamaker

        datasource_path = os.path.join(self.workspace_dir, 'raster.tif')
        create_raster(numpy.int16, datasource_path)
        mc = geometamaker.describe(datasource_path)

        temp_dir = tempfile.mkdtemp(dir=self.workspace_dir)
        mc.write(workspace=temp_dir)

        self.assertTrue(
            os.path.exists(os.path.join(
                temp_dir, f'{os.path.basename(datasource_path)}.yml')))
        self.assertTrue(
            os.path.exists(os.path.join(
                temp_dir, f'{os.path.basename(datasource_path)}.xml')))
