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
            with urllib.request.urlopen(req, timeout=10) as response:
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
            with urllib.request.urlopen(req, timeout=10) as response:
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
        try:
            params = {'lon': self.lon, 'lat': self.lat}
            url = "https://api-adresse.data.gouv.fr/reverse/?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (QGIS GeoBan France)'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))
