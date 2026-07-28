# -*- coding: utf-8 -*-
"""
GeoBan France - Client API REST (BAN & APICarto Cadastre)
Auteur : JOUINI Mohamed Wael
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from qgis.PyQt.QtCore import pyqtSignal, QThread
from qgis.core import QgsMessageLog

def safe_urlopen(req, timeout=10):
    url_str = req.full_url if hasattr(req, 'full_url') else str(req)
    if not url_str.startswith('https://'):
        raise ValueError("Seul le protocole HTTPS est autorisé.")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310

class BANSearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query, postcode=None, citycode=None):
        super().__init__()
        self.query = query
        self.postcode = postcode
        self.citycode = citycode

    def run(self):
        try:
            params = {'q': self.query, 'limit': 15}
            if self.postcode:
                params['postcode'] = self.postcode
            if self.citycode:
                params['citycode'] = self.citycode

            url = "https://api-adresse.data.gouv.fr/search/?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (QGIS GeoBan France)'})
            with safe_urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                features = data.get('features', [])
                self.finished.emit(features)
        except Exception as e:
            self.error.emit(str(e))

class CadastreSearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, code_insee=None, section=None, numero=None):
        super().__init__()
        self.code_insee = code_insee
        self.section = section
        self.numero = numero

    def run(self):
        try:
            params = {}
            if self.code_insee:
                params['code_insee'] = self.code_insee
            if self.section:
                params['section'] = self.section
            if self.numero:
                params['numero'] = self.numero.zfill(4) if self.numero else ''

            url = "https://apicarto.ign.fr/api/cadastre/parcelle?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (QGIS GeoBan France)'})
            with safe_urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                features = data.get('features', [])
                self.finished.emit(features)
        except Exception as e:
            self.error.emit(str(e))

class ReverseGeocodingThread(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, lon, lat):
        super().__init__()
        self.lon = lon
        self.lat = lat

    def run(self):
        result = {'ban': None, 'cadastre': None}
        headers = {'User-Agent': 'Mozilla/5.0 (QGIS GeoBan France)'}

        # 1. Query BAN Reverse Geocoding API
        try:
            params = {'lon': self.lon, 'lat': self.lat}
            url_ban = "https://api-adresse.data.gouv.fr/reverse/?" + urllib.parse.urlencode(params)
            req_ban = urllib.request.Request(url_ban, headers=headers)
            with safe_urlopen(req_ban, timeout=10) as response:
                data_ban = json.loads(response.read().decode('utf-8'))
                features = data_ban.get('features', [])
                if features:
                    result['ban'] = features[0]
        except Exception as err_ban:
            QgsMessageLog.logMessage(f"Recherche BAN: {str(err_ban)}", "GeoBan France", QgsMessageLog.INFO)

        # 2. Query APICarto Cadastre Reverse Geocoding API by geometry point
        try:
            geom_json = json.dumps({"type": "Point", "coordinates": [self.lon, self.lat]})
            url_cad = "https://apicarto.ign.fr/api/cadastre/parcelle?geom=" + urllib.parse.quote(geom_json)
            req_cad = urllib.request.Request(url_cad, headers=headers)
            with safe_urlopen(req_cad, timeout=10) as response:
                data_cad = json.loads(response.read().decode('utf-8'))
                features_cad = data_cad.get('features', [])
                if features_cad:
                    result['cadastre'] = features_cad[0]
        except Exception as err_cad:
            QgsMessageLog.logMessage(f"Recherche Cadastre: {str(err_cad)}", "GeoBan France", QgsMessageLog.INFO)

        if result['ban'] or result['cadastre']:
            self.finished.emit(result)
        else:
            self.error.emit("Aucune adresse ou parcelle trouvée à cet emplacement.")
