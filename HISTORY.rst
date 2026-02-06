Release History
===============

Unreleased Changes
------------------
* The Natural Capital Project changed its name to the Natural Capital Alliance.
  References to the old name and website URL have been updated to reflect
  this change. https://github.com/natcap/geometamaker/issues/115

0.2.1 (2026-02-02)
------------------
* Make sure that the option to compute band statistics will include
  STATISTICS_VALID_PERCENT. https://github.com/natcap/geometamaker/issues/106
* Improve the error message if frictionless raises an exception while
  trying to detect a filetype.
  https://github.com/natcap/geometamaker/issues/107
* Fixed bug where non-ascii characters in filepaths raised an exception
  in ``describe``. https://github.com/natcap/geometamaker/issues/112

0.2.0 (2025-07-22)
------------------
* Allow CLI to ``describe`` remote datasets.
  https://github.com/natcap/geometamaker/issues/78
* Add support for describing tar gzip files in the same manner as zip
  archives. https://github.com/natcap/geometamaker/issues/26
* Metadata documents for raster and vector datasets now include metadata
  key:value pairs that are defined on the GDAL raster, band, vector, and
  layer objects. https://github.com/natcap/geometamaker/issues/68
* Added an option to compute raster band statistics when calling ``describe``.
  Statistics are included in the ``gdal_metadata`` section of metadata documents.
  https://github.com/natcap/geometamaker/issues/77
* Vector metadata documents now include a 'data_model.layers' section
  for properties of the dataset that are specific to the layer.
  Existing metadata documents can be migrated to this new schema by
  calling ``describe`` on the vector dataset. GeoMetaMaker still only
  supports describing metadata for the first layer in a vector dataset.
  https://github.com/natcap/geometamaker/issues/28
* Add support for describing folders as collections, generating a single
  metadata file listing contained files along with their descriptions and
  metadata. https://github.com/natcap/geometamaker/issues/66
* ``describe_dir`` has been deprecated as this functionality can be achieved
  with ``describe_collection``. https://github.com/natcap/geometamaker/issues/98
* Existing attributes are now preserved when calling
  ``describe_collection`` on collection with existing metadata.
  https://github.com/natcap/geometamaker/issues/95
* Removed the ``profile`` argument to ``describe``. ``set_contact`` and
  ``set_license`` can still be used to set those metadata properties.
  ``Config`` can still be used to create and store a default profile.
  https://github.com/natcap/geometamaker/issues/92
* If an invalid metadata document exists when a dataset or collection is
  described, do not prevent creation of a new metadata document.
  Invalid/incompatible documents will be renamed by adding a '.bak' extension
  before the new metadata document replaces them.
  https://github.com/natcap/geometamaker/issues/89
* ``geometamaker describe``, when given a directory, will create a
  "-metadata.yml" document for that directory, as well as metadata documents
  for all datasets within.
  https://github.com/natcap/geometamaker/issues/94
* ``geometamaker.validate_dir`` was updated to use the ``depth`` argument
  instead of ``recursive``.
* If ``describe`` is called on a directory, a helpful error message is raised.
  https://github.com/natcap/geometamaker/issues/98


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
