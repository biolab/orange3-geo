import json
from os import path
from glob import glob

import numpy as np
from sklearn.neighbors import KDTree

import shapely.speedups
from shapely.geometry import Point, shape as Shape, Polygon

if shapely.speedups.available:
    shapely.speedups.enable()


GEOJSON_DIR = path.join(path.dirname(__file__), 'geojson')

ADMIN2_COUNTRIES = {path.basename(filename).split('.')[0].split('-')[1]
                    for filename in glob(path.join(GEOJSON_DIR, 'admin2-*.json'))}
NUL = {}  # nonmapped (invalid) output region


def init():
    def _admin_cc(filename):
        parts = path.basename(filename).split('.', 1)[0].split('-')
        admin, cc = parts if len(parts) == 2 else (parts[0], None)
        admin = int(admin[-1])
        return admin, cc

    centroids = {0: [], 1: [], 2: []}
    shapes = {0: [], 1: [], 2: []}
    cc_shapes = {}
    id_regions = {}
    for filename in glob(path.join(GEOJSON_DIR, 'admin*.json')):
        admin, cc = _admin_cc(filename)

        with open(filename) as f:
            collection = json.load(f)

        for feature in collection['features']:
            p = feature['properties']
            shape = Shape(feature['geometry'])
            centroid = (shape.centroid.y, shape.centroid.x)
            tup = (shape, p)

            # Add representative lat-lon pair if non-existent
            if (np.isnan(p.get('latitude', np.nan)) or
                np.isnan(p.get('longitude', np.nan))):
                try:
                    r = shape.representative_point()
                except ValueError:
                    # For GBR, representative point above fails with:
                    #   ValueError: No Shapely geometry can be created from null value
                    r = shape.centroid
                    if not r.within(shape):
                        max_poly = max([shape] if isinstance(shape, Polygon) else list(shape),
                                       key=lambda polygon: polygon.area)
                        # From https://stackoverflow.com/questions/33311616/find-coordinate-of-closest-point-on-polygon-shapely/33324058#33324058
                        poly_ext = max_poly.exterior
                        dist = poly_ext.project(r)
                        pt = poly_ext.interpolate(dist)
                        r = Point(pt.coords[0])
                        assert r.within(shape)
                p.update(latitude=r.y, longitude=r.x)

            id_regions[p['_id']] = tup + (centroid,)
            shapes[admin].append(tup)
            centroids[admin].append(centroid)

            if admin == 0:
                cc_shapes[p['adm0_a3']] = tup

            # Make Admin1 shapes available in Admin2 too. Except for USA
            # which is the country we have explicit Admin2 shapes for
            if admin == 1 and cc not in ADMIN2_COUNTRIES:
                shapes[2].append(tup)
                centroids[2].append(centroid)

    kdtree = {admin: KDTree(centroids)
              for admin, centroids in centroids.items()}
    shapes = {admin: np.array(lst, dtype=object)
              for admin, lst in shapes.items()}
    cc_shapes['NUL'] = (None, NUL)  # tuple for Null Island

    return shapes, cc_shapes, kdtree, id_regions


SHAPES, CC_SHAPES, KDTREE, ID_REGIONS = init()


def latlon2region(latlon, admin=0):
    """Return list of property dicts for regions mapped by latlon coordinates"""
    assert len(latlon) == 0 or len(latlon[0]) == 2
    assert 0 <= admin <= 2
    global SHAPES, CC_SHAPES, KDTREE

    latlon = np.asanyarray(latlon)

    # Replace missing latlon data with invalid coordinates for k-d tree to work
    nan_rows = np.isnan(latlon).any(axis=1)
    if nan_rows.any():
        latlon = np.array(latlon, dtype=float, order='C', copy=True)
        latlon[nan_rows, :] = -500

    out = []
    shapes = SHAPES[admin or 1]
    for isnan, point, inds in zip(nan_rows,
                                  (Point(x, y) for y, x in latlon),
                                  KDTREE[admin or 1].query(latlon, k=30,
                                                           return_distance=False,
                                                           sort_results=True)):
        if isnan:
            out.append(NUL)
            continue
        for i in inds:
            shape, props = shapes[i]
            if shape.contains(point):
                out.append(props)
                break
        else:
            # No shapes contain point. See if distance to nearest neighbor
            # is less than threshold (i.e. point very near but outside shape)
            shape, props = shapes[sorted(inds, key=lambda i: shapes[i][0].distance(point))[0]]
            if shape.distance(point) < .2:
                out.append(props)
            else:
                out.append(NUL)

    if admin == 0:
        out = [i and CC_SHAPES[i['adm0_a3']][1] for i in out]

    assert len(out) == len(latlon)
    return out


def get_bounding_rect(region_ids):
    """Return lat-lon bounding rect of the union of regions defined by ids"""
    if not region_ids:
        return None
    centroids = np.array([ID_REGIONS[_id][2] for _id in region_ids])
    mins, maxs = centroids.min(0), centroids.max(0)
    return tuple(mins.tolist() + maxs.tolist())


if __name__ == '__main__':
    import time
    from pprint import pprint

    coords = [
        (46.0555, 14.5083),
        (40.7127, -74.0059),
        (49.761667, -77.802778),
        (31.814700, 79.886838),
        (52.818925, 92.567674),
        (61.760153, -121.236525),
        (64.295556,-15.227222),
        (0, 0),
    ]

    start = time.clock()
    pprint(latlon2region(coords, 0))
    elpassed = time.clock() - start
    print(elpassed)
    print()

    start = time.clock()
    pprint(latlon2region(coords, 1))
    elpassed = time.clock() - start
    print(elpassed)
    print()

    start = time.clock()
    pprint(latlon2region(coords, 2))
    elpassed = time.clock() - start
    print(elpassed)
