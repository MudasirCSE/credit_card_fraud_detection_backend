# import os
# from flask import Flask
# from flask_cors import CORS
# from dotenv import load_dotenv

# # Load environment variables first
# load_dotenv(override=True)

# from database.database import test_database
# from routes.auth import auth_bp
# from routes.prediction import prediction_bp
# from routes.transaction import transactions_bp

# app = Flask(__name__)

# CORS(
#     app,
#     resources={r"/*": {"origins": "*"}},
#     supports_credentials=False,
#     allow_headers=["Content-Type", "Authorization"],
# )

# # Register routes
# app.register_blueprint(prediction_bp)
# app.register_blueprint(auth_bp)
# app.register_blueprint(transactions_bp)


# @app.route("/")
# def home():
#     return {
#         "success": True,
#         "message": "Fraud Detection Backend is Running"
#     }


# if __name__ == "__main__":

#     print("=" * 50, flush=True)
#     print("AI FRAUD DETECTION SYSTEM", flush=True)
#     print("=" * 50, flush=True)

#     # Check MongoDB before starting Flask
#     if not test_database():
#         print("[ERROR] Backend stopped: MongoDB connection failed.", flush=True)
#         raise SystemExit(1)

#     debug_mode = (
#         os.getenv("FLASK_DEBUG", "False").strip().lower() == "true"
#     )

#     print("[OK] Starting Flask Server...", flush=True)

#     app.run(
#         host="0.0.0.0",
#         port=5000,
#         debug=debug_mode,
#         use_reloader=False
#     )











import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

from database.database import test_database
from routes.auth import auth_bp
from routes.prediction import prediction_bp
from routes.transaction import transactions_bp

app = Flask(__name__)

# CORS configuration
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=False,
    allow_headers=["Content-Type", "Authorization"],
)

# Register routes
app.register_blueprint(prediction_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(transactions_bp)


@app.route("/")
def home():
    return {
        "success": True,
        "message": "Fraud Detection Backend is Running"
    }


# MongoDB connection check
print("[INFO] Checking MongoDB connection...", flush=True)

if not test_database():
    raise RuntimeError("MongoDB connection failed!")

print("[OK] Backend initialized successfully!", flush=True)


# Local development
if __name__ == "__main__":

    debug_mode = (
        os.getenv("FLASK_DEBUG", "False").strip().lower() == "true"
    )

    print("[OK] Starting Flask Server...", flush=True)

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=debug_mode,
        use_reloader=False
    )
