import logging

import numpy as np
import pandas as pd
from collections import OrderedDict

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QComboBox, QItemEditorFactory, QLineEdit, QCompleter

from Orange.data import Table, Domain, StringVariable, DiscreteVariable, ContinuousVariable
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel, PyTableModel

from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.mapper import latlon2region, ToLatLon


log = logging.getLogger(__name__)


def available_name(domain, template):
    """Return the next available variable name (from template) that is not
    already taken in domain"""
    for i in range(100000):
        name = '{}{}'.format(template, ('_' + str(i)) if i else '')
        if name not in domain:
            return name


class OWGeocoding(widget.OWWidget):
    name = 'Geocoding'
    description = 'Encode region names into geographical coordinates, or ' \
                  'reverse-geocode latitude and longitude pairs into cultural ' \
                  'regions.'
    icon = "icons/Geocoding.svg"
    priority = 40

    inputs = [("Data", Table, "set_data", widget.Default)]

    outputs = [("Coded Data", Table, widget.Default)]

    settingsHandler = settings.DomainContextHandler()

    resizing_enabled = False

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
    is_decoding = settings.ContextSetting(1)
    str_attr = settings.ContextSetting('')
    str_type = settings.ContextSetting(next(iter(ID_TYPE)))
    lat_attr = settings.ContextSetting('')
    lon_attr = settings.ContextSetting('')
    admin = settings.ContextSetting(0)
    append_features = settings.Setting(True)

    replacements = settings.Setting([], schema_only=True)

    class Error(widget.OWWidget.Error):
        aggregation_discrete = widget.Msg("Only certain types of aggregation defined on categorical attributes: {}")

    class Warning(widget.OWWidget.Warning):
        logarithmic_nonpositive = widget.Msg("Logarithmic quantization requires all values > 0. Using 'equidistant' quantization instead.")

    def __init__(self):
        super().__init__()
        self.data = None
        self.domainmodels = []

        top = self.controlArea

        def _radioChanged():
            self.mainArea.setVisible(self.is_decoding == 0)
            self.commit()

        modes = gui.radioButtons(top, self, 'is_decoding', callback=_radioChanged)

        gui.appendRadioButton(
            modes, '&Encode region names into geographical coordinates:', insertInto=top)
        box = gui.indentedBox(top)
        model = DomainModel(parent=self, valid_types=(StringVariable, DiscreteVariable))
        self.domainmodels.append(model)

        def _region_attr_changed():
            if self.data is None:
                return

            # Auto-detect the type of region in the attribute and set its combo
            values = self._get_data_values()
            func = ToLatLon.detect_input(values)
            str_type = next((k for k, v in self.ID_TYPE.items() if v == func), None)
            if str_type is not None and str_type != self.str_type:
                self.str_type = str_type

            self.commit()

        combo = gui.comboBox(
            box, self, 'str_attr', label='Region identifier:', orientation=Qt.Horizontal,
            callback=_region_attr_changed, sendSelectedValue=True)
        combo.setModel(model)
        gui.comboBox(
            box, self, 'str_type', label='Identifier type:', orientation=Qt.Horizontal,
            items=tuple(self.ID_TYPE.keys()), callback=lambda: self.commit(), sendSelectedValue=True)

        # Select first mode if any of its combos are changed
        for combo in box.findChildren(QComboBox):
            combo.currentIndexChanged.connect(
                lambda: setattr(self, 'is_decoding', 0))

        gui.appendRadioButton(
            modes, '&Decode latitude and longitude into regions:', insertInto=top)
        box = gui.indentedBox(top)
        model = DomainModel(parent=self, valid_types=ContinuousVariable)
        self.domainmodels.append(model)
        combo = gui.comboBox(
            box, self, 'lat_attr', label='Latitude:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(), sendSelectedValue=True)
        combo.setModel(model)
        combo = gui.comboBox(
            box, self, 'lon_attr', label='Longitude:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(), sendSelectedValue=True)
        combo.setModel(model)
        gui.comboBox(
            box, self, 'admin', label='Administrative level:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(),
            items=('Country',
                   '1st-level subdivision (state, region, province, municipality, ...)',
                   '2nd-level subdivisions (1st-level & US counties)'),)

        # Select second mode if any of its combos are changed
        for combo in box.findChildren(QComboBox):
            combo.currentIndexChanged.connect(
                lambda: setattr(self, 'is_decoding', 1))

        gui.checkBox(
            top, self, 'append_features',
            label='E&xtend coded data with additional region properties',
            callback=lambda: self.commit(),
            toolTip='Extend coded data with region properties, such as'
                    'ISO codes, continent, subregion, region type, '
                    'economy type, FIPS/HASC codes, region capital etc. as available.')

        gui.auto_commit(self.controlArea, self, 'autocommit', '&Apply')

        model = self.replacementsModel = PyTableModel(self.replacements, parent=self, editable=[False, True])
        view = gui.TableView(self,
                             sortingEnabled=False,
                             selectionMode=gui.TableView.NoSelection,
                             editTriggers=gui.TableView.AllEditTriggers)
        view.horizontalHeader().setSectionResizeMode(0)
        view.verticalHeader().setSectionResizeMode(0)
        view.setModel(model)

        owwidget = self

        class EditorFactory(QItemEditorFactory):
            def createEditor(self, p_int, parent):
                nonlocal owwidget
                edit = QLineEdit(parent)
                wordlist = [''] + ToLatLon.valid_values(owwidget.ID_TYPE[owwidget.str_type])
                edit.setCompleter(
                    QCompleter(wordlist, edit,
                               caseSensitivity=Qt.CaseInsensitive,
                               filterMode=Qt.MatchContains))
                return edit

        self.factory = EditorFactory()
        view.itemDelegate().setItemEditorFactory(self.factory)
        model.setHorizontalHeaderLabels(['Unmatched Identifier', 'Custom Replacement'])
        box = gui.vBox(self.mainArea)
        self.info_str = ' /'
        gui.label(box, self, 'Unmatched identifiers: %(info_str)s')
        box.layout().addWidget(view)
        self.mainArea.setVisible(self.is_decoding == 0)

    def commit(self):
        output = None
        if self.data is not None and len(self.data):
            output = self.decode() if self.is_decoding else self.encode()
            if output is not None:
                output = self.data.concatenate((self.data, output))
        self.send('Coded Data', output)

    def decode(self):
        if (self.data is None or not len(self.data) or
                self.lat_attr not in self.data.domain or
                self.lon_attr not in self.data.domain):
            return None
        latlon = np.c_[self.data.get_column_view(self.lat_attr)[0],
                       self.data.get_column_view(self.lon_attr)[0]]
        assert isinstance(self.admin, int)
        with self.progressBar(2) as progress:
            progress.advance()
            regions = pd.DataFrame(latlon2region(latlon, self.admin))
        return self._to_addendum(regions, ['name'])

    def encode(self):
        if self.data is None or not len(self.data) or self.str_attr not in self.data.domain:
            return None
        values = self._get_data_values()
        log.debug('Geocoding %d regions into coordinates', len(values))
        with self.progressBar(4) as progress:
            progress.advance()
            mappings = self.ID_TYPE[self.str_type](values)

            progress.advance()
            invalid_idx = [i for i, value in enumerate(mappings) if not value]
            unmatched = values[invalid_idx].drop_duplicates().dropna().sort_values()
            self.info_str = '{} / {}'.format(len(unmatched), values.nunique())

            replacements = {k: v
                            for k, v in self.replacementsModel.tolist()
                            if v}
            self.replacements = ([[name, '']
                                  for name in unmatched
                                  if name not in replacements] +
                                 [[name, value]
                                  for name, value in replacements.items()])
            self.replacementsModel.wrap(self.replacements)

            progress.advance()
            latlon = pd.DataFrame(mappings)
        return self._to_addendum(latlon, ['latitude', 'longitude'])

    def _get_data_values(self):
        if self.data is None:
            return None
        values = self.data.get_column_view(self.str_attr)[0]
        # no comment
        if self.data.domain[self.str_attr].is_discrete:
            values = np.array(self.data.domain[self.str_attr].values)[values.astype(np.int16)].astype(str)
        values = pd.Series(values)

        # Apply replacements from the replacements table
        if len(self.replacementsModel):
            values = values.replace({k: v
                                     for k, v in self.replacementsModel.tolist()
                                     if v})
        return values

    def _to_addendum(self, df, keep):
        if not df.shape[1]:
            return None

        df.drop(['_id', 'adm0_a3'], axis=1, inplace=True)
        addendum = df if self.append_features else df[keep]
        table = Table(Domain(
            [], metas=[(ContinuousVariable if col in ('latitude', 'longitude') else
                        StringVariable)(available_name(self.data.domain, col))
                       for col in addendum]),
            np.empty((len(addendum), 0)), None, addendum.values)
        return table

    def set_data(self, data):
        self.data = data
        self.closeContext()

        if data is None or not len(data):
            self.commit()
            return

        for model in self.domainmodels:
            model.set_domain(data.domain)

        lat, lon = find_lat_lon(data)
        self.lat_attr = lat.name if lat else None
        self.lon_attr = lon.name if lon else None

        self.openContext(data)
        self.mainArea.setVisible(self.is_decoding == 0)
        self.commit()


def main():
    from AnyQt.QtWidgets import QApplication
    a = QApplication([])

    ow = OWGeocoding()
    ow.show()
    ow.raise_()
    data = Table('philadelphia-crime')
    print(data[:10])
    ow.set_data(data)

    a.exec()
    ow.saveSettings()

if __name__ == "__main__":
    main()
