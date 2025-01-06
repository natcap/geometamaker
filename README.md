A Python library for creating human and machine-readable metadata for geospatial data.

Supported datatypes include:
* everything supported by GDAL
* tabular formats supported by `frictionless`
* compressed formats supported by `frictionless`


See `requirements.txt` for dependencies.

This library comes with a command-line interface (CLI) called `geometamaker`.
Many of the examples below show how to use the Python interface, and then
how to do the same thing, if possible, using the CLI.

### Creating & adding metadata to file:

##### Python

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

##### CLI
```
geometamaker describe data/watershed_gura.shp
```
The CLI does not provide options for setting metadata properties such as 
keywords, field or band descriptions, or other properties that require 
user-input. If you create a metadata document with the CLI, you may wish 
to add these values manually by editing the 
`watershed_gura.shp.yml` file in a text editor.

### Creating metadata for a batch of files:

#### Python

```python
import os

import geometamaker

data_dir = 'C:/Users/dmf/projects/invest/data/invest-sample-data'
geometamaker.describe_dir(data_dir, recursive=True)
```

#### CLI
```
geometamaker describe -r data/invest-sample-data
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

##### Python
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

##### CLI
```
geometamaker config
```
This will prompt the user to enter their profile information.  
Also see `geometamaker config --help`

### For a complete list of methods:
https://geometamaker.readthedocs.io/en/latest/api/geometamaker.html
