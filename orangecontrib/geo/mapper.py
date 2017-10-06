import time
from threading import Thread
from functools import lru_cache, wraps

from operator import itemgetter
from os import path
from glob import glob
import logging

import simplejson as json
import numpy as np
import pandas as pd
from sklearn.neighbors import KDTree

import shapely.speedups
from shapely.geometry import Point, shape as Shape, Polygon

from orangecontrib.geo.cc_cities import \
    CC_NAME_TO_CC_NAME, REGION_NAME_TO_REGION_NAME, US_STATE_TO_US_STATE,\
    EUROPE_CITIES, US_CITIES, WORLD_CITIES,\
    EUROPE_CITIES_LIST, US_CITIES_LIST, WORLD_CITIES_LIST



log = logging.getLogger(__name__)


def is_shapely_speedups_available():
    if not shapely.speedups.available:
        return False
    # Otherwise try shapely with speedups in a subprocess to see if shit
    # is crash due to ABI-incompatible libgeos found in path on Loonix
    import sys, subprocess
    proc = subprocess.Popen(
        sys.executable + ' -c ' + '''"import json
from shapely.geometry import shape
import shapely.speedups
shapely.speedups.enable()
shape(json.load(open('%s'))['features'][0]['geometry'])
"''' % path.join(GEOJSON_DIR, 'admin0.json'),
        # Didn't return correct exit status without shell=True
        shell=True)
    proc.wait()
    return proc.returncode == 0


GEOJSON_DIR = path.join(path.dirname(__file__), 'geojson')

ADMIN2_COUNTRIES = {path.basename(filename).split('.')[0].split('-')[1]
                    for filename in glob(path.join(GEOJSON_DIR, 'admin2-*.json'))}
NUL = {}  # nonmapped (invalid) output region


if is_shapely_speedups_available():
    shapely.speedups.enable()
    log.debug('Shapely speed-ups available')


def wait_until_loaded(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global is_done_loading
        while not is_done_loading:
            time.sleep(.1)
        return func(*args, **kwargs)
    return wrapper


is_done_loading = False


def init():
    def _admin_cc(filename):
        parts = path.basename(filename).split('.', 1)[0].split('-')
        admin, cc = parts if len(parts) == 2 else (parts[0], None)
        admin = int(admin[-1])
        return admin, cc

    nearest_points = {0: [], 1: [], 2: []}
    shapes = {0: [], 1: [], 2: []}
    cc_shapes = {}
    id_regions = {}
    us_states = {}

    files = glob(path.join(GEOJSON_DIR, 'admin*.json'))
    if not files:
        raise RuntimeError('Missing GeoJSON files. '
                           'In development environments, merge in the "json" '
                           'branch. See CONTRIBUTING.md')

    log.debug('Loading GeoJSON data ...')
    for filename in files:
        admin, cc = _admin_cc(filename)

        with open(filename, encoding='utf-8') as f:
            collection = json.load(f, encoding='utf-8')

        for feature in collection['features']:
            p = feature['properties']
            shape = Shape(feature['geometry'])
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

            # Get representative points for the k-d tree
            points = []
            polygons = (shape,) if isinstance(shape, Polygon) else shape
            for poly in polygons:
                points.append([poly.centroid.y, poly.centroid.x])
                if poly.area > 10:
                    points.extend(xy[::-1]
                                  for xy in poly.simplify(1).exterior.coords)

            nearest_points[admin].extend(points)
            tups = [tup] * len(points)
            shapes[admin].extend(tups)
            id_regions[p['_id']] = tup

            if admin == 0:
                cc_shapes[p['adm0_a3']] = tup

            # Make Admin1 shapes available in Admin2 too. Except for USA
            # which is the country we have explicit Admin2 shapes for
            if admin == 1 and cc not in ADMIN2_COUNTRIES:
                shapes[2].extend(tups)
                nearest_points[2].extend(points)

            if admin == 1 and cc == 'USA':
                us_states[p['hasc'].split('.')[1]] = tup

    kdtree = {admin: KDTree(centroids)
              for admin, centroids in nearest_points.items()}
    cc_shapes['NUL'] = (None, NUL)  # tuple for Null Island

    assert all(len(nearest_points[admin]) == len(shapes[admin])
               for admin in shapes)

    global is_done_loading, SHAPES, CC_SHAPES, KDTREE, ID_REGIONS, US_STATES
    SHAPES, CC_SHAPES, KDTREE, ID_REGIONS, US_STATES = shapes, cc_shapes, kdtree, id_regions, us_states
    is_done_loading = True
    return

Thread(target=init).start()


class ToLatLon:
    @classmethod
    def _lookup(cls, mapping, key):
        return {p[key]: p
                for _, p in mapping.values()
                if key in p}

    @classmethod
    def _get(cls, lookup, values, to_replace={}, _NUL={}):
        mapping = values.drop_duplicates()
        mapping.index = mapping.values.copy()
        mapping.replace(to_replace, inplace=True)
        mapping = mapping.apply(lookup.get, args=(_NUL,))
        return values.map(mapping).tolist()

    @classmethod
    @wait_until_loaded
    def from_cc_name(cls, values):
        return cls._get(ToLatLon._lookup(CC_SHAPES, 'name'), values, CC_NAME_TO_CC_NAME)

    @classmethod
    @wait_until_loaded
    def from_cc2(cls, values):
        return cls._get(ToLatLon._lookup(CC_SHAPES, 'iso_a2'), values)

    @classmethod
    @wait_until_loaded
    def from_cc3(cls, values):
        return cls._get(ToLatLon._lookup(CC_SHAPES, 'iso_a3'), values)

    @classmethod
    @wait_until_loaded
    def from_region(cls, values):
        return cls._get(ToLatLon._lookup(ID_REGIONS, 'name'), values, REGION_NAME_TO_REGION_NAME)

    @classmethod
    @wait_until_loaded
    def from_fips(cls, values):
        return cls._get(ToLatLon._lookup(ID_REGIONS, 'fips'), values)

    @classmethod
    @wait_until_loaded
    def from_hasc(cls, values):
        return cls._get(ToLatLon._lookup(ID_REGIONS, 'hasc'), values)

    @classmethod
    @wait_until_loaded
    def from_us_state(cls, values):
        lookup = ToLatLon._lookup(US_STATES, 'name')
        lookup.update({short_name: data
                       for short_name, (_polygon, data) in US_STATES.items()})
        return cls._get(lookup, values, US_STATE_TO_US_STATE)

    @classmethod
    @wait_until_loaded
    def from_city_eu(cls, values):
        assert isinstance(values, pd.Series)
        return cls.from_cc2(values.replace(regex=EUROPE_CITIES))

    @classmethod
    @wait_until_loaded
    def from_city_us(cls, values):
        assert isinstance(values, pd.Series)
        return cls.from_us_state(values.replace(regex=US_CITIES))

    @classmethod
    @wait_until_loaded
    def from_city_world(cls, values):
        assert isinstance(values, pd.Series)
        return cls.from_cc2(values.replace(regex=WORLD_CITIES))

    @classmethod
    @lru_cache(1)
    @wait_until_loaded
    def valid_values(cls, method):
        """ Return a sorted list of valid values for method of ToLatLon """
        assert method.__name__.startswith('from_')
        lookup_args = {
            ToLatLon.from_region: (ID_REGIONS, 'name'),
            ToLatLon.from_cc2: (CC_SHAPES, 'iso_a2'),
            ToLatLon.from_cc3: (CC_SHAPES, 'iso_a3'),
            ToLatLon.from_cc_name: (CC_SHAPES, 'name'),
            ToLatLon.from_fips: (ID_REGIONS, 'fips'),
            ToLatLon.from_hasc: (ID_REGIONS, 'hasc'),
            ToLatLon.from_us_state: (US_STATES, 'name'),
            ToLatLon.from_us_state: (US_STATES, 'name'),
            ToLatLon.from_city_eu: (EUROPE_CITIES_LIST,),
            ToLatLon.from_city_us: (US_CITIES_LIST,),
            ToLatLon.from_city_world: (WORLD_CITIES_LIST,),
        }[method]
        if len(lookup_args) == 1:
            return lookup_args[0]
        return sorted(filter(None, ToLatLon._lookup(*lookup_args).keys()))

    @classmethod
    def detect_input(cls, values, sample_size=200):
        """
        Return first "from_" method that in more than 50% matches values,
        or None.
        """
        assert isinstance(values, pd.Series)
        values = values.drop_duplicates().dropna()
        if len(values) > sample_size:
            values = values.sample(sample_size)
        strlen = values.str.len().dropna().unique()
        for method, *cond in ((cls.from_cc2, len(strlen) == 1 and strlen[0] == 2),
                              (cls.from_cc3, len(strlen) == 1 and strlen[0] == 3),
                              (cls.from_cc_name,),
                              (cls.from_us_state,),
                              (cls.from_city_eu,),
                              (cls.from_city_us,),
                              (cls.from_city_world,),
                              (cls.from_region,),
                              (cls.from_fips,),
                              (cls.from_hasc, np.in1d(strlen, [2, 5, 8]).all())):
            if cond and not cond[0]:
                continue
            if sum(map(bool, method(values))) >= len(values) / 2:
                return method
        return None


@wait_until_loaded
def latlon2region(latlon, admin=0):
    """Return list of property dicts for regions mapped by latlon coordinates"""
    assert len(latlon) == 0 or len(latlon[0]) == 2
    assert 0 <= admin <= 2
    global SHAPES, CC_SHAPES, KDTREE

    latlon = np.asanyarray(latlon, dtype=float)

    log.debug('Mapping %d coordinate pairs into regions', len(latlon))

    # Replace missing latlon data with invalid coordinates for k-d tree to work
    nan_rows = np.isnan(latlon).any(axis=1)
    if nan_rows.any():
        latlon = np.array(latlon, order='C', copy=True)
        latlon[nan_rows, :] = -500

    @lru_cache(700)
    def resolve_coords(coord):
        """Cached resolution.
        shape.contains(point) test is what takes the most time
        """
        nonlocal inds, shapes
        point = Point(*coord)
        for i in inds:
            shape, props = shapes[i]
            if shape.contains(point):
                return props
        # No shapes contain point. See if distance to nearest neighbor
        # is less than threshold (i.e. point very near but outside shape)
        shape, props = shapes[sorted(inds, key=lambda i: shapes[i][0].distance(point))[0]]
        return props if shape.distance(point) < .2 else NUL

    out = []
    shapes = SHAPES[admin or 1]
    for isnan, coord, inds in zip(nan_rows,
                                  np.roll(latlon, -1, axis=1),
                                  KDTREE[admin or 1].query(latlon, k=30,
                                                           return_distance=False,
                                                           sort_results=True)):
        out.append(NUL if isnan else resolve_coords(tuple(coord)))

    if admin == 0:
        out = [i and CC_SHAPES[i['adm0_a3']][1] for i in out]

    assert len(out) == len(latlon)
    return out


@wait_until_loaded
def get_bounding_rect(region_ids):
    """Return lat-lon bounding rect of the union of regions defined by ids"""
    if not region_ids:
        return None
    coords = itemgetter('longitude', 'latitude')
    centroids = np.array([coords(ID_REGIONS[_id][1])
                          for _id in region_ids])
    mins, maxs = centroids.min(0), centroids.max(0)
    return tuple(mins.tolist() + maxs.tolist())


if __name__ == '__main__':
    from pprint import pprint

    pprint(ToLatLon.from_cc2(pd.Series(['RU', 'SI'])))

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
