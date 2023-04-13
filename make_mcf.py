import os
from pprint import pprint
import yaml

import pygeometa.core
from pygeometa.schemas.iso19139 import ISO19139OutputSchema
from pygeometa.schemas.iso19139_2 import ISO19139_2OutputSchema
import pygeoprocessing
from osgeo import gdal
from osgeo import osr

# sample_mcf = 'sample.yml'
data_path = 'data/watershed_gura.shp'
mcf_path = f'{os.path.splitext(data_path)[0]}.yml'
xml_path = f'{data_path}.xml'

# attributes are properties of 'content_info' and of
# the top-level mcf. Both are arrays of objects like this:
attr_template = {
    'name': ''
}
poc_template = {
    'organization': '',
    'url': '',
    'individualname': '',
    'positionname': '',
    'phone': '',
    'fax': '',
    'address': '',
    'city': '',
    'administrativearea': '',
    'postalcode': '',
    'country': '',
    'email': ''
}

# template includes all the required properties of a valid MCF,
# But will still raise validation errors on properties that
# have required values.
template = {
    'mcf': {
        'version': 1
    },
    'metadata': {
        'identifier': '',
        'language': '',
        'charset': '',
        'hierarchylevel': '',
        'datestamp': '',
        'dataseturi': ''
    },
    'spatial': {
        'datatype': '',
        'geomtype': ''
    },
    'identification': {
        'language': '',
        'charset': '',
        'title': '',
        'abstract': '',
        'topiccategory': [],
        'fees': '',
        'accessconstraints': '',
        'rights': '',
        'url': '',
        'status': '',
        'maintenancefrequency': '',
        'dates': {},
        'extents': {
            'spatial': [
                {
                    'bbox': [],
                    'crs': '',
                    'description': ''
                }
            ]
        },
        'keywords': {},
    },
    'content_info': {
        'type': '',
        'attributes': [attr_template],
        'dimensions': [],
    },
    'contact': {
        'pointOfContact': poc_template
    },
    'distribution': {},
    'dataquality': {
        'scope': {},
        'lineage': {
            'statement': ''
        }
    },
    'acquisition': {
        'platforms': []
    },
    'attributes': [attr_template]
}

mcf = template
with open('template_required_properties.yml', 'w') as output:
    output.write(yaml.dump(mcf, indent=4))

## Populate required values
mcf['metadata']['hierarchylevel'] = 'dataset'
mcf['spatial']['datatype'] = 'vector'
mcf['spatial']['geomtype'] = 'surface'
mcf['content_info']['type'] = 'coverage'
with open('template_required_values.yml', 'w') as output:
    output.write(yaml.dump(mcf, indent=4))


## Non-required values:
poc = poc_template
poc['organization'] = 'Natural Capital Project'
mcf['contact']['pointOfContact'] = poc

vector_info = pygeoprocessing.get_vector_info(data_path)
srs = osr.SpatialReference()
srs.ImportFromWkt(vector_info['projection_wkt'])
epsg = srs.GetAttrValue('AUTHORITY', 1)
spatial_info = {
    'bbox': vector_info['bounding_box'],
    'crs': epsg  # MCF does not support WKT here
}
mcf['identification']['extents']['spatial'][0] = spatial_info

# attributes = [
#     {}
# ]
# mcf['content_info']['attributes'] = attributes

if pygeometa.core.validate_mcf(mcf):
    # iso_os = ISO19139OutputSchema()
    iso_os = ISO19139_2OutputSchema()
    xml_str = iso_os.write(mcf)

    with open('sample_autopopulated.yml', 'w') as output:
        output.write(yaml.dump(mcf, indent=4))

    with open(xml_path, 'w') as output:
        output.write(xml_str)
