import unittest
from unittest.mock import Mock

import numpy as np

from Orange.data import Table, Domain, ContinuousVariable
from Orange.widgets.tests.base import WidgetTest
from orangecontrib.geo.widgets.owgeolabels import OWGeoLabels, ADMIN_LEVELS
from orangewidget.tests.utils import simulate


class TestOWGeocoding(WidgetTest):
    def setUp(self):
        self.widget = self.create_widget(OWGeoLabels)
        self.data = Table.from_numpy(
            Domain(
                [ContinuousVariable("foo"),
                 ContinuousVariable("LatituDE"),
                 ContinuousVariable("LonGItude")]
            ),
            [[0, 46.05, 14.5],  # Ljubljana, Slovenia
             [1, 34.052235, -118.243683],  # Los Angeles, USA
             [np.nan, 48.856613, 2.3522219],  # Paris, France
             [np.nan, np.nan, 2.3522219]]  # unknown
        )

    def test_levels(self):
        w = self.widget
        combo = w.controls.admin
        w.admin = 0

        self.send_signal(self.data)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(
            out.metas[:, 0].tolist(),
            ["Slovenia", "United States of America", "France", ""]
        )

        simulate.combobox_activate_index(combo, 1)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(
            out.metas[:, 0].tolist(),
            ["Ljubljana", "California", "Paris", ""]
        )

        simulate.combobox_activate_index(combo, 2)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(
            out.metas[:, 0].tolist(),
            ["Ljubljana", "Los Angeles, California", "Paris", ""]
        )

    def test_append_features(self):
        w = self.widget
        check = w.controls.append_features
        w.append_features = False

        self.send_signal(self.data)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(len(out.domain.metas), 1)

        check.click()
        out = self.get_output(w.Outputs.coded_data)
        self.assertGreater(len(out.domain.metas), 1)

    def test_keep_context(self):
        w = self.widget
        lat = w.controls.lat_attr
        lon = w.controls.lon_attr

        # Scramble columns so that they must be chosen manually
        data = Table.from_numpy(
            self.data.domain, self.data.X[:, [1, 2, 0]])
        self.send_signal(self.widget.Inputs.data, data)

        # Sanity check: labels aren't determined
        out = self.get_output(w.Outputs.coded_data)
        self.assertNotEqual(
            out.metas[:, 0].tolist(),
            ["Slovenia", "United States of America", "France", ""]
        )

        # Properly set lan and lon
        simulate.combobox_activate_index(lat, 0)
        simulate.combobox_activate_index(lon, 1)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(
            out.metas[:, 0].tolist(),
            ["Slovenia", "United States of America", "France", ""]
        )

        self.send_signal(Table("iris")[:5])
        # Sanity check: labels aren't determined
        out = self.get_output(w.Outputs.coded_data)
        self.assertNotEqual(
            out.metas[:, 0].tolist(),
            ["Slovenia", "United States of America", "France", ""]
        )

        # Give it back the data: it should retrieve context
        # despite having attrs with names latitude and longitude
        self.send_signal(self.widget.Inputs.data, data)
        out = self.get_output(w.Outputs.coded_data)
        self.assertEqual(
            out.metas[:, 0].tolist(),
            ["Slovenia", "United States of America", "France", ""]
        )

    def test_no_matches(self):
        # Check that the widget does something sensible when data is
        # inappropriate, e.g. no numeric variables or no matches
        # (note: latlon2region returns an empty frame when no matches!)
        w = self.widget
        check = w.controls.append_features

        self.send_signal(Table("iris")[:5])
        out = self.get_output(w.Outputs.coded_data)
        self.assertTrue(np.all(out.metas == ""))

        check.click()
        out = self.get_output(w.Outputs.coded_data)
        self.assertTrue(np.all(out.metas == ""))

        self.send_signal(Table("titanic")[:5])
        out = self.get_output(w.Outputs.coded_data)
        self.assertIsNone(out)

        check.click()
        out = self.get_output(w.Outputs.coded_data)
        self.assertIsNone(out)

    def test_no_valid_columns(self):
        error = self.widget.Error.no_valid_columns

        self.send_signal(Table("titanic"))
        self.assertTrue(error.is_shown())

        self.send_signal(self.data)
        self.assertFalse(error.is_shown())

        self.send_signal(Table("titanic"))
        self.assertTrue(error.is_shown())

        self.send_signal(None)
        self.assertFalse(error.is_shown())

    def test_report(self):
        w = self.widget
        simulate.combobox_activate_index(w.controls.admin, 1)

        self.send_signal(self.widget.Inputs.data, self.data)

        w.report_items = Mock()
        w.send_report()
        self.assertEqual(w.report_items.call_args[0][0],
           (("Latitude", "LatituDE"),
            ("Longitude", "LonGItude"),
            ("Administrative level", ADMIN_LEVELS[1]),
            ("Unmatched coordinates", 1),))
        w.report_items.reset_mock()

        w.set_data(None)
        w.send_report()
        w.report_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
