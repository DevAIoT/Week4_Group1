# ML Training and Evaluation Files

This folder contains all the scripts and generated files for training and evaluating the TinyML RSSI prediction model.

## Scripts (Run in order)

### 1. `analyze_rssi_data.py`
Analyzes the Crawdad.csv dataset to determine if ML training is justified.

**Usage:**
```bash
python analyze_rssi_data.py
```

**Outputs:**
- Console report showing:
  - Number of measured RSSI values
  - Formula baseline accuracy (MAE, RMSE)
  - Feature availability
  - Recommendation (proceed with ML or use formula)

**Exit code:**
- 0 = Proceed with ML training (formula MAE > 3.0 dBm)
- 1 = Use formula (formula MAE ≤ 3.0 dBm)

---

### 2. `train_rssi_model.py`
Complete automated training pipeline for the RSSI prediction model.

**Usage:**
```bash
python train_rssi_model.py
```

**Requirements:**
- Python 3.8+
- tensorflow
- pandas
- numpy
- scikit-learn

**Outputs:**
- `rssi_model.keras` - Full Keras model
- `rssi_model_best.keras` - Best checkpoint during training
- `rssi_model_float32.tflite` - TFLite model for Arduino deployment
- `scaler_params.json` - Feature normalization parameters
- `training_results.json` - Training metrics (MAE, RMSE, R²)
- `test_data.npz` - Test dataset for validation

**Model Architecture:**
```
Input(6) → Dense(32, ReLU) → Dense(16, ReLU) → Dense(1)
Total parameters: 769 (3.00 KB)
```

**Features used:**
1. RSRP (Reference Signal Received Power, dBm)
2. RSRQ (Reference Signal Received Quality, dB)
3. SINR (Signal-to-Interference-plus-Noise Ratio, dB)
4. Latitude (GPS coordinates, degrees)
5. Longitude (GPS coordinates, degrees)
6. Elevation (Altitude, meters)

---

### 3. `validate_tflite.py`
Validates the TFLite model and compares ML performance vs formula baseline.

**Usage:**
```bash
python validate_tflite.py
```

**Outputs:**
- `validation_report.json` - Validation metrics and decision
- Console report showing:
  - Keras vs TFLite comparison (should be < 1% degradation)
  - ML model performance (MAE, RMSE, R²)
  - Formula baseline performance
  - ML improvement over formula
  - Final deployment recommendation

**Exit code:**
- 0 = Proceed to Arduino deployment (ML MAE < 5 dBm AND improvement ≥ 2 dBm)
- 1 = Use formula-based approach (criteria not met)

---

## Generated Files

### Model Files

- **`rssi_model.keras`** (34 KB)
  - Full Keras model with all training metadata
  - Can be used for further training or fine-tuning
  - Load with: `keras.models.load_model('rssi_model.keras')`

- **`rssi_model_best.keras`** (34 KB)
  - Best model checkpoint during training
  - Saved when validation loss was lowest

- **`rssi_model_float32.tflite`** (4.9 KB)
  - TensorFlow Lite model for Arduino deployment
  - Float32 precision (no quantization)
  - This file is converted to `rssi_model.h` for Arduino

- **`rssi_model_data.h`** (31 KB)
  - Intermediate C header file with model data
  - Generated using `xxd -i rssi_model_float32.tflite`
  - Final version copied to `Arduino/nano33_sense_rev2_all_fw/rssi_model.h`

### Configuration Files

- **`scaler_params.json`** (457 bytes)
  - Feature normalization parameters (mean and scale)
  - Used to generate `model_config.h` for Arduino
  - Format: `normalized = (value - mean) / scale`

- **`training_results.json`** (215 bytes)
  - Training metrics: MAE, RMSE, R²
  - Number of epochs trained
  - Final training and validation loss

- **`validation_report.json`** (688 bytes)
  - ML vs Formula comparison metrics
  - Keras vs TFLite degradation check
  - Deployment decision (proceed or use formula)

### Test Data

- **`test_data.npz`** (1.5 MB)
  - Numpy archive containing:
    - `X_test` - Raw test features
    - `y_test` - True RSSI values
    - `X_test_scaled` - Normalized test features
    - `y_test_pred` - Keras predictions
  - Used by `validate_tflite.py` for comparison

---

## Validation Results (Current)

**ML Model:**
- MAE: 2.931 dBm
- RMSE: 3.545 dBm
- R² Score: 0.8167

**Formula Baseline:**
- MAE: 3.952 dBm
- RMSE: 4.708 dBm
- R² Score: 0.6766

**ML Improvement:** 1.021 dBm (25.8% better)

**Decision:** Use formula (improvement < 2.0 dBm threshold)

---

## Workflow

```
1. analyze_rssi_data.py
   ↓ (if formula MAE > 3 dBm)
2. train_rssi_model.py
   ↓ (generates .tflite model)
3. validate_tflite.py
   ↓ (if ML improvement ≥ 2 dBm)
4. Convert to Arduino headers:
   - xxd -i rssi_model_float32.tflite > rssi_model.h
   - Copy to Arduino/nano33_sense_rev2_all_fw/
5. Deploy to Arduino
```

---

## Re-training the Model

To retrain with different parameters:

1. **Edit `train_rssi_model.py`:**
   ```python
   # Line ~82: Change model architecture
   model = keras.Sequential([
       layers.Dense(64, activation='relu'),  # Increase neurons
       layers.Dense(32, activation='relu'),  # Add more layers
       layers.Dense(1)
   ])

   # Line ~115: Change training parameters
   epochs = 200  # More epochs
   batch_size = 64  # Larger batches
   ```

2. **Run training:**
   ```bash
   python train_rssi_model.py
   ```

3. **Validate:**
   ```bash
   python validate_tflite.py
   ```

---

## Troubleshooting

### Import Error: No module named 'tensorflow'
```bash
pip install tensorflow pandas numpy scikit-learn
```

### Model training is slow
- Use a GPU if available (TensorFlow will auto-detect)
- Reduce batch size
- Reduce number of epochs

### Validation fails (ML improvement < 2 dBm)
This is expected based on current results. Options:
1. **Accept result:** Use formula (recommended)
2. **Improve model:** Collect more data, tune hyperparameters
3. **Lower threshold:** Change validation criteria in plan

---

## Notes

- All scripts are standalone and fully automated
- No manual intervention required during execution
- Dataset `Crawdad.csv` must be in the parent directory
- Scripts use virtual environment `.venv` if available
- Generated files are safe to delete and regenerate
