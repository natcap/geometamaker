from osgeo import gdalconst
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
    gdalconst.GFU_Generic: 'Generic',
    gdalconst.GFU_PixelCount: 'PixelCount',
    gdalconst.GFU_Name: 'Name',
    gdalconst.GFU_Min: 'Min',
    gdalconst.GFU_Max: 'Max',
    gdalconst.GFU_MinMax: 'MinMax',
    gdalconst.GFU_Red: 'Red',
    gdalconst.GFU_Green: 'Green',
    gdalconst.GFU_Blue: 'Blue',
    gdalconst.GFU_Alpha: 'Alpha',
    gdalconst.GFU_RedMin: 'RedMin',
    gdalconst.GFU_GreenMin: 'GreenMin',
    gdalconst.GFU_BlueMin: 'BlueMin',
    gdalconst.GFU_AlphaMin: 'AlphaMin',
    gdalconst.GFU_RedMax: 'RedMax',
    gdalconst.GFU_GreenMax: 'GreenMax',
    gdalconst.GFU_BlueMax: 'BlueMax',
    gdalconst.GFU_AlphaMax: 'AlphaMax',
}

_GFT_INT_TO_STR = {
    gdalconst.GFT_Integer: 'Integer',
    gdalconst.GFT_Real: 'Real',
    gdalconst.GFT_String: 'String',
    gdalconst.GFT_Boolean: 'Boolean',
    gdalconst.GFT_DateTime: 'DateTime',
    gdalconst.GFT_WKBGeometry: 'WKBGeometry',
}

_GRTT_INT_TO_STR = {
    gdalconst.GRTT_THEMATIC: 'Thematic',
    gdalconst.GRTT_ATHEMATIC: 'Athematic'
}
