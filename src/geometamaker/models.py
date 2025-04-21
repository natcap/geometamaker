from __future__ import annotations
import collections
import logging
import os
import warnings
from typing import Union

import fsspec
import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic.dataclasses import dataclass

import geometamaker
from . import utils


LOGGER = logging.getLogger(__name__)


class Parent(BaseModel):
    """Parent class on which to configure validation."""

    model_config = ConfigDict(validate_assignment=True,
                              extra='forbid',
                              use_attribute_docstrings=True)


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
    """Spatial extent [xmin, ymin, xmax, ymax]."""
    crs: str
    """Coordinate Reference System."""
    crs_units: str
    """Units of measure for coordinates in the CRS."""


class ContactSchema(Parent):
    """Class for storing contact information of data author."""

    email: str = ''
    organization: str = ''
    individual_name: str = ''
    position_name: str = ''


class LicenseSchema(Parent):
    """Class for storing data license information."""

    # Loosely follows https://datapackage.org/profiles/2.0/dataresource.json
    path: str = ''
    """URL that describes the license."""
    title: str = ''
    """Name of a license, such as one from http://licenses.opendefinition.org/"""


class FieldSchema(Parent):
    """Metadata for a field in a table."""

    # https://datapackage.org/standard/table-schema/
    name: str
    """The name used to uniquely identify the field."""
    type: str
    """Datatype of the content of the field."""
    description: str = ''
    """A description of the field."""
    title: str = ''
    """A human-readable title for the field."""
    units: str = ''
    """Unit of measurement for values in the field."""


class TableSchema(Parent):
    """Class for metadata for tables."""

    # https://datapackage.org/standard/table-schema/
    fields: list[FieldSchema]
    """A list of ``FieldSchema`` objects."""
    missingValues: list = Field(default_factory=list)
    """A list of values that represent missing data."""
    primaryKey: list[str] = Field(default_factory=list)
    """A field or list of fields that uniquely identifies each row in the table."""
    foreignKeys: list[str] = Field(default_factory=list)
    """A field or list of fields that can be used to join another table.

    See https://datapackage.org/standard/table-schema/#foreignKeys
    """


class BandSchema(Parent):
    """Class for metadata for a raster band."""

    index: int
    """The index of the band of a GDAL raster, starting at 1."""
    gdal_type: str
    """The GDAL data type of the band."""
    numpy_type: str
    """The numpy data type of the band."""
    nodata: Union[int, float, None]
    """The pixel value that represents no data in the band."""
    description: str = ''
    """A description of the band."""
    title: str = ''
    """A human-readable title for the band."""
    units: str = ''
    """Unit of measurement for the pixel values."""


class RasterSchema(Parent):
    """Class for metadata for raster bands."""

    bands: list[BandSchema]
    """A list of ``BandSchema`` objects."""
    pixel_size: tuple[Union[int, float], Union[int, float]]
    """The width and height of a pixel measured in ``SpatialSchema.crs_units``."""
    raster_size: Union[dict, list]
    """The width and height of the raster measured in number of pixels."""

    def model_post_init(self, __context):
        # Migrate from previous model where we stored this as a list
        if isinstance(self.raster_size, list):
            self.raster_size = {'width': self.raster_size[0],
                                'height': self.raster_size[1]}


class BaseMetadata(Parent):
    """A class for the things shared by Resource and Profile."""

    contact: ContactSchema = Field(default_factory=ContactSchema)
    """Contact information for the data author."""
    license: LicenseSchema = Field(default_factory=LicenseSchema)
    """Data license information."""

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
        returned instance. Only attribute values that are not empty
        in ``other`` will be used to replace values in ``self``.

        Args:
            other (BaseMetadata)

        Returns:
            an instance of same type as ``self``

        Raises:
            TypeError if ``other`` is not an instance of BaseMetadata.

        """
        def _deep_update_dict(self_dict, other_dict):
            for k, v in other_dict.items():
                if k in self_dict:
                    if isinstance(v, collections.abc.Mapping):
                        self_dict[k] = _deep_update_dict(self_dict[k], v)
                    else:
                        if v not in (None, ''):
                            self_dict[k] = v
            return self_dict

        if isinstance(other, BaseMetadata):
            updated_dict = _deep_update_dict(
                self.model_dump(), other.model_dump())
            return self.__class__(**updated_dict)
        raise TypeError(f'{type(other)} is not an instance of BaseMetadata')


class Profile(BaseMetadata):
    """Class for a metadata profile.

    A Profile can store metadata properties that are likely to apply
    to more than one resource, such as ``contact`` and ``license``.

    """

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
        with open(target_path, 'w', encoding='utf-8') as file:
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
    geometamaker_version: str = ''
    metadata_path: str = ''

    # These are populated by geometamaker.describe()
    bytes: int = 0
    """File size of the resource in bytes."""
    encoding: str = ''
    """File encoding of the resource."""
    format: str = ''
    """File format of the resource."""
    uid: str = ''
    """Unique identifier for the resource."""
    path: str = ''
    """Path to the resource being described."""
    scheme: str = ''
    """File protocol for opening the resource."""
    type: str = ''
    """The type of resource being described."""
    last_modified: str = ''
    """Last modified time of the file at ``path``."""
    sources: list[str] = Field(default_factory=list)
    """A list of files which comprise the dataset or resource."""

    # These are not populated by geometamaker.describe(),
    # and should have setters & getters
    citation: str = ''
    """A citation for the resource."""
    description: str = ''
    """A text description of the resource."""
    doi: str = ''
    """A digital object identifier for the resource."""
    edition: str = ''
    """A string representing the edition, or version, of the resource."""
    keywords: list[str] = Field(default_factory=list)
    """A list of keywords that describe the subject-matter of the resource."""
    lineage: str = ''
    """A text description of how the resource was created."""
    placenames: list[str] = Field(default_factory=list)
    """A list of geographic places associated with the resource."""
    purpose: str = ''
    """The author's stated purpose for the resource."""
    title: str = ''
    """The title of the resource."""
    url: str = ''
    """A URL where the resource is available."""

    def model_post_init(self, __context):
        self.metadata_path = f'{self.path}.yml'
        self.geometamaker_version: str = geometamaker.__version__
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
        if not yaml_dict or ('metadata_version' not in yaml_dict
                             and 'geometamaker_version' not in yaml_dict):
            message = (f'{filepath} exists but is not compatible with '
                       f'geometamaker.')
            raise ValueError(message)

        deprecated_attrs = ['metadata_version', 'mediatype', 'name']
        for attr in deprecated_attrs:
            if attr in yaml_dict:
                warnings.warn(
                    f'"{attr}" exists in {filepath} but is no longer part of '
                    f'the geometamaker specification. "{attr}" will be '
                    f'removed from this document. In the future, presence '
                    f' of "{attr}" will raise a ValidationError',
                    category=FutureWarning)
                del yaml_dict[attr]

        # migrate from 'schema' to 'data_model', if needed.
        if 'schema' in yaml_dict:
            warnings.warn(
                "'schema' has been replaced with 'data_model' as an attribute "
                "name. In the future, the presence of a 'schema' attribute "
                "will raise a ValidationError",
                category=FutureWarning)
            yaml_dict['data_model'] = yaml_dict['schema']
            del yaml_dict['schema']
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

        with open(target_path, 'w', encoding='utf-8') as file:
            file.write(utils.yaml_dump(
                self.model_dump(exclude=['metadata_path'])))


class TableResource(Resource):
    """Class for metadata for a table resource."""

    data_model: TableSchema = Field(default_factory=TableSchema)
    """A ``models.TableSchema`` object for describing fields."""

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
    """The compression method used to create the archive."""


class VectorResource(TableResource):
    """Class for metadata for a vector resource."""

    n_features: int
    """Number of features in the layer."""
    spatial: SpatialSchema
    """An object for describing spatial properties of a GDAL dataset."""


class RasterResource(Resource):
    """Class for metadata for a raster resource."""

    data_model: RasterSchema
    """An object for describing raster properties and bands."""
    spatial: SpatialSchema
    """An object for describing spatial properties of a GDAL dataset."""

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
