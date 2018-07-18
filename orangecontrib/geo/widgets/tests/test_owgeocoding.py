# pylint: disable=protected-access
import unittest

from Orange.data import Table
from Orange.widgets.tests.base import WidgetTest
from orangecontrib.geo.widgets.owgeocoding import OWGeocoding


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

    def test_all_continuous(self):
        # switch to Decode when all continuous data
        housing = Table("housing")
        self.send_signal(self.widget.Inputs.data, housing)
        self.assertEqual(self.widget.is_decoding, 1)

if __name__ == "__main__":
    unittest.main()

