import dataclasses

from AnyQt.QtCore import Qt, QModelIndex, QAbstractTableModel
from AnyQt.QtWidgets import QTableView, QLayout, QMessageBox, QFileDialog

from orangewidget.utils.widgetpreview import WidgetPreview
from Orange.widgets import gui, widget

from orangecontrib.geo.widgets.plotutils import \
    TileProvidersRegistry, _TileProvider, _TILE_PROVIDERS


class TileProviderModel(QAbstractTableModel):
    HEADERS = ["Name", "URL", "Size", "Max Zoom", "Attribution"]

    def __init__(self):
        super().__init__()
        reg = self.registry = TileProvidersRegistry()
        reg.providers_about_to_be_changed.connect(self.beginResetModel)
        reg.providers_changed.connect(self.endResetModel)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.registry)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        provider = self.registry[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            field = dataclasses.fields(_TileProvider)[index.column()]
            value = str(getattr(provider, field.name))
            if provider in _TILE_PROVIDERS and \
                    index.column() == 0 and \
                    role ==  Qt.ItemDataRole.DisplayRole:
                value = "⦿ " + value
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (2, 3):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        row, col = index.row(), index.column()
        provider = self.registry[row]
        field = dataclasses.fields(_TileProvider)[col]
        try:
            value = field.type(value)
        except ValueError:
            return False
        if field.name == "size" and value <= 0:
            return False
        if field.name == "url":
            try:
                if field.name == "url":
                    value.format(x=0, y=0, z=0)
            except (ValueError, KeyError, IndexError, AttributeError, TypeError):
                return False
        self.registry[row] = dataclasses.replace(provider, **{field.name: value})
        return True

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section < len(self.HEADERS):
                return self.HEADERS[section]
        return None


class OWManageGeoServices(widget.OWWidget):
    name = "Manage Geo Services"
    description = 'Manage services used by Geo Widgets'
    icon = "icons/GeoManager.svg"
    priority = 1000
    keywords = "geo tile"

    want_control_area = False

    def __init__(self):
        super().__init__()
        self.registry = TileProvidersRegistry()

        self.tile_provider_model = TileProviderModel()

        self.tile_provider_table = QTableView(self)
        self.tile_provider_table.setModel(self.tile_provider_model)
        self.tile_provider_table.setSelectionBehavior(QTableView.SelectRows)
        for i, size in enumerate([130, 500, 50, 65, 150]):
            self.tile_provider_table.setColumnWidth(i, size)
        self.tile_provider_model.modelReset.connect(self._resize_table)

        box = gui.vBox(self.mainArea, "Tile Providers")
        box.layout().addWidget(self.tile_provider_table)

        buttons = gui.hBox(box)
        gui.button(buttons, self, "Add Provider",
                   callback=self.add_tile_provider)
        gui.rubber(buttons)
        gui.button(buttons, self, "Remove Selected Providers",
                   callback=self.remove_selected_providers)
        gui.button(buttons, self, "Restore Default Providers",
                   callback=self.restore_default_providers)
        gui.button(buttons, self, "Save to File", callback=self.save)
        gui.button(buttons, self, "Load", callback=self.load)

        self._resize_table()
        self.adjustSize()
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

    def _resize_table(self):
        view = self.tile_provider_table
        height = (
            view.horizontalHeader().height()
            + sum(view.rowHeight(row) for row in range(view.model().rowCount()))
            + 2 * view.frameWidth()
        )
        view.setFixedHeight(min(height, 500))

        width = (
            view.verticalHeader().sizeHint().width()
            + sum(view.columnWidth(col) for col in range(self.tile_provider_model.columnCount()))
            + 2 * view.frameWidth()
        )
        if view.verticalScrollBar().isVisible():
            width += view.verticalScrollBar().sizeHint().width()

        view.setFixedWidth(width)

    def add_tile_provider(self):
        self.registry.append(
            _TileProvider(
                name="Custom provider",
                url="http://<HOST>/{z}/{x}/{y}.png",
                size=256,
                max_zoom=18,
                attribution=""))

    def remove_selected_providers(self):
        rows = self.tile_provider_table.selectionModel().selectedRows()
        rows = {r.row() for r in rows}
        if len(rows) == len(self.registry):
            QMessageBox.information(
                self, "Remove Providers", "Cannot remove all providers.")
            return
        for row in sorted(rows, reverse=True):
            del self.registry[row]

    def restore_default_providers(self):
        self.registry.reset_builtins()

    def save(self):
        name = QFileDialog.getSaveFileName(
            self, "Save Tile Providers", "", "JSON Files (*.json);;All Files (*)")[0]
        if not name:
            return
        with open(name, "w", encoding="utf-8") as f:
            self.registry.save_to_file(f)

    def load(self):
        name = QFileDialog.getOpenFileName(
            self, "Load Tile Providers", "", "JSON Files (*.json);;All Files (*)")[0]
        if not name:
            return
        try:
            with open(name, "r", encoding="utf-8") as f:
                self.registry.load_from_file(f)
        except OSError as exc:
            QMessageBox.warning(self, "Load Tile Providers", str(exc))



if __name__ == "__main__":
    WidgetPreview(OWManageGeoServices).run()
