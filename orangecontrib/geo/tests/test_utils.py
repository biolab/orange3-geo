from unittest import TestCase

import numpy as np

from orangecontrib.geo.mapper import latlon2region, get_bounding_rect


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
