# -*- coding: utf-8 -*-
"""
GeoBan France - Extension QGIS
Auteur : JOUINI Mohamed Wael
Licence : GPL v2+ / MIT
"""

import os
import json
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QDialog, QListWidgetItem, QMessageBox, QWidget, QVBoxLayout, QCheckBox,
    QPushButton, QHBoxLayout, QAbstractItemView, QGroupBox, QListWidget,
    QTextEdit, QLabel, QApplication, QFileDialog, QInputDialog, QLineEdit,
    QFormLayout, QFrame, QComboBox, QCompleter
)
from qgis.PyQt.QtCore import Qt, QTimer, QObject, pyqtProperty, QPropertyAnimation, QRectF, QPointF, QSettings, QUrl, QVariant, QStringListModel
from qgis.PyQt.QtGui import QColor, QIcon, QDesktopServices, QCursor
from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsGeometry, QgsRectangle, QgsWkbTypes,
    QgsVectorLayer, QgsFeature, QgsField, QgsRasterLayer, QgsApplication, QgsBookmark, QgsReferencedRectangle,
    QgsDistanceArea, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsFeatureRequest,
    QgsMapLayer, QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutItemShape,
    QgsSymbol, QgsSingleSymbolRenderer, QgsMarkerSymbol, QgsFillSymbol, QgsMessageLog
)
from qgis.gui import QgsRubberBand, QgsVertexMarker, QgsMapCanvasItem, QgsProjectionSelectionWidget
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
        
        from qgis.PyQt.QtWidgets import QSpinBox, QSlider
        self.settings_form = QFormLayout()
        
        self.colorCombo = QComboBox()
        self.colorCombo.addItems(["Rouge", "Bleu", "Vert", "Noir"])
        self.colorCombo.setCurrentText(settings.value("geoban/marker_color", "Rouge", type=str))
        self.colorCombo.currentTextChanged.connect(self.on_color_changed)
        
        self.opacitySlider = QSlider(Qt.Orientation.Horizontal)
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
        self.tabWidget.setTabIcon(self.tabWidget.indexOf(self.settings_tab), QIcon(os.path.join(plugin_dir, 'parametres.png')))
        
        # Outils SIG Tab
        self.outils_tab = QWidget()
        self.outils_layout = QVBoxLayout(self.outils_tab)
        
        # Analyse & Impression Group
        self.analyse_group = QGroupBox("Analyse & Impression")
        self.analyse_layout = QVBoxLayout()
        
        self.geomStatsLabel = QLabel("Sélectionnez une parcelle pour voir ses mesures.")
        self.geomStatsLabel.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
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
        self.tabWidget.setTabIcon(self.tabWidget.indexOf(self.outils_tab), QgsApplication.getThemeIcon("/mActionOptions.svg"))
        
        # Coordonnées Tab
        self.coords_tab = QWidget()
        self.coords_layout = QVBoxLayout(self.coords_tab)
        
        self.coords_form = QFormLayout()
        self.coordXLineEdit = QLineEdit()
        self.coordXLineEdit.setPlaceholderText("Ex: 2.3488 ou 600123.45")
        self.coordYLineEdit = QLineEdit()
        self.coordYLineEdit.setPlaceholderText("Ex: 48.8534 ou 6861234.56")
        
        self.coordAutoCrsCheckBox = QCheckBox("Détection automatique du système (WGS84 / Lambert 93)")
        self.coordAutoCrsCheckBox.setChecked(True)
        self.coordAutoCrsCheckBox.toggled.connect(self.on_toggle_auto_crs)
        
        self.coordAutoStatusLabel = QLabel("Système : Détection automatique active")
        self.coordAutoStatusLabel.setStyleSheet("font-weight: bold;")
        
        self.coordProjSelector = QgsProjectionSelectionWidget()
        self.coordProjSelector.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.coordProjSelector.setEnabled(False)
        
        self.coordXLineEdit.textChanged.connect(self.auto_detect_coords_crs)
        self.coordYLineEdit.textChanged.connect(self.auto_detect_coords_crs)
        
        self.coords_form.addRow("X / Longitude :", self.coordXLineEdit)
        self.coords_form.addRow("Y / Latitude :", self.coordYLineEdit)
        self.coords_form.addRow("", self.coordAutoCrsCheckBox)
        self.coords_form.addRow("Détection :", self.coordAutoStatusLabel)
        self.coords_form.addRow("Système :", self.coordProjSelector)
        
        self.searchCoordsButton = QPushButton("Placer sur la carte")
        self.searchCoordsButton.setIcon(QgsApplication.getThemeIcon("/mActionCapturePoint.svg"))
        self.searchCoordsButton.clicked.connect(self.search_by_coordinates)
        
        # Section Conversion de coordonnées (Intégrée dans la page, SANS POPUP MODALE)
        self.convertGroupBox = QGroupBox("Conversion de système de coordonnées")
        self.convertLayout = QVBoxLayout(self.convertGroupBox)
        
        self.convertForm = QFormLayout()
        self.convertProjSelector = QgsProjectionSelectionWidget()
        self.convertProjSelector.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
        self.convertForm.addRow("Convertir vers :", self.convertProjSelector)
        
        self.convertCoordsButton = QPushButton("Calculer la conversion")
        self.convertCoordsButton.setIcon(QgsApplication.getThemeIcon("/mActionCalculateField.svg"))
        self.convertCoordsButton.clicked.connect(self.convert_coordinates)
        
        self.convertResultFrame = QFrame()
        self.convertResultLayout = QVBoxLayout(self.convertResultFrame)
        self.convertResultForm = QFormLayout()
        
        self.convertResultX = QLineEdit()
        self.convertResultX.setReadOnly(True)
        self.convertResultY = QLineEdit()
        self.convertResultY.setReadOnly(True)
        
        self.convertResultForm.addRow("Résultat X :", self.convertResultX)
        self.convertResultForm.addRow("Résultat Y :", self.convertResultY)
        
        self.convertButtonsLayout = QHBoxLayout()
        self.copyConvertedCoordsButton = QPushButton("Copier X, Y")
        self.copyConvertedCoordsButton.setIcon(QgsApplication.getThemeIcon("/mActionEditCopy.svg"))
        self.copyConvertedCoordsButton.clicked.connect(self.copy_converted_coordinates)
        
        self.placeConvertedCoordsButton = QPushButton("Placer le résultat sur la carte")
        self.placeConvertedCoordsButton.setIcon(QgsApplication.getThemeIcon("/mActionCapturePoint.svg"))
        self.placeConvertedCoordsButton.clicked.connect(self.place_converted_coordinates)
        
        self.convertButtonsLayout.addWidget(self.copyConvertedCoordsButton)
        self.convertButtonsLayout.addWidget(self.placeConvertedCoordsButton)
        
        self.convertResultLayout.addLayout(self.convertResultForm)
        self.convertResultLayout.addLayout(self.convertButtonsLayout)
        self.convertResultFrame.setVisible(False)
        
        self.convertLayout.addLayout(self.convertForm)
        self.convertLayout.addWidget(self.convertCoordsButton)
        self.convertLayout.addWidget(self.convertResultFrame)
        
        self.coords_layout.addLayout(self.coords_form)
        self.coords_layout.addWidget(self.searchCoordsButton)
        self.coords_layout.addWidget(self.convertGroupBox)
        self.coords_layout.addStretch()
        
        self.tabWidget.addTab(self.coords_tab, "Coordonnées")
        self.tabWidget.setTabIcon(self.tabWidget.indexOf(self.coords_tab), QgsApplication.getThemeIcon("/mActionCapturePoint.svg"))

        # Import Tab
        self.import_tab = QWidget()
        self.import_layout = QVBoxLayout(self.import_tab)
        
        self.importFileButton = QPushButton("Parcourir fichier (CSV / Excel)")
        self.importFileButton.setIcon(QgsApplication.getThemeIcon("/mActionFileOpen.svg"))
        self.importFileButton.clicked.connect(self.browse_import_file)
        self.importFilePath = QLineEdit()
        self.importFilePath.setReadOnly(True)
        
        self.import_form = QFormLayout()
        self.importDelimiterCombo = QComboBox()
        self.importDelimiterCombo.addItems([
            "Automatique (Détection)",
            "Point-virgule (;)",
            "Virgule (,)",
            "Tabulation (Tab)",
            "Espace (Espace)",
            "Pipe (|)"
        ])
        self.importDelimiterCombo.currentIndexChanged.connect(self.on_delimiter_changed)
        
        self.importStatusLabel = QLabel("Aucun fichier chargé")
        self.importStatusLabel.setStyleSheet("color: #666666; font-style: italic;")
        
        self.importColX = QComboBox()
        self.importColY = QComboBox()
        self.importColX.currentIndexChanged.connect(self.on_import_cols_changed)
        self.importColY.currentIndexChanged.connect(self.on_import_cols_changed)
        
        self.importCrsSelector = QgsProjectionSelectionWidget()
        self.importCrsSelector.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        self.importCrsStatusLabel = QLabel("Système non vérifié")
        self.importCrsStatusLabel.setStyleSheet("color: #666666; font-style: italic;")
        
        self.import_form.addRow("Séparateur (CSV) :", self.importDelimiterCombo)
        self.import_form.addRow("Analyse :", self.importStatusLabel)
        self.import_form.addRow("Colonne X / Longitude :", self.importColX)
        self.import_form.addRow("Colonne Y / Latitude :", self.importColY)
        self.import_form.addRow("Détection SCR :", self.importCrsStatusLabel)
        self.import_form.addRow("Système de coordonnées :", self.importCrsSelector)
        
        self.importRunButton = QPushButton("Créer la couche de points")
        self.importRunButton.setIcon(QgsApplication.getThemeIcon("/mActionAddDelimitedTextLayer.svg"))
        self.importRunButton.setEnabled(False)
        self.importRunButton.clicked.connect(self.run_import_layer)
        
        self.import_layout.addWidget(self.importFileButton)
        self.import_layout.addWidget(self.importFilePath)
        self.import_layout.addLayout(self.import_form)
        self.import_layout.addWidget(self.importRunButton)
        self.import_layout.addStretch()
        
        self.tabWidget.addTab(self.import_tab, "Import")
        self.tabWidget.setTabIcon(self.tabWidget.indexOf(self.import_tab), QgsApplication.getThemeIcon("/mActionAddDelimitedTextLayer.svg"))
        
        # History (Hidden off-tab widget for backwards compatibility)
        self.historyListWidget = QListWidget()
        
        # Identifier Tab
        self.identifier_tab = QWidget()
        self.identifier_layout = QVBoxLayout(self.identifier_tab)
        self.activateIdentifierButton = QPushButton("1. Activer l'outil d'identification (Clic carte)")
        self.activateIdentifierButton.setCheckable(True)
        self.activateIdentifierButton.clicked.connect(self.toggle_identifier_tool)
        
        self.streetViewCoverageButton = QPushButton("Afficher Couverture Street View (Lignes bleues sur la carte)")
        self.streetViewCoverageButton.setCheckable(True)
        self.streetViewCoverageButton.clicked.connect(self.toggle_street_view_layer)
        
        self.activateStreetViewToolButton = QPushButton("2. Outil Clic Direct Street View (Pointer sur la carte)")
        self.activateStreetViewToolButton.setCheckable(True)
        self.activateStreetViewToolButton.clicked.connect(self.toggle_street_view_tool)

        self.identifierResultText = QTextEdit()
        self.identifierResultText.setReadOnly(True)
        
        self.identifier_layout.addWidget(self.activateIdentifierButton)
        self.identifier_layout.addWidget(self.streetViewCoverageButton)
        self.identifier_layout.addWidget(self.activateStreetViewToolButton)
        self.identifier_layout.addWidget(self.identifierResultText)
        self.tabWidget.addTab(self.identifier_tab, "Identifier")
        self.tabWidget.setTabIcon(self.tabWidget.indexOf(self.identifier_tab), QgsApplication.getThemeIcon("/mActionIdentify.svg"))
        
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
        
        self.resultsListWidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cadastreListWidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        self.cadastreSearchModeCombo.currentIndexChanged.connect(self.on_cadastre_mode_changed)
        self.on_cadastre_mode_changed(0)
        
        # BAN Search Type Filter
        self.banTypeCombo = QComboBox()
        self.banTypeCombo.addItems([
            "Tous types (Adresse, Lieu-dit, Rue, Commune)",
            "Lieu-dit / Hameau",
            "Voie / Rue",
            "Numéro d'adresse",
            "Commune"
        ])
        self.banTypeCombo.setToolTip("Filtrer par type de lieu (ex: Lieu-dit / Hameau)")
        self.banTypeCombo.currentIndexChanged.connect(self.perform_search_ban)
        
        if self.searchLineEdit.parentWidget() and self.searchLineEdit.parentWidget().layout():
            parent_lay = self.searchLineEdit.parentWidget().layout()
            idx = parent_lay.indexOf(self.searchLineEdit)
            if idx != -1:
                parent_lay.insertWidget(idx + 1, self.banTypeCombo)
        
        # Connect signals - BAN
        self.searchButton.clicked.connect(self.perform_search_ban)
        self.searchLineEdit.textChanged.connect(lambda: self.ban_timer.start(500))
        self.searchLineEdit.returnPressed.connect(self.perform_search_ban)
        if hasattr(self, 'lieuDitLineEdit'):
            self.lieuDitLineEdit.textChanged.connect(lambda: self.ban_timer.start(500))
            self.lieuDitLineEdit.returnPressed.connect(self.perform_search_ban)
        self.resultsListWidget.itemSelectionChanged.connect(self.on_selection_changed)
        self.resultsListWidget.itemDoubleClicked.connect(self.zoom_to_selected)
        
        # Connect signals - Cadastre
        self.searchCadastreButton.clicked.connect(self.perform_search_cadastre)
        self.inseeLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.prefixeLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.sectionLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.numeroLineEdit.textChanged.connect(lambda: self.cadastre_timer.start(500))
        self.inseeLineEdit.returnPressed.connect(self.perform_search_cadastre)
        self.prefixeLineEdit.returnPressed.connect(self.perform_search_cadastre)
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
        self.setup_autocomplete()
        
    def setup_autocomplete(self):
        self.lieu_dit_model = QStringListModel(self)
        self.lieu_dit_completer = QCompleter(self.lieu_dit_model, self)
        self.lieu_dit_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.lieu_dit_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        if hasattr(self, 'lieuDitLineEdit'):
            self.lieuDitLineEdit.setCompleter(self.lieu_dit_completer)
            self.lieu_dit_suggest_timer = QTimer(self)
            self.lieu_dit_suggest_timer.setSingleShot(True)
            self.lieu_dit_suggest_timer.setInterval(300)
            self.lieu_dit_suggest_timer.timeout.connect(self.fetch_lieu_dit_suggestions)
            self.lieuDitLineEdit.textChanged.connect(lambda: self.lieu_dit_suggest_timer.start())

        self.addr_model = QStringListModel(self)
        self.addr_completer = QCompleter(self.addr_model, self)
        self.addr_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.addr_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        if hasattr(self, 'searchLineEdit'):
            self.searchLineEdit.setCompleter(self.addr_completer)
            self.addr_suggest_timer = QTimer(self)
            self.addr_suggest_timer.setSingleShot(True)
            self.addr_suggest_timer.setInterval(300)
            self.addr_suggest_timer.timeout.connect(self.fetch_address_suggestions)
            self.searchLineEdit.textChanged.connect(lambda: self.addr_suggest_timer.start())

        if hasattr(self, 'cadastreAddressLineEdit'):
            self.cadastre_addr_model = QStringListModel(self)
            self.cadastre_addr_completer = QCompleter(self.cadastre_addr_model, self)
            self.cadastre_addr_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.cadastre_addr_completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.cadastreAddressLineEdit.setCompleter(self.cadastre_addr_completer)
            self.cadastre_suggest_timer = QTimer(self)
            self.cadastre_suggest_timer.setSingleShot(True)
            self.cadastre_suggest_timer.setInterval(300)
            self.cadastre_suggest_timer.timeout.connect(self.fetch_cadastre_suggestions)
            self.cadastreAddressLineEdit.textChanged.connect(lambda: self.cadastre_suggest_timer.start())

    def fetch_lieu_dit_suggestions(self):
        text = self.lieuDitLineEdit.text().strip() if hasattr(self, 'lieuDitLineEdit') else ''
        if len(text) < 3:
            return
        postcode = self.postcodeLineEdit.text().strip() if hasattr(self, 'postcodeLineEdit') else None
        citycode = self.citycodeLineEdit.text().strip() if hasattr(self, 'citycodeLineEdit') else None
        
        if hasattr(self, 'suggest_lieu_thread') and self.suggest_lieu_thread and self.suggest_lieu_thread.isRunning():
            self.suggest_lieu_thread.quit()
            self.suggest_lieu_thread.wait()
            
        self.suggest_lieu_thread = BANSearchThread(text, postcode=postcode, citycode=citycode, search_type='locality')
        self.suggest_lieu_thread.finished.connect(self.on_lieu_dit_suggestions_finished)
        self.suggest_lieu_thread.error.connect(self.on_suggestion_error)
        self.suggest_lieu_thread.start()

    def on_lieu_dit_suggestions_finished(self, features):
        suggestions = []
        for f in features:
            props = f.get('properties', {})
            label = props.get('label') or props.get('name')
            if label and label not in suggestions:
                suggestions.append(label)
        self.lieu_dit_model.setStringList(suggestions)

    def fetch_address_suggestions(self):
        text = self.searchLineEdit.text().strip() if hasattr(self, 'searchLineEdit') else ''
        if len(text) < 3:
            return
        postcode = self.postcodeLineEdit.text().strip() if hasattr(self, 'postcodeLineEdit') else None
        citycode = self.citycodeLineEdit.text().strip() if hasattr(self, 'citycodeLineEdit') else None
        
        if hasattr(self, 'suggest_addr_thread') and self.suggest_addr_thread and self.suggest_addr_thread.isRunning():
            self.suggest_addr_thread.quit()
            self.suggest_addr_thread.wait()
            
        self.suggest_addr_thread = BANSearchThread(text, postcode=postcode, citycode=citycode)
        self.suggest_addr_thread.finished.connect(self.on_address_suggestions_finished)
        self.suggest_addr_thread.error.connect(self.on_suggestion_error)
        self.suggest_addr_thread.start()

    def on_address_suggestions_finished(self, features):
        suggestions = []
        for f in features:
            props = f.get('properties', {})
            label = props.get('label')
            if label and label not in suggestions:
                suggestions.append(label)
        self.addr_model.setStringList(suggestions)

    def fetch_cadastre_suggestions(self):
        text = self.cadastreAddressLineEdit.text().strip() if hasattr(self, 'cadastreAddressLineEdit') else ''
        if len(text) < 3:
            return
        mode_idx = self.cadastreSearchModeCombo.currentIndex() if hasattr(self, 'cadastreSearchModeCombo') else 1
        stype = 'locality' if mode_idx == 2 else None
        
        if hasattr(self, 'suggest_cad_thread') and self.suggest_cad_thread and self.suggest_cad_thread.isRunning():
            self.suggest_cad_thread.quit()
            self.suggest_cad_thread.wait()
            
        self.suggest_cad_thread = BANSearchThread(text, search_type=stype)
        self.suggest_cad_thread.finished.connect(self.on_cadastre_suggestions_finished)
        self.suggest_cad_thread.error.connect(self.on_suggestion_error)
        self.suggest_cad_thread.start()

    def on_cadastre_suggestions_finished(self, features):
        suggestions = []
        for f in features:
            props = f.get('properties', {})
            label = props.get('label') or props.get('name')
            if label and label not in suggestions:
                suggestions.append(label)
        self.cadastre_addr_model.setStringList(suggestions)

    def on_suggestion_error(self, err_msg):
        QgsMessageLog.logMessage(f"Suggestion autocomplétion: {err_msg}", "GeoBan France", QgsMessageLog.INFO)

    def on_cadastre_mode_changed(self, index):
        if index == 0:
            self.cadastreIdWidget.setVisible(True)
            self.cadastreAddressWidget.setVisible(False)
        elif index == 1:
            self.cadastreIdWidget.setVisible(False)
            self.cadastreAddressWidget.setVisible(True)
            self.cadastreAddressLineEdit.setPlaceholderText("Saisissez une adresse...")
        elif index == 2:
            self.cadastreIdWidget.setVisible(False)
            self.cadastreAddressWidget.setVisible(True)
            self.cadastreAddressLineEdit.setPlaceholderText("Saisissez un Lieu-dit / Hameau...")

    def perform_search_ban(self):
        query = self.searchLineEdit.text().strip()
        lieu_dit = self.lieuDitLineEdit.text().strip() if hasattr(self, 'lieuDitLineEdit') else ''
        
        if not query and lieu_dit:
            query = lieu_dit
            search_type = 'locality'
        elif not query and not lieu_dit:
            return
        elif query and lieu_dit:
            search_types = [None, 'locality', 'street', 'housenumber', 'municipality']
            type_idx = self.banTypeCombo.currentIndex() if hasattr(self, 'banTypeCombo') else 0
            search_type = search_types[type_idx] if type_idx < len(search_types) else None
            if search_type is None:
                query = f"{query} {lieu_dit}"
        else:
            search_types = [None, 'locality', 'street', 'housenumber', 'municipality']
            type_idx = self.banTypeCombo.currentIndex() if hasattr(self, 'banTypeCombo') else 0
            search_type = search_types[type_idx] if type_idx < len(search_types) else None
            
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
            
        self.search_thread = BANSearchThread(query, postcode, citycode, search_type=search_type)
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
            ftype = props.get('type', '')
            
            type_badge = ""
            if ftype == 'locality':
                type_badge = "📍 [Lieu-dit] "
            elif ftype == 'street':
                type_badge = "🛣️ [Rue] "
            elif ftype == 'housenumber':
                type_badge = "🏠 [N°] "
            elif ftype == 'municipality':
                type_badge = "🏛️ [Commune] "

            item = QListWidgetItem(f"{type_badge}{label} ({context})")
            item.setData(Qt.ItemDataRole.UserRole, feature)
            self.resultsListWidget.addItem(item)
            
    def perform_search_cadastre(self):
        mode = self.cadastreSearchModeCombo.currentIndex()
        
        if mode == 0:
            insee = self.inseeLineEdit.text().strip()
            prefixe = self.prefixeLineEdit.text().strip()
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
                
            self.cadastre_thread = CadastreSearchThread(code_insee=insee, section=section, numero=numero, prefixe=prefixe)
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
            item.setData(Qt.ItemDataRole.UserRole, feature)
            self.cadastreAddressListWidget.addItem(item)
            
    def on_cadastre_address_selected(self, item):
        feature = item.data(Qt.ItemDataRole.UserRole)
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

        search_sec = self.sectionLineEdit.text().strip().upper()
        search_pref = self.prefixeLineEdit.text().strip().upper()
        target_sec = search_sec or (search_pref if not search_pref.isdigit() else "")

        count_added = 0
        for feature in features:
            props = feature.get('properties', {})
            id_parcelle = props.get('id', '')
            section = props.get('section', '').strip().upper()
            numero = props.get('numero', '')
            code_com = props.get('code_com', '')

            if target_sec and section != target_sec:
                continue

            if not id_parcelle and code_com and section and numero:
                id_parcelle = f"{code_com}{section}{numero}"
            if not id_parcelle:
                id_parcelle = "Inconnu"
                
            contenance = props.get('contenance', '')
            
            texte = f"Parcelle {id_parcelle} (Sec: {section}, Num: {numero})"
            if contenance:
                texte += f" - {contenance} m²"
                
            item = QListWidgetItem(texte)
            item.setData(Qt.ItemDataRole.UserRole, feature)
            self.cadastreListWidget.addItem(item)
            count_added += 1

        if count_added == 0:
            QListWidgetItem("Aucune parcelle ne correspond aux critères saisis.", self.cadastreListWidget)
            
    def on_search_error(self, error_msg):
        self.searchButton.setEnabled(True)
        self.searchButton.setText("Rechercher")
        QMessageBox.warning(self, "Erreur API", f"Une erreur est survenue: {error_msg}")
        
    def on_cadastre_error(self, error_msg):
        self.searchCadastreButton.setEnabled(True)
        self.searchCadastreButton.setText("Rechercher la parcelle")
        QMessageBox.warning(self, "Erreur API", f"Une erreur est survenue: {error_msg}")


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
        elif current_tab_idx == 6:
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
        has_selection = bool(selected and selected[0].data(Qt.ItemDataRole.UserRole))
        
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
            geom_dict = selected[0].data(Qt.ItemDataRole.UserRole).get('geometry', {})
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
            props = selected[0].data(Qt.ItemDataRole.UserRole).get('properties', {})
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
                new_item.setData(Qt.ItemDataRole.UserRole, item.data(Qt.ItemDataRole.UserRole))
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
            feature = item.data(Qt.ItemDataRole.UserRole)
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
                        marker.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
                        marker.setIconSize(15)
                    marker.setVisible(self.toggleVisibilityCheckbox.isChecked())
                    self.markers.append(marker)
                    
                elif qgs_geom.type() in (1, 2): # Line or Polygon
                    has_polygons = True
                    rb = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.GeometryType.PolygonGeometry)
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
            self.marker.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
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
        elif current_tab_idx == 6:
            layer_name = "Historique GeoBan"
        else:
            layer_name = "Sélection GeoBan"
            
        # Determine geometry type from the first item
        feature_data = selected[0].data(Qt.ItemDataRole.UserRole)
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
            feat_data = item.data(Qt.ItemDataRole.UserRole)
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
            geom_dict = item.data(Qt.ItemDataRole.UserRole).get('geometry', {})
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
                except Exception as err:
                    QgsMessageLog.logMessage(f"Erreur calcul coordonnées: {str(err)}", "GeoBan France", QgsMessageLog.INFO)
                    
        text_to_copy = "\n".join(coords_list)
        QApplication.clipboard().setText(text_to_copy)
        self.iface.messageBar().pushMessage("Copié", f"Les coordonnées ont été copiées dans le presse-papiers ({crs_dest.authid()}).", level=0, duration=2)

    def export_csv(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        keys = set()
        for item in selected:
            keys.update(item.data(Qt.ItemDataRole.UserRole).get('properties', {}).keys())
        keys = list(keys)

        filepath, _ = QFileDialog.getSaveFileName(self, "Exporter en CSV", "", "CSV Files (*.csv)")
        if filepath:
            try:
                import csv
                with open(filepath, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["ID", "Label", "Longitude", "Latitude"] + keys)
                    for item in selected:
                        feature = item.data(Qt.ItemDataRole.UserRole)
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

    def get_nearest_street_coords(self, lat, lon):
        """Snaps coordinates to the nearest street/address via BAN reverse geocoding to prevent Google Street View from opening on a black screen in fields/polygons."""
        try:
            from .api_client import safe_urlopen
            url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}&limit=1"
            response_text = safe_urlopen(url)
            if response_text:
                data = json.loads(response_text)
                features = data.get('features', [])
                if features:
                    coords = features[0].get('geometry', {}).get('coordinates', [])
                    if len(coords) >= 2:
                        return coords[1], coords[0] # lat, lon
        except Exception as e:
            QgsMessageLog.logMessage(f"Auto-snap Street View: {e}", "GeoBan France", QgsMessageLog.INFO)
        return lat, lon

    def open_street_view(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        feature_data = selected[0].data(Qt.ItemDataRole.UserRole)
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
            
        street_lat, street_lon = self.get_nearest_street_coords(lat, lon)
        url = f"https://www.google.com/maps?q={street_lat},{street_lon}&layer=c&cbll={street_lat},{street_lon}"
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
            lat = getattr(self, 'identifier_street_lat', self.identifier_lat)
            lon = getattr(self, 'identifier_street_lon', self.identifier_lon)
            street_lat, street_lon = self.get_nearest_street_coords(lat, lon)
            url = f"https://www.google.com/maps?q={street_lat},{street_lon}&layer=c&cbll={street_lat},{street_lon}"
            QDesktopServices.openUrl(QUrl(url))

    def toggle_identifier_tool(self, checked):
        if checked:
            if hasattr(self, 'streetview_tool') and self.iface.mapCanvas().mapTool() == self.streetview_tool:
                self.iface.mapCanvas().unsetMapTool(self.streetview_tool)
                if hasattr(self, 'activateStreetViewToolButton'):
                    self.activateStreetViewToolButton.setChecked(False)
                    self.activateStreetViewToolButton.setText("2. Outil Clic Direct Street View (Pointer sur la carte)")

            if not hasattr(self, 'identifier_tool') or not self.identifier_tool:
                self.identifier_tool = DialogReverseGeocodeTool(self.iface.mapCanvas(), self)
            self.iface.mapCanvas().setMapTool(self.identifier_tool)
            self.activateIdentifierButton.setText("Outil d'identification actif (Cliquez sur la carte)")
        else:
            if hasattr(self, 'identifier_tool') and self.iface.mapCanvas().mapTool() == self.identifier_tool:
                self.iface.mapCanvas().unsetMapTool(self.identifier_tool)
            self.activateIdentifierButton.setText("1. Activer l'outil d'identification (Clic carte)")

    def toggle_street_view_layer(self, checked=None):
        """Ajoute ou supprime le calque bleu de couverture Google Street View de la carte QGIS."""
        layer_name = "Couverture Google Street View"
        project = QgsProject.instance()
        existing_layers = [layer for layer in project.mapLayers().values() if layer.name() == layer_name]

        if checked is None or isinstance(checked, bool) is False:
            checked = not bool(existing_layers)

        if checked:
            if not existing_layers:
                uri = "type=xyz&url=https://mts2.google.com/mapslt?lyrs%3Dsvv%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D%26w%3D256%26h%3D256%26hl%3Dfr%26style%3D40,18&zmax=18&zmin=0&http-header:referer="
                rlayer = QgsRasterLayer(uri, layer_name, 'wms')
                if rlayer.isValid():
                    project.addMapLayer(rlayer)
                    if hasattr(self, 'streetViewCoverageButton'):
                        self.streetViewCoverageButton.setChecked(True)
                        self.streetViewCoverageButton.setText("Masquer Couverture Street View (Lignes bleues)")
                else:
                    QMessageBox.warning(self, "Erreur", "Impossible de charger la couche de couverture Street View.")
        else:
            if existing_layers:
                project.removeMapLayers([layer.id() for layer in existing_layers])
            if hasattr(self, 'streetViewCoverageButton'):
                self.streetViewCoverageButton.setChecked(False)
                self.streetViewCoverageButton.setText("Afficher Couverture Street View (Lignes bleues sur la carte)")
        if self.iface and self.iface.mapCanvas():
            self.iface.mapCanvas().refresh()

    def toggle_street_view_tool(self, checked):
        if checked:
            if hasattr(self, 'identifier_tool') and self.iface.mapCanvas().mapTool() == self.identifier_tool:
                self.iface.mapCanvas().unsetMapTool(self.identifier_tool)
                if hasattr(self, 'activateIdentifierButton'):
                    self.activateIdentifierButton.setChecked(False)
                    self.activateIdentifierButton.setText("1. Activer l'outil d'identification (Clic carte)")

            # Activer automatiquement la couche bleue de couverture si pas déjà chargée !
            self.toggle_street_view_layer(True)
            
            if not hasattr(self, 'streetview_tool') or not self.streetview_tool:
                self.streetview_tool = DialogStreetViewDirectTool(self.iface.mapCanvas(), self)
                
            self.iface.mapCanvas().setMapTool(self.streetview_tool)
            self.activateStreetViewToolButton.setText("Outil Street View Actif (Cliquez sur la ligne bleue)")
        else:
            if hasattr(self, 'streetview_tool') and self.iface.mapCanvas().mapTool() == self.streetview_tool:
                self.iface.mapCanvas().unsetMapTool(self.streetview_tool)
            self.activateStreetViewToolButton.setText("2. Outil Clic Direct Street View (Pointer sur la carte)")
            
    def open_itinerary(self):
        selected = self.get_selected_items()
        if not selected:
            return
            
        feature_data = selected[0].data(Qt.ItemDataRole.UserRole)
        geom = feature_data.get('geometry', {})
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
            
        feature_data = selected[0].data(Qt.ItemDataRole.UserRole)
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
        
        name, ok = QInputDialog.getText(self, "Signet Spatial", "Nom du signet :", QLineEdit.EchoMode.Normal, selected[0].text())
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
            geom_dict = item.data(Qt.ItemDataRole.UserRole).get('geometry', {})
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
                except Exception as err:
                    QgsMessageLog.logMessage(f"Erreur création buffer: {str(err)}", "GeoBan France", QgsMessageLog.INFO)
                    
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
            
            geom_type = "Polygon" if selected[0].data(Qt.ItemDataRole.UserRole).get('geometry', {}).get('type') in ('Polygon', 'MultiPolygon') else "Point"
            temp_layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:4326", "temp", "memory")
            pr = temp_layer.dataProvider()
            pr.addAttributes([QgsField("Label", QVariant.String)])
            temp_layer.updateFields()
            
            features_to_add = []
            for item in selected:
                geom_dict = item.data(Qt.ItemDataRole.UserRole).get('geometry', {})
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
            if err == QgsVectorFileWriter.WriterError.NoError:
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
        for layer_item in old_layers:
            project.removeMapLayer(layer_item)

        feature_data = selected[0].data(Qt.ItemDataRole.UserRole)
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
                feat_data = item.data(Qt.ItemDataRole.UserRole)
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
        map_item.attemptMove(QgsLayoutPoint(10, 30, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(205, 168, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        layout.addLayoutItem(map_item)
        
        # 2. Title Header Banner
        title_item = QgsLayoutItemLabel(layout)
        title_item.setText("Extrait Cartographique - " + selected[0].text())
        from qgis.PyQt.QtGui import QFont
        title_item.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title_item.setVAlign(Qt.AlignmentFlag.AlignVCenter)
        title_item.setHAlign(Qt.AlignmentFlag.AlignLeft)
        title_item.attemptMove(QgsLayoutPoint(10, 8, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        title_item.attemptResize(QgsLayoutSize(277, 18, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        layout.addLayoutItem(title_item)
        
        # 3. Sidebar Panel Shape
        sidebar_shape = QgsLayoutItemShape(layout)
        sidebar_shape.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
        sidebar_shape.setFrameEnabled(True)
        sidebar_shape.attemptMove(QgsLayoutPoint(220, 30, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        sidebar_shape.attemptResize(QgsLayoutSize(67, 168, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
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
        north_arrow.attemptMove(QgsLayoutPoint(243.5, 33, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        north_arrow.attemptResize(QgsLayoutSize(20, 20, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        layout.addLayoutItem(north_arrow)
        
        # 5. Legend
        legend_item = QgsLayoutItemLegend(layout)
        legend_item.setLinkedMap(map_item)
        legend_item.setTitle("Légende")
        legend_item.attemptMove(QgsLayoutPoint(223, 58, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        legend_item.attemptResize(QgsLayoutSize(61, 65, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
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
            scalebar.setUnits(QgsUnitTypes.DistanceUnit.DistanceKilometers)
            scalebar.setUnitsPerSegment(best_units / 1000.0)
            scalebar.setUnitLabel("km")
        else:
            scalebar.setUnits(QgsUnitTypes.DistanceUnit.DistanceMeters)
            scalebar.setUnitsPerSegment(best_units)
            scalebar.setUnitLabel("m")
            
        scalebar.attemptMove(QgsLayoutPoint(223, 128, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
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
        source_item.attemptMove(QgsLayoutPoint(223, 146, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        source_item.attemptResize(QgsLayoutSize(61, 50, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        layout.addLayoutItem(source_item)
        
        self.iface.openLayoutDesigner(layout)
        
    def perform_spatial_selection(self):
        active_layer = self.iface.activeLayer()
        if not active_layer or active_layer.type() != QgsMapLayer.LayerType.VectorLayer:
            QMessageBox.warning(self, "Erreur", "Veuillez d'abord sélectionner une couche vectorielle (polygones, lignes, points) dans le panneau des couches de QGIS.")
            return
            
        selected = self.get_selected_items()
        if not selected:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un élément.")
            return
            
        geom_dict = selected[0].data(Qt.ItemDataRole.UserRole).get('geometry', {})
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

    def on_toggle_auto_crs(self, checked):
        self.coordProjSelector.setEnabled(not checked)
        if checked:
            self.auto_detect_coords_crs()
        else:
            self.coordAutoStatusLabel.setText("Système : Sélection manuelle active")
            self.coordAutoStatusLabel.setStyleSheet("color: #666666;")

    def auto_detect_coords_crs(self):
        if not hasattr(self, 'coordAutoCrsCheckBox') or not self.coordAutoCrsCheckBox.isChecked():
            return
        x_str = self.coordXLineEdit.text().strip().replace(',', '.')
        y_str = self.coordYLineEdit.text().strip().replace(',', '.')
        if not x_str or not y_str:
            self.coordAutoStatusLabel.setText("Entrez X et Y pour auto-détecter")
            self.coordAutoStatusLabel.setStyleSheet("color: #888888;")
            return
        try:
            x = float(x_str)
            y = float(y_str)
        except ValueError:
            self.coordAutoStatusLabel.setText("Coordonnées non numériques")
            self.coordAutoStatusLabel.setStyleSheet("color: #cc0000;")
            return

        if -180 <= x <= 180 and -90 <= y <= 90:
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
            self.coordProjSelector.setCrs(crs)
            self.coordAutoStatusLabel.setText("✔ Détecté : WGS 84 (EPSG:4326)")
            self.coordAutoStatusLabel.setStyleSheet("color: #008800; font-weight: bold;")
        elif 100000 <= x <= 1300000 and 6000000 <= y <= 7200000:
            crs = QgsCoordinateReferenceSystem("EPSG:2154")
            self.coordProjSelector.setCrs(crs)
            self.coordAutoStatusLabel.setText("✔ Détecté : Lambert 93 (EPSG:2154)")
            self.coordAutoStatusLabel.setStyleSheet("color: #008800; font-weight: bold;")
        elif x > 1000:
            self.coordAutoStatusLabel.setText("Coordonnées projetées (Vérifiez le système)")
            self.coordAutoStatusLabel.setStyleSheet("color: #cc6600;")
        else:
            self.coordAutoStatusLabel.setText("Système non déterminé")
            self.coordAutoStatusLabel.setStyleSheet("color: #888888;")

    def search_by_coordinates(self):
        x_str = self.coordXLineEdit.text().strip().replace(',', '.')
        y_str = self.coordYLineEdit.text().strip().replace(',', '.')
        if not x_str or not y_str:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir les coordonnées X et Y.")
            return
            
        try:
            x = float(x_str)
            y = float(y_str)
        except ValueError:
            QMessageBox.warning(self, "Erreur", "Les coordonnées doivent être numériques.")
            return
            
        crs_src = self.coordProjSelector.crs()
        crs_map = self.iface.mapCanvas().mapSettings().destinationCrs()
        
        point_src = QgsPointXY(x, y)
        transform = QgsCoordinateTransform(crs_src, crs_map, QgsProject.instance())
        
        try:
            point_map = transform.transform(point_src)
        except Exception as err:
            QMessageBox.warning(self, "Erreur", f"Erreur de transformation : {str(err)}")
            return
            
        self.trigger_animation_on_point(point_map)

    def convert_coordinates(self):
        x_str = self.coordXLineEdit.text().strip().replace(',', '.')
        y_str = self.coordYLineEdit.text().strip().replace(',', '.')
        if not x_str or not y_str:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir les coordonnées X et Y.")
            return
        try:
            x, y = float(x_str), float(y_str)
        except ValueError:
            QMessageBox.warning(self, "Erreur", "Les coordonnées doivent être numériques.")
            return
            
        crs_src = self.coordProjSelector.crs()
        crs_dest = self.convertProjSelector.crs()
        
        transform = QgsCoordinateTransform(crs_src, crs_dest, QgsProject.instance())
        try:
            pt = transform.transform(QgsPointXY(x, y))
            self.converted_pt = pt
            self.converted_crs = crs_dest
            self.convertResultX.setText(f"{pt.x():.6f}")
            self.convertResultY.setText(f"{pt.y():.6f}")
            self.convertResultFrame.setVisible(True)
        except Exception as e:
            QMessageBox.warning(self, "Erreur de conversion", str(e))

    def copy_converted_coordinates(self):
        x = self.convertResultX.text()
        y = self.convertResultY.text()
        if x and y:
            text = f"{x}, {y}"
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copie", f"Coordonnées copiées dans le presse-papier :\n{text}")

    def place_converted_coordinates(self):
        if hasattr(self, 'converted_pt') and hasattr(self, 'converted_crs'):
            crs_map = self.iface.mapCanvas().mapSettings().destinationCrs()
            transform = QgsCoordinateTransform(self.converted_crs, crs_map, QgsProject.instance())
            try:
                point_map = transform.transform(self.converted_pt)
                self.trigger_animation_on_point(point_map)
            except Exception as err:
                QMessageBox.warning(self, "Erreur", f"Erreur de transformation : {str(err)}")

    def detect_csv_delimiter(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [f.readline() for _ in range(5)]
            sample = "".join([line for line in lines if line])
            if not sample:
                return ';'
            first_line = lines[0]
            counts = {
                ';': first_line.count(';'),
                ',': first_line.count(','),
                '\t': first_line.count('\t'),
                '|': first_line.count('|'),
                ' ': first_line.count(' ')
            }
            best = max([';', '\t', ',', '|'], key=lambda d: counts[d])
            if counts[best] > 0:
                return best
            if counts[' '] > 0:
                return ' '
        except Exception as err:
            QgsMessageLog.logMessage(f"GeoBan France - Détection séparateur: {err}", "GeoBan France")
        return ';'

    def get_selected_delimiter_char(self, filepath):
        idx = self.importDelimiterCombo.currentIndex()
        if idx == 0:
            return self.detect_csv_delimiter(filepath)
        elif idx == 1: return ';'
        elif idx == 2: return ','
        elif idx == 3: return '\t'
        elif idx == 4: return ' '
        elif idx == 5: return '|'
        return ';'

    def on_delimiter_changed(self):
        filepath = self.importFilePath.text()
        if filepath and filepath.lower().endswith('.csv'):
            self.parse_import_file(filepath)

    def browse_import_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Sélectionner un fichier", "", "Fichiers (*.csv *.xlsx *.xls)")
        if filepath:
            self.importFilePath.setText(filepath)
            self.parse_import_file(filepath)

    def on_import_cols_changed(self):
        filepath = self.importFilePath.text()
        col_x = self.importColX.currentText()
        col_y = self.importColY.currentText()
        if not filepath or not col_x or not col_y:
            return
        
        delim = self.get_selected_delimiter_char(filepath) if filepath.lower().endswith('.csv') else ';'
        detected_crs = self.auto_detect_crs_from_data(filepath, delim, col_x, col_y)

        if detected_crs == "EPSG:4326":
            self.importCrsSelector.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            self.importCrsStatusLabel.setText("✔ Détecté : WGS 84 (EPSG:4326)")
            self.importCrsStatusLabel.setStyleSheet("color: #27ae60; font-weight: bold;")
        elif detected_crs == "EPSG:2154":
            self.importCrsSelector.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
            self.importCrsStatusLabel.setText("✔ Détecté : Lambert 93 (EPSG:2154)")
            self.importCrsStatusLabel.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.importCrsStatusLabel.setText("⚠️ Inconnu - Veuillez choisir dans la liste")
            self.importCrsStatusLabel.setStyleSheet("color: #e67e22; font-weight: bold;")

    def auto_detect_crs_from_data(self, filepath, delim, col_x, col_y):
        x_vals, y_vals = [], []
        try:
            if filepath.lower().endswith('.csv'):
                import csv
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f, delimiter=delim)
                    header = next(reader, None)
                    if not header:
                        return "UNKNOWN"
                    header = [c.strip(' "\'\t\r\n') for c in header]
                    try:
                        x_idx = header.index(col_x)
                        y_idx = header.index(col_y)
                    except ValueError:
                        return "UNKNOWN"
                    
                    for i, row in enumerate(reader):
                        if i >= 50:
                            break
                        if len(row) > max(x_idx, y_idx):
                            raw_x = str(row[x_idx]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                            raw_y = str(row[y_idx]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                            try:
                                x_vals.append(float(raw_x))
                                y_vals.append(float(raw_y))
                            except ValueError:
                                continue
            else:
                layer = QgsVectorLayer(filepath, "sample", "ogr")
                if layer.isValid():
                    fields = [f.name() for f in layer.fields()]
                    if col_x in fields and col_y in fields:
                        for i, feat in enumerate(layer.getFeatures()):
                            if i >= 50:
                                break
                            raw_x = str(feat[col_x]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                            raw_y = str(feat[col_y]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                            try:
                                x_vals.append(float(raw_x))
                                y_vals.append(float(raw_y))
                            except ValueError:
                                continue
        except Exception as err:
            QgsMessageLog.logMessage(f"GeoBan France - Détection SCR: {err}", "GeoBan France")

        if not x_vals or not y_vals:
            return "UNKNOWN"

        is_wgs84 = all(-180.0 <= x <= 180.0 for x in x_vals) and all(-90.0 <= y <= 90.0 for y in y_vals)
        if is_wgs84:
            return "EPSG:4326"

        is_lambert93 = all(100000.0 <= x <= 1300000.0 for x in x_vals) and all(6000000.0 <= y <= 7200000.0 for y in y_vals)
        if is_lambert93:
            return "EPSG:2154"

        return "UNKNOWN"

    def parse_import_file(self, filepath):
        self.importColX.blockSignals(True)
        self.importColY.blockSignals(True)
        self.importColX.clear()
        self.importColY.clear()
        header = []
        
        try:
            if filepath.lower().endswith('.csv'):
                self.importDelimiterCombo.setEnabled(True)
                delim = self.get_selected_delimiter_char(filepath)
                delim_disp = {"\t": "Tabulation", ";": "Point-virgule (;)", ",": "Virgule (,)", " ": "Espace", "|": "Pipe (|)"}.get(delim, delim)
                import csv
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f, delimiter=delim)
                    try:
                        header = next(reader)
                    except StopIteration:
                        header = []
                self.importStatusLabel.setText(f"Séparateur : {delim_disp} ({len(header)} colonnes)")
                self.importStatusLabel.setStyleSheet("color: #008800; font-weight: bold;")
            else:
                self.importDelimiterCombo.setEnabled(False)
                layer = QgsVectorLayer(filepath, "test", "ogr")
                if layer.isValid():
                    header = [field.name() for field in layer.fields()]
                    self.importStatusLabel.setText(f"Fichier Excel ({len(header)} colonnes)")
                    self.importStatusLabel.setStyleSheet("color: #008800; font-weight: bold;")
                else:
                    QMessageBox.warning(self, "Erreur", "Impossible de lire le fichier Excel.")
                    self.importStatusLabel.setText("Erreur de lecture Excel")
                    self.importStatusLabel.setStyleSheet("color: #cc0000;")
                    self.importColX.blockSignals(False)
                    self.importColY.blockSignals(False)
                    return

            header = [c.strip(' "\'\t\r\n') for c in header if c.strip()]
            self.importColX.addItems(header)
            self.importColY.addItems(header)
            
            x_candidates = ['x', 'lon', 'longitude', 'long', 'lng', 'coord_x', 'coordonnee_x', 'coordonnees_x', 'x_wgs84', 'lambert_x', 'easting', 'e']
            y_candidates = ['y', 'lat', 'latitude', 'coord_y', 'coordonnee_y', 'coordonnees_y', 'y_wgs84', 'lambert_y', 'northing', 'n']
            
            best_x_idx = -1
            best_y_idx = -1
            
            for i, col in enumerate(header):
                col_lower = col.lower().strip()
                if best_x_idx == -1 and col_lower in x_candidates:
                    best_x_idx = i
                elif best_y_idx == -1 and col_lower in y_candidates:
                    best_y_idx = i
            
            if best_x_idx == -1:
                for i, col in enumerate(header):
                    col_lower = col.lower().strip()
                    if any(cand in col_lower for cand in ['longitude', 'coord_x', 'lambert_x', 'x_']):
                        best_x_idx = i
                        break
            if best_y_idx == -1:
                for i, col in enumerate(header):
                    col_lower = col.lower().strip()
                    if any(cand in col_lower for cand in ['latitude', 'coord_y', 'lambert_y', 'y_']):
                        best_y_idx = i
                        break

            if best_x_idx != -1:
                self.importColX.setCurrentIndex(best_x_idx)
            if best_y_idx != -1:
                self.importColY.setCurrentIndex(best_y_idx)
            
            self.importRunButton.setEnabled(len(header) >= 2)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Erreur de lecture du fichier : {str(e)}")
            self.importStatusLabel.setText("Erreur de lecture")
            self.importStatusLabel.setStyleSheet("color: #cc0000;")
        finally:
            self.importColX.blockSignals(False)
            self.importColY.blockSignals(False)
            
        self.on_import_cols_changed()

    def run_import_layer(self):
        filepath = self.importFilePath.text()
        col_x = self.importColX.currentText()
        col_y = self.importColY.currentText()
        crs_auth = self.importCrsSelector.crs().authid()
        
        if not filepath or not col_x or not col_y:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner le fichier et les colonnes X et Y.")
            return
            
        import os
        layer_name = f"Import_{os.path.splitext(os.path.basename(filepath))[0]}"
        
        mem_layer = QgsVectorLayer(f"Point?crs={crs_auth}", layer_name, "memory")
        prov = mem_layer.dataProvider()

        features_to_add = []

        try:
            if filepath.lower().endswith('.csv'):
                delim = self.get_selected_delimiter_char(filepath)
                import csv
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f, delimiter=delim)
                    header = next(reader, None)
                    if not header:
                        QMessageBox.warning(self, "Erreur", "Le fichier CSV est vide.")
                        return
                    field_names = [c.strip(' "\'\t\r\n') for c in header]
                    x_idx = field_names.index(col_x) if col_x in field_names else -1
                    y_idx = field_names.index(col_y) if col_y in field_names else -1
                    
                    if x_idx == -1 or y_idx == -1:
                        QMessageBox.warning(self, "Erreur", "Colonnes X ou Y invalides.")
                        return

                    qgs_fields = [QgsField(name, QVariant.String) for name in field_names]
                    prov.addAttributes(qgs_fields)
                    mem_layer.updateFields()

                    for row in reader:
                        if len(row) <= max(x_idx, y_idx):
                            continue
                        raw_x = str(row[x_idx]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                        raw_y = str(row[y_idx]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                        try:
                            val_x = float(raw_x)
                            val_y = float(raw_y)
                        except ValueError:
                            continue
                        
                        feat = QgsFeature(mem_layer.fields())
                        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(val_x, val_y)))
                        feat.setAttributes(row)
                        features_to_add.append(feat)
            else:
                src_layer = QgsVectorLayer(filepath, "temp", "ogr")
                if not src_layer.isValid():
                    QMessageBox.warning(self, "Erreur", "Fichier Excel invalide.")
                    return
                qgs_fields = src_layer.fields()
                prov.addAttributes(qgs_fields)
                mem_layer.updateFields()

                for src_feat in src_layer.getFeatures():
                    raw_x = str(src_feat[col_x]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                    raw_y = str(src_feat[col_y]).strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
                    try:
                        val_x = float(raw_x)
                        val_y = float(raw_y)
                    except ValueError:
                        continue
                    
                    feat = QgsFeature(mem_layer.fields())
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(val_x, val_y)))
                    feat.setAttributes(src_feat.attributes())
                    features_to_add.append(feat)

            if not features_to_add:
                QMessageBox.warning(self, "Attention", "Aucun point valide trouvé avec des coordonnées numériques.")
                return

            prov.addFeatures(features_to_add)
            mem_layer.updateExtents()
            
            QgsProject.instance().addMapLayer(mem_layer)
            if mem_layer.featureCount() > 0:
                self.iface.mapCanvas().setExtent(mem_layer.extent())
                self.iface.mapCanvas().refresh()
            
            QMessageBox.information(self, "Succès", f"La couche '{mem_layer.name()}' ({len(features_to_add)} points) a été ajoutée au projet avec succès !")
        except Exception as e:
            QMessageBox.warning(self, "Erreur d'import", f"Erreur lors de la création de la couche : {str(e)}")

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def canvasReleaseEvent(self, e):
        point_map = self.toMapCoordinates(e.pos())
        
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_map = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(crs_map, crs_wgs84, QgsProject.instance())
        
        try:
            point_wgs84 = transform.transform(point_map)
        except Exception as err:
            QgsMessageLog.logMessage(f"Erreur transformation point: {str(err)}", "GeoBan France", QgsMessageLog.INFO)
            return
            
        lon, lat = point_wgs84.x(), point_wgs84.y()
        
        self.dialog.identifierResultText.setText("Recherche de l'adresse en cours...")
        self.dialog.tabWidget.setCurrentWidget(self.dialog.identifier_tab)
        
        self.dialog.identifier_lon = lon
        self.dialog.identifier_lat = lat
        
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

    def on_finished(self, result):
        if not result or not isinstance(result, dict):
            self.dialog.identifierResultText.setText("Aucune information trouvée à cet emplacement.")
            return
            
        ban_feat = result.get('ban')
        cad_feat = result.get('cadastre')
        
        text_parts = []
        
        if ban_feat:
            coords = ban_feat.get('geometry', {}).get('coordinates', [])
            if len(coords) >= 2:
                self.dialog.identifier_street_lon = coords[0]
                self.dialog.identifier_street_lat = coords[1]

            props = ban_feat.get('properties', {})
            label = props.get('label', 'Adresse inconnue')
            context = props.get('context', '')
            postcode = props.get('postcode', '')
            city = props.get('city', '')
            dist = props.get('distance', '')
            dist_str = f" (à {dist}m)" if dist is not None and dist != '' else ""
            
            text_parts.append(f"ADRESSE BAN{dist_str} :\n{label}\nCode postal : {postcode} | Ville : {city}\nContexte : {context}")

        if cad_feat:
            props_cad = cad_feat.get('properties', {})
            code_insee = props_cad.get('code_insee', '')
            section = props_cad.get('section', '')
            numero = props_cad.get('numero', '')
            contenance = props_cad.get('contenance', '')
            
            contenance_str = f"\nSurface : {contenance} m²" if contenance else ""
            text_parts.append(f"PARCELLE CADASTRE (IGN) :\nCommune (INSEE) : {code_insee}\nSection : {section} | N° : {numero}{contenance_str}")

        if text_parts:
            full_text = "\n\n----------------------------------------\n\n".join(text_parts)
            self.dialog.identifierResultText.setText(full_text)
        else:
            self.dialog.identifierResultText.setText("Aucune adresse ou parcelle trouvée à cet emplacement.")

    def on_error(self, err):
        self.dialog.identifierResultText.setText(f"Information : {err}")

class DialogStreetViewDirectTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, dialog):
        super().__init__(canvas)
        self.canvas = canvas
        self.dialog = dialog
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def canvasReleaseEvent(self, e):
        point_map = self.toMapCoordinates(e.pos())
        
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_map = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(crs_map, crs_wgs84, QgsProject.instance())
        
        try:
            point_wgs84 = transform.transform(point_map)
        except Exception as err:
            QgsMessageLog.logMessage(f"Erreur transformation point Street View: {str(err)}", "GeoBan France", QgsMessageLog.INFO)
            return
            
        lon, lat = point_wgs84.x(), point_wgs84.y()
        
        # Automatic snap to nearest street address if clicked near street line
        street_lat, street_lon = self.dialog.get_nearest_street_coords(lat, lon)
        url = f"https://www.google.com/maps?q={street_lat},{street_lon}&layer=c&cbll={street_lat},{street_lon}"
        QDesktopServices.openUrl(QUrl(url))

    def deactivate(self):
        if hasattr(self.dialog, 'activateStreetViewToolButton'):
            self.dialog.activateStreetViewToolButton.setChecked(False)
            self.dialog.activateStreetViewToolButton.setText("2. Outil Clic Direct Street View (Pointer sur la carte)")
            self.dialog.activateStreetViewToolButton.setStyleSheet("")
        super().deactivate()
