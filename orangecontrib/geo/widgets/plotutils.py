import os
import weakref
from io import BytesIO
from concurrent.futures import Future
from typing import List, NamedTuple, Optional
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

from Orange.misc.environ import data_dir
from Orange.widgets.utils.plot import ZOOMING
from Orange.widgets.visualize.owscatterplotgraph import LegendItem
from Orange.widgets.visualize.utils.plotutils import InteractiveViewBox


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


class _TileProvider(NamedTuple):
    url: str
    attribution: str
    size: int
    max_zoom: int
    dark: bool = False


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
        max_zoom=19,
        dark=True
    ),
}

DEFAULT_TILE_PROVIDER = next(iter(TILE_PROVIDERS))


class MapViewBox(InteractiveViewBox):
    """ViewBox to be used for maps since it knows how to properly handle zoom"""
    def __init__(self, graph, enable_menu=False):
        super().__init__(graph, enable_menu=enable_menu)
        self.__zoom_level = 2
        self.__tile_provider = None  # type: _TileProvider

    def wheelEvent(self, ev, axis=None):
        """Override wheel event so we manually track changes of zoom and
        update map accordingly."""
        delta = 0.5 * np.sign(ev.delta())
        self.__zoom_level = self.__clipped_zoom(self.__zoom_level + delta)

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
                and ev.button() & (Qt.LeftButton | Qt.MiddleButton) \
                and self.state['mouseMode'] == ViewBox.RectMode \
                and ev.isFinish():
            zoom()
        elif ev.button() & Qt.RightButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis=axis)

    def mouseClickEvent(self, ev):
        if ev.button() != Qt.RightButton and not ev.double():
            super().mouseClickEvent(ev)
            return
        center = self.mapToView(ev.pos())
        if ev.double():
            self.__zoom_level = self.__clipped_zoom(self.__zoom_level + 1)
        else:
            self.__zoom_level = self.__clipped_zoom(self.__zoom_level - 1)
        self.match_zoom(center, offset=True)
        ev.accept()

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
        return int(self.__zoom_level)

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
        self.__zoom_level = self.__clipped_zoom(min(zx, zy))

    def tile_provider(self):
        return self.__tile_provider

    def set_tile_provider(self, tp):
        self.__tile_provider = tp

    def __clipped_zoom(self, zoom):
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
        dx = dx_px / (2 ** self.get_zoom() * self.__tile_provider.size)
        dy = dy_px / (2 ** self.get_zoom() * self.__tile_provider.size)
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
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, True)
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


class MapMixin:
    """
    This mixin provides maps for `OWScatterPlotBase` based visualizations.

    It expects an `OWScatterPlotBase` like object that must have:
     * `plot_widget` attribute of type pg.PlotWidget
     * `view_box` attribute of type MapViewBox
     * `master` attribute of type OWWidget
    """
    show_internet_error = Signal(bool)

    def __init__(self):
        self.tile_provider = TILE_PROVIDERS[DEFAULT_TILE_PROVIDER]

        self.tile_attribution = AttributionItem(
            parent=self.plot_widget.getViewBox())
        self.tile_attribution.setHtml(self.tile_provider.attribution)

        self.mem_cache = {}
        self.map = None  # type: Optional[Image.Image]

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

    def _update_view_range(self, min_x, max_x, min_y, max_y, keep_zoom=False):
        if not keep_zoom:
            self.view_box.recalculate_zoom(max_x - min_x, max_y - min_y)

        center = Point(min_x + (max_x - min_x) / 2,
                       min_y + (max_y - min_y) / 2)
        self.view_box.match_zoom(center)

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
            print(t)
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

    def _update_tile_provider(self, tp):
        self.clear_map()
        self.tile_provider = tp
        self.view_box.set_tile_provider(self.tile_provider)
        self.tile_attribution.setHtml(self.tile_provider.attribution)
        self.update_map()

    def clear_map(self):
        self._cancel_futures()
        self.futures = []
        self.map = None
        self.tz = 1
        self.__new_map_items()
