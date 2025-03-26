import functools
import hashlib
import logging
import os
import requests
from collections import defaultdict
from datetime import datetime, timezone

import frictionless
import fsspec
import numpy
import pygeoprocessing
import yaml
from osgeo import gdal
from osgeo import osr
from pydantic import ValidationError

from . import models
from .config import Config

logging.getLogger('chardet').setLevel(logging.INFO)  # DEBUG is just too noisy

LOGGER = logging.getLogger(__name__)

# URI schemes we support. A subset of fsspec.available_protocols()
PROTOCOLS = [
    'file',
    'http',
    'https',
]

DT_FMT = '%Y-%m-%d %H:%M:%S %Z'


# TODO: In the future we can remove these exception managers in favor of the
# builtin gdal.ExceptionMgr. It was released in 3.7.0 and debugged in 3.9.1.
# https://github.com/OSGeo/gdal/blob/v3.9.3/NEWS.md#gdalogr-391-release-notes
class _OSGEOUseExceptions:
    """Context manager that enables GDAL/OSR exceptions and restores state after."""

    def __init__(self):
        pass

    def __enter__(self):
        self.currentGDALUseExceptions = gdal.GetUseExceptions()
        self.currentOSRUseExceptions = osr.GetUseExceptions()
        gdal.UseExceptions()
        osr.UseExceptions()

    def __exit__(self, exc_type, exc_val, exc_tb):
        # The error-handlers are in a stack, so
        # these must be called from the top down.
        if self.currentOSRUseExceptions == 0:
            osr.DontUseExceptions()
        if self.currentGDALUseExceptions == 0:
            gdal.DontUseExceptions()


def _osgeo_use_exceptions(func):
    """Decorator that enables GDAL/OSR exceptions and restores state after.

    Args:
        func (callable): function to call with GDAL/OSR exceptions enabled

    Returns:
        Wrapper function that calls ``func`` with GDAL/OSR exceptions enabled
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _OSGEOUseExceptions():
            return func(*args, **kwargs)
    return wrapper


def _vsi_path(filepath, scheme):
    """Construct a GDAL virtual file system path.

    Args:
        filepath (str): path to a file to be opened by GDAL
        scheme (str): the protocol prefix of the filepath

    Returns:
        str

    """
    if scheme.startswith('http'):
        filepath = f'/vsicurl/{filepath}'
    return filepath


def _wkt_to_epsg_units_string(wkt_string):
    crs_string = 'unknown'
    units_string = 'unknown'
    try:
        srs = osr.SpatialReference(wkt_string)
        srs.AutoIdentifyEPSG()
        crs_string = (
            f"{srs.GetAttrValue('AUTHORITY', 0)}:"
            f"{srs.GetAttrValue('AUTHORITY', 1)}")
        units_string = srs.GetAttrValue('UNIT', 0)
    except RuntimeError:
        LOGGER.warning(
            f'{wkt_string} cannot be interpreted as a coordinate reference system')
    return crs_string, units_string


def detect_file_type(filepath, scheme):
    """Detect the type of resource contained in the file.

    Args:
        filepath (str): path to a file to be opened by GDAL or frictionless
        scheme (str): the protocol prefix of the filepath

    Returns:
        str

    Raises:
        ValueError on unsupported file formats.

    """
    # TODO: guard against classifying netCDF, HDF5, etc as GDAL rasters.
    # We'll likely want a different data model for multi-dimensional arrays.

    # Frictionless supports a wide range of formats. The quickest way to
    # determine if a file is recognized as a table or archive is to call list.
    info = frictionless.list(filepath)[0]
    if info.type == 'table':
        return 'table'
    if info.compression:
        return 'archive'
    # GDAL considers CSV a vector, so check against frictionless first.
    try:
        gis_type = pygeoprocessing.get_gis_type(_vsi_path(filepath, scheme))
    except ValueError:
        raise ValueError(
            f'{filepath} does not appear to be one of '
            f'(archive, table, raster, vector)')
    if gis_type == pygeoprocessing.VECTOR_TYPE:
        return 'vector'
    if gis_type == pygeoprocessing.RASTER_TYPE:
        return 'raster'
    raise ValueError(
        f'{filepath} contains both raster and vector data. '
        'Such files are not supported by GeoMetaMaker. '
        'If you wish to see support for these files, please '
        'submit a feature request and share your dataset: '
        'https://github.com/natcap/geometamaker/issues ')


def describe_file(source_dataset_path, scheme):
    """Describe basic properties of a file.

    Args:
        source_dataset_path (str): path to a file.
        scheme (str): the protocol prefix of the filepath

    Returns:
        dict

    """
    description = frictionless.describe(source_dataset_path).to_dict()

    # If we want to support more file protocols in the future, it may
    # make sense to use fsspec to access file info in a protocol-agnostic way.
    # But not all protocols are equally supported yet.
    # https://github.com/fsspec/filesystem_spec/issues/526
    if scheme.startswith('http'):
        info = requests.head(source_dataset_path).headers
        description['bytes'] = info['Content-Length']
        description['last_modified'] = datetime.strptime(
            info['Last-Modified'], '%a, %d %b %Y %H:%M:%S %Z').strftime(DT_FMT)
    else:
        info = os.stat(source_dataset_path)
        description['bytes'] = info.st_size
        description['last_modified'] = datetime.fromtimestamp(
            info.st_mtime, tz=timezone.utc).strftime(DT_FMT)

    hash_func = hashlib.new('sha256')
    hash_func.update(
        f'{description["bytes"]}{description["last_modified"]}\
        {description["path"]}'.encode('ascii'))
    description['uid'] = f'sizetimestamp:{hash_func.hexdigest()}'

    # We don't have a use for including these attributes in our metadata:
    description.pop('mediatype', None)
    description.pop('name', None)
    return description


def describe_archive(source_dataset_path, scheme):
    """Describe file properties of a compressed file.

    Args:
        source_dataset_path (str): path to a file.
        scheme (str): the protocol prefix of the filepath

    Returns:
        dict

    """
    description = describe_file(source_dataset_path, scheme)
    # innerpath is from frictionless and not useful because
    # it does not include all the files contained in the zip
    description.pop('innerpath', None)

    ZFS = fsspec.get_filesystem_class('zip')
    zfs = ZFS(source_dataset_path)
    file_list = []
    for dirpath, _, files in zfs.walk(zfs.root_marker):
        for f in files:
            file_list.append(os.path.join(dirpath, f))
    description['sources'] = file_list
    return description


def describe_vector(source_dataset_path, scheme):
    """Describe properties of a GDAL vector file.

    Args:
        source_dataset_path (str): path to a GDAL vector.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path, scheme)

    if 'http' in scheme:
        source_dataset_path = f'/vsicurl/{source_dataset_path}'
    vector = gdal.OpenEx(source_dataset_path, gdal.OF_VECTOR)
    layer = vector.GetLayer()
    fields = []
    description['n_features'] = layer.GetFeatureCount()
    for fld in layer.schema:
        fields.append(
            models.FieldSchema(name=fld.name, type=fld.GetTypeName()))
    vector = layer = None
    description['data_model'] = models.TableSchema(fields=fields)

    info = pygeoprocessing.get_vector_info(source_dataset_path)
    bbox = models.BoundingBox(*info['bounding_box'])
    epsg_string, units_string = _wkt_to_epsg_units_string(
        info['projection_wkt'])
    description['spatial'] = models.SpatialSchema(
        bounding_box=bbox,
        crs=epsg_string,
        crs_units=units_string)
    description['sources'] = info['file_list']
    return description


def describe_raster(source_dataset_path, scheme):
    """Describe properties of a GDAL raster file.

    Args:
        source_dataset_path (str): path to a GDAL raster.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path, scheme)
    if 'http' in scheme:
        source_dataset_path = f'/vsicurl/{source_dataset_path}'
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    bands = []
    for i in range(info['n_bands']):
        b = i + 1
        bands.append(models.BandSchema(
            index=b,
            gdal_type=gdal.GetDataTypeName(info['datatype']),
            numpy_type=numpy.dtype(info['numpy_type']).name,
            nodata=info['nodata'][i]))
    description['data_model'] = models.RasterSchema(
        bands=bands,
        pixel_size=info['pixel_size'],
        raster_size={'width': info['raster_size'][0],
                     'height': info['raster_size'][1]})
    # Some values of raster info are numpy types, which the
    # yaml dumper doesn't know how to represent.
    bbox = models.BoundingBox(*[float(x) for x in info['bounding_box']])
    epsg_string, units_string = _wkt_to_epsg_units_string(
        info['projection_wkt'])
    description['spatial'] = models.SpatialSchema(
        bounding_box=bbox,
        crs=epsg_string,
        crs_units=units_string)
    description['sources'] = info['file_list']
    return description


def describe_table(source_dataset_path, scheme):
    """Describe properties of a tabular dataset.

    Args:
        source_dataset_path (str): path to a file representing a table.
        scheme (str): the protocol prefix of the filepath

    Returns:
        dict

    """
    description = describe_file(source_dataset_path, scheme)
    description['data_model'] = models.TableSchema(**description['schema'])
    del description['schema']  # we forbid extra args in our Pydantic models
    return description


DESRCIBE_FUNCS = {
    'archive': describe_archive,
    'table': describe_table,
    'vector': describe_vector,
    'raster': describe_raster
}

RESOURCE_MODELS = {
    'archive': models.ArchiveResource,
    'table': models.TableResource,
    'vector': models.VectorResource,
    'raster': models.RasterResource
}


@_osgeo_use_exceptions
def describe(source_dataset_path, profile=None):
    """Create a metadata resource instance with properties of the dataset.

    Properties of the dataset are used to populate as many metadata
    properties as possible. Default/placeholder
    values are used for properties that require user input.

    Args:
        source_dataset_path (string): path or URL to dataset to which the
            metadata applies
        profile (geometamaker.models.Profile): a profile object from
            which to populate some metadata attributes

    Returns:
        geometamaker.models.Resource: a metadata object

    """
    config = Config()
    user_profile = config.profile
    if profile is not None:
        user_profile = user_profile.replace(profile)

    metadata_path = f'{source_dataset_path}.yml'

    # Despite naming, this does not open a file that must be closed
    of = fsspec.open(source_dataset_path)
    if not of.fs.exists(source_dataset_path):
        raise FileNotFoundError(f'{source_dataset_path} does not exist')

    protocol = fsspec.utils.get_protocol(source_dataset_path)
    if protocol not in PROTOCOLS:
        raise ValueError(
            f'Cannot describe {source_dataset_path}. {protocol} '
            f'is not one of the suppored file protocols: {PROTOCOLS}')
    resource_type = detect_file_type(source_dataset_path, protocol)
    description = DESRCIBE_FUNCS[resource_type](
        source_dataset_path, protocol)
    description['type'] = resource_type

    # Load existing metadata file
    try:
        existing_resource = RESOURCE_MODELS[resource_type].load(metadata_path)
        if 'data_model' in description:
            if isinstance(description['data_model'], models.RasterSchema):
                # If existing band metadata still matches data_model of the file
                # carry over existing metadata because it could include
                # human-defined properties.
                new_bands = []
                for band in description['data_model'].bands:
                    try:
                        eband = existing_resource.get_band_description(band.index)
                        # TODO: rewrite this as __eq__ of BandSchema?
                        if (band.numpy_type, band.gdal_type, band.nodata) == (
                                eband.numpy_type, eband.gdal_type, eband.nodata):
                            updated_dict = band.model_dump() | eband.model_dump()
                            band = models.BandSchema(**updated_dict)
                    except IndexError:
                        pass
                    new_bands.append(band)
                description['data_model'].bands = new_bands
            if isinstance(description['data_model'], models.TableSchema):
                # If existing field metadata still matches data_model of the file
                # carry over existing metadata because it could include
                # human-defined properties.
                new_fields = []
                for field in description['data_model'].fields:
                    try:
                        efield = existing_resource.get_field_description(
                            field.name)
                        # TODO: rewrite this as __eq__ of FieldSchema?
                        if field.type == efield.type:
                            updated_dict = field.model_dump() | efield.model_dump()
                            field = models.FieldSchema(**updated_dict)
                    except KeyError:
                        pass
                    new_fields.append(field)
                description['data_model'].fields = new_fields
        # overwrite properties that are intrinsic to the dataset
        updated_dict = existing_resource.model_dump() | description
        resource = RESOURCE_MODELS[resource_type](**updated_dict)

    # Common path: metadata file does not already exist
    # Or less common, ValueError if it exists but is incompatible
    except FileNotFoundError:
        resource = RESOURCE_MODELS[resource_type](**description)

    resource = resource.replace(user_profile)
    return resource


def validate(filepath):
    """Validate a YAML metadata document.

    Validation includes type-checking of property values and
    checking for the presence of required properties.

    Args:
        directory (string): path to a YAML file

    Returns:
        pydantic.ValidationError

    Raises:
        ValueError if the YAML document is not a geometamaker metadata doc.

    """
    with fsspec.open(filepath, 'r') as file:
        yaml_string = file.read()
        yaml_dict = yaml.safe_load(yaml_string)
        if not yaml_dict or ('metadata_version' not in yaml_dict
                             and 'geometamaker_version' not in yaml_dict):
            message = (f'{filepath} exists but is not compatible with '
                       f'geometamaker.')
            raise ValueError(message)

    try:
        RESOURCE_MODELS[yaml_dict['type']](**yaml_dict)
    except ValidationError as error:
        return error


def validate_dir(directory, recursive=False):
    """Validate all compatible yml documents in the directory.

    Args:
        directory (string): path to a directory
        recursive (bool): whether or not to describe files
            in all subdirectories

    Returns:
        tuple (list, list): a list of the filepaths that were validated and
            an equal-length list of the validation messages.

    """
    file_list = []
    if recursive:
        for path, dirs, files in os.walk(directory):
            for file in files:
                file_list.append(os.path.join(path, file))
    else:
        file_list.extend(
            [os.path.join(directory, path)
                for path in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, path))])

    messages = []
    yaml_files = []
    for filepath in file_list:
        if filepath.endswith('.yml'):
            yaml_files.append(filepath)
            msg = ''
            try:
                error = validate(filepath)
                if error:
                    msg = error
            except ValueError:
                msg = 'does not appear to be a geometamaker document'
            except yaml.YAMLError as exc:
                LOGGER.debug(exc)
                msg = 'is not a readable yaml document'
            messages.append(msg)

    return (yaml_files, messages)


def describe_dir(directory, recursive=False):
    """Describe all compatible datasets in the directory.

    Take special care to only describe multifile datasets,
    such as ESRI Shapefiles, one time.

    Args:
        directory (string): path to a directory
        recursive (bool): whether or not to describe files
            in all subdirectories

    Returns:
        None

    """
    root_set = set()
    root_ext_map = defaultdict(set)
    for path, dirs, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(path, file)
            root, ext = os.path.splitext(full_path)
            # tracking which files share a root name
            # so we can check if these comprise a shapefile
            root_ext_map[root].add(ext)
            root_set.add(root)
        if not recursive:
            break

    for root in root_set:
        extensions = root_ext_map[root]
        if '.shp' in extensions:
            # if we're dealing with a shapefile, we do not want to describe any
            # of these other files with the same root name
            extensions.difference_update(['.shx', '.sbn', '.sbx', '.prj', '.dbf'])
        for ext in extensions:
            filepath = f'{root}{ext}'
            try:
                resource = describe(filepath)
            except ValueError as error:
                LOGGER.debug(error)
                continue
            resource.write()
            LOGGER.info(f'{filepath} described')
