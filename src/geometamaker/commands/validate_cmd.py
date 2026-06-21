import click
import os

def echo_validation_error(error, filepath):
    summary = u'\u2715' + f' {filepath}: {error.error_count()} validation errors'
    click.secho(summary, fg='bright_red')
    for e in error.errors():
        location = '.'.join([str(loc) for loc in e['loc']])
        msg_string = (f"    {e['msg']}. [input_value={e['input']}, "
                      f"input_type={type(e['input']).__name__}]")
        click.secho(location, bold=True)
        click.secho(msg_string)


def echo_is_valid(filepath):
    click.secho(f'\u2713 {filepath} is valid', fg='bright_green')


@click.command(
    help='''Validate a .yml metadata document given by FILEPATH.
    Or if FILEPATH is a directory, validate all documents within.''',
    short_help='Validate metadata documents for syntax or type errors.')
@click.argument('filepath',
                type=click.Path(exists=True))
@click.option('-d', '--depth',
              default=None,
              help='if FILEPATH is a directory, validate files in'
                   ' subdirectories up to depth. Defaults to validating'
                   ' all files.')
def validate(filepath, depth):
    import geometamaker
    import numpy
    from pydantic import ValidationError

    if depth is None:
        depth = numpy.iinfo(numpy.int16).max

    if os.path.isdir(filepath):
        file_list, message_list = geometamaker.validate_dir(
            filepath, depth=depth)
        for filepath, msg in zip(file_list, message_list):
            if isinstance(msg, ValidationError):
                echo_validation_error(msg, filepath)
            elif msg:
                # The file was not a metadata document at all
                click.secho(f'\u25CB {filepath} {msg}', fg='yellow')
            else:
                echo_is_valid(filepath)
    else:
        error = geometamaker.validate(filepath)
        # If the filepath was not a metadata document validate
        # raises an exception rather than returning a message
        if error:
            echo_validation_error(error, filepath)
        else:
            echo_is_valid(filepath)
