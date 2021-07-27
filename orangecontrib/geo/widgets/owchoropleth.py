import sys
import itertools
from xml.sax.saxutils import escape
from typing import List, NamedTuple, Optional, Union, Callable
from math import floor, log10
from functools import reduce

from AnyQt.QtCore import Qt, QObject, QSize, QRectF, pyqtSignal as Signal, \
    QPointF
from AnyQt.QtGui import QPen, QBrush, QColor, QPolygonF, QPainter, QStaticText
from AnyQt.QtWidgets import QApplication, QToolTip, QGraphicsTextItem, \
    QGraphicsRectItem

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform
import pyqtgraph as pg
from pyqtgraph.graphicsItems.LegendItem import ItemSample
import numpy as np
import pandas as pd
from scipy import stats

from Orange.data import Table, Domain, ContinuousVariable, DiscreteVariable
from Orange.data.util import array_equal
from Orange.data.sql.table import SqlTable
from Orange.misc.cache import memoize_method
from Orange.statistics.util import bincount
from Orange.preprocess.discretize import decimal_binnings, BinDefinition,\
    time_binnings
from Orange.widgets import gui
from Orange.widgets.utils.annotated_data import create_annotated_table, \
    ANNOTATED_DATA_SIGNAL_NAME, create_groups_table
from Orange.widgets.utils.plot import OWPlotGUI
from Orange.widgets.utils.sql import check_sql_input
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.utils.colorpalettes import BinnedContinuousPalette, \
    DefaultContinuousPalette, LimitedDiscretePalette
from Orange.widgets.widget import Input, OWWidget, Msg, Output
from Orange.widgets.visualize.owscatterplotgraph import LegendItem, \
    SymbolItemSample
from Orange.widgets.visualize.utils.plotutils import HelpEventDelegate
from Orange.widgets.visualize.utils.widget import MAX_COLORS
from Orange.widgets.settings import Setting, SettingProvider, rename_setting, \
    DomainContextHandler, ContextSetting, migrate_str_to_variable

from orangecontrib.geo.utils import find_lat_lon
from orangecontrib.geo.mapper import latlon2region, get_shape
from orangecontrib.geo.widgets.plotutils import MapMixin, MapViewBox, \
    _TileProvider, deg2norm


CHOROPLETH_TILE_PROVIDER = _TileProvider(
    url="http://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    attribution='&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
    size=256,
    max_zoom=19
)

_ChoroplethRegion = NamedTuple(
    "_ChoroplethRegion", [
        ("id", str),
        ("qpolys", List[QPolygonF]),
        ("info", dict),
    ]
)


class BinningPaletteItemSample(ItemSample):
    """Legend ItemSample item for discretized colors"""

    def __init__(self, palette: BinnedContinuousPalette,
                 binning: BinDefinition, label_formatter=None):
        """
        :param palette: palette used for showing continuous values
        :param binning: binning used to discretize colors
        """
        super().__init__(None)

        self.palette = palette
        self.binning = binning
        if label_formatter is None:
            if binning.width is not None:
                width = binning.width
            else:
                width = min([t2 - t1
                             for t1, t2 in zip(binning.thresholds,
                                               binning.thresholds[1:])])
            decimals = max(-floor(log10(width)), 0)
            label_formatter = "{{:.{}f}}".format(decimals).format
        cuts = [label_formatter(l) for l in self.binning.thresholds]
        self.labels = [QStaticText("{} - {}".format(fr, to))
                       for fr, to in zip(cuts, cuts[1:])]
        font = self.font()
        font.setPixelSize(11)
        for label in self.labels:
            label.prepare(font=font)
        self.text_width = max(label.size().width() for label in self.labels)

    def boundingRect(self):
        return QRectF(0, 0, 40 + self.text_width, 20 + self.binning.nbins * 15)

    def paint(self, p, *args):
        p.setRenderHint(p.Antialiasing)
        p.translate(5, 5)
        font = p.font()
        font.setPixelSize(11)
        p.setFont(font)
        colors = self.palette.qcolors
        for i, color, label in zip(itertools.count(), colors, self.labels):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawRect(0, i * 15, 15, 15)
            p.setPen(QPen(Qt.black))
            p.drawStaticText(20, i * 15 + 1, label)


class ChoroplethItem(pg.GraphicsObject):
    """
    GraphicsObject that represents regions.
    Regions can consist of multiple disjoint polygons.
    """

    itemClicked = Signal(str)  # send region id

    def __init__(self, region: _ChoroplethRegion, pen: QPen, brush: QBrush):
        pg.GraphicsObject.__init__(self)
        self.region = region
        self.agg_value = None
        self.pen = pen
        self.brush = brush

        self._region_info = self._get_region_info(self.region)
        self._bounding_rect = reduce(
            lambda br1, br2: br1.united(br2),
            (qpoly.boundingRect() for qpoly in self.region.qpolys)
        )

    @staticmethod
    def _get_region_info(region: _ChoroplethRegion):
        region_text = "<br/>".join(escape('{} = {}'.format(k, v))
                                   for k, v in region.info.items())
        return "<b>Region info:</b><br/>" + region_text

    def tooltip(self):
        return f"<b>Agg. value = {self.agg_value}</b><hr/>{self._region_info}"

    def setPen(self, pen):
        self.pen = pen
        self.update()

    def setBrush(self, brush):
        self.brush = brush
        self.update()

    def paint(self, p: QPainter, *args):
        p.setBrush(self.brush)
        p.setPen(self.pen)
        for qpoly in self.region.qpolys:
            p.drawPolygon(qpoly)

    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def contains(self, point: QPointF) -> bool:
        return any(qpoly.containsPoint(point, Qt.OddEvenFill)
                   for qpoly in self.region.qpolys)

    def intersects(self, poly: QPolygonF) -> bool:
        return any(not qpoly.intersected(poly).isEmpty()
                   for qpoly in self.region.qpolys)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.contains(ev.pos()):
            self.itemClicked.emit(self.region.id)
            ev.accept()
        else:
            ev.ignore()


class OWChoroplethPlotGraph(gui.OWComponent, QObject):
    """
    Main class containing functionality for piloting `ChoroplethItem`.
    It is wary similar to `OWScatterPlotBase`. In fact some functionality
    is directly copied from there.
    """

    alpha_value = Setting(128)
    show_legend = Setting(True)

    def __init__(self, widget, parent=None):
        QObject.__init__(self)
        gui.OWComponent.__init__(self, widget)

        self.view_box = MapViewBox(self)
        self.plot_widget = pg.PlotWidget(viewBox=self.view_box, parent=parent,
                                         background="w")
        self.plot_widget.hideAxis("left")
        self.plot_widget.hideAxis("bottom")
        self.plot_widget.getPlotItem().buttonsHidden = True
        self.plot_widget.setAntialiasing(True)
        self.plot_widget.sizeHint = lambda: QSize(500, 500)

        self.master = widget  # type: OWChoropleth
        self._create_drag_tooltip(self.plot_widget.scene())

        self.choropleth_items = []  # type: List[ChoroplethItem]

        self.n_ids = 0
        self.selection = None  # np.ndarray

        self.palette = None
        self.color_legend = self._create_legend(((1, 1), (1, 1)))
        self.update_legend_visibility()

        self._tooltip_delegate = HelpEventDelegate(self.help_event)
        self.plot_widget.scene().installEventFilter(self._tooltip_delegate)

    def _create_legend(self, anchor):
        legend = LegendItem()
        legend.setParentItem(self.plot_widget.getViewBox())
        legend.restoreAnchor(anchor)
        return legend

    def _create_drag_tooltip(self, scene):
        tip_parts = [
            (Qt.ShiftModifier, "Shift: Add group"),
            (Qt.ShiftModifier + Qt.ControlModifier,
             "Shift-{}: Append to group".
             format("Cmd" if sys.platform == "darwin" else "Ctrl")),
            (Qt.AltModifier, "Alt: Remove")
        ]
        all_parts = ", ".join(part for _, part in tip_parts)
        self.tiptexts = {
            int(modifier): all_parts.replace(part, "<b>{}</b>".format(part))
            for modifier, part in tip_parts
        }
        self.tiptexts[0] = all_parts

        self.tip_textitem = text = QGraphicsTextItem()
        # Set to the longest text
        text.setHtml(self.tiptexts[Qt.ShiftModifier + Qt.ControlModifier])
        text.setPos(4, 2)
        r = text.boundingRect()
        rect = QGraphicsRectItem(0, 0, r.width() + 8, r.height() + 4)
        rect.setBrush(QColor(224, 224, 224, 212))
        rect.setPen(QPen(Qt.NoPen))
        self.update_tooltip()

        scene.drag_tooltip = scene.createItemGroup([rect, text])
        scene.drag_tooltip.hide()

    def update_tooltip(self, modifiers=Qt.NoModifier):
        modifiers &= Qt.ShiftModifier + Qt.ControlModifier + Qt.AltModifier
        text = self.tiptexts.get(int(modifiers), self.tiptexts[0])
        self.tip_textitem.setHtml(text)

    def clear(self):
        self.plot_widget.clear()
        self.color_legend.clear()
        self.update_legend_visibility()
        self.choropleth_items = []
        self.n_ids = 0
        self.selection = None

    def reset_graph(self):
        """Reset plot on data change."""
        self.clear()
        self.selection = None
        self.update_choropleth()
        self.update_colors()

    def update_choropleth(self):
        """Draw new polygons."""
        pen = self._make_pen(QColor(Qt.white), 1)
        brush = QBrush(Qt.NoBrush)
        regions = self.master.get_choropleth_regions()
        for region in regions:
            choropleth_item = ChoroplethItem(region, pen=pen, brush=brush)
            choropleth_item.itemClicked.connect(self.select_by_id)
            self.plot_widget.addItem(choropleth_item)
            self.choropleth_items.append(choropleth_item)

        if self.choropleth_items:
            self.n_ids = len(self.master.region_ids)

    def update_colors(self):
        """Update agg_value and inner color of existing polygons."""
        if not self.choropleth_items:
            return

        agg_data = self.master.get_agg_data()
        brushes = self.get_colors()
        for ci, d, b in zip(self.choropleth_items, agg_data, brushes):
            ci.agg_value = self.master.format_agg_val(d)
            ci.setBrush(b)
        self.update_legends()

    def get_colors(self):
        self.palette = self.master.get_palette()
        c_data = self.master.get_color_data()
        if c_data is None:
            self.palette = None
            return []
        elif self.master.is_mode():
            return self._get_discrete_colors(c_data)
        else:
            return self._get_continuous_colors(c_data)

    def _get_continuous_colors(self, c_data):
        palette = self.master.get_palette()
        bins = self.master.get_binning().thresholds
        self.palette = BinnedContinuousPalette.from_palette(palette, bins)
        rgb = self.palette.values_to_colors(c_data)
        rgba = np.hstack(
            [rgb, np.full((len(rgb), 1), self.alpha_value, dtype=np.ubyte)])

        return [QBrush(QColor(*col)) for col in rgba]

    def _get_discrete_colors(self, c_data):
        self.palette = self.master.get_palette()
        c_data = c_data.copy()
        c_data[np.isnan(c_data)] = len(self.palette)
        c_data = c_data.astype(int)
        colors = self.palette.qcolors_w_nan
        for col in colors:
            col.setAlpha(self.alpha_value)
        brushes = np.array([QBrush(col) for col in colors])
        return brushes[c_data]

    def update_legends(self):
        color_labels = self.master.get_color_labels()
        self.color_legend.clear()
        if self.master.is_mode():
            self._update_color_legend(color_labels)
        else:
            self._update_continuous_color_legend(color_labels)
        self.update_legend_visibility()

    def _update_continuous_color_legend(self, label_formatter):
        label = BinningPaletteItemSample(self.palette,
                                         self.master.get_binning(),
                                         label_formatter)
        self.color_legend.addItem(label, "")
        self.color_legend.setGeometry(label.boundingRect())

    def _update_color_legend(self, labels):
        symbols = ['o' for _ in range(len(labels))]
        colors = self.palette.values_to_colors(np.arange(len(labels)))
        for color, label, symbol in zip(colors, labels, symbols):
            color = QColor(*color)
            pen = self._make_pen(color.darker(120), 1.5)
            color.setAlpha(self.alpha_value)
            brush = QBrush(color)
            sis = SymbolItemSample(pen=pen, brush=brush, size=10, symbol=symbol)
            self.color_legend.addItem(sis, escape(label))

    def update_legend_visibility(self):
        self.color_legend.setVisible(
            self.show_legend and bool(self.color_legend.items))

    def update_selection_colors(self):
        """
        Update color of selected regions.
        """
        pens = self.get_colors_sel()
        for ci, pen in zip(self.choropleth_items, pens):
            ci.setPen(pen)

    def get_colors_sel(self):
        white_pen = self._make_pen(QColor(Qt.white), 1)
        if self.selection is None:
            pen = [white_pen] * self.n_ids
        else:
            sels = np.max(self.selection)
            if sels == 1:
                orange_pen = self._make_pen(QColor(255, 190, 0, 255), 3)
                pen = np.where(self.selection, orange_pen, white_pen)
            else:
                palette = LimitedDiscretePalette(number_of_colors=sels + 1)
                pens = [white_pen] + [self._make_pen(palette[i], 3)
                                      for i in range(sels)]
                pen = np.choose(self.selection, pens)
        return pen

    @staticmethod
    def _make_pen(color, width):
        p = QPen(color, width)
        p.setCosmetic(True)
        return p

    def zoom_button_clicked(self):
        self.plot_widget.getViewBox().setMouseMode(
            self.plot_widget.getViewBox().RectMode)

    def pan_button_clicked(self):
        self.plot_widget.getViewBox().setMouseMode(
            self.plot_widget.getViewBox().PanMode)

    def select_button_clicked(self):
        self.plot_widget.getViewBox().setMouseMode(
            self.plot_widget.getViewBox().RectMode)

    def select_by_id(self, region_id):
        """
        This is called by a `ChoroplethItem` on click.
        The selection is then based on the corresponding region.
        """
        indices = np.where(self.master.region_ids == region_id)[0]
        self.select_by_indices(indices)

    def select_by_rectangle(self, rect: QRectF):
        """
        Find regions that intersect with selected rectangle.
        """
        poly_rect = QPolygonF(rect)
        indices = set()
        for ci in self.choropleth_items:
            if ci.intersects(poly_rect):
                indices.add(np.where(self.master.region_ids == ci.region.id)[0][0])
        if indices:
            self.select_by_indices(np.array(list(indices)))

    def unselect_all(self):
        if self.selection is not None:
            self.selection = None
            self.update_selection_colors()
            self.master.selection_changed()

    def select_by_indices(self, indices):
        if self.selection is None:
            self.selection = np.zeros(self.n_ids, dtype=np.uint8)
        keys = QApplication.keyboardModifiers()
        if keys & Qt.AltModifier:
            self.selection_remove(indices)
        elif keys & Qt.ShiftModifier and keys & Qt.ControlModifier:
            self.selection_append(indices)
        elif keys & Qt.ShiftModifier:
            self.selection_new_group(indices)
        else:
            self.selection_select(indices)

    def selection_select(self, indices):
        self.selection = np.zeros(self.n_ids, dtype=np.uint8)
        self.selection[indices] = 1
        self._update_after_selection()

    def selection_append(self, indices):
        self.selection[indices] = np.max(self.selection)
        self._update_after_selection()

    def selection_new_group(self, indices):
        self.selection[indices] = np.max(self.selection) + 1
        self._update_after_selection()

    def selection_remove(self, indices):
        self.selection[indices] = 0
        self._update_after_selection()

    def _update_after_selection(self):
        self._compress_indices()
        self.update_selection_colors()
        self.master.selection_changed()

    def _compress_indices(self):
        indices = sorted(set(self.selection) | {0})
        if len(indices) == max(indices) + 1:
            return
        mapping = np.zeros((max(indices) + 1,), dtype=int)
        for i, ind in enumerate(indices):
            mapping[ind] = i
        self.selection = mapping[self.selection]

    def get_selection(self):
        if self.selection is None:
            return np.zeros(self.n_ids, dtype=np.uint8)
        else:
            return self.selection

    def help_event(self, event):
        """Tooltip"""
        if not self.choropleth_items:
            return False
        act_pos = self.choropleth_items[0].mapFromScene(event.scenePos())
        ci = next((ci for ci in self.choropleth_items
                   if ci.contains(act_pos)), None)
        if ci is not None:
            QToolTip.showText(event.screenPos(), ci.tooltip(),
                              widget=self.plot_widget)
            return True
        else:
            return False


class OWChoroplethPlotMapGraph(MapMixin, OWChoroplethPlotGraph):
    """
    This just adds maps as background.
    """

    def __init__(self, widget, parent):
        OWChoroplethPlotGraph.__init__(self, widget, parent)
        MapMixin.__init__(self)
        self._update_tile_provider(CHOROPLETH_TILE_PROVIDER)

    def update_view_range(self, match_data=True):
        if match_data:
            min_x, max_x, min_y, max_y = 0, 1, 0, 1
            if self.choropleth_items:
                # find bounding rect off all ChoroplethItems
                rect = self.choropleth_items[0].boundingRect()
                for ci in self.choropleth_items[1:]:
                    rect = rect.united(ci.boundingRect())
                min_x, min_y = rect.x(), rect.y()
                max_x, max_y = rect.x() + rect.width(), rect.y() + rect.height()
        else:
            [min_x, max_x], [min_y, max_y] = self.view_box.viewRange()

        self._update_view_range(min_x, max_x, min_y, max_y, not match_data)

    def clear(self):
        super().clear()
        self.clear_map()

    def reset_button_clicked(self):
        """Reset map so that all items are displayed."""
        self.update_view_range()

    def update_choropleth(self):
        """When redrawing polygons update view."""
        super().update_choropleth()
        self.update_view_range()


AggDesc = NamedTuple("AggDesc", [("transform", Union[str, Callable]),
                                 ("disc", bool), ("time", bool)])

AGG_FUNCS = {
    'Count': AggDesc("size", True, True),
    'Count defined': AggDesc("count", True, True),
    'Sum': AggDesc("sum", False, False),
    'Mean': AggDesc("mean", False, True),
    'Median': AggDesc("median", False, True),
    'Mode': AggDesc(lambda x: stats.mode(x, nan_policy='omit').mode[0],
                    True, True),
    'Maximal': AggDesc("max", False, True),
    'Minimal': AggDesc("min", False, True),
    'Std.': AggDesc("std", False, False)
}

DEFAULT_AGG_FUNC = list(AGG_FUNCS)[0]


class OWChoropleth(OWWidget):
    """
    This is to `OWDataProjectionWidget` what
    `OWChoroplethPlotGraph` is to `OWScatterPlotBase`.
    """

    name = 'Choropleth Map'
    description = 'A thematic map in which areas are shaded in proportion ' \
                  'to the measurement of the statistical variable being displayed.'
    icon = "icons/Choropleth.svg"
    priority = 120

    class Inputs:
        data = Input("Data", Table, default=True)

    class Outputs:
        selected_data = Output("Selected Data", Table, default=True)
        annotated_data = Output(ANNOTATED_DATA_SIGNAL_NAME, Table)

    settings_version = 2
    settingsHandler = DomainContextHandler()
    selection = Setting(None, schema_only=True)
    auto_commit = Setting(True)

    attr_lat = ContextSetting(None)
    attr_lon = ContextSetting(None)

    agg_attr = ContextSetting(None)
    agg_func = ContextSetting(DEFAULT_AGG_FUNC)
    admin_level = Setting(0)
    binning_index = Setting(0)

    GRAPH_CLASS = OWChoroplethPlotMapGraph
    graph = SettingProvider(OWChoroplethPlotMapGraph)
    graph_name = "graph.plot_widget.plotItem"

    input_changed = Signal(object)
    output_changed = Signal(object)

    class Error(OWWidget.Error):
        no_lat_lon_vars = Msg("Data has no latitude and longitude variables.")

    class Warning(OWWidget.Warning):
        no_region = Msg("{} points are not in any region.")

    def __init__(self):
        super().__init__()
        self.data = None
        self.data_ids = None  # type: Optional[np.ndarray]

        self.agg_data = None  # type: Optional[np.ndarray]
        self.region_ids = None  # type: Optional[np.ndarray]

        self.choropleth_regions = []
        self.binnings = []

        self.setup_gui()

    def setup_gui(self):
        self._add_graph()
        self._add_controls()
        self.input_changed.emit(None)
        self.output_changed.emit(None)

    def _add_graph(self):
        box = gui.vBox(self.mainArea, True, margin=0)
        self.graph = self.GRAPH_CLASS(self, box)
        box.layout().addWidget(self.graph.plot_widget)

    def _add_controls(self):
        options = dict(
            labelWidth=75, orientation=Qt.Horizontal, sendSelectedValue=True,
            contentsLength=14
        )

        lat_lon_box = gui.vBox(self.controlArea, True)
        self.lat_lon_model = DomainModel(DomainModel.MIXED,
                                         valid_types=(ContinuousVariable,))
        gui.comboBox(lat_lon_box, self, 'attr_lat', label='Latitude:',
                     callback=self.setup_plot, model=self.lat_lon_model,
                     **options, searchable=True)

        gui.comboBox(lat_lon_box, self, 'attr_lon', label='Longitude:',
                     callback=self.setup_plot, model=self.lat_lon_model,
                     **options, searchable=True)

        agg_box = gui.vBox(self.controlArea, True)
        self.agg_attr_model = DomainModel(valid_types=(ContinuousVariable,
                                                       DiscreteVariable))
        gui.comboBox(agg_box, self, 'agg_attr', label='Attribute:',
                     callback=self.update_agg, model=self.agg_attr_model,
                     **options, searchable=True)

        self.agg_func_combo = gui.comboBox(agg_box, self, 'agg_func',
                                           label='Agg.:',
                                           items=[DEFAULT_AGG_FUNC],
                                           callback=self.graph.update_colors,
                                           **options)

        a_slider = gui.hSlider(agg_box, self, 'admin_level', minValue=0,
                               maxValue=2, step=1, label='Detail:',
                               createLabel=False, callback=self.setup_plot)
        a_slider.setFixedWidth(176)

        visualization_box = gui.vBox(self.controlArea, True)
        b_slider = gui.hSlider(visualization_box, self, "binning_index",
                               label="Bin width:", minValue=0,
                               maxValue=max(1, len(self.binnings) - 1),
                               createLabel=False,
                               callback=self.graph.update_colors)
        b_slider.setFixedWidth(176)

        av_slider = gui.hSlider(visualization_box, self, "graph.alpha_value",
                                minValue=0, maxValue=255, step=10,
                                label="Opacity:", createLabel=False,
                                callback=self.graph.update_colors)
        av_slider.setFixedWidth(176)

        gui.checkBox(visualization_box, self, "graph.show_legend",
                     "Show legend",
                     callback=self.graph.update_legend_visibility)

        self.controlArea.layout().addStretch(100)

        plot_gui = OWPlotGUI(self)
        plot_gui.box_zoom_select(self.controlArea)
        gui.auto_send(self.controlArea, self, "auto_commit")

    @property
    def effective_variables(self):
        return [self.attr_lat, self.attr_lon] \
            if self.attr_lat and self.attr_lon else []

    @property
    def effective_data(self):
        eff_var = self.effective_variables
        if eff_var and self.attr_lat.name == self.attr_lon.name:
            eff_var = [self.attr_lat]
        return self.data.transform(Domain(eff_var))

    # Input
    @Inputs.data
    @check_sql_input
    def set_data(self, data):
        data_existed = self.data is not None
        effective_data = self.effective_data if data_existed else None

        self.closeContext()
        self.data = data
        self.Warning.no_region.clear()
        self.Error.no_lat_lon_vars.clear()
        self.agg_func = DEFAULT_AGG_FUNC
        self.check_data()
        self.init_attr_values()
        self.openContext(self.data)

        if not (data_existed and self.data is not None and
                array_equal(effective_data.X, self.effective_data.X)):
            self.clear(cache=True)
            self.input_changed.emit(data)
            self.setup_plot()
        self.update_agg()
        self.apply_selection()
        self.unconditional_commit()

    def check_data(self):
        if self.data is not None and (len(self.data) == 0 or
                                      len(self.data.domain.variables) == 0):
            self.data = None

    def init_attr_values(self):
        lat, lon = None, None
        if self.data is not None:
            lat, lon = find_lat_lon(self.data, filter_hidden=True)
            if lat is None or lon is None:
                # we either find both or we don't have valid data
                self.Error.no_lat_lon_vars()
                self.data = None
                lat, lon = None, None

        domain = self.data.domain if self.data is not None else None
        self.lat_lon_model.set_domain(domain)
        self.agg_attr_model.set_domain(domain)
        self.agg_attr = domain.class_var if domain is not None else None
        self.attr_lat, self.attr_lon = lat, lon

    def update_agg(self):
        current_agg = self.agg_func
        self.agg_func_combo.clear()

        if self.agg_attr is not None:
            new_aggs = list(AGG_FUNCS)
            if self.agg_attr.is_discrete:
                new_aggs = [agg for agg in AGG_FUNCS if AGG_FUNCS[agg].disc]
            elif self.agg_attr.is_time:
                new_aggs = [agg for agg in AGG_FUNCS if AGG_FUNCS[agg].time]
        else:
            new_aggs = [DEFAULT_AGG_FUNC]

        self.agg_func_combo.addItems(new_aggs)

        if current_agg in new_aggs:
            self.agg_func = current_agg
        else:
            self.agg_func = DEFAULT_AGG_FUNC

        self.graph.update_colors()

    def setup_plot(self):
        self.controls.binning_index.setEnabled(not self.is_mode())
        self.clear()
        self.graph.reset_graph()

    def apply_selection(self):
        if self.data is not None and self.selection is not None:
            index_group = np.array(self.selection).T
            selection = np.zeros(self.graph.n_ids, dtype=np.uint8)
            selection[index_group[0]] = index_group[1]
            self.graph.selection = selection
            self.graph.update_selection_colors()

    def selection_changed(self):
        sel = None if self.data and isinstance(self.data, SqlTable) \
            else self.graph.selection
        self.selection = [(i, x) for i, x in enumerate(sel) if x] \
            if sel is not None else None
        self.commit()

    def commit(self):
        self.send_data()

    def send_data(self):
        data, graph_sel = self.data, self.graph.get_selection()
        selected_data, ann_data = None, None
        if data:
            group_sel = np.zeros(len(data), dtype=int)

            if len(graph_sel):
                # we get selection by region ids so we have to map it to points
                for id, s in zip(self.region_ids, graph_sel):
                    if s == 0:
                        continue
                    id_indices = np.where(self.data_ids == id)[0]
                    group_sel[id_indices] = s
            else:
                graph_sel = [0]

            if np.sum(graph_sel) > 0:
                selected_data = create_groups_table(data, group_sel, False, "Group")

            if data is not None:
                if np.max(graph_sel) > 1:
                    ann_data = create_groups_table(data, group_sel)
                else:
                    ann_data = create_annotated_table(data, group_sel.astype(bool))

        self.output_changed.emit(selected_data)
        self.Outputs.selected_data.send(selected_data)
        self.Outputs.annotated_data.send(ann_data)

    def recompute_binnings(self):
        if self.is_mode():
            return

        if self.is_time():
            self.binnings = time_binnings(self.agg_data,
                                          min_bins=3, max_bins=15)
        else:
            self.binnings = decimal_binnings(self.agg_data,
                                             min_bins=3, max_bins=15)

        max_bins = len(self.binnings) - 1
        self.controls.binning_index.setMaximum(max_bins)
        self.binning_index = min(max_bins, self.binning_index)

    def get_binning(self) -> BinDefinition:
        return self.binnings[self.binning_index]

    def get_palette(self):
        if self.agg_func in ('Count', 'Count defined'):
            return DefaultContinuousPalette
        elif self.is_mode():
            return LimitedDiscretePalette(MAX_COLORS)
        else:
            return self.agg_attr.palette

    def get_color_data(self):
        return self.get_reduced_agg_data()

    def get_color_labels(self):
        if self.is_mode():
            return self.get_reduced_agg_data(return_labels=True)
        elif self.is_time():
            return self.agg_attr.str_val

    def get_reduced_agg_data(self, return_labels=False):
        """
        This returns agg data or its labels. It also merges infrequent data.
        """
        needs_merging = self.is_mode() \
                        and len(self.agg_attr.values) >= MAX_COLORS
        if return_labels and not needs_merging:
            return self.agg_attr.values

        if not needs_merging:
            return self.agg_data

        dist = bincount(self.agg_data, max_val=len(self.agg_attr.values) - 1)[0]
        infrequent = np.zeros(len(self.agg_attr.values), dtype=bool)
        infrequent[np.argsort(dist)[:-(MAX_COLORS - 1)]] = True
        if return_labels:
            return [value for value, infreq in zip(self.agg_attr.values, infrequent)
                    if not infreq] + ["Other"]
        else:
            result = self.agg_data.copy()
            freq_vals = [i for i, f in enumerate(infrequent) if not f]
            for i, infreq in enumerate(infrequent):
                if infreq:
                    result[self.agg_data == i] = MAX_COLORS - 1
                else:
                    result[self.agg_data == i] = freq_vals.index(i)
            return result

    def is_mode(self):
        return self.agg_attr is not None and \
               self.agg_attr.is_discrete and \
               self.agg_func == 'Mode'

    def is_time(self):
        return self.agg_attr is not None and \
               self.agg_attr.is_time and \
               self.agg_func not in ('Count', 'Count defined')

    @memoize_method(3)
    def get_regions(self, lat_attr, lon_attr, admin):
        """
        Map points to regions and get regions information.
        Returns:
            ndarray of ids corresponding to points,
            dict of region ids matched to their additional info,
            dict of region ids matched to their polygon
        """
        latlon = np.c_[self.data.get_column_view(lat_attr)[0],
                       self.data.get_column_view(lon_attr)[0]]
        region_info = latlon2region(latlon, admin)
        ids = np.array([region.get('_id') for region in region_info])
        region_info = {info.get('_id'): info for info in region_info}

        self.data_ids = np.array(ids)
        no_region = np.sum(self.data_ids == None)
        if no_region:
            self.Warning.no_region(no_region)

        unique_ids = list(set(ids) - {None})
        polygons = {_id: poly
                    for _id, poly in zip(unique_ids, get_shape(unique_ids))}
        return ids, region_info, polygons

    def get_grouped(self, lat_attr, lon_attr, admin, attr, agg_func):
        """
        Get aggregation value for points grouped by regions.
        Returns:
            Series of aggregated values
        """
        if attr is not None:
            data = self.data.get_column_view(attr)[0]
        else:
            data = np.ones(len(self.data))

        ids, _, _ = self.get_regions(lat_attr, lon_attr, admin)
        result = pd.Series(data, dtype=float)\
            .groupby(ids)\
            .agg(AGG_FUNCS[agg_func].transform)

        return result

    def get_agg_data(self) -> np.ndarray:
        result = self.get_grouped(self.attr_lat, self.attr_lon,
                                  self.admin_level, self.agg_attr,
                                  self.agg_func)

        self.agg_data = np.array(result.values)
        self.region_ids = np.array(result.index)

        arg_region_sort = np.argsort(self.region_ids)
        self.region_ids = self.region_ids[arg_region_sort]
        self.agg_data = self.agg_data[arg_region_sort]

        self.recompute_binnings()

        return self.agg_data

    def format_agg_val(self, value):
        if self.agg_func in ('Count', 'Count defined'):
            return f"{value:d}"
        else:
            return self.agg_attr.repr_val(value)

    def get_choropleth_regions(self) -> List[_ChoroplethRegion]:
        """Recalculate regions"""
        if self.attr_lat is None:
            # if we don't have locations we can't compute regions
            return []

        _, region_info, polygons = self.get_regions(self.attr_lat,
                                                    self.attr_lon,
                                                    self.admin_level)

        regions = []
        for _id in polygons:
            if isinstance(polygons[_id], MultiPolygon):
                # some regions consist of multiple polygons
                polys = list(polygons[_id].geoms)
            else:
                polys = [polygons[_id]]

            qpolys = [self.poly2qpoly(transform(self.deg2canvas, poly))
                      for poly in polys]
            regions.append(_ChoroplethRegion(id=_id, info=region_info[_id],
                                             qpolys=qpolys))

        self.choropleth_regions = sorted(regions, key=lambda cr: cr.id)
        self.get_agg_data()
        return self.choropleth_regions

    @staticmethod
    def poly2qpoly(poly: Polygon) -> QPolygonF:
        return QPolygonF([QPointF(x, y)
                          for x, y in poly.exterior.coords])

    @staticmethod
    def deg2canvas(x, y):
        x, y = deg2norm(x, y)
        y = 1 - y
        return x, y

    def clear(self, cache=False):
        self.choropleth_regions = []
        if cache:
            self.get_regions.cache_clear()

    def send_report(self):
        if self.data is None:
            return
        self.report_plot()

    def sizeHint(self):
        return QSize(1132, 708)

    def onDeleteWidget(self):
        super().onDeleteWidget()
        self.graph.plot_widget.getViewBox().deleteLater()
        self.graph.plot_widget.clear()
        self.graph.clear()

    def keyPressEvent(self, event):
        """Update the tip about using the modifier keys when selecting"""
        super().keyPressEvent(event)
        self.graph.update_tooltip(event.modifiers())

    def keyReleaseEvent(self, event):
        """Update the tip about using the modifier keys when selecting"""
        super().keyReleaseEvent(event)
        self.graph.update_tooltip(event.modifiers())

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
    def migrate_settings(cls, settings, version):
        if version < 2:
            settings["graph"] = {}
            rename_setting(settings, "admin", "admin_level")
            rename_setting(settings, "autocommit", "auto_commit")
            settings["graph"]["alpha_value"] = \
                round(settings["opacity"] * 2.55)
            settings["graph"]["show_legend"] = settings["show_legend"]

    @classmethod
    def migrate_context(cls, context, version):
        if version < 2:
            migrate_str_to_variable(context, names="lat_attr",
                                    none_placeholder="")
            migrate_str_to_variable(context, names="lon_attr",
                                    none_placeholder="")
            migrate_str_to_variable(context, names="attr",
                                    none_placeholder="")

            rename_setting(context, "lat_attr", "attr_lat")
            rename_setting(context, "lon_attr", "attr_lon")
            rename_setting(context, "attr", "agg_attr")
            # old selection will not be ported
            rename_setting(context, "selection", "old_selection")

            if context.values["agg_func"][0] == "Max":
                context.values["agg_func"] = ("Maximal",
                                              context.values["agg_func"][1])
            elif context.values["agg_func"][0] == "Min":
                context.values["agg_func"] = ("Minimal",
                                              context.values["agg_func"][1])
            elif context.values["agg_func"][0] == "Std":
                context.values["agg_func"] = ("Std.",
                                              context.values["agg_func"][1])


if __name__ == "__main__":
    data = Table("India_census_district_population")
    WidgetPreview(OWChoropleth).run(data)
