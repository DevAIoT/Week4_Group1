#!/usr/bin/env python3
"""
Validate TFLite model against Keras model and compare with formula baseline.
Generates validation report to determine if ML deployment is justified.
"""

import numpy as np
import json
import os
from typing import Dict

try:
    import tensorflow as tf
except ImportError:
    print("ERROR: TensorFlow not installed. Install with: pip install tensorflow")
    exit(1)

def calculate_rssi_formula(rsrp: float, rsrq: float) -> float:
    """Calculate RSSI using the formula: RSSI = RSRP - RSRQ + 14"""
    return rsrp - rsrq + 14

def load_test_data() -> Dict:
    """Load test data from training pipeline."""
    if not os.path.exists('test_data.npz'):
        raise FileNotFoundError("test_data.npz not found. Run train_rssi_model.py first.")

    data = np.load('test_data.npz')
    return {
        'X_test': data['X_test'],
        'y_test': data['y_test'],
        'X_test_scaled': data['X_test_scaled'],
        'y_test_pred_keras': data['y_test_pred']
    }

def load_tflite_model(model_path: str = 'rssi_model_float32.tflite'):
    """Load and initialize TFLite model."""
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"TFLite model not found: {model_path}")

    interpreter = tf.lite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    return interpreter, input_details, output_details

def run_tflite_inference(
    interpreter,
    input_details,
    output_details,
    X: np.ndarray
) -> np.ndarray:
    """Run inference on TFLite model."""
    predictions = []

    for i in range(len(X)):
        # Set input tensor
        input_data = X[i:i+1].astype(np.float32)
        interpreter.set_tensor(input_details[0]['index'], input_data)

        # Run inference
        interpreter.invoke()

        # Get output
        output_data = interpreter.get_tensor(output_details[0]['index'])
        predictions.append(output_data[0, 0])

    return np.array(predictions)

def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, name: str = "Model") -> Dict:
    """Compute evaluation metrics."""
    errors = y_pred - y_true
    mae = np.abs(errors).mean()
    rmse = np.sqrt((errors ** 2).mean())
    mean_error = errors.mean()
    std_error = errors.std()

    # R² score
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    r2 = 1 - (ss_res / ss_tot)

    return {
        'name': name,
        'mae': float(mae),
        'rmse': float(rmse),
        'mean_error': float(mean_error),
        'std_error': float(std_error),
        'r2': float(r2)
    }

def compare_keras_tflite(y_keras: np.ndarray, y_tflite: np.ndarray) -> Dict:
    """Compare Keras vs TFLite predictions."""
    diff = np.abs(y_keras - y_tflite)
    max_diff = diff.max()
    mean_diff = diff.mean()
    percent_diff = (mean_diff / np.abs(y_keras).mean()) * 100

    return {
        'max_diff': float(max_diff),
        'mean_diff': float(mean_diff),
        'percent_diff': float(percent_diff)
    }

def generate_validation_report(
    test_data: Dict,
    tflite_predictions: np.ndarray,
    formula_predictions: np.ndarray
) -> Dict:
    """Generate comprehensive validation report."""

    y_test = test_data['y_test']
    y_keras = test_data['y_test_pred_keras']

    # Compute metrics for each method
    ml_metrics = compute_metrics(y_test, tflite_predictions, "TFLite ML")
    formula_metrics = compute_metrics(y_test, formula_predictions, "Formula")

    # Compare Keras vs TFLite
    keras_tflite_comparison = compare_keras_tflite(y_keras, tflite_predictions)

    # Decision criteria
    ml_improvement = formula_metrics['mae'] - ml_metrics['mae']
    proceed_to_arduino = (
        ml_metrics['mae'] < 5.0 and  # ML MAE < 5 dBm
        ml_improvement >= 2.0 and     # ML improves by ≥ 2 dBm
        keras_tflite_comparison['percent_diff'] < 1.0  # TFLite degradation < 1%
    )

    return {
        'ml_metrics': ml_metrics,
        'formula_metrics': formula_metrics,
        'keras_tflite_comparison': keras_tflite_comparison,
        'ml_improvement_dBm': float(ml_improvement),
        'proceed_to_arduino': bool(proceed_to_arduino)
    }

def print_validation_report(report: Dict):
    """Print validation report to console."""

    print(f"\n{'='*70}")
    print(f"TFLite Model Validation Report")
    print(f"{'='*70}\n")

    # Keras vs TFLite comparison
    print(f"1. Keras vs TFLite Prediction Comparison:")
    print(f"   {'-'*66}")
    comp = report['keras_tflite_comparison']
    print(f"   Maximum difference:  {comp['max_diff']:.6f} dBm")
    print(f"   Mean difference:     {comp['mean_diff']:.6f} dBm")
    print(f"   Percent difference:  {comp['percent_diff']:.4f}%")

    if comp['percent_diff'] < 1.0:
        print(f"   [+] PASS: TFLite degradation < 1%")
    else:
        print(f"   [-] FAIL: TFLite degradation >= 1%")

    # ML metrics
    print(f"\n2. TFLite ML Model Performance:")
    print(f"   {'-'*66}")
    ml = report['ml_metrics']
    print(f"   Mean Absolute Error (MAE):    {ml['mae']:.3f} dBm")
    print(f"   Root Mean Squared Error (RMSE): {ml['rmse']:.3f} dBm")
    print(f"   Mean Error (bias):            {ml['mean_error']:.3f} dBm")
    print(f"   Standard Deviation:           {ml['std_error']:.3f} dBm")
    print(f"   R² Score:                     {ml['r2']:.4f}")

    if ml['mae'] < 5.0:
        print(f"   [+] PASS: MAE < 5.0 dBm threshold")
    else:
        print(f"   [-] FAIL: MAE >= 5.0 dBm threshold")

    # Formula metrics
    print(f"\n3. Formula Baseline Performance (RSSI = RSRP - RSRQ + 14):")
    print(f"   {'-'*66}")
    formula = report['formula_metrics']
    print(f"   Mean Absolute Error (MAE):    {formula['mae']:.3f} dBm")
    print(f"   Root Mean Squared Error (RMSE): {formula['rmse']:.3f} dBm")
    print(f"   Mean Error (bias):            {formula['mean_error']:.3f} dBm")
    print(f"   Standard Deviation:           {formula['std_error']:.3f} dBm")
    print(f"   R² Score:                     {formula['r2']:.4f}")

    # Comparison
    print(f"\n4. ML vs Formula Comparison:")
    print(f"   {'-'*66}")
    improvement = report['ml_improvement_dBm']
    print(f"   ML MAE:         {ml['mae']:.3f} dBm")
    print(f"   Formula MAE:    {formula['mae']:.3f} dBm")
    print(f"   Improvement:    {improvement:.3f} dBm")

    if improvement >= 2.0:
        print(f"   [+] PASS: ML improves by >= 2.0 dBm")
    else:
        print(f"   [-] FAIL: ML improvement < 2.0 dBm")

    # Final decision
    print(f"\n{'='*70}")
    print(f"Final Decision:")
    print(f"{'='*70}")

    if report['proceed_to_arduino']:
        print(f"[+] PROCEED TO ARDUINO DEPLOYMENT")
        print(f"\n  Criteria met:")
        print(f"  * ML MAE < 5.0 dBm: {ml['mae']:.3f} dBm [+]")
        print(f"  * ML improvement >= 2.0 dBm: {improvement:.3f} dBm [+]")
        print(f"  * TFLite degradation < 1%: {comp['percent_diff']:.4f}% [+]")
        print(f"\n  Next steps:")
        print(f"  1. Convert TFLite model to Arduino header:")
        print(f"     xxd -i rssi_model_float32.tflite > rssi_model.h")
        print(f"  2. Create model_config.h with normalization parameters")
        print(f"  3. Integrate into Arduino firmware")
    else:
        print(f"[-] DO NOT DEPLOY TO ARDUINO")
        print(f"\n  Reasons:")
        if ml['mae'] >= 5.0:
            print(f"  * ML MAE >= 5.0 dBm: {ml['mae']:.3f} dBm [-]")
        if improvement < 2.0:
            print(f"  * ML improvement < 2.0 dBm: {improvement:.3f} dBm [-]")
        if comp['percent_diff'] >= 1.0:
            print(f"  * TFLite degradation >= 1%: {comp['percent_diff']:.4f}% [-]")
        print(f"\n  Recommendation: Continue using formula-based approach")

    print(f"{'='*70}\n")

def main():
    """Main validation pipeline."""

    print(f"\n{'='*70}")
    print(f"TFLite Model Validation Pipeline")
    print(f"{'='*70}\n")

    # Load test data
    print(f"Loading test data...")
    test_data = load_test_data()
    X_test = test_data['X_test']
    y_test = test_data['y_test']
    X_test_scaled = test_data['X_test_scaled']

    print(f"  Test samples: {len(y_test):,}")
    print(f"  Features: {X_test.shape[1]}")
    print(f"  Target range: [{y_test.min():.1f}, {y_test.max():.1f}] dBm")

    # Load TFLite model
    print(f"\nLoading TFLite model...")
    interpreter, input_details, output_details = load_tflite_model()

    print(f"  Model loaded successfully")
    print(f"  Input shape: {input_details[0]['shape']}")
    print(f"  Output shape: {output_details[0]['shape']}")

    # Run TFLite inference
    print(f"\nRunning TFLite inference on {len(X_test):,} samples...")
    tflite_predictions = run_tflite_inference(
        interpreter,
        input_details,
        output_details,
        X_test_scaled
    )
    print(f"  [+] Inference complete")

    # Run formula predictions
    print(f"\nRunning formula predictions...")
    formula_predictions = np.array([
        calculate_rssi_formula(X_test[i, 0], X_test[i, 1])
        for i in range(len(X_test))
    ])
    print(f"  [+] Formula predictions complete")

    # Generate validation report
    print(f"\nGenerating validation report...")
    report = generate_validation_report(test_data, tflite_predictions, formula_predictions)

    # Save report
    with open('validation_report.json', 'w') as f:
        json.dump({
            'ml_metrics': report['ml_metrics'],
            'formula_metrics': report['formula_metrics'],
            'keras_tflite_comparison': report['keras_tflite_comparison'],
            'ml_improvement_dBm': report['ml_improvement_dBm'],
            'proceed_to_arduino': report['proceed_to_arduino']
        }, f, indent=2)
    print(f"  [+] Report saved to: validation_report.json")

    # Print report
    print_validation_report(report)

    # Exit with appropriate code
    exit_code = 0 if report['proceed_to_arduino'] else 1
    return exit_code

if __name__ == '__main__':
    import sys
    exit_code = main()
    sys.exit(exit_code)
