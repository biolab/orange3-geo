import unittest
from unittest.mock import patch, Mock
import numpy as np

from AnyQt.QtCore import QRectF, QPointF

from Orange.data import Table, Domain, DiscreteVariable, ContinuousVariable
from Orange.misc.cache import memoize_method
from Orange.widgets.tests.base import WidgetTest, WidgetOutputsTestMixin
from Orange.widgets.utils.colorpalettes import DefaultContinuousPalette
from Orange.widgets.visualize.owscatterplotgraph import SymbolItemSample
from orangecontrib.geo.widgets.owchoropleth import OWChoropleth, \
    BinningPaletteItemSample, DEFAULT_AGG_FUNC


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

    def test_default_attrs(self):
        self.assertIsNone(self.widget.agg_attr)

        data = self.data.transform(Domain(self.data.domain.attributes[:-1],
                                          self.data.domain.attributes[-1]))
        self.send_signal(self.widget.Inputs.data, data)
        self.assertIs(self.widget.agg_attr, data.domain.class_var)
        self.assertEqual(self.widget.agg_func, "Mean")

        data = self.data.transform(Domain(self.data.domain.attributes[:-1]))
        self.send_signal(self.widget.Inputs.data, data)
        self.assertIs(self.widget.agg_attr, data.domain.attributes[0])
        self.assertEqual(self.widget.agg_func, "Mode")

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
        self.widget.agg_func = DEFAULT_AGG_FUNC
        self.widget.admin_level = 1
        self.widget.setup_plot()
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

    def test_no_data(self):
        self.send_signal(self.widget.Inputs.data, self.data[:0])

        with self.data.unlocked():
            self.data.X[:] = np.nan

        self.send_signal(self.widget.Inputs.data, self.data)

    def test_get_palette(self):
        self.widget.get_regions = memoize_method(3)(
            lambda *_: (np.arange(26), [{}] * 26, [[]] * 26))
        self.widget.setup_plot = Mock()

        a, b = (
            DiscreteVariable("a", values=("a", "b")),
            DiscreteVariable("b", values=tuple("abcdefghijklm")))
        d = Domain(
            [a, b],
            [],
            [ContinuousVariable("latitude"),
             ContinuousVariable("longitude")])
        # 0 and 3 appear only once, 13 doesn't appear at all
        data = Table.from_numpy(
            d,
            np.array([[0, 1] * 13,
                      [1, 2, 4, 5, 6, 7, 8, 9, 8, 9, 10, 10, 12,
                       0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],]).T,
            None,
            np.arange(45, 97).reshape(2, 26).T
        )
        self.send_signal(self.widget.Inputs.data, data)

        self.widget.agg_attr = data.domain["a"]
        self.widget.agg_func = "Mode"
        np.testing.assert_equal(
            self.widget.get_palette().palette,
            a.palette.palette)
        self.widget.agg_func = "Instance Count"
        self.assertIs(
            self.widget.get_palette(),
            DefaultContinuousPalette)

        self.widget.agg_attr = data.domain["b"]
        self.widget.get_agg_data()
        self.assertIs(
            self.widget.get_palette(),
            DefaultContinuousPalette)
        self.widget.agg_func = "Mode"
        self.widget.graph.update_colors()
        self.widget.get_agg_data()
        palette = self.widget.get_palette().palette
        np.testing.assert_equal(
            palette[:-1],
            b.palette.palette[[1, 2, 4, 5, 6, 7, 8, 9, 10, 12]])
        np.testing.assert_equal(palette[-1], [192, 192, 192])


class TestOWChoroplethPlotGraph(WidgetTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        WidgetOutputsTestMixin.init(cls)
        cls.same_input_output_domain = False
        cls.signal_name = "Data"

    @patch("orangecontrib.geo.widgets.plotutils.ImageLoader")
    def setUp(self, _):
        self.widget = self.create_widget(OWChoropleth)
        self.widget.admin_level = 1
        data = self.data = Table("India_census_district_population")
        self.send_signal(self.widget.Inputs.data, data)
        self.graph = self.widget.graph

    def test_set_get_selection_by_ids(self):
        selection = list(zip(self.widget.region_ids[[1, 3, 4]], [1, 1, 2]))
        self.graph.set_selection_from_ids(selection)
        np.testing.assert_equal(self.graph.selection[:6], [0, 1, 0, 1, 2, 0])
        self.assertEqual(self.graph.selected_ids(), selection)

        selection.append(("foo", 1))
        selection.pop(0)
        self.graph.set_selection_from_ids(selection)
        np.testing.assert_equal(self.graph.selection[:6], [0, 0, 0, 1, 2, 0])
        self.assertEqual(self.graph.selected_ids(), selection[:2])

        self.graph.set_selection_from_ids([])
        self.assertFalse(np.any(self.graph.selection))
        self.assertEqual(self.graph.selected_ids(), [])

        self.graph.set_selection_from_ids(selection)
        np.testing.assert_equal(self.graph.selection[:6], [0, 0, 0, 1, 2, 0])
        self.graph.set_selection_from_ids(None)
        self.assertFalse(np.any(self.graph.selection))
        self.assertEqual(self.graph.selected_ids(), [])


if __name__ == "__main__":
    unittest.main()
