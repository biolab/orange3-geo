var map = L.map('map', {
    // preferCanvas: true,
    minZoom: 2,
    maxZoom: 17,
    layers: [
    ],
    worldCopyJump: true
});
map.attributionControl.setPrefix('Orange Data Mining | Leaflet | Natural Earth');
map.fitWorld();

L.easyButton('<img src="target.png" title="Fit to area bounds" class="custom-button">', function () {
    pybridge.fit_to_bounds();
}).addTo(map);

function _tooltip(layer) {
    if ($.isEmptyObject(results))
        return;
    var props = layer.feature.properties,
        keys = {
            //~ '_id': null,
            'Name': null,
            'Type': null,
            'iso_a2': 'ISO 3166-1',
            'adm0_a3': 'Country',
            'sovereignt': 'Sovereign territory',
            'Subregion': null,
            'Economy': null,
            'State': null,
            'Capital': null,
            'FIPS 10-4': 'fips10',
            'FIPS': null,
            'HASC': null
        };
    var parts = Object.keys(keys).map(function(key) {
        if (!window.show_details && key != 'Name')
            return false;
        var label = keys[key] || key,
            key = key.toLowerCase();
        return (props[key] ? '<b>' + label + ':</b> ' + props[key] : false);
    }).filter(function(value) { return value; });
    var value = results.repr_vals[props._id] || results.values[props._id];
    if (typeof value === 'undefined') {
        value = NaN;
    } else {
        if (results.discrete.length)
            value = results.discrete[value] || NaN;
        else if (value.toFixed) {
            value = value.toFixed(3);
            value = parseInt(value) == value ? parseInt(value) : value;
        }
    }
    return ('<b>' + results.attr + ':</b> ' + value + '<hr>') + parts.join('<br>');
}

var selection = {};
function _select_layer(id) {
    if (isNaN(results.values[id]))
        return;
    selection[id] = 1;
    var layer = geojson_layers_by_id[id]
    layer.setStyle({color:'orangeRed', weight:3});
    var el = layer.getElement();
    el.parentNode.appendChild(el);
}
function _unselect_layer(id) {
    var layer = geojson_layers_by_id[id];
    // Fully override orangeRed from selection, otherwise ghosted stroke persists
    layer.setStyle({color: 'white', weight: 3});

    layer.setStyle({color: 'white', weight: .5});
    var el = layer.getElement();
    el.parentNode && el.parentNode.insertBefore(el, el.parentNode.childNodes[0]);
    delete selection[id];
}
function _on_click(event) {
    var append = event.originalEvent.shiftKey,
        toggle = event.originalEvent.ctrlKey,
        layer = event.target;
    if (!(append || toggle)) {
        Object.keys(selection).forEach(_unselect_layer);
    }
    try {
        var id = layer.feature.properties._id;
    } catch (e) {
        // Clicked on map tile layer (e.g. sea, not region feature)
        return;
    }

    // Nothing further to do on regions that don't contain data points
    if (isNaN(results.values[id]))
        return;

    if (toggle && selection[id]) {
        _unselect_layer(id);
    } else {
        _select_layer(id);
    }
    pybridge.selection(Object.keys(selection));
    // If clicked on feature, don't propagate to clicked-on-map-sea
    L.DomEvent.stopPropagation(event);
}
map.on('click', _on_click);
function set_region_selection(user_selection) {
    selection = {};
    user_selection.forEach(function (id) {selection[id] = 1;});
}
function apply_region_selection() {
    Object.keys(selection).forEach(function (id) {
        _select_layer(id);
    });
    pybridge.selection(Object.keys(selection));
}

var fill_opacity = .7;
function set_opacity(opacity) {
    window.fill_opacity = opacity;
    geojson_layers.forEach(function(layer) {
        layer.setStyle({fillOpacity: opacity});
    });
}

var quantization = 'e';
function set_quantization(q) {
    quantization = q;
    replot();
}

var n_color_steps = 5;
function set_color_steps(steps) {
    n_color_steps = steps;
    replot();
}

// Add legend
var legend = L.control({position: 'bottomright'});
legend.onAdd = function(map) {
    var div = L.DomUtil.create('div', 'legend-horiz');
    div.setAttribute('id', 'legend');
    return div;
};
legend.addTo(map);

function toggle_legend(show) {
    $('.legend, .legend-horiz').css({display: show ? 'block' : 'none'});
}

var tileLayer = L.tileLayer.provider('CartoDB.Positron').addTo(map);
function toggle_map_labels(show) {
    // OpenStreetMap.BlackAndWhite, OpenMapSurfer.Grayscale, Hydda.Base,
    // Stamen.TonerLite, Esri.WorldTopoMap, Esri.WorldGrayCanvas,
    // CartoDB.Positron, CartoDB.PositronNoLabels
    var provider = show ? 'CartoDB.Positron' : 'CartoDB.PositronNoLabels';
    var new_provider = L.tileLayer.provider(provider).addTo(map);
    tileLayer.removeFrom(map);
    tileLayer = new_provider;
}

var show_details = true;
function toggle_tooltip_details(show) {
    show_details = show;
    geojson_layers.forEach(function(layer) {
        layer.getLayers().forEach(function(layer){
            layer.isTooltipOpen() && layer.closeTooltip();
        });
    });
}

var geojson_layers = [];
var geojson_layers_by_id = {};

function add_geojson_layer(geojson) {
    var choroplethLayer = L.choropleth(geojson, {
        valueProperty: function (feature) {
            return results.values[feature.properties._id];
        },
        colors: colors,
        // scale: results.colors,
        steps: n_color_steps,
        mode: results.have_nonpositive && quantization == 'l' ? 'e' : quantization,
        style: function() {
            return {
                color: 'white',
                weight: .5,
                fillOpacity: fill_opacity,
                fillColor: 'transparent'
            };
        },
        onEachFeature: function (feature, layer) {
            var id = feature.properties._id;
            geojson_layers_by_id[id] = layer;
            layer.bindTooltip(_tooltip, {sticky: true});
            layer.on('click', _on_click);
            // No border on shapes without data
            if (typeof results.values[id] === 'undefined')
                layer.setStyle({weight: 0});
        }
    }).addTo(map);
    geojson_layers.push(choroplethLayer);

    if (results.discrete.length) {
        // Update fillColors for discrete attribute
        choroplethLayer.getLayers().forEach(function (layer) {
            var value = results.values[layer.feature.properties._id];
            if (typeof value !== 'undefined')
                layer.setStyle({fillColor: results.colors[value]});
        });
    }
    apply_region_selection();
}

var json_cache = {};
function replot() {
    geojson_layers = geojson_layers.filter(function(layer) {
        layer.removeFrom(map);
        return false;
    });

    if (!window.results || !results.values || !Object.keys(results.values).length)
        return;

    console.log('Replotting regions:', results.regions);

    window.colors = chroma.scale(results.colors).colors(n_color_steps);
    
    var jsons = [];
    function _check_json_download_complete() {
        // When all JSONs obtained
        if (jsons.length == results.regions.length) {
            add_geojson_layer({
                type: "FeatureCollection",
                features: [].concat.apply([], jsons)
            });
        }
    }
    results.regions.forEach(function(region) {
        if (typeof json_cache[region] === 'undefined') {
            $.getJSON('../../geojson/admin' + region + '.json', function (json) {
                json_cache[region] = json.features;
                jsons.push(json.features);
                _check_json_download_complete();
            });
        } else {
            jsons.push(json_cache[region]);
            _check_json_download_complete();
        }
    });

    // Update legend
    if (results.discrete.length) {
        var str = '',
            legend = $('#legend');
        for (var i=0; i<results.colors.length; ++i) {
            if (i >= 15) {
                str += L.Util.template('<div>&nbsp;&nbsp;+ {n_more} more ...</div>', {
                    n_more: results.colors.length - i });
                break;
            }
            str += L.Util.template(
                '<div title="{value}"><div class="legend-icon" style="background:{color}">&nbsp;</div> <span class="legend-label">{value}</span></div>', {
                    color: results.colors[i],
                    value: results.discrete[i]
            });
        }
        legend.addClass('legend');
        legend.removeClass('legend-horiz');
        legend[0].innerHTML = str;
    } else {
        var legend = $('#legend');
        legend.addClass('legend-horiz');
        legend.removeClass('legend');
        legend[0].innerHTML = L.Util.template(
            '<div class="labels"><div title="{min_full}" class="min">{min}</div><div title="{max_full}" class="max">{max}</div></div><ul>{colors}</ul>', {
                min: parseFloat(results.minmax[0]).toFixed(3),
                max: parseFloat(results.minmax[1]).toFixed(3),
                min_full: results.minmax[0],
                max_full: results.minmax[1],
                colors: colors.map(function (color) {
                    return '<li style="background-color: ' + color + '"></li>';
                }).join('')}
        );
    }
}
