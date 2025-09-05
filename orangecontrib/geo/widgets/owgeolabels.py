from itertools import chain

import numpy as np
import pandas as pd

from AnyQt.QtWidgets import QGridLayout, QLabel

from orangewidget.utils.widgetpreview import WidgetPreview
from Orange.data import Table, Domain, StringVariable, ContinuousVariable
from Orange.data.util import get_unique_names
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.widget import Input, Output

from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.mapper import latlon2region


ADMIN_LEVELS = (
    'Country',
    '1st-level subdivision (state, region, province, municipality, ...)',
    '2nd-level subdivisions (1st-level & US counties)'

)
class OWGeoLabels(widget.OWWidget):
    name = "Geo Labels"
    description = 'Assign names corresponding to geographical coordinates.'
    icon = "icons/GeoLabels.svg"
    priority = 40
    keywords = "geocoding, geo, coding"

    class Inputs:
        data = Input("Data", Table, default=True)

    class Outputs:
        coded_data = Output("Data", Table, default=True)

    class Error(widget.OWWidget.Error):
        no_valid_columns = widget.Msg("Input data contains no numeric columns.")

    want_main_area = False
    resizing_enabled = False

    settingsHandler = settings.DomainContextHandler()
    autocommit = settings.Setting(True)
    lat_attr = settings.ContextSetting(None)
    lon_attr = settings.ContextSetting(None)
    admin = settings.ContextSetting(0)
    append_features = settings.Setting(False)

    def __init__(self):
        super().__init__()
        self.data = None
        self.n_mismatches = False  # For reporting
        self.domainmodel = DomainModel(valid_types=(ContinuousVariable, ))

        grid = QGridLayout()
        gui.widgetBox(self.controlArea, True, orientation=grid)
        grid.addWidget(QLabel("Latitude:"), 0, 0)
        grid.addWidget(
            gui.comboBox(
                None, self, 'lat_attr', model=self.domainmodel,
                callback=self.commit.deferred),
            1, 0)

        grid.addWidget(QLabel("Longitude:"), 0, 1)
        grid.addWidget(
            gui.comboBox(
                None, self, 'lon_attr', model=self.domainmodel,
                callback=self.commit.deferred),
            1, 1)

        grid.addWidget(QLabel("Administrative level:"), 2, 0)
        grid.addWidget(
            gui.comboBox(
                None, self, 'admin',
                items=ADMIN_LEVELS,
                callback=self.commit.deferred),
            3, 0, 1, 2)

        gui.checkBox(
            gui.widgetBox(self.controlArea, True), self, 'append_features',
            label='Include additional properties',
            callback=self.commit.deferred,
            toolTip='Extend coded data with properties, such as'
                    'ISO codes, continent, subregion, region type, '
                    'economy type, FIPS/HASC codes, region capital etc.'
                    'as available.')

        gui.auto_commit(self.controlArea, self, 'autocommit', '&Apply')

    @Inputs.data
    def set_data(self, data):
        self.closeContext()

        if not data:
            self.data = None
            self.domainmodel.set_domain(None)
        else:
            self.data = data
            self.domainmodel.set_domain(data.domain)
            self.lat_attr, self.lon_attr = find_lat_lon(data)
            self.openContext(data)

        self.Error.no_valid_columns(shown=data and not self.domainmodel)
        self.commit.now()

    @gui.deferred
    def commit(self):
        if not self.data or self.lat_attr is None or self.lon_attr is None:
            self.Outputs.coded_data.send(None)
            self.n_mismatches = False
            return

        data, metas = self.decode()
        output = self.data.transform(
            Domain(self.data.domain.attributes,
                   self.data.domain.class_vars,
                   self.data.domain.metas + metas))
        with output.unlocked(output.metas):
            output.metas[:, -data.shape[1]:] = data
        self.n_mismatches = np.sum(output.get_column(metas[0]) == "")
        self.Outputs.coded_data.send(output)

    def decode(self):
        latlon = np.c_[self.data.get_column(self.lat_attr),
                       self.data.get_column(self.lon_attr)]
        regions = pd.DataFrame(latlon2region(latlon, self.admin))

        name_var = StringVariable(get_unique_names(self.data.domain, "Name"))

        if regions.empty:
            return (
                np.full((len(self.data), 1), ""),
                (name_var, )
            )

        if self.append_features:
            addendum = regions.drop(['_id', 'adm0_a3', 'longitude', 'latitude'],
                                     axis=1)
            metas = tuple(
                StringVariable(get_unique_names(self.data.domain, name))
                for name in addendum
            )
        else:
            addendum = regions[['name']]
            metas = (name_var, )

        values = addendum.values
        values[pd.isna(values)] = ""
        return values, metas

    def send_report(self):
        if not self.data or self.lon_attr is None or self.lat_attr is None:
            return

        self.report_items((("Latitude", self.lat_attr.name),
                           ("Longitude", self.lon_attr.name),
                           ("Administrative level", ADMIN_LEVELS[self.admin]),
                           ("Unmatched coordinates", self.n_mismatches)))


if __name__ == "__main__":
    WidgetPreview(OWGeoLabels).run(Table("India_census_district_population"))
