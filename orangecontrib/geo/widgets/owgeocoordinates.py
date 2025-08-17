from itertools import chain
from typing import Union

import numpy as np
import pandas as pd

from AnyQt.QtCore import Qt, pyqtSignal as Signal, QAbstractTableModel
from AnyQt.QtGui import QFont
from AnyQt.QtWidgets import QItemDelegate, QLineEdit, QLabel, \
    QCompleter, QHeaderView, QSizePolicy, QGridLayout

from orangewidget.utils.widgetpreview import WidgetPreview
from Orange.data import \
    Table, Domain, StringVariable, DiscreteVariable, ContinuousVariable
from Orange.data.util import get_unique_names
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.widget import Input, Output

from orangecontrib.geo.utils import LAT_LONG_NAMES
from orangecontrib.geo.mapper import ToLatLon, RegionTypes


class ReplacementModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.unmatched = []
        self.matched = []

    def rowCount(self, parent=None, *_, **__):
        if parent and parent.isValid() \
                or not self.unmatched and not self.matched:
            return 0
        return len(self.unmatched) + len(self.matched) + 1

    def columnCount(self, parent=None, *_, **__):
        if parent and parent.isValid():
            return 0
        return 2

    def set_items(self, unmatched, matched):
        self.beginResetModel()
        self.unmatched = unmatched
        self.matched = matched
        self.endResetModel()

    def headerData(self, section, orientation, role=None):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["Identifier", "Replacement"][section]

    def flags(self, index):
        flags = super().flags(index)
        if not index.isValid() or index.column() == 0 \
                or index.row() == len(self.unmatched):
            return flags
        return flags | Qt.ItemIsEditable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return

        row = index.row()
        nunmatched = len(self.unmatched)
        if row < nunmatched:
            if role == Qt.DisplayRole:
                return self.unmatched[row][index.column()]
            if role == Qt.FontRole and index.column() == 0:
                font = QFont()
                font.setBold(True)
                return font
            if role == Qt.ToolTipRole:
                return "Unknown region name; provide a recognized synonym."
        elif row > nunmatched:  # But not equal - the middle line is empty!
            row -= nunmatched + 1
            if role == Qt.DisplayRole:
                item = self.matched[row]
                return item[index.column()] or f"({item[0]})"
            if role == Qt.ToolTipRole:
                return "Region recognized; you may change it if necessary."

        return None

    def setData(self, index, value, role=None):
        if not index.isValid() or index.column() > 1 or role != Qt.EditRole:
            return False
        row = index.row()
        if row < len(self.unmatched):
            self.unmatched[row][index.column()] = value
        else:
            self.matched[row - len(self.unmatched)  - 1][index.column()] = value
        return True

    def replacements(self):
        return {k: v for k, v in chain(self.unmatched, self.matched) if v}

class ReplacementDelegate(QItemDelegate):
    replacementsChanged = Signal(str, str)

    def __init__(self, valid_names, parent):
        super().__init__(parent)
        self.valid_names = valid_names

    def set_valid_names(self, valid_names):
        self.valid_names = valid_names

    def emitReplacement(self, index):
        self.replacementsChanged.emit(
            index.siblingAtColumn(0).data(),
            index.data())

    def createEditor(self, parent, options, index):
        edit = QLineEdit(parent)
        completer = QCompleter(self.valid_names, edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        edit.setCompleter(completer)

        @edit.editingFinished.connect
        def save_and_commit():
            if edit.text() in self.valid_names \
                    and index.model().setData(index, edit.text(), Qt.EditRole):
                self.emitReplacement(index)
                return
            edit.clear()

        @edit.returnPressed.connect
        def save_commit():
            if edit.text() and edit.text() not in self.valid_names \
                    or not index.model().setData(index, edit.text(), Qt.EditRole):
                return

            self.emitReplacement(index)
            edit.clearFocus()

            next_row = index.row() + 1
            if next_row < len(index.model().unmatched):
                self.parent().edit(index.siblingAtRow(next_row))

        return edit


class OWGeoCoordinates(widget.OWWidget):
    name = "Geocoding"
    description = "Add geographical coordinates for regions or places"
    icon = "icons/Geocoding.svg"
    priority = 40
    keywords = "geocoding, geo, coding"

    class Inputs:
        data = Input("Data", Table, default=True)

    class Outputs:
        coded_data = Output("Data", Table, default=True)

    want_main_area = False
    resizing_enabled = False

    settingsHandler = settings.DomainContextHandler()

    region_attr: Union[DiscreteVariable, StringVariable, None] \
        = settings.ContextSetting(None)
    region_type = settings.ContextSetting(0)
    append_features = settings.Setting(False)
    autocommit = settings.Setting(True)

    replacements: dict[str, str] = settings.Setting({}, schema_only=True)

    def __init__(self):
        super().__init__()
        self.data = None
        self.unmatched = []

        self.domainmodel = DomainModel(
            parent=self,
            valid_types=(StringVariable, DiscreteVariable))

        layout = QGridLayout()
        gui.widgetBox(self.controlArea, orientation=layout)
        region_combo = gui.comboBox(
            None, self, 'region_attr',
            callback=self.on_region_attr_changed,
            model=self.domainmodel
        )
        layout.addWidget(QLabel("Region identifier:"), 0, 0)
        layout.addWidget(region_combo, 1, 0)

        self.region_type_combo = gui.comboBox(
            None, self, 'region_type', items=[t.name for t in RegionTypes],
            callback=self.on_region_type_changed)
        layout.addWidget(QLabel("Region type:"), 0, 1)
        layout.addWidget(self.region_type_combo, 1, 1)

        self.replacementsModel = ReplacementModel(self)
        view = gui.TableView(
            self,
            sortingEnabled=False,
            selectionMode=gui.TableView.NoSelection,
            editTriggers=gui.TableView.AllEditTriggers
        )
        view.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        view.setModel(self.replacementsModel)
        view.setFixedWidth(600)
        self.delegate = ReplacementDelegate(self.region_type, view)
        self.delegate.replacementsChanged.connect(self.replacements_changed)
        view.setItemDelegate(self.delegate)
        layout.addWidget(view, 2, 0, 1, 2)

        gui.checkBox(
            self.controlArea, self, 'append_features', box=True,
            label='E&xtend data with additional region properties',
            callback=self.commit.deferred,
            toolTip='Extend coded data with region properties, such as'
                    'ISO codes, continent, subregion, region type, '
                    'economy type, FIPS/HASC codes, region capital etc. '
                    'as available.')

        gui.auto_commit(self.controlArea, self, 'autocommit', '&Apply')

        self.statusBar().setSizeGripEnabled(True)

    def on_region_attr_changed(self):
        old_type = self.region_type
        self.guess_region_type()
        if old_type != self.region_type:
            self.update_delegate()
        self.update_replacement_model()
        self.commit.deferred()

    def on_region_type_changed(self):
        self.update_delegate()
        self.update_replacement_model()
        self.commit.deferred()

    def update_delegate(self):
        self.delegate.set_valid_names(
            ToLatLon.valid_values(RegionTypes[self.region_type].mapper))

    def guess_region_type(self):
        if self.data is None or not self.region_attr:
            return

        values = self._get_data_values()
        if values is None:
            return

        func = ToLatLon.detect_input(values)
        for i, t in enumerate(RegionTypes):
            if t.mapper == func:  # `is` doesn't work for bound methods
                self.region_type = i
                return

    def replacements_changed(self, key, value):
        self.replacements[key] = value
        self.commit.deferred()

    @Inputs.data
    def set_data(self, data):
        self.closeContext()
        self.data = data

        if data is None or not len(data):
            self.region_attr = None
            self.domainmodel.set_domain(None)
            self.update_replacement_model()
            self.commit.now()
            return

        self.domainmodel.set_domain(data.domain)
        self.region_attr = self.domainmodel[0] if self.domainmodel else None
        self.guess_region_type()
        self.openContext(data)
        self.region_type_combo.setCurrentText(RegionTypes[self.region_type].name)
        self.update_delegate()
        self.update_replacement_model()

        self.commit.now()

    def _valid_data(self):
        return self.data is not None \
            and len(self.data) > 0 \
            and self.region_attr is not None

    @gui.deferred
    def commit(self):
        if not self._valid_data():
            self.Outputs.coded_data.send(None)
            return

        data, metas = self.encode()
        if data is None:
            self.Outputs.coded_data.send(None)
            return

        output = self.data.transform(
            Domain(self.data.domain.attributes,
                   self.data.domain.class_vars,
                   self.data.domain.metas + metas))
        with output.unlocked(output.metas):
            output.metas[:, -data.shape[1]:] = data

        self.Outputs.coded_data.send(output)

    def update_replacement_model(self):
        if not self._valid_data():
            self.replacementsModel.set_items([], [])
            return

        values = self._get_data_values(no_replacements=True)
        mappings = RegionTypes[self.region_type].mapper(values)

        mask = np.array([not value for value in mappings])
        unmatched = values[mask].drop_duplicates().dropna().sort_values()
        matched = values[~mask].drop_duplicates().dropna().sort_values()
        self.replacementsModel.set_items(
            *([[k, self.replacements.get(k, "")] for k in m]
                for m in (unmatched, matched)))

    def encode(self):
        if not self._valid_data():
            return None, None

        values = self._get_data_values()
        mappings = RegionTypes[self.region_type].mapper(values)
        latlon = pd.DataFrame(mappings)
        if latlon.empty:
            return None, None

        # ignore errors: _id and adm0_a3 are not always present
        latlon.drop(['_id', 'adm0_a3'], axis=1, inplace=True, errors="ignore")
        addendum = latlon if self.append_features else latlon[LAT_LONG_NAMES]

        metas = tuple(
            (ContinuousVariable if col in LAT_LONG_NAMES else StringVariable)
            (get_unique_names(self.data.domain, col))
            for col in addendum)

        return addendum.values, metas

    def _get_data_values(self, no_replacements=False):
        if not self._valid_data():
            return None

        values = self.data.get_column(self.region_attr)
        if self.region_attr.is_discrete:
            values = np.array(self.region_attr.values)[values.astype(np.int16)].astype(str)
        values = pd.Series(values)
        if not no_replacements and self.replacements:
            values = values.replace(self.replacements)
        return values


if __name__ == "__main__":
    WidgetPreview(OWGeoCoordinates).run(
        set_data=Table("/Users/janez/Downloads/_vreme/continents.csv"))
