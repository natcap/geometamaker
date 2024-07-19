import dataclasses
import logging
import os
import uuid
from datetime import datetime

import frictionless
import fsspec
import numpy
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
import pygeoprocessing
import yaml

from . import models


LOGGER = logging.getLogger(__name__)


def detect_file_type(filepath):
    # TODO: zip, or other archives. Can they be represented as a Resource?
    # or do they need to be a Package?

    # TODO: guard against classifying netCDF, HDF5, etc as GDAL rasters,
    # we'll want a different data model for multi-dimensional arrays.

    # GDAL considers CSV a vector, so check against frictionless
    # first.
    desc = frictionless.describe(filepath)
    if desc.type == 'table':
        return 'table'
    if desc.compression:
        return 'archive'
    gis_type = pygeoprocessing.get_gis_type(filepath)
    if gis_type == pygeoprocessing.VECTOR_TYPE:
        return 'vector'
    if gis_type == pygeoprocessing.RASTER_TYPE:
        return 'raster'
    raise ValueError()


def describe_archive(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()
    return description


def describe_vector(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()
    fields = []
    vector = gdal.OpenEx(source_dataset_path, gdal.OF_VECTOR)
    layer = vector.GetLayer()
    description['rows'] = layer.GetFeatureCount()
    for fld in layer.schema:
        fields.append(
            models.FieldSchema(name=fld.name, type=fld.type))
    vector = layer = None
    description['schema'] = models.TableSchema(fields=fields)
    description['fields'] = len(fields)

    info = pygeoprocessing.get_vector_info(source_dataset_path)
    spatial = {
        'bounding_box': info['bounding_box'],
        'crs': info['projection_wkt']
    }
    description['spatial'] = models.SpatialSchema(**spatial)
    description['sources'] = info['file_list']
    return description


def describe_raster(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()

    bands = []
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    # Some values of raster info are numpy types, which the
    # yaml dumper doesn't know how to represent.
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
    description['spatial'] = models.SpatialSchema(
        bounding_box=[float(x) for x in info['bounding_box']],
        crs=info['projection_wkt'])
    description['sources'] = info['file_list']
    return description


def describe_table(source_dataset_path):
    description = frictionless.describe(
        source_dataset_path, stats=True).to_dict()
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


class MetadataControl(object):
    """Encapsulates the Metadata Control File and methods for populating it.

    A Metadata Control File (MCF) is a YAML file that complies with the
    MCF specification defined by pygeometa.
    https://github.com/geopython/pygeometa

    Attributes:
        datasource (string): path to dataset to which the metadata applies
        mcf (dict): dict representation of the Metadata Control File

    """


def describe(source_dataset_path):
    """Create a metadata resource instance with properties of the dataset.

    Properties of the dataset are used to populate as many metadata
    properties as possible. Default/placeholder
    values are used for properties that require user input.

    Args:
        source_dataset_path (string): path or URL to dataset to which the
            metadata applies

    Returns
        one of TableResource, VectorResource, RasterResource
    """

    data_package_path = f'{source_dataset_path}.yml'

    # Despite naming, this does not open a resource that must be closed
    of = fsspec.open(source_dataset_path)
    if not of.fs.exists(source_dataset_path):
        raise FileNotFoundError(f'{source_dataset_path} does not exist')

    resource_type = detect_file_type(source_dataset_path)
    description = DESRCIBE_FUNCS[resource_type](source_dataset_path)
    # this is nice for autodetect of field types, but sometimes
    # we will know the table schema (invest MODEL_SPEC).
    # Is there any benefit to passing in the known schema? Maybe not
    # Can also just overwrite the schema attribute with known data after.

    # Load existing metadata file
    try:
        with fsspec.open(data_package_path, 'r') as file:
            yaml_string = file.read()

        # This validates the existing yaml against our dataclasses.
        existing_resource = RESOURCE_MODELS[resource_type](
            **yaml.safe_load(yaml_string))
        # overwrite properties that are intrinsic to the dataset,
        # which is everything from `description` other than schema.
        # Some parts of schema are intrinsic, but others are human-input
        # so replace the whole thing for now.
        del description['schema']
        resource = dataclasses.replace(
            existing_resource, **description)

    # Common path: metadata file does not already exist
    except FileNotFoundError as err:
        resource = RESOURCE_MODELS[resource_type](**description)

    return resource

