import click
import os

# The recommended approach to allowing multiple ParamTypes
# https://github.com/pallets/click/issues/1729
class _ParamUnion(click.ParamType):
    def __init__(self, types, report_all_errors=True):
        """Union of click.ParamTypes.

        Args:
            types (list): List of click.ParamTypes to try to convert the value.
            report_all_errors (bool): If True, all errors will be reported.
                If False, only the last error will be reported.

        """
        self.types = types
        self.report_all_errors = report_all_errors

    def convert(self, value, param, ctx):
        errors = []
        for type_ in self.types:
            try:
                return type_.convert(value, param, ctx)
            except click.BadParameter as e:
                errors.append(e)
                continue

        if self.report_all_errors:
            self.fail(errors)
        else:
            # If errors from different types are expected to
            # be very similar, just report the last one.
            self.fail(errors.pop())


# https://click.palletsprojects.com/en/stable/parameters/#how-to-implement-custom-types
class _URL(click.ParamType):
    """A type that asserts a URL exists."""

    name = "url"

    def convert(self, value, param, ctx):
        import fsspec
        of = fsspec.open(value)
        if not of.fs.exists(value):
            self.fail(f'{value} does not exist', param, ctx)

        return value

@click.command(
    help='''Describe properties of a dataset given by FILEPATH and write this
    metadata to a .yml sidecar file. Or if FILEPATH is a directory, describe
    all datasets within.''',
    short_help='Generate metadata for geospatial or tabular data, compressed'
               ' archives, or collections of files in a directory.')
@click.argument('filepath',
                type=_ParamUnion([click.Path(exists=True), _URL()],
                                 report_all_errors=False))
@click.option('-nw', '--no-write',
              is_flag=True,
              default=False,
              help='Dump metadata to stdout instead of to a .yml file.'
                   ' This option is ignored when describing all files'
                   ' in a directory.')
@click.option('-st', '--stats',
              is_flag=True,
              default=False,
              help='Compute raster band statistics.')
@click.option('-d', '--depth',
              default=None,
              help='if FILEPATH is a directory, describe files in'
                   ' subdirectories up to depth. Defaults to describing'
                   ' all files.')
@click.option('-x', '--exclude',
              default=None,
              help='Regular expression used to exclude files from being'
                   ' described. Only used if FILEPATH is a directory.')
@click.option('-a', '--all', 'all_files',
              is_flag=True,
              default=False,
              help='Do not ignore files starting with .'
                   ' Only used if FILEPATH is a directory.')
@click.option('-co', '--collection-only',
              is_flag=True,
              default=False,
              help='If FILEPATH is a directory, do not write metadata documents'
                   ' for all files in the directory. Only create a single'
                   ' *-metadata.yml document for the collection')
@click.option('-o', '--output', 'target_filename',
              default=None,
              help='if FILEPATH is a directory, this is the filename of the'
                   ' target YML document to be created within the directory.'
                   ' If output is not specified, the filename will be'
                   ' <directory_name>-metadata.yml.')
def describe(filepath, depth, exclude, all_files, no_write, stats,
             collection_only, target_filename):
    import geometamaker
    import numpy

    if depth is None:
        depth = numpy.iinfo(numpy.int16).max

    describing_single = True  # if filepath is a file, or collection_only=True
    if os.path.isdir(filepath):
        resource = geometamaker.describe_collection(
            filepath,
            depth=depth,
            exclude_regex=exclude,
            exclude_hidden=(not all_files),
            describe_files=(not collection_only),
            compute_stats=stats,
            target_filename=target_filename)
        describing_single = collection_only
    else:
        resource = geometamaker.describe(filepath, compute_stats=stats)

    if no_write and describing_single:
        click.echo(geometamaker.utils.yaml_dump(
            resource._dump_for_write()))
        return

    if no_write and not describing_single:
        click.echo('the -nw, or --no-write, flag is ignored when '
                   'describing all files in a directory.')
    if resource._would_overwrite:
        click.confirm(
            f'\n{resource.metadata_path} is about to be overwritten'
            ' because it is not a valid metadata document.\n'
            'Are you sure want to continue?',
            abort=True)
    try:
        # Users can abort at the confirm and manage their own backups.
        resource.write(backup=True)
    except OSError:
        click.echo(
            f'geometamaker could not write to {resource.metadata_path}\n'
            'Try using the --no-write flag to print metadata to '
            'stdout instead:')
        click.echo(f'    geometamaker describe --no-write {filepath}')
