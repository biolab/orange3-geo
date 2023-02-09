from itertools import chain
from dataclasses import dataclass
from typing import Optional, Tuple

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
from Orange.data.util import get_unique_names, SharedComputeValue

from orangecontrib.geo.utils import \
    find_lat_lon, LATITUDE_NAMES, LONGITUDE_NAMES


def get_projections():
    supported_proj = database.query_crs_info()
    return {i[2]: f"{i[0]}:{i[1]}" for i in supported_proj}


class GeoTransformerCommon:
    def __init__(self, transformer, var_lat, var_lon):
        self.transformer = transformer
        self.var_lat, self.var_lon = var_lat, var_lon

    def __call__(self, data):
        latitude = data.get_column(self.var_lat)
        longitude = data.get_column(self.var_lon)
        coords = tuple(
            zip(*self.transformer.itransform(zip(latitude, longitude))))
        return coords


class GeoTransformer(SharedComputeValue):
    def __init__(self, transform, column):
        super().__init__(transform)
        self.column = column

    def compute(self, _, coords):
        return coords[self.column]


@dataclass
class ReportData:
    coord_names: Tuple[str, str] = ("", "")
    transf_names: Optional[Tuple[str, str]] = None
    from_trans: str = ""
    to_trans: str = ""


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
        self.report_data: Optional[ReportData] = None

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
        self.Error.no_lat_lon_vars.clear()
        self.variable_model.set_domain(self.data.domain if self.data else None)

        lat, lon = None, None
        if self.data:
            lat, lon = find_lat_lon(self.data, filter_hidden=True)
            if not (lat and lon):
                self.Error.no_lat_lon_vars()
                self.data = None

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
            self.report_data = None
            return

        self.report_data = ReportData(
            from_trans=self.from_idx,
            to_trans=self.to_idx
        )
        out = self.data.transform(self._transformed_domain())
        self.Outputs.data.send(out)

    def _transformed_domain(self):
        dom = self.data.domain
        orig_coords = (self.attr_lat, self.attr_lon)

        names = [var.name for var in orig_coords]
        self.report_data.coord_names = tuple(names)
        if self.replace_original:
            self.report_data.transf_names = None
        else:
            # If names wouldn't be recognized in following widgets,
            # replace with defaults
            if not (names[0].lower().startswith(LATITUDE_NAMES) and
                    names[1].lower().startswith(LONGITUDE_NAMES)):
                names = ("latitude", "longitude")

            existing = [v.name for v in chain(dom.variables, dom.metas)]
            names = get_unique_names(existing, names)
            self.report_data.transf_names = tuple(names)
        self.report_data.lat_na = ReportData(*names)

        transformer = Transformer.from_crs(
            self.EPSG_CODES[self.from_idx], self.EPSG_CODES[self.to_idx])
        transformer_common = GeoTransformerCommon(transformer, *orig_coords)
        coords = (
            ContinuousVariable(
                name,
                compute_value=GeoTransformer(transformer_common, col))
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

    def send_report(self):
        data = self.report_data
        if data is None:
            return
        self.report_items(
            "",
            [("Original system", data.from_trans),
             ("Conversion to", data.to_trans),
             ("Coordinate variables", f"{data.coord_names[0]} / {data.coord_names[1]}"),
             ("Output coordinates",
              data.transf_names
              and f"{data.transf_names[0]} / {data.transf_names[1]}")])


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    data = Table.from_url("http://datasets.biolab.si/core/philadelphia-crime.csv.xz")
    WidgetPreview(OWGeoTransform).run(set_data=data)
