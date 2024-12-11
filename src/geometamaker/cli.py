# import argparse
import logging
import os
import sys

import click

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


@click.command()
@click.argument('filepath')
@click.option('-r', '--recursive', is_flag=True, default=False)
def validate(filepath, recursive):
    if os.path.isdir(filepath):
        file_list, message_list = geometamaker.validate_dir(
            filepath, recursive=recursive)
        for filepath, msg in zip(file_list, message_list):
            click.echo(f'{filepath}: {msg}\n')
    else:
        validation_message = geometamaker.validate(filepath)
        if validation_message:
            click.echo(validation_message)


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
@click.option('-p', '--print', is_flag=True, is_eager=True, callback=print_config, expose_value=False)
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
    # click.echo(f'{profile}')
    config = geometamaker.Config()
    config.save(profile)
    click.echo(f'saved profile information to {config.config_path}')


cli.add_command(describe)
cli.add_command(validate)
cli.add_command(config)
