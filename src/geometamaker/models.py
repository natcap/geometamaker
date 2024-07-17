from dataclasses import dataclass, field
import logging
import pprint

import yaml


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
    individual_name: str = ''
    position_name: str = ''


@dataclass
class License:
    """Class for storing license info."""

    # https://datapackage.org/profiles/2.0/dataresource.json
    # This profile also includes `name`, described as:
    # "MUST be an Open Definition license identifier",
    # see http://licenses.opendefinition.org/"
    # I don't think that's useful to us yet.
    path: str
    title: str


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

    # TODO: DP includes `sources` as list of source files
    # with some amount of metadata for each item. For our
    # use-case, I think a list of filenames is good enough.

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
    licenses: list = field(default_factory=list)
    citation: str = ''
    doi: str = ''
    url: str = ''
    edition: str = ''
    lineage: str = ''
    purpose: str = ''
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
