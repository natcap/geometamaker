import dataclasses
import logging
import os
import uuid
from datetime import datetime

import frictionless
import fsspec
import pygeoprocessing
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
import yaml

from . import models


# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
class _NoAliasDumper(yaml.SafeDumper):
    """Keep the yaml human-readable by avoiding anchors and aliases."""

    def ignore_aliases(self, data):
        return True


LOGGER = logging.getLogger(__name__)

# MCF_SCHEMA['properties']['identification']['properties'][
#     'keywords']['patternProperties']['^.*'][
#     'required'] = ['keywords', 'keywords_type']
# to accomodate tables that do not represent spatial content:

def get_file_type(filepath):
    # TODO: guard against classifying netCDF, HDF5, etc as GDAL rasters,
    # we'll want a different data model for multi-dimensional arrays.

    # GDAL considers CSV a vector, so check against frictionless
    # first.
    filetype = frictionless.describe(filepath).type
    if filetype == 'table':
        return filetype
    gis_type = pygeoprocessing.get_gis_type(filepath)
    if gis_type == pygeoprocessing.VECTOR_TYPE:
        return 'vector'
    if gis_type == pygeoprocessing.RASTER_TYPE:
        return 'raster'
    raise ValueError()


def describe_vector(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()
    fields = []
    vector = gdal.OpenEx(source_dataset_path, gdal.OF_VECTOR)
    layer = vector.GetLayer()
    for fld in layer.schema:
        fields.append(
            models.FieldSchema(name=fld.name, type=fld.type))
    vector = layer = None
    description['schema'] = models.TableSchema(fields=fields)

    info = pygeoprocessing.get_vector_info(source_dataset_path)
    spatial = {
        'bounding_box': info['bounding_box'],
        'crs': info['projection_wkt']
    }
    description['spatial'] = models.SpatialSchema(**spatial)
    description['sources'] = info['file_list']
    return description


def describe_raster(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()

    bands = []
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    for i in range(info['n_bands']):
        b = i + 1
        # band = raster.GetRasterBand(b)
        # datatype = 'integer' if band.DataType < 6 else 'number'
        bands.append(models.BandSchema(
            index=b,
            gdal_type=info['datatype'],
            numpy_type=info['numpy_type'],
            nodata=info['nodata'][i]))
    description['schema'] = models.RasterSchema(
        bands=bands,
        pixel_size=info['pixel_size'],
        raster_size=info['raster_size'])
    description['spatial'] = models.SpatialSchema(
        bounding_box=info['bounding_box'],
        crs=info['projection_wkt'])
    description['sources'] = info['file_list']
    return description


def describe_table(source_dataset_path):
    return frictionless.describe(
        source_dataset_path, stats=True).to_dict()


DESRCIBE_FUNCS = {
    'table': describe_table,
    'vector': describe_vector,
    'raster': describe_raster
}

RESOURCE_MODELS = {
    'table': models.TableResource,
    'vector': models.VectorResource,
    'raster': models.RasterResource
}


class MetadataControl(object):
    """Encapsulates the Metadata Control File and methods for populating it.

    A Metadata Control File (MCF) is a YAML file that complies with the
    MCF specification defined by pygeometa.
    https://github.com/geopython/pygeometa

    Attributes:
        datasource (string): path to dataset to which the metadata applies
        mcf (dict): dict representation of the Metadata Control File

    """

    def __init__(self, source_dataset_path=None):
        """Create an MCF instance, populated with properties of the dataset.

        The MCF will be valid according to the pygeometa schema. It has
        all required properties. Properties of the dataset are used to
        populate as many MCF properties as possible. Default/placeholder
        values are used for properties that require user input.

        Instantiating without a ``source_dataset_path`` creates an MCF template.

        Args:
            source_dataset_path (string): path or URL to dataset to which the
                metadata applies

        """

        # if source_dataset_path is not None:
        self.datasource = source_dataset_path
        self.data_package_path = f'{self.datasource}.yml'

        # Despite naming, this does not open a resource that must be closed
        of = fsspec.open(self.datasource)
        if not of.fs.exists(self.datasource):
            raise FileNotFoundError(f'{self.datasource} does not exist')

        resource_type = get_file_type(source_dataset_path)
        description = DESRCIBE_FUNCS[resource_type](source_dataset_path)
        # this is nice for autodetect of field types, but sometimes
        # we will know the table schema (invest MODEL_SPEC).
        # Is there any benefit to passing in the known schema? Maybe not
        # Can also just overwrite the schema attribute with known data after.

        # Load existing metadata file
        try:
            with fsspec.open(self.data_package_path, 'r') as file:
                yaml_string = file.read()

            # This validates the existing yaml against our dataclasses.
            existing_resource = RESOURCE_MODELS[resource_type](
                **yaml.safe_load(yaml_string))
            # overwrite properties that are intrinsic to the dataset,
            # which is everything from `description` other than schema.
            # Some parts of schema are intrinsic, but others are human-input
            # so replace the whole thing for now.
            del description['schema']
            self.metadata = dataclasses.replace(
                existing_resource, **description)

        # Common path: metadata file does not already exist
        except FileNotFoundError as err:
            self.metadata = RESOURCE_MODELS[resource_type](**description)

    def set_title(self, title):
        """Add a title for the dataset.

        Args:
            title (str)

        """
        self.metadata.title = title

    def get_title(self):
        """Get the title for the dataset."""
        return self.metadata.title

    def set_description(self, description):
        """Add an description for the dataset.

        Args:
            description (str)

        """
        self.metadata.description = description

    def get_description(self):
        """Get the description for the dataset."""
        return self.metadata.description

    def set_citation(self, citation):
        """Add a citation string for the dataset.

        Args:
            citation (str)

        """
        self.metadata.citation = citation

    def get_citation(self):
        """Get the citation for the dataset."""
        return self.metadata.citation

    def set_contact(self, organization=None, individual_name=None,
                    position_name=None, email=None):
        """Add a contact section.

        Args:
            organization (str): name of the responsible organization
            individual_name (str): name of the responsible person
            position_name (str): role or position of the responsible person
            email (str): address of the responsible organization or individual

        """

        if organization:
            self.metadata.contact.organization = organization
        if individual_name:
            self.metadata.contact.individualname = individual_name
        if position_name:
            self.metadata.contact.positionname = position_name
        if email:
            self.metadata.contact.email = email

    def get_contact(self):
        """Get metadata from a contact section.

        Returns:
            ContactSchema

        """
        return self.metadata.contact

    def set_doi(self, doi):
        """Add a doi string for the dataset.

        Args:
            doi (str)

        """
        self.metadata.doi = doi

    def get_doi(self):
        """Get the doi for the dataset."""
        return self.metadata.doi

    def set_edition(self, edition):
        """Set the edition for the dataset.

        Args:
            edition (str): version of the cited resource

        """
        self.metadata.edition = edition

    def get_edition(self):
        """Get the edition of the dataset.

        Returns:
            str or ``None`` if ``edition`` does not exist.

        """
        return self.metadata.edition

    def set_keywords(self, keywords, section='default', keywords_type='theme',
                     vocabulary=None):
        """Describe a dataset with a list of keywords.

        Keywords are grouped into sections for the purpose of complying with
        pre-exising keyword schema. A section will be overwritten if it
        already exists.

        Args:
            keywords (list): sequence of strings
            section (string): the name of a keywords section
            keywords_type (string): subject matter used to group similar
                keywords. Must be one of,
                ('discipline', 'place', 'stratum', 'temporal', 'theme')
            vocabulary (dict): a dictionary with 'name' and 'url' (optional)
                keys. Used to describe the source (thesaurus) of keywords

        Raises:
            ValidationError

        """
        section_dict = {
            'keywords': keywords,
            'keywords_type': keywords_type
        }

        if vocabulary:
            section_dict['vocabulary'] = vocabulary
        self.mcf['identification']['keywords'][section] = section_dict
        self.validate()

    def get_keywords(self, section='default'):
        return self.mcf['identification']['keywords'][section]

    def set_license(self, title=None, path=None):
        """Add a license for the dataset.

        Either or both title and path are required if there is a license.
        Call with no arguments to remove access constraints and license
        info.

        Args:
            title (str): human-readable title of the license
            path (str): url for the license

        """
        license_dict = {}
        license_dict['title'] = title if title else ''
        license_dict['path'] = path if path else ''

        # TODO: DataPackage/Resource allows for a list of licenses.
        # So far we only support one license per resource.
        self.licenses = [models.License(**license_dict)]

    def get_license(self):
        """Get ``license`` for the dataset.

        Returns:
            models.License

        """
        # TODO: DataPackage/Resource allows for a list of licenses.
        # So far we only support one license per resource.
        if self.licenses:
            return self.licenses[0]

    def set_lineage(self, statement):
        """Set the lineage statement for the dataset.

        Args:
            statement (str): general explanation describing the lineage or
                provenance of the dataset

        """
        self.metadata.lineage = statement

    def get_lineage(self):
        """Get the lineage statement of the dataset.

        Returns:
            str

        """
        return self.metadata.lineage

    def set_purpose(self, purpose):
        """Add a purpose for the dataset.

        Args:
            purpose (str): description of the purpose of the source dataset

        """
        self.metadata.purpose = purpose

    def get_purpose(self):
        """Get ``purpose`` for the dataset.

        Returns:
            str

        """
        return self.metadata.purpose

    def set_url(self, url):
        """Add a url for the dataset.

        Args:
            url (str)

        """
        self.metadata.url = url

    def get_url(self):
        """Get the url for the dataset."""
        return self.metadata.url

    def set_band_description(self, band_number, name=None, title=None,
                             abstract=None, units=None, type=None):
        """Define metadata for a raster band.

        Args:
            band_number (int): a raster band index, starting at 1
            name (str): name for the raster band
            title (str): title for the raster band
            abstract (str): description of the raster band
            units (str): unit of measurement for the band's pixel values
            type (str): of the band's values, either 'integer' or 'number'

        """
        idx = band_number - 1
        attribute = self.mcf['content_info']['attributes'][idx]

        if name is not None:
            attribute['name'] = name
        if title is not None:
            attribute['title'] = title
        if abstract is not None:
            attribute['abstract'] = abstract
        if units is not None:
            attribute['units'] = units
        if type is not None:
            attribute['type'] = type

        self.mcf['content_info']['attributes'][idx] = attribute

    def get_band_description(self, band_number):
        """Get the attribute metadata for a band.

        Args:
            band_number (int): a raster band index, starting at 1

        Returns:
            dict
        """
        return self.mcf['content_info']['attributes'][band_number - 1]

    def _get_attr(self, name):
        """Get an attribute by its name property.

        Args:
            name (string): to match the value of the 'name' key in a dict

        Returns:
            tuple of (list index of the matching attribute, the attribute
                dict)

        Raises:
            KeyError if no attributes exist in the MCF or if the named
                attribute does not exist.

        """
        if len(self.mcf['content_info']['attributes']) == 0:
            raise KeyError(
                f'{self.datasource} MCF has not attributes')
        for idx, attr in enumerate(self.mcf['content_info']['attributes']):
            if attr['name'] == name:
                return idx, attr
        raise KeyError(
            f'{self.datasource} has no attribute named {name}')

    def set_field_description(self, name, title=None, abstract=None,
                              units=None, type=None):
        """Define metadata for a tabular field.

        Args:
            name (str): name and unique identifier of the field
            title (str): title for the field
            abstract (str): description of the field
            units (str): unit of measurement for the field's values

        """
        idx, attribute = self._get_attr(name)

        if title is not None:
            attribute['title'] = title
        if abstract is not None:
            attribute['abstract'] = abstract
        if units is not None:
            attribute['units'] = units
        if type is not None:
            attribute['type'] = type

        self.mcf['content_info']['attributes'][idx] = attribute

    def get_field_description(self, name):
        """Get the attribute metadata for a field.

        Args:
            name (str): name and unique identifier of the field

        Returns:
            dict
        """
        idx, attribute = self._get_attr(name)
        return attribute

    def write(self, workspace=None):
        """Write datapackage yaml to disk.

        This creates sidecar files with '.yml'
        appended to the full filename of the data source. For example,

        - 'myraster.tif'
        - 'myraster.tif.yml'

        Args:
            workspace (str): if ``None``, files write to the same location
                as the source data. If not ``None``, a path to a local directory
                to write files. They will still be named to match the source
                filename. Use this option if the source data is not on the local
                filesystem.

        """
        if workspace is None:
            target_path = self.data_package_path
        else:
            target_path = os.path.join(
                workspace, f'{os.path.basename(self.datasource)}.yml')

        with open(target_path, 'w') as file:
            file.write(yaml.dump(
                dataclasses.asdict(self.metadata), Dumper=_NoAliasDumper))

    def to_string(self):
        pass
