from collections import defaultdict
from datetime import datetime
import os
import yaml

import pygeometa.core
from pygeometa.schemas.iso19139 import ISO19139OutputSchema
from pygeometa.schemas.iso19139_2 import ISO19139_2OutputSchema
import pygeoprocessing
from osgeo import gdal
from osgeo import ogr
from osgeo import osr

# Keep the yaml human-readable by avoiding anchors and aliases
# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
yaml.Dumper.ignore_aliases = lambda *args: True

MCF_SCHEMA_FILE = os.path.join(
    pygeometa.core.SCHEMAS, 'mcf', 'core.yaml')
with open(MCF_SCHEMA_FILE, 'r') as schema_file:
    MCF_SCHEMA = pygeometa.core.yaml_load(schema_file)

# modify the core MCF schema
MCF_SCHEMA['required'].append('content_info')
MCF_SCHEMA['properties']['content_info']['required'].append(
    'attributes')
MCF_SCHEMA['properties']['identification']['properties'][
    'keywords']['patternProperties']['^.*'][
    'required'] = ['keywords', 'keywords_type']
# It's not clear to me why 'spatial' is type 'array' instead of
# 'object', since it contains 'properties'.
MCF_SCHEMA['properties']['identification']['properties'][
    'extents']['properties']['spatial']['type'] = 'object'
MCF_SCHEMA['properties']['identification']['properties'][
    'extents']['properties']['temporal']['type'] = 'object'

# TODO: read types from the #/definitions found in MCF_SCHEMA
# instead of hardcoding values here
DEFAULT_VALUES = {
    'string': '',
    'int': 0,
    'integer': 0,
    'number': 0,
    'array': [],
    'list': [],
    'tuple': [],
    'dict': {},
    'object': {},
    'boolean': 'false',
    '#/definitions/date_or_datetime_string': '',
    '#/definitions/i18n_string': '',
    '#/definitions/i18n_array': [],
    '#/definitions/any_type': '',
}


OGR_MCF_ATTR_TYPE_MAP = {
    ogr.OFTInteger: 'integer',
    ogr.OFTInteger64: 'integer',
    ogr.OFTReal: 'number',
    ogr.OFTString: 'string'
}


def get_default(item):
    """Return a default value for a property.

    Args:
        item (dict): a jsonschema definition of a property with no children.

    Return:
        a value from DEFAULT_VALUES

    Raises:
        KeyError if ``item`` does not include an
        'enum', 'type', or '$ref' property.

    """
    # If there are enumerated values which must be used
    try:
        fixed_values = item['enum']
        # TODO: find a better way to choose the default
        return fixed_values[0]
    except KeyError:
        pass

    # If no enumerated values, get a default value based on type
    try:
        t = item['type']
    except KeyError:
        # When 'type' is missing, a $ref to another schema is present
        try:
            t = item['$ref']
        except KeyError:
            raise KeyError(
                f'schema has no type and no reference to a type definition\n'
                f'{item}')

    return DEFAULT_VALUES[t]


def get_template(schema):
    """Create a minimal dictionary that is valid against ``schema``.

    Args:
        schema (dict): a jsonschema definition.

    Return:
        dict that is valid against ``schema``

    Raises:
        KeyError if a penultimate property in a schema branch
        does not include an 'enum', 'type', or '$ref' property.

    """
    template = {}
    if 'type' in schema and schema['type'] == 'object':
        for prop, sch in schema['properties'].items():
            if 'required' in schema and prop not in schema['required']:
                continue
            if 'patternProperties' in sch:
                # this item's properties can have any name matching the pattern.
                # assign the name 'default' and overwite the current schema
                # with a new one that explicitly includes the 'default' property.
                example_sch = {
                    'type': 'object',
                    'required': ['default'],
                    'properties': {
                        'default': sch['patternProperties']['^.*']
                    }
                }
                sch = example_sch

            if 'properties' in sch and 'anyOf' in sch['properties']:
                # if 'anyOf' is a property, then we effectively want to
                # treat the children of 'anyOf' as the properties instead.
                template[prop] = {
                    p: get_template(s)
                    for p, s in sch['properties']['anyOf'].items()
                }
            else:
                template[prop] = get_template(sch)
        return template

    elif 'type' in schema and schema['type'] == 'array':
        return [get_template(schema['items'])]
    else:
        return get_default(schema)


def get_vector_attr(attribute_list, name):
    for idx, attr in enumerate(attribute_list):
        if attr['name'] == name:
            return idx, attr
    raise ValueError(
        f'There is no attribute named {name}')


class MCF:
    """Encapsulates the Metadata Control File and methods for populating it.

    A Metadata Control File (MCF) is a YAML file that complies with the
    MCF specification defined by pygeometa.
    https://github.com/geopython/pygeometa

    Attributes:
        datasource (string): path to dataset to which the metadata applies
        mcf (dict): dict representation of the MCF

    """

    def __init__(self, source_dataset_path=None):
        """Create an MCF instance, populated with inherent values.

        The MCF will be valid according to the pygeometa schema. It has
        have all required properties. Instrinsic properties of the dataset
        are used to populate as many properties as possible. And
        default/placeholder values are used for properties that require
        user input.

        Args:
            source_dataset_path (string): path to dataset to which the metadata
                applies

        """
        self.datasource = source_dataset_path
        self.mcf = get_template(MCF_SCHEMA)
        self.mcf['mcf']['version'] = \
            MCF_SCHEMA['properties']['mcf']['properties']['version']['const']

        # fill all values that can be derived from the dataset
        if source_dataset_path:
            self.get_spatial_info()

    def add_metadata_attr(self, attribute):
        """Add an arbitrary attribute to the metadata.

        These should be attributes that do not appear elsewhere in the MCF
        specification.

        Args:
            attribute (dict)

        """
        if 'attributes' not in self.mcf:
            self.mcf['attributes'] = []
        self.mcf['attributes'].append(attribute)

    def keywords(self, keywords, section='default', keywords_type='theme',
                 vocabulary=None):
        """Describe a dataset with a list of keywords.

        Keywords are grouped into sections for the purpose of complying with
        pre-exising keyword schema.

        Args:
            keywords (list): sequence of strings
            section (string): the name of a keywords section
            keywords_type (string): subject matter used to group similar
                keywords. Must be one of,
                ('discipline', 'place', 'stratum', 'temporal', 'theme')
            vocabulary (dict): a dictionary with 'name' and 'url' (optional)
                keys. Used to describe the source (thesaurus) of keywords

        Raises:
            TypeError if ``keywords`` is not a list or tuple

        """
        if not isinstance(keywords, (list, tuple)):
            raise TypeError(
                'The first argument of keywords must be a list.'
                f'received {type(keywords)} instead')

        default_section_dict = {
            'keywords': [],
            'keywords_type': ''
        }

        kw_section = self.mcf['identification']['keywords']
        keywords_list = keywords

        named_section = kw_section.get(section, default_section_dict)
        named_section['keywords'].extend(keywords_list)
        named_section['keywords_type'] = keywords_type
        if vocabulary:
            named_section['vocabulary'] = vocabulary
        kw_section[section] = named_section

    def describe_band(self, band_number, name=None, title=None, abstract=None,
                      type=None, units=None):
        """Define metadata for a raster band."""

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

        self.mcf['content_info']['attributes'].insert(idx, attribute)

    def describe_field(self, name, title=None, abstract=None,
                       units=None):
        """Define metadata for a tabular field."""

        try:
            idx, attribute = get_vector_attr(
                self.mcf['content_info']['attributes'], name)
        except ValueError:
            raise ValueError(
                f'{self.datasource} has no attribute named {name}')

        if title is not None:
            attribute['title'] = title
        if abstract is not None:
            attribute['abstract'] = abstract
        if units is not None:
            attribute['units'] = units

        self.mcf['content_info']['attributes'].insert(idx, attribute)

    def write(self):
        with open(f'{self.datasource}.yml', 'w') as file:
            file.write(yaml.dump(self.mcf))

    def validate(self):
        pygeometa.core.validate_mcf(self.mcf)

    def to_string(self):
        pass

    def get_spatial_info(self):
        gis_type = pygeoprocessing.get_gis_type(self.datasource)
        if gis_type == pygeoprocessing.UNKNOWN_TYPE:
            self.mcf['metadata']['hierarchylevel'] = 'nonGeographicDataset'
            return

        if gis_type == pygeoprocessing.VECTOR_TYPE:
            self.mcf['metadata']['hierarchylevel'] = 'dataset'
            self.mcf['spatial']['datatype'] = 'vector'
            self.mcf['content_info']['type'] = 'coverage'

            vector = gdal.OpenEx(self.datasource, gdal.OF_VECTOR)
            layer = vector.GetLayer()
            layer_defn = layer.GetLayerDefn()
            geomname = ogr.GeometryTypeToName(layer_defn.GetGeomType())
            geomtype = ''
            # https://www.fgdc.gov/nap/metadata/register/codelists.html
            if 'Point' in geomname:
                geomtype = 'point'
            if 'Polygon' in geomname:
                geomtype = 'surface'
            if 'Line' in geomname:
                geomtype = 'curve'
            if 'Collection' in geomname:
                geomtype = 'complex'
            self.mcf['spatial']['geomtype'] = geomtype

            attributes = []
            for field in layer.schema:
                attribute = {}
                attribute['name'] = field.name
                attribute['type'] = OGR_MCF_ATTR_TYPE_MAP[field.type]
                attribute['units'] = ''
                attribute['title'] = ''
                attribute['abstract'] = ''
                attributes.append(attribute)
            self.mcf['content_info']['attributes'] = attributes
            vector = None
            layer = None

            gis_info = pygeoprocessing.get_vector_info(self.datasource)

        if gis_type == pygeoprocessing.RASTER_TYPE:
            self.mcf['metadata']['hierarchylevel'] = 'dataset'
            self.mcf['spatial']['datatype'] = 'grid'
            self.mcf['spatial']['geomtype'] = 'surface'
            self.mcf['content_info']['type'] = 'image'

            raster = gdal.OpenEx(self.datasource, gdal.OF_RASTER)
            attributes = []
            for i in range(raster.RasterCount):
                b = i + 1
                band = raster.GetRasterBand(b)
                attribute = {}
                attribute['name'] = ''
                attribute['type'] = 'integer' if band.DataType < 6 else 'number'
                attribute['units'] = ''
                attribute['title'] = ''
                attribute['abstract'] = band.GetDescription()
                attributes.append(attribute)
            self.mcf['content_info']['attributes'] = attributes
            raster = None

            gis_info = pygeoprocessing.get_raster_info(self.datasource)

        srs = osr.SpatialReference()
        srs.ImportFromWkt(gis_info['projection_wkt'])
        epsg = srs.GetAttrValue('AUTHORITY', 1)
        # for human-readable values after yaml dump, use python types
        # instead of numpy types
        bbox = [float(x) for x in gis_info['bounding_box']]
        spatial_info = [
            {'bbox': bbox},
            {'crs': epsg}  # MCF does not support WKT here
        ]
        self.mcf['identification']['extents']['spatial'] = spatial_info
