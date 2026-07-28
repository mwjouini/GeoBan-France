# -*- coding: utf-8 -*-
"""
GeoBan France - Module d'intégration QGIS (Menu & Barre d'outils)
Auteur : JOUINI Mohamed Wael
"""

import os
import base64
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
        self._ensure_icon()
        
    def _ensure_icon(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        if not os.path.exists(icon_path):
            try:
                b64_data = "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAYdEVYdFNvZnR3YXJlAHBhaW50Lm5ldCA0LjEuNWRjKzEAAAIxSURBVGhD7ZhPiMw4HMe/v9+MZmd2/syKtbBkWaw47O5QDhQH3e5BcThQHOzOigPlQHFY3CgHBw6L3cGiA8XBHV3HwsLiZlmS2Zl/szO/v+d5M+1s5teZtH/s9wNf08yb9/fzTX6Z/E3QNE3TNE3TNE3TNE3TNE3TNP8xJIT4g4H/U2EYBq7rzvR6vS+WZb0F8ALAQ/p4B+B1FEXPMpnMa5qj0bE4l8uN9/v9L67rLluWdQPABYB5AEsAFgAsAVji58cAzgG4AuAagPue511Np9PPaY5WxxJCCH6I/0i/31/heS7553meEELcI/s0z0hL0YmEED+QxKk8zyV/k/5Jv6d5Wl0bYQixI32M4zi/MpnMi9F05v4JId6T/p3neX/SHFk2o8g/6TfLspJ83Xg24nneh7I0+Y/I+x3j2YkQYo/I8w9Zmvyn1L8az0bY//A7WZr8R+T9jvHsROq/TZYm/yn1r8azEWkIfpOl8s/zvFf0O82xS2iK41j/j4eSJMk113UTP+bW2KOPt0EQLGj9sUtoimz9+8hJkmSN67o/6bN2/i+0/tilNMXo+k9zXZf8V/RZO/8XWn/sUpqiXP8bvu+T/5k+a+f/Qutv1f8V8m9HlmXx8aP0WTv/F1p/7FKaojzPe5/OZAaZTKbfbrc/0Wft/F9o/bFLaQohxJc0x+A7uVxuPJ1O12hP7fxfaP2xS2mKqan0HwghxL20hX8zjuMTaU9N0zRN0zRN0zRN0zRN0zRN07SmU/UPL74r/o9Q+FkAAAAASUVORK5CYII="
                with open(icon_path, "wb") as fh:
                    fh.write(base64.b64decode(b64_data))
            except Exception:
                pass

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
