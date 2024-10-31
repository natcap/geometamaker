import yaml


class FoldedStr(str):
    pass


def _change_style(style, representer):
    def new_representer(dumper, data):
        scalar = representer(dumper, data)
        scalar.style = style
        return scalar
    return new_representer


represent_folded_str = _change_style(
    '>', yaml.representer.SafeRepresenter.represent_str)
yaml.SafeDumper.add_representer(FoldedStr, represent_folded_str)


# https://stackoverflow.com/questions/13518819/avoid-references-in-pyyaml
class _NoAliasDumper(yaml.SafeDumper):
    """Keep the yaml human-readable by avoiding anchors and aliases."""

    def ignore_aliases(self, data):
        return True


def _yaml_dump(data):
    return yaml.dump(
        data,
        allow_unicode=True,
        Dumper=_NoAliasDumper)
