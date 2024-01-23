A Python library for creating [Metadata Control Files](https://geopython.github.io/pygeometa/reference/mcf/)

See `requirements.txt` for dependencies

### Some usage patterns:

#### Creating & adding metadata to file:

```python
from geometamaker.mcf import MCF

data_path = 'data/watershed_gura.shp'
mcf = MCF(data_path)

mcf.set_title('My Dataset')
mcf.set_abstract('all about my dataset')
mcf.set_keywords(['hydrology', 'watersheds'])

# For a vector:
mcf.describe_field(
    'field_name',  # the name of an actual field in the vector's table
    abstract='something about the field',
    units='mm')

# or for a raster:
mcf.describe_band(
    1,  # a raster band index, starting at 1
    name='band name',
    abstract='something about the band',
    units='mm')


mcf.validate()
mcf.write()
```

#### Creating metadata for a batch of files:
```python
import os

from geometamaker.mcf import MCF

data_dir = 'C:/Users/dmf/projects/invest/data/invest-sample-data'
for path, dirs, files in os.walk(data_dir):
    for file in files:
        if file.endswith(('.shp', '.gpkg', '.tif')):
            filepath = os.path.join(path, file)
            print(filepath)
            mcf = MCF(filepath)
            mcf.validate()
            mcf.write()
```
