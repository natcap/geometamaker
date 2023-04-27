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

# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
yaml.Dumper.ignore_aliases = lambda *args: True

data_path = 'data/watershed_gura.shp'
# data_path = 'data/DEM_gura.tif'
datatype = 'vector'
xml_path = f'{data_path}.xml'

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
identification_template = {
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
    'identification': identification_template,
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
    }
}

with open('01_template_required_properties.yml', 'w') as output:
    output.write(yaml.dump(template, indent=4))


def get_spatial_info(data_path, template):
    mcf = template
    gis_type = pygeoprocessing.get_gis_type(data_path)
    if gis_type == pygeoprocessing.UNKNOWN_TYPE:
        mcf['metadata']['hierarchylevel'] = 'nonGeographicDataset'
        return mcf

    if gis_type == pygeoprocessing.VECTOR_TYPE:
        mcf['metadata']['hierarchylevel'] = 'dataset'
        mcf['spatial']['datatype'] = 'vector'
        mcf['content_info']['type'] = 'coverage'

        vector = gdal.OpenEx(data_path, gdal.OF_VECTOR)
        layer = vector.GetLayer()
        layer_defn = layer.GetLayerDefn()
        geomname = ogr.GeometryTypeToName(layer_defn.GetGeomType())
        print(geomname)
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
        mcf['spatial']['geomtype'] = geomtype

        attributes = []
        for field in layer.schema:
            attribute = attr_template.copy()
            attribute['name'] = field.name
            attribute['type'] = field.GetTypeName().lower()
            attribute['units'] = ''
            attribute['title'] = ''
            attribute['abstract'] = ''
            attributes.append(attribute)
        mcf['content_info']['attributes'] = attributes
        vector = None
        layer = None

        gis_info = pygeoprocessing.get_vector_info(data_path)

    if gis_type == pygeoprocessing.RASTER_TYPE:
        mcf['metadata']['hierarchylevel'] = 'dataset'
        mcf['spatial']['datatype'] = 'grid'
        mcf['spatial']['geomtype'] = 'surface'
        mcf['content_info']['type'] = 'image'

        raster = gdal.OpenEx(data_path, gdal.OF_RASTER)
        attributes = []
        for i in range(raster.RasterCount):
            b = i + 1
            band = raster.GetRasterBand(b)
            attribute = attr_template.copy()
            attribute['name'] = f'band{b}'
            attribute['type'] = 'integer' if band.DataType < 6 else 'number'
            attribute['units'] = ''
            attribute['title'] = ''
            attribute['abstract'] = band.GetDescription()
            attributes.append(attribute)
        mcf['content_info']['attributes'] = attributes
        raster = None

        gis_info = pygeoprocessing.get_raster_info(data_path)

    srs = osr.SpatialReference()
    srs.ImportFromWkt(gis_info['projection_wkt'])
    epsg = srs.GetAttrValue('AUTHORITY', 1)
    # for human-readable values after yaml dump, use python types
    # instead of numpy types
    bbox = [float(x) for x in gis_info['bounding_box']]
    spatial_info = {
        'bbox': bbox,
        'crs': epsg  # MCF does not support WKT here
    }
    mcf['identification']['extents']['spatial'][0] = spatial_info

    return mcf


mcf = get_spatial_info(data_path, template)
mcf['metadata']['dataseturi'] = os.path.abspath(data_path)
mcf['metadata']['datestamp'] = datetime.now().isoformat()
with open(f'02_sample_{datatype}_autopopulated.yml', 'w') as output:
    output.write(yaml.dump(mcf, indent=4))


poc = poc_template.copy()
poc['individualname'] = 'Nat C. Proj'
poc['organization'] = 'Natural Capital Project'
mcf['contact']['pointOfContact'] = poc

identification = identification_template.copy()
identification['language'] = 'en'
identification['charset'] = 'utf8'
identification['title'] = 'Dataset Title'
identification['abstract'] = 'Dataset Description'
identification['topiccategory'] = ['elevation', 'environment']  # https://geopython.github.io/pygeometa/reference/mcf/
identification['fees'] = 'None'
identification['accessconstraints'] = 'otherRestrictions'  # MCF says use this to mean None
identification['license'] = {
    'name': 'CC BY 4.0'
}
identification['status'] = 'completed'
identification['maintenancefrequency'] = 'asNeeded'
identification['keywords'] = {
    'default': {
        'keywords': {
            'en': ['natcrap']
        },
        'keywords_type': 'theme',
        'vocabulary': {
            'name': 'Ecosystem Services',
            'url': 'www.natcap.com/vocab'
        }
    },
    'NASA': {
        'keywords': {
            'en': ['elevation']
        },
        'keywords_type': 'theme',
        'vocabulary': {
            'name': 'NASA Thesaurus',
            'url': 'https://www.sti.nasa.gov/nasa-thesaurus/'
        }
    }
}
mcf['identification'] = identification


if pygeometa.core.validate_mcf(mcf):
    # iso_os = ISO19139OutputSchema()
    iso_os = ISO19139_2OutputSchema()
    xml_str = iso_os.write(mcf)

    with open(f'03_sample_{datatype}_fullypopulated.yml', 'w') as output:
        output.write(yaml.dump(mcf, indent=4))

    with open(xml_path, 'w') as output:
        output.write(xml_str)
