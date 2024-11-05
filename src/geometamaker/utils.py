import yaml


def _represent_str(dumper, data):
    scalar = yaml.representer.SafeRepresenter.represent_str(dumper, data)
    if len(data.splitlines()) > 1:
        scalar.style = '|'  # literal style, newline chars will be new lines
    return scalar


class _SafeDumper(yaml.SafeDumper):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Patch the default string representer to use a literal block
        # style when the data contain newline characters
        self.add_representer(str, _represent_str)

    # https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
    def ignore_aliases(self, data):
        """Keep the yaml human-readable by avoiding anchors and aliases."""
        return True


def yaml_dump(data):
    return yaml.dump(
        data,
        allow_unicode=True,
        Dumper=_SafeDumper)
