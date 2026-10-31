import xgboost as xgb
import joblib
import os

print("Loading old model from JSON...")
# 1. Sahi path: model/artifacts/hybrid_model.json
model = xgb.XGBClassifier()
model.load_model("model/artifacts/hybrid_model.json")

print("Saving model as .pkl with new version...")
# 2. Usi ko artifacts folder mein .pkl ke roop mein save karein
joblib.dump(model, "model/artifacts/hybrid_model.pkl")

print("✅ Model successfully converted to hybrid_model.pkl!")