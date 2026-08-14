# -*- coding: utf-8 -*-
"""
GeoBan France - Client API REST (BAN & APICarto Cadastre)
Auteur : JOUINI Mohamed Wael
"""

import json
import urllib.parse
from qgis.PyQt.QtCore import pyqtSignal, QThread, QUrl
from qgis.core import QgsMessageLog, QgsBlockingNetworkRequest
from qgis.PyQt.QtNetwork import QNetworkRequest

def safe_urlopen(url_str, timeout=10000):
    if not url_str.startswith('https://'):
        raise ValueError("Seul le protocole HTTPS est autorisé.")
    req = QgsBlockingNetworkRequest()
    request = QNetworkRequest(QUrl(url_str))
    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, 'Mozilla/5.0 (QGIS GeoBan France)')
    # Block until request completes
    err = req.get(request, forceRefresh=True)
    if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise Exception(f"Erreur réseau: {req.errorMessage()}")
    reply = req.reply()
    return reply.content().data().decode('utf-8')

class BANSearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query, postcode=None, citycode=None, search_type=None):
        super().__init__()
        self.query = query
        self.postcode = postcode
        self.citycode = citycode
        self.search_type = search_type

    def run(self):
        try:
            params = {'q': self.query, 'limit': 20}
            if self.postcode:
                params['postcode'] = self.postcode
            if self.citycode:
                params['citycode'] = self.citycode
            if self.search_type:
                params['type'] = self.search_type

            url = "https://api-adresse.data.gouv.fr/search/?" + urllib.parse.urlencode(params)
            response_text = safe_urlopen(url)
            data = json.loads(response_text)
            features = data.get('features', [])
            self.finished.emit(features)
        except Exception as e:
            self.error.emit(str(e))

class CadastreSearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, code_insee=None, section=None, numero=None, prefixe=None, lon=None, lat=None):
        super().__init__()
        self.code_insee = code_insee
        self.section = section
        self.numero = numero
        self.prefixe = prefixe
        self.lon = lon
        self.lat = lat

    def run(self):
        try:
            if self.lon is not None and self.lat is not None:
                geom_json = json.dumps({"type": "Point", "coordinates": [self.lon, self.lat]})
                url = "https://apicarto.ign.fr/api/cadastre/parcelle?geom=" + urllib.parse.quote(geom_json)
            else:
                params = {}
                if self.code_insee:
                    params['code_insee'] = self.code_insee
                
                sec = (self.section or '').strip().upper()
                pref = (self.prefixe or '').strip()

                # If user entered letters (like ZB, ZA) in prefixe field and section is empty, auto-detect as section!
                if pref and not sec and not pref.isdigit():
                    sec = pref.upper()
                    pref = ''

                if sec:
                    params['section'] = sec
                if self.numero:
                    params['numero'] = self.numero.zfill(4) if self.numero else ''
                if pref and pref.isdigit():
                    params['prefixe'] = pref.zfill(3)

                url = "https://apicarto.ign.fr/api/cadastre/parcelle?" + urllib.parse.urlencode(params)
                
            response_text = safe_urlopen(url)
            data = json.loads(response_text)
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

        # 1. Query BAN Reverse Geocoding API
        try:
            params = {'lon': self.lon, 'lat': self.lat}
            url_ban = "https://api-adresse.data.gouv.fr/reverse/?" + urllib.parse.urlencode(params)
            response_text = safe_urlopen(url_ban)
            data_ban = json.loads(response_text)
            features = data_ban.get('features', [])
            if features:
                result['ban'] = features[0]
        except Exception as err_ban:
            QgsMessageLog.logMessage(f"Recherche BAN: {str(err_ban)}", "GeoBan France", QgsMessageLog.INFO)

        # 2. Query APICarto Cadastre Reverse Geocoding API by geometry point
        try:
            geom_json = json.dumps({"type": "Point", "coordinates": [self.lon, self.lat]})
            url_cad = "https://apicarto.ign.fr/api/cadastre/parcelle?geom=" + urllib.parse.quote(geom_json)
            response_text = safe_urlopen(url_cad)
            data_cad = json.loads(response_text)
            features_cad = data_cad.get('features', [])
            if features_cad:
                result['cadastre'] = features_cad[0]
        except Exception as err_cad:
            QgsMessageLog.logMessage(f"Recherche Cadastre: {str(err_cad)}", "GeoBan France", QgsMessageLog.INFO)

        if result['ban'] or result['cadastre']:
            self.finished.emit(result)
        else:
            self.error.emit("Aucune adresse ou parcelle trouvée à cet emplacement.")
