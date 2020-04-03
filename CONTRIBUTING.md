Contributing guidelines
=======================

Guidelines:

1. Approximately adhere to [Orange's contributing guidelines].

[Orange's contributing guidelines]: https://github.com/biolab/orange3/blob/master/CONTRIBUTING.md


Building GeoJSON files
------------------------------
To re-build JSON files due to upstream region shape changes, wget & unzip
the following into orangecontrib/geo/geojson:

Admin0 (countries)
- <http://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_0_countries.zip>

Admin1 (states, regions, municipalities)
- <http://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_1_states_provinces.zip>

Admin2 (US counties)
- <http://www2.census.gov/geo/tiger/GENZ2015/shp/cb_2015_us_county_500k.zip>
- <http://www2.census.gov/geo/tiger/GENZ2015/shp/cb_2015_us_state_5m.zip>
- <http://www2.census.gov/geo/docs/reference/state.txt>
- contents as counties.txt <https://web.archive.org/web/20160924075116/http://www.statoids.com/yus.html>

You also need to install [mapshaper](https://www.npmjs.com/package/mapshaper),
[isoquery](https://packages.ubuntu.com/bionic/isoquery) and [ogr2ogr](http://manpages.ubuntu.com/manpages/trusty/man1/ogr2ogr.1.html)
(for Ubuntu it comes with the [gdal-bin](https://mothergeo-py.readthedocs.io/en/latest/development/how-to/gdal-ubuntu-pkg.html) package)

Then run the following:

    git checkout master

    cd orangecontrib/geo/geojson
    ./make-geojson.sh

    git add admin*.json
    git commit -m "Add binary GeoJSON files"

Building package
-------------------------------
When building the source distribution package, the following workflow 
works for me:

    git checkout master
    git checkout -b build

    python setup.py sdist
    # ... upload built tgz

    git checkout --force master
    git branch -D build
