// Feature normalization parameters for RSSI ML model
// Generated from training with StandardScaler
// Features: RSRP, RSRQ, SINR, Latitude, Longitude, Elevation

#ifndef MODEL_CONFIG_H
#define MODEL_CONFIG_H

// Number of input features
#define NUM_FEATURES 6

// Feature normalization parameters (from StandardScaler)
// Formula: normalized = (value - mean) / scale

const float feature_means[NUM_FEATURES] = {
  -92.82158798394855,   // RSRP mean
  -12.378179738080586,  // RSRQ mean
  5.899808457344924,    // SINR mean
  47.850803844157944,   // Latitude mean
  13.205420546494691,   // Longitude mean
  592.1170299621222     // Elevation mean
};

const float feature_scales[NUM_FEATURES] = {
  10.85231552752163,    // RSRP scale
  2.469692534687768,    // RSRQ scale
  9.068259673106164,    // SINR scale
  0.004299538384380982, // Latitude scale
  0.06606928273926402,  // Longitude scale
  38.31224337837014     // Elevation scale
};

// Feature names (for debugging)
const char* feature_names[NUM_FEATURES] = {
  "RSRP",
  "RSRQ",
  "SINR",
  "Latitude",
  "Longitude",
  "Elevation"
};

// Model output range (dBm)
#define RSSI_MIN -120.0
#define RSSI_MAX -25.0

// TensorFlow Lite arena size (bytes)
// Adjust if model is larger or if memory is constrained
#define TFLITE_ARENA_SIZE (10 * 1024)  // 10 KB

#endif // MODEL_CONFIG_H
