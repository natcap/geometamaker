import logging
import sys
import click

def configure_cli_logging(verbosity):
    """configure logging lazily"""
    import geometamaker

    log_level = logging.ERROR - (verbosity * 10)
    logger = logging.getLogger('geometamaker')
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        fmt='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
        datefmt='%m/%d/%Y %H:%M:%S ')
    handler.setFormatter(formatter)
    # stop global import by dynamically looking up up NOT_FOR_CLI
    not_for_cli_attr = getattr(sys.modules.get('geometamaker.geometamaker'), '_NOT_FOR_CLI', '_not_for_cli')
    logger.addFilter(lambda record: not record.__dict__.get(not_for_cli_attr, False))

    
class LazyGroup(click.Group):
    def list_commands(self, ctx):
        # Hardcode your command names so Click can display them in --help instantly
        return ['describe', 'validate', 'config']

    def get_command(self, ctx, name):
        if name == 'describe':
            # Import the file ONLY when 'describe' is explicitly invoked by the user
            from geometamaker.commands.describe_cmd import describe
            return describe
        elif name == 'validate':
            from geometamaker.commands.validate_cmd import validate
            return validate
        elif name == 'config':
            from geometamaker.commands.config_cmd import config
            return config
        return None

@click.group(
    cls=LazyGroup,
    epilog='https://geometamaker.readthedocs.io/en/latest/ for more details')
@click.option('-v', 'verbosity', count=True, default=2, required=False,
              help='''Override the default verbosity of logging. Use "-vvv" for
              debug-level logging. Omit this flag for default,
              info-level logging.''')
@click.version_option(message="%(version)s")
def cli(verbosity):
    configure_cli_logging(verbosity)
