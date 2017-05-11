import logging

import numpy as np
import pandas as pd
from collections import OrderedDict

from AnyQt.QtCore import Qt

from Orange.data import Table, Domain, StringVariable, DiscreteVariable, ContinuousVariable
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel

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

    want_main_area = False
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

    autocommit = settings.Setting(False)
    is_decoding = settings.ContextSetting(1)
    str_attr = settings.ContextSetting('')
    str_type = settings.ContextSetting(next(iter(ID_TYPE)))
    lat_attr = settings.ContextSetting('')
    lon_attr = settings.ContextSetting('')
    admin = settings.ContextSetting(0)
    append_features = settings.Setting(True)

    class Error(widget.OWWidget.Error):
        aggregation_discrete = widget.Msg("Only certain types of aggregation defined on categorical attributes: {}")

    class Warning(widget.OWWidget.Warning):
        logarithmic_nonpositive = widget.Msg("Logarithmic quantization requires all values > 0. Using 'equidistant' quantization instead.")

    def __init__(self):
        super().__init__()
        self.data = None
        self.domainmodels = []

        top = self.controlArea
        modes = gui.radioButtons(
            top, self, 'is_decoding', callback=lambda: self.commit())

        gui.appendRadioButton(
            modes, '&Encode region names into geographical coordinates:', insertInto=top)
        box = gui.indentedBox(top)
        model = DomainModel(parent=self, valid_types=(StringVariable, DiscreteVariable))
        self.domainmodels.append(model)
        combo = gui.comboBox(
            box, self, 'str_attr', label='Region identifier:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(), sendSelectedValue=True)
        combo.setModel(model)
        gui.comboBox(
            box, self, 'str_type', label='Identifier type:', orientation=Qt.Horizontal,
            items=tuple(self.ID_TYPE.keys()), callback=lambda: self.commit(), sendSelectedValue=True)

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
        gui.comboBox(
            box, self, 'admin', label='Administrative level:', orientation=Qt.Horizontal,
            callback=lambda: self.commit(),
            items=('Country',
                   '1st-level subdivision (state, region, province, municipality, ...)',
                   '2nd-level subdivisions (1st-level & US counties)'),)
        combo.setModel(model)

        gui.checkBox(
            top, self, 'append_features',
            label='E&xtend coded data with additional region properties',
            callback=lambda: self.commit(),
            toolTip='Extend coded data with region properties, such as'
                    'ISO codes, continent, subregion, region type, '
                    'economy type, FIPS/HASC codes, region capital etc. as available.')

        gui.auto_commit(self.controlArea, self, 'autocommit', '&Apply')

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
        regions = pd.DataFrame(latlon2region(latlon, self.admin))
        return self._to_addendum(regions, ['name'])

    def encode(self):
        if self.data is None or not len(self.data) or self.str_attr not in self.data.domain:
            return None
        values = self.data.get_column_view(self.str_attr)[0]
        # no comment
        if self.data.domain[self.str_attr].is_discrete:
            values = np.array(self.data.domain[self.str_attr].values)[values.astype(int)].astype(str)

        log.debug('Geocoding %d regions into coordinates', len(values))
        latlon = pd.DataFrame(self.ID_TYPE[self.str_type](pd.Series(values)))
        return self._to_addendum(latlon, ['latitude', 'longitude'])

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
        # if lat: self.controls.lat_attr.setCurrentText(lat.name)
        # if lon: self.controls.lon_attr.setCurrentText(lon.name)
        self.lat_attr = lat.name if lat else None
        self.lon_attr = lon.name if lon else None

        self.openContext(data)
        self.commit()


def main():
    from AnyQt.QtWidgets import QApplication
    a = QApplication([])

    ow = OWGeocoding()
    ow.show()
    ow.raise_()
    data = Table('/home/jk/PycharmProjects/orange3/geo/small_airports.csv')
    print(data[:10])
    ow.set_data(data)

    a.exec()
    ow.saveSettings()

if __name__ == "__main__":
    main()
