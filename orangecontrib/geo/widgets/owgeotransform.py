from itertools import chain

from AnyQt.QtCore import Qt
from pyproj import Transformer, database

from orangewidget import gui
from orangewidget.widget import Msg

from Orange.widgets import settings
from Orange.widgets.widget import OWWidget
from Orange.widgets.utils.itemmodels import DomainModel, PyListModelTooltip
from Orange.widgets.utils.signals import Input, Output

from Orange.data import ContinuousVariable, Table
from Orange.data.util import get_unique_names

from orangecontrib.geo.utils import find_lat_lon


def get_projections():
    supported_proj = database.query_crs_info()
    return {i[2]: f"{i[0]}:{i[1]}" for i in supported_proj}


class OWGeoTransform(OWWidget):
    name = "Geo Transform"
    description = "Transform geographic coordinates from one system to another."
    icon = "icons/GeoTransform.svg"
    priority = 320
    keywords = ["transform", "geo"]

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        data = Output("Data", Table)

    settingsHandler = settings.DomainContextHandler()
    attr_lat = settings.ContextSetting(None)
    attr_lon = settings.ContextSetting(None)
    from_idx = settings.Setting("Slovenia 1996 / Slovene National Grid")
    to_idx = settings.Setting("WGS 84")

    want_main_area = False
    resizing_enabled = False

    EPSG_CODES = get_projections()

    class Error(OWWidget.Error):
        no_lat_lon_vars = Msg(
                "Data has no latitude and longitude variables.")

    def __init__(self):
        super().__init__()
        self.data = None

        box = gui.vBox(self.controlArea, box="Coordinates:")

        self.variable_model = DomainModel(
            order=DomainModel.MIXED, valid_types=(ContinuousVariable,))

        geo_args = dict(contentsLength=100, searchable=True,
                        model=self.variable_model, orientation=Qt.Horizontal)

        gui.comboBox(box, self, "attr_lat", label="Latitude:", **geo_args)
        gui.comboBox(box, self, "attr_lon", label="Longitude:", **geo_args)

        box = gui.vBox(self.controlArea, box="Transformation:")

        transform_model = PyListModelTooltip()
        transform_model.setParent(self)
        transform_model[:] = chain(list(self.EPSG_CODES))
        transform_model.tooltips[:] = chain(list(self.EPSG_CODES))

        proj_args = dict(contentsLength=100, searchable=True,
                         model=transform_model, orientation=Qt.Horizontal,
                         sendSelectedValue=True)

        gui.comboBox(box, self, "from_idx", label="From:", **proj_args)
        gui.comboBox(box, self, "to_idx", label="To:", **proj_args)

        self.commit_button = gui.button(self.controlArea, self, "&Commit",
                                        self.apply)

    def init_attr_values(self):
        self.Error.clear()
        lat, lon = None, None
        if self.data is not None:
            lat, lon = find_lat_lon(self.data, filter_hidden=True)
            if lat is None or lon is None:
                # we either find both or we try all numeric
                if self.data.domain.has_continuous_attributes(
                        include_metas=True):
                    vars = [var for var in self.data.domain.variables
                            if var.is_continuous] + \
                           [var for var in self.data.domain.metas if
                            var.is_continuous]
                    lat, lon = vars[0], vars[0]
                else:
                    self.Error.no_lat_lon_vars()
                    self.data = None
                    lat, lon = None, None

        self.variable_model.set_domain(self.data.domain if self.data else None)
        self.attr_lat, self.attr_lon = lat, lon

    @Inputs.data
    def set_data(self, data: Table = None):
        self.data = data
        self.closeContext()

        if not data:
            self.clear()
            self.init_attr_values()
            self.Outputs.data.send(None)
            return

        self.init_attr_values()
        self.openContext(self.data)
        self.apply()

    def clear(self):
        self.data = None
        self.attr_lat = self.attr_lon = None

    def apply(self):
        if not self.data:
            self.Outputs.data.send(None)
            return
        transformer = Transformer.from_crs(self.EPSG_CODES[self.from_idx],
                                           self.EPSG_CODES[self.to_idx])
        latitude = self.data.get_column_view(self.attr_lat)[0]
        longitude = self.data.get_column_view(self.attr_lon)[0]
        lat, lon = zip(*transformer.itransform(zip(latitude, longitude)))

        var_names = [v.name for v in self.data.domain.variables +
                     self.data.domain.metas]
        lat_var = ContinuousVariable(get_unique_names(var_names, "lat"))
        lon_var = ContinuousVariable(get_unique_names(var_names, "lon"))
        out = self.data.add_column(lat_var, lat)
        out = out.add_column(lon_var, lon)
        self.Outputs.data.send(out)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    data = Table.from_url("http://datasets.biolab.si/core/philadelphia-crime.csv.xz")
    WidgetPreview(OWGeoTransform).run(set_data=data)
