import sys, serial, serial.tools.list_ports, csv, os, bisect
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QLocale, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor
import pyqtgraph as pg

# Umrechnungsschrittfaktor für mm
STEP_TO_MM = 0.000467

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class SerialWorker(QThread):
    line_received = pyqtSignal(str)
    error_received = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.ser = None
        self.is_running = True

    def run(self):
        try:
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = 115200
            self.ser.timeout = 0.1
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            self.ser.open()
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

class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Zugmaschine - Profi Dashboard")
        self.resize(1100, 900)
        
        icon_path = resource_path('icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("myappid")
        
        self.worker = None 
        self.is_measuring = False
        self.start_pos = None 
        self.sg_baseline = None 
        
        self.plots = {}               
        self.cycle_data_x = {}        
        self.cycle_data_y = {}        
        self.all_measurements = []    
        self.current_cycle_idx = 0    
        
        self.max_force = 0.0  
        
        # Fadenkreuz-Variablen
        self.crosshair_active = False 
        self.active_crosshair_cycle = 0   
        self.crosshair_branch = 'upper'  
        self.last_mouse_x = 0.0          

        # Dauertest Variablen
        self.endpoint_steps = None
        self.last_known_steps = 262112
        self.dauertest_active = False
        self.dauertest_state = None
        self.remaining_cycles = 0
        
        self.dauertest_timer = QTimer()
        self.dauertest_timer.timeout.connect(self.handle_dauertest_timer)

        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        controls = QVBoxLayout()
        controls.setSpacing(8)
        
        self.port_box = QComboBox()
        for p in serial.tools.list_ports.comports(): self.port_box.addItem(p.device)
        self.btn_con = QPushButton("Verbinden")
        self.btn_con.clicked.connect(self.toggle_serial)
        
        self.status = QLabel("STATUS: GETRENNT")
        self.status.setStyleSheet("background: #444; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        self.status.setAlignment(Qt.AlignCenter)

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

        self.btn_test = QPushButton("EINZEL-TEST STARTEN")
        self.btn_test.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_test.setMinimumHeight(40)
        self.btn_test.setStyleSheet("background: #28a745; color: white;")
        self.btn_test.clicked.connect(self.start_test)
        
        self.btn_save_endpoint = QPushButton("Aktuelle Position als Endpunkt speichern")
        self.btn_save_endpoint.clicked.connect(self.save_endpoint)
        self.lbl_endpoint = QLabel("Endpunkt: Nicht gesetzt")
        self.lbl_endpoint.setStyleSheet("color: blue; font-weight: bold;")
        
        self.spin_cycles = QSpinBox()
        self.spin_cycles.setRange(1, 9999)
        self.spin_cycles.setValue(10)
        self.spin_cycles.setMinimumHeight(30)
        
        self.lbl_remaining_cycles = QLabel("Verbleibende Zyklen: -")
        self.lbl_remaining_cycles.setStyleSheet("font-size: 14px; font-weight: bold; color: #856404;")

        self.btn_start_dauertest = QPushButton("DAUERTEST STARTEN")
        self.btn_start_dauertest.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_start_dauertest.setMinimumHeight(40)
        self.btn_start_dauertest.setStyleSheet("background: #007bff; color: white;")
        self.btn_start_dauertest.clicked.connect(self.start_dauertest)

        self.btn_stop = QPushButton("MESSUNG STOPPEN")
        self.btn_stop.setFont(QFont("Arial", 11, QFont.Bold))
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setStyleSheet("background: #dc3545; color: white;")
        self.btn_stop.clicked.connect(lambda: self.send('q'))

        self.file_name = QLineEdit("Probe_001")
        self.btn_save = QPushButton("Daten Speichern (CSV)")
        self.btn_save.setMinimumHeight(35)
        self.btn_save.clicked.connect(self.save_csv)

        self.btn_clear = QPushButton("Neuen Graph / Daten löschen")
        self.btn_clear.setMinimumHeight(35)
        self.btn_clear.setStyleSheet("background: #ffc107; color: black; font-weight: bold;")
        self.btn_clear.clicked.connect(self.clear_graph)

        self.btn_view_all = QPushButton("Ansicht zurücksetzen (Auto-Fit)")
        self.btn_view_all.setMinimumHeight(35)
        self.btn_view_all.setStyleSheet("background: #6c757d; color: white; font-weight: bold;")
        self.btn_view_all.clicked.connect(self.reset_graph_view)

        self.btn_crosshair = QPushButton("Fadenkreuz: AUS")
        self.btn_crosshair.setMinimumHeight(35)
        self.btn_crosshair.setCheckable(True) 
        self.btn_crosshair.clicked.connect(self.toggle_crosshair)

        self.load_bar = QProgressBar()
        self.load_bar.setRange(0, 100)
        self.load_bar.setValue(0)
        self.load_bar.setTextVisible(True)
        self.load_bar.setFormat("Motor-Last: %p%")
        self.load_bar.setMinimumHeight(30)
        self.set_load_bar_color(0)

        self.buttons_prep = [self.btn_h, self.btn_zero, self.btn_tare, self.btn_cal, 
                             self.btn_clear, self.btn_test, self.btn_save_endpoint, self.btn_start_dauertest]

        for b in self.buttons_prep + [self.btn_stop, self.btn_save]:
            b.setEnabled(False)

        ui_elements = [
            QLabel("<b>1. Verbindung:</b>"), self.port_box, self.btn_con, self.status, 
            QLabel("<b>2. Vorbereitung:</b>"), self.btn_h, self.btn_zero, self.btn_tare, self.btn_cal,
            QLabel("<b>3. Einzel-Messung:</b>"), self.btn_test, self.lbl_max, 
            QLabel("<b>4. Dauertest (Zyklisch):</b>"), self.btn_save_endpoint, self.lbl_endpoint, QLabel("Anzahl Zyklen einstellen:"), self.spin_cycles, self.lbl_remaining_cycles, self.btn_start_dauertest,
            QLabel("<b>5. Allgemeiner Stopp:</b>"), self.btn_stop,
            QLabel("<b>6. Datenexport & Ansicht:</b>"), self.file_name, self.btn_save, self.btn_clear, self.btn_view_all, self.btn_crosshair,
            QLabel("<b>7. Motor-Überwachung:</b>"), self.load_bar
        ]
        
        for w in ui_elements:
            controls.addWidget(w)
            
        controls.addStretch()

        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        self.graph = pg.PlotWidget(title="Kraft-Weg-Diagramm")
        self.graph.setLabel('bottom', 'Weg (mm)')
        self.graph.setLabel('left', 'Kraft (N)')
        self.graph.showGrid(x=True, y=True)
        
        self.graph.addLegend(offset=(10, 10))
        self.graph.scene().sigMouseClicked.connect(self.mouse_clicked)
        
        self.plot = self.graph.plot(pen=pg.mkPen('r', width=3), name="Einzeltest")
        self.plots[self.current_cycle_idx] = self.plot
        self.cycle_data_x[self.current_cycle_idx] = []
        self.cycle_data_y[self.current_cycle_idx] = []

        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('gray', width=1, style=Qt.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('gray', width=1, style=Qt.DashLine))
        self.graph.addItem(self.vLine, ignoreBounds=True)
        self.graph.addItem(self.hLine, ignoreBounds=True)
        
        self.cursor_label = pg.TextItem(text="", color='k', fill=pg.mkBrush(255, 255, 255, 220))
        self.graph.addItem(self.cursor_label)
        
        self.vLine.setVisible(False)
        self.hLine.setVisible(False)
        self.cursor_label.setVisible(False)
        
        self.proxy = pg.SignalProxy(self.graph.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)

        layout.addLayout(controls, 2)
        layout.addWidget(self.graph, 8)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def keyPressEvent(self, event):
        if not self.crosshair_active or not self.plots:
            super().keyPressEvent(event)
            return
            
        if event.key() == Qt.Key_Up:
            self.crosshair_branch = 'upper'
            self.update_crosshair()
            
        elif event.key() == Qt.Key_Down:
            self.crosshair_branch = 'lower'
            self.update_crosshair()
            
        elif event.key() == Qt.Key_Right:
            available = sorted(list(self.plots.keys()))
            if available:
                idx = available.index(self.active_crosshair_cycle)
                next_idx = (idx + 1) % len(available)
                self.set_active_cycle(available[next_idx])
                
        elif event.key() == Qt.Key_Left:
            available = sorted(list(self.plots.keys()))
            if available:
                idx = available.index(self.active_crosshair_cycle)
                prev_idx = (idx - 1) % len(available)
                self.set_active_cycle(available[prev_idx])
        else:
            super().keyPressEvent(event)

    def mouse_clicked(self, evt):
        if not self.crosshair_active: return
        pos = evt.scenePos()
        if self.graph.plotItem.legend:
            for sample, label in self.graph.plotItem.legend.items:
                if label.sceneBoundingRect().contains(pos) or sample.sceneBoundingRect().contains(pos):
                    text = label.text
                    if "Zyklus" in text:
                        try: 
                            cycle_id = int(text.split()[1])
                            self.set_active_cycle(cycle_id)
                        except: pass
                    elif "Einzeltest" in text:
                        self.set_active_cycle(0)
                    evt.accept()
                    return

    def set_active_cycle(self, cycle_id):
        if cycle_id not in self.plots: return
        self.active_crosshair_cycle = cycle_id
        
        for cid, plot in self.plots.items():
            if cid == 0:
                color = QColor('red')
            else:
                hue = int(((cid - 1) * 137.5) % 360)  
                color = QColor.fromHsv(hue, 220, 200)
            
            if cid == cycle_id:
                color.setAlpha(255)
                plot.setPen(pg.mkPen(color, width=4.0))
                plot.setZValue(10) 
            else:
                color.setAlpha(60)
                plot.setPen(pg.mkPen(color, width=1.5))
                plot.setZValue(0)
                
        self.update_crosshair()

    def set_load_bar_color(self, percentage):
        if percentage > 85: color = "#dc3545"
        elif percentage > 60: color = "#ffc107"
        else: color = "#28a745"
        style = f"QProgressBar {{ border: 2px solid grey; border-radius: 5px; text-align: center; font-weight: bold; color: black; }} QProgressBar::chunk {{ background-color: {color}; }}"
        self.load_bar.setStyleSheet(style)

    def toggle_crosshair(self):
        if self.btn_crosshair.isChecked():
            self.crosshair_active = True
            self.btn_crosshair.setText("Fadenkreuz: EIN (Tipp: Klick auf Legende)")
            self.btn_crosshair.setStyleSheet("background: #17a2b8; color: white; font-weight: bold;")
            self.vLine.setVisible(True)
            self.hLine.setVisible(True)
            self.cursor_label.setVisible(True)
            
            if self.plots:
                self.set_active_cycle(max(self.plots.keys()))
        else:
            self.crosshair_active = False
            self.btn_crosshair.setText("Fadenkreuz: AUS")
            self.btn_crosshair.setStyleSheet("")
            self.vLine.setVisible(False)
            self.hLine.setVisible(False)
            self.cursor_label.setVisible(False)
            
            for cid, plot in self.plots.items():
                if cid == 0: color = QColor('red')
                else:
                    hue = int(((cid - 1) * 137.5) % 360)  
                    color = QColor.fromHsv(hue, 220, 200)
                color.setAlpha(255)
                plot.setPen(pg.mkPen(color, width=2.5))

    def mouse_moved(self, evt):
        if not getattr(self, 'crosshair_active', False) or not self.all_measurements: return
        pos = evt[0]
        if self.graph.sceneBoundingRect().contains(pos):
            mousePoint = self.graph.plotItem.vb.mapSceneToView(pos)
            self.last_mouse_x = mousePoint.x()
            self.update_crosshair()

    def update_crosshair(self):
        if not self.all_measurements or self.active_crosshair_cycle not in self.plots:
            return
            
        cycle_points = [m for m in self.all_measurements if m[3] == self.active_crosshair_cycle]
        if not cycle_points: return
            
        max_x_point = max(cycle_points, key=lambda m: m[1])
        max_x_idx = cycle_points.index(max_x_point)
        
        forward_points = cycle_points[:max_x_idx+1]
        backward_points = cycle_points[max_x_idx+1:]
        
        target_points = forward_points if self.crosshair_branch == 'upper' else backward_points
        if not target_points: 
            target_points = forward_points 
            
        closest_m = min(target_points, key=lambda m: abs(m[1] - self.last_mouse_x))
        
        zeit_ms = closest_m[0]
        echter_weg = closest_m[1]
        echte_kraft = closest_m[2]
        zyklus_id = closest_m[3]
        
        self.vLine.setPos(echter_weg)
        self.hLine.setPos(echte_kraft)
        
        branch_text = "Hinweg (Oberer Bogen)" if self.crosshair_branch == 'upper' else "Rückweg (Unterer Bogen)"
        
        text = f"Weg: {echter_weg:.2f} mm\nKraft: {echte_kraft:.2f} N\nZeit: {zeit_ms/1000:.1f} s"
        if zyklus_id > 0:
            text += f"\nZyklus: {zyklus_id}"
        else:
            text += "\nTyp: Einzeltest"
            
        text += f"\nKurve: {branch_text}"
            
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
        if self.worker: self.worker.send(char)

    def handle_usb_error(self, err_msg):
        if self.worker: 
            self.worker.stop()
            self.worker.wait()
            self.worker = None
        self.btn_con.setText("Verbinden")
        self.status.setText("USB GETRENNT!")
        self.status.setStyleSheet("background: #dc3545; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        for b in self.buttons_prep + [self.btn_stop, self.btn_save]: b.setEnabled(False)
        QMessageBox.warning(self, "Verbindungsabbruch", "Die USB-Verbindung wurde unterbrochen!\nBitte Kabel prüfen.")

    def save_endpoint(self):
        self.endpoint_steps = self.last_known_steps
        self.lbl_endpoint.setText(f"Endpunkt: {self.endpoint_steps} Steps")

    def start_dauertest(self):
        if self.endpoint_steps is None:
            QMessageBox.warning(self, "Fehler", "Bitte fahre den Motor zuerst an den gewünschten Endpunkt und klicke auf 'Endpunkt speichern'!")
            return
            
        for p in self.plots.values(): 
            self.graph.removeItem(p)
            
        if self.graph.plotItem.legend: 
            self.graph.plotItem.legend.clear() 
        
        self.plots = {}
        self.cycle_data_x = {}
        self.cycle_data_y = {}
        self.all_measurements = []
        
        self.remaining_cycles = self.spin_cycles.value()
        self.lbl_remaining_cycles.setText(f"Verbleibende Zyklen: {self.remaining_cycles}")
        
        self.current_cycle_idx = 1
        hue = int(((self.current_cycle_idx - 1) * 137.5) % 360)  
        color = QColor.fromHsv(hue, 220, 200)
        
        new_plot = self.graph.plot(pen=pg.mkPen(color, width=2.5), name=f"Zyklus {self.current_cycle_idx}")
        self.plots[self.current_cycle_idx] = new_plot
        self.cycle_data_x[self.current_cycle_idx] = []
        self.cycle_data_y[self.current_cycle_idx] = []
        
        self.active_crosshair_cycle = self.current_cycle_idx
        
        self.dauertest_active = True
        self.is_measuring = True
        self.dauertest_state = "MOVING_TO_END"
        
        for b in self.buttons_prep: b.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.status.setText("DAUERTEST: ZIEHE ZU ENDPUNKT")
        self.status.setStyleSheet("background: #007bff; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        
        self.start_pos = None
        self.sg_baseline = None
        self.max_force = 0.0 
        self.lbl_max.setText("F Max: 0.00 N")
        self.graph.enableAutoRange(axis='xy')
        
        self.send('w') 
        self.send(f"g{self.endpoint_steps}") 

    def handle_dauertest_timer(self):
        self.dauertest_timer.stop()
        if not self.dauertest_active: return
        
        if self.dauertest_state == "HOLDING_AT_END":
            self.dauertest_state = "MOVING_TO_START"
            self.status.setText("DAUERTEST: FAHRE ZU STARTPOSITION")
            self.status.setStyleSheet("background: #007bff; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.send("g262112") 
            
        elif self.dauertest_state == "HOLDING_AT_START":
            self.remaining_cycles -= 1
            self.lbl_remaining_cycles.setText(f"Verbleibende Zyklen: {self.remaining_cycles}")
            
            if self.remaining_cycles > 0:
                self.current_cycle_idx += 1
                
                hue = int(((self.current_cycle_idx - 1) * 137.5) % 360) 
                color = QColor.fromHsv(hue, 220, 200)
                
                new_plot = self.graph.plot(pen=pg.mkPen(color, width=2.5), name=f"Zyklus {self.current_cycle_idx}")
                self.plots[self.current_cycle_idx] = new_plot
                self.cycle_data_x[self.current_cycle_idx] = []
                self.cycle_data_y[self.current_cycle_idx] = []
                
                if not self.crosshair_active:
                    self.active_crosshair_cycle = self.current_cycle_idx
                
                # AUTO-TARA FIX FÜR MOTORWÄRME
                self.start_pos = None
                self.sg_baseline = None
                
                self.dauertest_state = "MOVING_TO_END"
                self.status.setText("DAUERTEST: ZIEHE ZU ENDPUNKT")
                self.status.setStyleSheet("background: #007bff; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
                self.send(f"g{self.endpoint_steps}")
            else:
                self.dauertest_active = False
                self.is_measuring = False
                self.status.setText("DAUERTEST BEENDET!")
                self.status.setStyleSheet("background: #28a745; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
                self.btn_stop.setEnabled(False)
                for b in self.buttons_prep: b.setEnabled(True)
                self.btn_save.setEnabled(True)

    def process_serial_line(self, line):
        if line.startswith("DATA:"):
            p = line.split(":")[1].split(",")
            if len(p) >= 4:
                time_ms = float(p[0])
                force = float(p[1])
                current_steps = float(p[2])
                sg_result = int(p[3])
                self.last_known_steps = int(current_steps) 
                
                if self.is_measuring:
                    if self.start_pos is None: 
                        self.start_pos = current_steps
                        self.sg_baseline = sg_result if sg_result > 0 else 1
                    mm = abs(self.start_pos - current_steps) * STEP_TO_MM
                    
                    self.all_measurements.append((time_ms, mm, force, self.current_cycle_idx))
                    
                    if self.current_cycle_idx not in self.cycle_data_x:
                        self.cycle_data_x[self.current_cycle_idx] = []
                        self.cycle_data_y[self.current_cycle_idx] = []
                        
                    self.cycle_data_x[self.current_cycle_idx].append(mm)
                    self.cycle_data_y[self.current_cycle_idx].append(force)
                    
                    if self.plots and self.current_cycle_idx in self.plots:
                        self.plots[self.current_cycle_idx].setData(self.cycle_data_x[self.current_cycle_idx], self.cycle_data_y[self.current_cycle_idx])
                    
                    drop = self.sg_baseline - sg_result
                    load_percent = max(0, min(100, int((drop / self.sg_baseline) * 100)))
                    self.load_bar.setValue(load_percent)
                    self.set_load_bar_color(load_percent)
                    
                    if force > self.max_force:
                        self.max_force = force
                        self.lbl_max.setText(f"F Max: {self.max_force:.2f} N")
        
        elif "Ziel erreicht" in line:
            if getattr(self, 'dauertest_active', False):
                if self.dauertest_state == "MOVING_TO_END":
                    self.dauertest_state = "HOLDING_AT_END"
                    self.status.setText("DAUERTEST: HALTEN OBEN (10s)")
                    self.status.setStyleSheet("background: #ffc107; color: black; padding: 10px; border-radius: 5px; font-weight: bold;")
                    self.dauertest_timer.start(10000) 
                elif self.dauertest_state == "MOVING_TO_START":
                    self.dauertest_state = "HOLDING_AT_START"
                    self.status.setText("DAUERTEST: HALTEN UNTEN (10s)")
                    self.status.setStyleSheet("background: #ffc107; color: black; padding: 10px; border-radius: 5px; font-weight: bold;")
                    self.dauertest_timer.start(10000) 
            else:
                self.is_measuring = False
                self.status.setText("BEREIT")
                self.status.setStyleSheet("background: #28a745; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
                self.btn_stop.setEnabled(False)
                self.btn_test.setEnabled(True)
                self.btn_clear.setEnabled(True)
                self.btn_save.setEnabled(True)
                self.load_bar.setValue(0)
                self.set_load_bar_color(0)
        
        elif "Abgebrochen" in line or "ALARM:" in line:
            if getattr(self, 'dauertest_active', False):
                self.dauertest_active = False
                self.dauertest_timer.stop()
            self.is_measuring = False
            if "ALARM:" in line:
                self.status.setText("NOT-AUS!")
                self.status.setStyleSheet("background: #dc3545; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            else:
                self.status.setText("ABGEBROCHEN")
                self.status.setStyleSheet("background: #6c757d; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_stop.setEnabled(False)
            for b in self.buttons_prep: b.setEnabled(True)
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
            spinBox.setRange(0.1, 100000.0)
            spinBox.setValue(1000.0)
            spinBox.setDecimals(1)
            layout.addWidget(spinBox)
            
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("Speichern")
            btn_cancel = QPushButton("Abbrechen")
            btn_box.addWidget(btn_ok)
            btn_box.addWidget(btn_cancel)
            layout.addLayout(btn_box)
            
            btn_ok.clicked.connect(dialog.accept)
            btn_cancel.clicked.connect(dialog.reject)
            
            if dialog.exec_() == QDialog.Accepted:
                gramm = spinBox.value()
                newton = (gramm / 1000.0) * 9.81
                self.send(f"k{newton}")
                msg_erfolg = QMessageBox(self)
                msg_erfolg.setWindowTitle("Erfolg")
                msg_erfolg.setText(f"Erfolgreich kalibriert auf {newton:.3f} N!")
                msg_erfolg.addButton("OK", QMessageBox.AcceptRole)
                msg_erfolg.exec_()

    def reset_graph_view(self):
        if self.all_measurements:
            all_x = [m[1] for m in self.all_measurements]
            all_y = [m[2] for m in self.all_measurements]
            self.graph.setXRange(0, max(all_x) * 1.1, padding=0)
            self.graph.setYRange(min(all_y), max(all_y) * 1.1, padding=0)
        else: 
            self.graph.enableAutoRange(axis='xy')

    def clear_graph(self):
        if not self.all_measurements: return 
        msg = QMessageBox(self)
        msg.setWindowTitle("Löschen")
        msg.setText("Graph und Messdaten wirklich verwerfen?")
        btn_ja = msg.addButton("Ja, löschen", QMessageBox.YesRole)
        msg.addButton("Nein, behalten", QMessageBox.NoRole)
        msg.exec_()
        
        if msg.clickedButton() == btn_ja:
            for p in self.plots.values(): 
                self.graph.removeItem(p)
                
            if self.graph.plotItem.legend: 
                self.graph.plotItem.legend.clear() 
            
            self.plots = {}
            self.cycle_data_x = {}
            self.cycle_data_y = {}
            self.all_measurements = []
            
            self.current_cycle_idx = 0
            self.plot = self.graph.plot(pen=pg.mkPen('r', width=3), name="Einzeltest")
            self.plots[self.current_cycle_idx] = self.plot
            self.cycle_data_x[self.current_cycle_idx] = []
            self.cycle_data_y[self.current_cycle_idx] = []
            self.active_crosshair_cycle = 0
            
            self.start_pos = None
            self.sg_baseline = None
            self.max_force = 0.0 
            self.lbl_max.setText("F Max: 0.00 N")
            self.reset_graph_view()
            self.status.setText("GRAPH GELÖSCHT")
            self.status.setStyleSheet("background: #6c757d; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
            self.btn_save.setEnabled(False)
            self.load_bar.setValue(0)
            self.set_load_bar_color(0)

    def start_test(self):
        for p in self.plots.values(): 
            self.graph.removeItem(p)
            
        if self.graph.plotItem.legend: 
            self.graph.plotItem.legend.clear() 
        
        self.plots = {}
        self.cycle_data_x = {}
        self.cycle_data_y = {}
        self.all_measurements = []
        
        self.current_cycle_idx = 0 
        self.plot = self.graph.plot(pen=pg.mkPen('r', width=3), name="Einzeltest")
        self.plots[self.current_cycle_idx] = self.plot
        self.cycle_data_x[self.current_cycle_idx] = []
        self.cycle_data_y[self.current_cycle_idx] = []
        self.active_crosshair_cycle = 0
        
        self.start_pos = None
        self.sg_baseline = None
        self.max_force = 0.0 
        self.lbl_max.setText("F Max: 0.00 N")
        self.graph.enableAutoRange(axis='xy')
        
        self.is_measuring = True
        self.send('t')
        
        self.btn_stop.setEnabled(True)
        self.btn_test.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.status.setText("MESSUNG LÄUFT...")
        self.status.setStyleSheet("background: #ffc107; color: black; padding: 10px; border-radius: 5px; font-weight: bold;")

    def save_csv(self):
        default_name = f"{self.file_name.text()}.csv" if self.file_name.text() else "Messdaten.csv"
        
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Daten exportieren (MATLAB-Format)", 
            default_name, 
            "CSV Dateien (*.csv);;Alle Dateien (*)", 
            options=options
        )
        
        if not file_path:
            return 
            
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=",") 
                for t, x, y, c in self.all_measurements: 
                    w.writerow([
                        f"{t:.0f}",
                        f"{x:.3f}", 
                        f"{y:.3f}", 
                        str(c)
                    ])
            QMessageBox.information(self, "Erfolg", f"Daten erfolgreich exportiert nach:\n{file_path}")
        except Exception as e: 
            QMessageBox.warning(self, "Fehler", f"Fehler beim Speichern:\n{e}\n\nIst die Datei evtl. noch in MATLAB/Excel geöffnet?")

    def closeEvent(self, event):
        if self.worker: 
            self.worker.stop()
            self.worker.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))
    win = Dashboard()
    win.show()
    sys.exit(app.exec_())
