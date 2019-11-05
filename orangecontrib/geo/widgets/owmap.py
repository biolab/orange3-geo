import os
import weakref
from io import BytesIO
from concurrent.futures import Future
from typing import List, NamedTuple
from functools import partial
from contextlib import closing

from PIL import Image
import numpy as np

from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import Qt, QObject, QThread, QRect, QRectF, QUrl, \
    pyqtSignal as Signal
from AnyQt.QtNetwork import QNetworkAccessManager, QNetworkDiskCache,\
    QNetworkRequest, QNetworkReply
from AnyQt.QtGui import QBrush, QColor

from pyqtgraph import Point, ImageItem, ViewBox, LabelItem
import pyqtgraph.functions as fn

from Orange.data import Table, ContinuousVariable
from Orange.misc.environ import data_dir
from Orange.widgets import gui, settings
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.utils.itemmodels import DomainModel
from Orange.widgets.utils.plot import ZOOMING
from Orange.widgets.widget import Msg
from Orange.widgets.visualize.utils.widget import OWDataProjectionWidget
from Orange.widgets.visualize.owscatterplotgraph import OWScatterPlotBase, \
    LegendItem
from Orange.widgets.visualize.utils.plotutils import InteractiveViewBox

from orangecontrib.geo.utils import find_lat_lon


MAX_LATITUDE = 85.0511287798
MAX_LONGITUDE = 180


def deg2norm(lon_deg, lat_deg):
    """
    Transform GLOBE (curved) lat, lon to Pseudo-Mercator (flat) normalized,
    zoom independent x, y.
    See: https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
    """
    lon_rad = np.radians(np.clip(lon_deg, -MAX_LONGITUDE, MAX_LONGITUDE))
    lat_rad = np.radians(np.clip(lat_deg, -MAX_LATITUDE, MAX_LATITUDE))
    x = (1 + lon_rad / np.pi) / 2
    y = (1 - np.log(np.tan(lat_rad) + (1 / np.cos(lat_rad))) / np.pi) / 2
    return x, y


def norm2tile(x, y, zoom):
    """
    Transform normalized x, y coordinates into tilex, tiley coordinates
    according to zoom.
    """
    n = 2 ** zoom
    return x * n, y * n


def tile2norm(x, y, zoom):
    """
    Transform tilex, tiley coordinates into normalized x, y coordinates
    according to zoom.
    """
    n = 2 ** zoom
    return x / n, y / n


_TileProvider = NamedTuple(
    "_TileProvider", [
        ("url", str),
        ("attribution", str),
        ("size", int),
        ("max_zoom", int),
    ]
)


class _TileItem:
    def __init__(self, x: int, y: int, z: int, tile_provider: _TileProvider):
        self.x = x
        self.y = y
        self.z = z
        self.tile_provider = tile_provider
        self.url = tile_provider.url.format(x=x, y=y, z=z)
        self.disc_cache = False
        self.n_loadings = 1

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return self.url == other.url


TILE_PROVIDERS = {
    "OpenStreetMap": _TileProvider(
        url="http://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution='&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        size=256,
        max_zoom=18
    ),
    "Black and white": _TileProvider(
        url="http://tiles.wmflabs.org/bw-mapnik/{z}/{x}/{y}.png",
        attribution='&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        size=256,
        max_zoom=18
    ),
    "Topographic": _TileProvider(
        url="http://tile.opentopomap.org/{z}/{x}/{y}.png",
        attribution='map data: &copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
        size=256,
        max_zoom=17
    ),
    "Satellite": _TileProvider(
        url="http://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution="Sources: Esri, DigitalGlobe, GeoEye, Earthstar Geographics, CNES/Airbus DS, USDA, USGS, AeroGRID, IGN, and the GIS User Community",
        size=256,
        max_zoom=19
    ),
    "Print": _TileProvider(
        url="http://tile.stamen.com/toner/{z}/{x}/{y}.png",
        attribution='Map tiles by <a href="http://stamen.com">Stamen Design</a>, under <a href="http://creativecommons.org/licenses/by/3.0">CC BY 3.0</a>. Data by <a href="http://openstreetmap.org">OpenStreetMap</a>, under <a href="http://www.openstreetmap.org/copyright">ODbL</a>.',
        size=256,
        max_zoom=20
    ),
    "Dark": _TileProvider(
        url="http://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        attribution='&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
        size=256,
        max_zoom=19
    ),
}
DEFAULT_TILE_PROVIDERS = next(iter(TILE_PROVIDERS))


class MapViewBox(InteractiveViewBox):
    """ViewBox to be used for maps since it knows how to properly handle zoom"""
    def __init__(self, graph, enable_menu=False):
        super().__init__(graph, enable_menu=enable_menu)
        self.__zoom_level = 2
        self.__tile_provider = None  # type: _TileProvider

    def wheelEvent(self, ev, axis=None):
        """Override wheel event so we manually track changes of zoom and
        update map accordingly."""
        if ev.delta() > 0:
            # zoom-in
            self.__zoom_level = self.__zoom_in_range(self.__zoom_level + 1)
        else:
            # zoom-out
            self.__zoom_level = self.__zoom_in_range(self.__zoom_level - 1)

        center = Point(fn.invertQTransform(self.childGroup.transform()).map(ev.pos()))
        self.match_zoom(center, offset=True)
        ev.accept()

    def mouseDragEvent(self, ev, axis=None):
        """Override from InteractiveViewBox with updated zooming."""
        def get_mapped_rect():
            p1, p2 = ev.buttonDownPos(ev.button()), ev.pos()
            p1 = self.mapToView(p1)
            p2 = self.mapToView(p2)
            return QRectF(p1, p2)

        def zoom():
            ev.accept()
            self.rbScaleBox.hide()
            ax = get_mapped_rect()
            # we recalculate approximate zoom and viewRect
            # we cannot use the exact rect because then the map would be blurry
            rect = ax.normalized()
            self.recalculate_zoom(rect.width(), rect.height())
            self.match_zoom(rect.center())

        if self.graph.state == ZOOMING \
                and ev.button() & (Qt.LeftButton | Qt.MidButton) \
                and self.state['mouseMode'] == ViewBox.RectMode \
                and ev.isFinish():
            zoom()
        elif ev.button() & Qt.RightButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis=axis)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.RightButton:
            ev.ignore()
        else:
            super().mouseClickEvent(ev)

    def match_zoom(self, center: Point, offset=False):
        """
        Find the right rectangle of visualization so that maps and
        screens resolutions match.
        :param center: center point of the new rectangle
        :param offset: set true if center is offset so the visualization
        doesn't jump around (used from zooming)
        """
        new_target = self.__new_target(center, offset=offset)
        self.setRange(new_target, padding=0)
        self.sigRangeChangedManually.emit(self.state['mouseEnabled'])

    def get_zoom(self):
        return self.__zoom_level

    def recalculate_zoom(self, dx: float, dy: float):
        """
        Calculate new zoom level to be close but smaller then needed to
        match resolution of screen with portion of maps described by dx, dy.
        :param dx: width in normalized coordinates
        :param dy: height in normalized coordinates
        """
        if self.__tile_provider is None or not dx or not dy:
            return
        dx_px = self.size().width()
        dy_px = self.size().height()
        dx_tiles = dx_px / self.__tile_provider.size
        dy_tiles = dy_px / self.__tile_provider.size
        zx = int(np.floor(np.log2(dx_tiles / dx)))
        zy = int(np.floor(np.log2(dy_tiles / dy)))
        self.__zoom_level = self.__zoom_in_range(min(zx, zy))

    def set_tile_provider(self, tp):
        self.__tile_provider = tp

    def __zoom_in_range(self, zoom):
        """Zoom must always be in range that tile servers provide."""
        return min(self.__tile_provider.max_zoom, max(2, zoom))

    def __new_target(self, center, offset=False):
        """Get new rectangle centered around center."""
        dx, dy = self.__get_size()
        left_size, up_size = 0.5, 0.5

        if offset:
            # offset target rectangle size, more natural for zooming
            vr = self.targetRect()
            left_size = (center.x() - vr.topLeft().x()) / vr.width()
            up_size = (center.y() - vr.topLeft().y()) / vr.height()

        tl = center + Point(-dx * left_size, -dy * up_size)
        br = center + Point(dx * (1 - left_size), dy * (1 - up_size))
        return QRectF(tl, br)

    def __get_size(self):
        """Get width and height in normalized coordinates that would match
         with screen resolution."""
        if self.__tile_provider is None:
            return 1, 1
        dx_px = self.size().width()
        dy_px = self.size().height()
        dx = dx_px / (2 ** self.__zoom_level * self.__tile_provider.size)
        dy = dy_px / (2 ** self.__zoom_level * self.__tile_provider.size)
        return dx, dy


class AttributionItem(LabelItem):
    """
    This holds the map attribution text. It doesn't change position on scaling
    """
    def __init__(self, anchor=((0, 1), (0, 1)), parent=None):
        super().__init__()
        self.setAttr('justify', 'left')

        self.item.setOpenExternalLinks(True)
        self.item.setTextInteractionFlags(Qt.TextBrowserInteraction)

        font = self.item.font()
        font.setPointSize(7)
        self.item.setFont(font)

        self.setParentItem(parent)
        self.anchor(*anchor)

    def setHtml(self, html):
        self.item.setHtml(html)
        self.updateMin()
        self.resizeEvent(None)
        self.updateGeometry()

    def paint(self, p, *_):
        p.setPen(fn.mkPen(196, 197, 193, 200))
        p.setBrush(fn.mkBrush(232, 232, 232, 200))
        p.drawRect(self.itemRect())


class OWScatterPlotMapGraph(OWScatterPlotBase):
    """
    Scatter plot that knows how to draw normalized coordinates on map. It
    additionally also manages zooming and resizing so that resolution of widget
    matches displayed images of maps.
    """
    show_internet_error = Signal(bool)

    freeze = settings.Setting(False)
    tile_provider_key = settings.Setting(DEFAULT_TILE_PROVIDERS)

    def __init__(self, scatter_widget, parent):
        super().__init__(scatter_widget, parent, view_box=MapViewBox)
        self.tile_provider = TILE_PROVIDERS[self.tile_provider_key]

        self.tile_attribution = AttributionItem(
            parent=self.plot_widget.getViewBox())
        self.tile_attribution.setHtml(self.tile_provider.attribution)

        self.mem_cache = {}
        self.map = None  # type: Image.Image

        # we use a background map so transitions between zoom levels looks nicer
        self.b_map_item = None
        self.map_item = None
        self.__new_map_items()

        self.ts = QRect(0, 0, 1, 1)
        self.ts_norm = QRect(0, 0, 1, 1)
        self.tz = 1
        self.zoom_changed = False

        self.loader = ImageLoader(self)
        self.futures = []

        self.view_box.setAspectLocked(lock=True, ratio=1)
        self.view_box.sigRangeChangedManually.connect(self.update_map)
        self.view_box.set_tile_provider(self.tile_provider)

    def _create_legend(self, anchor, brush=QBrush(QColor(232, 232, 232, 200))):
        # by default the legend transparency was to high for colorful maps
        legend = LegendItem(brush=brush)
        legend.setParentItem(self.plot_widget.getViewBox())
        legend.restoreAnchor(anchor)
        return legend

    @staticmethod
    def __new_map_item(z):
        map_item = ImageItem(autoLevels=False)
        map_item.setOpts(axisOrder='row-major')
        map_item.setZValue(z)
        return map_item

    def __new_map_items(self):
        if self.b_map_item is not None:
            self.plot_widget.removeItem(self.b_map_item)
        self.b_map_item = self.__new_map_item(-3)
        self.plot_widget.addItem(self.b_map_item)

        if self.map_item is not None:
            self.plot_widget.removeItem(self.map_item)
        self.map_item = self.__new_map_item(-2)
        self.plot_widget.addItem(self.map_item)

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
            self.reset_map()

    def get_sizes(self):
        return super().get_sizes() * 0.8

    def _reset_view(self, x_data, y_data):
        """
        This functionality is moved to reset_map which is called after
        update_coordinates because this is not called if there is no data and
        it also interferes with map freeze.
        """
        pass

    def reset_map(self, match_data=True):
        """
        Reset what part of tha map is drawn.
        :param match_data: if True reset so that all data is shown else just
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

        if match_data:
            self.view_box.recalculate_zoom(max_x - min_x, max_y - min_y)

        center = Point(min_x + (max_x - min_x) / 2,
                       min_y + (max_y - min_y) / 2)
        self.view_box.match_zoom(center)

    def reset_button_clicked(self):
        """Reset map so that all data is displayed"""
        self.reset_map()

    def update_map(self):
        """Get current view box to calculate which tiles to draw."""
        [min_x, max_x], [min_y, max_y] = self.view_box.viewRange()

        new_zoom = self.view_box.get_zoom()
        self.zoom_changed = self.tz != new_zoom
        self.tz = new_zoom

        # flip y to calculate edge tiles
        tile_min_x, tile_max_y = norm2tile(min_x, 1 - min_y, self.tz)
        tile_max_x, tile_min_y = norm2tile(max_x, 1 - max_y, self.tz)

        # round them to get edge tiles x, y
        tile_min_x = max(int(np.floor(tile_min_x)), 0)
        tile_min_y = max(int(np.floor(tile_min_y)), 0)
        tile_max_x = min(int(np.ceil(tile_max_x)), 2 ** self.tz)
        tile_max_y = min(int(np.ceil(tile_max_y)), 2 ** self.tz)

        self.ts = QRect(tile_min_x, tile_min_y,
                        tile_max_x - tile_min_x,
                        tile_max_y - tile_min_y)

        # transform rounded tile coordinates back
        min_edge_x, min_edge_y = tile2norm(tile_min_x, tile_min_y, self.tz)
        max_edge_x, max_edge_y = tile2norm(tile_max_x, tile_max_y, self.tz)

        # flip y back to transform map
        min_edge_y, max_edge_y = 1 - min_edge_y, 1 - max_edge_y

        # rectangle where to put the map into
        self.ts_norm = QRectF(min_edge_x, min_edge_y,
                              max_edge_x - min_edge_x,
                              max_edge_y - min_edge_y)

        self._map_z_shift()
        self._load_new_map()

    def _map_z_shift(self):
        """If zoom changes move current map to background and draw new over it"""
        if self.zoom_changed:
            self.plot_widget.removeItem(self.b_map_item)
            self.b_map_item = self.map_item
            self.b_map_item.setZValue(-3)
            self.map_item = self.__new_map_item(-2)
            self.plot_widget.addItem(self.map_item)

    def _load_new_map(self):
        """Prepare tiles that are needed in new view."""
        in_mem = []
        to_download = []

        for x in range(self.ts.width()):
            for y in range(self.ts.height()):
                tile = _TileItem(x=self.ts.x() + x, y=self.ts.y() + y,
                                 z=self.tz, tile_provider=self.tile_provider)
                if tile in self.mem_cache:
                    in_mem.append(tile)
                else:
                    to_download.append(tile)

        self._load_from_mem(in_mem)
        self._load_from_net(to_download)

    def _load_from_mem(self, tiles: List[_TileItem]):
        """Create new image object to draw tiles onto it.
        Tiles that are stored in memory are drawn immediately."""
        self.map = Image.new('RGBA',
                             (self.ts.width() * self.tile_provider.size,
                              self.ts.height() * self.tile_provider.size),
                             color="#ffffff00")
        for t in tiles:
            self._add_patch(t)

        self._update_map_item()

    def _add_patch(self, t):
        """Add tile to full image."""
        px = (t.x - self.ts.x()) * self.tile_provider.size
        py = (t.y - self.ts.y()) * self.tile_provider.size
        self.map.paste(self.mem_cache[t], (px, py))

    def _update_map_item(self):
        """Update ImageItem with current image."""
        self.map_item.setImage(np.array(self.map))
        self.map_item.setRect(self.ts_norm)

    def _load_from_net(self, tiles: List[_TileItem]):
        """Tiles that are not in memory are downloaded concurrently and are
        added to the main image dynamically."""

        if self.zoom_changed:
            self._cancel_futures()
            self.futures = []

        for t in tiles:
            self._load_one_from_net(t)

    def _load_one_from_net(self, t: _TileItem):
        """
        Download a tile from the internet. For a tile if we already tried
        to download it three times then show no internet error. If we managed
        to get a tile from the internet clear no internet warning
        """
        if t.n_loadings == 3:
            self.show_internet_error.emit(True)
            return

        future = self.loader.get(t)
        @future.add_done_callback
        def set_tile(_future):
            if _future.cancelled():
                return

            assert _future.done()

            _tile = _future._tile
            if _future.exception():
                _tile.n_loadings += 1
                # retry to download image
                self._load_one_from_net(_tile)
            else:
                img = _future.result()
                if not _tile.disc_cache:
                    self.show_internet_error.emit(False)
                self.mem_cache[_tile] = img
                self._add_patch(_tile)
                self._update_map_item()
                self.futures.remove(_future)

        self.futures.append(future)

    def _cancel_futures(self):
        for future in self.futures:
            future.cancel()
            if future._reply is not None:
                future._reply.close()
                future._reply.deleteLater()
                future._reply = None

    def update_tile_provider(self):
        self.clear_map()
        self.tile_provider = TILE_PROVIDERS[self.tile_provider_key]
        self.view_box.set_tile_provider(self.tile_provider)
        self.tile_attribution.setHtml(self.tile_provider.attribution)
        self.update_map()

    def clear_map(self):
        self._cancel_futures()
        self.futures = []
        self.map = None
        self.tz = 1
        self.__new_map_items()

    def clear(self):
        super().clear()
        if self.freeze:
            # readd map items that are cleared
            self.plot_widget.addItem(self.b_map_item)
            self.plot_widget.addItem(self.map_item)
        else:
            self.clear_map()


class ImageLoader(QObject):
    # Mostly a copy from OWImageViewer in imageanalytics add-on
    #: A weakref to a QNetworkAccessManager used for image retrieval.
    #: (we can only have one QNetworkDiskCache opened on the same
    #: directory)
    _NETMANAGER_REF = None

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        assert QThread.currentThread() is QApplication.instance().thread()

        netmanager = self._NETMANAGER_REF and self._NETMANAGER_REF()
        if netmanager is None:
            netmanager = QNetworkAccessManager()
            cache = QNetworkDiskCache()
            cache.setCacheDirectory(
                os.path.join(data_dir(), "geo", __name__ + ".GeoMap.Cache")
            )
            netmanager.setCache(cache)
            ImageLoader._NETMANAGER_REF = weakref.ref(netmanager)
        self._netmanager = netmanager

    def get(self, tile):
        future = Future()
        url = QUrl(tile.url)
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"OWMap/1.0")
        request.setAttribute(
            QNetworkRequest.CacheLoadControlAttribute,
            QNetworkRequest.PreferCache
        )
        request.setAttribute(QNetworkRequest.HTTP2AllowedAttribute, True)
        request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
        request.setMaximumRedirectsAllowed(5)

        # Future yielding a QNetworkReply when finished.
        reply = self._netmanager.get(request)
        future._reply = reply
        future._tile = tile

        @future.add_done_callback
        def abort_on_cancel(f):
            # abort the network request on future.cancel()
            if f.cancelled() and f._reply is not None:
                f._reply.abort()

        def on_reply_ready(reply, future):
            # type: (QNetworkReply, Future) -> None

            # schedule deferred delete to ensure the reply is closed
            # otherwise we will leak file/socket descriptors
            reply.deleteLater()
            future._reply = None

            with closing(reply):
                if not future.set_running_or_notify_cancel():
                    return

                if reply.error() != QNetworkReply.NoError:
                    # XXX Maybe convert the error into standard http and
                    # urllib exceptions.
                    future.set_exception(Exception(reply.errorString()))
                    return

                try:
                    image = Image.open(BytesIO(reply.readAll()))
                except Exception as e:
                    future.set_exception(e)
                else:
                    tile.disc_cache = reply.attribute(
                        QNetworkRequest.SourceIsFromCacheAttribute)
                    future.set_result(image)

        reply.finished.connect(partial(on_reply_ready, reply, future))
        return future


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
        self.graph.reset_map()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # when resizing we need to constantly reset the map so that new
        # portions are drawn
        self.graph.reset_map(match_data=False)

    @classmethod
    def migrate_settings(cls, _settings, version):
        if version < 3:
            _settings["graph"] = {}
            if "tile_provider" in _settings:
                if _settings["tile_provider"] == "Watercolor":
                    _settings["tile_provider"] = DEFAULT_TILE_PROVIDERS
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
