from flask import Blueprint, jsonify
from database.database import transactions_collection, users_collection
from utils.auth_utils import token_required

transactions_bp = Blueprint("transactions", __name__)


# ============================================================
# GET ACCOUNT BALANCE
# ============================================================

@transactions_bp.route("/balance/<user_id>", methods=["GET"])
@token_required
def get_balance(user_id, current_user_id):
    """Retrieve the current account balance for a specific user."""

    if str(user_id) != str(current_user_id):
        return jsonify({
            "success": False,
            "message": "You are not authorized to view this data"
        }), 403

    try:
        user_doc = users_collection.find_one({"user_id": str(user_id)})
        if not user_doc:
            return jsonify({
                "success": False,
                "message": "Account not found"
            }), 404

        return jsonify({
            "success": True,
            "balance": float(user_doc.get("balance", 0.0)),
            "account_number": user_doc.get("account_number", ""),
            "bank_name": user_doc.get("bank_name", "SecureBank")
        }), 200

    except Exception as e:
        print(f"\n[BALANCE ERROR] {str(e)}")
        return jsonify({
            "success": False,
            "message": "Could not load balance. Please try again."
        }), 500


# ============================================================
# GET USER TRANSACTIONS
# ============================================================

@transactions_bp.route("/transactions/<user_id>", methods=["GET"])
@token_required
def get_transactions(user_id, current_user_id):
    """Retrieve full transaction history for a specific user."""

    # A logged-in user can only ever read their own transactions.
    if str(user_id) != str(current_user_id):
        return jsonify({
            "success": False,
            "message": "You are not authorized to view this data"
        }), 403

    try:
        transactions = list(
            transactions_collection.find(
                {"user_id": str(user_id)}
            ).sort("created_at", -1)
        )

        result = []

        for tx in transactions:
            result.append({
                "transaction_id": tx.get("transaction_id", ""),
                "user_id": tx.get("user_id", ""),
                "amount": float(tx.get("amount", 0)),
                "merchant": tx.get("merchant", "-"),
                "transaction_type": tx.get("transaction_type", "merchant"),   # <-- add
                "destination_bank": tx.get("destination_bank"),               # <-- add
                "recipient_account": tx.get("recipient_account"),             # <-- add
                "declined": bool(tx.get("declined", False)),                  # <-- add
                "decline_reason": tx.get("decline_reason"),                   # <-- add
                "balance_after": float(tx.get("balance_after", 0)), 
                "location": tx.get("location", ""),
                "card_masked": tx.get("card_masked", ""),
                "prediction": tx.get("prediction", "UNKNOWN"),
                "fraud": bool(tx.get("fraud", False)),
                "confidence": float(tx.get("confidence", 0)),
                "confidence_percent": float(tx.get("confidence_percent", 0)),
                "risk_score": float(tx.get("risk_score", 0)),
                "threshold": float(tx.get("threshold", 0.54)),
                "anomaly_scores": tx.get("anomaly_scores", {}),
                "behavior_analysis": tx.get("behavior_analysis", {}),
                "risk_signals": tx.get("risk_signals", []),
                "date": tx.get("date", "")
            })

        return jsonify({
            "success": True,
            "count": len(result),
            "transactions": result
        }), 200

    except Exception as e:
        print(f"\n[TRANSACTION HISTORY ERROR] {str(e)}")
        return jsonify({
            "success": False,
            "message": "Could not load transaction history. Please try again."
        }), 500


# ============================================================
# GET USER ANALYTICS SUMMARY
# ============================================================

@transactions_bp.route("/analytics/<user_id>", methods=["GET"])
@token_required
def get_analytics(user_id, current_user_id):
    """
    Calculate and return real-time statistical metrics and fraud analytics
    for the specified user from MongoDB.
    """

    if str(user_id) != str(current_user_id):
        return jsonify({
            "success": False,
            "message": "You are not authorized to view this data"
        }), 403

    try:
        transactions = list(
            transactions_collection.find(
                {"user_id": str(user_id)}
            ).sort("created_at", -1)
        )

        total_tx = len(transactions)

        if total_tx == 0:
            return jsonify({
                "success": True,
                "analytics": {
                    "total_transactions": 0,
                    "legitimate_count": 0,
                    "fraud_count": 0,
                    "fraud_rate": 0.0,
                    "total_volume": 0.0,
                    "average_amount": 0.0,
                    "average_risk_score": 0.0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "risk_distribution": {
                        "low": 0,
                        "medium": 0,
                        "high": 0
                    }
                }
            }), 200

        fraud_count = 0
        legit_count = 0
        total_volume = 0.0
        risk_scores = []

        low_risk = 0
        med_risk = 0
        high_risk = 0

        for tx in transactions:
            amt = float(tx.get("amount", 0.0))
            is_fraud = bool(tx.get("fraud", False))
            risk = float(tx.get("risk_score", 0.0))

            total_volume += amt
            risk_scores.append(risk)

            if is_fraud:
                fraud_count += 1
            else:
                legit_count += 1

            if risk >= 65.0:
                high_risk += 1
            elif risk >= 35.0:
                med_risk += 1
            else:
                low_risk += 1

        avg_amount = round(total_volume / total_tx, 2)
        avg_risk = round(sum(risk_scores) / total_tx, 2)
        fraud_rate = round((fraud_count / total_tx) * 100, 2)

        return jsonify({
            "success": True,
            "analytics": {
                "total_transactions": total_tx,
                "legitimate_count": legit_count,
                "fraud_count": fraud_count,
                "fraud_rate": fraud_rate,
                "total_volume": round(total_volume, 2),
                "average_amount": avg_amount,
                "average_risk_score": avg_risk,
                "high_risk_count": high_risk,
                "medium_risk_count": med_risk,
                "low_risk_count": low_risk,
                "risk_distribution": {
                    "low": low_risk,
                    "medium": med_risk,
                    "high": high_risk
                }
            }
        }), 200

    except Exception as e:
        print(f"\n[ANALYTICS ERROR] {str(e)}")
        return jsonify({
            "success": False,
            "message": "Could not load analytics. Please try again."
        }), 500
