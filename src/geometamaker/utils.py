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
        sort_keys=False,
        Dumper=_SafeDumper)


# GDALGetRATFieldUsageName() and GDALGetRATFieldTypeName() were only added to
# GDAL in 3.12, so we can maintain our own lookups.
_GFU_INT_TO_STR = {
    0: 'Generic',
    1: 'PixelCount',
    2: 'Name',
    3: 'Min',
    4: 'Max',
    5: 'MinMax',
    6: 'Red',
    7: 'Green',
    8: 'Blue',
    9: 'Alpha',
    10: 'RedMin',
    11: 'GreenMin',
    12: 'BlueMin',
    13: 'AlphaMin',
    14: 'RedMax',
    15: 'GreenMax',
    16: 'BlueMax',
    17: 'AlphaMax',
}

_GFT_INT_TO_STR = {
    0: 'Integer',
    1: 'Real',
    2: 'String',
    3: 'Boolean',
    4: 'DateTime',
    5: 'WKBGeometry',
}

_GRTT_INT_TO_STR = {
    0: 'Thematic',
    1: 'Athematic'
}
