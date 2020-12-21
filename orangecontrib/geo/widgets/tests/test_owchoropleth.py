from unittest.mock import patch
import numpy as np

from AnyQt.QtCore import QRectF, QPointF

from Orange.data import Table
from Orange.widgets.tests.base import WidgetTest, WidgetOutputsTestMixin
from Orange.widgets.visualize.owscatterplotgraph import SymbolItemSample
from orangecontrib.geo.widgets.owchoropleth import OWChoropleth, \
    BinningPaletteItemSample


class TestOWChoropleth(WidgetTest, WidgetOutputsTestMixin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        WidgetOutputsTestMixin.init(cls)
        cls.same_input_output_domain = False
        cls.signal_name = "Data"

    @patch("orangecontrib.geo.widgets.plotutils.ImageLoader")
    def setUp(self, _):
        self.widget = self.create_widget(OWChoropleth)
        self.signal_data = self.data = Table("India_census_district_population")

    def test_set_data(self):
        self.send_signal(self.widget.Inputs.data, self.data)

        self.assertEqual(self.widget.attr_lat, self.data.domain[1])
        self.assertEqual(self.widget.attr_lon, self.data.domain[2])

        self.send_signal(self.widget.Inputs.data, None)

        self.assertIsNone(self.widget.attr_lat)
        self.assertIsNone(self.widget.attr_lon)

    def test_admin_level(self):
        self.send_signal(self.widget.Inputs.data, self.data)
        self.widget.admin_level = 0
        self.assertEqual(len(self.widget.region_ids), 2)

        self.widget.admin_level = 1
        self.widget.setup_plot()
        self.assertEqual(len(self.widget.region_ids), 26)

    def test_discrete(self):
        """Test if legend changes on discrete mode"""
        self.send_signal(self.widget.Inputs.data, self.data)
        self.widget.admin_level = 1
        self.assertIsInstance(self.widget.graph.color_legend.items[0][0],
                              BinningPaletteItemSample)
        self.assertFalse(self.widget.is_mode())

        self.widget.agg_func = "Mode"
        self.widget.agg_attr = self.data.domain["State"]
        self.widget.setup_plot()
        self.assertIsInstance(self.widget.graph.color_legend.items[0][0],
                              SymbolItemSample)
        self.assertTrue(self.widget.is_mode())

    def _select_data(self):
        rect = QRectF(QPointF(0, 0), QPointF(1, 1))
        self.widget.graph.select_by_rectangle(rect)
        return np.arange(len(self.data))

    def _compare_selected_annotated_domains(self, selected, annotated):
        selected_vars = selected.domain.attributes + selected.domain.metas
        annotated_vars = annotated.domain.attributes + annotated.domain.metas
        self.assertLessEqual(set(selected_vars), set(annotated_vars))

    def test_saved_selection(self, timeout=5000):
        self.widget.admin_level = 1
        self.send_signal(self.widget.Inputs.data, self.data)
        self.assertTrue(
            self.signal_manager.wait_for_finished(self.widget, timeout),
            f"Did not finish in the specified {timeout}ms timeout"
        )

        ind = list(range(0, self.widget.graph.n_ids, 2))
        self.widget.graph.select_by_indices(ind)
        settings = self.widget.settingsHandler.pack_data(self.widget)
        w = self.create_widget(self.widget.__class__, stored_settings=settings)

        self.send_signal(self.widget.Inputs.data, self.data, widget=w)
        self.assertTrue(
            self.signal_manager.wait_for_finished(w, timeout),
            f"Did not finish in the specified {timeout}ms timeout"
        )

        self.assertEqual(np.sum(w.graph.selection), len(ind))
        np.testing.assert_equal(self.widget.graph.selection, w.graph.selection)

    def test_send_report(self):
        self.send_signal(self.widget.Inputs.data, self.data)
        self.widget.send_report()
        self.send_signal(self.widget.Inputs.data, None)
        self.widget.send_report()

    def test_in_out_summary(self, timeout=5000):
        info = self.widget.info
        self.assertEqual(info._StateInfo__input_summary.brief, "")
        self.assertEqual(info._StateInfo__output_summary.brief, "")

        self.send_signal(self.widget.Inputs.data, self.data)
        self.assertTrue(
            self.signal_manager.wait_for_finished(self.widget, timeout),
            f"Did not finish in the specified {timeout}ms timeout"
        )
        ind = self._select_data()
        self.assertEqual(info._StateInfo__input_summary.brief,
                         str(len(self.data)))
        self.assertEqual(info._StateInfo__output_summary.brief, str(len(ind)))

        self.send_signal(self.widget.Inputs.data, None)
        self.assertEqual(info._StateInfo__input_summary.brief, "")
        self.assertEqual(info._StateInfo__output_summary.brief, "")

    def test_none_data(self):
        self.send_signal(self.widget.Inputs.data, self.data[:0])
