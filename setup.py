#!/usr/bin/env python

from os import path
from setuptools import setup, find_packages


VERSION = "0.2.8"

README_FILE = path.join(path.dirname(__file__), 'README.pypi')
LONG_DESCRIPTION = open(README_FILE).read()


ENTRY_POINTS = {
    # Entry points that marks this package as an orange add-on. If set, addon will
    # be shown in the add-ons manager even if not published on PyPi.
    'orange3.addon': (
        'geo = orangecontrib.geo',
    ),
    # Entry point used to specify packages containing widgets.
    'orange.widgets': (
        # Syntax: category name = path.to.package.containing.widgets
        # Widget category specification can be seen in
        #    orangecontrib/example/widgets/__init__.py
        'Geo = orangecontrib.geo.widgets',
    ),
    # Register widget help
    "orange.canvas.help": (
        'html-index = orangecontrib.geo.widgets:WIDGET_HELP_PATH',)
}


def _discover_tests():
    import unittest
    return unittest.defaultTestLoader.discover('orangecontrib.geo',
                                               pattern='test_*.py',
                                               top_level_dir='.')


if __name__ == '__main__':
    setup(
        name='Orange3-Geo',
        version=VERSION,
        description="Orange add-on for dealing with geography and geo-location.",
        long_description=LONG_DESCRIPTION,
        long_description_content_type='text/markdown',
        license='GPL-3.0',
        packages=find_packages(),
        include_package_data=True,
        install_requires=[
            'Orange3>=3.25.0',
            'scikit-learn',
            'pandas',
            'scipy>=0.17',
            'shapely',
            'simplejson',
            'Pillow'
        ],
        extras_require = {
            'test': ['coverage']
        },
        entry_points=ENTRY_POINTS,
        keywords=(
            'orange3 add-on',
            'geographic',
            'visualization',
            'choropleth',
            'map',
            'cartography',
            'location',
            'position',
            'geolocation',
            'geoposition',
            'latitude',
            'longitude',
        ),
        namespace_packages=["orangecontrib"],
        test_suite="setup._discover_tests",
        zip_safe=False,
        author='Biolab, UL FRI',
        author_email='info@biolab.si',
        url="https://github.com/biolab/orange3-geo",
        classifiers=[
            'Development Status :: 4 - Beta',
            'Environment :: X11 Applications :: Qt',
            'Environment :: Plugins',
            'Programming Language :: Python',
            'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
            'Operating System :: OS Independent',
            'Topic :: Scientific/Engineering :: Visualization',
            'Topic :: Software Development :: Libraries :: Python Modules',
            'Intended Audience :: Education',
            'Intended Audience :: Science/Research',
            'Intended Audience :: Developers',
        ],
    )
