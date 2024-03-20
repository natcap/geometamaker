A Python library for creating [Metadata Control Files](https://geopython.github.io/pygeometa/reference/mcf/)

See `requirements.txt` for dependencies

### Some usage patterns:

#### Creating & adding metadata to file:

```python
from geometamaker import MetadataControl

data_path = 'data/watershed_gura.shp'
mc = MetadataControl(data_path)

mc.set_title('My Dataset')
mc.set_abstract('all about my dataset')
mc.set_keywords(['hydrology', 'watersheds'])

# For a vector:
mc.set_field_description(
    'field_name',  # the name of an actual field in the vector's table
    abstract='something about the field',
    units='mm')

# or for a raster:
mc.set_band_description(
    1,  # a raster band index, starting at 1
    name='band name',
    abstract='something about the band',
    units='mm')


mc.validate()
mc.write()
```

#### Creating metadata for a batch of files:
```python
import os

from geometamaker import MetadataControl

data_dir = 'C:/Users/dmf/projects/invest/data/invest-sample-data'
for path, dirs, files in os.walk(data_dir):
    for file in files:
        if file.endswith(('.shp', '.gpkg', '.tif')):
            filepath = os.path.join(path, file)
            print(filepath)
            mc = MetadataControl(filepath)
            mc.validate()
            mc.write()
```

#### For a complete list of methods:
https://geometamaker.readthedocs.io/en/latest/api/geometamaker.html
