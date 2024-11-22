# pylint: disable=protected-access
import unittest

from Orange.data import Table, Domain, DiscreteVariable, StringVariable
from Orange.widgets.tests.base import WidgetTest
from orangecontrib.geo.widgets.owgeocoding import OWGeocoding
from orangecontrib.geo.mapper import ToLatLon, CC_NAME_TO_CC_NAME


class TestOWGeocoding(WidgetTest):
    def setUp(self):
        self.widget = self.create_widget(OWGeocoding)
        self.radio_buttons = self.widget.controls.is_decoding.buttons

    def tearDown(self):
        self.widget.onDeleteWidget()
        super().tearDown()

    def test_non_matching(self):
        india_data = Table("India_census_district_population")
        india_data = india_data[:10]
        self.send_signal(self.widget.Inputs.data, india_data)

        # check the default is Encode
        self.assertEqual(self.widget.is_decoding, 0)
        self.assertFalse(self.widget.mainArea.isHidden())

        # change to Decode and check mainArea is hidden
        self.radio_buttons[1].click()
        self.assertTrue(self.widget.mainArea.isHidden())

        # change back to Encode and show mainArea
        self.radio_buttons[0].click()
        self.assertFalse(self.widget.mainArea.isHidden())

    def test_matching(self):
        hdi_data = Table("HDI-small")
        hdi_data = hdi_data[:7]
        self.send_signal(self.widget.Inputs.data, hdi_data)

        # check the default is Encode
        self.assertEqual(self.widget.is_decoding, 0)
        self.assertTrue(self.widget.mainArea.isHidden())

        # change to Decode, mainArea has to be hidden
        self.radio_buttons[1].click()
        self.assertTrue(self.widget.mainArea.isHidden())

        # change back to Encode, mainArea still has to be hidden
        self.radio_buttons[0].click()
        self.assertTrue(self.widget.mainArea.isHidden())

    def test_data_on_output(self):
        hdi_data = Table("HDI-small")
        self.send_signal(self.widget.Inputs.data, hdi_data)
        outtable = self.get_output(self.widget.Outputs.coded_data)
        self.assertGreater(len(outtable.domain.metas),
                           len(hdi_data.domain.metas))
        # Disconnect the data
        self.send_signal(self.widget.Inputs.data, None)
        # removing data should have cleared the output
        self.assertIsNone(self.get_output(self.widget.Outputs.coded_data))

    def test_cc_name_mapping(self):
        # check if the CC_NAME_TO_CC_NAME maps to known values
        known_countries = set(ToLatLon.valid_values(ToLatLon.from_cc_name))
        mapped_countries = set(CC_NAME_TO_CC_NAME.values())
        self.assertSetEqual(mapped_countries - known_countries, set())

    def test_all_continuous(self):
        # switch to Decode when all continuous data
        housing = Table("housing")
        self.send_signal(self.widget.Inputs.data, housing)
        self.assertEqual(self.widget.is_decoding, 1)

    def test_geo_region_guess(self):
        countries = Table.from_list(
            Domain([], [], [StringVariable("s")]),
            [["Slovenia"], ["Germany"], ["France"], ["Italy"], ["Spain"]]
        )
        cities = Table.from_list(
            Domain([], [], [StringVariable("t")]),
            [["Ljubljana"], ["Berlin"], ["Paris"], ["Rome"], ["Madrid"]]
        )
        jibberish = Table.from_list(
            Domain([], [], [StringVariable("u")]),
            [["asdfas"], ["Adsfas"], ["agehra"]]
        )
        jibberish_t = Table.from_list(
            Domain([], [], [StringVariable("t")]),
            [["asdfas"], ["Adsfas"], ["agehra"]]
        )
        cities_u = Table.from_list(
            Domain([], [], [StringVariable("u")]),
            [["Ljubljana"], ["Berlin"], ["Paris"], ["Rome"], ["Madrid"]]
        )

        # check if the widget guesses the correct geo region
        self.send_signal(self.widget.Inputs.data, countries)
        self.assertEqual(self.widget.str_type, "Country name")
        self.assertEqual(self.widget.str_type_combo.currentText(), "Country name")
        m = self.get_output(self.widget.Outputs.coded_data).metas
        self.assertAlmostEqual(m[0][1], 46.150207418500074)
        self.assertAlmostEqual(m[4][2], -3.4893281046335867)

        # check if the widget guesses the correct geo region
        self.send_signal(self.widget.Inputs.data, cities)
        self.assertEqual(self.widget.str_type, "Major city (Europe)")
        self.assertEqual(self.widget.str_type_combo.currentText(), "Major city (Europe)")
        m = self.get_output(self.widget.Outputs.coded_data).metas
        self.assertAlmostEqual(m[0][1], 46.150207418500074)
        self.assertAlmostEqual(m[4][2], -3.4893281046335867)

        # cannot guess: use default, country name
        self.send_signal(self.widget.Inputs.data, jibberish)
        self.assertEqual(self.widget.str_type, "Country name")
        self.assertEqual(self.widget.str_type_combo.currentText(), "Country name")

        # cannot guess, but can use context
        self.send_signal(self.widget.Inputs.data, jibberish_t)
        self.assertEqual(self.widget.str_type, "Major city (Europe)")
        self.assertEqual(self.widget.str_type_combo.currentText(), "Major city (Europe)")

        # could guess, but context takes precedence
        self.send_signal(self.widget.Inputs.data, cities_u)
        self.assertEqual(self.widget.str_type, "Country name")
        self.assertEqual(self.widget.str_type_combo.currentText(), "Country name")

    def test_minimum_size(self):
        pass


if __name__ == "__main__":
    unittest.main()
