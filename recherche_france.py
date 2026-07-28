# -*- coding: utf-8 -*-
"""
GeoBan France - Module d'intégration QGIS (Menu & Barre d'outils)
Auteur : JOUINI Mohamed Wael
"""

import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from .recherche_dialog import RechercheDialog

class RechercheFrance:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = 'GeoBan France'
        self.dialog = None
        self.locator_filter = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), 'GeoBan France', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)
        self.actions.append(self.action)

        from .ban_locator_filter import BanLocatorFilter
        self.locator_filter = BanLocatorFilter(self)
        self.iface.registerLocatorFilter(self.locator_filter)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self.locator_filter:
            self.iface.deregisterLocatorFilter(self.locator_filter)

    def run(self):
        if not self.dialog:
            self.dialog = RechercheDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.activateWindow()
