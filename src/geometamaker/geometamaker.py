import functools
import hashlib
import logging
import os
import re
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
from pathlib import Path
from pydantic import ValidationError
import tarfile

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


def _list_files_with_depth(directory, depth, exclude_regex,
                           exclude_hidden=True):
    """List files in directory up to depth

    Args:
        directory (string): path to a directory
        depth (int): maximum number of subdirectory levels to traverse when
            walking through a directory. A value of 1 limits the walk to files
            in the top-level ``directory`` only. A value of 2 allows
            descending into immediate subdirectories, etc.
        exclude_regex (str, optional): a regular expression to pattern-match
            any files for which you do not want to create metadata.
        exclude_hidden (bool, default True): whether to ignore hidden files

    Returns:
        list of relative filepaths in ``directory``

    """
    directory = Path(directory).resolve()
    file_list = []

    for path in directory.rglob("*"):
        relative_path = path.relative_to(directory)
        current_depth = len(relative_path.parts)
        if current_depth > depth:
            continue
        if exclude_hidden and (
                any(part.startswith('.') for part in relative_path.parts)):
            continue
        file_list.append(str(relative_path))

    # remove excluded files based on regex
    if exclude_regex:
        file_list = [f for f in file_list if not re.search(exclude_regex, f)]

    return sorted(file_list)


def _group_files_by_root(file_list):
    """Get set of files (roots) and extensions by filename"""
    root_set = set()
    root_ext_map = defaultdict(set)
    for filepath in file_list:
        root, ext = os.path.splitext(filepath)
        # tracking which files share a root name
        # so we can check if these comprise a shapefile
        root_ext_map[root].add(ext)
        root_set.add(root)
    return root_ext_map, sorted(list(root_set))


def _get_collection_size_time_uid(directory):
    """Get size of directory (in bytes), when it was last modified, and uid"""
    total_bytes = 0
    latest_mtime = 0

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            stat = os.stat(file_path)
            total_bytes += stat.st_size
            latest_mtime = max(latest_mtime, stat.st_mtime)

    last_modified = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
    last_modified_str = last_modified.strftime('%Y-%m-%d %H:%M:%S %Z')

    hash_func = hashlib.sha256()
    hash_func.update(
        f'{total_bytes}{last_modified_str}{directory}'.encode('utf-8'))
    uid = f'sizetimestamp:{hash_func.hexdigest()}'

    return total_bytes, last_modified_str, uid


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
    # Frictionless doesn't recognize .tgz compression (but does recognize .tar.gz)
    if info.compression or info.format == "tgz":
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


def describe_archive(source_dataset_path, scheme, **kwargs):
    """Describe file properties of a compressed file.

    Args:
        source_dataset_path (str): path to a file.
        scheme (str): the protocol prefix of the filepath

    Returns:
        dict

    """
    def _list_tgz_contents(path):
        """List contents of a .tar, .tgz, or .tar.gz archive."""
        file_list = []
        with fsspec.open(path, 'rb') as fobj:
            with tarfile.open(fileobj=fobj, mode='r:*') as tar:
                file_list = [member.name for member in tar.getmembers()
                             if member.isfile()]
        return file_list

    def _list_zip_contents(path):
        """List contents of a zip archive"""
        file_list = []
        ZFS = fsspec.get_filesystem_class('zip')
        zfs = ZFS(path)
        for dirpath, _, files in zfs.walk(zfs.root_marker):
            for f in files:
                file_list.append(os.path.join(dirpath, f))
        return file_list

    description = describe_file(source_dataset_path, scheme)
    # innerpath is from frictionless and not useful because
    # it does not include all the files contained in the zip
    description.pop('innerpath', None)

    if description.get("compression") == "zip":
        file_list = _list_zip_contents(source_dataset_path)
    elif description.get("format") in ["tgz", "tar"]:
        file_list = _list_tgz_contents(source_dataset_path)
        # 'compression' attr not auto-added by frictionless.describe for .tgz
        # (but IS added for .tar.gz)
        if source_dataset_path.endswith((".tgz")):
            description["compression"] = "gz"
    else:
        raise ValueError(f"Unsupported archive format: {source_dataset_path}")

    description['sources'] = file_list
    return description


def describe_vector(source_dataset_path, scheme, **kwargs):
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
    for fld in layer.schema:
        fields.append(
            models.FieldSchema(name=fld.name, type=fld.GetTypeName()))
    layer_schema = models.LayerSchema(
        name=layer.GetName(),
        n_features=layer.GetFeatureCount(),
        table=models.TableSchema(fields=fields),
        gdal_metadata=layer.GetMetadata())
    description['data_model'] = models.VectorSchema(
        layers=[layer_schema],
        gdal_metadata=vector.GetMetadata())
    vector = layer = None

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


def describe_raster(source_dataset_path, scheme, **kwargs):
    """Describe properties of a GDAL raster file.

    Args:
        source_dataset_path (str): path to a GDAL raster.

    Returns:
        dict

    """
    compute_stats = kwargs.get('compute_stats', False)
    description = describe_file(source_dataset_path, scheme)
    if 'http' in scheme:
        source_dataset_path = f'/vsicurl/{source_dataset_path}'
    info = pygeoprocessing.get_raster_info(source_dataset_path)
    raster = gdal.OpenEx(source_dataset_path)
    raster_gdal_metadata = raster.GetMetadata()
    bands = []
    for i in range(info['n_bands']):
        b = i + 1
        band = raster.GetRasterBand(b)
        if compute_stats:
            try:
                _ = band.ComputeStatistics(0)
            except RuntimeError as e:
                LOGGER.warning(
                    f'Could not compute statistics for band {b} of '
                    f'{source_dataset_path}: {e}')
        band_gdal_metadata = band.GetMetadata()

        bands.append(models.BandSchema(
            index=b,
            gdal_type=gdal.GetDataTypeName(info['datatype']),
            numpy_type=numpy.dtype(info['numpy_type']).name,
            nodata=info['nodata'][i],
            gdal_metadata=band_gdal_metadata))
        band = None
    raster = None

    description['data_model'] = models.RasterSchema(
        bands=bands,
        pixel_size=info['pixel_size'],
        raster_size={'width': info['raster_size'][0],
                     'height': info['raster_size'][1]},
        gdal_metadata=raster_gdal_metadata)
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


def describe_table(source_dataset_path, scheme, **kwargs):
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


def describe_collection(directory, depth=numpy.iinfo(numpy.int16).max,
                        exclude_regex=None, exclude_hidden=True,
                        describe_files=False):
    """Create a single metadata document to describe a collection of files.

    Describe all the files within a directory as members of a "collection".
    The resulting metadata resource should include a list of all the files
    included in the collection along with a description and metadata filepath
    (or placeholder).

    This is distinct from ``describe_all``, which
    creates individual metadata files for each supported file in a directory.

    Args:
        directory (str): path to collection
        depth (int, optional): maximum number of subdirectory levels to
            traverse when walking through ``directory`` to find files included
            in the collection. A value of 1 limits the walk to files in the
            top-level ``directory`` only. A value of 2 allows descending into
            immediate subdirectories, etc. All files in all subdirectories in
            the collection will be included by default.
        exclude_regex (str, optional): a regular expression to pattern-match
            any files you do not want included in the output metadata yml.
        exclude_hidden (bool, default True): whether to exclude hidden files
            (files that start with ".").
        describe_files (bool, default False): whether to ``describe`` all
            files, i.e., create individual metadata files for each supported
            resource in the collection.

    Returns:
        Collection metadata
    """
    directory = str(Path(directory).resolve())

    file_list = _list_files_with_depth(directory, depth, exclude_regex,
                                       exclude_hidden)

    root_ext_map, root_list = _group_files_by_root(file_list)

    items = []

    for root in root_list:
        extensions = root_ext_map[root]
        if '.shp' in extensions:
            # if we're dealing with a shapefile, we do not want to describe any
            # of these other files with the same root name
            extensions.difference_update(['.shx', '.sbn', '.sbx', '.prj', '.dbf', '.cpg'])
        # Only drop .yml if its sidecar file, i.e. the corresponding data file
        # (root) exists on disk
        if '.yml' in extensions and os.path.exists(root):
            extensions.discard('.yml')
        for ext in extensions:
            filepath = os.path.join(directory, f'{root}{ext}')
            try:
                this_desc = describe(filepath)
            except (ValueError, frictionless.FrictionlessException):
                # if file type isn't supported by geometamaker, e.g. pdf
                # or if trying to describe a dir
                this_desc = None

            if describe_files and this_desc:
                this_desc.write()

            if ext and os.path.exists(filepath + '.yml'):
                metadata_yml = f'{root}{ext}' + '.yml'
            else:
                metadata_yml = ''

            this_resource = models.CollectionItemSchema(
                path=f'{root}{ext}',
                description=this_desc.description if this_desc else '',
                metadata=metadata_yml
            )
            items.append(this_resource)

    total_bytes, last_modified, uid = _get_collection_size_time_uid(directory)

    resource = models.CollectionResource(
        path=directory,
        type='collection',
        format='directory',
        scheme=fsspec.utils.get_protocol(directory),
        bytes=total_bytes,
        last_modified=last_modified,
        items=items,
        uid=uid
    )

    # Check if there is existing metadata for the collection
    try:
        existing_metadata = models.CollectionResource.load(
            f'{directory}-metadata.yml')

        # Copy any existing item descriptions from existing yml to new metadata
        # Note that descriptions in individual resources' ymls will take
        # priority over item descriptions from preexisting collection metadata
        for item in resource.items:
            # Existing metadata's item desc will overwrite new metadata item
            # desc if new item desc is ''
            existing_item_desc = [
                i.description for i in existing_metadata.items if (
                    i.path == item.path)]
            if item.description == '' and len(existing_item_desc) > 0:
                item.description = existing_item_desc[0]

        # Replace fields in existing yml if new metadata has existing value
        resource = existing_metadata.replace(resource)

    except FileNotFoundError:
        pass

    # Add profile metadata
    config = Config()
    resource = resource.replace(config.profile)

    return resource


DESCRIBE_FUNCS = {
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
def describe(source_dataset_path, profile=None, **kwargs):
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
    description = DESCRIBE_FUNCS[resource_type](
        source_dataset_path, protocol, **kwargs)
    description['type'] = resource_type
    resource = RESOURCE_MODELS[resource_type](**description)

    # Load existing metadata file
    try:
        # For the data model, use heuristic to decide if the new resource
        # should inherit values from the existing resource.
        # After that, take all non-empty values from the new resource
        # and update the existing resource.
        existing_resource = RESOURCE_MODELS[resource_type].load(metadata_path)
        if resource_type == 'raster':
            for band in resource.data_model.bands:
                try:
                    eband = existing_resource.get_band_description(band.index)
                except IndexError:
                    continue
                if (band.numpy_type, band.gdal_type, band.nodata) == (
                        eband.numpy_type, eband.gdal_type, eband.nodata):
                    resource.set_band_description(
                        band.index,
                        title=eband.title,
                        description=eband.description,
                        units=eband.units)
        if resource_type in ('vector', 'table'):
            for field in resource._get_fields():
                try:
                    efield = existing_resource.get_field_description(field.name)
                except KeyError:
                    continue
                if field.type == efield.type:
                    resource.set_field_description(
                        field.name,
                        title=efield.title,
                        description=efield.description,
                        units=efield.units)
        resource = existing_resource.replace(resource)

    # Common path: metadata file does not already exist
    except FileNotFoundError:
        pass

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


def describe_all(directory, depth=numpy.iinfo(numpy.int16).max,
                 exclude_regex=None, **kwargs):
    """Describe compatible datasets in the directory.

    Take special care to only describe multifile datasets,
    such as ESRI Shapefiles, one time.

    Args:
        directory (string): path to a directory
        depth (int): maximum number of subdirectory levels to traverse when
            walking through a directory. A value of 1 limits the walk to files
            in the top-level ``directory`` only. A value of 2 allows
            descending into immediate subdirectories, etc. By default, all
            supported files in all subdirectories in ``directory`` will
            be described.
        exclude_regex (str, optional): a regular expression to pattern-match
            any files for which you do not want to create metadata.
    Returns:
        None

    """
    file_list = _list_files_with_depth(directory, depth, exclude_regex)
    root_ext_map, root_set = _group_files_by_root(file_list)

    for root in root_set:
        extensions = root_ext_map[root]
        if '.shp' in extensions:
            # if we're dealing with a shapefile, we do not want to describe any
            # of these other files with the same root name
            extensions.difference_update(
                ['.shx', '.sbn', '.sbx', '.prj', '.dbf', '.cpg'])
        for ext in extensions:
            filepath = os.path.join(directory, f'{root}{ext}')
            try:
                resource = describe(filepath, **kwargs)
            except (ValueError, frictionless.FrictionlessException) as error:
                LOGGER.debug(error)
                continue
            resource.write()
            LOGGER.info(f'{filepath} described')
