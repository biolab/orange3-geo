import unittest
from unittest import TestCase

import numpy as np

from orangecontrib.geo.mapper import latlon2region, get_bounding_rect
from orangecontrib.geo.utils import find_lat_lon
from Orange.data import Table, Domain, DiscreteVariable, ContinuousVariable


class TestUtils(TestCase):

    def test_mapper(self):
        latlons = np.array([
            [46.0555, 14.5083],       # Ljubljana
            [40.7127, -74.0059],      # NYC
            [32.775833, -96.796667],  # Dallas
            (49.761667, -77.802778),  # Quebec, Ontario
            (31.814700, 79.886838),   # Tibet
            (52.818925, 92.567674),   # Krasnoyarsk
            [64.295556, -15.227222],  # Austurland, Iceland
            [61.760153, -121.236525], # Canada
            [0, -1],                  # "middle of the ocean"
            [40, np.nan],
        ])
        self.assertEqual(
            [i.get('name') for i in latlon2region(latlons, 2)],
            ['Ljubljana', 'New York, New York', 'Dallas, Texas', 'Québec',
             'Xizang', 'Krasnoyarsk', 'Austurland', 'Northwest Territories',
             None, None])
        self.assertEqual(
            [i.get('_id') for i in latlon2region(latlons, 0)],
             ['SVN', 'USA', 'USA', 'CAN', 'CHN', 'RUS', 'ISL', 'CAN', None, None])
        self.assertEqual(
            [i.get('_id') for i in latlon2region(latlons, 1)],
            ['SVN-962', 'USA-3559', 'USA-3536', 'CAN-683', 'CHN-1662',
             'RUS-2603', 'ISL-695', 'CAN-635', None, None])
        self.assertEqual(
            [i.get('_id') for i in latlon2region(latlons, 2)],
            ['SVN-962', 'USA-NY-36061', 'USA-TX-48113', 'CAN-683', 'CHN-1662',
             'RUS-2603', 'ISL-695', 'CAN-635', None, None])

    def test_get_bounding_rect(self):
        np.testing.assert_equal(np.array(get_bounding_rect({'SWE', 'ITA'}), dtype=int),
                                np.r_[12, 42, 14, 62])

    def test_find_lat_lon(self):
        def attrs_for(*attrs, x=None):
            if x is None:
                data = Table.from_domain(Domain(attrs), 0)
            else:
                data = Table.from_numpy(Domain(attrs), x)
            return find_lat_lon(data)

        d1, d2 = [DiscreteVariable(n, values=tuple(str(i) for i in range(6)))
                  for n in ("d1", "d2")]
        c1, c2, c3, lat, lon = [ContinuousVariable(n)
                                for n in "c1 c2 c3 lat lon".split()]

        # match names
        self.assertEqual(attrs_for(c1, lon, lat, c2), (lat, lon))
        self.assertEqual(attrs_for(d1, lon, lat, d2), (lat, lon))

        # two numeric variables; one is matched by name
        self.assertEqual(attrs_for(d1, lon, c2, d2), (c2, lon))
        self.assertEqual(attrs_for(d1, c2, lon, d2), (c2, lon))
        self.assertEqual(attrs_for(d1, lat, c2, d2), (lat, c2))
        self.assertEqual(attrs_for(d1, c2, lat, d2), (lat, c2))

        # two numeric variables, none matched by name, useful range heuristic
        d = np.array([[0, 12, 8, 1], [0, 45, 120, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c1, c2))

        d = np.array([[0, 12, 8, 1], [0, 120, 45, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c2, c1))


        # two numeric variables, none matched by name, no range heuristic: use them
        d = np.array([[0, 12, 8, 1], [0, 13, 45, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c1, c2))

        d = np.array([[0, 100, 8, 1], [0, 13, 150, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c1, c2))

        self.assertEqual(attrs_for(d1, c1, c2, d2), (c1, c2))

        # two numeric variables, but latitude out of range
        d = np.array([[0, 12, 8, 1], [0, 200, 45, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c1, c1))

        d = np.array([[0, 12, 8, 1], [0, 13, 245, 0]])
        self.assertEqual(attrs_for(d1, c1, c2, d2, x=d), (c1, c1))

        # more than 2
        self.assertEqual(attrs_for(d1, c1, c2, lat), (c1, c1))
        self.assertEqual(attrs_for(d1, lat, c1, c2), (lat, lat))
        self.assertEqual(attrs_for(d1, c1, c2, lon), (c1, c1))
        self.assertEqual(attrs_for(d1, lon, c1, c2), (lon, lon))
        self.assertEqual(attrs_for(d1, c3, c2, c1), (c3, c3))


if __name__ == "__main__":
    unittest.main()
