Contributing guidelines
=======================

Guidelines:

1. Approximately adhere to [Orange's contributing guidelines].

[Orange's contributing guidelines]: https://github.com/biolab/orange3/blob/master/CONTRIBUTING.md


Building missing GeoJSON files
------------------------------

Due to its size, GeoJSON files aren't tracked in the same repository branch.
Built JSONs can be found in _json_ branch. You can merge the files into your
current development branch with:

    git checkout topic-branch
    git checkout origin/json orangecontrib/geo/geojson/*.json
    git reset HEAD orangecontrib/geo/geojson/*.json

When re-building the JSON files due to upstream region shape changes, the 
following should work:

    git checkout master
    git branch -D json
    git checkout --orphan json
    git reset HEAD .

    cd orangecontrib/geo/geojson
    ./make-geojson.sh

    git add admin*.json
    git commit -m "Add binary GeoJSON files"

    # force-push to overwrite remote binary json branch
    git push --force
    
When building the source distribution package, the following workflow 
works for me:

    git checkout master
    git checkout -b build
    git checkout origin/json orangecontrib/geo/geojson/*.json
    git reset HEAD .

    python setup.py sdist
    # ... upload built tgz

    git checkout --force master
    git branch -D build
