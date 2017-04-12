from itertools import chain

import numpy as np
    
from Orange.data import Table


def find_lat_lon(data):
    """Return inferred latitude and longitude attributes as found in the data domain"""
    assert isinstance(data, Table)

    all_vars = list(chain(data.domain.variables, data.domain.metas))

    lat_attr = next(
        (attr for attr in all_vars
         if attr.is_continuous and
         attr.name.lower().startswith(('latitude', 'lat'))), None)
    lon_attr = next(
        (attr for attr in all_vars
         if attr.is_continuous and
         attr.name.lower().startswith(('longitude', 'lng', 'long', 'lon'))),
        None)

    def _all_between(vals, min, max):
        return np.all((min <= vals) & (vals <= max))

    if not lat_attr:
        for attr in all_vars:
            if attr.is_continuous:
                values = np.nan_to_num(
                    data.get_column_view(attr)[0].astype(float))
                if _all_between(values, -90, 90):
                    lat_attr = attr
                    break
    if not lon_attr:
        for attr in all_vars:
            if attr.is_continuous:
                values = np.nan_to_num(
                    data.get_column_view(attr)[0].astype(float))
                if _all_between(values, -180, 180):
                    lon_attr = attr
                    break

    return lat_attr, lon_attr
