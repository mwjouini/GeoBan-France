# -*- coding: utf-8 -*-
"""
GeoBan France - Extension QGIS
Auteur : JOUINI Mohamed Wael
Licence : GPL v2+ / MIT
"""

def classFactory(iface):
    from .recherche_france import RechercheFrance
    return RechercheFrance(iface)
