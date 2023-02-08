import logging
from itertools import chain

import numpy as np
import pandas as pd
from collections import OrderedDict

from AnyQt.QtCore import Qt, QPersistentModelIndex
from AnyQt.QtWidgets import QComboBox, QItemDelegate, QLineEdit, \
    QCompleter, QHeaderView, QLayout, QWIDGETSIZE_MAX

from Orange.data import Table, Domain, StringVariable, DiscreteVariable, ContinuousVariable
from Orange.data.util import get_unique_names
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel, PyTableModel
from Orange.widgets.widget import Input, Output
from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.mapper import latlon2region, ToLatLon


log = logging.getLogger(__name__)


def guess_region_attr_name(data):
    """Return the name of the first variable that could specify a region name"""
    string_vars = (var for var in data.domain.metas if var.is_string)
    discrete_vars = (var for var in data.domain.variables if var.is_discrete)
    for var in chain(string_vars, discrete_vars):
        return var


class OWGeocoding(widget.OWWidget):
    name = 'Geocoding'
    description = 'Encode region names into geographical coordinates, or ' \
                  'reverse-geocode latitude and longitude pairs into regions.'
    icon = "icons/Geocoding.svg"
    priority = 40

    class Inputs:
        data = Input("Data", Table, default=True)

    class Outputs:
        coded_data = Output("Coded Data", Table, default=True)

    settings_version = 2
    settingsHandler = settings.DomainContextHandler()

    ID_TYPE = OrderedDict((
        ('Country name', ToLatLon.from_cc_name),
        ('ISO 3166-1 alpha-2 country code', ToLatLon.from_cc2),
        ('ISO 3166-1 alpha-3 country code', ToLatLon.from_cc3),
        # ('ISO 3166-1 numeric-3 country code', ),  # Who uses this?
        # ('ISO 3166-2 subdivision code', ),  # XXX: where to get these?
        ('Region name', ToLatLon.from_region),
        ('Major city (US)', ToLatLon.from_city_us),
        ('Major city (Europe)', ToLatLon.from_city_eu),
        ('Major city (World)', ToLatLon.from_city_world),
        ('FIPS code', ToLatLon.from_fips),
        ('HASC code', ToLatLon.from_hasc),
        ('US state (name or abbr.)', ToLatLon.from_us_state),
    ))

    autocommit = settings.Setting(True)
    is_decoding = settings.ContextSetting(0)
    str_attr = settings.ContextSetting(None)
    str_type = settings.ContextSetting(next(iter(ID_TYPE)))
    lat_attr = settings.ContextSetting(None)
    lon_attr = settings.ContextSetting(None)
    admin = settings.ContextSetting(0)
    append_features = settings.Setting(False)

    replacements = settings.Setting([], schema_only=True)

    def setMainAreaVisibility(self, visible):
        self.mainArea.setVisible(visible)
        if visible:
            constraint = QLayout.SetMinAndMaxSize
        else:
            constraint = QLayout.SetFixedSize
        self.layout().setSizeConstraint(constraint)
        if visible:
            # immediately reset the maximum size constraint `setSizeConstraint`
            # will do this only on scheduled layout
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self.statusBar().setSizeGripEnabled(visible)
        self.updateGeometry()
        self.adjustSize()

    def __init__(self):
        super().__init__()
        self.data = None
        self.domainmodels = []
        self.unmatched = []

        top = self.controlArea

        def _radioChanged():
            self.commit()

        modes = gui.radioButtons(top, self, 'is_decoding', callback=_radioChanged)

        gui.appendRadioButton(
            modes, '&Encode region names into geographical coordinates:', insertInto=top)
        box = gui.indentedBox(top)
        model = DomainModel(parent=self, valid_types=(StringVariable, DiscreteVariable))
        self.domainmodels.append(model)

        combo = gui.comboBox(
            box, self, 'str_attr', label='Region identifier:',
            orientation=Qt.Horizontal, callback=self.region_attr_changed,
            sendSelectedValue=True, model=model)
        gui.comboBox(
            box, self, 'str_type', label='Identifier type:', orientation=Qt.Horizontal,
            items=tuple(self.ID_TYPE.keys()), callback=lambda: self.commit(), sendSelectedValue=True)

        # Select first mode if any of its combos are changed
        for combo in box.findChildren(QComboBox):
            combo.activated.connect(
                lambda: setattr(self, 'is_decoding', 0))

        gui.appendRadioButton(
            modes, '&Decode latitude and longitude into regions:', insertInto=top)
        box = gui.indentedBox(top)
        model = DomainModel(parent=self, valid_types=ContinuousVariable)
        self.domainmodels.append(model)
        combo = gui.comboBox(
            box, self, 'lat_attr', label='Latitude:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(), sendSelectedValue=True, model=model)
        combo = gui.comboBox(
            box, self, 'lon_attr', label='Longitude:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(), sendSelectedValue=True, model=model)
        gui.comboBox(
            box, self, 'admin', label='Administrative level:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(),
            items=('Country',
                   '1st-level subdivision (state, region, province, municipality, ...)',
                   '2nd-level subdivisions (1st-level & US counties)'),)

        # Select second mode if any of its combos are changed
        for combo in box.findChildren(QComboBox):
            combo.activated.connect(
                lambda: setattr(self, 'is_decoding', 1))

        gui.checkBox(
            top, self, 'append_features',
            label='E&xtend coded data with additional region properties',
            callback=lambda: self.commit(),
            toolTip='Extend coded data with region properties, such as'
                    'ISO codes, continent, subregion, region type, '
                    'economy type, FIPS/HASC codes, region capital etc. as available.')

        gui.auto_commit(self.controlArea, self, 'autocommit', '&Apply')
        gui.rubber(self.controlArea)

        model = self.replacementsModel = PyTableModel(self.replacements,
                                                      parent=self,
                                                      editable=[False, True])
        view = gui.TableView(self,
                             sortingEnabled=False,
                             selectionMode=gui.TableView.NoSelection,
                             editTriggers=gui.TableView.AllEditTriggers)
        view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        view.verticalHeader().setSectionResizeMode(0)
        view.setMinimumWidth(500)
        view.setModel(model)

        owwidget = self

        class TableItemDelegate(QItemDelegate):
            def createEditor(self, parent, options, index):
                nonlocal owwidget
                edit = QLineEdit(parent)
                wordlist = [''] + ToLatLon.valid_values(owwidget.ID_TYPE[owwidget.str_type])
                edit.setCompleter(
                    QCompleter(wordlist, edit,
                               caseSensitivity=Qt.CaseInsensitive,
                               filterMode=Qt.MatchContains))

                def save_and_commit():
                    if edit.text() and edit.text() in wordlist:
                        model = index.model()
                        pindex = QPersistentModelIndex(index)
                        if pindex.isValid():
                            new_index = pindex.sibling(pindex.row(),
                                                       pindex.column())
                            save = model.setData(new_index,
                                                 edit.text(),
                                                 Qt.EditRole)
                            if save:
                                owwidget.commit()
                                return
                    edit.clear()

                edit.editingFinished.connect(save_and_commit)
                return edit

        view.setItemDelegate(TableItemDelegate())
        model.setHorizontalHeaderLabels(['Unmatched Identifier', 'Custom Replacement'])
        box = gui.vBox(self.mainArea)
        self.info_str = ' /'
        gui.label(box, self, 'Unmatched identifiers: %(info_str)s')
        box.layout().addWidget(view)
        self.setMainAreaVisibility(False)

    def region_attr_changed(self):
        if self.data is None:
            return
        if self.str_attr:
            # Auto-detect the type of region in the attribute and set its combo
            values = self._get_data_values()
            func = ToLatLon.detect_input(values)
            str_type = next((k for k, v in self.ID_TYPE.items() if v == func), None)
            if str_type is not None and str_type != self.str_type:
                self.str_type = str_type

        self.commit()

    def commit(self):
        output = None
        if self.data is not None and len(self.data):
            data, metas = self.decode() if self.is_decoding else self.encode()
            if data is not None:
                output = self.data.transform(
                    Domain(self.data.domain.attributes,
                           self.data.domain.class_vars,
                           self.data.domain.metas + metas))
                with output.unlocked(output.metas):
                    output.metas[:, -data.shape[1]:] = data

        self.Outputs.coded_data.send(output)

    def decode(self):
        self.setMainAreaVisibility(False)
        if (self.data is None or not len(self.data) or
                self.lat_attr not in self.data.domain or
                self.lon_attr not in self.data.domain):
            return None
        latlon = np.c_[self.data.get_column(self.lat_attr),
                       self.data.get_column(self.lon_attr)]
        assert isinstance(self.admin, int)
        with self.progressBar(2) as progress:
            progress.advance()
            regions = pd.DataFrame(latlon2region(latlon, self.admin))
        return self._to_addendum(regions, ['name'])

    def encode(self):
        if self.data is None or not len(self.data) or self.str_attr not in self.data.domain:
            self.setMainAreaVisibility(False)
            return None
        values = self._get_data_values()
        log.debug('Geocoding %d regions into coordinates', len(values))
        with self.progressBar(4) as progress:
            progress.advance()
            mappings = self.ID_TYPE[self.str_type](values)

            progress.advance()
            invalid_idx = [i for i, value in enumerate(mappings) if not value]
            self.unmatched = values[invalid_idx].drop_duplicates().dropna().sort_values()
            self.info_str = '{} / {}'.format(len(self.unmatched),
                                             values.nunique())

            replacements = {k: v
                            for k, v in self.replacementsModel.tolist()
                            if v}

            rep_unmatched = [[name, '']
                             for name in self.unmatched
                             if name not in replacements]
            rep_matched = [list(items) for items in replacements.items()]

            self.replacements = sorted(rep_unmatched + rep_matched)
            self.replacementsModel.wrap(self.replacements)
            self.setMainAreaVisibility(bool(self.replacements))

            progress.advance()
            latlon = pd.DataFrame(mappings)
        return self._to_addendum(latlon, ['latitude', 'longitude'])

    def _get_data_values(self):
        if self.data is None:
            return None

        values = self.data.get_column(self.str_attr)
        # no comment
        if self.str_attr.is_discrete:
            values = np.array(self.str_attr.values)[values.astype(np.int16)].astype(str)
        values = pd.Series(values)

        # Apply replacements from the replacements table
        if len(self.replacementsModel):
            values = values.replace({k: v
                                     for k, v in self.replacementsModel.tolist()
                                     if v})
        return values

    def _to_addendum(self, df, keep):
        if not df.shape[1]:
            return None, None

        df.drop(['_id', 'adm0_a3'], axis=1, inplace=True)
        addendum = df if self.append_features else df[keep]

        metas = []
        for col in addendum:
            unique_name = get_unique_names(self.data.domain, col)
            if col in ('latitude', 'longitude'):
                metas.append(ContinuousVariable(unique_name))
            else:
                metas.append(StringVariable(unique_name))

        return addendum.values, tuple(metas)

    @Inputs.data
    def set_data(self, data):
        self.data = data
        self.closeContext()

        if data is None or not len(data):
            self.clear()
            self.commit()
            return

        for model in self.domainmodels:
            model.set_domain(data.domain)

        attr = self.str_attr = guess_region_attr_name(data)
        if attr is None:
            self.is_decoding = 1

        self.lat_attr, self.lon_attr = find_lat_lon(data)

        self.openContext(data)
        self.region_attr_changed()

    def clear(self):
        self.data = None
        for model in self.domainmodels:
            model.set_domain(None)
        self.unmatched = []
        self.str_attr = self.lat_attr = self.lon_attr = None

    @classmethod
    def migrate_context(cls, context, version):
        if version < 2:
            for attr in ["str_attr", "lat_attr", "lon_attr"]:
                settings.migrate_str_to_variable(context, names=attr,
                                                 none_placeholder="")

def main():
    from AnyQt.QtWidgets import QApplication
    a = QApplication([])

    ow = OWGeocoding()
    ow.show()
    ow.raise_()
    data = Table("India_census_district_population")
    data = data[:10]
    ow.set_data(data)

    a.exec()
    ow.saveSettings()

if __name__ == "__main__":
    main()
