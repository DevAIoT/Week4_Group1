#!/usr/bin/env python3
"""
Complete automated training pipeline for RSSI prediction using TensorFlow.
Trains a neural network model and exports to TFLite format for Arduino deployment.
"""

import pandas as pd
import numpy as np
import json
import os
from typing import Tuple, Dict
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers, callbacks
except ImportError:
    print("ERROR: TensorFlow not installed. Install with: pip install tensorflow")
    exit(1)

def load_and_prepare_data(csv_path: str = 'Crawdad.csv') -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """
    Load dataset and prepare features and target.

    Returns:
        Tuple of (dataframe, feature_array, target_array)
    """
    print(f"Loading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)

    print(f"Total records: {len(df):,}")

    # Filter to records with measured RSSI
    df_measured = df[df['RSSI'].notna()].copy()
    print(f"Records with measured RSSI: {len(df_measured):,}")

    if len(df_measured) < 100:
        raise ValueError(f"Insufficient training data: only {len(df_measured)} samples with measured RSSI")

    # Define features
    feature_cols = ['RSRP', 'RSRQ', 'SINR', 'Latitude', 'Longitude', 'Elevation']

    # Check for missing values in features
    print(f"\nFeature availability:")
    for col in feature_cols:
        non_null = df_measured[col].notna().sum()
        percentage = (non_null / len(df_measured)) * 100
        print(f"  {col:12s}: {non_null:7,} / {len(df_measured):7,} ({percentage:5.1f}%)")

    # Drop rows with missing feature values
    df_clean = df_measured[feature_cols + ['RSSI']].dropna()
    print(f"\nRecords after removing missing values: {len(df_clean):,}")

    if len(df_clean) < 100:
        raise ValueError(f"Insufficient clean training data: only {len(df_clean)} samples")

    # Extract features and target
    X = df_clean[feature_cols].values
    y = df_clean['RSSI'].values

    print(f"\nFeature matrix shape: {X.shape}")
    print(f"Target vector shape: {y.shape}")
    print(f"Target range: [{y.min():.1f}, {y.max():.1f}] dBm")

    return df_clean, X, y

def create_model(input_dim: int = 6) -> keras.Model:
    """
    Create neural network model architecture.

    Architecture: Input(6) → Dense(32, ReLU) → Dense(16, ReLU) → Dense(1)

    Args:
        input_dim: Number of input features (default: 6)

    Returns:
        Compiled Keras model
    """
    model = keras.Sequential([
        layers.Input(shape=(input_dim,)),
        layers.Dense(32, activation='relu', name='hidden1'),
        layers.Dense(16, activation='relu', name='hidden2'),
        layers.Dense(1, name='output')
    ])

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss='mse',
        metrics=['mae']
    )

    return model

def train_model(
    X: np.ndarray,
    y: np.ndarray,
    epochs: int = 100,
    batch_size: int = 32,
    validation_split: float = 0.1
) -> Tuple[keras.Model, StandardScaler, Dict]:
    """
    Train the model with normalization and early stopping.

    Args:
        X: Feature matrix
        y: Target vector
        epochs: Maximum number of training epochs
        batch_size: Batch size for training
        validation_split: Fraction of training data for validation

    Returns:
        Tuple of (trained_model, scaler, training_history)
    """
    print(f"\n{'='*60}")
    print(f"Training Configuration:")
    print(f"{'='*60}")
    print(f"Epochs: {epochs}")
    print(f"Batch size: {batch_size}")
    print(f"Validation split: {validation_split:.1%}")

    # Split into train, validation, test (80/10/10)
    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=0.1, random_state=42
    )

    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=validation_split/(1-0.1), random_state=42
    )

    print(f"\nData split:")
    print(f"  Training:   {len(X_train):,} samples ({len(X_train)/len(X)*100:.1f}%)")
    print(f"  Validation: {len(X_val):,} samples ({len(X_val)/len(X)*100:.1f}%)")
    print(f"  Test:       {len(X_test):,} samples ({len(X_test)/len(X)*100:.1f}%)")

    # Normalize features
    print(f"\nNormalizing features with StandardScaler...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    # Save scaler parameters
    scaler_params = {
        'mean': scaler.mean_.tolist(),
        'scale': scaler.scale_.tolist(),
        'feature_names': ['RSRP', 'RSRQ', 'SINR', 'Latitude', 'Longitude', 'Elevation']
    }

    print(f"Scaler parameters:")
    for i, name in enumerate(scaler_params['feature_names']):
        print(f"  {name:12s}: mean={scaler_params['mean'][i]:8.3f}, scale={scaler_params['scale'][i]:8.3f}")

    # Create model
    print(f"\n{'='*60}")
    print(f"Model Architecture:")
    print(f"{'='*60}")
    model = create_model(input_dim=X_train.shape[1])
    model.summary()

    # Setup callbacks
    early_stop = callbacks.EarlyStopping(
        monitor='val_loss',
        patience=10,
        restore_best_weights=True,
        verbose=1
    )

    checkpoint = callbacks.ModelCheckpoint(
        'rssi_model_best.keras',
        monitor='val_loss',
        save_best_only=True,
        verbose=0
    )

    # Train model
    print(f"\n{'='*60}")
    print(f"Training Model:")
    print(f"{'='*60}")

    history = model.fit(
        X_train_scaled, y_train,
        validation_data=(X_val_scaled, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[early_stop, checkpoint],
        verbose=1
    )

    # Evaluate on test set
    print(f"\n{'='*60}")
    print(f"Model Evaluation on Test Set:")
    print(f"{'='*60}")

    y_test_pred = model.predict(X_test_scaled, verbose=0).flatten()

    test_mae = mean_absolute_error(y_test, y_test_pred)
    test_rmse = np.sqrt(mean_squared_error(y_test, y_test_pred))
    test_r2 = r2_score(y_test, y_test_pred)

    print(f"Mean Absolute Error (MAE):  {test_mae:.3f} dBm")
    print(f"Root Mean Squared Error (RMSE): {test_rmse:.3f} dBm")
    print(f"R² Score: {test_r2:.4f}")

    # Store test data for validation script
    training_results = {
        'test_mae': float(test_mae),
        'test_rmse': float(test_rmse),
        'test_r2': float(test_r2),
        'epochs_trained': len(history.history['loss']),
        'final_train_loss': float(history.history['loss'][-1]),
        'final_val_loss': float(history.history['val_loss'][-1])
    }

    # Save test data for validation
    np.savez('test_data.npz',
             X_test=X_test,
             y_test=y_test,
             X_test_scaled=X_test_scaled,
             y_test_pred=y_test_pred)

    return model, scaler, scaler_params, training_results

def convert_to_tflite(model: keras.Model, output_path: str = 'rssi_model_float32.tflite'):
    """
    Convert Keras model to TensorFlow Lite format (float32).

    Args:
        model: Trained Keras model
        output_path: Output path for TFLite model
    """
    print(f"\n{'='*60}")
    print(f"Converting to TensorFlow Lite:")
    print(f"{'='*60}")

    # Convert to TFLite with float32
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = []  # No quantization, keep float32
    tflite_model = converter.convert()

    # Save TFLite model
    with open(output_path, 'wb') as f:
        f.write(tflite_model)

    model_size_kb = len(tflite_model) / 1024
    print(f"[+] TFLite model saved to: {output_path}")
    print(f"  Model size: {model_size_kb:.2f} KB")

    return output_path

def main():
    """Main training pipeline."""
    print(f"\n{'='*60}")
    print(f"RSSI Prediction Model Training Pipeline")
    print(f"{'='*60}\n")

    # Load and prepare data
    df, X, y = load_and_prepare_data('Crawdad.csv')

    # Train model
    model, scaler, scaler_params, training_results = train_model(X, y)

    # Save Keras model
    model.save('rssi_model.keras')
    print(f"\n[+] Keras model saved to: rssi_model.keras")

    # Save scaler parameters
    with open('scaler_params.json', 'w') as f:
        json.dump(scaler_params, f, indent=2)
    print(f"[+] Scaler parameters saved to: scaler_params.json")

    # Save training results
    with open('training_results.json', 'w') as f:
        json.dump(training_results, f, indent=2)
    print(f"[+] Training results saved to: training_results.json")

    # Convert to TFLite
    tflite_path = convert_to_tflite(model)

    print(f"\n{'='*60}")
    print(f"Training Complete!")
    print(f"{'='*60}")
    print(f"Generated files:")
    print(f"  1. rssi_model.keras - Keras model")
    print(f"  2. {tflite_path} - TFLite model (float32)")
    print(f"  3. scaler_params.json - Feature normalization parameters")
    print(f"  4. training_results.json - Training metrics")
    print(f"  5. test_data.npz - Test dataset for validation")
    print(f"\nNext steps:")
    print(f"  1. Run: python validate_tflite.py")
    print(f"  2. If validation passes, convert to Arduino headers")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
