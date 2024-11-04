import yaml


def represent_str(dumper, data):
    scalar = yaml.representer.SafeRepresenter.represent_str(dumper, data)
    if len(data.splitlines()) > 1:
        scalar.style = '|'  # literal style, newline chars will be new lines
    return scalar


# Patch the default string representer so that it uses
# a literal block style when the data contain newline characters
yaml.SafeDumper.add_representer(str, represent_str)


# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
class _NoAliasDumper(yaml.SafeDumper):
    """Keep the yaml human-readable by avoiding anchors and aliases."""

    def ignore_aliases(self, data):
        return True


def yaml_dump(data):
    return yaml.dump(
        data,
        allow_unicode=True,
        Dumper=_NoAliasDumper)
