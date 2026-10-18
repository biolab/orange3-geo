import dataclasses
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pyqtgraph as pg

from AnyQt.QtCore import Qt, QObject, QRectF, QRect
from AnyQt.QtTest import QSignalSpy

from Orange.widgets.tests.base import WidgetTest, GuiTest
from Orange.widgets.utils.plot import ZOOMING
from orangecontrib.geo.widgets.plotutils import deg2norm, norm2tile, \
    tile2norm, MapViewBox, _TILE_PROVIDERS, DEFAULT_TILE_PROVIDER, MapMixin, \
    _TileProvider, TileProvidersRegistry, SettingsKey, TileProviderListModel, \
    TILE_PROVIDERS


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
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 3)
        qrect1 = self.sr.call_args[0][0]
        mock_event.accept.assert_called()
        self.mvb.wheelEvent(mock_event)
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 4)
        qrect2 = self.sr.call_args[0][0]
        # after zooming in the shown rectangle should be smaller
        self.assertTrue(qrect1.width() > qrect2.width())

        mock_event.delta.return_value = -1
        self.mvb.wheelEvent(mock_event)
        self.mvb.wheelEvent(mock_event)
        self.assertEqual(self.mvb.get_zoom(), 3)
        qrect3 = self.sr.call_args[0][0]
        # after zooming out the shown rectangle should be larger
        self.assertTrue(qrect3.width() > qrect2.width())

        self.mvb.wheelEvent(mock_event)
        self.mvb.wheelEvent(mock_event)
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


class TestTileProvidersRegistry(GuiTest):
    def setUp(self):
        assert len(_TILE_PROVIDERS) == 6  # Sanity check

        self.store = {}

        class MockSettings:
            @staticmethod
            def value(key, default=None, type=None):
                value = self.store.get(key, default)
                if type:
                    value = type(value)
                return value

            @staticmethod
            def setValue(key, value):
                self.store[key] = value

        self.patch_settings = patch(
            "orangecontrib.geo.widgets.plotutils.QSettings", lambda: MockSettings())
        self.patch_settings.start()
        self.addCleanup(self.patch_settings.stop)

        self.mock_providers = [
            _TileProvider(
                name=f"Mock {i}",
                url=f"https://mock{i}.com/{{z}}/{{x}}/{{y}}.png",
                attribution=f"Mock Attribution {i}",
                size=256,
                max_zoom=5,
            ) for i in range(2)
        ]

    def tearDown(self):
        TileProvidersRegistry.instance = None

    def test_tile_provider_is_a_singleton(self):
        registry1 = TileProvidersRegistry()
        registry2 = TileProvidersRegistry()
        self.assertIs(registry1, registry2)

    def test_tile_provider_init_is_not_called_multiple_times(self):
        with patch.object(QObject, "__init__", return_value=None) as mock_init:
            TileProvidersRegistry()
            TileProvidersRegistry()
            self.assertEqual(mock_init.call_count, 1)

    def test_provider_gets_defaults(self):
        registry = TileProvidersRegistry()
        self.assertEqual(registry.providers, _TILE_PROVIDERS)
        self.assertIsNot(registry.providers, _TILE_PROVIDERS)

    def test_retrieves_settings(self):
        mock = _TILE_PROVIDERS[:4] + self.mock_providers
        self.store[SettingsKey] = _TILE_PROVIDERS[:4] + self.mock_providers
        registry = TileProvidersRegistry()
        self.assertEqual(registry.providers, self.store[SettingsKey])
        self.assertIsNot(registry.providers, mock)

    def test_len(self):
        registry = TileProvidersRegistry()
        self.assertEqual(len(registry), len(_TILE_PROVIDERS))

        registry.append(self.mock_providers[0])
        registry.append(self.mock_providers[1])
        self.assertEqual(len(registry), len(_TILE_PROVIDERS) + 2)

    def test_getitem(self):
        registry = TileProvidersRegistry()
        registry.append(self.mock_providers[0])
        registry.append(self.mock_providers[1])

        self.assertEqual(registry[0], _TILE_PROVIDERS[0])
        self.assertEqual(registry[1], _TILE_PROVIDERS[1])
        self.assertEqual(registry[len(_TILE_PROVIDERS)], self.mock_providers[0])
        self.assertEqual(registry[len(_TILE_PROVIDERS) + 1], self.mock_providers[1])
        self.assertEqual(registry[-1], self.mock_providers[1])
        with self.assertRaises(IndexError):
            _ = registry[len(_TILE_PROVIDERS) + 2]

    def test_append_and_get(self):
        registry = TileProvidersRegistry()
        registry.append(self.mock_providers[0])
        registry.append(self.mock_providers[1])

        provider = registry.get(_TILE_PROVIDERS[1].name)
        self.assertEqual(registry.get(provider.name), provider)
        self.assertEqual(registry.get("Mock 0"), self.mock_providers[0])
        self.assertEqual(registry.get("Mock 1"), self.mock_providers[1])

        self.assertEqual(
            registry.get("Nonexistent Provider", default=provider.name),
            provider)
        self.assertEqual(
            registry.get("Nonexistent Provider"),
            registry.get(DEFAULT_TILE_PROVIDER))
        registry.providers = [self.mock_providers[0], self.mock_providers[1]]
        self.assertEqual(
            registry.get("Nonexistent Provider"),
            self.mock_providers[0])

    def test_set_item(self):
        registry = TileProvidersRegistry()

        spy1 = QSignalSpy(registry.providers_about_to_be_changed)
        spy2 = QSignalSpy(registry.providers_changed)
        new_provider = _TileProvider(
            name="New Provider",
            url="https://newprovider.com/{z}/{x}/{y}.png",
            attribution="New Attribution",
            size=256,
            max_zoom=5,
        )
        registry[3] = new_provider

        self.assertEqual(registry.providers,
            _TILE_PROVIDERS[:3] + [new_provider] + _TILE_PROVIDERS[4:])
        self.assertEqual(list(self.store.values()), [registry.providers])
        self.assertEqual(len(spy1), 1)
        self.assertEqual(len(spy2), 1)

    def test_del_item(self):
        registry = TileProvidersRegistry()
        spy1 = QSignalSpy(registry.providers_about_to_be_changed)
        spy2 = QSignalSpy(registry.providers_changed)
        del registry[2]
        self.assertEqual(len(spy1), 1)
        self.assertEqual(len(spy2), 1)
        self.assertEqual(registry.providers, _TILE_PROVIDERS[:2] + _TILE_PROVIDERS[3:])
        self.assertEqual(list(self.store.values()), [registry.providers])

    def test_iter(self):
        registry = TileProvidersRegistry()
        registry.append(self.mock_providers[0])
        registry.append(self.mock_providers[1])
        self.assertEqual(list(registry.providers),
                         _TILE_PROVIDERS + self.mock_providers)

    def test_reset_builtins(self):
        registry = TileProvidersRegistry()
        # Sanity check, other test mutated this and caused this test to fail
        assert registry.providers == _TILE_PROVIDERS
        registry.append(self.mock_providers[0])
        registry.append(self.mock_providers[1])
        changed = dataclasses.replace(registry[2], size=128)
        registry[2] = changed
        del registry[3]

        spy1 = QSignalSpy(registry.providers_about_to_be_changed)
        spy2 = QSignalSpy(registry.providers_changed)

        registry.reset_builtins()
        self.assertEqual(len(spy1), 1)
        self.assertEqual(len(spy2), 1)
        self.assertEqual(registry.providers, _TILE_PROVIDERS + [changed] + self.mock_providers)


class TestTileProviderListModel(GuiTest):
    def setUp(self):
        self.registry = TileProvidersRegistry()
        # Just for the case the widget settings have been changed manually and stored
        self.registry.providers = _TILE_PROVIDERS.copy()
        self.model = TileProviderListModel()

    def test_row_count(self):
        self.assertEqual(self.model.rowCount(), len(self.registry))
        spy = QSignalSpy(self.model.modelReset)
        print(len(self.registry.providers))
        del self.registry[2]
        self.assertEqual(self.model.rowCount(), len(self.registry))
        self.assertEqual(len(spy), 1)

    def test_data(self):
        for row in range(len(self.registry)):
            provider = self.registry[row]
            index = self.model.index(row, 0)
            self.assertEqual(self.model.data(index, Qt.DisplayRole), provider.name)


if __name__ == "__main__":
    unittest.main()