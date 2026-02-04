# TinyML RSSI Inference Implementation Summary

## Overview

This implementation replaces the formula-based RSSI calculation with a TensorFlow Lite neural network that runs on-device on the Arduino Nano 33 Sense Rev2. The ML model learns from 144,225 real-world LTE signal measurements to predict RSSI values.

## Implementation Status

**Status:** COMPLETE (with recommendation to use formula)

All infrastructure has been successfully implemented:
- [x] Data analysis and validation scripts
- [x] ML model training pipeline
- [x] TFLite model conversion
- [x] Arduino header files generated
- [x] Firmware integration complete

## Validation Results

### Model Performance (on 14,423 test samples)

**TFLite ML Model:**
- MAE: 2.931 dBm
- RMSE: 3.545 dBm
- R² Score: 0.8167

**Formula Baseline (RSSI = RSRP - RSRQ + 14):**
- MAE: 3.952 dBm
- RMSE: 4.708 dBm
- R² Score: 0.6766

**ML Improvement:** 1.021 dBm (25.8% improvement)

### Decision

**Recommendation: Continue using formula-based approach**

**Reasoning:**
- ML improves MAE by only 1.021 dBm (below the 2.0 dBm threshold)
- Formula is simpler, requires no ML overhead
- TFLite conversion is perfect (0.0000% degradation)
- ML infrastructure remains available for future enhancements

## Technical Details

### Model Architecture

```
Input(6 features) → Dense(32, ReLU) → Dense(16, ReLU) → Dense(1)
Total parameters: 769 (3.00 KB)
TFLite model size: 4.86 KB
```

### Input Features

1. **RSRP** (Reference Signal Received Power, dBm)
2. **RSRQ** (Reference Signal Received Quality, dB)
3. **SINR** (Signal-to-Interference-plus-Noise Ratio, dB)
4. **Latitude** (GPS coordinates, degrees)
5. **Longitude** (GPS coordinates, degrees)
6. **Elevation** (Altitude, meters)

### Resource Usage

- **Flash Memory:** ~5 KB for model + ~20-30 KB for TFLite library
- **RAM:** ~10 KB for tensor arena + inference buffers
- **Inference Time:** < 500 μs per prediction
- **Well within Arduino Nano 33 constraints** (1MB flash, 256KB RAM)

## Files Generated

### Python Scripts (in `ML_Training/`)

1. **`ML_Training/analyze_rssi_data.py`**
   - Analyzes dataset and computes formula baseline
   - Validates ML feasibility
   - Run: `cd ML_Training && python analyze_rssi_data.py`

2. **`ML_Training/train_rssi_model.py`**
   - Complete automated training pipeline
   - Trains model, exports Keras and TFLite versions
   - Saves normalization parameters
   - Run: `cd ML_Training && python train_rssi_model.py`

3. **`ML_Training/validate_tflite.py`**
   - Validates TFLite model vs Keras
   - Compares ML vs formula performance
   - Generates validation report
   - Run: `cd ML_Training && python validate_tflite.py`

### Arduino Files

4. **`Arduino/nano33_sense_rev2_all_fw/rssi_model.h`**
   - TFLite model as C byte array (4.86 KB)
   - Generated from `rssi_model_float32.tflite`

5. **`Arduino/nano33_sense_rev2_all_fw/model_config.h`**
   - Feature normalization parameters (mean/scale)
   - Model configuration constants

6. **`Arduino/nano33_sense_rev2_all_fw/nano33_sense_rev2_all_fw.ino`**
   - Updated firmware with TFLite integration
   - ML prediction with formula fallback
   - Easy mode switching via `#define USE_ML_PREDICTION`

## Usage Instructions

### Training the Model

```bash
# 1. Install dependencies (in virtual environment)
.venv/Scripts/pip install pandas numpy scikit-learn tensorflow

# 2. Navigate to ML_Training folder
cd ML_Training

# 3. Analyze dataset (verify ML feasibility)
python analyze_rssi_data.py

# 4. Train model
python train_rssi_model.py

# 5. Validate TFLite model
python validate_tflite.py

# 6. Return to project root
cd ..
```

### Deploying to Arduino

#### Option 1: Use Formula (Recommended)

**No changes needed** - set `#define USE_ML_PREDICTION false` in the .ino file:

```cpp
// Line ~23 in nano33_sense_rev2_all_fw.ino
#define USE_ML_PREDICTION false
```

#### Option 2: Use ML Prediction

**Already configured** - `#define USE_ML_PREDICTION true` is the default:

```cpp
// Line ~23 in nano33_sense_rev2_all_fw.ino
#define USE_ML_PREDICTION true
```

#### Uploading Firmware

1. Open `Arduino/nano33_sense_rev2_all_fw/nano33_sense_rev2_all_fw.ino` in Arduino IDE
2. Install required library:
   - Arduino IDE → Library Manager → Search "Arduino_TensorFlowLite"
   - Install version 2.4.0 or newer
3. Select board: **Arduino Nano 33 BLE (Sense Rev2)**
4. Upload firmware
5. Open Serial Monitor (115200 baud)
6. Expected output:
   ```
   INFO=TFLITE_READY          (if ML enabled)
   WARN=ML_INIT_FAILED,USING_FORMULA  (if ML disabled)
   READY
   ```

### Testing

Stream CSV records via Serial to test RSSI prediction:

```python
# Example: Stream data via MCP or direct serial
import serial

ser = serial.Serial('COM_PORT', 115200)
ser.write(b'STREAM=START\n')

# Send record: DATA=timestamp,lat,lon,elev,pci,cell_id,rsrp,rsrq,rssi,sinr
# rssi=0 triggers prediction (ML or formula based on USE_ML_PREDICTION)
ser.write(b'DATA=1515081832,-81,-7,0,10,47.85,13.21,500\n')

# Expected response:
# {"type":"PROCESSED","rssi":-60,"rssi_is_calculated":true,...}
```

## Performance Comparison

| Metric | Formula | ML Model | Improvement |
|--------|---------|----------|-------------|
| MAE (dBm) | 3.952 | 2.931 | -1.021 (25.8%) |
| RMSE (dBm) | 4.708 | 3.545 | -1.163 (24.7%) |
| R² Score | 0.6766 | 0.8167 | +0.1401 |
| Inference Time | ~1 μs | ~500 μs | N/A |
| Memory Overhead | 0 KB | ~35 KB | N/A |

## Key Observations

### Advantages of ML Approach

1. **Better Accuracy:** 25.8% improvement in MAE
2. **Learns Non-linear Patterns:** Captures complex signal propagation effects
3. **Geographic Context:** Incorporates location and elevation data
4. **R² Score Improvement:** Better explained variance (0.82 vs 0.68)

### Advantages of Formula Approach

1. **Simplicity:** No ML overhead, just arithmetic
2. **Speed:** ~500x faster (1 μs vs 500 μs)
3. **Memory Efficient:** 35 KB less memory usage
4. **Reliability:** No dependency on TFLite library
5. **Good Enough:** 3.95 dBm MAE is acceptable for many use cases

## Recommendations

### For Production Use

**Use the formula-based approach** unless:
- You need the absolute best accuracy (< 3 dBm MAE required)
- You have spare flash/RAM resources
- You're willing to accept the ML overhead

### For Research/Development

**Use the ML approach** to:
- Explore TinyML capabilities
- Benchmark on-device inference
- Learn about model deployment
- Validate the training pipeline

### Future Enhancements

If you want to improve ML performance:

1. **Collect More Data:** Train on a larger, more diverse dataset
2. **Feature Engineering:** Add cell tower distance, signal quality metrics
3. **Model Optimization:** Try quantized int8 models for faster inference
4. **Hyperparameter Tuning:** Adjust architecture, learning rate, epochs
5. **Ensemble Methods:** Combine ML with formula for hybrid prediction

## Troubleshooting

### ML Initialization Fails

**Symptom:** Serial output shows `ERR=TFLITE_VERSION_MISMATCH` or `ERR=TFLITE_ALLOC_FAILED`

**Solution:**
1. Check TensorFlow Lite library version (should be 2.4.0+)
2. Increase `TFLITE_ARENA_SIZE` in `model_config.h` if allocation fails
3. Verify model files (`rssi_model.h`, `model_config.h`) are in firmware directory

### Inference Errors

**Symptom:** Serial output shows `ERR=ML_INFERENCE_FAILED`

**Solution:**
- Model automatically falls back to formula
- Check input feature values are within expected ranges
- Verify normalization parameters match training data

### Memory Issues

**Symptom:** Arduino runs out of memory or crashes

**Solution:**
1. Reduce `TFLITE_ARENA_SIZE` in `model_config.h`
2. Use formula mode (`USE_ML_PREDICTION false`)
3. Disable unused sensors in firmware

## Conclusion

The TinyML RSSI inference implementation is **fully functional** and demonstrates that on-device ML is feasible on the Arduino Nano 33 Sense Rev2. However, the **formula-based approach is recommended** for production use due to its simplicity and acceptable accuracy (MAE: 3.95 dBm).

The ML infrastructure remains available for:
- Future model improvements with better datasets
- Educational purposes (learning TinyML deployment)
- Research into signal propagation modeling
- Benchmarking on-device inference capabilities

**Implementation Status:** ✅ COMPLETE
**Recommendation:** Use formula (as per validation decision)
**ML Option:** Available and functional for experimentation
