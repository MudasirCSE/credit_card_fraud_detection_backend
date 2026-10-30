import os
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

# Load variables from .env into the environment
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("MONGO_URI is missing from .env file")

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000
)

client = MongoClient(MONGO_URI)

# db = client["fraud_detection_db"]

db = client["credit_card_fraud_detection_db"]

users_collection = db["users"]
transactions_collection = db["transactions"]
security_alerts_collection = db["security_alerts"]


def create_indexes():
    """
    Create indexes used for fast lookups and to enforce uniqueness.
    Safe to call every time the app starts — Mongo skips creation if
    an identical index already exists.
    """
    try:
        # Drop the old email-based unique index if it exists — it's no
        # longer relevant now that accounts use username instead of
        # email, and leaving it in place would make every user after
        # the first fail to sign up (all documents would look like they
        # have the same missing "email" field to a unique index).
        try:
            users_collection.drop_index("unique_email")
            print("[OK] Dropped legacy unique_email index")
        except Exception:
            pass  # index didn't exist — nothing to do

        users_collection.create_index(
            [("username", ASCENDING)], unique=True, name="unique_username"
        )
        users_collection.create_index(
            [("account_number", ASCENDING)], unique=True, name="unique_account_number"
        )
        users_collection.create_index(
            [("card_number", ASCENDING)], unique=True, name="unique_card_number"
        )
        users_collection.create_index(
            [("user_id", ASCENDING)], unique=True, name="unique_user_id"
        )
        transactions_collection.create_index(
            [("user_id", ASCENDING)], name="user_id_lookup"
        )
        transactions_collection.create_index(
            [("card_hash", ASCENDING)], name="card_hash_lookup"
        )
        transactions_collection.create_index(
            [("created_at", ASCENDING)], name="created_at_sort"
        )
        print("[OK] MongoDB indexes ensured")
    except Exception as e:
        print("[WARN] Could not create indexes:")
        print(e)


def test_database():
    try:
        client.admin.command("ping")
        print("[OK] MongoDB Connected Successfully")
        create_indexes()
        return True

    except Exception as e:
        print("[ERROR] MongoDB Connection Failed:")
        print(e)
        return False