import os
import uuid
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from database.database import transactions_collection, users_collection, security_alerts_collection
from services.behavior_analysis import analyze_behavior
from services.fraud_detection import predict_transaction, map_payment_to_features
from services.geo_utils import check_impossible_travel
from utils.auth_utils import token_required
from werkzeug.security import check_password_hash

prediction_bp = Blueprint("prediction", __name__)

HIGH_VALUE_THRESHOLD = 50000.0
MAX_HIGH_VALUE_TRANSACTIONS_PER_DAY = 2

def _mask_phone(phone):
    digits = "".join(filter(str.isdigit, phone or ""))
    if len(digits) < 5:
        return "XXX-XXXXXX"
    return f"{digits[:2]}XX-XXX{digits[-3:]}"

def _hash_card(card_number):
    digits = "".join(filter(str.isdigit, card_number or ""))
    if not digits:
        return None
    return hashlib.sha256(digits.encode("utf-8")).hexdigest()

@prediction_bp.route("/predict", methods=["POST"])
@token_required
def predict(current_user_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data received"}), 400

        # =====================================================
        # 1. INPUT EXTRACTION
        # =====================================================
        user_id = current_user_id
        merchant = str(data.get("merchant", "")).strip()
        transaction_type = str(data.get("transaction_type", "merchant")).strip()
        destination_bank = data.get("destination_bank")
        recipient_account = data.get("recipient_account")
        location = str(data.get("location", "Karachi")).strip()
        card_number = str(data.get("card_number", "")).strip()
        expiry = str(data.get("expiry", "")).strip()
        mpin = str(data.get("mpin", "")).strip()

        try:
            latitude = float(data.get("latitude")) if data.get("latitude") is not None else None
            longitude = float(data.get("longitude")) if data.get("longitude") is not None else None
        except (ValueError, TypeError):
            latitude, longitude = None, None

        is_mock_location = bool(data.get("is_mock_location", False))

        try:
            amount = float(data.get("amount", 0))
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid transaction amount"}), 400

        if not user_id:
            return jsonify({"success": False, "error": "user_id is required"}), 400
        if not merchant:
            return jsonify({"success": False, "error": "merchant is required"}), 400
        if amount <= 0:
            return jsonify({"success": False, "error": "Amount must be greater than 0"}), 400

        current_time = datetime.now()

        # =====================================================
        # 1b. MPIN VERIFICATION (Status 400 - app logout nahi hogi)
        # =====================================================
        if not mpin or len(mpin) != 4 or not mpin.isdigit():
            return jsonify({"success": False, "error": "MPIN must be exactly 4 digits"}), 400

        user_doc = users_collection.find_one({"user_id": user_id})
        if not user_doc:
            return jsonify({"success": False, "error": "User not found"}), 404

        if not check_password_hash(user_doc.get("mpin", ""), mpin):
            return jsonify({"success": False, "error": "Invalid MPIN. Please try again."}), 400
        # =====================================================

        # =====================================================
        # 2. RETRIEVE TRANSACTION HISTORY
        # =====================================================
        previous_transactions = list(
            transactions_collection.find({"user_id": user_id}).sort("created_at", -1).limit(50)
        )

        # =====================================================
        # 2a. BALANCE CHECK (Hamesha chalega)
        # =====================================================
        current_balance = float(user_doc.get("balance", 0.0))
        decline_reason = None

        if amount > current_balance:
            decline_reason = (
                f"Insufficient balance: transaction PKR {amount:.0f} exceeds "
                f"available balance PKR {current_balance:.0f}"
            )

        if decline_reason is None and amount > HIGH_VALUE_THRESHOLD:
            high_value_count_24h = sum(
                1 for tx in previous_transactions
                if float(tx.get("amount", 0)) > HIGH_VALUE_THRESHOLD
                and not tx.get("declined", False)
                and tx.get("created_at")
                and tx.get("created_at") >= current_time - timedelta(hours=24)
            )
            if high_value_count_24h >= MAX_HIGH_VALUE_TRANSACTIONS_PER_DAY:
                decline_reason = (
                    f"Daily limit reached: only {MAX_HIGH_VALUE_TRANSACTIONS_PER_DAY} "
                    f"transactions above PKR {HIGH_VALUE_THRESHOLD:.0f} are allowed per day"
                )

        # EARLY RETURN IF DECLINED
        if decline_reason:
            transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
            declined_document = {
                "transaction_id": transaction_id,
                "user_id": user_id,
                "success": False,
                "merchant": merchant,
                "transaction_type": transaction_type,
                "destination_bank": destination_bank,
                "recipient_account": recipient_account,
                "amount": amount,
                "location": location,
                "latitude": latitude,
                "longitude": longitude,
                "is_mock_location": is_mock_location,
                "card_masked": f"**** **** **** {card_number[-4:]}" if len(card_number) >= 4 else "",
                "prediction": "DECLINED",
                "fraud": False,
                "declined": True,
                "decline_reason": decline_reason,
                "risk_score": 0.0,
                "confidence_percent": 0.0,
                "balance_after": round(current_balance, 2),
                "risk_signals": [decline_reason],
                "date": current_time.strftime("%d-%m-%Y %I:%M %p"),
                "created_at": current_time
            }
            transactions_collection.insert_one(declined_document)
            return jsonify({
                "success": True,
                "result": {
                    "success": True,
                    "transaction_id": transaction_id,
                    "prediction": "DECLINED",
                    "fraud": False,
                    "declined": True,
                    "decline_reason": decline_reason,
                    "transaction_type": transaction_type,          # <-- add
                    "destination_bank": destination_bank,          # <-- add
                    "recipient_account": recipient_account,        # <-- add
                    "card_masked": declined_document["card_masked"],  # <-- add
                    "risk_score": 0.0,
                    "confidence_percent": 0.0,
                    "amount": amount,
                    "merchant": merchant,
                    "location": location,
                    "balance_after": round(current_balance, 2),
                    "current_balance": round(current_balance, 2),
                    "date": current_time.strftime("%d-%m-%Y %I:%M %p"),
                    "risk_signals": [decline_reason]
                }
            }), 200

        # =====================================================
        # 2b. IMPOSSIBLE TRAVEL CHECK (HAR AMOUNT PAR CHALEGA!)
        # =====================================================
        travel_signal = None
        if previous_transactions:
            last_txn = previous_transactions[0]
            is_impossible, distance_km, hours_elapsed, implied_speed = check_impossible_travel(
                prev_location=last_txn.get("location"),
                prev_time=last_txn.get("created_at"),
                curr_location=location,
                curr_time=current_time,
                prev_lat=last_txn.get("latitude"),
                prev_lon=last_txn.get("longitude"),
                curr_lat=latitude,
                curr_lon=longitude
            )
            if is_impossible:
                travel_signal = (
                    f"Impossible travel: {distance_km} km from {last_txn.get('location')} to {location} "
                    f"in {hours_elapsed} hours (implied speed {implied_speed} km/h)"
                )

        # =====================================================
        # 2c. CARD REUSE CHECK (HAR AMOUNT PAR CHALEGA!)
        # =====================================================
        card_hash = _hash_card(card_number)
        card_reuse_signal = None
        if card_hash:
            other_account_hit = transactions_collection.find_one({
                "card_hash": card_hash,
                "user_id": {"$ne": user_id},
                "created_at": {"$gte": current_time - timedelta(days=30)}
            })
            if other_account_hit:
                card_reuse_signal = "This card was used on a different account within the last 30 days"

        # =====================================================
        # 3. BEHAVIORAL ANALYSIS
        # =====================================================
        behavior_result = analyze_behavior(
            previous_transactions=previous_transactions,
            amount=amount,
            merchant=merchant,
            location=location,
            transaction_time=current_time
        )

        # =====================================================
        # 4. AI FRAUD DETECTION
        # =====================================================
        raw_features = map_payment_to_features(
            amount=amount,
            merchant=merchant,
            transaction_time=current_time,
            behavior_signals=behavior_result.get("features", {})
        )
        raw_features["Amount"] = amount
        ai_result = predict_transaction(raw_features)

        if not ai_result.get("success"):
            return jsonify({"success": False, "error": "AI Prediction engine failed"}), 500

        # =====================================================
        # 5. MULTI-FACTOR RISK AGGREGATION
        # =====================================================
        ai_risk = float(ai_result.get("ai_risk_score", 0.0))
        behavior_risk = float(behavior_result.get("behavior_score", 0.0))

        composite_risk = (0.55 * ai_risk) + (0.45 * behavior_risk)
        model_threshold_pct = float(ai_result.get("threshold", 0.54)) * 100.0

        if ai_risk >= 80.0 or behavior_risk >= 85.0:
            composite_risk = max(composite_risk, 75.0)

        if ai_risk >= model_threshold_pct:
            composite_risk = max(composite_risk, ai_risk)

        # =====================================================
        # 5b. HARD-EVIDENCE ESCALATION (Real Bank Style)
        # -----------------------------------------------------
        # These three are tampering / fraud EVIDENCE, not statistical
        # nuances — a GPS-spoofing app, a physically-impossible travel
        # gap, or a card already used on someone else's account are each
        # enough on their own to guarantee FRAUD, no matter how low the
        # AI/behavioral composite score is. Using max() (a floor) instead
        # of an additive bonus is what makes this a GUARANTEE rather than
        # "maybe, if the rest of the score is already high enough" — which
        # was the bug: a +25 bonus on a normal-looking 10% transaction
        # only reached 35%, still under the 54% threshold.
        # =====================================================
        final_risk_score = composite_risk

        if is_mock_location:
            final_risk_score = max(final_risk_score, 90.0)

        if travel_signal:
            final_risk_score = max(final_risk_score, 88.0)

        if card_reuse_signal:
            final_risk_score = max(final_risk_score, 82.0)

        final_risk_score = round(min(max(final_risk_score, 0.0), 100.0), 2)

        is_fraud = final_risk_score >= 54.0
        prediction = "FRAUD" if is_fraud else "LEGITIMATE"
        confidence_percent = final_risk_score if is_fraud else round(100.0 - final_risk_score, 2)

        # =====================================================
        # 6. BUILD RISK SIGNALS LIST
        # =====================================================
        
        if not card_number and user_doc:
            card_number = user_doc.get("card_number", "")

        masked_card = ""
        if card_number:
            clean_digits = "".join(filter(str.isdigit, card_number))
            if len(clean_digits) >= 4:
                masked_card = f"**** **** **** {clean_digits[-4:]}"
            else:
                masked_card = "**** **** **** ****"

        transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        risk_signals = list(behavior_result.get("signals", []))

        if ai_result.get("anomaly_scores", {}).get("isolation_forest", 0) > 0.4:
            risk_signals.append("High statistical outlier detected by Isolation Forest")
        if ai_result.get("anomaly_scores", {}).get("autoencoder", 0) > 0.3:
            risk_signals.append("Abnormal transaction structure detected by Autoencoder")

        if is_mock_location:
            risk_signals.append("Suspicious location activity detected. Location data cannot be trusted.")

        if travel_signal:
            risk_signals.append(travel_signal)

        if card_reuse_signal:
            risk_signals.append(card_reuse_signal)

        # =====================================================
        # 6b. BALANCE UPDATE
        # =====================================================
        if prediction == "LEGITIMATE":
            new_balance = round(current_balance - amount, 2)
            users_collection.update_one({"user_id": user_id}, {"$set": {"balance": new_balance}})
        else:
            new_balance = round(current_balance, 2)

        # # =====================================================
        # # 7. SECURITY ALERT
        # # =====================================================
        # security_alert = None
        # if prediction == "FRAUD":
        #     masked_phone = _mask_phone(user_doc.get("phone", ""))
        #     top_reason = risk_signals[0] if risk_signals else "Unusual transaction detected"
        #     security_alert = {
        #         "title": "Suspicious Transaction Blocked",
        #         "amount": amount,
        #         "merchant": merchant,
        #         "location": location,
        #         "date": current_time.strftime("%d-%m-%Y %I:%M %p"),
        #         "reason": top_reason,
        #         "status": "BLOCKED",
        #         "masked_phone": masked_phone,
        #         "delivery": "DEMO_ALERT"
        #     }
        #     security_alerts_collection.insert_one({
        #         "user_id": user_id,
        #         "transaction_id": transaction_id,
        #         **security_alert,
        #         "created_at": current_time
        #     })

        # =====================================================
        # 8. ASSEMBLE RESULT
        # =====================================================
        security_alert = None
        
        result = {
            "success": True,
            "transaction_id": transaction_id,
            "prediction": prediction,
            "fraud": is_fraud,
            "declined": False,
            "transaction_type": transaction_type,
            "destination_bank": destination_bank,       
            "recipient_account": recipient_account,    
            "risk_score": final_risk_score,
            "confidence_percent": confidence_percent,
            "threshold": ai_result.get("threshold", 0.54),
            "amount": amount,
            "merchant": merchant,
            "location": location,
            "card_masked": masked_card,
            "balance_after": new_balance,
            "current_balance": round(current_balance, 2),
            "date": current_time.strftime("%d-%m-%Y %I:%M %p"),
            "security_alert": security_alert,
            "ai_analysis": {
                "ai_risk_score": ai_risk,
                "ai_probability": ai_result.get("probability", 0.0),
                "anomaly_scores": ai_result.get("anomaly_scores", {}),
            },
            "behavior_analysis": behavior_result,
            "risk_signals": risk_signals
        }

        # =====================================================
        # 9. PERSIST TO MONGODB
        # =====================================================
        transaction_document = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "success": True,
            "merchant": merchant,
            "transaction_type": transaction_type,
            "destination_bank": destination_bank,
            "recipient_account": recipient_account,
            "amount": amount,
            "location": location,
            "latitude": latitude,
            "longitude": longitude,
            "is_mock_location": is_mock_location,
            "card_masked": masked_card,
            "card_hash": card_hash,
            "prediction": prediction,
            "fraud": is_fraud,
            "declined": False,
            "balance_after": new_balance,
            "risk_score": final_risk_score,
            "confidence": ai_result.get("probability", 0.0),
            "confidence_percent": confidence_percent,
            "threshold": ai_result.get("threshold", 0.54),
            "anomaly_scores": ai_result.get("anomaly_scores", {}),
            "behavior_analysis": behavior_result,
            "risk_signals": risk_signals,
            "date": current_time.strftime("%d-%m-%Y %I:%M %p"),
            "created_at": current_time
        }
        transactions_collection.insert_one(transaction_document)

        print(f"\n[TRANSACTION PROCESSED] {transaction_id} | {merchant} | PKR {amount} | Decision: {prediction} ({final_risk_score}%) | Mock:{is_mock_location} | Travel:{travel_signal is not None}")
        return jsonify({"success": True, "result": result}), 200

    except Exception as e:
        print(f"\n[PREDICTION ROUTE ERROR] {str(e)}")
        return jsonify({"success": False, "error": "Could not process this transaction. Please try again."}), 500