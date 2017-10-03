#!/bin/bash
#
# Update GeoJSON files.
#
# Before running, wget & unzip into this dir:
#   Admin0 (countries)
#   - http://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_0_countries.zip
#   Admin1 (states, regions, municipalities)
#   - http://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_1_states_provinces.zip
#   Admin2 (US counties)
#   - http://www2.census.gov/geo/tiger/GENZ2015/shp/cb_2015_us_county_500k.zip
#   - http://www2.census.gov/geo/tiger/GENZ2015/shp/cb_2015_us_state_5m.zip
#   - http://www2.census.gov/geo/docs/reference/state.txt
#   - contents as counties.txt https://web.archive.org/web/20160924075116/http://www.statoids.com/yus.html

set -e

# ensure have dependencies
mapshaper --version >/dev/null
{ isoquery --iso=3166 | cut -sf1,2 > iso3166a2a3.txt; } 2>/dev/null || true  # use checked-out file

simplify () { mapshaper -i "$2" -simplify $1 dp planar keep-shapes stats -o "$3"; }

# Admin0
rm out.json 2>/dev/null || true
ogr2ogr \
    -f GeoJSON \
    -select ISO_A2,ISO_A3,GU_A3,FIPS_10_,ADM0_A3,NAME,SOVEREIGNT,CONTINENT,TYPE,REGION_UN,REGION_WB,ECONOMY,SUBREGION \
    out.json ne_10m_admin_0_countries.shp
sed -i 's/"ISO_A2"/"iso_a2"/g;
        s/"ISO_A3"/"iso_a3"/g;
        s/"FIPS_10_"/"fips10"/g;
        s/"ADM0_A3"/"adm0_a3"/g;
        s/"NAME"/"name"/g;
        s/"SOVEREIGNT"/"sovereignt"/g;
        s/"CONTINENT"/"continent"/g;
        s/"TYPE"/"type"/g;
        s/"REGION_UN"/"region_un"/g;
        s/"REGION_WB"/"region_wb"/g;
        s/"ECONOMY"/"economy"/g;
        s/"SUBREGION"/"subregion"/g;
        s/"-99"/null/g;' out.json
simplify .3 out.json admin0.json
rm out.json

python3 -c "
import json
from math import isnan

CC = {}
for line in open('iso3166a2a3.txt'):
    cc2, cc3 = line.split()
    CC[cc3] = cc2

with open('admin0.json') as f:
    geo = json.load(f)

def isnull(val):
    return (val is None or
            val in ('-99', '-1', 'NUL', 'NULL') or
            isinstance(val, float) and isnan(val))

out = {'type': 'FeatureCollection',
       'features': []}
seen = set()
for feature in geo['features']:
    p = feature['properties']
    id = p['adm0_a3']
    assert id not in seen
    seen.add(id)

    cc2 = (p['iso_a2'] if not isnull(p['iso_a2']) else
           CC.get(p['iso_a3']) or
           CC.get(p['adm0_a3']) or
           CC.get(p['GU_A3']))
    cc3 = None
    if cc2 or 'country' in p['type'].lower():
        cc3 = (p['iso_a3'] if not isnull(p['iso_a3']) else
               p['adm0_a3'] if not isnull(p['adm0_a3']) else
               p['GU_A3'] if not isnull(p['GU_A3']) else
               None)
    p['iso_a2'] = cc2
    p['iso_a3'] = cc3
    p['_id'] = p['adm0_a3']
    del p['GU_A3']
    assert 'GU_A3' not in feature['properties']
    out['features'].append(feature)

with open('admin0.json', 'w') as f:
    json.dump(out, f)
"


# Admin1
# NOTE: Admin0 and Admin1 are matched on adm0_a3 field
ogr2ogr -f GeoJSON \
        -select name,iso_a2,adm0_a3,adm1_code,fips,admin,code_hasc,type_en,latitude,longitude \
        out.json ne_10m_admin_1_states_provinces.shp
sed -i -r 's/"type_en"/"type"/g;
           s/"code_hasc"/"hasc"/g;
           s/"adm1_code"/"_id"/g;
           s/"-1"/null/g;
           s/"-99"/null/g;' out.json
simplify .7 out.json admin1.json
rm out.json
python3 -c "
import json
from math import isnan
from itertools import groupby
from collections import OrderedDict

CC = {}
for line in open('iso3166a2a3.txt'):
    cc2, cc3 = line.split()
    CC[cc3] = cc2

with open('admin1.json') as f:
    geo = json.load(f)

def isnull(val):
    return (val is None or
            val in ('-99', '-1', 'NUL', 'NULL') or
            isinstance(val, float) and isnan(val))

out = {'type': 'FeatureCollection',
       'features': []}
for feature in geo['features']:
    p = feature['properties']
    if isnull(p['iso_a2']):
        p['iso_a2'] = CC.get(p['adm0_a3'])
    out['features'].append(feature)

# with open('admin1.json', 'w') as f:
#     json.dump(out, f)
key = lambda feature: feature['properties']['adm0_a3']
for cc, features in groupby(sorted(out['features'], key=key), key):
    features = [OrderedDict([
                    ('type', f['type']),
                    ('properties', f['properties']),
                    ('geometry', f['geometry']),
                ]) for f in features]
    print(cc, len(features))
    if cc == 'SVN':
        from pprint import pprint
        pprint(features[0])
    with open('admin1-{}.json'.format(cc), 'w') as f:
        json.dump(dict(type='FeatureCollection', features=features), f)
"
rm admin1.json
## Alternatively, don't simplify all admin1 at once (above), but simplify
## each country individually here
for file in admin1-*.json; do
    simplify .7 "$file" "$file"
done


# US Admin2
ogr2ogr -f GeoJSON -select NAME,STATEFP,GEOID out.json cb_2015_us_county_500k.shp
sed -i 's/"NAME"/"name"/g;' out.json
simplify .11 out.json admin2-USA.json
rm out.json
python3 -c "
import json
from math import isnan

STATES = {}
for line in open('state.txt'):
    if line.startswith('STATE|'): continue
    fips, state, state_name, *_ = line.split('|')
    STATES[fips] = (state, state_name)

COUNTIES = {}
_NLEN = len('----------------------')
_CAPCOL = len('---------------------- - -------- ----- --------- ------- ------- - ')
for line in open('counties.txt'):
    if not line.strip() or line.startswith(('Name ', '---')): continue
    name = line[:_NLEN].strip()
    capital = line[_CAPCOL:].strip()
    _, hasc, fips, *_ = line[_NLEN:].split()
    COUNTIES[fips] = (hasc, capital, name)

with open('admin2-USA.json') as f:
    geo = json.load(f)

def isnull(val):
    return (val is None or
            val in ('-99', '-1', 'NUL', 'NULL') or
            isinstance(val, float) and isnan(val))

out = {'type': 'FeatureCollection',
       'features': []}
seen = set()
for feature in geo['features']:
    p = feature['properties']
    fips = p['GEOID']
    try:
        hasc, capital, name = COUNTIES[fips]
    except KeyError:
        # Skip American Samoa, Guam, US Minor Outlying Islands (etc.) missing in counties.txt
        hasc, capital, name = None, None, None

    # Each county gets listed twice (in ogr2ogr stage already, dunno)
    if fips in seen:
        continue
    seen.add(fips)

    state, state_long = STATES[p['STATEFP']]
    p['adm0_a3'] = 'USA'
    p['_id'] = 'USA-' + state + '-' + fips
    p['name'] = (name or p['name']) + ', ' + state_long
    p['state'] = state
    p['capital'] = capital

    p['iso_a2'] = 'US'
    p['hasc'] = hasc
    p['fips'] = fips
    p['type'] = 'County'

    for k in ('STATEFP', 'GEOID'):
        del p[k]
    out['features'].append(feature)

with open('admin2-USA.json', 'w') as f:
    json.dump(out, f)
"
