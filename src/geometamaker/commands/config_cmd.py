import click

def print_config(ctx, param, value):
    import geometamaker
    if not value or ctx.resilient_parsing:
        return
    config = geometamaker.Config()
    click.echo(config)
    ctx.exit()


def delete_config(ctx, param, value):
    import geometamaker
    if not value or ctx.resilient_parsing:
        return
    config = geometamaker.Config()
    click.confirm(
        f'\nAre you sure you want to delete {config.config_path}?',
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
    import geometamaker
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