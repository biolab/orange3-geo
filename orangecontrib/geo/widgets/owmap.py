import numpy as np
from AnyQt.QtCore import Qt
from Orange.data import Table, ContinuousVariable
from Orange.widgets import gui, settings
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.widget import Msg
from Orange.widgets.visualize.owscatterplotgraph import OWScatterPlotBase
from Orange.widgets.visualize.utils.widget import OWDataProjectionWidget

from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.widgets.plotutils import MapMixin, MapViewBox, \
    deg2norm, MAX_LONGITUDE, MAX_LATITUDE, TILE_PROVIDERS, DEFAULT_TILE_PROVIDER


class OWScatterPlotMapGraph(MapMixin, OWScatterPlotBase):
    """
    Scatter plot that knows how to draw normalized coordinates on map. It
    additionally also manages zooming and resizing so that resolution of widget
    matches displayed images of maps.
    """
    freeze = settings.Setting(False)
    tile_provider_key = settings.Setting(DEFAULT_TILE_PROVIDER)

    def __init__(self, scatter_widget, parent):
        OWScatterPlotBase.__init__(self, scatter_widget, parent,
                                   view_box=MapViewBox)
        MapMixin.__init__(self)

    def update_density(self):
        """We decrease transparency to better see density on maps"""
        super().update_density()
        if self.density_img:
            img = self.density_img.image
            img[:, :, 3] = np.clip(img[:, :, 3] * 1.2, 0, 255)
            self.density_img.setImage(img)

    def update_coordinates(self):
        super().update_coordinates()
        if not self.freeze:
            self.update_view_range()

    def get_sizes(self):
        return super().get_sizes() * 0.8

    def _reset_view(self, x_data, y_data):
        """
        This functionality is moved to update_view_range which is called after
        update_coordinates because this is not called if there is no data and
        it also interferes with map freeze.
        """
        pass

    def update_view_range(self, match_data=True):
        """
        Update what part of tha map is shown.
        :param match_data: if True update so that all data is shown else just
        update current view
        """
        if match_data:
            # if we have no data then show the whole map
            min_x, max_x, min_y, max_y = 0, 1, 0, 1
            if self.scatterplot_item is not None:
                x_data, y_data = self.scatterplot_item.getData()
                if len(x_data):
                    min_x, max_x = np.min(x_data), np.max(x_data)
                    min_y, max_y = np.min(y_data), np.max(y_data)
        else:
            [min_x, max_x], [min_y, max_y] = self.view_box.viewRange()

        self._update_view_range(min_x, max_x, min_y, max_y, not match_data)

    def reset_button_clicked(self):
        """Reset map so that all data is displayed"""
        self.update_view_range()

    def update_tile_provider(self):
        super()._update_tile_provider(TILE_PROVIDERS[self.tile_provider_key])

    def clear(self):
        super().clear()
        if self.freeze:
            # readd map items that are cleared
            self.plot_widget.addItem(self.b_map_item)
            self.plot_widget.addItem(self.map_item)
        else:
            self.clear_map()


class OWMap(OWDataProjectionWidget):
    """
    Scatter plot visualization of coordinates data with geographic maps for
    background.
    """

    name = 'Geo Map'
    description = 'Show data points on a world map.'
    icon = "icons/GeoMap.svg"
    priority = 100

    replaces = [
        "Orange.widgets.visualize.owmap.OWMap",
    ]

    settings_version = 3

    attr_lat = settings.ContextSetting(None)
    attr_lon = settings.ContextSetting(None)

    GRAPH_CLASS = OWScatterPlotMapGraph
    graph = settings.SettingProvider(OWScatterPlotMapGraph)
    embedding_variables_names = None

    class Warning(OWDataProjectionWidget.Warning):
        missing_coords = Msg(
            "Plot cannot be displayed because '{}' or '{}' "
            "is missing for all data points")
        no_continuous_vars = Msg("Data has no continuous variables")
        no_lat_lon_vars = Msg("Data has no latitude and longitude variables.")
        out_of_range = Msg("Points with out of range latitude or longitude are not displayed.")
        no_internet = Msg("Cannot fetch map from the internet. "
                          "Displaying only cached parts.")

    class Information(OWDataProjectionWidget.Information):
        missing_coords = Msg(
            "Points with missing '{}' or '{}' are not displayed")

    def __init__(self):
        super().__init__()
        self.graph.show_internet_error.connect(self._show_internet_error)

    def _show_internet_error(self, show):
        if not self.Warning.no_internet.is_shown() and show:
            self.Warning.no_internet()
        elif self.Warning.no_internet.is_shown() and not show:
            self.Warning.no_internet.clear()

    def _add_controls(self):
        self.lat_lon_model = DomainModel(DomainModel.MIXED,
                                         valid_types=ContinuousVariable)

        lat_lon_box = gui.vBox(self.controlArea, True)
        options = dict(
            labelWidth=75, orientation=Qt.Horizontal, sendSelectedValue=True,
            valueType=str, contentsLength=14
        )

        gui.comboBox(lat_lon_box, self, 'graph.tile_provider_key', label='Map:',
                     items=list(TILE_PROVIDERS.keys()),
                     callback=self.graph.update_tile_provider, **options)

        gui.comboBox(lat_lon_box, self, 'attr_lon', label='Longitude:',
                     callback=self.setup_plot,
                     model=self.lat_lon_model, **options)

        gui.comboBox(lat_lon_box, self, 'attr_lat', label='Latitude:',
                     callback=self.setup_plot,
                     model=self.lat_lon_model, **options)

        super()._add_controls()

        gui.checkBox(
            self._plot_box, self,
            value="graph.freeze",
            label="Freeze map",
            tooltip="If checked, the map won't change position to fit new data.")

    def check_data(self):
        super().check_data()
        if self.data is not None:
            if not self.data.domain.has_continuous_attributes(True, True):
                self.Warning.no_continuous_vars()
                self.data = None

    def get_embedding(self):
        self.valid_data = None
        if self.data is None:
            return None

        lat_data = self.get_column(self.attr_lat, filter_valid=False)
        lon_data = self.get_column(self.attr_lon, filter_valid=False)
        if lat_data is None or lon_data is None:
            return None

        self.Warning.missing_coords.clear()
        self.Information.missing_coords.clear()
        self.valid_data = np.isfinite(lat_data) & np.isfinite(lon_data)
        if self.valid_data is not None and not np.all(self.valid_data):
            msg = self.Information if np.any(self.valid_data) else self.Warning
            msg.missing_coords(self.attr_lat.name, self.attr_lon.name)

        in_range = (-MAX_LONGITUDE <= lon_data) & (lon_data <= MAX_LONGITUDE) &\
                   (-MAX_LATITUDE <= lat_data) & (lat_data <= MAX_LATITUDE)
        in_range = ~np.bitwise_xor(in_range, self.valid_data)
        self.Warning.out_of_range.clear()
        if in_range.sum() != len(lon_data):
            self.Warning.out_of_range()
        if in_range.sum() == 0:
            return None
        self.valid_data &= in_range

        x, y = deg2norm(lon_data, lat_data)
        # invert y to increase from bottom to top
        y = 1 - y
        return np.vstack((x, y)).T

    def init_attr_values(self):
        super().init_attr_values()
        self.Warning.no_lat_lon_vars.clear()
        self.attr_lat, self.attr_lon = None, None
        domain = self.data.domain if self.data else None
        self.lat_lon_model.set_domain(domain)
        if self.data:
            attr_lat, attr_lon = find_lat_lon(self.data, filter_hidden=True)
            if attr_lat is None or attr_lon is None:
                # we either find both or none
                self.Warning.no_lat_lon_vars()
            else:
                self.attr_lat, self.attr_lon = attr_lat, attr_lon

    @property
    def effective_variables(self):
        return [self.attr_lat, self.attr_lon] \
            if self.attr_lat and self.attr_lon else []

    def showEvent(self, ev):
        super().showEvent(ev)
        # reset the map on show event since before that we didn't know the
        # right resolution
        self.graph.update_view_range()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # when resizing we need to constantly reset the map so that new
        # portions are drawn
        self.graph.update_view_range(match_data=False)

    @classmethod
    def migrate_settings(cls, _settings, version):
        if version < 3:
            _settings["graph"] = {}
            if "tile_provider" in _settings:
                if _settings["tile_provider"] == "Watercolor":
                    _settings["tile_provider"] = DEFAULT_TILE_PROVIDER
                _settings["graph"]["tile_provider_key"] = \
                    _settings["tile_provider"]
            if "opacity" in _settings:
                _settings["graph"]["alpha_value"] = \
                    round(_settings["opacity"] * 2.55)
            if "zoom" in _settings:
                _settings["graph"]["point_width"] = \
                    round(_settings["zoom"] * 0.02)
            if "jittering" in _settings:
                _settings["graph"]["jitter_size"] = _settings["jittering"]
            if "show_legend" in _settings:
                _settings["graph"]["show_legend"] = _settings["show_legend"]

    @classmethod
    def migrate_context(cls, context, version):
        if version < 2:
            settings.migrate_str_to_variable(context, names="lat_attr",
                                             none_placeholder="")
            settings.migrate_str_to_variable(context, names="lon_attr",
                                             none_placeholder="")
            settings.migrate_str_to_variable(context, names="class_attr",
                                             none_placeholder="(None)")

            # those settings can have two none placeholder
            attr_placeholders = [("color_attr", "(Same color)"),
                                 ("label_attr", "(No labels)"),
                                 ("shape_attr", "(Same shape)"),
                                 ("size_attr", "(Same size)")]
            for attr, place in attr_placeholders:
                if context.values[attr][0] == place:
                    context.values[attr] = ("", context.values[attr][1])

                settings.migrate_str_to_variable(context, names=attr,
                                                 none_placeholder="")
        if version < 3:
            settings.rename_setting(context, "lat_attr", "attr_lat")
            settings.rename_setting(context, "lon_attr", "attr_lon")
            settings.rename_setting(context, "color_attr", "attr_color")
            settings.rename_setting(context, "label_attr", "attr_label")
            settings.rename_setting(context, "shape_attr", "attr_shape")
            settings.rename_setting(context, "size_attr", "attr_size")


if __name__ == "__main__":
    data = Table("India_census_district_population")
    WidgetPreview(OWMap).run(data)
