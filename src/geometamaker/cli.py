import logging
import os
import sys

import click
from pydantic import ValidationError

import geometamaker

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    fmt='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
    datefmt='%m/%d/%Y %H:%M:%S ')
handler.setFormatter(formatter)


@click.command(
    help='''Describe properties of a dataset given by FILEPATH and write this
    metadata to a .yml sidecar file. Or if FILEPATH is a directory, describe
    all datasets within.''',
    short_help='Generate metadata for geospatial or tabular data, or zip archives.')
@click.argument('filepath', type=click.Path(exists=True))
@click.option('-r', '--recursive', is_flag=True, default=False,
              help='if FILEPATH is a directory, describe files '
                   'in all subdirectories')
@click.option('-nw', '--no-write', is_flag=True, default=False,
              help='Dump metadata to stdout instead of to a .yml file. '
                   'This option is ignored if `filepath` is a directory')
def describe(filepath, recursive, no_write):
    if os.path.isdir(filepath):
        if no_write:
            click.echo('the -nw, or --no-write, flag is ignored when '
                       'describing all files in a directory.')
        geometamaker.describe_dir(
            filepath, recursive=recursive)
    else:
        resource = geometamaker.describe(filepath)
        if no_write:
            click.echo(geometamaker.utils.yaml_dump(
                resource.model_dump(exclude=['metadata_path'])))
        else:
            resource.write()


def echo_validation_error(error, filepath):
    summary = u'\u2715' + f' {filepath}: {error.error_count()} validation errors'
    click.secho(summary, fg='bright_red')
    for e in error.errors():
        location = ', '.join(e['loc'])
        msg_string = (f"    {e['msg']}. [input_value={e['input']}, "
                      f"input_type={type(e['input']).__name__}]")
        click.secho(location, bold=True)
        click.secho(msg_string)


@click.command(
    help='''Validate a .yml metadata document given by FILEPATH.
    Or if FILEPATH is a directory, validate all documents within.''',
    short_help='Validate metadata documents for syntax or type errors.')
@click.argument('filepath', type=click.Path(exists=True))
@click.option('-r', '--recursive', is_flag=True, default=False,
              help='if `filepath` is a directory, validate documents '
                   'in all subdirectories.')
def validate(filepath, recursive):
    if os.path.isdir(filepath):
        file_list, message_list = geometamaker.validate_dir(
            filepath, recursive=recursive)
        for filepath, msg in zip(file_list, message_list):
            if isinstance(msg, ValidationError):
                echo_validation_error(msg, filepath)
            else:
                color = 'yellow'
                icon = u'\u25CB'
                if not msg:
                    color = 'bright_green'
                    icon = u'\u2713'
                click.secho(f'{icon} {filepath} {msg}', fg=color)
    else:
        error = geometamaker.validate(filepath)
        if error:
            echo_validation_error(error, filepath)


def print_config(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    config = geometamaker.Config()
    click.echo(config)
    ctx.exit()


def delete_config(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    config = geometamaker.Config()
    click.confirm(
        f'Are you sure you want to delete {config.config_path}?',
        abort=True)
    config.delete()
    ctx.exit()


@click.command(
    short_help='''Configure GeoMetaMaker with information to apply to all
    metadata descriptions''',
    help='''When prompted, enter contact and data-license information
    that will be stored in a user profile. This information will automatically
    populate contact and license sections of any metadata described on your
    system. Press enter to leave any field blank.''')
@click.option('--individual-name', prompt=True, default='')
@click.option('--email', prompt=True, default='')
@click.option('--organization', prompt=True, default='')
@click.option('--position-name', prompt=True, default='')
@click.option('--license-title', prompt=True, default='',
              help='the name of a data license, e.g. "CC-BY-4.0"')
@click.option('--license-url', prompt=True, default='',
              help='a url for a data license')
@click.option('-p', '--print', is_flag=True, is_eager=True,
              callback=print_config, expose_value=False,
              help='Print your current GeoMetaMaker configuration.')
@click.option('--delete', is_flag=True, is_eager=True,
              callback=delete_config, expose_value=False,
              help='Delete your configuration file.')
def config(individual_name, email, organization, position_name,
           license_url, license_title):
    contact = geometamaker.models.ContactSchema()
    contact.individual_name = individual_name
    contact.email = email
    contact.organization = organization
    contact.position_name = position_name

    license = geometamaker.models.LicenseSchema()
    license.path = license_url
    license.title = license_title

    profile = geometamaker.models.Profile(contact=contact, license=license)
    config = geometamaker.Config()
    config.save(profile)
    click.echo(f'saved profile information to {config.config_path}')


@click.group()
@click.option('-v', 'verbosity', count=True, default=2, required=False,
              help='''Override the default verbosity of logging. Use "-vvv" for
              debug-level logging. Omit this flag for default,
              info-level logging.''')
@click.version_option(message="%(version)s")
def cli(verbosity):
    log_level = logging.ERROR - verbosity*10
    handler.setLevel(log_level)
    root_logger.addHandler(handler)


cli.add_command(describe)
cli.add_command(validate)
cli.add_command(config)
