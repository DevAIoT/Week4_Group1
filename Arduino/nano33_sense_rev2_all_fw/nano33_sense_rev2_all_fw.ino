#include <Arduino_HS300x.h>
#include <Arduino_LPS22HB.h>
#include <Arduino_APDS9960.h>
#include <Arduino_BMI270_BMM150.h>
#include <Arduino_JSON.h>

// TensorFlow Lite for RSSI prediction
#include <TensorFlowLite.h>
#include <tensorflow/lite/micro/all_ops_resolver.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_log.h>
#include <tensorflow/lite/micro/system_setup.h>
#include <tensorflow/lite/schema/schema_generated.h>

// ML model and configuration
#include "rssi_model.h"
#include "model_config.h"

// ML prediction mode: true = use ML, false = use formula
#define USE_ML_PREDICTION true

const int LED_PIN = LED_BUILTIN;

// Do not use names LEDR/LEDG/LEDB (these are macros)!
const int RGB_R = LEDR;  // (22u)
const int RGB_G = LEDG;  // (23u)
const int RGB_B = LEDB;  // (24u)

String cmd;

// --- TensorFlow Lite Global Variables ---
namespace {
  const tflite::Model* tflite_model = nullptr;
  tflite::MicroInterpreter* tflite_interpreter = nullptr;
  TfLiteTensor* tflite_input = nullptr;
  TfLiteTensor* tflite_output = nullptr;

  // Tensor arena for intermediate arrays
  constexpr int kTensorArenaSize = TFLITE_ARENA_SIZE;
  alignas(16) uint8_t tensor_arena[kTensorArenaSize];

  // Model initialization status
  bool ml_model_ready = false;
}

// --- CSV Streaming Data Structures ---
struct CSVRecord {
  uint32_t timestamp;

  // Geographic and cell tower fields (NEW)
  float latitude;       // GPS latitude (-90 to 90 degrees)
  float longitude;      // GPS longitude (-180 to 180 degrees)
  float elevation;      // Altitude above sea level (meters)
  int16_t pci;         // Physical Cell Identity (0-503)
  uint32_t cell_id;    // Cell Tower ID

  // Signal quality fields
  int8_t rsrp;  // -140 to -44 dBm range
  int8_t rsrq;  // -20 to -3 dB range
  int8_t rssi;  // Will be calculated if 0
  int8_t sinr;  // -20 to 30 dB range
  bool rssi_is_calculated;  // Flag indicating RSSI was calculated
};
// New size: ~26 bytes (was ~10 bytes)

struct StreamState {
  bool active;
  uint32_t record_count;
};

StreamState streamState = {false, 0};

static inline void setRgb(uint8_t r, uint8_t g, uint8_t b) {
  // active-low PWM: analogWrite(pin, 255-r)
  analogWrite(RGB_R, 255 - r);
  analogWrite(RGB_G, 255 - g);
  analogWrite(RGB_B, 255 - b);
}

static inline void rgbOff() { setRgb(0, 0, 0); }

int8_t calculateRSSI(int8_t rsrp, int8_t rsrq) {
  // Formula: RSSI = RSRP - RSRQ + 14
  // Based on: RSRQ = RSRP - RSSI + 10*log10(N_RB)
  // Assuming N_RB=25 (5MHz channel): 10*log10(25) ≈ 14 dB

  int calculated = rsrp - rsrq + 14;

  // Clamp to typical LTE RSSI range [-120, -25] dBm
  if (calculated < -120) calculated = -120;
  if (calculated > -25) calculated = -25;

  return (int8_t)calculated;
}

// Normalize feature value using StandardScaler parameters
float normalizeFeature(float value, int feature_idx) {
  return (value - feature_means[feature_idx]) / feature_scales[feature_idx];
}

// ML-based RSSI prediction
int8_t predictRSSI_ML(int8_t rsrp, int8_t rsrq, int8_t sinr,
                       float latitude, float longitude, float elevation) {
  // Fallback to formula if ML not ready
  if (!ml_model_ready || !USE_ML_PREDICTION) {
    return calculateRSSI(rsrp, rsrq);
  }

  // Normalize input features (order: RSRP, RSRQ, SINR, Lat, Lon, Elev)
  tflite_input->data.f[0] = normalizeFeature((float)rsrp, 0);
  tflite_input->data.f[1] = normalizeFeature((float)rsrq, 1);
  tflite_input->data.f[2] = normalizeFeature((float)sinr, 2);
  tflite_input->data.f[3] = normalizeFeature(latitude, 3);
  tflite_input->data.f[4] = normalizeFeature(longitude, 4);
  tflite_input->data.f[5] = normalizeFeature(elevation, 5);

  // Run inference
  TfLiteStatus invoke_status = tflite_interpreter->Invoke();
  if (invoke_status != kTfLiteOk) {
    Serial.println("ERR=ML_INFERENCE_FAILED");
    // Fallback to formula on error
    return calculateRSSI(rsrp, rsrq);
  }

  // Get prediction
  float rssi_predicted = tflite_output->data.f[0];

  // Clamp to valid RSSI range
  if (rssi_predicted < RSSI_MIN) rssi_predicted = RSSI_MIN;
  if (rssi_predicted > RSSI_MAX) rssi_predicted = RSSI_MAX;

  return (int8_t)round(rssi_predicted);
}

// Initialize TensorFlow Lite model
bool initMLModel() {
  // Load model
  tflite_model = tflite::GetModel(rssi_model_tflite);
  if (tflite_model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.print("ERR=TFLITE_VERSION_MISMATCH,MODEL=");
    Serial.print(tflite_model->version());
    Serial.print(",EXPECTED=");
    Serial.println(TFLITE_SCHEMA_VERSION);
    return false;
  }

  // Create ops resolver (includes all operations)
  static tflite::AllOpsResolver resolver;

  // Build interpreter
  static tflite::MicroInterpreter static_interpreter(
      tflite_model, resolver, tensor_arena, kTensorArenaSize);
  tflite_interpreter = &static_interpreter;

  // Allocate tensors
  TfLiteStatus allocate_status = tflite_interpreter->AllocateTensors();
  if (allocate_status != kTfLiteOk) {
    Serial.println("ERR=TFLITE_ALLOC_FAILED");
    return false;
  }

  // Get input/output tensors
  tflite_input = tflite_interpreter->input(0);
  tflite_output = tflite_interpreter->output(0);

  // Verify tensor dimensions
  if (tflite_input->dims->size != 2 || tflite_input->dims->data[1] != NUM_FEATURES) {
    Serial.print("ERR=TFLITE_INPUT_DIM,EXPECTED=");
    Serial.print(NUM_FEATURES);
    Serial.print(",GOT=");
    Serial.println(tflite_input->dims->data[1]);
    return false;
  }

  Serial.println("INFO=TFLITE_READY");
  return true;
}

void sendProcessedRecord(CSVRecord& rec, bool is_anomaly) {
  JSONVar result;
  result["type"] = "PROCESSED";
  result["timestamp"] = (int)rec.timestamp;

  // Geographic and cell tower fields (NEW)
  result["latitude"] = rec.latitude;
  result["longitude"] = rec.longitude;
  result["elevation"] = rec.elevation;
  result["pci"] = (int)rec.pci;
  result["cell_id"] = (int)rec.cell_id;

  // Signal quality fields
  result["rsrp"] = (int)rec.rsrp;
  result["rsrq"] = (int)rec.rsrq;
  result["rssi"] = (int)rec.rssi;
  result["sinr"] = (int)rec.sinr;
  result["is_anomaly"] = is_anomaly;
  result["record_num"] = (int)streamState.record_count;
  result["rssi_is_calculated"] = rec.rssi_is_calculated;

  Serial.println(JSON.stringify(result));
}

void processRecord(CSVRecord& rec) {
  streamState.record_count++;

  // Detect anomaly (poor signal quality)
  bool is_anomaly = (rec.rsrp < -100) || (rec.sinr < 0);

  // Send individual record result immediately
  sendProcessedRecord(rec, is_anomaly);
}

void handleCommand(const String& s) {
  if (s == "LED=ON") {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("ACK=LED_ON");
    return;
  }
  if (s == "LED=OFF") {
    digitalWrite(LED_PIN, LOW);
    Serial.println("ACK=LED_OFF");
    return;
  }

  if (s.startsWith("RGB=")) {
    int r = -1, g = -1, b = -1;
    if (sscanf(s.c_str(), "RGB=%d,%d,%d", &r, &g, &b) == 3) {
      r = constrain(r, 0, 255);
      g = constrain(g, 0, 255);
      b = constrain(b, 0, 255);
      setRgb((uint8_t)r, (uint8_t)g, (uint8_t)b);
      Serial.print("ACK=RGB,");
      Serial.print(r); Serial.print(",");
      Serial.print(g); Serial.print(",");
      Serial.println(b);
      return;
    }
    Serial.print("ERR=BAD_RGB,VAL=");
    Serial.println(s);
    return;
  }

  // --- CSV Streaming Commands ---
  if (s.startsWith("STREAM=")) {
    if (s == "STREAM=START") {
      streamState.active = true;
      streamState.record_count = 0;
      Serial.println("ACK=STREAM_START");
      return;
    }
    if (s == "STREAM=STOP") {
      streamState.active = false;
      Serial.println("ACK=STREAM_STOP");
      return;
    }
    if (s == "STREAM=RESET") {
      streamState.active = false;
      streamState.record_count = 0;
      Serial.println("ACK=STREAM_RESET");
      return;
    }
  }

  if (s.startsWith("DATA=")) {
    if (!streamState.active) {
      Serial.println("ERR=NOT_STREAMING");
      return;
    }

    // Parse: DATA=timestamp,latitude,longitude,elevation,pci,cell_id,rsrp,rsrq,rssi,sinr
    CSVRecord rec;
    long timestamp_long;
    float lat_float, lon_float, elev_float;
    int pci_int, rsrp_int, rsrq_int, rssi_int, sinr_int;
    long cell_id_long;

    if (sscanf(s.c_str(), "DATA=%ld,%f,%f,%f,%d,%ld,%d,%d,%d,%d",
               &timestamp_long, &lat_float, &lon_float, &elev_float,
               &pci_int, &cell_id_long,
               &rsrp_int, &rsrq_int, &rssi_int, &sinr_int) == 10) {

      // Assign parsed values
      rec.timestamp = (uint32_t)timestamp_long;
      rec.latitude = lat_float;
      rec.longitude = lon_float;
      rec.elevation = elev_float;
      rec.pci = (int16_t)pci_int;
      rec.cell_id = (uint32_t)cell_id_long;
      rec.rsrp = (int8_t)rsrp_int;
      rec.rsrq = (int8_t)rsrq_int;
      rec.sinr = (int8_t)sinr_int;

      // Check if RSSI is missing (Python sends 0 for missing values)
      if (rssi_int == 0) {
        // Predict RSSI using ML model (or formula as fallback)
        rec.rssi = predictRSSI_ML(rec.rsrp, rec.rsrq, rec.sinr,
                                   rec.latitude, rec.longitude, rec.elevation);
        rec.rssi_is_calculated = true;
      } else {
        // Use measured RSSI from CSV
        rec.rssi = (int8_t)rssi_int;
        rec.rssi_is_calculated = false;
      }

      // Process the record
      processRecord(rec);
      return;
    }

    Serial.print("ERR=PARSE_FAILED,VAL=");
    Serial.println(s);
    return;
  }

  Serial.print("ERR=UNKNOWN_CMD,VAL=");
  Serial.println(s);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  pinMode(RGB_R, OUTPUT);
  pinMode(RGB_G, OUTPUT);
  pinMode(RGB_B, OUTPUT);
  rgbOff();

  bool ok = true;
  if (!HS300x.begin()) { Serial.println("ERR=HS300x_INIT"); ok = false; }
  if (!BARO.begin())   { Serial.println("ERR=LPS22HB_INIT"); ok = false; }
  if (!APDS.begin())   { Serial.println("ERR=APDS9960_INIT"); ok = false; }
  if (!IMU.begin())    { Serial.println("ERR=IMU_INIT"); ok = false; }

  if (!ok) {
    Serial.println("ERR=INIT_FAILED");
    while (1) {}
  }

  // Initialize TensorFlow Lite model for RSSI prediction
  ml_model_ready = initMLModel();
  if (!ml_model_ready) {
    Serial.println("WARN=ML_INIT_FAILED,USING_FORMULA");
  }

  Serial.println("READY");
  Serial.println("Commands: LED=ON|OFF, RGB=R,G,B (0-255)");
}

void loop() {
  // read commands
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmd.length() > 0) {
        cmd.trim();
        handleCommand(cmd);
        cmd = "";
      }
    } else {
      cmd += c;
      if (cmd.length() > 96) { cmd = ""; Serial.println("ERR=CMD_TOO_LONG"); }
    }
  }

  // publish JSON @ 1Hz
  static unsigned long last = 0;
  unsigned long now = millis();
  if (now - last < 1000) return;
  last = now;

  JSONVar root;

  root["hs3003_t_c"]  = (double)HS300x.readTemperature();
  root["hs3003_h_rh"] = (double)HS300x.readHumidity();

  root["lps22hb_p_kpa"] = (double)BARO.readPressure();
  root["lps22hb_t_c"]   = (double)BARO.readTemperature();

  if (APDS.proximityAvailable()) {
    root["apds_prox"] = APDS.readProximity();
  }
  if (APDS.colorAvailable()) {
    int r, g, b, c;
    APDS.readColor(r, g, b, c);
    JSONVar col;
    col["r"] = r; col["g"] = g; col["b"] = b; col["c"] = c;
    root["apds_color"] = col;
  }
  if (APDS.gestureAvailable()) {
    root["apds_gesture"] = APDS.readGesture();
  }

  if (IMU.accelerationAvailable()) {
    float x, y, z;
    IMU.readAcceleration(x, y, z);
    JSONVar a; a["x"]=x; a["y"]=y; a["z"]=z;
    root["acc_g"] = a;
  }
  if (IMU.gyroscopeAvailable()) {
    float x, y, z;
    IMU.readGyroscope(x, y, z);
    JSONVar g; g["x"]=x; g["y"]=y; g["z"]=z;
    root["gyro_dps"] = g;
  }
  if (IMU.magneticFieldAvailable()) {
    float x, y, z;
    IMU.readMagneticField(x, y, z);
    JSONVar m; m["x"]=x; m["y"]=y; m["z"]=z;
    root["mag_uT"] = m;
  }

  Serial.println(JSON.stringify(root));
}
