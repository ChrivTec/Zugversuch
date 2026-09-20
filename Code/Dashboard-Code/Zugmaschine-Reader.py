import sys, csv, math, os
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QLocale
from PyQt5.QtGui import QFont, QColor, QIcon
import pyqtgraph as pg

# Hilfsfunktion, damit PyInstaller das Icon in der .exe findet
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class AnalysisTool(QMainWindow):
    def _init_(self):
        super()._init_()
        self.setWindowTitle("Zugmaschine - Daten-Auswertung & Peak-Auswahl")
        self.resize(1200, 900)
        
        # Daten-Speicher
        self.all_data = []      
        self.saved_points = []  
        self.loaded_file_name = "Gefundene_Peaks" # Standard-Name, falls ohne Laden gespeichert wird
        
        self.init_ui()
        
        icon_path = resource_path('icon.ico') # <--- HIER .ico eintragen!
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("reader_appid")
            except:
                pass
        
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        
        # --- LINKE SEITE: STEUERUNG & TABELLE ---
        left_panel = QVBoxLayout()
        
        # 1. Laden
        self.btn_load = QPushButton("1. Messdaten (CSV) laden")
        self.btn_load.setMinimumHeight(40)
        self.btn_load.setStyleSheet("background-color: #007bff; color: white; font-weight: bold;")
        self.btn_load.clicked.connect(self.load_csv)
        
        self.lbl_info = QLabel("Geladene Datei: Keine")
        self.lbl_info.setStyleSheet("color: gray;")
        
        # 2a. Bereichs-Suche
        self.btn_toggle_region = QPushButton("2a. Such-Bereich (Box) einblenden")
        self.btn_toggle_region.setMinimumHeight(35)
        self.btn_toggle_region.setCheckable(True)
        self.btn_toggle_region.clicked.connect(self.toggle_region)
        self.btn_toggle_region.setEnabled(False)
        
        self.region_controls = QWidget()
        region_layout = QHBoxLayout(self.region_controls)
        region_layout.setContentsMargins(0, 0, 0, 0)
        
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-9999, 9999)
        self.spin_min.setDecimals(2)
        self.spin_min.setSuffix(" mm")
        self.spin_min.valueChanged.connect(self.update_region_from_spin)
        
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-9999, 9999)
        self.spin_max.setDecimals(2)
        self.spin_max.setSuffix(" mm")
        self.spin_max.valueChanged.connect(self.update_region_from_spin)
        
        region_layout.addWidget(QLabel("Start:"))
        region_layout.addWidget(self.spin_min)
        region_layout.addWidget(QLabel("Ende:"))
        region_layout.addWidget(self.spin_max)
        self.region_controls.setVisible(False) 
        
        self.btn_find_peak = QPushButton("2b. Höchsten Punkt (je Zyklus) markieren")
        self.btn_find_peak.setMinimumHeight(35)
        self.btn_find_peak.setStyleSheet("background-color: #ffc107; color: black; font-weight: bold;")
        self.btn_find_peak.clicked.connect(self.find_peak_in_region)
        self.btn_find_peak.setEnabled(False)

        # 3. Manuelle Klick-Auswahl und Tabelle
        self.btn_manual_point = QPushButton("3. Manuelle Auswahl per Klick: AUS")
        self.btn_manual_point.setMinimumHeight(35)
        self.btn_manual_point.setCheckable(True)
        self.btn_manual_point.clicked.connect(self.toggle_manual_mode)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Zyklus", "Weg (mm)", "Kraft (N)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        
        self.btn_delete_row = QPushButton("Ausgewählte Zeile(n) löschen")
        self.btn_delete_row.clicked.connect(self.delete_selected_rows)
        
        self.btn_clear = QPushButton("Komplette Tabelle leeren")
        self.btn_clear.clicked.connect(self.clear_table)
        
        self.btn_calc_diff = QPushButton("Δ Differenz der 2 gewählten Zeilen berechnen")
        self.btn_calc_diff.setMinimumHeight(35)
        self.btn_calc_diff.setStyleSheet("background-color: #17a2b8; color: white; font-weight: bold;")
        self.btn_calc_diff.clicked.connect(self.calculate_difference)
        
        self.lbl_diff = QLabel("Tabellen-Differenz: -")
        self.lbl_diff.setAlignment(Qt.AlignCenter) 
        self.lbl_diff.setMinimumHeight(50) 
        self.lbl_diff.setStyleSheet("color: #d9534f; background-color: #fdf5f5; font-weight: bold; font-size: 18px; border: 2px solid #d9534f; border-radius: 5px;")
        
        # 4. Manuelles Messwerkzeug (Lineal)
        self.btn_ruler = QPushButton("4. Messschieber (Lineal) einblenden")
        self.btn_ruler.setMinimumHeight(40)
        self.btn_ruler.setCheckable(True)
        self.btn_ruler.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_ruler.clicked.connect(self.toggle_ruler)
        
        self.lbl_ruler = QLabel("Lineal -> Δ Weg: - mm   |   Δ Kraft: - N")
        self.lbl_ruler.setAlignment(Qt.AlignCenter)
        self.lbl_ruler.setMinimumHeight(40)
        self.lbl_ruler.setStyleSheet("color: #6f42c1; background-color: #f8f4ff; font-weight: bold; font-size: 16px; border: 2px solid #6f42c1; border-radius: 5px;")
        
        # 5. Speichern
        self.btn_save = QPushButton("5. Ausgewählte Punkte speichern (CSV)")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_points)
        
        # Zusammenbau der linken Spalte
        left_panel.addWidget(self.btn_load)
        left_panel.addWidget(self.lbl_info)
        left_panel.addSpacing(15)
        
        left_panel.addWidget(QLabel("<b>Automatische Peak-Suche:</b>"))
        left_panel.addWidget(self.btn_toggle_region)
        left_panel.addWidget(self.region_controls)
        left_panel.addWidget(self.btn_find_peak)
        left_panel.addSpacing(10)
        
        left_panel.addWidget(QLabel("<b>Erfasste Messpunkte:</b>"))
        left_panel.addWidget(self.btn_manual_point)
        left_panel.addWidget(self.table)
        
        table_ctrl_layout = QHBoxLayout()
        table_ctrl_layout.addWidget(self.btn_delete_row)
        table_ctrl_layout.addWidget(self.btn_clear)
        left_panel.addLayout(table_ctrl_layout)
        
        left_panel.addWidget(self.btn_calc_diff)
        left_panel.addWidget(self.lbl_diff)
        left_panel.addSpacing(15)
        
        left_panel.addWidget(QLabel("<b>Manuelle Distanz-Messung:</b>"))
        left_panel.addWidget(self.btn_ruler)
        left_panel.addWidget(self.lbl_ruler)
        left_panel.addSpacing(15)
        
        left_panel.addWidget(self.btn_save)
        
        # --- RECHTE SEITE: GRAPH ---
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        self.graph = pg.PlotWidget(title="Interaktive Auswertung")
        self.graph.setLabel('bottom', 'Weg (mm)')
        self.graph.setLabel('left', 'Kraft (N)')
        self.graph.showGrid(x=True, y=True)
        self.graph.addLegend()
        
        self.graph.scene().sigMouseClicked.connect(self.graph_clicked)
        
        # Bereichs-Tool (Box)
        self.region = pg.LinearRegionItem(pen=pg.mkPen('b', width=3), brush=pg.mkBrush(0, 0, 255, 30))
        self.region.setZValue(10)
        self.graph.addItem(self.region, ignoreBounds=True)
        self.region.setVisible(False)
        self.region.sigRegionChanged.connect(self.update_spin_from_region)
        
        # Lineal-Tool (LineSegmentROI)
        self.ruler = pg.LineSegmentROI([[0, 0], [5, 100]], pen=pg.mkPen('#6f42c1', width=3, style=Qt.DashLine))
        self.ruler.setZValue(20)
        self.graph.addItem(self.ruler, ignoreBounds=True)
        self.ruler.setVisible(False)
        self.ruler.sigRegionChanged.connect(self.update_ruler)
        
        # Punkt-Ebene
        self.scatter = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None), brush=pg.mkBrush(255, 0, 0, 200))
        self.graph.addItem(self.scatter)
        
        layout.addLayout(left_panel, 1)
        layout.addWidget(self.graph, 3)

    # --- UI Logic ---
    def load_csv(self):
        options = QFileDialog.Options()
        path, _ = QFileDialog.getOpenFileName(self, "CSV Laden", "", "CSV Dateien (*.csv)", options=options)
        if not path: return
            
        self.all_data = []
        self.graph.clear()
        
        self.graph.addItem(self.region)
        self.graph.addItem(self.ruler)
        self.graph.addItem(self.scatter)
        self.scatter.clear()
        self.clear_table()
        
        # Resets
        self.btn_toggle_region.setChecked(False)
        self.region.setVisible(False)
        self.region_controls.setVisible(False)
        self.btn_toggle_region.setText("2a. Such-Bereich (Box) einblenden")
        self.btn_find_peak.setEnabled(False)
        
        self.btn_ruler.setChecked(False)
        self.ruler.setVisible(False)
        self.btn_ruler.setText("4. Messschieber (Lineal) einblenden")
        self.btn_ruler.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.lbl_ruler.setText("Lineal -> Δ Weg: - mm   |   Δ Kraft: - N")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=',')
                for row in reader:
                    if len(row) >= 4:
                        try:
                            t = float(row[0])
                            x = float(row[1])
                            y = float(row[2])
                            c = int(float(row[3]))
                            self.all_data.append({'t': t, 'x': x, 'y': y, 'c': c})
                        except ValueError:
                            pass 
                            
            # NEU: Namen der Datei merken (ohne .csv Endung)
            file_name = path.split('/')[-1]
            if file_name.endswith('.csv'):
                self.loaded_file_name = file_name[:-4]
            else:
                self.loaded_file_name = file_name
                
            self.lbl_info.setText(f"Geladene Datei: {file_name}")
            self.btn_toggle_region.setEnabled(True)
            self.plot_data()
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Fehler beim Laden der Datei:\n{e}")

    def plot_data(self):
        if not self.all_data: return
        cycles = set([d['c'] for d in self.all_data])
        
        for c_id in sorted(cycles):
            x_vals = [d['x'] for d in self.all_data if d['c'] == c_id]
            y_vals = [d['y'] for d in self.all_data if d['c'] == c_id]
            
            if c_id == 0:
                color = QColor('blue')
                name = "Einzeltest"
            else:
                hue = int(((c_id - 1) * 137.5) % 360)  
                color = QColor.fromHsv(hue, 220, 200)
                name = f"Zyklus {c_id}"
                
            self.graph.plot(x_vals, y_vals, pen=pg.mkPen(color, width=2), name=name)
            
        self.graph.enableAutoRange(axis='xy')

    # --- Box Search ---
    def toggle_region(self):
        if self.btn_toggle_region.isChecked():
            self.region.setVisible(True)
            self.region_controls.setVisible(True)
            self.btn_toggle_region.setText("2a. Such-Bereich (Box) ausblenden")
            self.btn_find_peak.setEnabled(True)
            
            if self.all_data:
                xs = [d['x'] for d in self.all_data]
                x_min = min(xs)
                x_max = max(xs)
                start_val = x_min
                end_val = x_min + (x_max - x_min) * 0.2
                self.region.setRegion([start_val, end_val])
                self.update_spin_from_region()
        else:
            self.region.setVisible(False)
            self.region_controls.setVisible(False)
            self.btn_toggle_region.setText("2a. Such-Bereich (Box) einblenden")
            self.btn_find_peak.setEnabled(False)

    def update_spin_from_region(self):
        min_x, max_x = self.region.getRegion()
        self.spin_min.blockSignals(True)
        self.spin_max.blockSignals(True)
        self.spin_min.setValue(min_x)
        self.spin_max.setValue(max_x)
        self.spin_min.blockSignals(False)
        self.spin_max.blockSignals(False)

    def update_region_from_spin(self):
        min_x = self.spin_min.value()
        max_x = self.spin_max.value()
        if min_x < max_x:
            self.region.setRegion([min_x, max_x])

    def find_peak_in_region(self):
        if not self.all_data: return
        min_x, max_x = self.region.getRegion()
        cycles = set([d['c'] for d in self.all_data])
        found_any = False
        
        for c_id in sorted(cycles):
            points_in_region = [d for d in self.all_data if d['c'] == c_id and min_x <= d['x'] <= max_x]
            if points_in_region:
                peak_point = max(points_in_region, key=lambda d: d['y'])
                self.add_point_to_selection(peak_point)
                found_any = True
                
        if not found_any:
            QMessageBox.warning(self, "Fehler", "Keine Messpunkte im ausgewählten Bereich gefunden!")

    # --- Lineal Logik ---
    def toggle_ruler(self):
        if self.btn_ruler.isChecked():
            self.ruler.setVisible(True)
            self.btn_ruler.setText("4. Messschieber (Lineal) ausblenden")
            self.btn_ruler.setStyleSheet("background-color: white; color: #6f42c1; font-weight: bold; border: 2px solid #6f42c1;")
            
            try:
                view_range = self.graph.viewRange()
                x_mid = sum(view_range[0]) / 2.0
                y_mid = sum(view_range[1]) / 2.0
                
                span_x = (view_range[0][1] - view_range[0][0]) * 0.1
                span_y = (view_range[1][1] - view_range[1][0]) * 0.3
                
                self.ruler.setPos([0, 0]) 
                handles = self.ruler.getHandles()
                handles[0].setPos([x_mid - span_x, y_mid - span_y])
                handles[1].setPos([x_mid + span_x, y_mid + span_y])
            except:
                pass
                
            self.update_ruler()
        else:
            self.ruler.setVisible(False)
            self.btn_ruler.setText("4. Messschieber (Lineal) einblenden")
            self.btn_ruler.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
            self.lbl_ruler.setText("Lineal -> Δ Weg: - mm   |   Δ Kraft: - N")

    def update_ruler(self):
        try:
            handles = self.ruler.getHandles()
            p1 = self.graph.plotItem.vb.mapSceneToView(handles[0].scenePos())
            p2 = self.graph.plotItem.vb.mapSceneToView(handles[1].scenePos())
            
            dx = abs(p2.x() - p1.x())
            dy = abs(p2.y() - p1.y())
            
            self.lbl_ruler.setText(f"Lineal -> Δ Weg: {dx:.3f} mm   |   Δ Kraft: {dy:.2f} N")
        except Exception:
            pass

    # --- Manuelle Auswahl ---
    def toggle_manual_mode(self):
        if self.btn_manual_point.isChecked():
            self.btn_manual_point.setText("3. Manuelle Auswahl per Klick: EIN")
            self.btn_manual_point.setStyleSheet("background-color: #17a2b8; color: white; font-weight: bold;")
        else:
            self.btn_manual_point.setText("3. Manuelle Auswahl per Klick: AUS")
            self.btn_manual_point.setStyleSheet("")

    def graph_clicked(self, evt):
        if not self.btn_manual_point.isChecked(): return
        if not self.all_data: return
        if evt.button() != Qt.LeftButton: return
            
        scene_pos = evt.scenePos()
        
        if self.ruler.isVisible() and self.ruler.sceneBoundingRect().contains(scene_pos):
            return
            
        if self.graph.sceneBoundingRect().contains(scene_pos):
            mouse_point = self.graph.plotItem.vb.mapSceneToView(scene_pos)
            mouse_x = mouse_point.x()
            mouse_y = mouse_point.y()
            
            closest_point = None
            min_dist = float('inf')
            
            max_y = max([d['y'] for d in self.all_data]) if self.all_data else 1
            max_x = max([d['x'] for d in self.all_data]) if self.all_data else 1
            
            for d in self.all_data:
                dist = math.sqrt(((d['x'] - mouse_x)/max_x)*2 + ((d['y'] - mouse_y)/max_y)*2)
                if dist < min_dist:
                    min_dist = dist
                    closest_point = d
                    
            if closest_point:
                self.add_point_to_selection(closest_point)

    # --- Tabellen-Operationen ---
    def add_point_to_selection(self, point):
        if point in self.saved_points: return
            
        self.saved_points.append(point)
        self.update_scatter()
        
        row_pos = self.table.rowCount()
        self.table.insertRow(row_pos)
        self.table.setItem(row_pos, 0, QTableWidgetItem(str(point['c'])))
        self.table.setItem(row_pos, 1, QTableWidgetItem(f"{point['x']:.2f}"))
        self.table.setItem(row_pos, 2, QTableWidgetItem(f"{point['y']:.2f}"))
        self.table.scrollToBottom()

    def delete_selected_rows(self):
        selected_rows = sorted(list(set(index.row() for index in self.table.selectedIndexes())), reverse=True)
        if not selected_rows: return
            
        for row in selected_rows:
            del self.saved_points[row]
            self.table.removeRow(row)
            
        self.update_scatter()
        self.lbl_diff.setText("Tabellen-Differenz: -")

    def clear_table(self):
        self.table.setRowCount(0)
        self.saved_points = []
        self.scatter.clear()
        self.lbl_diff.setText("Tabellen-Differenz: -")

    def update_scatter(self):
        spots = [{'pos': (p['x'], p['y']), 'data': 1} for p in self.saved_points]
        self.scatter.setData(spots)

    # --- Rechnen & Speichern ---
    def calculate_difference(self):
        selected_rows = sorted(list(set(index.row() for index in self.table.selectedIndexes())))
        
        if len(selected_rows) != 2:
            QMessageBox.warning(self, "Fehler", "Bitte wähle exakt 2 Zeilen in der Tabelle aus!\n\nTipp: Halte die 'Strg'-Taste gedrückt, während du die Zeilen anklickst.")
            return
            
        idx1, idx2 = selected_rows[0], selected_rows[1]
        p1 = self.saved_points[idx1]
        p2 = self.saved_points[idx2]
        
        diff_x = abs(p2['x'] - p1['x'])
        diff_y = abs(p2['y'] - p1['y'])
        
        self.lbl_diff.setText(f"Δ Weg: {diff_x:.3f} mm   |   Δ Kraft: {diff_y:.2f} N")

    def save_points(self):
        if not self.saved_points:
            QMessageBox.information(self, "Leer", "Es wurden keine Punkte ausgewählt!")
            return
            
        # NEU: Automatischer Name mit "-bereinigt" am Ende
        default_save_name = f"{self.loaded_file_name}-bereinigt.csv"
        
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Ausgewählte Punkte speichern", 
            default_save_name, 
            "CSV Dateien (.csv);;Alle Dateien ()", 
            options=options
        )
        
        if not file_path: return 
            
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Zyklus", "Weg_mm", "Kraft_N"])
                for p in self.saved_points:
                    x_str = f"{p['x']:.3f}".replace('.', ',')
                    y_str = f"{p['y']:.3f}".replace('.', ',')
                    w.writerow([str(p['c']), x_str, y_str])
                    
            QMessageBox.information(self, "Erfolg", f"Messpunkte gespeichert unter:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Fehler beim Speichern:\n{e}")

if _name_ == "_main_":
    app = QApplication(sys.argv)
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))
    win = AnalysisTool()
    win.show()
    sys.exit(app.exec_())
