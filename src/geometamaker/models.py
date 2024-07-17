import dataclasses
from dataclasses import dataclass, field
import logging
import os
import pprint

import frictionless
import fsspec
import pygeoprocessing
import yaml
from osgeo import gdal


LOGGER = logging.getLogger(__name__)

# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
class _NoAliasDumper(yaml.SafeDumper):
    """Keep the yaml human-readable by avoiding anchors and aliases."""

    def ignore_aliases(self, data):
        return True


@dataclass
class BoundingBox():

    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass
class SpatialSchema():

    bounding_box: BoundingBox
    crs: str


@dataclass
class ContactSchema:
    """Class for keeping track of contact info."""

    email: str = ''
    organization: str = ''
    individualname: str = ''
    positionname: str = ''


@dataclass
class FieldSchema:
    """metadata for a field in a table."""

    # https://datapackage.org/standard/table-schema/
    name: str = ''
    title: str = ''
    type: str = ''
    format: str = ''
    example: any = None
    description: str = ''
    units: str = ''


@dataclass
class TableSchema:
    """Class for metadata for tables."""

    # https://datapackage.org/standard/table-schema/
    fields: list = field(default_factory=FieldSchema)
    missingValues: list = field(default_factory=list)
    primaryKey: list = field(default_factory=list)
    foreignKeys: list = field(default_factory=list)

    # def get_field():


@dataclass
class BandSchema:
    """Class for metadata for a raster band."""

    index: int
    gdal_type: int
    numpy_type: str
    nodata: int | float
    description: str = ''


@dataclass
class RasterSchema:
    """Class for metadata for raster bands."""

    bands: list
    pixel_size: list
    raster_size: list


@dataclass(kw_only=True)
class Resource:
    """Base class for metadata for a resource.

    https://datapackage.org/standard/data-resource/
    This class should be based on Data Package - Resource
    specification. But we have some additional properties
    that are important to us.
    """

    path: str = ''
    type: str = ''
    scheme: str = ''
    encoding: str = ''
    format: str = ''
    mediatype: str = ''
    bytes: int = 0
    hash: str = ''
    name: str = ''
    title: str = ''
    description: str = ''
    sources: list = field(default_factory=list)
    # schema: dict = field(init=False)
    licenses: list = field(default_factory=list)
    contact: ContactSchema = ContactSchema()

    # def __post_init__(self):
    #     self.schema = 


@dataclass(kw_only=True)
class TableResource(Resource):
    """Class for metadata for a table resource."""

    # without post-init, schema ends up as a dict, or whatever is passed in.
    schema: TableSchema = field(default_factory=TableSchema)
    # type: str = 'table'

    def __post_init__(self):
        # Allow init of the resource with a schema of type
        # TableSchema, or type dict. Mostly because dataclasses.replace
        # calls init, but the base object will have already been initialized.
        if isinstance(self.schema, TableSchema):
            return
        self.schema = TableSchema(**self.schema)


@dataclass(kw_only=True)
class VectorResource(TableResource):
    """Class for metadata for a vector resource."""

    spatial: SpatialSchema


@dataclass(kw_only=True)
class RasterResource(Resource):
    """Class for metadata for a raster resource."""

    schema: RasterSchema
    spatial: SpatialSchema

    def __post_init__(self):
        # Allow init of the resource with a schema of type
        # RasterSchema, or type dict. Mostly because dataclasses.replace
        # calls init, but the base object will have already been initialized.
        if isinstance(self.schema, RasterSchema):
            return
        self.schema = RasterSchema(**self.schema)


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
    description = frictionless.describe(source_dataset_path).to_dict()
    fields = []
    vector = gdal.OpenEx(source_dataset_path, gdal.OF_VECTOR)
    layer = vector.GetLayer()
    for fld in layer.schema:
        fields.append(
            FieldSchema(name=fld.name, type=fld.type))
    vector = layer = None
    description['schema'] = TableSchema(fields=fields)

    info = pygeoprocessing.get_vector_info(source_dataset_path)
    spatial = {
        'bounding_box': info['bounding_box'],
        'crs': info['projection_wkt']
    }
    description['spatial'] = SpatialSchema(**spatial)
    description['sources'] = info['file_list']
    return description


def describe_raster(source_dataset_path):
    description = frictionless.describe(source_dataset_path).to_dict()

    bands = []
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    for i in range(info['n_bands']):
        b = i + 1
        # band = raster.GetRasterBand(b)
        # datatype = 'integer' if band.DataType < 6 else 'number'
        bands.append(BandSchema(
            index=b,
            gdal_type=info['datatype'],
            numpy_type=info['numpy_type'],
            nodata=info['nodata'][i]))
    description['schema'] = RasterSchema(
        bands=bands,
        pixel_size=info['pixel_size'],
        raster_size=info['raster_size'])
    description['spatial'] = SpatialSchema(
        bounding_box=info['bounding_box'],
        crs=info['projection_wkt'])
    description['sources'] = info['file_list']
    return description


def describe_table(source_dataset_path):
    return frictionless.describe(source_dataset_path).to_dict()


DESRCIBE_FUNCS = {
    'table': describe_table,
    'vector': describe_vector,
    'raster': describe_raster
}

RESOURCE_MODELS = {
    'table': TableResource,
    'vector': VectorResource,
    'raster': RasterResource
}


class MetadataControl(object):

    def __init__(self, source_dataset_path):
        # if source_dataset_path is not None:
        self.datasource = source_dataset_path
        self.data_package_path = f'{self.datasource}.dp.yml'

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
                workspace, f'{os.path.basename(self.datasource)}.dp.yml')

        with open(target_path, 'w') as file:
            file.write(yaml.dump(
                dataclasses.asdict(self.metadata), Dumper=_NoAliasDumper))


if __name__ == "__main__":
    # from natcap.invest import carbon
    # arg_spec = carbon.MODEL_SPEC['args']['carbon_pools_path']

    # filepath = 'C:/Users/dmf/projects/geometamaker/data/carbon_pools.csv'
    # filepath = 'C:/Users/dmf/projects/geometamaker/data/watershed_gura.shp'
    filepath = 'C:/Users/dmf/projects/geometamaker/data/DEM_gura.tif'
    mc = MetadataControl(filepath)
    pprint.pprint(dataclasses.asdict(mc.metadata))
    # mc.write()
