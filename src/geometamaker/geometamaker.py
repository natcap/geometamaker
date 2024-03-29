import logging
import os
import uuid
from datetime import datetime

import fsspec
import jsonschema
from jsonschema.exceptions import ValidationError
import pygeometa.core
from pygeometa.schemas import load_schema
import pygeoprocessing
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
import yaml


# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
class _NoAliasDumper(yaml.SafeDumper):
    """Keep the yaml human-readable by avoiding anchors and aliases."""

    def ignore_aliases(self, data):
        return True


LOGGER = logging.getLogger(__name__)

MCF_SCHEMA_FILE = os.path.join(
    pygeometa.core.SCHEMAS, 'mcf', 'core.yaml')
with open(MCF_SCHEMA_FILE, 'r') as schema_file:
    MCF_SCHEMA = pygeometa.core.yaml_load(schema_file)

# modify the core MCF schema so that our default
# template MCFs have all the properties we expect
# users to use.
MCF_SCHEMA['required'].append('content_info')
MCF_SCHEMA['required'].append('dataquality')
MCF_SCHEMA['properties']['identification']['properties'][
    'citation'] = {
        'type': 'string',
        'description': 'a biobliographic citation for the dataset'
    }
MCF_SCHEMA['properties']['identification']['required'].append('citation')
MCF_SCHEMA['properties']['identification']['properties'][
    'keywords']['patternProperties']['^.*'][
    'required'] = ['keywords', 'keywords_type']
# to accomodate tables that do not represent spatial content:
NO_GEOM_TYPE = 'none'
MCF_SCHEMA['properties']['spatial']['properties'][
    'geomtype']['enum'].append(NO_GEOM_TYPE)
TABLE_CONTENT_TYPE = 'table'
MCF_SCHEMA['properties']['content_info']['properties'][
    'type']['enum'].append(TABLE_CONTENT_TYPE)

OGR_MCF_ATTR_TYPE_MAP = {
    ogr.OFTInteger: 'integer',
    ogr.OFTInteger64: 'integer',
    ogr.OFTReal: 'number',
    ogr.OFTString: 'string'
}


def _get_default(item):
    """Return a default value for a property.

    Args:
        item (dict): a jsonschema definition of a property with no children.

    Return:
        a value from DEFAULT_VALUES

    Raises:
        KeyError if ``item`` does not include an
        'enum', 'type', or '$ref' property.

    """
    # TODO: read types from the #/definitions found in MCF_SCHEMA
    # instead of hardcoding values here
    # TODO: support i18n properly by using objects
    # keyed by country codes to contain the array of strings
    default_values = {
        'string': str(),
        'int': int(),
        'integer': int(),
        'number': float(),
        'boolean': False,
        '#/definitions/date_or_datetime_string': str(),
        '#/definitions/i18n_string': str(),
        '#/definitions/i18n_array': list(),
        '#/definitions/any_type': str(),
    }

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

    return default_values[t]


def _get_template(schema):
    """Create a minimal dictionary that is valid against ``schema``.

    The dict will ontain only the 'required' properties.

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
                    p: _get_template(s)
                    for p, s in sch['properties']['anyOf'].items()
                }
            else:
                template[prop] = _get_template(sch)
        return template

    elif 'type' in schema and schema['type'] == 'array':
        if 'properties' in schema:
            # for the weird case where identification.extents.spatial
            # is type: array but contains 'properties' instead of 'items'
            return [{
                p: _get_template(s)
                for p, s in schema['properties'].items()
                if p in schema['required']
            }]
        return [_get_template(schema['items'])]
    else:
        return _get_default(schema)


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
        self.mcf = None
        if source_dataset_path is not None:
            self.datasource = source_dataset_path
            self.mcf_path = f'{self.datasource}.yml'

            # Despite naming, this does not open a resource that must be closed
            of = fsspec.open(self.datasource)
            if not of.fs.exists(self.datasource):
                raise FileNotFoundError(f'{self.datasource} does not exist')

            try:
                with fsspec.open(self.mcf_path, 'r') as file:
                    yaml_string = file.read()

                # pygeometa.core.read_mcf can parse nested MCF documents,
                # where one MCF refers to another
                self.mcf = pygeometa.core.read_mcf(yaml_string)
                LOGGER.info(f'loaded existing metadata from {self.mcf_path}')
                self.validate()

            # Common path: MCF often does not already exist
            except FileNotFoundError as err:
                LOGGER.debug(err)

            # Uncommon path: MCF already exists but cannot be used
            except (pygeometa.core.MCFReadError,
                    ValidationError, AttributeError) as err:
                # AttributeError in read_mcf not caught by pygeometa
                LOGGER.warning(err)
                self.mcf = None

            if self.mcf is None:
                self.mcf = _get_template(MCF_SCHEMA)
                self.mcf['metadata']['identifier'] = str(uuid.uuid4())

            # fill all values that can be derived from the dataset
            LOGGER.debug(f'getting properties from {source_dataset_path}')
            self._set_spatial_info()

        else:
            self.mcf = _get_template(MCF_SCHEMA)

        self.mcf['mcf']['version'] = \
            MCF_SCHEMA['properties']['mcf'][
                'properties']['version']['const']

    def set_title(self, title):
        """Add a title for the dataset.

        Args:
            title (str)

        """
        self.mcf['identification']['title'] = title

    def get_title(self):
        """Get the title for the dataset."""
        return self.mcf['identification']['title']

    def set_abstract(self, abstract):
        """Add an abstract for the dataset.

        Args:
            abstract (str)

        """
        self.mcf['identification']['abstract'] = abstract

    def get_abstract(self):
        """Get the abstract for the dataset."""
        return self.mcf['identification']['abstract']

    def set_citation(self, citation):
        """Add a citation string for the dataset.

        Args:
            citation (str)

        """
        self.mcf['identification']['citation'] = citation

    def get_citation(self):
        """Get the citation for the dataset."""
        return self.mcf['identification']['citation']

    def set_contact(self, organization=None, individualname=None, positionname=None,
                    email=None, section='default', **kwargs):
        """Add a contact section.

        Args:
            organization (str): name of the responsible organization
            individualname (str): name of the responsible person
            positionname (str): role or position of the responsible person
            email (str): email address of the responsible organization or individual
            section (str): a header for the contact section under which to
                apply the other args, since there can be more than one.
            kwargs (dict): key-value pairs for any other properties listed in
                the contact section of the core MCF schema.

        """

        if organization:
            self.mcf['contact'][section]['organization'] = organization
        if individualname:
            self.mcf['contact'][section]['individualname'] = individualname
        if positionname:
            self.mcf['contact'][section]['positionname'] = positionname
        if email:
            self.mcf['contact'][section]['email'] = email
        if kwargs:
            for k, v in kwargs.items():
                self.mcf['contact'][section][k] = v

        self.validate()

    def get_contact(self, section='default'):
        """Get metadata from a contact section.

        Args:
            section (str): a header for the contact section under which to
                    apply the other args, since there can be more than one.
        Returns:
            A dict or ``None`` if ``section`` does not exist.

        """
        return self.mcf['contact'].get(section)

    def set_doi(self, doi):
        """Add a doi string for the dataset.

        Args:
            doi (str)

        """
        self.mcf['identification']['doi'] = doi

    def get_doi(self):
        """Get the doi for the dataset."""
        return self.mcf['identification']['doi']

    def set_edition(self, edition):
        """Set the edition for the dataset.

        Args:
            edition (str): version of the cited resource

        """
        self.mcf['identification']['edition'] = edition
        self.validate()

    def get_edition(self):
        """Get the edition of the dataset.

        Returns:
            str or ``None`` if ``edition`` does not exist.

        """
        return self.mcf['identification'].get('edition')

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

    def set_license(self, name=None, url=None):
        """Add a license for the dataset.

        Either or both name and url are required if there is a license.
        Call with no arguments to remove access constraints and license
        info.

        Args:
            name (str): name of the license of the source dataset
            url (str): url for the license

        """
        # MCF spec says use 'otherRestrictions' to mean no restrictions
        constraints = 'otherRestrictions'
        if name or url:
            constraints = 'license'

        license_dict = {}
        license_dict['name'] = name if name else ''
        license_dict['url'] = url if url else ''
        self.mcf['identification']['license'] = license_dict
        self.mcf['identification']['accessconstraints'] = constraints
        self.validate()

    def get_license(self):
        """Get ``license`` for the dataset.

        Returns:
            dict or ``None`` if ``license`` does not exist.

        """
        return self.mcf['identification'].get('license')

    def set_lineage(self, statement):
        """Set the lineage statement for the dataset.

        Args:
            statement (str): general explanation describing the lineage or provenance
                of the dataset

        """
        self.mcf['dataquality']['lineage']['statement'] = statement
        self.validate()

    def get_lineage(self):
        """Get the lineage statement of the dataset.

        Returns:
            str or ``None`` if ``lineage`` does not exist.

        """
        return self.mcf['dataquality']['lineage'].get('statement')

    def set_purpose(self, purpose):
        """Add a purpose for the dataset.

        Args:
            purpose (str): description of the purpose of the source dataset

        """
        # 'Purpose' is not supported in the core MCF spec, probably because
        # `<gmd:purpose>` was added to ISO-19115 in 2014, and MCF still only
        # supports 2015. For now, we can add `purpose` in `identification`.
        # Later we can move it elsewhere if it becomes formally supported.
        self.mcf['identification']['purpose'] = purpose
        self.validate()

    def get_purpose(self):
        """Get ``purpose`` for the dataset.

        Returns:
            str or ``None`` if ``purpose`` does not exist.

        """
        return self.mcf['identification'].get('purpose')

    def set_url(self, url):
        """Add a url for the dataset.

        Args:
            url (str)

        """
        self.mcf['identification']['url'] = url

    def get_url(self):
        """Get the url for the dataset."""
        return self.mcf['identification']['url']

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

    def _write_mcf(self, target_path):
        with open(target_path, 'w') as file:
            file.write(yaml.dump(self.mcf, Dumper=_NoAliasDumper))

    def write(self, workspace=None):
        """Write MCF and ISO-19139 XML to disk.

        This creates sidecar files with '.yml' and '.xml' extensions
        appended to the full filename of the data source. For example,

        - 'myraster.tif'
        - 'myraster.tif.yml'
        - 'myraster.tif.xml'

        Args:
            workspace (str): if ``None``, files write to the same location
                as the source data. If not ``None``, a path to a local directory
                to write files. They will still be named to match the source
                filename. Use this option if the source data is not on the local
                filesystem.

        """
        if workspace is None:
            target_mcf_path = self.mcf_path
            target_xml_path = f'{self.datasource}.xml'
        else:
            target_mcf_path = os.path.join(
                workspace, f'{os.path.basename(self.datasource)}.yml')
            target_xml_path = os.path.join(
                workspace, f'{os.path.basename(self.datasource)}.xml')

        self.mcf['metadata']['datestamp'] = datetime.utcnow().strftime(
                '%Y-%m-%d')
        self._write_mcf(target_mcf_path)

        schema_obj = load_schema('iso19139')
        xml_string = schema_obj.write(self.mcf)
        with open(target_xml_path, 'w') as xmlfile:
            xmlfile.write(xml_string)

    def validate(self):
        """Validate MCF against a jsonschema object."""
        # validate against our own schema, which could
        # be a superset of the core MCF schema.
        # If we wanted to validate against core MCF,
        # we could use pygeometa.core.validate_mcf
        jsonschema.validate(self.mcf, MCF_SCHEMA)

    def to_string(self):
        pass

    def _set_spatial_info(self):
        """Populate the MCF using spatial properties of the dataset."""
        gis_type = pygeoprocessing.get_gis_type(self.datasource)
        self.mcf['metadata']['hierarchylevel'] = 'dataset'

        if gis_type == pygeoprocessing.VECTOR_TYPE:
            LOGGER.debug('opening as GDAL vector')
            self.mcf['content_info']['type'] = 'coverage'
            self.mcf['spatial']['datatype'] = 'vector'
            open_options = []

            if os.path.splitext(self.datasource)[1] == '.csv':
                self.mcf['spatial']['datatype'] = 'textTable'
                open_options.append('AUTODETECT_TYPE=YES')

            vector = gdal.OpenEx(self.datasource, gdal.OF_VECTOR,
                                 open_options=open_options)
            layer = vector.GetLayer()
            layer_defn = layer.GetLayerDefn()
            geomname = ogr.GeometryTypeToName(layer_defn.GetGeomType())
            geomtype = NO_GEOM_TYPE
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

            if len(layer.schema) and 'attributes' not in self.mcf['content_info']:
                self.mcf['content_info']['attributes'] = []

            for field in layer.schema:
                try:
                    idx, attribute = self._get_attr(field.name)
                except KeyError:
                    attribute = _get_template(
                        MCF_SCHEMA['properties']['content_info']['properties'][
                            'attributes'])[0]
                    attribute['name'] = field.name
                    self.mcf['content_info']['attributes'].append(
                        attribute)

                try:
                    datatype = OGR_MCF_ATTR_TYPE_MAP[field.type]
                except KeyError:
                    LOGGER.warning(
                        f'{field.type} is missing in the OGR-to-MCF '
                        f'attribute type map; attribute type for field '
                        f'{field.name} will be "object".')
                    datatype = 'object'
                self.set_field_description(field.name, type=datatype)

            vector = None
            layer = None

            gis_info = pygeoprocessing.get_vector_info(self.datasource)

        if gis_type == pygeoprocessing.RASTER_TYPE:
            LOGGER.debug('opening as GDAL raster')
            self.mcf['spatial']['datatype'] = 'grid'
            self.mcf['spatial']['geomtype'] = 'surface'
            self.mcf['content_info']['type'] = 'image'

            raster = gdal.OpenEx(self.datasource, gdal.OF_RASTER)

            attr = _get_template(
                    MCF_SCHEMA['properties']['content_info']['properties'][
                        'attributes'])[0]

            if 'attributes' not in self.mcf['content_info']:
                self.mcf['content_info']['attributes'] = [attr]*raster.RasterCount
            else:
                n_attrs = len(self.mcf['content_info']['attributes'])
                if n_attrs < raster.RasterCount:
                    extend_n = raster.RasterCount - n_attrs
                    self.mcf['content_info']['attributes'].extend(
                        [attr]*extend_n)

            for i in range(raster.RasterCount):
                b = i + 1
                band = raster.GetRasterBand(b)
                datatype = 'integer' if band.DataType < 6 else 'number'
                self.set_band_description(b, type=datatype)
            band = None
            raster = None

            gis_info = pygeoprocessing.get_raster_info(self.datasource)

        if gis_info['projection_wkt']:
            try:
                srs = osr.SpatialReference()
                srs.ImportFromWkt(gis_info['projection_wkt'])
                epsg = srs.GetAttrValue('AUTHORITY', 1)
            except TypeError:
                LOGGER.warning(
                    f'could not import a spatial reference system from '
                    f'"projection_wkt" in {gis_info}')
                epsg = ''
            # for human-readable values after yaml dump, use python types
            # instead of numpy types
            bbox = [float(x) for x in gis_info['bounding_box']]
            spatial_info = [{
                'bbox': bbox,
                'crs': epsg  # MCF does not support WKT here
            }]
            self.mcf['identification']['extents']['spatial'] = spatial_info
