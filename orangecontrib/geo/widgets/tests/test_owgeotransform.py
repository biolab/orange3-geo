import unittest

from Orange.data import Table
from Orange.widgets.tests.base import WidgetTest
from orangecontrib.geo.widgets.owgeotransform import OWGeoTransform


class TestOWGeoTransform(WidgetTest):
    def setUp(self):
        self.widget = self.create_widget(OWGeoTransform)
        self.india_data = Table("India_census_district_population")
        self.india_data = self.india_data[:10]

    def tearDown(self):
        self.widget.onDeleteWidget()
        super().tearDown()

    def test_input(self):
        self.send_signal(self.widget.Inputs.data, self.india_data)

        # check Lat and Lon are recognized
        self.assertEqual(self.widget.attr_lat.name, "Latitude")
        self.assertEqual(self.widget.attr_lon.name, "Longitude")

        # test continuous data (not Lat/Lon)
        iris = Table("iris")
        iris = iris[:10]
        self.send_signal(self.widget.Inputs.data, iris)

        self.assertEqual(self.widget.attr_lat.name, "sepal length")
        self.assertEqual(self.widget.attr_lon.name, "sepal length")

        # test discrete data
        titanic = Table("titanic")
        titanic = titanic[:10]
        self.send_signal(self.widget.Inputs.data, titanic)
        self.assertTrue(self.widget.Error.no_lat_lon_vars.is_shown())

        self.send_signal(self.widget.Inputs.data, self.india_data)
        self.assertFalse(self.widget.Error.no_lat_lon_vars.is_shown())

    def test_data_on_output(self):
        self.send_signal(self.widget.Inputs.data, self.india_data)
        self.widget.apply()
        output = self.get_output(self.widget.Outputs.data)
        self.assertGreater(len(output.domain.variables),
                           len(self.india_data.domain.variables))

        # change settings and commit, assure output didn't change
        # idx 186 is WGS 84
        self.widget.controls.from_idx.activated.emit(186)
        output2 = self.get_output(self.widget.Outputs.data)
        self.assertEqual(output, output2)

        self.widget.apply()
        output2 = self.get_output(self.widget.Outputs.data)
        self.assertNotEqual(output, output2)

        # Disconnect the data
        self.send_signal(self.widget.Inputs.data, None)
        # removing data should have cleared the output
        self.assertIsNone(self.get_output(self.widget.Outputs.data))

        # pressing Commit button still emits empty signal
        self.widget.apply()
        self.assertIsNone(self.get_output(self.widget.Outputs.data))


if __name__ == "__main__":
    unittest.main()

