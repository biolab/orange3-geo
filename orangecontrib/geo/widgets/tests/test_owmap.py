from unittest.mock import Mock

from AnyQt.QtCore import Qt

import numpy as np
from pyqtgraph import Point

from Orange.data import Table,  Domain, ContinuousVariable
from Orange.widgets.widget import OWWidget
from Orange.widgets.settings import SettingProvider
from Orange.widgets.utils.colorpalette import ColorPaletteGenerator, \
    ContinuousPaletteGenerator
from Orange.widgets.tests.base import (
    WidgetTest, WidgetOutputsTestMixin, ProjectionWidgetTestMixin
)
from orangecontrib.geo.widgets.owmap import OWMap, OWScatterPlotMapGraph


class TestOWMap(WidgetTest, ProjectionWidgetTestMixin, WidgetOutputsTestMixin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        WidgetOutputsTestMixin.init(cls)
        cls.same_input_output_domain = False
        cls.signal_name = "Data"
        cls.signal_data = cls.data

    def setUp(self):
        super().setUp()
        self.widget = self.create_widget(OWMap)

    def test_set_data(self):
        india_data = Table("India_census_district_population")
        self.send_signal(self.widget.Inputs.data, india_data)

        self.assertEqual(self.widget.attr_lat, india_data.domain[1])
        self.assertEqual(self.widget.attr_lon, india_data.domain[2])

        self.send_signal(self.widget.Inputs.data, None)

        self.assertIsNone(self.widget.attr_lat)
        self.assertIsNone(self.widget.attr_lon)

    def test_out_of_range(self):
        domain = Domain([ContinuousVariable("Lat"),
                         ContinuousVariable("Lon")])
        table = Table(domain,
                      np.array([[0., 0.], [80., 200.], [180., 100.]]))
        self.send_signal(self.widget.Inputs.data, table)

        self.assertTrue(self.widget.Warning.out_of_range.is_shown())
        self.assertEqual(np.sum(self.widget.valid_data), 1)

    def test_send_report(self):
        self.send_signal(self.widget.Inputs.data, self.data)
        self.widget.send_report()
        self.send_signal(self.widget.Inputs.data, None)
        self.widget.send_report()


class MockWidget(OWWidget):
    name = "Mock"
    get_coordinates_data = Mock(return_value=(None, None))
    get_size_data = Mock(return_value=None)
    get_shape_data = Mock(return_value=None)
    get_color_data = Mock(return_value=None)
    get_label_data = Mock(return_value=None)
    get_color_labels = Mock(return_value=None)
    get_shape_labels = Mock(return_value=None)
    get_subset_mask = Mock(return_value=None)
    get_tooltip = Mock(return_value="")

    is_continuous_color = Mock(return_value=False)
    can_draw_density = Mock(return_value=True)
    combined_legend = Mock(return_value=False)
    selection_changed = Mock(return_value=None)
    freeze = Mock(return_value=False)

    GRAPH_CLASS = OWScatterPlotMapGraph
    graph = SettingProvider(OWScatterPlotMapGraph)

    def get_palette(self):
        if self.is_continuous_color():
            return ContinuousPaletteGenerator(Qt.white, Qt.black, False)
        else:
            return ColorPaletteGenerator(12)


class TestOWScatterPlotMapGraph(WidgetTest):
    def setUp(self):
        self.xy = np.array([0.5, 0.6, 0.7]), np.array([0.6, 0.7, 0.8])
        self.master = MockWidget()
        self.master.get_coordinates_data = lambda: self.xy

        self.view_box = Mock()
        self.view_box.viewRange.return_value = [0.1, 0.2], [0.3, 0.4]

        self.graph = OWScatterPlotMapGraph(self.master, None)
        self.graph.view_box = self.view_box

    def test_no_data(self):
        self.xy = None, None
        self.graph.reset_graph()
        self.view_box.recalculate_zoom.assert_called_once_with(1, 1)
        self.view_box.match_zoom.assert_called_once_with(Point(0.5, 0.5))

    def test_update_view_range(self):
        self.graph.reset_graph()
        self.view_box.recalculate_zoom.reset_mock()
        self.view_box.match_zoom.reset_mock()

        self.graph.update_view_range()
        self.view_box.recalculate_zoom.assert_called_once_with(0.7 - 0.5,
                                                               0.8 - 0.6)
        self.view_box.match_zoom.assert_called_once_with(Point(0.6, 0.7))

        self.view_box.recalculate_zoom.reset_mock()
        self.view_box.match_zoom.reset_mock()
        self.graph.update_view_range(match_data=False)
        self.assertFalse(self.view_box.recalculate_zoom.called)
        self.view_box.match_zoom.assert_called_once_with(Point(0.15, 0.35))

    def test_freeze(self):
        self.graph.clear_map = Mock()
        self.graph.update_view_range = Mock()

        self.graph.reset_graph()
        self.graph.clear_map.assert_called_once()
        self.graph.update_view_range.assert_called_once()

        self.graph.clear_map.reset_mock()
        self.graph.update_view_range.reset_mock()
        self.graph.freeze = True
        self.xy = None, None
        self.graph.reset_graph()
        self.graph.clear_map.assert_not_called()
        self.graph.update_view_range.assert_not_called()
