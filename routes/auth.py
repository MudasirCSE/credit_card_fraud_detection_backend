import random
import re
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from database.database import users_collection
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from utils.auth_utils import generate_token

auth_bp = Blueprint("auth", __name__)

MIN_STARTING_BALANCE = 50000
MAX_STARTING_BALANCE = 200000
HOME_BANK_NAME = "SecureBank"

def _random_starting_balance():
    return float(random.randint(MIN_STARTING_BALANCE // 1000, MAX_STARTING_BALANCE // 1000) * 1000)

def _generate_unique_account_number():
    for _ in range(5):
        candidate = str(random.randint(10**9, 10**10 - 1))
        if not users_collection.find_one({"account_number": candidate}):
            return candidate
    return str(random.randint(10**9, 10**10 - 1)) + str(uuid.uuid4().int)[:2]

def _generate_unique_card_number():
    for _ in range(5):
        length = random.choice([13, 14])
        candidate = "".join(str(random.randint(0, 9)) for _ in range(length))
        if not users_collection.find_one({"card_number": candidate}):
            return candidate
    return "".join(str(random.randint(0, 9)) for _ in range(14))

def _generate_card_expiry():
    future = datetime.utcnow() + timedelta(days=365 * 3)
    return future.strftime("%m/%y")

@auth_bp.route("/auth/signup", methods=["POST"])
def signup():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data received"}), 400
        
        name = str(data.get("name", "")).strip()
        username = str(data.get("username", "")).strip().lower()
        phone = str(data.get("phone", "")).strip()
        password = str(data.get("password", ""))
        mpin = str(data.get("mpin", "")).strip()
        
        if not name: return jsonify({"success": False, "message": "Name is required"}), 400
        if not username: return jsonify({"success": False, "message": "Username is required"}), 400
        if not re.match(r'^[a-zA-Z0-9_.]{3,20}$', username):
            return jsonify({"success": False, "message": "Username must be 3-20 characters"}), 400
        if not phone: return jsonify({"success": False, "message": "Phone number is required"}), 400
        
        digits_only = "".join(filter(str.isdigit, phone))
        if len(digits_only) != 11:
            return jsonify({"success": False, "message": "Phone number must be exactly 11 digits"}), 400
            
        if not password: return jsonify({"success": False, "message": "Password is required"}), 400
        if len(password) != 8: return jsonify({"success": False, "message": "Password must be exactly 8 characters"}), 400
        if not re.search(r'[A-Z]', password): return jsonify({"success": False, "message": "Password must contain uppercase"}), 400
        if not re.search(r'[a-z]', password): return jsonify({"success": False, "message": "Password must contain lowercase"}), 400
        if not re.search(r'\d', password): return jsonify({"success": False, "message": "Password must contain a number"}), 400
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password): return jsonify({"success": False, "message": "Password must contain special char"}), 400

        if not mpin: return jsonify({"success": False, "message": "MPIN is required"}), 400
        if len(mpin) != 4 or not mpin.isdigit(): return jsonify({"success": False, "message": "MPIN must be exactly 4 digits"}), 400

        if users_collection.find_one({"username": username}):
            return jsonify({"success": False, "message": "Username already taken"}), 409

        user_id = str(uuid.uuid4())
        starting_balance = _random_starting_balance()
        account_number = _generate_unique_account_number()
        card_number = _generate_unique_card_number()
        card_expiry = _generate_card_expiry()

        user = {
            "user_id": user_id,
            "name": name,
            "username": username,
            "phone": phone,
            "password": generate_password_hash(password),
            "mpin": generate_password_hash(mpin),
            "balance": starting_balance,
            "account_number": account_number,
            "bank_name": HOME_BANK_NAME,
            "card_number": card_number,
            "card_expiry": card_expiry,
            "created_at": datetime.utcnow()
        }
        users_collection.insert_one(user)

        return jsonify({
            "success": True, "message": "Account created successfully",
            "user": {"id": user_id, "name": name, "username": username, "phone": phone, "balance": starting_balance, "account_number": account_number, "bank_name": HOME_BANK_NAME, "card_number": card_number, "card_expiry": card_expiry}
        }), 201

    except Exception as e:
        print("SIGNUP ERROR:", str(e))
        return jsonify({"success": False, "message": "Something went wrong. Please try again."}), 500

@auth_bp.route("/auth/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        if not data: return jsonify({"success": False, "message": "No JSON data received"}), 400
        
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))
        
        if not username or not password:
            return jsonify({"success": False, "message": "Username and password are required"}), 400
        
        user = users_collection.find_one({"username": username})
        if not user or not check_password_hash(user["password"], password):
            return jsonify({"success": False, "message": "Invalid username or password"}), 401
        
        token = generate_token(user["user_id"], user["username"])
        
        return jsonify({
            "success": True, "message": "Login successful", "token": token,
            "user": {"id": user["user_id"], "name": user["name"], "username": user["username"], "phone": user.get("phone", ""), "balance": float(user.get("balance", 0.0)), "account_number": user.get("account_number", ""), "bank_name": user.get("bank_name", HOME_BANK_NAME), "card_number": user.get("card_number", ""), "card_expiry": user.get("card_expiry", "")}
        }), 200

    except Exception as e:
        print("LOGIN ERROR:", str(e))
        return jsonify({"success": False, "message": "Something went wrong. Please try again."}), 500