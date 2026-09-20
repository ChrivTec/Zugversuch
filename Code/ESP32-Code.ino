#include <Arduino.h>
#include <TMCStepper.h>
#include <AccelStepper.h>
#include <HX711.h> 

// --- Pin-Definitionen ---
// TMC2209 (Stepper)
#define EN_PIN           14 // Enable
#define DIR_PIN          27 // Direction
#define STEP_PIN         26 // Step
#define SERIAL_PORT      Serial2 // Hardware Serial 2 für ESP32 UART
#define DRIVER_ADDRESS   0b00    // TMC2209 Adresse (je nach Hardware-Config)
#define R_SENSE          0.11f   // Messwiderstand (Standard bei TMC2209)

// Kraftmessdose (HX711)
#define LOADCELL_DOUT_PIN 33
#define LOADCELL_SCK_PIN  32

// --- Objekte instanziieren ---
TMC2209Stepper driver(&SERIAL_PORT, R_SENSE, DRIVER_ADDRESS);
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
HX711 scale;

// --- Status-Variablen ---
bool isTesting = false;

// Deine 15 mm/min entsprechen einer bestimmten Steps/Sekunde-Rate.
// Beispiel: 15 mm/min = 0.25 mm/s. Bei 1/16 Mikroschritten und 4mm Spindelsteigung -> 200 Steps/sec.
float testSpeedStepsPerSec = 200.0; 

void setup() {
  // Kommunikation zum Python-Dashboard
  Serial.begin(115200);
  
  // TMC2209 UART Setup
  SERIAL_PORT.begin(115200); // ESP32 Serial2 nutzt default RX2=16, TX2=17 (anpassen falls nötig)
  
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW); // Motor Enable (Low = Aktiv)
  
  // TMC2209 konfigurieren
  driver.begin();
  driver.toff(5);                 // Enable Driver
  driver.rms_current(1000);       // Motorstrom auf 1000mA (anpassen an deinen Motor!)
  driver.microsteps(16);          // 1/16 Mikroschritte für ruhigen Lauf
  driver.pwm_autoscale(true);     // StealthChop für leisen Betrieb aktivieren
  
  // AccelStepper Setup
  stepper.setMaxSpeed(2000); 
  stepper.setAcceleration(500);
  
  // Loadcell Setup & Auto-Tara
  Serial.println("Initialisiere Waage...");
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(228.0f); // WICHTIG: Hier deinen ermittelten Kalibrierungsfaktor eintragen!
  scale.tare();            // Automatisches Tara beim Start
  
  Serial.println("Zugmaschine bereit.");
}

void loop() {
  // Befehle vom Python-Dashboard empfangen
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    
    switch(cmd) {
      case 'S': // Start Zugversuch (15 mm/min)
        isTesting = true;
        stepper.setSpeed(testSpeedStepsPerSec); 
        Serial.println("STATUS:START");
        break;
        
      case 'H': // Halt / Stop
        isTesting = false;
        stepper.stop();
        Serial.println("STATUS:STOP");
        break;
        
      case 'T': // Tara setzen
        scale.tare();
        Serial.println("STATUS:TARE_OK");
        break;
        
      case 'R': // Reverse (Motor zurückfahren)
        isTesting = true;
        stepper.setSpeed(-testSpeedStepsPerSec);
        Serial.println("STATUS:REVERSE");
        break;
    }
  }

  // Wenn der Test läuft: Motor bewegen und Daten ans Dashboard senden
  if (isTesting) {
    stepper.runSpeed(); // Motor mit konstanter Geschwindigkeit bewegen (nicht blockierend)
    
    // Daten-Logging (z.B. alle 50ms an das Python-Dashboard senden)
    static unsigned long lastLog = 0;
    if (millis() - lastLog >= 50) {
      float currentForce = scale.get_units();
      // Format für Python Dashboard: "DATA:<Kraft>"
      Serial.print("DATA:");
      Serial.println(currentForce, 2);
      lastLog = millis();
    }
  }
}
