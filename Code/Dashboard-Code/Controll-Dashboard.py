import sys, serial, serial.tools.list_ports, csv, os, bisect
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QLocale, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap
import pyqtgraph as pg

STEP_TO_MM = 0.000467

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ========================================================
# DER HINTERGRUND-ARBEITER FÜR DIE USB-VERBINDUNG
# ========================================================
class SerialWorker(QThread):
    line_received = pyqtSignal(str)
    error_received = pyqtSignal(str)

    def _init_(self, port):
        super()._init_()
        self.port = port
        self.ser = None
        self.is_running = True

    def run(self):
        try:
            self.ser = serial.Serial(self.port, 115200, timeout=0.1)
        except Exception as e:
            self.error_received.emit(str(e))
            return

        while self.is_running:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.line_received.emit(line)
            except Exception as e:
                if self.is_running:
                    self.error_received.emit(str(e))
                    self.is_running = False

    def send(self, char):
        if self.ser and self.is_running:
            try:
                self.ser.write(char.encode())
            except: pass

    def stop(self):
        self.is_running = False
        if self.ser:
            self.ser.close()

# ========================================================
# DAS HAUPT-DASHBOARD
# ========================================================
class Dashboard(QMainWindow):
    def _init_(self):
        super()._init_()
        self.setWindowTitle("Zugmaschine - Profi Dashboard")
        self.resize(1100, 800)
        
        icon_path = resource_path('icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("myappid")
        
        self.worker = None 
        self.is_measuring = False
        self.start_pos = None 
        self.data_x, self.data_y = [], []
        self.max_force = 0.0  
        self.crosshair_active = False 
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        controls = QVBoxLayout()
        controls.setSpacing(10)
        
        self.port_box = QComboBox()
        for p in serial.tools.list_ports.comports(): self.port_box.addItem(p.device)
        self.btn_con = QPushButton("Verbinden")
        self.btn_con.clicked.connect(self.toggle_serial)
        
        self.status = QLabel("STATUS: GETRENNT")
        self.status.setStyleSheet("background: #444; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        self.status.setAlignment(Qt.AlignCenter)

        # --- GEÄNDERT: F Max statt F_max ---
        self.lbl_max = QLabel("F Max: 0.00 N")
        self.lbl_max.setStyleSheet("color: #d9534f; font-size: 24px; font-weight: bold; border: 2px solid #d9534f; padding: 5px; border-radius: 5px;")
        self.lbl_max.setAlignment(Qt.AlignCenter)

        self.btn_h = QPushButton("Homing (Referenzfahrt)")
        self.btn_h.clicked.connect(lambda: self.send('h'))
        self.btn_zero = QPushButton("Fahre zur Startposition")
        self.btn_zero.clicked.connect(lambda: self.send('n'))
        self.btn_tare = QPushButton("Waage nullen (Tara)")
        self.btn_tare.setStyleSheet("background: #17a2b8; color: white; font-weight: bold;")
        self.btn_tare.clicked.connect(self.confirm_tare)
        self.btn_cal = QPushButton("Kalibrierung (Gewicht)")
        self.btn_cal.clicked.connect(self.calibrate_scale)

        self.btn_test = QPushButton("TEST STARTEN")
        self.btn_test.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_test.setMinimumHeight(50)
        self.btn_test.setStyleSheet("background: #28a745; color: white;")
        self.btn_test.clicked.connect(self.start_test)
        
        self.btn_stop = QPushButton("MESSUNG STOPPEN")
        self.btn_stop.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("background: #dc3545; color: white;")
        self.btn_stop.clicked.connect(lambda: self.send('q'))

        self.file_name = QLineEdit("Probe_001")
        self.btn_save = QPushButton("Daten Speichern (CSV)")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.clicked.connect(self.save_csv)

        self.btn_clear = QPushButton("Neuen Graph / Daten löschen")
        self.btn_clear.setMinimumHeight(40)
        self.btn_clear.setStyleSheet("background: #ffc107; color: black; font-weight: bold;")
        self.btn_clear.clicked.connect(self.clear_graph)

        self.btn_view_all = QPushButton("Ansicht zurücksetzen (Auto-Fit)")
        self.btn_view_all.setMinimumHeight(40)
        self.btn_view_all.setStyleSheet("background: #6c757d; color: white; font-weight: bold;")
        self.btn_view_all.clicked.connect(self.reset_graph_view)

        self.btn_crosshair = QPushButton("Fadenkreuz: AUS")
        self.btn_crosshair.setMinimumHeight(40)
        self.btn_crosshair.setCheckable(True) 
        self.btn_crosshair.clicked.connect(self.toggle_crosshair)

        self.buttons_prep = [self.btn_h, self.btn_zero, self.btn_tare, self.btn_cal, self.btn_clear, self.btn_test]

        for b in self.buttons_prep + [self.btn_stop, self.btn_save]:
            b.setEnabled(False)

        for w in [QLabel("<b>1. Verbindung:</b>"), self.port_box, self.btn_con, self.status, 
                  QLabel("<b>2. Vorbereitung:</b>"), self.btn_h, self.btn_zero, self.btn_tare, self.btn_cal,
                  QLabel("<b>3. Messung:</b>"), self.btn_test, self.btn_stop, self.lbl_max, 
                  QLabel("<b>4. Datenexport & Ansicht:</b>"), self.file_name, self.btn_save, self.btn_clear, self.btn_view_all, self.btn_crosshair]:
            controls.addWidget(w)
        controls.addStretch()

        pg.setConfigOption('background', 'w'); pg.setConfigOption('foreground', 'k')
        self.graph = pg.PlotWidget(title="Kraft-Weg-Diagramm")
        self.graph.setLabel('bottom', 'Weg (mm)')
        self.graph.setLabel('left', 'Kraft (N)')
        self.graph.showGrid(x=True, y=True)
        self.plot = self.graph.plot(pen=pg.mkPen('r', width=3))

        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('gray', width=1, style=Qt.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('gray', width=1, style=Qt.DashLine))
        self.graph.addItem(self.vLine, ignoreBounds=True)
        self.graph.addItem(self.hLine, ignoreBounds=True)
        
        self.cursor_label = pg.TextItem(text="", color='k', fill=pg.mkBrush(255, 255, 255, 200))
        self.graph.addItem(self.cursor_label)
        
        self.vLine.setVisible(False)
        self.hLine.setVisible(False)
        self.cursor_label.setVisible(False)
        
        self.proxy = pg.SignalProxy(self.graph.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)

        layout.addLayout(controls, 2); layout.addWidget(self.graph, 8)
        container = QWidget(); container.setLayout(layout); self.setCentralWidget(container)

    def toggle_crosshair(self):
        if self.btn_crosshair.isChecked():
            self.crosshair_active = True
            self.btn_crosshair.setText("Fadenkreuz: EIN")
            self.btn_crosshair.setStyleSheet("background: #17a2b8; color: white; font-weight: bold;")
            self.vLine.setVisible(True)
            self.hLine.setVisible(True)
            self.cursor_label.setVisible(True)
        else:
            self.crosshair_active = False
            self.btn_crosshair.setText("Fadenkreuz: AUS")
            self.btn_crosshair.setStyleSheet("")
            self.vLine.setVisible(False)
            self.hLine.setVisible(False)
            self.cursor_label.setVisible(False)

    def mouse_moved(self, evt):
        if not getattr(self, 'crosshair_active', False):
            return
            
        pos = evt[0]
        if self.graph.sceneBoundingRect().contains(pos):
            mousePoint = self.graph.plotItem.vb.mapSceneToView(pos)
            mouse_x = mousePoint.x()

            if not self.data_x:
                return

            idx = bisect.bisect_left(self.data_x, mouse_x)
            if idx == 0:
                closest_idx = 0
            elif idx == len(self.data_x):
                closest_idx = len(self.data_x) - 1
            else:
                if (mouse_x - self.data_x[idx - 1]) < (self.data_x[idx] - mouse_x):
                    closest_idx = idx - 1
                else:
                    closest_idx = idx

            echter_weg = self.data_x[closest_idx]
            echte_kraft = self.data_y[closest_idx]

            self.vLine.setPos(echter_weg)
            self.hLine.setPos(echte_kraft)
            
            text = f"Weg: {echter_weg:.2f} mm\nKraft: {echte_kraft:.2f} N"
            self.cursor_label.setText(text)
            self.cursor_label.setPos(echter_weg, echte_kraft)

    def toggle_serial(self):
        if self.worker is None or not self.worker.is_running:
            port = self.port_box.currentText()
            self.worker = SerialWorker(port)
            self.worker.line_received.connect(self.process_serial_line) 
            self.worker.error_received.connect(self.handle_usb_error)
            self.worker.start()

            self.status.setText("VERBUNDEN")
            self.status.setStyleSheet("background: #28a745; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_con.setText("Trennen")
            for b in self.buttons_prep: b.setEnabled(True)
        else:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
            self.btn_con.setText("Verbinden")
            self.status.setText("GETRENNT")
            self.status.setStyleSheet("background: #444; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            for b in self.buttons_prep + [self.btn_stop, self.btn_save]: b.setEnabled(False)

    def send(self, char):
        if self.worker: 
            self.worker.send(char)

    def handle_usb_error(self, err_msg):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
        self.btn_con.setText("Verbinden")
        self.status.setText("USB GETRENNT!")
        self.status.setStyleSheet("background: #dc3545; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        for b in self.buttons_prep + [self.btn_stop, self.btn_save]: b.setEnabled(False)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Verbindungsabbruch")
        msg.setText("Die USB-Verbindung wurde unterbrochen!\nBitte Kabel prüfen.")
        msg.addButton("Verstanden", QMessageBox.AcceptRole)
        msg.exec_()

    def process_serial_line(self, line):
        if line.startswith("DATA:") and self.is_measuring:
            p = line.split(":")[1].split(",")
            if len(p) == 3:
                force = float(p[1]); current_steps = float(p[2])
                if self.start_pos is None: self.start_pos = current_steps
                mm = abs(self.start_pos - current_steps) * STEP_TO_MM
                
                self.data_x.append(mm); self.data_y.append(force)
                self.plot.setData(self.data_x, self.data_y)
                
                # --- GEÄNDERT: F Max statt F_max ---
                if force > self.max_force:
                    self.max_force = force
                    self.lbl_max.setText(f"F Max: {self.max_force:.2f} N")
        
        elif "ALARM:" in line:
            self.is_measuring = False; self.status.setText("NOT-AUS!")
            self.status.setStyleSheet("background: #dc3545; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_stop.setEnabled(False); self.btn_test.setEnabled(True); self.btn_clear.setEnabled(True)
            self.btn_save.setEnabled(True)
            
        elif "Abgebrochen" in line or "Ziel erreicht" in line:
            self.is_measuring = False; self.status.setText("BEREIT")
            self.status.setStyleSheet("background: #28a745; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_stop.setEnabled(False); self.btn_test.setEnabled(True); self.btn_clear.setEnabled(True)
            self.btn_save.setEnabled(True)

    def confirm_tare(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Tara")
        msg.setText("Soll die Waage jetzt genullt werden?")
        btn_ja = msg.addButton("Ja", QMessageBox.YesRole)
        msg.addButton("Nein", QMessageBox.NoRole)
        msg.exec_()
        if msg.clickedButton() == btn_ja: self.send('w')

    def calibrate_scale(self):
        msg1 = QMessageBox(self)
        msg1.setWindowTitle("Kalibrierung - Schritt 1")
        msg1.setText("Ist die Waage komplett leer?")
        btn_ja = msg1.addButton("Ja", QMessageBox.YesRole)
        msg1.addButton("Nein", QMessageBox.NoRole)
        msg1.exec_()
        
        if msg1.clickedButton() == btn_ja:
            self.send('w') 
            msg2 = QMessageBox(self)
            msg2.setWindowTitle("Kalibrierung - Schritt 2")
            msg2.setText("Bitte das Prüfgewicht jetzt aufhängen / auflegen.")
            msg2.addButton("Erledigt (Weiter)", QMessageBox.AcceptRole)
            msg2.exec_()
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Kalibrierung - Schritt 3")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Exaktes Gewicht in Gramm (g) eingeben:"))
            
            spinBox = QDoubleSpinBox(dialog)
            spinBox.setRange(0.1, 100000.0); spinBox.setValue(1000.0); spinBox.setDecimals(1)
            layout.addWidget(spinBox)
            
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("Speichern"); btn_cancel = QPushButton("Abbrechen")
            btn_box.addWidget(btn_ok); btn_box.addWidget(btn_cancel)
            layout.addLayout(btn_box)
            
            btn_ok.clicked.connect(dialog.accept); btn_cancel.clicked.connect(dialog.reject)
            
            if dialog.exec_() == QDialog.Accepted:
                gramm = spinBox.value()
                newton = (gramm / 1000.0) * 9.81
                self.send(f"k{newton}")
                str_gramm = f"{gramm}".replace('.', ',')
                str_newton = f"{newton:.3f}".replace('.', ',')
                msg_erfolg = QMessageBox(self)
                msg_erfolg.setWindowTitle("Erfolg")
                msg_erfolg.setText(f"Eingegeben: {str_gramm} g\nUmgerechnet: {str_newton} N\n\nErfolgreich kalibriert!")
                msg_erfolg.addButton("OK", QMessageBox.AcceptRole)
                msg_erfolg.exec_()

    def reset_graph_view(self):
        if self.data_x and self.data_y:
            max_x = max(self.data_x) * 1.1
            max_y = max(self.data_y) * 1.1
            min_y = min(self.data_y)
            if min_y > 0: min_y = 0
            self.graph.setXRange(0, max_x, padding=0)
            self.graph.setYRange(min_y, max_y, padding=0)
        else:
            self.graph.enableAutoRange(axis='xy')

    def clear_graph(self):
        if not self.data_x: return 
        msg = QMessageBox(self)
        msg.setWindowTitle("Löschen")
        msg.setText("Graph und Messdaten wirklich verwerfen?")
        btn_ja = msg.addButton("Ja, löschen", QMessageBox.YesRole)
        msg.addButton("Nein, behalten", QMessageBox.NoRole)
        msg.exec_()
        if msg.clickedButton() == btn_ja:
            self.data_x, self.data_y, self.start_pos = [], [], None
            self.max_force = 0.0 
            # --- GEÄNDERT: F Max statt F_max ---
            self.lbl_max.setText("F Max: 0.00 N")
            self.plot.setData([], [])
            self.reset_graph_view()
            self.status.setText("GRAPH GELÖSCHT")
            self.status.setStyleSheet("background: #6c757d; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_save.setEnabled(False)

    def start_test(self):
        self.data_x, self.data_y, self.start_pos = [], [], None
        self.max_force = 0.0 
        # --- GEÄNDERT: F Max statt F_max ---
        self.lbl_max.setText("F Max: 0.00 N")
        self.plot.setData([], []) 
        self.graph.enableAutoRange(axis='xy')
        self.is_measuring = True; self.send('t')
        self.btn_stop.setEnabled(True); self.btn_test.setEnabled(False); self.btn_clear.setEnabled(False)
        self.status.setText("MESSUNG LÄUFT...")
        self.status.setStyleSheet("background: #ffc107; color: black; padding: 10px; border-radius: 5px; font-weight: bold;")

    def save_csv(self):
        fn = f"{self.file_name.text()}.csv"
        try:
            with open(fn, "w", newline="") as f:
                w = csv.writer(f, delimiter=";") 
                w.writerow(["Weg_mm", "Kraft_N"])
                for x, y in zip(self.data_x, self.data_y):
                    w.writerow([f"{x:.3f}".replace('.', ','), f"{y:.3f}".replace('.', ',')])
            msg = QMessageBox(self)
            msg.setWindowTitle("Erfolg")
            msg.setText(f"Daten wurden erfolgreich gespeichert unter:\n{fn}")
            msg.addButton("OK", QMessageBox.AcceptRole)
            msg.exec_()
        except Exception as e:
            msg = QMessageBox(self)
            msg.setWindowTitle("Fehler")
            msg.setText(f"Konnte nicht speichern.\nDetails: {e}")
            msg.addButton("OK", QMessageBox.AcceptRole)
            msg.exec_()

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        event.accept()

if _name_ == "_main_":
    app = QApplication(sys.argv)
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))
    win = Dashboard()
    win.show()
    sys.exit(app.exec_())
