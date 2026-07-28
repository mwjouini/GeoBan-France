# -*- coding: utf-8 -*-
"""
GeoBan France - Filtre Locator QGIS
Auteur : JOUINI Mohamed Wael
"""

import json
import urllib.request
import urllib.parse
from qgis.core import QgsLocatorFilter, QgsLocatorResult, QgsPointXY, QgsCoordinateTransform, QgsMessageLog, QgsProject, QgsCoordinateReferenceSystem

def safe_urlopen(req, timeout=10):
    url_str = req.full_url if hasattr(req, 'full_url') else str(req)
    if not url_str.startswith('https://'):
        raise ValueError("Seul le protocole HTTPS est autorisé.")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310

class BanLocatorFilter(QgsLocatorFilter):
    def __init__(self, plugin):
        QgsLocatorFilter.__init__(self, None)
        self.plugin = plugin

    def clone(self):
        return BanLocatorFilter(self.plugin)

    def name(self):
        return "recherche adresse ban"

    def prefix(self):
        return "ban"

    def displayName(self):
        return "Adresses BAN (France)"

    def flags(self):
        return QgsLocatorFilter.FlagFast

    def fetchResults(self, search, context, feedback):
        if len(search) < 3:
            return

        url = "https://api-adresse.data.gouv.fr/search/?q=" + urllib.parse.quote(search) + "&limit=5"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (QGIS GeoBan France)'})
            with safe_urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                features = data.get('features', [])
                
                for feature in features:
                    if feedback.isCanceled():
                        return
                        
                    props = feature.get('properties', {})
                    coords = feature.get('geometry', {}).get('coordinates', [])
                    if len(coords) < 2:
                        continue
                        
                    result = QgsLocatorResult()
                    result.filter = self
                    result.displayString = props.get('label', '')
                    result.description = f"Type: {props.get('type', '')} | CP: {props.get('postcode', '')}"
                    result.userData = {
                        'lon': coords[0],
                        'lat': coords[1],
                        'label': props.get('label', ''),
                        'properties': props,
                        'geometry': feature.get('geometry', {})
                    }
                    self.resultFetched.emit(result)
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur Locator BAN: {str(e)}", "GeoBan France", QgsMessageLog.WARNING)

    def triggerResult(self, result):
        data = result.userData
        if not data:
            return

        lon, lat = data['lon'], data['lat']
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        canvas = self.plugin.iface.mapCanvas()
        crs_map = canvas.mapSettings().destinationCrs()
        
        transform = QgsCoordinateTransform(crs_wgs84, crs_map, QgsProject.instance())
        point = transform.transform(QgsPointXY(lon, lat))
        
        canvas.setCenter(point)
        canvas.zoomScale(2500)
        canvas.refresh()
