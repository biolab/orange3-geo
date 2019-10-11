Choropleth Map
==============

A thematic map in which areas are shaded in proportion to the measurement of the statistical variable being displayed.

**Inputs**
-  Data: An input data set.

**Outputs**
-  Selected Data: A subset of instances selected from the map.
-  Data: Data set with an appended meta attribute specifying selected and unselected data.


**Choropleth** provides an easy way to visualize how a measurement varies across a geographic area or show the level of variability within a region. There are several levels of granularity available, from countries to states, counties, or municipalities.

![](images/Choropleth-stamped.png)

1. Aggregation properties:
   - Latitude attribute.
   - Longitude attribute.
   - Attribute to color the region by.
   - Aggregation level. Default counts the number of occurences of the region in the data. Count defined shows which regions appear in the data. Sum, mean, median, max, min and standard deviation work for numeric data, while mode works for categorical.
   - Administrative level. 0 is for countries, 1 is for states (US)/counties/Bundesländer/provinces, 2 is for counties (US)/municipalities.
2. Visualization properties:
   - Color steps defines into how many bins to split numeric data.
   - Color quantization defines the coloring scale (equidistant, logarithmic, quantile, k-means).
   - Opacity sets transparency of the color.
   - If *Show legend* is off, legend will be hidden.
   - If *Show map labels* is off, region names' will be hidden.
   - If *Show region details in a tooltip* is off, hovering over the region won't display anything.
3. If *Send Selection Automatically* is on, selection will be commited automatically. Alternatively, press *Send Selection*.

To reset the zoom level, press the target icon in the to left corner of the map. For zoom, use to + and - icons or mouse scroll. To select a region, click on it in the visualization. To select more than one region, hold Shift.

Example
-------

We will use *HDI* data from the **Datasets** widget. Open the widget, find *HDI* data, select it and press *Send*. **Choropleth** widget requires latitude and longitude pairs, so we will use **Geocoding** to extract this information. We used the attribute *Country* and found lat/lon pairs that **Choropleth** can use.

**Choropleth** will automatically look for attributes named *latitude*, *longitude*, *lat*, *lon* or similar. It will use them for plotting. Alternatively, set the attributes manually.

Since *HDI* attribute is our target variable, it will automatically be used for coloring. You can change it in the *Attribute* dropdown. We have set the level of aggregation to *max*, but since we have only one value per country, we could use *sum* or *min* just as well.

The widget shows HDI values as reported by the United Nations per country. Yellow countries are those with a high HDI and blue ones are the ones with a low HDI value.

![](images/Choropleth-Example.png)
