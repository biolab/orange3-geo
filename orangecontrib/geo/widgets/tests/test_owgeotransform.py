import unittest
from itertools import chain

import numpy as np

from Orange.data import Table, Domain, ContinuousVariable, DiscreteVariable
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

        # test not enough numeric variables
        titanic = Table("titanic")
        titanic = titanic[:10]
        self.send_signal(self.widget.Inputs.data, titanic)
        self.assertTrue(self.widget.Error.no_lat_lon_vars.is_shown())

        self.send_signal(self.widget.Inputs.data, self.india_data)
        self.assertFalse(self.widget.Error.no_lat_lon_vars.is_shown())

        short_iris = iris[:10].transform(
            Domain([iris.domain[0], iris.domain.class_var]))
        self.send_signal(self.widget.Inputs.data, short_iris)
        self.assertTrue(self.widget.Error.no_lat_lon_vars.is_shown())

    def test_data_on_output(self):
        self.send_signal(self.widget.Inputs.data, self.india_data)
        self.widget.replace_original = False
        self.widget.apply()
        output = self.get_output(self.widget.Outputs.data)
        self.assertGreater(len(output.domain.variables),
                           len(self.india_data.domain.variables))

        # change settings and commit, assure output didn't change
        combo = self.widget.controls.from_idx
        combo.activated.emit(combo.model().indexOf("WGS 84"))
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

    def test_coord_position(self):
        def names(data):
            domain = data.domain
            return [var.name for var in chain(domain.variables, domain.metas)]

        widget = self.widget
        widget.from_idx = "Slovenia 1996 / Slovene National Grid"
        widget.to_idx = "WGS 84"

        A = np.arange(6).reshape(3, 2)
        B = np.arange(12).reshape(3, 4)
        B[:, 2:] = [[384788.0, 128475.0],
                    [388624.0, 43500.0],
                    [388668.0, 43394.0]]
        conv = np.array([[46.28622568426956, 13.504804692172053],
                         [45.522518503917375, 13.574276877425241],
                         [45.52157199667168, 13.574864024802482]])

        vara = [DiscreteVariable("a1", values=tuple(str(i) for i in range(6))),
                ContinuousVariable("a2")]
        varb = [ContinuousVariable(n) for n in ("b1", "b2", "lat", "lon")]

        # Coordinates in metas
        data = Table.from_numpy(Domain(vara, None, varb), A, None, B)

        # ... replaced
        widget.replace_original = True
        self.send_signal(widget.Inputs.data, data)
        out = self.get_output(widget.Outputs.data)
        self.assertEqual(names(data), names(out))
        np.testing.assert_equal(A, out.X)
        np.testing.assert_equal(B[:, :2], out.metas[:, :2])
        np.testing.assert_almost_equal(conv, out.metas[:, 2:])

        # ... appended
        widget.controls.replace_original.click()
        self.send_signal(widget.Inputs.data, data)
        out = self.get_output(widget.Outputs.data)
        self.assertEqual(names(data) + ['lat (1)', 'lon (1)'], names(out))
        np.testing.assert_equal(A, out.X)
        np.testing.assert_equal(B, out.metas[:, :4])
        np.testing.assert_almost_equal(conv, out.metas[:, 4:])


        # Coordinates in attributes
        data = Table.from_numpy(Domain(varb, None, vara), B, None, A)

        # ... replaced
        widget.replace_original = True
        self.send_signal(widget.Inputs.data, data)
        out = self.get_output(widget.Outputs.data)
        self.assertEqual(names(data), names(out))
        np.testing.assert_equal(B[:, :2], out.X[:, :2])
        np.testing.assert_almost_equal(conv, out.X[:, 2:])
        np.testing.assert_equal(A, out.metas)

        # ... appended
        widget.controls.replace_original.click()
        self.send_signal(widget.Inputs.data, data)
        out = self.get_output(widget.Outputs.data)
        self.assertEqual(
            names(data)[:4] + ['lat (1)', 'lon (1)'] + names(data)[-2:],
            names(out))
        np.testing.assert_equal(B, out.X[:, :4])
        np.testing.assert_almost_equal(conv, out.X[:, 4:])
        np.testing.assert_equal(A, out.metas)


if __name__ == "__main__":
    unittest.main()

