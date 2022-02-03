from itertools import chain

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QFormLayout

from pyproj import Transformer, database

from orangewidget import gui
from orangewidget.widget import Msg

from Orange.widgets import settings
from Orange.widgets.widget import OWWidget
from Orange.widgets.utils.itemmodels import DomainModel, PyListModelTooltip
from Orange.widgets.utils.signals import Input, Output

from Orange.data import ContinuousVariable, Table, Domain
from Orange.data.util import get_unique_names

from orangecontrib.geo.utils import find_lat_lon


def get_projections():
    supported_proj = database.query_crs_info()
    return {i[2]: f"{i[0]}:{i[1]}" for i in supported_proj}


class GeoTransformer:
    def __init__(self, transformer, var_lat, var_lon, column):
        self.transformer = transformer
        self.var_lat, self.var_lon = var_lat, var_lon
        self.column = column

    def __call__(self, data):
        latitude = data.get_column_view(self.var_lat)[0]
        longitude = data.get_column_view(self.var_lon)[0]
        coords = tuple(
            zip(*self.transformer.itransform(zip(latitude, longitude))))
        return coords[self.column]


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
    replace_original = settings.Setting(True)

    want_main_area = False
    resizing_enabled = False

    EPSG_CODES = get_projections()

    class Error(OWWidget.Error):
        no_lat_lon_vars = Msg("Data has no latitude and longitude variables.")

    def __init__(self):
        super().__init__()
        self.data = None

        layout = QFormLayout()
        gui.widgetBox(self.controlArea, box="Coordinates:", orientation=layout)
        self.variable_model = DomainModel(
            order=DomainModel.MIXED, valid_types=(ContinuousVariable,))
        args = dict(contentsLength=100, searchable=True,
                    model=self.variable_model, orientation=Qt.Horizontal)
        layout.addRow("Latitude:", gui.comboBox(None, self, "attr_lat", **args))
        layout.addRow("Longitude:", gui.comboBox(None, self, "attr_lon", **args))
        layout.addWidget(
            gui.checkBox(
                None, self, "replace_original", "Replace original coordinates",
                tooltip="If unchecked, the original coordinates are retained "
                        "and new coordinates are added as separate variables."))

        layout = QFormLayout()
        gui.widgetBox(self.controlArea, "Transformation:", orientation=layout)
        args["model"] = PyListModelTooltip(self.EPSG_CODES, list(self.EPSG_CODES))
        layout.addRow("From:", gui.comboBox(None, self, "from_idx", **args))
        layout.addRow("To:", gui.comboBox(None, self, "to_idx", **args))

        self.commit_button = gui.button(self.controlArea, self, "&Commit",
                                        self.apply)

    def init_attr_values(self):
        self.variable_model.set_domain(self.data.domain if self.data else None)
        self.Error.no_lat_lon_vars.clear()

        if self.variable_model.rowCount() < 2:
            self.Error.no_lat_lon_vars()
            lat, lon = None, None
            self.data = None
        else:
            lat, lon = find_lat_lon(
                self.data, filter_hidden=True, fallback=False)
            if lat is None or lon is None:
                lat, lon = self.variable_model[:2]

        self.attr_lat, self.attr_lon = lat, lon

    @Inputs.data
    def set_data(self, data: Table = None):
        self.data = data
        self.closeContext()
        self.init_attr_values()
        self.openContext(self.data)
        self.apply()

    def apply(self):
        if not self.data:
            self.Outputs.data.send(None)
            return

        out = self.data.transform(self._transformed_domain())
        self.Outputs.data.send(out)

    def _transformed_domain(self):
        dom = self.data.domain
        orig_coords = (self.attr_lat, self.attr_lon)

        names = [var.name for var in orig_coords]
        if not self.replace_original:
            # If appending, use the same names, just with numbers for uniqueness
            existing = [v.name for v in chain(dom.variables, dom.metas)]
            names = get_unique_names(existing, names)

        transformer = Transformer.from_crs(
            self.EPSG_CODES[self.from_idx], self.EPSG_CODES[self.to_idx])
        coords = (
            ContinuousVariable(
                name,
                compute_value=GeoTransformer(transformer, *orig_coords, col))
            for col, name in enumerate(names))

        if self.replace_original:
            tr = dict(zip(orig_coords, coords))

            def r(variables):
                return [tr.get(var, var) for var in variables]

            return Domain(r(dom.attributes), r(dom.class_vars), r(dom.metas))

        # Put each new variable in attributes, if it was there, else to metas
        attrs, metas = list(dom.attributes), list(dom.metas)
        for orig, new in zip(orig_coords, coords):
            (attrs if orig in dom.attributes else metas).append(new)
        return Domain(attrs, dom.class_vars, metas)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    data = Table.from_url("http://datasets.biolab.si/core/philadelphia-crime.csv.xz")
    WidgetPreview(OWGeoTransform).run(set_data=data)
