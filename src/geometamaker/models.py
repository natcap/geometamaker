import dataclasses
from dataclasses import dataclass
import logging
import os

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
    fields: list = dataclasses.field(default_factory=FieldSchema)
    missingValues: list = dataclasses.field(default_factory=list)
    primaryKey: list = dataclasses.field(default_factory=list)
    foreignKeys: list = dataclasses.field(default_factory=list)

    def __post_init__(self):
        field_schemas = []
        for field in self.fields:
            # Allow init of the resource with a schema of type
            # FieldSchema, or type dict. Mostly because dataclasses.replace
            # calls init, but the base object will have already been initialized.
            if isinstance(field, FieldSchema):
                field_schemas.append(field)
            else:
                field_schemas.append(FieldSchema(**field))
        self.fields = field_schemas


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
    keywords: list = dataclasses.field(default_factory=list)
    sources: list = dataclasses.field(default_factory=list)
    licenses: list = dataclasses.field(default_factory=list)
    citation: str = ''
    doi: str = ''
    url: str = ''
    edition: str = ''
    lineage: str = ''
    purpose: str = ''
    contact: ContactSchema = ContactSchema()

    def __post_init__(self):
        self.metadata_path = f'{self.path}.yml'

    def set_title(self, title):
        """Add a title for the dataset.

        Args:
            title (str)

        """
        self.title = title

    def get_title(self):
        """Get the title for the dataset."""
        return self.title

    def set_description(self, description):
        """Add an description for the dataset.

        Args:
            description (str)

        """
        self.description = description

    def get_description(self):
        """Get the description for the dataset."""
        return self.description

    def set_citation(self, citation):
        """Add a citation string for the dataset.

        Args:
            citation (str)

        """
        self.citation = citation

    def get_citation(self):
        """Get the citation for the dataset."""
        return self.citation

    def set_contact(self, organization=None, individual_name=None,
                    position_name=None, email=None):
        """Add a contact section.

        Args:
            organization (str): name of the responsible organization
            individual_name (str): name of the responsible person
            position_name (str): role or position of the responsible person
            email (str): address of the responsible organization or individual

        """

        if organization is not None:
            self.contact.organization = organization
        if individual_name is not None:
            self.contact.individual_name = individual_name
        if position_name is not None:
            self.contact.position_name = position_name
        if email is not None:
            self.contact.email = email

    def get_contact(self):
        """Get metadata from a contact section.

        Returns:
            ContactSchema

        """
        return self.contact

    def set_doi(self, doi):
        """Add a doi string for the dataset.

        Args:
            doi (str)

        """
        self.doi = doi

    def get_doi(self):
        """Get the doi for the dataset."""
        return self.doi

    def set_edition(self, edition):
        """Set the edition for the dataset.

        Args:
            edition (str): version of the cited resource

        """
        self.edition = edition

    def get_edition(self):
        """Get the edition of the dataset.

        Returns:
            str or ``None`` if ``edition`` does not exist.

        """
        return self.edition

    def set_keywords(self, keywords):
        """Describe a dataset with a list of keywords.

        Args:
            keywords (list): sequence of strings

        """
        self.keywords = keywords

    def get_keywords(self):
        return self.keywords

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
        self.licenses = [License(**license_dict)]

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
        self.lineage = statement

    def get_lineage(self):
        """Get the lineage statement of the dataset.

        Returns:
            str

        """
        return self.lineage

    def set_purpose(self, purpose):
        """Add a purpose for the dataset.

        Args:
            purpose (str): description of the purpose of the source dataset

        """
        self.purpose = purpose

    def get_purpose(self):
        """Get ``purpose`` for the dataset.

        Returns:
            str

        """
        return self.purpose

    def set_url(self, url):
        """Add a url for the dataset.

        Args:
            url (str)

        """
        self.url = url

    def get_url(self):
        """Get the url for the dataset."""
        return self.url

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
            target_path = self.metadata_path
        else:
            target_path = os.path.join(
                workspace, f'{os.path.basename(self.datasource)}.yml')

        with open(target_path, 'w') as file:
            file.write(yaml.dump(
                dataclasses.asdict(self), Dumper=_NoAliasDumper))

    def to_string(self):
        pass


@dataclass(kw_only=True)
class TableResource(Resource):
    """Class for metadata for a table resource."""

    fields: int
    rows: int
    # without post-init, schema ends up as a dict, or whatever is passed in.
    schema: TableSchema = dataclasses.field(default_factory=TableSchema)

    def __post_init__(self):
        super().__post_init__()
        # Allow init of the resource with a schema of type
        # TableSchema, or type dict. Mostly because dataclasses.replace
        # calls init, but the base object will have already been initialized.
        if isinstance(self.schema, TableSchema):
            return
        self.schema = TableSchema(**self.schema)

    def _get_field(self, name):
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
        if len(self.schema.fields) == 0:
            raise KeyError(
                f'{self.schema} has no fields')
        for idx, field in enumerate(self.schema.fields):
            if field.name == name:
                return idx, field
        raise KeyError(
            f'{self.schema} has no field named {name}')

    def set_field_description(self, name, title=None, description=None,
                              units=None, type=None, format=None,
                              example=None):
        """Define metadata for a tabular field.

        Args:
            name (str): name and unique identifier of the field
            title (str): title for the field
            abstract (str): description of the field
            units (str): unit of measurement for the field's values

        """
        idx, field = self._get_field(name)

        if title is not None:
            field.title = title
        if description is not None:
            field.description = description
        if units is not None:
            field.units = units
        if type is not None:
            field.type = type
        if format is not None:
            field.format = format
        if example is not None:
            field.example = example

        self.schema.fields[idx] = field

    def get_field_description(self, name):
        """Get the attribute metadata for a field.

        Args:
            name (str): name and unique identifier of the field

        Returns:
            dict
        """
        idx, field = self._get_field(name)
        return field


@dataclass(kw_only=True)
class ArchiveResource(Resource):
    """Class for metadata for an archive resource."""

    compression: str
    innerpath: str


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
        super().__post_init__()
        # Allow init of the resource with a schema of type
        # RasterSchema, or type dict. Mostly because dataclasses.replace
        # calls init, but the base object will have already been initialized.
        if isinstance(self.schema, RasterSchema):
            return
        self.schema = RasterSchema(**self.schema)

    def set_band_description(self, band_number, title=None,
                             description=None, units=None):
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
        band = self.schema.bands[idx]

        if title is not None:
            band.title = title
        if description is not None:
            band.description = description
        if units is not None:
            band.units = units

        self.schema.bands[idx] = band

    def get_band_description(self, band_number):
        """Get the attribute metadata for a band.

        Args:
            band_number (int): a raster band index, starting at 1

        Returns:
            dict
        """
        return self.schema.bands[band_number - 1]
