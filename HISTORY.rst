Release History
===============

Unreleased Changes
------------------
* Allow CLI to ``describe`` remote datasets.
  https://github.com/natcap/geometamaker/issues/78
* Add support for describing tar gzip files in the same manner as zip
  archives. https://github.com/natcap/geometamaker/issues/26
* Metadata documents for raster and vector datasets now include metadata
  key:value pairs that are defined on the GDAL raster, band, vector, and
  layer objects. https://github.com/natcap/geometamaker/issues/68
* Vector metadata documents now include a 'data_model.layers' section
  for properties of the dataset that are specific to the layer.
  Existing metadata documents can be migrated to this new schema by
  calling ``describe`` on the vector dataset. GeoMetaMaker still only
  supports describing metadata for the first layer in a vector dataset.
  https://github.com/natcap/geometamaker/issues/28
* Add support for describing folders as collections, generating a single
  metadata file listing contained files along with their descriptions and
  metadata. https://github.com/natcap/geometamaker/issues/66
* ``describe_dir`` has been renamed to ``describe_all`` and the parameter
  ``recursive`` has been replaced with ``depth`` to allow for more
  fine-grained control.
* Existing attributes are now preserved when calling
  ``describe_collection`` on collection with existing metadata.
  https://github.com/natcap/geometamaker/issues/95

0.1.2 (2025-02-05)
------------------
* Declared dependencies in ``pyproject.toml`` to facilitate pip installs.

0.1.1 (2025-02-04)
------------------
* Fixed a bug where rasters without a defined nodata value could not be
  described. https://github.com/natcap/geometamaker/issues/70
* All YAML documents will be written as UTF-8 encoded files.
  https://github.com/natcap/geometamaker/issues/71
* Fixed a bug in formatting of validation messages about nested attributes
  https://github.com/natcap/geometamaker/issues/65
* Added exception handling to make validating directories more resilient to
  unreadable yaml files. https://github.com/natcap/geometamaker/issues/62

0.1.0 (2025-01-10)
------------------
* First release!
