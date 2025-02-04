Release History
===============

.. Unreleased Changes

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
