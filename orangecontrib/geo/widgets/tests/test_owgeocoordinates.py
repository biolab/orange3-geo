# pylint: disable=protected-access
import unittest
from unittest.mock import Mock

import numpy as np
from AnyQt.QtCore import Qt

from Orange.data import Table, Domain, StringVariable
from Orange.widgets.tests.base import WidgetTest
from orangecontrib.geo.widgets.owgeocoordinates import (
    OWGeoCoordinates, ReplacementModel)
from orangewidget.tests.base import GuiTest
from orangewidget.tests.utils import simulate

class TestReplacementsModel(GuiTest):
    def test_data(self):
        model = ReplacementModel()
        self.assertEqual(model.rowCount(), 0)
        self.assertEqual(model.columnCount(), 2)

        model.set_items(
            [["Foo", ""], ["Bar", ""]],
            [["Baz", ""]])

        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(model.data(model.index(0, 0)), "Foo")
        self.assertEqual(model.data(model.index(1, 0)), "Bar")
        self.assertEqual(model.data(model.index(1, 1)), "")
        self.assertEqual(model.data(model.index(2, 0)), "Baz")
        self.assertEqual(model.data(model.index(2, 1)), "(Baz)")
        self.assertEqual(model.replacements(), {})

        self.assertTrue(model.setData(model.index(1, 1), "Barchik", Qt.EditRole))
        self.assertEqual(model.data(model.index(1, 1)), "Barchik")
        self.assertEqual(model.replacements(),
                         {"Bar": "Barchik"})

        self.assertTrue(model.setData(model.index(2, 1), "Buzz", Qt.EditRole))
        self.assertEqual(model.data(model.index(2, 1)), "Buzz")
        self.assertEqual(model.replacements(),
                         {"Bar": "Barchik", "Baz": "Buzz"})


class TestOWGeocoding(WidgetTest):
    def setUp(self):
        self.widget = self.create_widget(OWGeoCoordinates)

        self.data = Table.from_list(
            Domain(
                [], None,
                [StringVariable("ctry"), StringVariable("cty"), StringVariable("foo")]),
            [["Slovenia", "Ljubljana", "Sheriff"],
             ["Germany", "Hamburg", "Tschentscher"],
             ["France", "Nica", "Estrosi"],
             ["Italy", "Napoli", "Manfredi"],
             ["Spain", "Barcelona", "Collboni"],
             ["Slovenija", "Maribor", ""]
             ]
        )

    def tearDown(self):
        self.widget.onDeleteWidget()
        super().tearDown()

    def test_type_guess_on_new_data(self):
        countries = Table.from_list(
            Domain([], [], [StringVariable("s")]),
            [["Slovenia"], ["Germany"], ["France"], ["Italy"], ["Spain"]]
        )
        cities = Table.from_list(
            Domain([], [], [StringVariable("t")]),
            [["Ljubljana"], ["Berlin"], ["Paris"], ["Rome"], ["Madrid"]]
        )
        gibberish = Table.from_list(
            Domain([], [], [StringVariable("u")]),
            [["asdfas"], ["Adsfas"], ["agehra"]]
        )
        gibberish_t = Table.from_list(
            Domain([], [], [StringVariable("t")]),
            [["asdfas"], ["Adsfas"], ["agehra"]]
        )
        cities_u = Table.from_list(
            Domain([], [], [StringVariable("u")]),
            [["Ljubljana"], ["Berlin"], ["Paris"], ["Rome"], ["Madrid"]]
        )

        combo = self.widget.controls.region_type

        # check if the widget guesses the correct geo region
        self.send_signal(self.widget.Inputs.data, countries)
        self.assertEqual(self.widget.region_type, 0)
        self.assertEqual(combo.currentText(), "Country name")
        m = self.get_output(self.widget.Outputs.coded_data).metas
        self.assertAlmostEqual(m[0][1], 46.150207418500074)
        self.assertAlmostEqual(m[4][2], -3.4893281046335867)

        # check if the widget guesses the correct geo region
        self.send_signal(self.widget.Inputs.data, cities)
        self.assertEqual(self.widget.region_type, 5)
        self.assertEqual(combo.currentText(), "Major city (Europe)")
        m = self.get_output(self.widget.Outputs.coded_data).metas
        self.assertAlmostEqual(m[0][1], 46.150207418500074)
        self.assertAlmostEqual(m[4][2], -3.4893281046335867)

        # cannot guess: keep what you have
        self.send_signal(self.widget.Inputs.data, gibberish)
        self.assertEqual(self.widget.region_type, 5)
        self.assertEqual(combo.currentText(), "Major city (Europe)")

        self.widget.region_type = 0

        # cannot guess, but can use context
        self.send_signal(self.widget.Inputs.data, gibberish_t)
        self.assertEqual(self.widget.region_type, 5)
        self.assertEqual(combo.currentText(), "Major city (Europe)")

        # could guess, but context takes precedence
        self.send_signal(self.widget.Inputs.data, cities_u)
        self.assertEqual(self.widget.region_type, 0)
        self.assertEqual(combo.currentText(), "Country name")

        # New widget: default guess is 0
        w = self.create_widget(OWGeoCoordinates)
        self.send_signal(w.Inputs.data, gibberish)
        self.assertEqual(w.region_type, 0)

    def test_type_guess_on_attr_change(self):
        combo = self.widget.controls.region_attr

        # check if the widget guesses the correct geo region
        self.send_signal(self.widget.Inputs.data, self.data)
        self.assertEqual(self.widget.region_type, 0)

        # change attribute to city names
        simulate.combobox_activate_index(combo, 1)
        self.assertEqual(self.widget.region_type, 5)

        # change attribute to foo, keep region type
        simulate.combobox_activate_index(combo, 2)
        self.assertEqual(self.widget.region_type, 5)

        # change attribute to country names
        simulate.combobox_activate_index(combo, 0)
        self.assertEqual(self.widget.region_type, 0)

    def test_replacement_model_update(self):
        combo = self.widget.controls.region_attr
        model = self.widget.replacementsModel

        self.send_signal(self.widget.Inputs.data, self.data)
        self.assertEqual(self.widget.region_type, 0)

        self.assertEqual(
            [x[0] for x in model.unmatched],
            ["Slovenija"])
        self.assertEqual(
            [x[0] for x in model.matched],
            ["France", "Germany", "Italy", "Slovenia", "Spain"])

        simulate.combobox_activate_index(combo, 1)
        self.assertEqual(
            [x[0] for x in model.unmatched],
            ["Maribor", "Napoli", "Nica"]
        )
        self.assertEqual(
            [x[0] for x in model.matched],
            ["Barcelona", "Hamburg", "Ljubljana"]
        )

        simulate.combobox_activate_index(combo, 2)
        self.assertEqual(
            [x[0] for x in model.unmatched],
            sorted(self.data.get_column("foo"))
        )
        self.assertEqual(model.matched, [])

        simulate.combobox_activate_index(combo, 1)
        self.assertEqual(
            [x[0] for x in model.unmatched],
            ["Maribor", "Napoli", "Nica"]
        )
        simulate.combobox_activate_index(self.widget.controls.region_type, 2)
        self.assertEqual(
            [x[0] for x in model.unmatched],
            sorted(self.data.get_column("cty"))
        )

    def test_combo_change_triggers_commit(self):
        commit = self.widget.commit.deferred = Mock()
        self.send_signal(self.widget.Inputs.data, self.data)

        # Change attribute to city names
        commit.reset_mock()
        simulate.combobox_activate_index(self.widget.controls.region_attr, 1)
        commit.assert_called_once()

        # Check if commit was triggered
        commit.reset_mock()
        simulate.combobox_activate_index(self.widget.controls.region_type, 1)
        commit.assert_called_once()

    def test_update_delegate(self):
        set_valid = self.widget.delegate.set_valid_names = Mock()

        self.send_signal(self.widget.Inputs.data, self.data)

        self.assertIn("Albania", set_valid.call_args[0][0])
        self.assertNotIn("Tirana", set_valid.call_args[0][0])

        simulate.combobox_activate_index(self.widget.controls.region_attr, 1)
        self.assertNotIn("Albania", set_valid.call_args[0][0])
        self.assertIn("Tirana", set_valid.call_args[0][0])

        simulate.combobox_activate_index(self.widget.controls.region_type, 4)
        self.assertIn("Albuquerque", set_valid.call_args[0][0])
        self.assertNotIn("Albania", set_valid.call_args[0][0])
        self.assertNotIn("Tirana", set_valid.call_args[0][0])

    def test_inappropriate_data(self):
        self.send_signal(self.widget.Inputs.data, self.data)

        self.send_signal(Table("titanic"))
        self.assertIsNone(self.get_output(self.widget.Outputs.coded_data))

    def test_output(self):
        self.send_signal(self.widget.Inputs.data, self.data)

        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_equal(out.metas[:, :3], self.data.metas)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

        simulate.combobox_activate_index(self.widget.controls.region_attr, 1)
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [np.nan, np.nan],
                 [np.nan, np.nan],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

    def test_output_w_replacements(self):
        self.send_signal(self.widget.Inputs.data, self.data)
        simulate.combobox_activate_index(self.widget.controls.region_attr, 1)

        self.widget.replacements_changed("Nica", "Nice")
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [np.nan, np.nan],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

        self.widget.replacements_changed("Napoli", "Rome")
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

        # Switch to another column
        simulate.combobox_activate_index(self.widget.controls.region_attr, 0)

        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

        # Add replacementes for that column
        self.widget.replacements_changed("Slovenija", "Slovenia")
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [46.150207418500074, 14.6159375132848]]
            )
        )

        # Switch back: previous replacements should kick in
        simulate.combobox_activate_index(self.widget.controls.region_attr, 1)
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [np.nan, np.nan]]
            )
        )

        # ... and back again
        simulate.combobox_activate_index(self.widget.controls.region_attr, 0)
        out = self.get_output(self.widget.Outputs.coded_data)
        np.testing.assert_almost_equal(
            out.metas[:, 3:].astype(float),
            np.array(
                [[46.150207418500074, 14.6159375132848],
                 [51.11347035750008, 10.519743037746785],
                 [46.73255361250007, 2.1926591063622185],
                 [42.50054342900006, 12.686960062430446],
                 [39.88185496300002, -3.4893281046335867],
                 [46.150207418500074, 14.6159375132848]]
            )
        )


if __name__ == "__main__":
    unittest.main()
