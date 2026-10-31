import os
import hashlib
import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from tensorflow.keras.models import load_model

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

ARTIFACT_DIR = os.path.join(
    BASE_DIR,
    "model",
    "artifacts"
)

# ------------------------------------------------------------
# LOAD ARTIFACTS
# ------------------------------------------------------------
scaler = joblib.load(
    os.path.join(ARTIFACT_DIR, "scaler.pkl")
)

isolation_forest = joblib.load(
    os.path.join(ARTIFACT_DIR, "isolation_forest.pkl")
)

one_class_svm = joblib.load(
    os.path.join(ARTIFACT_DIR, "one_class_svm.pkl")
)

nystroem = joblib.load(
    os.path.join(ARTIFACT_DIR, "nystroem.pkl")
)

model_config = joblib.load(
    os.path.join(ARTIFACT_DIR, "model_config.pkl")
)

autoencoder = load_model(
    os.path.join(ARTIFACT_DIR, "autoencoder.keras")
)

# hybrid_model = xgb.XGBClassifier()
# hybrid_model.load_model(
#     os.path.join(ARTIFACT_DIR, "hybrid_model.json")
# )

hybrid_model = joblib.load(os.path.join(ARTIFACT_DIR, "hybrid_model.pkl"))

FEATURE_COLUMNS = model_config["feature_columns"]
THRESHOLD = float(model_config["threshold"])

ISO_SCORE_TRAIN = np.asarray(model_config["iso_score_train"], dtype=float)
SVM_SCORE_TRAIN = np.asarray(model_config["svm_score_train"], dtype=float)
AE_SCORE_TRAIN = np.asarray(model_config["ae_score_train"], dtype=float)

# Precomputed 95th percentile from the training dataset (replaces 150MB disk read)
AMOUNT_95TH_PERCENTILE = 22836.6255


def minmax_score(value, training_values):
    """Normalize score to [0, 1] using training reference distribution."""
    training_values = np.asarray(training_values, dtype=float)
    min_value = np.min(training_values)
    max_value = np.max(training_values)

    if max_value == min_value:
        return 0.0

    score = (float(value) - min_value) / (max_value - min_value + 1e-8)
    return float(np.clip(score, 0.0, 1.0))


def reconstruction_error(model, data):
    """Calculate mean squared error between input and autoencoder reconstruction."""
    reconstructed = model.predict(data, verbose=0)
    error = np.mean(
        np.square(data.values - reconstructed),
        axis=1
    )
    return error


def map_payment_to_features(
    amount,
    merchant="",
    transaction_time=None,
    behavior_signals=None
):
    """
    Deterministically project digital payment inputs into the trained model's
    normalized PCA latent feature space (V1..V28).
    
    Uses empirical dataset statistics:
    - Normal (Legitimate) baseline: V14 ~ +1.33, V12 ~ +0.23, V17 ~ +0.60, V4 ~ -0.62, V11 ~ -0.31
    - Fraud profile: V14 ~ -1.5 to -3.0, V12 ~ -1.5 to -3.0, V4 ~ +1.5 to +3.0, V11 ~ +1.5 to +3.0
    """
    amount = float(amount)
    merchant = str(merchant or "").strip()
    behavior_signals = behavior_signals or {}

    raw_features = {
        "id": 0.0,
        "Amount": amount
    }

    # Merchant category risk signature from deterministic hash
    mch_hash = int(hashlib.md5(merchant.lower().encode("utf-8")).hexdigest()[:6], 16)
    mch_factor = ((mch_hash % 1000) / 500.0) - 1.0  # Range: [-1.0, 1.0]

    # Temporal context
    hour = transaction_time.hour if transaction_time else 12
    night_factor = 1.0 if (hour >= 23 or hour <= 5) else 0.0

    # Behavioral risk influences on latent features
    amt_score = float(behavior_signals.get("amount_score", 0.0)) / 100.0
    vel_score = float(behavior_signals.get("frequency_score", 0.0)) / 100.0
    loc_score = float(behavior_signals.get("location_score", 0.0)) / 100.0
    time_score = float(behavior_signals.get("time_score", 0.0)) / 100.0

    risk_magnitude = (
        amt_score * 0.40
        + vel_score * 0.25
        + loc_score * 0.20
        + time_score * 0.15
    )

    # Shift top predictive features from normal baseline towards anomalous zone proportionally
    # Legitimate baseline -> Fraud direction
    v14_val = 1.33 - (risk_magnitude * 2.8) - (night_factor * 0.4)
    v12_val = 0.23 - (risk_magnitude * 1.8) - (loc_score * 0.8)
    v17_val = 0.60 - (risk_magnitude * 1.4) - (vel_score * 0.6)
    v4_val = -0.62 + (risk_magnitude * 2.2) + (vel_score * 0.8)
    v11_val = -0.31 + (risk_magnitude * 2.0) + (loc_score * 0.6)
    v10_val = 0.50 - (risk_magnitude * 1.6)
    v3_val = 0.40 - (risk_magnitude * 1.4)
    v7_val = 0.35 - (risk_magnitude * 1.2)

    raw_features["V14"] = float(np.clip(v14_val, -15.0, 5.0))
    raw_features["V12"] = float(np.clip(v12_val, -12.0, 4.0))
    raw_features["V17"] = float(np.clip(v17_val, -15.0, 5.0))
    raw_features["V4"] = float(np.clip(v4_val, -5.0, 12.0))
    raw_features["V11"] = float(np.clip(v11_val, -4.0, 10.0))
    raw_features["V10"] = float(np.clip(v10_val, -10.0, 5.0))
    raw_features["V3"] = float(np.clip(v3_val, -8.0, 5.0))
    raw_features["V7"] = float(np.clip(v7_val, -8.0, 5.0))

    # Populate remaining PCA vectors with normal-distributed baseline + merchant nuance
    for i in range(1, 29):
        key = f"V{i}"
        if key not in raw_features:
            variation = (mch_factor * 0.05) * np.sin(i * 1.37 + (mch_hash % 100))
            raw_features[key] = float(np.clip(variation, -3.0, 3.0))

    return raw_features


def engineer_features(raw_features):
    """
    Transform raw transaction dictionary into the exact 37-column dataframe
    required by the RobustScaler and Anomaly Detectors.
    """
    row = pd.DataFrame([raw_features])

    if "Amount" not in row.columns:
        raise ValueError("Amount is required")

    amount = float(row["Amount"].iloc[0])
    if amount < 0:
        raise ValueError("Amount cannot be negative")

    # Engineered Amount features matching training pipeline
    row["Amount_log"] = np.log1p(amount)
    row["Amount_sqrt"] = np.sqrt(amount)
    row["High_amount"] = int(amount > AMOUNT_95TH_PERCENTILE)
    row["Zero_amount"] = int(amount == 0)

    # Ensure required V features exist (default to 0.0 if not provided)
    for i in range(1, 29):
        col = f"V{i}"
        if col not in row.columns:
            row[col] = 0.0

    if "id" not in row.columns:
        row["id"] = 0.0

    # Interaction terms
    row["Amount_x_V14"] = row["Amount_log"] * row["V14"].abs()
    row["V14_x_V12"] = row["V14"] * row["V12"]
    row["V14_x_V17"] = row["V14"] * row["V17"]
    row["V4_x_V11"] = row["V4"] * row["V11"]

    # Drop original Time and Amount columns if present
    for column in ["Time", "Amount"]:
        if column in row.columns:
            row = row.drop(columns=[column])

    # Enforce column ordering
    row = row[FEATURE_COLUMNS]
    return row


def predict_transaction(raw_features):
    """
    Execute full Hybrid AI Fraud Detection pipeline:
    1. Feature Engineering
    2. RobustScaler transformation
    3. Isolation Forest Anomaly Scoring
    4. SGDOneClassSVM Anomaly Scoring (via Nystroem)
    5. Deep Autoencoder Reconstruction Error Scoring
    6. Score Fusion Augmentation (45 features)
    7. XGBoost Final Probability & Decision
    """
    try:
        row = engineer_features(raw_features)

        # Scale input
        row_scaled_values = scaler.transform(row)
        row_scaled = pd.DataFrame(row_scaled_values, columns=FEATURE_COLUMNS)

        # 1. Isolation Forest
        raw_iso = float(-isolation_forest.score_samples(row_scaled)[0])
        iso_score = minmax_score(raw_iso, ISO_SCORE_TRAIN)

        # 2. One-Class SVM
        svm_input = nystroem.transform(row_scaled)
        raw_svm = float(-one_class_svm.score_samples(svm_input)[0])
        svm_score = minmax_score(raw_svm, SVM_SCORE_TRAIN)

        # 3. Deep Autoencoder
        raw_ae = float(reconstruction_error(autoencoder, row_scaled)[0])
        ae_score = minmax_score(raw_ae, AE_SCORE_TRAIN)

        # 4. Score Fusion (8 derived anomaly features)
        score_values = np.array([iso_score, svm_score, ae_score], dtype=float)
        score_avg = float(np.mean(score_values))
        score_max = float(np.max(score_values))
        iso_x_ae = float(iso_score * ae_score)
        iso_x_svm = float(iso_score * svm_score)
        svm_x_ae = float(svm_score * ae_score)

        # Construct 45-feature augmented matrix
        augmented = np.concatenate([
            row_scaled.values[0],
            np.array([
                iso_score,
                svm_score,
                ae_score,
                score_avg,
                score_max,
                iso_x_ae,
                iso_x_svm,
                svm_x_ae
            ], dtype=float)
        ]).reshape(1, -1)

        if augmented.shape[1] != 45:
            raise ValueError(f"Hybrid model expected 45 features, but received {augmented.shape[1]}")

        # XGBoost inference
        probability = float(hybrid_model.predict_proba(augmented)[0, 1])
        probability = float(np.clip(probability, 0.0, 1.0))

        is_fraud = probability >= THRESHOLD
        prediction = "FRAUD" if is_fraud else "LEGITIMATE"

        confidence_percent = (
            probability * 100 if is_fraud else (1.0 - probability) * 100
        )
        ai_risk_score = probability * 100

        return {
            "success": True,
            "prediction": prediction,
            "fraud": is_fraud,
            "probability": round(probability, 4),
            "ai_confidence": round(confidence_percent, 2),
            "ai_risk_score": round(ai_risk_score, 2),
            "threshold": round(THRESHOLD, 3),
            "anomaly_scores": {
                "isolation_forest": round(iso_score, 4),
                "one_class_svm": round(svm_score, 4),
                "autoencoder": round(ae_score, 4),
                "composite_anomaly": round(score_avg, 4)
            }
        }

    except Exception as e:
        print(f"\n[AI PREDICTION ERROR] {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }