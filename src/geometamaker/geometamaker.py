import dataclasses
import hashlib
import logging
from datetime import datetime, timezone

import frictionless
import fsspec
import numpy
from osgeo import gdal
import pygeoprocessing
import yaml

from . import models


LOGGER = logging.getLogger(__name__)

# URI schemes we support. A subset of fsspec.available_protocols()
PROTOCOLS = [
    'file',
    'http',
    'https',
]


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


def detect_file_type(filepath, scheme):
    """Detect the type of resource contained in the file.

    Args:
        filepath (str): path to a file to be opened by GDAL or frictionless

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


def describe_file(source_dataset_path):
    """Describe basic properties of a file.

    Args:
        source_dataset_path (str): path to a file.

    Returns:
        dict

    """
    description = frictionless.describe(source_dataset_path).to_dict()
    # Frictionless can retrieve stats like file size, but doing so necessarily
    # computes a sha256 hash, which is too costly for remote or large files.
    # So we use fsspec to get basic stats and construct a simple hash
    of = fsspec.open(source_dataset_path)
    info = of.fs.info(source_dataset_path)
    description['bytes'] = info['size']
    # files opened from http do not have mtime
    try:
        mtime = info['mtime']
        description['last_modified'] = datetime.fromtimestamp(
            mtime, tz=timezone.utc)
    except KeyError:
        mtime = ''
    hash_func = hashlib.new('sha256')
    hash_func.update(
        f'{info["size"]}{mtime}{description["path"]}'.encode('ascii'))
    description['uid'] = f'sizetimestamp:{hash_func.hexdigest()}'
    return description


def describe_archive(source_dataset_path, scheme=None):
    """Describe file properties of a compressed file.

    Args:
        source_dataset_path (str): path to a file.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path)
    return description


def describe_vector(source_dataset_path, scheme):
    """Describe properties of a GDAL vector file.

    Args:
        source_dataset_path (str): path to a GDAL vector.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path)

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
    description['schema'] = models.TableSchema(fields=fields)

    info = pygeoprocessing.get_vector_info(source_dataset_path)
    spatial = {
        'bounding_box': info['bounding_box'],
        'crs': info['projection_wkt']
    }
    description['spatial'] = models.SpatialSchema(**spatial)
    description['sources'] = info['file_list']
    return description


def describe_raster(source_dataset_path, scheme):
    """Describe properties of a GDAL raster file.

    Args:
        source_dataset_path (str): path to a GDAL raster.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path)
    if 'http' in scheme:
        source_dataset_path = f'/vsicurl/{source_dataset_path}'
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    bands = []
    for i in range(info['n_bands']):
        b = i + 1
        bands.append(models.BandSchema(
            index=b,
            gdal_type=info['datatype'],
            numpy_type=numpy.dtype(info['numpy_type']).name,
            nodata=info['nodata'][i]))
    description['schema'] = models.RasterSchema(
        bands=bands,
        pixel_size=info['pixel_size'],
        raster_size=info['raster_size'])
    # Some values of raster info are numpy types, which the
    # yaml dumper doesn't know how to represent.
    description['spatial'] = models.SpatialSchema(
        bounding_box=[float(x) for x in info['bounding_box']],
        crs=info['projection_wkt'])
    description['sources'] = info['file_list']
    return description


def describe_table(source_dataset_path, scheme=None):
    """Describe properties of a tabular dataset.

    Args:
        source_dataset_path (str): path to a file representing a table.

    Returns:
        dict

    """
    description = describe_file(source_dataset_path)
    description['schema'] = models.TableSchema(**description['schema'])
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


def describe(source_dataset_path):
    """Create a metadata resource instance with properties of the dataset.

    Properties of the dataset are used to populate as many metadata
    properties as possible. Default/placeholder
    values are used for properties that require user input.

    Args:
        source_dataset_path (string): path or URL to dataset to which the
            metadata applies

    Returns
        instance of ArchiveResource, TableResource, VectorResource,
        or RasterResource

    """
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

    # Load existing metadata file
    try:
        existing_resource = RESOURCE_MODELS[resource_type].load(metadata_path)
        if 'schema' in description:
            if isinstance(description['schema'], models.RasterSchema):
                # If existing band metadata still matches schema of the file
                # carry over metadata from the existing file because it could
                # include human-defined properties.
                new_bands = []
                for band in description['schema'].bands:
                    try:
                        eband = existing_resource.get_band_description(band.index)
                        # TODO: rewrite this as __eq__ of BandSchema?
                        if (band.numpy_type, band.gdal_type, band.nodata) == (
                                eband.numpy_type, eband.gdal_type, eband.nodata):
                            band = dataclasses.replace(band, **eband.__dict__)
                    except IndexError:
                        pass
                    new_bands.append(band)
                description['schema'].bands = new_bands
            if isinstance(description['schema'], models.TableSchema):
                # If existing field metadata still matches schema of the file
                # carry over metadata from the existing file because it could
                # include human-defined properties.
                new_fields = []
                for field in description['schema'].fields:
                    try:
                        efield = existing_resource.get_field_description(
                            field.name)
                        # TODO: rewrite this as __eq__ of FieldSchema?
                        if field.type == efield.type:
                            field = dataclasses.replace(field, **efield.__dict__)
                    except KeyError:
                        pass
                    new_fields.append(field)
                description['schema'].fields = new_fields
        # overwrite properties that are intrinsic to the dataset
        resource = dataclasses.replace(
            existing_resource, **description)

    # Common path: metadata file does not already exist
    # Or less common, ValueError if it exists but is incompatible
    except (FileNotFoundError, ValueError) as err:
        resource = RESOURCE_MODELS[resource_type](**description)

    return resource
