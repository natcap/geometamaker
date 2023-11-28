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

# from . import sections

# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
yaml.Dumper.ignore_aliases = lambda *args: True

MCF_SCHEMA_FILE = os.path.join(
    pygeometa.core.SCHEMAS, 'mcf', 'core.yaml')
with open(MCF_SCHEMA_FILE, 'r') as schema_file:
    MCF_SCHEMA = pygeometa.core.yaml_load(schema_file)

REQUIRED_PROPERTIES = MCF_SCHEMA['required']
REQUIRED_PROPERTIES.extend([
    'content_info'
])
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
}


def get_default(item, key):
    if item['type'] == 'array':
        return
            DEFAULT_VALUES[item['items']['properties'][key]['type']]
    try:
        return DEFAULT_VALUES[item['type']]
    except KeyError:
        # When 'type' is missing, a $ref to another schema is
        # probably present. For now, we won't bother trying
        # to resolve that.
        return None


def get_template(schema, required_properties_list=None):
    """
    schema: a jsonschema dict with a 'properties' key
    """
    print(required_properties_list)
    mcf = {}
    for key, value in schema['properties'].items():
        print(key)
        if required_properties_list:
            if key not in required_properties_list:
                # print(key)
                continue
        if 'patternProperties' in value:
            value = value['patternProperties']['^.*']
        print(key)
        mcf[key] = {
            k: get_default(value['properties'][k])
            for k in list(value['properties'])
            if k in value['required']
        }
    return mcf


ATTR_TEMPLATE = get_template(
    MCF_SCHEMA['properties']['content_info'],
    required_properties_list=['attributes'])


class MCF:

    def __init__(self, source_dataset_path, profile_list=None):
        self.datasource = source_dataset_path
        self.mcf = get_template(
            MCF_SCHEMA,
            required_properties_list=REQUIRED_PROPERTIES)

        # self.attributes = {}  # arbitrary extras

        # fill all values that can be derived from the dataset
        self.get_spatial_info()

    def keywords(self, keywords, schema='default', language='en',
                 type='theme', vocabulary=None, profile=None):
        keywords_dict = {}
        # construct the dict
        self.mcf['identification']['keywords'] = keywords_dict

    def describe_band(self, index, name, title=None, abstract=None,
                      type=None, units=None):
        """Define metadata for a raster band."""

    def describe_field(self, name, title=None, abstract=None,
                       type=None, units=None):
        """Define metadata for a tabular field."""

    def write(self):
        with open(f'{self.datasource}.yml', 'w') as file:
            file.write(yaml.dump(self.mcf))

    def validate(self):
        pygeometa.core.validate_mcf(self.mcf)

    def to_string(self):
        pass

    # def to_dict(self):
    #     return self.__dict__

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
                attribute = ATTR_TEMPLATE.copy()
                attribute['name'] = field.name
                attribute['type'] = field.GetTypeName().lower()
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
                attribute = ATTR_TEMPLATE.copy()
                attribute['name'] = f'band{b}'
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
