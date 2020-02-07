import unittest
from unittest.mock import Mock, patch

import numpy as np
import pyqtgraph as pg

from AnyQt.QtCore import Qt, QObject, QRectF, QRect

from Orange.widgets.tests.base import WidgetTest
from Orange.widgets.utils.plot import ZOOMING
from orangecontrib.geo.widgets.plotutils import deg2norm, norm2tile, \
    tile2norm, MapViewBox, TILE_PROVIDERS, DEFAULT_TILE_PROVIDER, MapMixin


class TestMapping(unittest.TestCase):
    def test_deg_mapping(self):
        lon = np.array([-200, -180, 0, 180, 200])
        lat = np.array([-90, -85.0511, 0, 85.0511, 90])

        x, y = deg2norm(lon, lat)
        np.testing.assert_almost_equal(np.array([0, 0, 0.5, 1, 1]), x,
                                       decimal=3)
        np.testing.assert_almost_equal(np.array([1, 1, 0.5, 0, 0]), y,
                                       decimal=3)

    def test_tile_mapping(self):
        x = np.array([0, 0.25, 0.5, 0.75, 1])
        y = np.array([0, 0.25, 0.5, 0.75, 1])
        x_test, y_test = tile2norm(*norm2tile(x, y, 4), 4)
        np.testing.assert_almost_equal(x, x_test)
        np.testing.assert_almost_equal(y, y_test)


class TestMapViewBox(WidgetTest):
    def setUp(self):
        self.mock_graph = Mock()
        self.sr = Mock()
        mock_size = Mock()
        mock_size.return_value.width.return_value = 1000
        mock_size.return_value.height.return_value = 1000

        self.mvb = MapViewBox(self.mock_graph)
        self.mvb.set_tile_provider(TILE_PROVIDERS[DEFAULT_TILE_PROVIDER])
        self.mvb.setRange = self.sr
        self.mvb.size = mock_size

    def test_match_zoom(self):
        point1 = pg.Point(0.5, 0.5)
        self.mvb.match_zoom(point1)
        qrect1 = self.sr.call_args[0][0]

        point2 = pg.Point(0.75, 0.75)
        self.mvb.match_zoom(point2, offset=True)
        qrect2 = self.sr.call_args[0][0]
        # when center is offset the new rect should also be offset
        self.assertTrue(qrect1.x() < qrect2.x())
        self.assertAlmostEqual(qrect1.width(), qrect2.width())

    def test_wheel_event(self):
        mock_event = Mock()
        mock_event.delta.return_value = 1
        mock_event.pos.return_value = pg.Point(0.5, 0.5)

        self.assertEqual(self.mvb.get_zoom(), 2)
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 3)
        qrect1 = self.sr.call_args[0][0]
        mock_event.accept.assert_called()
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 4)
        qrect2 = self.sr.call_args[0][0]
        # after zooming in the shown rectangle should be smaller
        self.assertTrue(qrect1.width() > qrect2.width())

        mock_event.delta.return_value = -1
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 3)
        qrect3 = self.sr.call_args[0][0]
        # after zooming out the shown rectangle should be larger
        self.assertTrue(qrect3.width() > qrect2.width())

        self.mvb.wheelEvent(mock_event)
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 2)

    def test_mouse_drag_event(self):
        self.mock_graph.state = ZOOMING
        mock_event = Mock()
        mock_event.button.return_value = Qt.LeftButton
        mock_event.pos.return_value = pg.Point(0.6, 0.6)
        mock_event.isFinish.return_value = True
        mock_event.buttonDownPos.return_value = pg.Point(0.4, 0.4)
        self.mvb.mapToView = lambda x: x
        self.mvb.state['mouseMode'] = pg.ViewBox.RectMode

        self.mvb.match_zoom(pg.Point(0.5, 0.5))
        qrect1 = self.sr.call_args[0][0]
        zoom1 = self.mvb.get_zoom()
        self.mvb.mouseDragEvent(mock_event)
        mock_event.accept.assert_called()
        zoom2 = self.mvb.get_zoom()
        qrect2 = self.sr.call_args[0][0]
        # when selecting a smaller region zoom level should increase and
        # shown area should decrees
        self.assertTrue(zoom2 > zoom1)
        self.assertTrue(qrect2.width() < qrect1.width())

        mock_event.button.return_value = Qt.RightButton
        self.mvb.mouseDragEvent(mock_event)
        mock_event.ignore.assert_called()

    def test_recalculate_zoom(self):
        self.mvb.recalculate_zoom(0.5, 0.5)
        zoom1 = self.mvb.get_zoom()
        self.mvb.recalculate_zoom(0.1, 0.1)
        zoom2 = self.mvb.get_zoom()
        # zoom level should be larger for smaller portions
        self.assertTrue(zoom1 < zoom2)


class MockPlotBase(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.view_box = Mock()
        self.plot_widget = Mock()
        self.master = Mock()


class MapPlot(MapMixin, MockPlotBase):
    def __init__(self):
        MockPlotBase.__init__(self)
        with patch("orangecontrib.geo.widgets.plotutils.AttributionItem.setParentItem"):
            with patch("orangecontrib.geo.widgets.plotutils.AttributionItem.anchor"):
                MapMixin.__init__(self)


class TestMapMixin(WidgetTest):
    def setUp(self):
        self.map_plot = MapPlot()

    def test_tile_provider(self):
        mock_update = Mock()
        self.map_plot.update_map = mock_update
        self.map_plot.view_box.set_tile_provider.reset_mock()
        tp = TILE_PROVIDERS["Topographic"]

        self.map_plot._update_tile_provider(tp)
        self.assertEqual(self.map_plot.tile_provider, tp)
        self.map_plot.view_box.set_tile_provider.assert_called_once_with(tp)
        self.assertEqual("map data: © OpenStreetMap contributors, SRTM | map style: © OpenTopoMap (CC-BY-SA)",
                         self.map_plot.tile_attribution.item.toPlainText())
        mock_update.assert_called_once()

    def test_update_map(self):
        mock_loader = Mock()
        self.map_plot.loader = mock_loader
        self.map_plot.view_box.get_zoom.return_value = 3
        self.map_plot.view_box.viewRange.return_value = [0.1, 0.2], [0.3, 0.4]

        self.map_plot.update_map()
        self.assertEqual(self.map_plot.tz, 3)
        self.assertEqual(self.map_plot.ts, QRect(0, 4, 2, 2))
        self.assertEqual(self.map_plot.ts_norm, QRectF(0.0, 0.5, 0.25, -0.25))
        self.assertEqual(mock_loader.get.call_count, 4)
        self.assertEqual(len(self.map_plot.futures), 4)
