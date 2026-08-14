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

        self.sv_layer_action = QAction("Couverture Street View (Lignes Bleues)", self.iface.mainWindow())
        self.sv_layer_action.triggered.connect(self.toggle_sv_layer)
        self.iface.addPluginToMenu(self.menu, self.sv_layer_action)
        self.actions.append(self.sv_layer_action)

        self.sv_click_action = QAction("Outil Clic Direct Street View", self.iface.mainWindow())
        self.sv_click_action.triggered.connect(self.activate_sv_tool)
        self.iface.addPluginToMenu(self.menu, self.sv_click_action)
        self.actions.append(self.sv_click_action)

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

    def toggle_sv_layer(self):
        if not self.dialog:
            self.dialog = RechercheDialog(self.iface, self.iface.mainWindow())
        self.dialog.toggle_street_view_layer()

    def activate_sv_tool(self):
        if not self.dialog:
            self.dialog = RechercheDialog(self.iface, self.iface.mainWindow())
        self.dialog.tabWidget.setCurrentWidget(self.dialog.identifier_tab)
        self.dialog.activateStreetViewToolButton.setChecked(True)
        self.dialog.toggle_street_view_tool(True)
        self.dialog.show()
        self.dialog.activateWindow()
