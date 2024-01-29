# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import datetime
import os
import sys
import sphinx.ext.apidoc
from pkg_resources import get_distribution

sys.path.insert(0, os.path.abspath('../../src/geometamaker'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'geometamaker'
copyright = '2024, The Natural Capital Project'
author = 'The Natural Capital Project'
# release = '0.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',  # support google style docstrings
    'sphinx.ext.autosummary',
]

templates_path = ['_templates']
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# -- Extension configuration -------------------------------------------------

# Nitpicky=True will make sphinx complain about the types matching python types
# _exactly_.  So "string" will be wrong, but "str" right.  I don't think we
# need to be so picky.
nitpicky = False
autoclass_content = 'both'

DOCS_SOURCE_DIR = os.path.dirname(__file__)
sphinx.ext.apidoc.main([
    '--force',
    '-d', '1',  # max depth for TOC
    '-o', os.path.join(DOCS_SOURCE_DIR, 'api'),
    os.path.join(DOCS_SOURCE_DIR, '..', '..', 'src'),
])

release = get_distribution('geometamaker').version
version = '.'.join(release.split('.')[:2])
