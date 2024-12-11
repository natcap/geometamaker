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


cli.add_command(describe)
cli.add_command(validate)
