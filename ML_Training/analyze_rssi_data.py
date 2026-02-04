#!/usr/bin/env python3
"""
Analyze Crawdad.csv dataset to assess feasibility of ML-based RSSI prediction.
Computes baseline formula accuracy and determines if ML approach is justified.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple

def calculate_rssi_formula(rsrp: float, rsrq: float) -> float:
    """
    Calculate RSSI using the formula: RSSI = RSRP - RSRQ + 14
    This assumes N_RB=25 (5MHz channel bandwidth).

    Args:
        rsrp: Reference Signal Received Power (dBm)
        rsrq: Reference Signal Received Quality (dB)

    Returns:
        Calculated RSSI (dBm)
    """
    return rsrp - rsrq + 14

def analyze_rssi_dataset(csv_path: str = 'Crawdad.csv') -> Dict:
    """
    Analyze the dataset to determine ML feasibility.

    Returns:
        Dictionary with analysis results including:
        - total_records: Total number of records
        - measured_rssi_count: Number of records with measured RSSI
        - missing_rssi_count: Number of records without RSSI
        - measured_rssi_percentage: Percentage of measured RSSI values
        - formula_mae: Mean Absolute Error of formula on measured RSSI
        - formula_rmse: Root Mean Squared Error of formula on measured RSSI
        - proceed_with_ml: Boolean indicating if ML is justified
    """
    print(f"Loading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)

    total_records = len(df)
    print(f"Total records: {total_records:,}")

    # Count measured vs missing RSSI
    measured_mask = df['RSSI'].notna()
    measured_rssi_count = measured_mask.sum()
    missing_rssi_count = (~measured_mask).sum()
    measured_percentage = (measured_rssi_count / total_records) * 100

    print(f"\n{'='*60}")
    print(f"RSSI Data Distribution:")
    print(f"{'='*60}")
    print(f"Measured RSSI values:  {measured_rssi_count:,} ({measured_percentage:.2f}%)")
    print(f"Missing RSSI values:   {missing_rssi_count:,} ({100-measured_percentage:.2f}%)")

    # Check if we have enough measured values for ML training
    if measured_rssi_count < 100:
        print(f"\n[!] WARNING: Insufficient measured RSSI values for ML training!")
        print(f"    Need at least 100 samples, found only {measured_rssi_count}")
        return {
            'total_records': total_records,
            'measured_rssi_count': measured_rssi_count,
            'missing_rssi_count': missing_rssi_count,
            'measured_rssi_percentage': measured_percentage,
            'proceed_with_ml': False,
            'reason': 'Insufficient measured RSSI values'
        }

    # Calculate formula accuracy on measured RSSI values
    print(f"\n{'='*60}")
    print(f"Formula Baseline Accuracy (RSSI = RSRP - RSRQ + 14):")
    print(f"{'='*60}")

    df_measured = df[measured_mask].copy()
    df_measured['rssi_formula'] = calculate_rssi_formula(
        df_measured['RSRP'].values,
        df_measured['RSRQ'].values
    )

    # Compute errors
    errors = df_measured['rssi_formula'] - df_measured['RSSI']
    mae = np.abs(errors).mean()
    rmse = np.sqrt((errors ** 2).mean())
    mean_error = errors.mean()
    std_error = errors.std()

    print(f"Mean Absolute Error (MAE):    {mae:.3f} dBm")
    print(f"Root Mean Squared Error (RMSE): {rmse:.3f} dBm")
    print(f"Mean Error (bias):            {mean_error:.3f} dBm")
    print(f"Standard Deviation:           {std_error:.3f} dBm")

    # Show example predictions
    print(f"\n{'='*60}")
    print(f"Sample Predictions (first 10 measured RSSI values):")
    print(f"{'='*60}")
    print(f"{'RSRP':>6} {'RSRQ':>6} {'Measured':>10} {'Formula':>10} {'Error':>8}")
    print(f"{'-'*60}")

    sample_df = df_measured.head(10)
    for _, row in sample_df.iterrows():
        error = row['rssi_formula'] - row['RSSI']
        print(f"{row['RSRP']:6.1f} {row['RSRQ']:6.1f} {row['RSSI']:10.1f} {row['rssi_formula']:10.1f} {error:8.1f}")

    # Decision criteria
    print(f"\n{'='*60}")
    print(f"ML Feasibility Decision:")
    print(f"{'='*60}")

    proceed_with_ml = mae > 3.0  # Proceed if formula MAE > 3 dBm

    if proceed_with_ml:
        print(f"[+] PROCEED with ML training")
        print(f"  Reason: Formula MAE ({mae:.3f} dBm) > 3.0 dBm threshold")
        print(f"  Sufficient measured RSSI samples: {measured_rssi_count:,}")
        print(f"  ML has potential to improve accuracy")
    else:
        print(f"[-] DO NOT PROCEED with ML training")
        print(f"  Reason: Formula MAE ({mae:.3f} dBm) <= 3.0 dBm threshold")
        print(f"  Formula already provides good accuracy")
        print(f"  ML overhead not justified")

    # Feature availability check
    print(f"\n{'='*60}")
    print(f"Feature Availability for ML Training:")
    print(f"{'='*60}")

    features = ['RSRP', 'RSRQ', 'SINR', 'Latitude', 'Longitude', 'Elevation']
    for feature in features:
        if feature in df_measured.columns:
            non_null = df_measured[feature].notna().sum()
            percentage = (non_null / len(df_measured)) * 100
            print(f"{feature:12s}: {non_null:7,} / {len(df_measured):7,} ({percentage:5.1f}%)")
        else:
            print(f"{feature:12s}: NOT FOUND")

    return {
        'total_records': total_records,
        'measured_rssi_count': measured_rssi_count,
        'missing_rssi_count': missing_rssi_count,
        'measured_rssi_percentage': measured_percentage,
        'formula_mae': mae,
        'formula_rmse': rmse,
        'formula_mean_error': mean_error,
        'formula_std_error': std_error,
        'proceed_with_ml': proceed_with_ml,
        'reason': 'Formula MAE > 3.0 dBm' if proceed_with_ml else 'Formula MAE ≤ 3.0 dBm'
    }

if __name__ == '__main__':
    import sys

    csv_path = 'Crawdad.csv'
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    results = analyze_rssi_dataset(csv_path)

    print(f"\n{'='*60}")
    print(f"Analysis Summary:")
    print(f"{'='*60}")
    print(f"Dataset: {csv_path}")
    print(f"Total records: {results['total_records']:,}")
    print(f"Measured RSSI: {results['measured_rssi_count']:,} ({results['measured_rssi_percentage']:.2f}%)")

    if 'formula_mae' in results:
        print(f"Formula MAE: {results['formula_mae']:.3f} dBm")
        print(f"Formula RMSE: {results['formula_rmse']:.3f} dBm")

    print(f"\nRecommendation: {'PROCEED with ML training' if results['proceed_with_ml'] else 'USE formula-based approach'}")
    print(f"Reason: {results['reason']}")
    print(f"{'='*60}")

    # Exit with appropriate code
    sys.exit(0 if results['proceed_with_ml'] else 1)
