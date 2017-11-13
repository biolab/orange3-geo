#!/usr/bin/env python

from os import path
from setuptools import setup, find_packages


VERSION = "0.2.1"

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


def assert_release_contains_geojson():
    import sys
    from glob import glob

    if any('dist' in arg for arg in sys.argv):
        files = glob(path.join(path.dirname(__file__),
                               'orangecontrib', 'geo', 'geojson', 'admin*.json'))
        if not files:
            raise RuntimeError('GeoJSON files missing in geojson folder. If '
                               'this is a release, merge in the "json" branch. '
                               'See CONTRIBUTING.md for info.')


def _discover_tests():
    import unittest
    return unittest.defaultTestLoader.discover('orangecontrib.geo',
                                               pattern='test_*.py',
                                               top_level_dir='.')


if __name__ == '__main__':

    assert_release_contains_geojson()

    setup(
        name='Orange3-Geo',
        version=VERSION,
        description="Orange add-on for dealing with geography and geo-location.",
        long_description=open(path.join(path.dirname(__file__), 'README.md')).read(),
        license='GPL-3.0',
        packages=find_packages(),
        package_data={
            'orangecontrib.geo.widgets': ['icons/*',
                                          '_leaflet/*'],
        },
        include_package_data=True,
        install_requires=[
            'Orange3',
            'scikit-learn',
            'pandas',
            'scipy>=0.17',
            'shapely',
            'simplejson',
        ],
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
