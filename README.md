A Python library for creating human and machine-readable metadata for geospatial data.

Supported datatypes include:
* everything supported by GDAL
* tabular formats supported by `frictionless`
* compressed formats supported by `frictionless`


See `requirements.txt` for dependencies

### Creating & adding metadata to file:

```python
import geometamaker

data_path = 'data/watershed_gura.shp'
resource = geometamaker.describe(data_path)

resource.set_title('My Dataset')
resource.set_description('all about my dataset')
resource.set_keywords(['hydrology', 'watersheds'])

# For a vector:
resource.set_field_description(
    'field_name',  # the name of an actual field in the vector's table
    description='something about the field',
    units='mm')

# or for a raster:
data_path = 'data/dem.tif'
resource = geometamaker.describe(data_path)
resource.set_band_description(
    1,  # a raster band index, starting at 1
    description='something about the band',
    units='mm')


resource.write()
```

### Creating metadata for a batch of files:
```python
import os

import geometamaker

data_dir = 'C:/Users/dmf/projects/invest/data/invest-sample-data'
for path, dirs, files in os.walk(data_dir):
    for file in files:
        filepath = os.path.join(path, file)
        print(filepath)
        try:
            resource = geometamaker.describe(filepath)
        except ValueError as err:
            print(err)
        resource.write()
```

### Configuring default values for metadata properties:

Users can create a "profile" that will apply some common properties
to all datasets they describe. Profiles can include `contact` information
and/or `license` information.

A profile can be saved to a configuration file so that it will be re-used
everytime you use `geometamaker`. In addition, users can set a profile
during runtime, which takes precedence over a profile in the config file.

#### Create & apply a Profile at runtime
```python
import os

import geometamaker
from geometamaker import models

contact = {
    'individual_name': 'bob'
}
license = {
    'title': 'CC-BY-4'
}

# Two different ways for setting profile attributes:
profile = models.Profile(contact=contact)  # keyword arguments
profile.set_license(**license)             # `set_*` methods

data_path = 'data/watershed_gura.shp'
# Pass the profile to the `describe` function
resource = geometamaker.describe(data_path, profile=profile)
```

#### Store a Profile in user-configuration
```python
import os

import geometamaker
from geometamaker import models

contact = {
    'individual_name': 'bob'
}

profile = models.Profile(contact=contact)
config = geometamaker.Config()
config.save(profile)

data_path = 'data/watershed_gura.shp'
# A profile saved in the user's configuration file does not
# need to be passed to `describe`. It is always applied.
resource = geometamaker.describe(data_path)
```


### For a complete list of methods:
https://geometamaker.readthedocs.io/en/latest/api/geometamaker.html
