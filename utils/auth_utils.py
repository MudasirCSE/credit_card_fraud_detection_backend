import os
import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))


def generate_token(user_id, username):
    """Create a signed JWT for a logged-in user."""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token):
    """
    Decode and validate a JWT.
    Returns (payload, None) on success or (None, error_message) on failure.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Session expired, please log in again"
    except jwt.InvalidTokenError:
        return None, "Invalid authentication token"


def token_required(f):
    """
    Decorator for protected routes.
    Reads 'Authorization: Bearer <token>', validates it, and injects the
    authenticated user's id into the view as `current_user_id`.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({
                "success": False,
                "message": "Missing or malformed Authorization header"
            }), 401

        token = auth_header.split(" ", 1)[1].strip()

        payload, error = decode_token(token)
        if error:
            return jsonify({
                "success": False,
                "message": error
            }), 401

        # Make the authenticated user's id available to the route
        kwargs["current_user_id"] = payload["user_id"]
        return f(*args, **kwargs)

    return decorated
