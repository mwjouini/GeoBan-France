# -*- coding: utf-8 -*-
"""
GeoBan France - Extension QGIS
Auteur : JOUINI Mohamed Wael
Licence : GPL v2+ / MIT
"""

import os
import json
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QListWidgetItem, QMessageBox, QWidget, QVBoxLayout, QCheckBox, QPushButton, QHBoxLayout, QAbstractItemView, QGroupBox, QListWidget, QTextEdit, QLabel, QApplication, QFileDialog
from qgis.PyQt.QtCore import Qt, QTimer, QObject, pyqtProperty, QPropertyAnimation, QRectF, QPointF, QSettings, QUrl, QVariant
from qgis.PyQt.QtGui import QColor, QIcon, QDesktopServices, QCursor
from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsGeometry, QgsRectangle, QgsWkbTypes,
    QgsVectorLayer, QgsFeature, QgsField, QgsRasterLayer, QgsApplication, QgsBookmark, QgsReferencedRectangle,
    QgsDistanceArea, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsFeatureRequest,
    QgsMapLayer, QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutItemShape,
    QgsSymbol, QgsSingleSymbolRenderer, QgsMarkerSymbol, QgsFillSymbol
)
from qgis.gui import QgsRubberBand, QgsVertexMarker, QgsMapCanvasItem, QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit
from osgeo import ogr

from .api_client import BANSearchThread, CadastreSearchThread

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'recherche_dialog_base.ui'))

class RechercheDialog(QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super(RechercheDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.setMinimumSize(920, 620)
        self.resize(920, 650)
        
        self.map_tool = None
        
        self.search_thread = None
        self.cadastre_thread = None
        
        self.markers = []
        self.polygon_rubber_bands = []
        
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate_polygon)
        self.animation_step = 0
        
        # Load Icons
        plugin_dir = os.path.dirname(__file__)
        self.setWindowIcon(QIcon(os.path.join(plugin_dir, 'icon.png')))
        self.tabWidget.setTabIcon(0, QIcon(os.path.join(plugin_dir, 'adresse.png')))
        self.tabWidget.setTabIcon(1, QIcon(os.path.join(plugin_dir, 'parcelle.png')))
        
        # Settings Tab
        self.settings_tab = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_tab)
        
        self.anim_checkbox = QCheckBox("Activer les animations (Marqueur et Polygone)")
        settings = QSettings()
        self.animations_enabled = settings.value("geoban/animations_enabled", True, type=bool)
        self.anim_checkbox.setChecked(self.animations_enabled)
        self.anim_checkbox.toggled.connect(self.toggle_animations)
        self.settings_layout.addWidget(self.anim_checkbox)
        
        from qgis.PyQt.QtWidgets import QFormLayout, QComboBox, QSpinBox, QSlider
        self.settings_form = QFormLayout()
        
        self.colorCombo = QComboBox()
        self.colorCombo.addItems(["Rouge", "Bleu", "Vert", "Noir"])
        self.colorCombo.setCurrentText(settings.value("geoban/marker_color", "Rouge", type=str))
        self.colorCombo.currentTextChanged.connect(self.on_color_changed)
        
        self.opacitySlider = QSlider(Qt.Horizontal)
        self.opacitySlider.setRange(0, 100)
        self.opacitySlider.setValue(settings.value("geoban/polygon_opacity", 50, type=int))
        self.opacitySlider.valueChanged.connect(self.on_color_changed)
        
        self.zoomSpinBox = QSpinBox()
        self.zoomSpinBox.setRange(100, 100000)
        self.zoomSpinBox.setSingleStep(500)
        self.zoomSpinBox.setValue(settings.value("geoban/zoom_level", 2500, type=int))
        self.zoomSpinBox.valueChanged.connect(self.on_zoom_changed)
        
        self.projSelector = QgsProjectionSelectionWidget()
        self.projSelector.setCrs(self.iface.mapCanvas().mapSettings().destinationCrs())
        
        self.settings_form.addRow("Couleur du repère :", self.colorCombo)
        self.settings_form.addRow("Opacité des polygones (%) :", self.opacitySlider)
        self.settings_form.addRow("Échelle de zoom par défaut : 1/", self.zoomSpinBox)
        self.settings_form.addRow("Système de projection (SCR) :", self.projSelector)
        
        self.settings_layout.addLayout(self.settings_form)
        
        self.settings_layout.addStretch()
        
        self.tabWidget.addTab(self.settings_tab, "Paramètres")
        self.tabWidget.setTabIcon(2, QIcon(os.path.join(plugin_dir, 'parametres.png')))
        
        # Outils SIG Tab
        self.outils_tab = QWidget()
        self.outils_layout = QVBoxLayout(self.outils_tab)
        
        # Analyse & Impression Group
        self.analyse_group = QGroupBox("Analyse & Impression")
        self.analyse_layout = QVBoxLayout()
        
        self.geomStatsLabel = QLabel("Sélectionnez une parcelle pour voir ses mesures.")
        self.geomStatsLabel.setStyleSheet("font-weight: bold; color: #34495E; margin-bottom: 5px;")
        self.geomStatsLabel.setWordWrap(True)
        
        self.printLayoutButton = QPushButton("Créer une Mise en Page (Impression)")
        self.printLayoutButton.clicked.connect(self.create_print_layout)
        
        self.spatialSelectButton = QPushButton("Sélection spatiale sur la couche active")
        self.spatialSelectButton.clicked.connect(self.perform_spatial_selection)
        self.spatialSelectButton.setToolTip("Sélectionne les entités de la couche sélectionnée dans QGIS qui intersectent cette parcelle.")
        
        self.analyse_layout.addWidget(self.geomStatsLabel)
        self.analyse_layout.addWidget(self.printLayoutButton)
        self.analyse_layout.addWidget(self.spatialSelectButton)
        self.analyse_group.setLayout(self.analyse_layout)
        self.outils_layout.addWidget(self.analyse_group)
        
        # Buffer
        self.buffer_group = QGroupBox("Périmètre de voisinage (Buffer)")
        self.buffer_layout = QFormLayout()
        self.bufferSpinBox = QSpinBox()
        self.bufferSpinBox.setRange(1, 10000)
        self.bufferSpinBox.setValue(50)
        self.bufferSpinBox.setSuffix(" m")
        self.bufferButton = QPushButton("Générer le périmètre")
        self.bufferButton.clicked.connect(self.generate_buffer)
        self.buffer_layout.addRow("Distance du buffer :", self.bufferSpinBox)
        self.buffer_layout.addRow("", self.bufferButton)
        self.buffer_group.setLayout(self.buffer_layout)
        
        # Bookmarks
        self.bookmark_group = QGroupBox("Signets Spatiaux (Bookmarks)")
        self.bookmark_layout = QVBoxLayout()
        self.bookmarkButton = QPushButton("Créer un Signet QGIS sur la sélection")
        self.bookmarkButton.clicked.connect(self.create_bookmark)
        self.bookmark_layout.addWidget(self.bookmarkButton)
        self.bookmark_group.setLayout(self.bookmark_layout)
        
        self.outils_layout.addWidget(self.buffer_group)
        self.outils_layout.addWidget(self.bookmark_group)
        self.outils_layout.addStretch()
        self.tabWidget.addTab(self.outils_tab, "Outils SIG")
        # Reuse mActionOptions or similar for icon, let's use mActionOptions
        self.tabWidget.setTabIcon(3, QgsApplication.getThemeIcon("/mActionOptions.svg"))
        
        # History Tab
        self.history_tab = QWidget()
        self.history_layout = QVBoxLayout(self.history_tab)
        self.historyListWidget = QListWidget()
        self.historyListWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.history_layout.addWidget(self.historyListWidget)
        self.tabWidget.addTab(self.history_tab, "Historique")
        self.tabWidget.setTabIcon(4, QgsApplication.getThemeIcon("/mActionHistory.svg"))
        
        # Identifier Tab
        self.identifier_tab = QWidget()
        self.identifier_layout = QVBoxLayout(self.identifier_tab)
        self.activateIdentifierButton = QPushButton("Activer l'outil d'identification (Clic carte)")
        self.activateIdentifierButton.setCheckable(True)
        self.activateIdentifierButton.clicked.connect(self.toggle_identifier_tool)
        self.identifierResultText = QTextEdit()
        self.identifierResultText.setReadOnly(True)
        self.identifierStreetViewButton = QPushButton("Ouvrir Street View")
        self.identifierStreetViewButton.setEnabled(False)
        self.identifierStreetViewButton.clicked.connect(self.identifier_open_street_view)
        
        self.identifier_layout.addWidget(self.activateIdentifierButton)
        self.identifier_layout.addWidget(self.identifierResultText)
        self.identifier_layout.addWidget(self.identifierStreetViewButton)
        self.tabWidget.addTab(self.identifier_tab, "Identifier")
        self.tabWidget.setTabIcon(5, QgsApplication.getThemeIcon("/mActionIdentify.svg"))
        
        # Details Label
        self.detailsLabel = QLabel("")
        self.detailsLabel.setWordWrap(True)
        self.detailsLabel.setStyleSheet("color: #7f8fa6; font-style: italic;")
        self.layout().insertWidget(self.layout().count() - 1, self.detailsLabel)
        
        # Extra buttons
        self.extra_buttons_layout = QHBoxLayout()
        self.toggleVisibilityCheckbox = QCheckBox("Afficher repère")
        self.toggleVisibilityCheckbox.setChecked(True)
        self.toggleVisibilityCheckbox.toggled.connect(self.toggle_visibility_realtime)
        
        self.copyCoordsButton = QPushButton("Copier Coordonnées")
        self.copyGeoJsonButton = QPushButton("Copier GeoJSON")
        self.exportKmlButton = QPushButton("Exporter KML")
        self.exportCsvButton = QPushButton("Exporter CSV")
        self.exportLayerButton = QPushButton("Créer Couche")
        self.streetViewButton = QPushButton("Street View")
        self.itineraryButton = QPushButton("Itinéraire")
        
        self.copyCoordsButton.setEnabled(False)
        self.copyGeoJsonButton.setEnabled(False)
        self.exportKmlButton.setEnabled(False)
        self.exportCsvButton.setEnabled(False)
        self.exportLayerButton.setEnabled(False)
        self.streetViewButton.setEnabled(False)
        self.itineraryButton.setEnabled(False)
        
        self.extra_buttons_layout.addWidget(self.toggleVisibilityCheckbox)
        self.extra_buttons_layout.addStretch()
        self.extra_buttons_layout.addWidget(self.copyGeoJsonButton)
        self.extra_buttons_layout.addWidget(self.copyCoordsButton)
        self.extra_buttons_layout.addWidget(self.exportCsvButton)
        self.extra_buttons_layout.addWidget(self.exportLayerButton)
        self.extra_buttons_layout.addWidget(self.itineraryButton)
        self.extra_buttons_layout.addWidget(self.streetViewButton)
        
        self.layout().insertLayout(self.layout().count() - 1, self.extra_buttons_layout)
        
        self.setStyleSheet("""
            QDialog { background-color: #f5f6fa; }
            QTabWidget::pane { border: 1px solid #dcdde1; border-radius: 4px; background: white; }
            QTabBar::tab { background: #e1e2e6; padding: 8px 15px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: white; border-bottom: none; font-weight: bold; color: #2C3E50; }
            QPushButton { background-color: #2C3E50; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #34495E; }
            QPushButton:disabled { background-color: #7f8fa6; }
            QLineEdit { padding: 5px; border: 1px solid #dcdde1; border-radius: 3px; }
            QListWidget { border: 1px solid #dcdde1; border-radius: 4px; background: white; }
            QListWidget::item:selected { background-color: #34495E; color: white; }
        """)
        
        # Setup Timers for auto-search
        self.ban_timer = QTimer()
        self.ban_timer.setSingleShot(True)
        self.ban_timer.timeout.connect(self.perform_search_ban)
        
        self.cadastre_timer = QTimer()
        self.cadastre_timer.setSingleShot(True)
        self.cadastre_timer.timeout.connect(self.perform_search_cadastre)
        
        self.cadastre_address_timer = QTimer()
        self.cadastre_address_timer.setSingleShot(True)
        self.cadastre_address_timer.timeout.connect(self.perform_search_cadastre_address_ban)
        
        self.resultsListWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cadastreListWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        
        self.cadastreSearchModeCombo.currentIndexChanged.connect(self.on_cadastre_mode_changed)
        self.on_cadastre_mode_changed(0)
        
        # Connect signals - BAN
        self.searchButton.clicked.connect(self.perform_search_ban)
        self.searchLineEdit.textChanged.connect(lambda: self.ban_timer.start(500))
        self.searchLineEdit.returnPressed.connect(self.perform_search_ban)
        self.resultsListWidget.itemSelectionChanged.connect(self.on_selection_changed)
        self.resultsListWidget.itemDoubleClicked.connect(self.zoom_to_selected)
        
        # Connect signals - Cadastre
        self.searchCadastreButton.clicked.connect(self.perform_search_cadastre)
        self.inseeLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.sectionLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.numeroLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.inseeLineEdit.returnPressed.connect(self.perform_search_cadastre)
        self.sectionLineEdit.returnPressed.connect(self.perform_search_cadastre)
        self.numeroLineEdit.returnPressed.connect(self.perform_search_cadastre)
        self.cadastreListWidget.itemSelectionChanged.connect(self.on_selection_changed)
        self.cadastreListWidget.itemDoubleClicked.connect(self.zoom_to_selected)
        
        self.cadastreAddressLineEdit.textChanged.connect(lambda: self.cadastre_address_timer.start(500))
        self.cadastreAddressListWidget.itemClicked.connect(self.on_cadastre_address_selected)
        
        # History
        self.historyListWidget.itemSelectionChanged.connect(self.on_selection_changed)
        self.historyListWidget.itemDoubleClicked.connect(self.zoom_to_selected)
        
        # Zoom Button (shared)
        self.zoomButton.clicked.connect(self.zoom_to_selected)
        
        self.copyCoordsButton.clicked.connect(self.copy_coordinates)
        self.copyGeoJsonButton.clicked.connect(self.copy_geojson)
        self.exportKmlButton.clicked.connect(self.export_kml)
        self.exportCsvButton.clicked.connect(self.export_csv)
        self.exportLayerButton.clicked.connect(self.export_to_layer)
        self.streetViewButton.clicked.connect(self.open_street_view)
        self.itineraryButton.clicked.connect(self.open_itinerary)
        
        self.tabWidget.currentChanged.connect(self.on_selection_changed)
        
    def on_cadastre_mode_changed(self, index):
        if index == 0:
            self.cadastreIdWidget.setVisible(True)
            self.cadastreAddressWidget.setVisible(False)
        else:
            self.cadastreIdWidget.setVisible(False)
            self.cadastreAddressWidget.setVisible(True)

    def perform_search_ban(self):
        query = self.searchLineEdit.text().strip()
        if len(query) < 3:
            return
            
        postcode = self.postcodeLineEdit.text().strip()
        citycode = self.citycodeLineEdit.text().strip()
            
        self.searchButton.setEnabled(False)
        self.resultsListWidget.clear()
        self.searchButton.setText("Recherche...")
        
        if hasattr(self, 'search_thread') and self.search_thread and self.search_thread.isRunning():
            self.search_thread.quit()
            self.search_thread.wait()
            
        self.search_thread = BANSearchThread(query, postcode, citycode)
        self.search_thread.finished.connect(self.on_ban_search_finished)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()

    def on_ban_search_finished(self, features):
        self.searchButton.setEnabled(True)
        self.searchButton.setText("Rechercher")
        
        if not features:
            QListWidgetItem("Aucun résultat trouvé.", self.resultsListWidget)
            return
            
        for feature in features:
            props = feature.get('properties', {})
            label = props.get('label', 'Adresse inconnue')
            context = props.get('context', '')
            item = QListWidgetItem(f"{label} ({context})")
            item.setData(Qt.UserRole, feature)
            self.resultsListWidget.addItem(item)
            
    def perform_search_cadastre(self):
        mode = self.cadastreSearchModeCombo.currentIndex()
        
        if mode == 0:
            insee = self.inseeLineEdit.text().strip()
            section = self.sectionLineEdit.text().strip().upper()
            numero = self.numeroLineEdit.text().strip().zfill(4) if self.numeroLineEdit.text().strip() else ""
            
            if len(insee) < 5:
                return
                
            self.searchCadastreButton.setEnabled(False)
            self.cadastreListWidget.clear()
            self.searchCadastreButton.setText("Recherche...")
            
            if hasattr(self, 'cadastre_thread') and self.cadastre_thread and self.cadastre_thread.isRunning():
                self.cadastre_thread.quit()
                self.cadastre_thread.wait()
                
            self.cadastre_thread = CadastreSearchThread(code_insee=insee, section=section, numero=numero)
            self.cadastre_thread.finished.connect(self.on_cadastre_search_finished)
            self.cadastre_thread.error.connect(self.on_cadastre_error)
            self.cadastre_thread.start()
        else:
            # The search is triggered by clicking the address in the cadastreAddressListWidget
            pass

    def perform_search_cadastre_address_ban(self):
        query = self.cadastreAddressLineEdit.text().strip()
        if len(query) < 3:
            return
            
        self.cadastreAddressListWidget.clear()
        
        if hasattr(self, 'cadastre_ban_thread') and self.cadastre_ban_thread and self.cadastre_ban_thread.isRunning():
            self.cadastre_ban_thread.quit()
            self.cadastre_ban_thread.wait()
            
        self.cadastre_ban_thread = BANSearchThread(query)
        self.cadastre_ban_thread.finished.connect(self.on_cadastre_address_ban_list_finished)
        self.cadastre_ban_thread.error.connect(self.on_cadastre_error)
        self.cadastre_ban_thread.start()
        
    def on_cadastre_address_ban_list_finished(self, features):
        self.cadastreAddressListWidget.clear()
        for feature in features:
            label = feature.get('properties', {}).get('label', 'Sans label')
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, feature)
            self.cadastreAddressListWidget.addItem(item)
            
    def on_cadastre_address_selected(self, item):
        feature = item.data(Qt.UserRole)
        if not feature: return
        
        geom = feature.get('geometry', {})
        coords = geom.get('coordinates', [])
        if len(coords) < 2: return
        
        lon, lat = coords[0], coords[1]
        self.searchCadastreButton.setText("Recherche Parcelle...")
        self.searchCadastreButton.setEnabled(False)
        self.cadastreListWidget.clear()
        
        if hasattr(self, 'cadastre_thread') and self.cadastre_thread and self.cadastre_thread.isRunning():
            self.cadastre_thread.quit()
            self.cadastre_thread.wait()
            
        self.cadastre_thread = CadastreSearchThread(lon=lon, lat=lat)
        self.cadastre_thread.finished.connect(self.on_cadastre_search_finished)
        self.cadastre_thread.error.connect(self.on_cadastre_error)
        self.cadastre_thread.start()

    def on_cadastre_search_finished(self, features):
        self.searchCadastreButton.setEnabled(True)
        self.searchCadastreButton.setText("Rechercher la parcelle")
        
        if not features:
            QListWidgetItem("Aucune parcelle trouvée.", self.cadastreListWidget)
            return
            
        for feature in features:
            props = feature.get('properties', {})
            id_parcelle = props.get('id', '')
            section = props.get('section', '')
            numero = props.get('numero', '')
            code_com = props.get('code_com', '')
            
            if not id_parcelle and code_com and section and numero:
                id_parcelle = f"{code_com}{section}{numero}"
            if not id_parcelle:
                id_parcelle = "Inconnu"
                
            contenance = props.get('contenance', '')
            
            texte = f"Parcelle {id_parcelle} (Sec: {section}, Num: {numero})"
            if contenance:
                texte += f" - {contenance} m²"
                
            item = QListWidgetItem(texte)
            item.setData(Qt.UserRole, feature)
            self.cadastreListWidget.addItem(item)
            
    def on_search_error(self, error_msg):
        self.searchButton.setEnabled(True)
        self.searchButton.setText("Rechercher")
        QMessageBox.warning(self, "Erreur API", f"Une erreur est survenue: {error_msg}")
        
    def on_cadastre_error(self, error_msg):
        self.searchCadastreButton.setEnabled(True)
        self.searchCadastreButton.setText("Rechercher la parcelle")
        QMessageBox.warning(self, "Erreur API", f"Une erreur est survenue: {error_msg}")

    def toggle_identifier_tool(self):
        if self.activateIdentifierButton.isChecked():
            if self.map_tool is None:
                self.map_tool = DialogReverseGeocodeTool(self.iface.mapCanvas(), self)
            self.iface.mapCanvas().setMapTool(self.map_tool)
        else:
            if self.map_tool:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)

    def get_selected_items(self):
        current_tab_idx = self.tabWidget.currentIndex()
        if current_tab_idx == 0:
            selected = self.resultsListWidget.selectedItems()
            if selected:
                return selected
        elif current_tab_idx == 1:
            selected = self.cadastreListWidget.selectedItems()
            if selected:
                return selected
        elif current_tab_idx == 4:
            selected = self.historyListWidget.selectedItems()
            if selected:
                return selected
                
        for list_widget in (self.resultsListWidget, self.cadastreListWidget, self.historyListWidget):
            selected = list_widget.selectedItems()
            if selected:
                return selected
        return []

    def on_selection_changed(self):
        selected = self.get_selected_items()
        has_selection = bool(selected and selected[0].data(Qt.UserRole))
        
        self.zoomButton.setEnabled(has_selection)
        self.exportLayerButton.setEnabled(has_selection)
        self.streetViewButton.setEnabled(has_selection)
        self.itineraryButton.setEnabled(has_selection)
        self.copyCoordsButton.setEnabled(has_selection)
        self.copyGeoJsonButton.setEnabled(has_selection)
        self.exportKmlButton.setEnabled(has_selection)
        self.exportCsvButton.setEnabled(has_selection)
        self.bufferButton.setEnabled(has_selection)
        self.bookmarkButton.setEnabled(has_selection)
        self.printLayoutButton.setEnabled(has_selection)
        self.spatialSelectButton.setEnabled(has_selection)
        
        # Update Geometry Stats
        if has_selection and len(selected) == 1:
            geom_dict = selected[0].data(Qt.UserRole).get('geometry', {})
            import json
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
            if ogr_geom:
                qgs_geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
                crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                crs_l93 = QgsCoordinateReferenceSystem("EPSG:2154")
                transform = QgsCoordinateTransform(crs_wgs84, crs_l93, QgsProject.instance())
                qgs_geom.transform(transform)
                
                if qgs_geom.type() == 0: # Point
                    pt = qgs_geom.asPoint()
                    self.geomStatsLabel.setText(f"Position (Lambert 93) : X = {pt.x():,.2f} m | Y = {pt.y():,.2f} m".replace(',', ' '))
                else:
                    da = QgsDistanceArea()
                    da.setSourceCrs(crs_l93, QgsProject.instance().transformContext())
                    da.setEllipsoid('GRS80')
                    
                    area_m2 = da.measureArea(qgs_geom)
                    perimeter_m = da.measurePerimeter(qgs_geom)
                    ha = area_m2 / 10000.0
                    self.geomStatsLabel.setText(f"Surface : {area_m2:,.1f} m² ({ha:,.2f} ha) | Périmètre : {perimeter_m:,.1f} m".replace(',', ' '))
        else:
            self.geomStatsLabel.setText("Sélectionnez une adresse ou parcelle pour voir ses mesures.")
        
        # Details Label
        if has_selection and len(selected) == 1:
            props = selected[0].data(Qt.UserRole).get('properties', {})
            contenance = props.get('contenance', None)
            if contenance:
                self.detailsLabel.setText(f"Détails : Contenance de {contenance} m²")
            else:
                self.detailsLabel.setText(f"Détails : {selected[0].text()}")
        elif len(selected) > 1:
            self.detailsLabel.setText(f"Détails : {len(selected)} éléments sélectionnés")
        else:
            self.detailsLabel.setText("")
            
    def toggle_animations(self, state):
        self.animations_enabled = state
        QSettings().setValue("geoban/animations_enabled", state)
        self.zoom_to_selected()

    def on_zoom_changed(self, value):
        QSettings().setValue("geoban/zoom_level", value)
        self.zoom_level = value
        
    def clear_rubber_bands(self):
        self.animation_timer.stop()
        for marker in self.markers:
            if hasattr(marker, 'anim'):
                marker.anim.stop()
            self.iface.mapCanvas().scene().removeItem(marker)
            marker.hide()
        self.markers.clear()
            
        for rb in self.polygon_rubber_bands:
            self.iface.mapCanvas().scene().removeItem(rb)
            rb.hide()
        self.polygon_rubber_bands.clear()
        
        if hasattr(self, 'marker') and self.marker:
            if hasattr(self.marker, 'anim'):
                self.marker.anim.stop()
            self.iface.mapCanvas().scene().removeItem(self.marker)
            self.marker.hide()
            self.marker = None
        
        self.iface.mapCanvas().refresh()
        
    def toggle_visibility_realtime(self, checked):
        for marker in self.markers:
            marker.setVisible(checked)
        for rb in self.polygon_rubber_bands:
            rb.setVisible(checked)
        if hasattr(self, 'marker') and self.marker:
            self.marker.setVisible(checked)
        self.iface.mapCanvas().refresh()

    def zoom_to_selected(self):
        selected_items = self.get_selected_items()
        if not selected_items:
            return
            
        current_tab_idx = self.tabWidget.currentIndex()
        # Add to history if a single item is clicked from search tabs
        if current_tab_idx in (0, 1) and len(selected_items) == 1:
            item = selected_items[0]
            if self.historyListWidget.count() == 0 or self.historyListWidget.item(0).text() != item.text():
                new_item = QListWidgetItem(item.text())
                new_item.setData(Qt.UserRole, item.data(Qt.UserRole))
                self.historyListWidget.insertItem(0, new_item)
                if self.historyListWidget.count() > 20:
                    self.historyListWidget.takeItem(20)
            
        self.clear_rubber_bands()
        
        settings = QSettings()
        color_name = settings.value("geoban/marker_color", "Rouge", type=str)
        color_map = {"Rouge": QColor(232, 65, 24), "Bleu": QColor(52, 152, 219), "Vert": QColor(46, 204, 113), "Noir": QColor(44, 62, 80)}
        self.marker_color = color_map.get(color_name, QColor(232, 65, 24))
        self.zoom_level = settings.value("geoban/zoom_level", 2500, type=int)
        self.polygon_opacity = settings.value("geoban/polygon_opacity", 50, type=int)
        
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_map = self.iface.mapCanvas().mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(crs_wgs84, crs_map, QgsProject.instance())
        
        combined_extent = None
        has_polygons = False
        
        for item in selected_items:
            feature = item.data(Qt.UserRole)
            if not feature:
                continue
                
            geometry_dict = feature.get('geometry', {})
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geometry_dict))
            if not ogr_geom:
                continue
                
            wkt = ogr_geom.ExportToWkt()
            qgs_geom = QgsGeometry.fromWkt(wkt)
            
            if not qgs_geom.isEmpty():
                qgs_geom.transform(transform)
                bbox = qgs_geom.boundingBox()
                
                if combined_extent is None:
                    combined_extent = bbox
                else:
                    combined_extent.combineExtentWith(bbox)
                
                if qgs_geom.type() == 0: # Point
                    point_map = qgs_geom.asPoint()
                    if self.animations_enabled:
                        marker = dynaLocationMarker(self.iface.mapCanvas(), point_map.x(), point_map.y(), self.marker_color)
                    else:
                        marker = QgsVertexMarker(self.iface.mapCanvas())
                        marker.setCenter(point_map)
                        marker.setColor(self.marker_color)
                        marker.setPenWidth(3)
                        marker.setIconType(QgsVertexMarker.ICON_CROSS)
                        marker.setIconSize(15)
                    marker.setVisible(self.toggleVisibilityCheckbox.isChecked())
                    self.markers.append(marker)
                    
                elif qgs_geom.type() in (1, 2): # Line or Polygon
                    has_polygons = True
                    rb = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
                    rb.setToGeometry(qgs_geom, None)
                    rb.setColor(self.marker_color)
                    rb.setWidth(3)
                    
                    alpha_color = QColor(self.marker_color)
                    alpha_color.setAlpha(int((self.polygon_opacity / 100.0) * 255))
                    rb.setFillColor(alpha_color)
                    
                    rb.setVisible(self.toggleVisibilityCheckbox.isChecked())
                    rb.show()
                    self.polygon_rubber_bands.append(rb)
        
        if combined_extent is not None:
            is_single_point = (combined_extent.width() == 0 and combined_extent.height() == 0)
            
            if is_single_point or (len(selected_items) == 1 and len(self.markers) == 1):
                self.iface.mapCanvas().setCenter(combined_extent.center())
                if self.iface.mapCanvas().scale() > self.zoom_level:
                    self.iface.mapCanvas().zoomScale(self.zoom_level)
            else:
                self.iface.mapCanvas().setExtent(combined_extent)
                self.iface.mapCanvas().zoomByFactor(1.2)
                
        if has_polygons and self.animations_enabled:
            self.animation_step = 0
            self.animation_timer.start(50)
            
        self.iface.mapCanvas().refresh()

    def trigger_animation_on_point(self, point_map):
        self.iface.mapCanvas().setCenter(point_map)
        if self.iface.mapCanvas().scale() > getattr(self, 'zoom_level', 2500):
            self.iface.mapCanvas().zoomScale(getattr(self, 'zoom_level', 2500))
            
        if hasattr(self, 'marker') and self.marker:
            if hasattr(self.marker, 'anim'):
                self.marker.anim.stop()
            self.iface.mapCanvas().scene().removeItem(self.marker)
            self.marker.hide()
            self.marker = None
            
        color_name = QSettings().value("geoban/marker_color", "Rouge", type=str)
        color_map = {"Rouge": QColor(232, 65, 24), "Bleu": QColor(52, 152, 219), "Vert": QColor(46, 204, 113), "Noir": QColor(44, 62, 80)}
        marker_color = color_map.get(color_name, QColor(232, 65, 24))
            
        if self.animations_enabled:
            self.marker = dynaLocationMarker(self.iface.mapCanvas(), point_map.x(), point_map.y(), marker_color)
        else:
            self.marker = QgsVertexMarker(self.iface.mapCanvas())
            self.marker.setCenter(point_map)
            self.marker.setColor(marker_color)
            self.marker.setPenWidth(3)
            self.marker.setIconType(QgsVertexMarker.ICON_CROSS)
            self.marker.setIconSize(15)
            
        self.marker.setVisible(self.toggleVisibilityCheckbox.isChecked())
        self.iface.mapCanvas().refresh()

    def export_to_layer(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        current_tab_idx = self.tabWidget.currentIndex()
        if current_tab_idx == 0:
            layer_name = "Adresse GeoBan"
        elif current_tab_idx == 1:
            layer_name = "Parcelle GeoBan"
        elif current_tab_idx == 4:
            layer_name = "Historique GeoBan"
        else:
            layer_name = "Sélection GeoBan"
            
        # Determine geometry type from the first item
        feature_data = selected[0].data(Qt.UserRole)
        geom_dict = feature_data.get('geometry', {})
        ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
        if not ogr_geom:
            return
        wkt = ogr_geom.ExportToWkt()
        first_qgs_geom = QgsGeometry.fromWkt(wkt)
        
        geom_type = "Point" if first_qgs_geom.type() == 0 else "Polygon"
        layer = QgsVectorLayer(f"{geom_type}?crs=epsg:4326", layer_name, "memory")
        pr = layer.dataProvider()
        
        pr.addAttributes([QgsField("Label", QVariant.String)])
        layer.updateFields()
        
        features_to_add = []
        for item in selected:
            feat_data = item.data(Qt.UserRole)
            if not feat_data:
                continue
            geom_dict = feat_data.get('geometry', {})
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
            wkt = ogr_geom.ExportToWkt()
            qgs_geom = QgsGeometry.fromWkt(wkt)
            
            f = QgsFeature()
            f.setGeometry(qgs_geom)
            f.setAttributes([item.text()])
            features_to_add.append(f)
            
        pr.addFeatures(features_to_add)
        layer.updateExtents()
        
        QgsProject.instance().addMapLayer(layer)
        QMessageBox.information(self, "Couche créée", f"La couche '{layer_name}' a été ajoutée au projet avec {len(features_to_add)} entité(s).")

    def copy_coordinates(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        crs_dest = self.projSelector.crs()
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs_wgs84, crs_dest, QgsProject.instance())
            
        coords_list = []
        for item in selected:
            geom_dict = item.data(Qt.UserRole).get('geometry', {})
            import json
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
            if ogr_geom:
                qgs_geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
                try:
                    qgs_geom.transform(transform)
                    if qgs_geom.type() == 0:
                        pt = qgs_geom.asPoint()
                        coords_list.append(f"{pt.x()}, {pt.y()}")
                    else:
                        centroid = qgs_geom.centroid().asPoint()
                        coords_list.append(f"{centroid.x()}, {centroid.y()}")
                except:
                    pass
                    
        text_to_copy = "\n".join(coords_list)
        QApplication.clipboard().setText(text_to_copy)
        self.iface.messageBar().pushMessage("Copié", f"Les coordonnées ont été copiées dans le presse-papiers ({crs_dest.authid()}).", level=0, duration=2)

    def export_csv(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        keys = set()
        for item in selected:
            keys.update(item.data(Qt.UserRole).get('properties', {}).keys())
        keys = list(keys)

        filepath, _ = QFileDialog.getSaveFileName(self, "Exporter en CSV", "", "CSV Files (*.csv)")
        if filepath:
            try:
                import csv
                with open(filepath, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["ID", "Label", "Longitude", "Latitude"] + keys)
                    for item in selected:
                        feature = item.data(Qt.UserRole)
                        feat_id = feature.get('properties', {}).get('id', '')
                        label = feature.get('properties', {}).get('label', 'Inconnu')
                        geom = feature.get('geometry', {})
                        lon, lat = "", ""
                        if geom.get('type') == 'Point':
                            coords = geom.get('coordinates', [])
                            if len(coords) >= 2:
                                lon, lat = coords[0], coords[1]
                        elif geom.get('type') in ['Polygon', 'MultiPolygon']:
                            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom))
                            if ogr_geom:
                                centroid = ogr_geom.Centroid()
                                lon, lat = centroid.GetX(), centroid.GetY()
                        
                        row = [feat_id, label, lon, lat]
                        for k in keys:
                            row.append(str(feature.get('properties', {}).get(k, '')))
                        writer.writerow(row)
                QMessageBox.information(self, "Export réussi", "Le fichier CSV a été généré avec succès.")
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Erreur lors de l'export CSV : {e}")

    def open_street_view(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        feature_data = selected[0].data(Qt.UserRole)
        geom_dict = feature_data.get('geometry', {})
        
        # Fallback to feature coordinates
        coords = geom_dict.get('coordinates', [])
        if not coords:
            return
            
        if geom_dict.get('type') == 'Point':
            lon, lat = coords[0], coords[1]
        elif geom_dict.get('type') in ['Polygon', 'MultiPolygon']:
            # Use centroid for polygons
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
            if ogr_geom:
                centroid = ogr_geom.Centroid()
                lon, lat = centroid.GetX(), centroid.GetY()
            else:
                return
        else:
            return
            
        url = f"http://maps.google.com/maps?q=&layer=c&cbll={lat},{lon}"
        QDesktopServices.openUrl(QUrl(url))

    def animate_polygon(self):
        import math
        self.animation_step += 1
        val = math.sin(self.animation_step * 0.2)
        
        base_opacity = int((getattr(self, 'polygon_opacity', 50) / 100.0) * 255)
        # Pulse alpha slightly around base_opacity
        alpha = min(255, max(0, base_opacity - 50 + int((val + 1) * 40)))
        
        anim_color = QColor(getattr(self, 'marker_color', QColor(232, 65, 24)))
        anim_color.setAlpha(alpha)
        
        for rb in self.polygon_rubber_bands:
            rb.setFillColor(anim_color)
            
        if self.animation_step > 200:
            self.animation_timer.stop()
            
    def on_color_changed(self, value=None):
        settings = QSettings()
        color_name = self.colorCombo.currentText()
        settings.setValue("geoban/marker_color", color_name)
        
        opacity = self.opacitySlider.value()
        settings.setValue("geoban/polygon_opacity", opacity)
        self.polygon_opacity = opacity
        
        color_map = {"Rouge": QColor(232, 65, 24), "Bleu": QColor(52, 152, 219), "Vert": QColor(46, 204, 113), "Noir": QColor(44, 62, 80)}
        self.marker_color = color_map.get(color_name, QColor(232, 65, 24))
        
        alpha_val = int((self.polygon_opacity / 100.0) * 255)
        
        for marker in getattr(self, 'markers', []):
            if hasattr(marker, 'setColor'): # QgsVertexMarker
                marker.setColor(self.marker_color)
            elif hasattr(marker, 'color'): # dynaLocationMarker
                marker.color = self.marker_color
                marker.update()
                
        if hasattr(self, 'marker') and self.marker:
            if hasattr(self.marker, 'setColor'):
                self.marker.setColor(self.marker_color)
            elif hasattr(self.marker, 'color'):
                self.marker.color = self.marker_color
                self.marker.update()
                
        for rb in getattr(self, 'polygon_rubber_bands', []):
            rb.setColor(self.marker_color)
            alpha_color = QColor(self.marker_color)
            alpha_color.setAlpha(alpha_val)
            rb.setFillColor(alpha_color)
            
    def identifier_open_street_view(self):
        if hasattr(self, 'identifier_lon') and hasattr(self, 'identifier_lat'):
            import webbrowser
            url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={self.identifier_lat},{self.identifier_lon}"
            webbrowser.open(url)
            
    def open_itinerary(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        feature_data = selected[0].data(Qt.UserRole)
        geom = feature_data.get('geometry', {})
        import json
        ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom))
        if ogr_geom:
            centroid = ogr_geom.Centroid()
            lat, lon = centroid.GetY(), centroid.GetX()
            import webbrowser
            url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
            webbrowser.open(url)
            
    def copy_geojson(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        feature_data = selected[0].data(Qt.UserRole)
        import json
        geojson_str = json.dumps(feature_data, indent=2, ensure_ascii=False)
        QApplication.clipboard().setText(geojson_str)
        self.iface.messageBar().pushMessage("Copié", "GeoJSON copié dans le presse-papiers.", level=0, duration=2)
        
    def create_bookmark(self):
        selected = self.get_selected_items()
        if not selected:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un élément d'abord.")
            return
            
        # Zoom to update map canvas extent
        self.zoom_to_selected()
        
        extent = self.iface.mapCanvas().extent()
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        
        name, ok = QInputDialog.getText(self, "Signet Spatial", "Nom du signet :", QLineEdit.Normal, selected[0].text())
        if ok and name:
            bookmark_manager = QgsProject.instance().bookmarkManager()
            bookmark = QgsBookmark()
            bookmark.setName(name)
            bookmark.setExtent(QgsReferencedRectangle(extent, crs))
            bookmark_manager.addBookmark(bookmark)
            self.iface.messageBar().pushMessage("Succès", f"Signet '{name}' créé avec succès.", level=0, duration=3)
            
    def generate_buffer(self):
        selected = self.get_selected_items()
        if not selected:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un élément d'abord.")
            return
            
        dist = self.bufferSpinBox.value()
        
        crs_dest = self.projSelector.crs()
        if crs_dest.isGeographic():
            # Force Lambert 93 for accurate metric buffering in France
            crs_dest = QgsCoordinateReferenceSystem("EPSG:2154")
            
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs_wgs84, crs_dest, QgsProject.instance())
        
        layer = QgsVectorLayer(f"Polygon?crs={crs_dest.authid()}", f"Périmètre {dist}m - GeoBan", "memory")
        pr = layer.dataProvider()
        pr.addAttributes([QgsField("Label", QVariant.String), QgsField("Distance", QVariant.Int)])
        layer.updateFields()
        
        features_to_add = []
        for item in selected:
            geom_dict = item.data(Qt.UserRole).get('geometry', {})
            import json
            ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
            if ogr_geom:
                qgs_geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
                try:
                    qgs_geom.transform(transform)
                    buffered_geom = qgs_geom.buffer(dist, 5) # 5 segments for arcs
                    if buffered_geom:
                        f = QgsFeature()
                        f.setGeometry(buffered_geom)
                        f.setAttributes([item.text(), dist])
                        features_to_add.append(f)
                except Exception as e:
                    pass
                    
        if features_to_add:
            pr.addFeatures(features_to_add)
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)
            QMessageBox.information(self, "Buffer créé", f"Le périmètre de {dist}m a été généré avec succès.")
        else:
            QMessageBox.warning(self, "Erreur", "Impossible de générer le périmètre. Vérifiez la géométrie.")

    def export_kml(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        filepath, _ = QFileDialog.getSaveFileName(self, "Exporter en KML", "", "KML Files (*.kml)")
        if filepath:
            from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext
            
            geom_type = "Polygon" if selected[0].data(Qt.UserRole).get('geometry', {}).get('type') in ('Polygon', 'MultiPolygon') else "Point"
            temp_layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:4326", "temp", "memory")
            pr = temp_layer.dataProvider()
            pr.addAttributes([QgsField("Label", QVariant.String)])
            temp_layer.updateFields()
            
            features_to_add = []
            import json
            for item in selected:
                geom_dict = item.data(Qt.UserRole).get('geometry', {})
                ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
                if ogr_geom:
                    qgs_geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
                    f = QgsFeature()
                    f.setGeometry(qgs_geom)
                    f.setAttributes([item.text()])
                    features_to_add.append(f)
                    
            pr.addFeatures(features_to_add)
            
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "KML"
            err, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(temp_layer, filepath, QgsCoordinateTransformContext(), options)
            if err == QgsVectorFileWriter.NoError:
                QMessageBox.information(self, "Export réussi", "Le fichier KML a été généré avec succès. Vous pouvez l'ouvrir dans Google Earth !")
            else:
                QMessageBox.warning(self, "Erreur d'export", f"Erreur lors de l'export KML : {err_msg}")

    def create_print_layout(self):
        selected = self.get_selected_items()
        if not selected:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un élément.")
            return
            
        self.zoom_to_selected()
        
        # Add high-visibility print highlight layer in QGIS project
        project = QgsProject.instance()
        old_layers = project.mapLayersByName("Sélection GeoBan (Impression)")
        for l in old_layers:
            project.removeMapLayer(l)

        feature_data = selected[0].data(Qt.UserRole)
        geom_dict = feature_data.get('geometry', {})
        ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
        if ogr_geom:
            wkt = ogr_geom.ExportToWkt()
            first_qgs_geom = QgsGeometry.fromWkt(wkt)
            geom_type = "Point" if first_qgs_geom.type() == 0 else "Polygon"
            
            highlight_layer = QgsVectorLayer(f"{geom_type}?crs=epsg:4326", "Sélection GeoBan (Impression)", "memory")
            pr = highlight_layer.dataProvider()
            pr.addAttributes([QgsField("Label", QVariant.String)])
            highlight_layer.updateFields()
            
            features_to_add = []
            for item in selected:
                feat_data = item.data(Qt.UserRole)
                if not feat_data: continue
                g_dict = feat_data.get('geometry', {})
                og = ogr.CreateGeometryFromJson(json.dumps(g_dict))
                if og:
                    qg = QgsGeometry.fromWkt(og.ExportToWkt())
                    f = QgsFeature()
                    f.setGeometry(qg)
                    f.setAttributes([item.text()])
                    features_to_add.append(f)
                    
            pr.addFeatures(features_to_add)
            highlight_layer.updateExtents()
            
            # Apply prominent cartographic styling
            if geom_type == "Point":
                symbol = QgsMarkerSymbol.createSimple({
                    'name': 'circle',
                    'color': '232,65,24,255',
                    'outline_color': '255,255,255,255',
                    'size': '5.0',
                    'outline_width': '0.8'
                })
            else:
                symbol = QgsFillSymbol.createSimple({
                    'color': '232,65,24,75',
                    'outline_color': '232,65,24,255',
                    'outline_width': '0.8'
                })
                
            renderer = QgsSingleSymbolRenderer(symbol)
            highlight_layer.setRenderer(renderer)
            highlight_layer.triggerRepaint()
            
            project.addMapLayer(highlight_layer)
        
        manager = project.layoutManager()
        
        layout_name = "Extrait GeoBan"
        layout = manager.layoutByName(layout_name)
        if layout:
            manager.removeLayout(layout)
            
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(layout_name)
        manager.addLayout(layout)
        
        # 1. Main Map Item
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(0, 0, 205, 168)
        map_item.setExtent(self.iface.mapCanvas().extent())
        map_item.setFrameEnabled(True)
        map_item.attemptMove(QgsLayoutPoint(10, 30, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(205, 168, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(map_item)
        
        # 2. Title Header Banner
        title_item = QgsLayoutItemLabel(layout)
        title_item.setText("Extrait Cartographique - " + selected[0].text())
        from qgis.PyQt.QtGui import QFont
        title_item.setFont(QFont("Arial", 14, QFont.Bold))
        title_item.setVAlign(Qt.AlignVCenter)
        title_item.setHAlign(Qt.AlignLeft)
        title_item.attemptMove(QgsLayoutPoint(10, 8, QgsUnitTypes.LayoutMillimeters))
        title_item.attemptResize(QgsLayoutSize(277, 18, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(title_item)
        
        # 3. Sidebar Panel Shape
        sidebar_shape = QgsLayoutItemShape(layout)
        sidebar_shape.setShapeType(QgsLayoutItemShape.Rectangle)
        sidebar_shape.setFrameEnabled(True)
        sidebar_shape.attemptMove(QgsLayoutPoint(220, 30, QgsUnitTypes.LayoutMillimeters))
        sidebar_shape.attemptResize(QgsLayoutSize(67, 168, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(sidebar_shape)
        
        # 4. Orientation (North Arrow)
        north_arrow = QgsLayoutItemPicture(layout)
        svg_paths = QgsApplication.svgPaths()
        found_svg = ""
        for p in svg_paths:
            candidate = os.path.join(p, "arrows", "NorthArrow_02.svg")
            if os.path.exists(candidate):
                found_svg = candidate
                break
            candidate4 = os.path.join(p, "arrows", "NorthArrow_04.svg")
            if os.path.exists(candidate4):
                found_svg = candidate4
                break
        if found_svg:
            north_arrow.setPicturePath(found_svg)
        north_arrow.attemptMove(QgsLayoutPoint(243.5, 33, QgsUnitTypes.LayoutMillimeters))
        north_arrow.attemptResize(QgsLayoutSize(20, 20, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(north_arrow)
        
        # 5. Legend
        legend_item = QgsLayoutItemLegend(layout)
        legend_item.setLinkedMap(map_item)
        legend_item.setTitle("Légende")
        legend_item.attemptMove(QgsLayoutPoint(223, 58, QgsUnitTypes.LayoutMillimeters))
        legend_item.attemptResize(QgsLayoutSize(61, 65, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(legend_item)
        
        # 6. Dynamic Scalebar adapting automatically to zoom level
        scalebar = QgsLayoutItemScaleBar(layout)
        scalebar.setLinkedMap(map_item)
        scalebar.setStyle('Single Box')
        scalebar.setNumberOfSegments(2)
        
        extent = map_item.extent()
        width_m = extent.width()
        if self.iface.mapCanvas().mapSettings().destinationCrs().isGeographic():
            center_lat = (extent.yMinimum() + extent.yMaximum()) / 2.0
            import math
            width_m = extent.width() * 111000.0 * math.cos(math.radians(center_lat))
            
        raw_segment = width_m / 8.0
        nice_steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]
        best_units = 100
        for step in nice_steps:
            best_units = step
            if step >= raw_segment:
                break
                
        if best_units >= 1000:
            scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
            scalebar.setUnitsPerSegment(best_units / 1000.0)
            scalebar.setUnitLabel("km")
        else:
            scalebar.setUnits(QgsUnitTypes.DistanceMeters)
            scalebar.setUnitsPerSegment(best_units)
            scalebar.setUnitLabel("m")
            
        scalebar.attemptMove(QgsLayoutPoint(223, 128, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(scalebar)
        
        # 7. Source and Metadata Text
        import datetime
        today_str = datetime.date.today().strftime("%d/%m/%Y")
        crs_authid = self.iface.mapCanvas().mapSettings().destinationCrs().authid()
        
        source_item = QgsLayoutItemLabel(layout)
        source_item.setText(
            f"Sources Données :\n"
            f"• Base Adresse Nationale (BAN)\n"
            f"• APICarto Cadastre (IGN)\n\n"
            f"Projection : {crs_authid}\n"
            f"Date : {today_str}\n"
            f"Auteur : JOUINI Mohamed Wael\n"
            f"GeoBan France (QGIS)"
        )
        source_item.setFont(QFont("Arial", 8))
        source_item.attemptMove(QgsLayoutPoint(223, 146, QgsUnitTypes.LayoutMillimeters))
        source_item.attemptResize(QgsLayoutSize(61, 50, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(source_item)
        
        self.iface.openLayoutDesigner(layout)
        
    def perform_spatial_selection(self):
        active_layer = self.iface.activeLayer()
        if not active_layer or active_layer.type() != QgsMapLayer.VectorLayer:
            QMessageBox.warning(self, "Erreur", "Veuillez d'abord sélectionner une couche vectorielle (polygones, lignes, points) dans le panneau des couches de QGIS.")
            return
            
        selected = self.get_selected_items()
        if not selected:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un élément.")
            return
            
        geom_dict = selected[0].data(Qt.UserRole).get('geometry', {})
        import json
        ogr_geom = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
        if not ogr_geom: return
        
        qgs_geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
        if qgs_geom.isEmpty(): return

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if crs_wgs84 != active_layer.crs():
            transform = QgsCoordinateTransform(crs_wgs84, active_layer.crs(), QgsProject.instance())
            qgs_geom.transform(transform)
            
        qgs_geom = qgs_geom.makeValid()
        
        # Buffer slightly to absorb PROJ / GEOS floating point precision noise
        if active_layer.crs().isGeographic():
            search_geom = qgs_geom.buffer(0.00005, 3)
        else:
            search_geom = qgs_geom.buffer(0.5, 3)
            
        search_geom = search_geom.makeValid()
        
        request = QgsFeatureRequest().setFilterRect(search_geom.boundingBox())
        selected_ids = []
        for feat in active_layer.getFeatures(request):
            feat_geom = feat.geometry()
            if not feat_geom.isEmpty():
                feat_geom_valid = feat_geom.makeValid()
                if search_geom.intersects(feat_geom_valid) or qgs_geom.intersects(feat_geom_valid):
                    selected_ids.append(feat.id())
                
        active_layer.selectByIds(selected_ids)
        count = active_layer.selectedFeatureCount()
        QMessageBox.information(self, "Sélection spatiale", f"{count} entité(s) sélectionnée(s) dans la couche '{active_layer.name()}'.")

    def closeEvent(self, event):
        self.clear_rubber_bands()
        super().closeEvent(event)

class dynaLocationMarker(QgsMapCanvasItem):
    class aniObject(QObject):
        def __init__(self):
            super(dynaLocationMarker.aniObject, self).__init__()
            self._size = 0
            self.startsize = 0
            self.maxsize = 32

        @pyqtProperty(int)
        def size(self): return self._size

        @size.setter
        def size(self, value): self._size = value

    def __init__(self, canvas, x, y, color):
        self.canvas = canvas
        self.color = color
        from qgis.core import QgsPointXY
        self.map_pos = QgsPointXY(x, y)
        self.aniObject = dynaLocationMarker.aniObject()
        QgsMapCanvasItem.__init__(self, canvas)
        self.anim = QPropertyAnimation(self.aniObject, b"size")
        self.anim.setDuration(1000)
        self.anim.setStartValue(self.aniObject.startsize)
        self.anim.setEndValue(self.aniObject.maxsize)
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self.value_changed)
        self.anim.start()

    @property
    def size(self): return self.aniObject.size
    @property
    def halfsize(self): return self.aniObject.maxsize / 2.0
    @property
    def maxsize(self): return self.aniObject.maxsize
    def value_changed(self, value): self.update()

    def paint(self, painter, xxx, xxx2):
        from qgis.PyQt.QtGui import QPainter
        self.setCenter(self.map_pos)
        rect = QRectF(0 - self.halfsize, 0 - self.halfsize, self.size, self.size)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.color) 
        painter.setPen(self.color) 
        painter.drawEllipse(QPointF(0,0), float(self.size), float(self.size))

    def boundingRect(self): return QRectF(-self.halfsize * 2.0, -self.halfsize * 2.0, 2.0 * self.maxsize, 2.0 * self.maxsize)
    def setCenter(self, map_pos): self.map_pos = map_pos; self.setPos(self.toCanvasCoordinates(self.map_pos))
    def updatePosition(self): self.setCenter(self.map_pos)

from qgis.gui import QgsMapToolEmitPoint

class DialogReverseGeocodeTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, dialog):
        super().__init__(canvas)
        self.canvas = canvas
        self.dialog = dialog
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, e):
        point_map = self.toMapCoordinates(e.pos())
        
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_map = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(crs_map, crs_wgs84, QgsProject.instance())
        
        try:
            point_wgs84 = transform.transform(point_map)
        except Exception:
            return
            
        lon, lat = point_wgs84.x(), point_wgs84.y()
        
        self.dialog.identifierResultText.setText("Recherche de l'adresse en cours...")
        self.dialog.tabWidget.setCurrentIndex(5) # Go to identifier tab (index 5)
        
        self.dialog.identifier_lon = lon
        self.dialog.identifier_lat = lat
        self.dialog.identifierStreetViewButton.setEnabled(True)
        
        if hasattr(self, 'rev_geocode_thread') and self.rev_geocode_thread and self.rev_geocode_thread.isRunning():
            self.rev_geocode_thread.quit()
            self.rev_geocode_thread.wait()
            
        from .api_client import ReverseGeocodingThread
        self.rev_geocode_thread = ReverseGeocodingThread(lon, lat)
        self.rev_geocode_thread.finished.connect(self.on_finished)
        self.rev_geocode_thread.error.connect(self.on_error)
        self.rev_geocode_thread.start()

    def deactivate(self):
        self.dialog.activateIdentifierButton.setChecked(False)
        super().deactivate()

    def on_finished(self, feature):
        if not feature:
            self.dialog.identifierResultText.setText("Aucune adresse trouvée à cet emplacement.")
            return
            
        props = feature.get('properties', {})
        label = props.get('label', 'Adresse inconnue')
        context = props.get('context', '')
        
        self.dialog.identifierResultText.setText(f"Adresse trouvée:\n{label}\n\nContexte:\n{context}")
        
    def on_error(self, err):
        self.dialog.identifierResultText.setText(f"Erreur API: {err}")
