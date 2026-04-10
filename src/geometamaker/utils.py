from osgeo import gdal
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
    gdal.GFU_Generic: 'Generic',
    gdal.GFU_PixelCount: 'PixelCount',
    gdal.GFU_Name: 'Name',
    gdal.GFU_Min: 'Min',
    gdal.GFU_Max: 'Max',
    gdal.GFU_MinMax: 'MinMax',
    gdal.GFU_Red: 'Red',
    gdal.GFU_Green: 'Green',
    gdal.GFU_Blue: 'Blue',
    gdal.GFU_Alpha: 'Alpha',
    gdal.GFU_RedMin: 'RedMin',
    gdal.GFU_GreenMin: 'GreenMin',
    gdal.GFU_BlueMin: 'BlueMin',
    gdal.GFU_AlphaMin: 'AlphaMin',
    gdal.GFU_RedMax: 'RedMax',
    gdal.GFU_GreenMax: 'GreenMax',
    gdal.GFU_BlueMax: 'BlueMax',
    gdal.GFU_AlphaMax: 'AlphaMax',
}

_GFT_INT_TO_STR = {
    gdal.GFT_Integer: 'Integer',
    gdal.GFT_Real: 'Real',
    gdal.GFT_String: 'String',
    3: 'Boolean',      # gdal.GFT_Boolean (not available until GDAL 3.12)
    4: 'DateTime',     # gdal.GFT_DateTime
    5: 'WKBGeometry',  # gdal.GFT_WKBGeometry
}

_GRTT_INT_TO_STR = {
    gdal.GRTT_THEMATIC: 'Thematic',
    gdal.GRTT_ATHEMATIC: 'Athematic'
}
