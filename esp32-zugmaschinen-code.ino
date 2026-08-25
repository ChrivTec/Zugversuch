#include <Arduino.h>
#include <FastAccelStepper.h> 
#include <HX711.h>
#include <TMCStepper.h>
#include <Preferences.h>

#define NORMAL_CURRENT 1100             
#define R_SENSE 0.11f                  

#define TASTER_GESCHWINDIGKEIT 12000    
#define HOMING_GESCHWINDIGKEIT 8000     
#define MESS_GESCHWINDIGKEIT 535  // Exakt 15 mm/min      
#define POSITION_X 262112               

#define HX711_DT 21
#define HX711_SCK 22
#define MOTOR_STEP 12
#define MOTOR_DIR 14
#define MOTOR_EN 13    
#define TMC_UART_TX 17 
#define TMC_UART_RX 16 
#define BTN_VOR 25
#define BTN_ZURUECK 26
#define BTN_STOP 27    

HX711 scale;
Preferences prefs; 
HardwareSerial TMCSerial(2); 
TMC2209Stepper driver(&TMCSerial, R_SENSE, 0x00);

FastAccelStepperEngine engine = FastAccelStepperEngine();
FastAccelStepper *stepper = NULL;

long lastLogTime = 0;
bool autoFahrt = false; 
volatile bool notAusAktiv = false; 
bool letzterZustandTaster = false;
volatile uint16_t liveWiderstand = 510; 
volatile bool homingAktiv = false;      
TaskHandle_t SensorTask;                

void fuehreHomingAus();

void sensorTaskCode( void * pvParameters ){
  for(;;){
    if(homingAktiv || autoFahrt || stepper->isRunning()){ 
        liveWiderstand = driver.SG_RESULT(); 
    }
    vTaskDelay(10 / portTICK_PERIOD_MS); 
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_VOR, INPUT_PULLUP);
  pinMode(BTN_ZURUECK, INPUT_PULLUP);
  pinMode(BTN_STOP, INPUT_PULLUP); 
  pinMode(MOTOR_EN, OUTPUT);
  digitalWrite(MOTOR_EN, LOW); 

  TMCSerial.begin(115200, SERIAL_8N1, TMC_UART_RX, TMC_UART_TX);
  driver.begin();
  
  driver.toff(5); driver.rms_current(NORMAL_CURRENT, 0.15); driver.microsteps(16);     
  driver.en_spreadCycle(false); driver.pwm_autoscale(true); driver.shaft(true); 

  engine.init();
  stepper = engine.stepperConnectToPin(MOTOR_STEP);
  if (stepper) {
    stepper->setDirectionPin(MOTOR_DIR);
    stepper->setAutoEnable(false); 
    stepper->setAcceleration(80000); 
  }

  scale.begin(HX711_DT, HX711_SCK);
  prefs.begin("zugmaschine", false);
  float savedScale = prefs.getFloat("scaleFactor", 1.0f);
  scale.set_scale(savedScale);
  scale.tare(); 

  xTaskCreatePinnedToCore(sensorTaskCode, "SensorTask", 10000, NULL, 1, &SensorTask, 0);               

  Serial.println("INFO:Bereit");
  if(digitalRead(BTN_STOP) == LOW) {
    notAusAktiv = true; digitalWrite(MOTOR_EN, HIGH); Serial.println("ALARM:NOT-AUS");
  } else {
    fuehreHomingAus(); 
  }
}

void loop() {
  if (digitalRead(BTN_STOP) == LOW) {
    if (!notAusAktiv) {
      notAusAktiv = true; digitalWrite(MOTOR_EN, HIGH); autoFahrt = false;
      stepper->forceStopAndNewPosition(stepper->getCurrentPosition());
      Serial.println("ALARM:NOT-AUS");
    }
  } else if (notAusAktiv && digitalRead(BTN_STOP) == HIGH) {
      delay(100); if(digitalRead(BTN_STOP) == HIGH) {
          notAusAktiv = false; digitalWrite(MOTOR_EN, LOW); Serial.println("INFO:Not-Aus entriegelt");
      }
  }
  if (notAusAktiv) return;

  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == 't') { 
      if (scale.is_ready()) { scale.tare(); }
      autoFahrt = true; 
      stepper->setSpeedInHz(MESS_GESCHWINDIGKEIT); 
      stepper->runBackward(); 
      Serial.println("INFO:Test gestartet");
    }
    // --- NEU: Fahre zu einer absoluten Position mit Testgeschwindigkeit ---
    else if (cmd == 'g') { 
      long target = Serial.parseInt();
      autoFahrt = true;
      stepper->setSpeedInHz(MESS_GESCHWINDIGKEIT);
      stepper->moveTo(target);
      Serial.println("INFO:Dauertest Fahrt");
    }
    else if (cmd == 'q') { 
      autoFahrt = false; 
      stepper->stopMove(); 
      Serial.println("INFO:Abgebrochen");
    }
    else if (cmd == 'h') { fuehreHomingAus(); }
    else if (cmd == 'n') { 
      autoFahrt = true; 
      stepper->setSpeedInHz(TASTER_GESCHWINDIGKEIT); 
      stepper->moveTo(POSITION_X); 
      Serial.println("INFO:Fahre zur Startposition");
    }
    else if (cmd == 'w') { scale.tare(); Serial.println("INFO:Waage genullt"); }
    else if (cmd == 'k') { 
      float weight = Serial.parseFloat();
      if (weight > 0) {
        long raw = scale.get_value(10);
        float newScale = (float)raw / weight;
        scale.set_scale(newScale);
        prefs.putFloat("scaleFactor", newScale);
        Serial.print("INFO:Kalibriert");
      }
    }
  }

  bool vor = (digitalRead(BTN_VOR) == LOW);
  bool zurueck = (digitalRead(BTN_ZURUECK) == LOW);
  bool tasterAktiv = (vor || zurueck);
  
  if (tasterAktiv) {
      autoFahrt = false;
      stepper->setSpeedInHz(TASTER_GESCHWINDIGKEIT);
      if (vor && !zurueck) stepper->runForward();
      else if (zurueck && !vor) stepper->runBackward();
  } 

  if (!tasterAktiv && letzterZustandTaster && !autoFahrt) {
      stepper->stopMove(); 
  }
  letzterZustandTaster = tasterAktiv;

  if (autoFahrt && !stepper->isRunning()) {
    autoFahrt = false; Serial.println("INFO:Ziel erreicht");
  }

  if (autoFahrt || stepper->isRunning()) {
    if (millis() - lastLogTime >= 15) {
      if (scale.is_ready()) {
        Serial.print("DATA:"); Serial.print(millis()); Serial.print(",");
        Serial.print(scale.get_units(1)); Serial.print(",");
        Serial.print(stepper->getCurrentPosition()); Serial.print(",");
        Serial.println(liveWiderstand);
        lastLogTime = millis(); 
      }
    }
  }
}

void fuehreHomingAus() {
  Serial.println("INFO:Homing startet");
  driver.rms_current(600); driver.TCOOLTHRS(0xFFFFF); driver.SGTHRS(100); 
  stepper->setSpeedInHz(HOMING_GESCHWINDIGKEIT); 
  stepper->runBackward(); 
  uint32_t startZeit = millis(); homingAktiv = true; 
  while (true) {
    if (digitalRead(BTN_STOP) == LOW) return;
    if (millis() - startZeit > 1500) {
      if (liveWiderstand < 150) { break; }
    }
    delay(5); 
  }
  homingAktiv = false; stepper->forceStopAndNewPosition(0); delay(500); 
  driver.rms_current(NORMAL_CURRENT, 0.15); 
  stepper->setSpeedInHz(TASTER_GESCHWINDIGKEIT);
  stepper->moveTo(POSITION_X); 
  while (stepper->isRunning()) { delay(10); }
  Serial.println("INFO:Homing fertig");
}
