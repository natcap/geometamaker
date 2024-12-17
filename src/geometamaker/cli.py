import logging
import os
import sys

import click
from pydantic import ValidationError

import geometamaker

# root_logger = logging.getLogger()
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    fmt='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
    datefmt='%m/%d/%Y %H:%M:%S ')
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)  # TODO: take user input


@click.group()
def cli():
    pass


@click.command()
@click.argument('filepath')
@click.option('-r', '--recursive', is_flag=True, default=False)
def describe(filepath, recursive):
    if os.path.isdir(filepath):
        geometamaker.describe_dir(
            filepath, recursive=recursive)
    else:
        geometamaker.describe(filepath).write()


def echo_validation_error(error, filepath):
    summary = u'\u2715' + f' {filepath}: {error.error_count()} validation errors'
    click.secho(summary, fg='bright_red')
    for e in error.errors():
        location = ', '.join(e['loc'])
        msg_string = (f"    {e['msg']}. [input_value={e['input']}, "
                      f"input_type={type(e['input']).__name__}]")
        click.secho(location, bold=True)
        click.secho(msg_string)


@click.command()
@click.argument('filepath')
@click.option('-r', '--recursive', is_flag=True, default=False)
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
    click.echo(f'{config.profile}')
    ctx.exit()


@click.command()
@click.option('--individual_name', prompt=True, default='')
@click.option('--email', prompt=True, default='')
@click.option('--organization', prompt=True, default='')
@click.option('--position_name', prompt=True, default='')
@click.option('--license_title', prompt=True, default='')
@click.option('--license_path', prompt=True, default='')
@click.option('-p', '--print', is_flag=True, is_eager=True,
              callback=print_config, expose_value=False)
def config(individual_name, email, organization, position_name,
           license_path, license_title):
    contact = geometamaker.models.ContactSchema()
    contact.individual_name = individual_name
    contact.email = email
    contact.organization = organization
    contact.position_name = position_name

    license = geometamaker.models.LicenseSchema()
    license.path = license_path
    license.title = license_title

    profile = geometamaker.models.Profile(contact=contact, license=license)
    config = geometamaker.Config()
    config.save(profile)
    click.echo(f'saved profile information to {config.config_path}')


cli.add_command(describe)
cli.add_command(validate)
cli.add_command(config)
