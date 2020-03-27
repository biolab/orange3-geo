Contributing guidelines
=======================

Guidelines:

1. Approximately adhere to [Orange's contributing guidelines].

[Orange's contributing guidelines]: https://github.com/biolab/orange3/blob/master/CONTRIBUTING.md


Building missing GeoJSON files
------------------------------

When re-building the JSON files due to upstream region shape changes, the 
following should work:

    git checkout master

    cd orangecontrib/geo/geojson
    ./make-geojson.sh

    git add admin*.json
    git commit -m "Add binary GeoJSON files"
    
When building the source distribution package, the following workflow 
works for me:

    git checkout master
    git checkout -b build

    python setup.py sdist
    # ... upload built tgz

    git checkout --force master
    git branch -D build
