Orange3-Geo
===========

[![Discord Chat](https://img.shields.io/discord/633376992607076354?style=for-the-badge&logo=discord&color=orange&labelColor=black)](https://discord.gg/FWrfeXV)
[![build: passing](https://img.shields.io/travis/biolab/orange3-geo?style=for-the-badge&labelColor=black)](https://travis-ci.org/biolab/orange3-geo)
[![codecov](https://img.shields.io/codecov/c/github/biolab/orange3-geo?style=for-the-badge&labelColor=black)](https://codecov.io/gh/biolab/orange3-geo)

[Orange](http://orange.biolab.si) add-on for dealing with geography and geo-location. It provides widgets
for visualizing maps and regions, and encoding and decoding geographical data.

Installation
------------

Install from Orange add-on installer through Options - Add-ons.

To install the add-on with pip use

    pip install Orange3-Geo

To install the add-on from source, run

    python setup.py install

To register this add-on with Orange, but keep the code in the development
directory (do not copy it to Python's site-packages directory), run

    python setup.py develop

You can also run

    pip install -e .

which is sometimes preferable as you can *pip uninstall* packages later.
You may also want to read [CONTRIBUTING.md](CONTRIBUTING.md)

Usage
-----

After the installation the widgets from this add-on are registered with Orange.
To run Orange from the terminal use

    orange-canvas

or

    python3 -m Orange.canvas

New widgets are in the toolbox bar under the Geo section.
