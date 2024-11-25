from __future__ import annotations
import logging
import os
from typing import List, Union

import fsspec
import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic.dataclasses import dataclass

import geometamaker
from . import utils


LOGGER = logging.getLogger(__name__)


class Parent(BaseModel):
    """Parent class on which to configure validation."""

    model_config = ConfigDict(validate_assignment=True, extra='forbid')


# dataclass allows positional args, BaseModel does not.
# positional args are convenient for initializing BoundingBox,
# but we could switch to BaseModel for consistency.
@dataclass(frozen=True)
class BoundingBox:
    """Class for a spatial bounding box."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float


class SpatialSchema(Parent):
    """Class for keeping track of spatial info."""

    bounding_box: BoundingBox
    crs: str
    crs_units: str


class ContactSchema(Parent):
    """Class for keeping track of contact info."""

    email: str = ''
    organization: str = ''
    individual_name: str = ''
    position_name: str = ''


class LicenseSchema(Parent):
    """Class for storing license info."""

    # https://datapackage.org/profiles/2.0/dataresource.json
    # This profile also includes `name`, described as:
    # "MUST be an Open Definition license identifier",
    # see http://licenses.opendefinition.org/"
    # I don't think that's useful to us yet.
    path: str = ''
    title: str = ''


class FieldSchema(Parent):
    """Metadata for a field in a table."""

    # https://datapackage.org/standard/table-schema/
    name: str
    type: str
    description: str = ''
    title: str = ''
    units: str = ''


class TableSchema(Parent):
    """Class for metadata for tables."""

    # https://datapackage.org/standard/table-schema/
    fields: List[FieldSchema]
    missingValues: list = Field(default_factory=list)
    primaryKey: list = Field(default_factory=list)
    foreignKeys: list = Field(default_factory=list)


class BandSchema(Parent):
    """Class for metadata for a raster band."""

    index: int
    gdal_type: str
    numpy_type: str
    nodata: Union[int, float]
    description: str = ''
    title: str = ''
    units: str = ''


class RasterSchema(Parent):
    """Class for metadata for raster bands."""

    bands: List[BandSchema]
    pixel_size: list
    raster_size: list


class BaseMetadata(Parent):
    """A class for the things shared by Resource and Profile."""

    # These default to None in order to facilitate the logic
    # in ``replace`` where we only replace values that are not None.
    contact: Union[ContactSchema, None] = Field(default_factory=ContactSchema)
    license: Union[LicenseSchema, None] = Field(default_factory=LicenseSchema)

    def set_contact(self, organization=None, individual_name=None,
                    position_name=None, email=None):
        """Add a contact section.

        Args:
            organization (str): name of the responsible organization
            individual_name (str): name of the responsible person
            position_name (str): role or position of the responsible person
            email (str): address of the responsible organization or individual

        """
        if self.contact is None:
            self.contact = ContactSchema()
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

    def set_license(self, title=None, path=None):
        """Add a license for the dataset.

        Either or both title and path are required if there is a license.
        Call with no arguments to remove license info.

        Args:
            title (str): human-readable title of the license
            path (str): url for the license

        """
        if self.license is None:
            self.license = LicenseSchema()
        license_dict = {}
        license_dict['title'] = title if title else ''
        license_dict['path'] = path if path else ''

        # TODO: DataPackage/Resource allows for a list of licenses.
        # So far we only support one license per resource.
        self.license = LicenseSchema(**license_dict)

    def get_license(self):
        """Get ``license`` for the dataset.

        Returns:
            models.LicenseSchema

        """
        # TODO: DataPackage/Resource allows for a list of licenses.
        # So far we only support one license per resource.
        return self.license

    def replace(self, other):
        """Replace attribute values with those from another instance.

        Only attributes that exist in ``self`` will exist in the
        returned instance. Only attribute values that are not None will be used
        to replace existing attribute values in ``self``.

        Args:
            other (BaseMetadata)

        Returns:
            an instance of same type as ``self``

        Raises:
            TypeError if ``other`` is not an instance of BaseMetadata.

        """
        if isinstance(other, BaseMetadata):
            updated_dict = self.model_dump() | {
                k: v for k, v in other.__dict__.items() if v is not None}
            return self.__class__(**updated_dict)
        raise TypeError(f'{type(other)} is not an instance of BaseMetadata')


class Profile(BaseMetadata):
    """Class for a metadata profile.

    A Profile can store metadata properties that are likely to apply
    to more than one resource, such as ``contact`` and ``license``.

    """

    # For a Profile, default these to None so that they do not replace
    # values in a Resource
    contact: Union[ContactSchema, None] = None
    license: Union[LicenseSchema, None] = None

    @classmethod
    def load(cls, filepath):
        """Load metadata document from a yaml file.

        Args:
            filepath (str): path to yaml file

        Returns:
            instance of the class

        """
        with fsspec.open(filepath, 'r') as file:
            yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        return cls(**yaml_dict)

    def write(self, target_path):
        """Write profile data to a yaml file.

        Args:
            target_path (str): path to a yaml file to be written

        """
        with open(target_path, 'w') as file:
            file.write(utils.yaml_dump(self.model_dump()))


class Resource(BaseMetadata):
    """Base class for metadata for a resource.

    https://datapackage.org/standard/data-resource/
    This class borrows from the Data Package - Resource
    specification. But we have some additional properties
    that are important to us.

    All attributes are keyword-only so that we can init
    with default values, allowing the user to get a template
    with which to complete later.

    """

    # A version string we can use to identify geometamaker compliant documents
    metadata_version: str = ''
    # TODO: don't want to include this in doc, but need it as an attribute
    metadata_path: str = ''

    # These are populated geometamaker.describe()
    bytes: int = 0
    encoding: str = ''
    format: str = ''
    uid: str = ''
    mediatype: str = ''
    name: str = ''
    path: str = ''
    scheme: str = ''
    type: str = ''
    last_modified: str = ''
    # DataPackage includes `sources` as a list of source files
    # with some amount of metadata for each item. For our
    # use-case, I think a list of filenames is good enough.
    sources: list = Field(default_factory=list)

    # These are not populated by geometamaker.describe(),
    # and should have setters & getters
    citation: str = ''
    description: str = ''
    doi: str = ''
    edition: str = ''
    keywords: list = Field(default_factory=list)
    lineage: str = ''
    placenames: list = Field(default_factory=list)
    purpose: str = ''
    title: str = ''
    url: str = ''

    def model_post_init(self, __context):
        self.metadata_path = f'{self.path}.yml'
        self.metadata_version: str = f'geometamaker.{geometamaker.__version__}'
        self.path = self.path.replace('\\', '/')
        self.sources = [x.replace('\\', '/') for x in self.sources]

    @classmethod
    def load(cls, filepath):
        """Load metadata document from a yaml file.

        Args:
            filepath (str): path to yaml file

        Returns:
            instance of the class

        Raises:
            FileNotFoundError if filepath does not exist
            ValueError if the metadata is found to be incompatible with
                geometamaker.

        """
        with fsspec.open(filepath, 'r') as file:
            yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        if 'metadata_version' not in yaml_dict \
                or not yaml_dict['metadata_version'].startswith('geometamaker'):
            message = (f'{filepath} exists but is not compatible with '
                       f'geometamaker.')
            raise ValueError(message)
        # delete this property so that geometamaker can initialize it itself
        # with the current version info.
        del yaml_dict['metadata_version']
        return cls(**yaml_dict)

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
        """Add a description for the dataset.

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
        """Get the keywords describing the dataset.

        Returns:
            list

        """
        return self.keywords

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

    def set_placenames(self, placenames):
        """Describe the geography of a dataset with a list of placenames.

        Args:
            places (list): sequence of strings

        """
        self.placenames = placenames

    def get_placenames(self):
        """Get the placenames describing the dataset.

        Returns:
            list

        """
        return self.placenames

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
                workspace, os.path.basename(self.metadata_path))

        with open(target_path, 'w') as file:
            file.write(utils.yaml_dump(self.model_dump()))

    def to_string(self):
        pass


class TableResource(Resource):
    """Class for metadata for a table resource."""

    data_model: TableSchema = Field(default_factory=TableSchema)

    def _get_field(self, name):
        """Get an attribute by its name property.

        Args:
            name (string): to match the value of the 'name' key in a dict

        Returns:
            tuple of (list index of the matching attribute, the attribute
                dict)

        Raises:
            KeyError if no attributes exist in the resource or if the named
                attribute does not exist.

        """
        if len(self.data_model.fields) == 0:
            raise KeyError(
                f'{self.data_model} has no fields')
        for idx, field in enumerate(self.data_model.fields):
            if field.name == name:
                return idx, field
        raise KeyError(
            f'{self.data_model} has no field named {name}')

    def set_field_description(self, name, title=None, description=None,
                              units=None, type=None):
        """Define metadata for a tabular field.

        Args:
            name (str): name and unique identifier of the field
            title (str): title for the field
            description (str): description of the field
            units (str): unit of measurement for the field's values
            type (str): datatype of values in the field

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

        self.data_model.fields[idx] = field

    def get_field_description(self, name):
        """Get the attribute metadata for a field.

        Args:
            name (str): name and unique identifier of the field

        Returns:
            FieldSchema
        """
        idx, field = self._get_field(name)
        return field


class ArchiveResource(Resource):
    """Class for metadata for an archive resource."""

    compression: str


class VectorResource(TableResource):
    """Class for metadata for a vector resource."""

    n_features: int
    spatial: SpatialSchema


class RasterResource(Resource):
    """Class for metadata for a raster resource."""

    data_model: RasterSchema
    spatial: SpatialSchema

    def set_band_description(self, band_number, title=None,
                             description=None, units=None):
        """Define metadata for a raster band.

        Args:
            band_number (int): a raster band index, starting at 1
            title (str): title for the raster band
            description (str): description of the raster band
            units (str): unit of measurement for the band's pixel values

        """
        idx = band_number - 1
        band = self.data_model.bands[idx]

        if title is not None:
            band.title = title
        if description is not None:
            band.description = description
        if units is not None:
            band.units = units

        self.data_model.bands[idx] = band

    def get_band_description(self, band_number):
        """Get the attribute metadata for a band.

        Args:
            band_number (int): a raster band index, starting at 1

        Returns:
            BandSchema

        """
        return self.data_model.bands[band_number - 1]
