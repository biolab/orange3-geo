import dataclasses
import unittest
from unittest.mock import patch

from AnyQt.QtCore import Qt
from AnyQt.QtTest import QSignalSpy

from orangewidget.tests.base import GuiTest, WidgetTest
from orangecontrib.geo.widgets.plotutils import _TILE_PROVIDERS, _TileProvider
from orangecontrib.geo.widgets.owmanagegeoservices import \
    TileProviderModel, OWManageGeoServices


class TestTileProviderModel(GuiTest):
    def setUp(self):
        self.model = TileProviderModel()
        # A list interface will suffice for the model
        self.model.registry = \
            _TILE_PROVIDERS[1:4] + \
            [_TileProvider(
                name="Test", url="http://test.com/{z}/{x}/{y}.png", size=256,
                max_zoom=18, attribution="Test")
            ]

    def test_row_and_col_count(self):
        self.assertEqual(self.model.rowCount(), 4)
        self.assertEqual(self.model.columnCount(), 5)

    def test_data(self):
        def assert_data(col, expected):
            value = self.model.data(self.model.index(row, col),
                                    role=Qt.ItemDataRole.DisplayRole)
            self.assertEqual(value, expected)

        for row in range(self.model.rowCount()):
            assert_data(0, "⦿ " * (row < 3) + self.model.registry[row].name)
            assert_data(1, self.model.registry[row].url)
            assert_data(2, str(self.model.registry[row].size))
            assert_data(3, str(self.model.registry[row].max_zoom))
            assert_data(4, self.model.registry[row].attribution)
            self.assertIsNone(
                self.model.index(row, 0).data(Qt.ItemDataRole.TextAlignmentRole)
            )
            self.assertTrue(
                self.model.index(row, 2).data(Qt.ItemDataRole.TextAlignmentRole)
                &  Qt.AlignmentFlag.AlignRight
            )
            self.assertTrue(
                self.model.index(row, 3).data(Qt.ItemDataRole.TextAlignmentRole)
                &  Qt.AlignmentFlag.AlignRight
            )

    def test_set_data(self):
        self.assertTrue(self.model.setData(self.model.index(3, 0), "New Name"))
        self.assertEqual(self.model.registry[3].name, "New Name")

        # Check type conversion for size and max_zoom
        self.assertTrue(self.model.setData(self.model.index(3, 2), "32"))
        self.assertEqual(self.model.registry[3].size, 32)

        self.assertTrue(self.model.setData(self.model.index(3, 3), "10"))
        self.assertEqual(self.model.registry[3].max_zoom, 10)

        self.assertFalse(self.model.setData(self.model.index(3, 2), "invalid"))
        self.assertEqual(self.model.registry[3].size, 32)  # unchanged

        self.assertFalse(self.model.setData(self.model.index(3, 2), "0"))
        self.assertEqual(self.model.registry[3].size, 32)  # unchanged

        self.assertFalse(self.model.setData(self.model.index(3, 2), "-1"))
        self.assertEqual(self.model.registry[3].size, 32)  # unchanged

        self.assertFalse(self.model.setData(self.model.index(3, 1),
                                            "https://test.com{s}"))
        self.assertEqual(self.model.registry[3].url,
                         "http://test.com/{z}/{x}/{y}.png")


    def test_flags(self):
        index = self.model.index(0, 0)
        self.assertTrue(self.model.flags(index) & Qt.ItemFlag.ItemIsEditable)

    def test_header_data(self):
        for col, header in enumerate(TileProviderModel.HEADERS):
            self.assertEqual(
                self.model.headerData(col, Qt.Orientation.Horizontal,
                                      role=Qt.ItemDataRole.DisplayRole),
                header
            )
        self.assertIsNone(
            self.model.headerData(0, Qt.Orientation.Vertical,
                                  role=Qt.ItemDataRole.DisplayRole)
        )


class TestOWManageGeoServices(WidgetTest):
    def setUp(self):
        # Prevent changing the QSettings during tests, as it can affect other
        # tests and the environment
        self.patch_settings = patch(
            "orangecontrib.geo.widgets.plotutils.QSettings.setValue",
            lambda *_: None)
        self.patch_settings.start()
        self.addCleanup(self.patch_settings.stop)

        self.widget = self.create_widget(OWManageGeoServices)
        self.widget.registry.providers = _TILE_PROVIDERS[1:4]

    def test_minimum_size(self):
        pass

    def test_add_tile_provider(self):
        spy = QSignalSpy(self.widget.tile_provider_model.modelReset)
        with patch.object(self.widget.tile_provider_table,
                          "setFixedHeight") as resize:
            self.widget.add_tile_provider()
        self.assertEqual(len(spy), 1)
        resize.assert_called_once()
        self.assertEqual(self.widget.tile_provider_model.rowCount(), 4)

    def test_remove_tile_provider(self):
        self.widget.add_tile_provider()
        self.widget.add_tile_provider()
        self.widget.add_tile_provider()
        providers = self.widget.registry.providers.copy()
        rows = [1, 5, 2]
        indices = [self.widget.tile_provider_model.index(row, 0) for row in rows]
        spy = QSignalSpy(self.widget.tile_provider_model.modelReset)
        with patch.object(self.widget.tile_provider_table,
                          "setFixedHeight") as resize, \
                patch.object(self.widget.tile_provider_table.selectionModel(),
                             "selectedRows", return_value=indices):
            self.widget.remove_selected_providers()
        self.assertEqual(len(spy), 3)
        resize.assert_called()
        self.assertEqual(
            self.widget.registry.providers,
            [p for i, p in enumerate(providers) if i not in rows])

    def test_dont_remove_all(self):
        row_count = self.widget.tile_provider_model.rowCount()
        indices = [
            self.widget.tile_provider_model.index(row, 0)
            for row in range(row_count)]
        with patch.object(self.widget.tile_provider_table.selectionModel(),
                          "selectedRows", return_value=indices), \
                patch("AnyQt.QtWidgets.QMessageBox.information") as warning:
            self.widget.remove_selected_providers()
        self.assertEqual(len(self.widget.registry.providers), row_count)
        warning.assert_called_once()

    def test_reset_default_providers(self):
        self.widget.add_tile_provider()
        new_provider = self.widget.registry[-1]
        replaced = dataclasses.replace(
            self.widget.registry[2],
            url="http://replaced.com/{z}/{x}/{y}.png")
        self.widget.registry[2] = replaced
        assert len(self.widget.registry) == 4

        spy = QSignalSpy(self.widget.tile_provider_model.modelReset)
        with patch.object(self.widget.tile_provider_table, "setFixedHeight") as resize:
            self.widget.restore_default_providers()
        self.assertNotEqual(len(spy), 0)
        resize.assert_called()
        self.assertEqual(
            self.widget.registry.providers,
            _TILE_PROVIDERS + [replaced, new_provider])

    def test_save(self):
        with patch("AnyQt.QtWidgets.QFileDialog.getSaveFileName",
                   return_value=("test.json", "JSON Files (*.json)")) as dialog, \
                patch("builtins.open", unittest.mock.mock_open()) as m_open, \
                patch.object(self.widget.registry, "save_to_file") as save:
            self.widget.save()
        dialog.assert_called_once()
        m_open.assert_called_once_with("test.json", "w", encoding="utf-8")
        save.assert_called_once()

        with patch("AnyQt.QtWidgets.QFileDialog.getSaveFileName",
                   return_value=(None, "")) as dialog, \
                patch("builtins.open", unittest.mock.mock_open()) as m_open, \
                patch.object(self.widget.registry, "save_to_file") as save:
            self.widget.save()
        dialog.assert_called_once()
        m_open.assert_not_called()
        save.assert_not_called()

    def test_load(self):
        with patch("AnyQt.QtWidgets.QFileDialog.getOpenFileName",
                   return_value=("test.json", "JSON Files (*.json)")) as dialog, \
                patch("builtins.open", unittest.mock.mock_open()) as m_open, \
                patch.object(self.widget.registry, "load_from_file") as load:
            self.widget.load()
        dialog.assert_called_once()
        m_open.assert_called_once_with("test.json", "r", encoding="utf-8")
        load.assert_called_once()

        with patch("AnyQt.QtWidgets.QFileDialog.getOpenFileName",
                   return_value=(None, "")) as dialog, \
                patch("builtins.open", unittest.mock.mock_open()) as m_open, \
                patch.object(self.widget.registry, "load_from_file") as load:
            self.widget.load()
        dialog.assert_called_once()
        m_open.assert_not_called()
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()

