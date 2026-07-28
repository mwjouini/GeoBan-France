# -*- coding: utf-8 -*-
"""
GeoBan France - Extension QGIS
Auteur : JOUINI Mohamed Wael
Licence : GPL v2+ / MIT
"""

import base64
import os

png_data = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAACYSURBVDhPzZExDsMgDEVdKkdkycweqUvP0L1n6xG69Ag9Q6fMjGQJE8XQOlWlT/pP8D+2bYx4aX6mN9e18x12h83tC5jP1w+43N/B+XwF5/sTnM9PcL4/wPn+AOf7A5zvD3C+P8D5/gDn+wOc7w9wvj/A+f4A5/sDnO8PcL4/wPn+AOf7A5zvD3C+P8D5/oD/T2B9R9x/wD/Gv2bTf2N/wwAAAABJRU5ErkJggg=="

with open("e:\\nouveau projet adresse qgis\\icon.png", "wb") as f:
    f.write(base64.b64decode(png_data))

print("Icon created.")
