import os
import logging

import numpy as np
import pandas as pd
from scipy import stats

from AnyQt.QtCore import (
    Qt, QUrl, pyqtSignal, pyqtSlot, QT_VERSION_STR,
    QObject, QTimer,
)

from Orange.misc.cache import memoize_method
from Orange.util import color_to_hex
from Orange.data import Table, TimeVariable, DiscreteVariable, ContinuousVariable
from Orange.widgets import gui, widget, settings
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.utils.webview import WebviewWidget
from Orange.widgets.utils.annotated_data import create_annotated_table, ANNOTATED_DATA_SIGNAL_NAME

from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.mapper import latlon2region, ADMIN2_COUNTRIES, get_bounding_rect


if QT_VERSION_STR <= '5.3':
    raise RuntimeError('Choropleth widget only works with Qt 5.3+')


log = logging.getLogger(__name__)


# Test that memoize_method exposes cache_clear(), avoid otherwise
# https://github.com/biolab/orange3/pull/2229
if not hasattr(memoize_method(1)(int), 'cache_clear'):
    memoize_method = lambda x: (lambda x: x)


class LeafletChoropleth(WebviewWidget):
    selectionChanged = pyqtSignal(list)

    def __init__(self, parent=None):

        class Bridge(QObject):
            @pyqtSlot()
            def fit_to_bounds(_):
                return self.fit_to_bounds()

            @pyqtSlot('QVariantList')
            def selection(_, selected):
                self.selectionChanged.emit(selected)

        super().__init__(parent,
                         bridge=Bridge(),
                         url=QUrl(self.toFileURL(
                             os.path.join(os.path.dirname(__file__), '_leaflet', 'owchoropleth.html'))))
        self._owwidget = parent
        self.bounds = None

    def fit_to_bounds(self):
        if self.bounds is None:
            return
        east, south, west, north = self.bounds
        maxzoom = 5 if self._owwidget.admin == 0 else 7
        self.evalJS('''
            map.flyToBounds([[%f, %f], [%f, %f]], {
                padding: [0,0], minZoom: 2, maxZoom: %d,
                duration: .6, easeLinearity: .4
            });''' % (north, west, south, east, maxzoom))

    def set_opacity(self, opacity):
        self.evalJS('''set_opacity(%f);''' % (opacity / 100 / 2))

    def set_quantization(self, quantization):
        self.evalJS('''set_quantization("%s");''' % (quantization[0].lower()))

    def set_color_steps(self, steps):
        self.evalJS('''set_color_steps(%d);''' % steps)

    def toggle_legend(self, visible):
        self.evalJS('''toggle_legend(%d);''' % (int(bool(visible))))

    def toggle_map_labels(self, visible):
        self.evalJS('''toggle_map_labels(%d);''' % (int(bool(visible))))

    def toggle_tooltip_details(self, visible):
        self.evalJS('''toggle_tooltip_details(%d);''' % (int(bool(visible))))

    def preset_region_selection(self, selection):
        self.evalJS('''set_region_selection(%s);''' % selection)


class OWChoropleth(widget.OWWidget):
    name = 'Choropleth Map'
    description = 'A thematic map in which areas are shaded in proportion ' \
                  'to the measurement of the statistical variable being displayed.'
    icon = "icons/Choropleth.svg"
    priority = 120

    inputs = [("Data", Table, "set_data", widget.Default)]

    outputs = [("Selected Data", Table, widget.Default),
               (ANNOTATED_DATA_SIGNAL_NAME, Table)]

    settingsHandler = settings.DomainContextHandler()

    want_main_area = True

    AGG_FUNCS = (
        'Count',
        'Count defined',
        'Sum',
        'Mean',
        'Median',
        'Mode',
        'Max',
        'Min',
        'Std',
    )
    AGG_FUNCS_TRANSFORM = {
        'Count': 'size',
        'Count defined': 'count',
        'Mode': lambda x: stats.mode(x, nan_policy='omit').mode[0],
    }
    AGG_FUNCS_DISCRETE = ('Count', 'Count defined', 'Mode')
    AGG_FUNCS_CANT_TIME = ('Count', 'Count defined', 'Sum', 'Std')

    autocommit = settings.Setting(True)
    lat_attr = settings.ContextSetting('')
    lon_attr = settings.ContextSetting('')
    attr = settings.ContextSetting('')
    agg_func = settings.ContextSetting(AGG_FUNCS[0])
    admin = settings.Setting(0)
    opacity = settings.Setting(70)
    color_steps = settings.Setting(5)
    color_quantization = settings.Setting('equidistant')
    show_labels = settings.Setting(True)
    show_legend = settings.Setting(True)
    show_details = settings.Setting(True)
    selection = settings.ContextSetting([])

    class Error(widget.OWWidget.Error):
        aggregation_discrete = widget.Msg("Only certain types of aggregation defined on categorical attributes: {}")

    class Warning(widget.OWWidget.Warning):
        logarithmic_nonpositive = widget.Msg("Logarithmic quantization requires all values > 0. Using 'equidistant' quantization instead.")

    graph_name = "map"

    def __init__(self):
        super().__init__()
        self.map = map = LeafletChoropleth(self)
        self.mainArea.layout().addWidget(map)
        self.selection = []
        self.data = None
        self.latlon = None
        self.result_min_nonpositive = False
        self._should_fit_bounds = False

        def selectionChanged(selection):
            self._indices = self.ids.isin(selection).nonzero()[0]
            self.selection = selection
            self.commit()

        map.selectionChanged.connect(selectionChanged)

        box = gui.vBox(self.controlArea, 'Aggregation')

        self._latlon_model = DomainModel(parent=self, valid_types=ContinuousVariable)
        self._combo_lat = combo = gui.comboBox(
            box, self, 'lat_attr', orientation=Qt.Horizontal,
            label='Latitude:', sendSelectedValue=True, callback=self.aggregate)
        combo.setModel(self._latlon_model)

        self._combo_lon = combo = gui.comboBox(
            box, self, 'lon_attr', orientation=Qt.Horizontal,
            label='Longitude:', sendSelectedValue=True, callback=self.aggregate)
        combo.setModel(self._latlon_model)

        self._combo_attr = combo = gui.comboBox(
            box, self, 'attr', orientation=Qt.Horizontal,
            label='Attribute:', sendSelectedValue=True, callback=self.aggregate)
        combo.setModel(DomainModel(parent=self, valid_types=(ContinuousVariable, DiscreteVariable)))

        gui.comboBox(
            box, self, 'agg_func', orientation=Qt.Horizontal, items=self.AGG_FUNCS,
            label='Aggregation:', sendSelectedValue=True, callback=self.aggregate)

        self._detail_slider = gui.hSlider(
            box, self, 'admin', None, 0, 2, 1,
            label='Administrative level:', labelFormat=' %d',
            callback=self.aggregate)

        box = gui.vBox(self.controlArea, 'Visualization')

        gui.spin(box, self, 'color_steps', 3, 15, 1, label='Color steps:',
                 callback=lambda: self.map.set_color_steps(self.color_steps))

        def _set_quantization():
            self.Warning.logarithmic_nonpositive(
                shown=(self.color_quantization.startswith('log') and
                       self.result_min_nonpositive))
            self.map.set_quantization(self.color_quantization)

        gui.comboBox(box, self, 'color_quantization', label='Color quantization:',
                     orientation=Qt.Horizontal, sendSelectedValue=True,
                     items=('equidistant', 'logarithmic', 'quantile', 'k-means'),
                     callback=_set_quantization)

        self._opacity_slider = gui.hSlider(
            box, self, 'opacity', None, 20, 100, 5,
            label='Opacity:', labelFormat=' %d%%',
            callback=lambda: self.map.set_opacity(self.opacity))

        gui.checkBox(box, self, 'show_legend', label='Show legend',
                     callback=lambda: self.map.toggle_legend(self.show_legend))
        gui.checkBox(box, self, 'show_labels', label='Show map labels',
                     callback=lambda: self.map.toggle_map_labels(self.show_labels))
        gui.checkBox(box, self, 'show_details', label='Show region details in tooltip',
                     callback=lambda: self.map.toggle_tooltip_details(self.show_details))

        gui.rubber(self.controlArea)
        gui.auto_commit(self.controlArea, self, 'autocommit', 'Send Selection')

        self.map.toggle_legend(self.show_legend)
        self.map.toggle_map_labels(self.show_labels)
        self.map.toggle_tooltip_details(self.show_details)
        self.map.set_quantization(self.color_quantization)
        self.map.set_color_steps(self.color_steps)
        self.map.set_opacity(self.opacity)

    def __del__(self):
        self.map = None

    def commit(self):
        self.send('Selected Data',
                  self.data[self._indices] if self.data is not None and self.selection else None)
        self.send(ANNOTATED_DATA_SIGNAL_NAME,
                  create_annotated_table(self.data, self._indices))

    def set_data(self, data):
        self.data = data

        self.closeContext()

        self.clear()
        
        if data is None:
            return

        self._combo_attr.model().set_domain(data.domain)
        self._latlon_model.set_domain(data.domain)

        lat, lon = find_lat_lon(data)
        if lat or lon:
            self._combo_lat.setCurrentIndex(-1 if lat is None else self._latlon_model.indexOf(lat))
            self._combo_lon.setCurrentIndex(-1 if lat is None else self._latlon_model.indexOf(lon))
            self.lat_attr = lat.name if lat else None
            self.lon_attr = lon.name if lon else None
            if lat and lon:
                self.latlon = np.c_[self.data.get_column_view(self.lat_attr)[0],
                                    self.data.get_column_view(self.lon_attr)[0]]

        if data.domain.class_var:
            self.attr = data.domain.class_var.name
        else:
            self.attr = self._combo_attr.itemText(0)

        self.openContext(data)

        if self.selection:
            self.map.preset_region_selection(self.selection)
        self.aggregate()

        self.map.set_opacity(self.opacity)

        if self.isVisible():
            self.map.fit_to_bounds()
        else:
            self._should_fit_bounds = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._should_fit_bounds:
            QTimer.singleShot(500, self.map.fit_to_bounds)
            self._should_fit_bounds = False

    def aggregate(self):
        if self.latlon is None or self.attr not in self.data.domain:
            self.clear(caches=False)
            return

        attr = self.data.domain[self.attr]

        if attr.is_discrete and self.agg_func not in self.AGG_FUNCS_DISCRETE:
            self.Error.aggregation_discrete(', '.join(map(str.lower, self.AGG_FUNCS_DISCRETE)))
            self.Warning.logarithmic_nonpositive.clear()
            self.clear(caches=False)
            return
        else:
            self.Error.aggregation_discrete.clear()

        try:
            regions, adm0, result, self.map.bounds = \
                self.get_grouped(self.lat_attr, self.lon_attr, self.admin, self.attr, self.agg_func)
        except ValueError:
            # This might happen if widget scheme File→Choropleth, and
            # some attr is selected in choropleth, and then the same attr
            # is set to string attr in File and dataset reloaded.
            # Our "dataflow" arch can suck my balls
            return

        # Only show discrete values that are contained in aggregated results
        discrete_values = []
        if attr.is_discrete and not self.agg_func.startswith('Count'):
            subset = sorted(result.drop_duplicates().dropna().astype(int))
            discrete_values = np.array(attr.values)[subset].tolist()
            discrete_colors = np.array(attr.colors)[subset].tolist()
            result.replace(subset, list(range(len(subset))), inplace=True)

        self.result_min_nonpositive = attr.is_continuous and result.min() <= 0
        force_quantization = self.color_quantization.startswith('log') and self.result_min_nonpositive
        self.Warning.logarithmic_nonpositive(shown=force_quantization)

        repr_time = isinstance(attr, TimeVariable) and self.agg_func not in self.AGG_FUNCS_CANT_TIME

        self.map.exposeObject(
            'results',
            dict(discrete=discrete_values,
                 colors=[color_to_hex(i)
                         for i in (discrete_colors if discrete_values else
                                   ((0, 0, 255), (255, 255, 0)) if attr.is_discrete else
                                   attr.colors[:-1])],  # ???
                 regions=list(adm0),
                 attr=attr.name,
                 have_nonpositive=self.result_min_nonpositive or bool(discrete_values),
                 values=result.to_dict(),
                 repr_vals=result.map(attr.repr_val).to_dict() if repr_time else {},
                 minmax=([result.min(), result.max()] if attr.is_discrete and not discrete_values else
                         [attr.repr_val(result.min()), attr.repr_val(result.max())] if repr_time or not discrete_values else
                         [])))

        self.map.evalJS('replot();')

    @memoize_method(3)
    def get_regions(self, lat_attr, lon_attr, admin):
        latlon = np.c_[self.data.get_column_view(lat_attr)[0],
                       self.data.get_column_view(lon_attr)[0]]
        regions = latlon2region(latlon, admin)
        adm0 = ({'0'} if admin == 0 else
                {'1-' + a3 for a3 in (i.get('adm0_a3') for i in regions) if a3} if admin == 1 else
                {('2-' if a3 in ADMIN2_COUNTRIES else '1-') + a3
                 for a3 in (i.get('adm0_a3') for i in regions) if a3})
        ids = [i.get('_id') for i in regions]
        self.ids = pd.Series(ids)
        regions = set(ids) - {None}
        bounds = get_bounding_rect(regions) if regions else None
        return regions, ids, adm0, bounds

    @memoize_method(6)
    def get_grouped(self, lat_attr, lon_attr, admin, attr, agg_func):
        log.debug('Grouping %s(%s) by (%s, %s; admin%d)',
                  agg_func, attr, lat_attr,  lon_attr, admin)
        regions, ids, adm0, bounds = self.get_regions(lat_attr, lon_attr, admin)
        attr = self.data.domain[attr]
        result = pd.Series(self.data.get_column_view(attr)[0], dtype=float)\
            .groupby(ids)\
            .agg(self.AGG_FUNCS_TRANSFORM.get(agg_func, agg_func.lower()))
        return regions, adm0, result, bounds

    def clear(self, caches=True):
        if caches:
            try:
                self.get_regions.cache_clear()
                self.get_grouped.cache_clear()
            except AttributeError:
                pass  # back-compat https://github.com/biolab/orange3/pull/2229
        self.selection = []
        self.map.exposeObject('results', {})
        self.map.evalJS('replot();')


def test_main():
    from AnyQt.QtWidgets import QApplication
    a = QApplication([])

    ow = OWChoropleth()
    ow.show()
    ow.raise_()
    data = Table('philadelphia-crime')
    ow.set_data(data)

    a.exec()
    ow.saveSettings()

if __name__ == "__main__":
    test_main()
