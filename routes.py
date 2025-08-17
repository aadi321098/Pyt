import os, requests
from flask import Blueprint, request, jsonify
from database import users, transactions
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

PI_API_BASE = os.getenv("PI_API_BASE")
PI_SERVER_API_KEY = os.getenv("PI_SERVER_API_KEY")

pi_routes = Blueprint("pi_routes", __name__)

def now_utc():
    return datetime.now(timezone.utc)

def server_headers():
    return {"Authorization": f"Key {PI_SERVER_API_KEY}", "Content-Type": "application/json"}

def user_headers(access_token: str):
    return {"Authorization": f"Bearer {access_token}"}

# ✅ Secure Login (verify user with Pi)
@pi_routes.route("/auth/verify", methods=["POST"])
def verify_auth():
    data = request.json
    access_token = data.get("accessToken")
    user = data.get("user", {})

    # Verify with Pi server
    r = requests.get(f"{PI_API_BASE}/me", headers=user_headers(access_token))
    if r.status_code != 200:
        return jsonify({"success": False, "message": "Invalid access token"}), 401
    me = r.json()
    uid = str(me.get("uid") or user.get("uid"))
    username = user.get("username") or me.get("username", "Pioneer")

    # Upsert user
    doc = users.find_one({"pi_uid": uid})
    if not doc:
        doc = {
            "pi_uid": uid,
            "username": username,
            "is_premium": False,
            "premium_expiry": None,
            "transactions": []
        }
        users.insert_one(doc)
    else:
        users.update_one({"pi_uid": uid}, {"$set": {"username": username}})

    return jsonify({"success": True, "user": doc}), 200

# ✅ Approve payment (server side)
@pi_routes.route("/payments/approve", methods=["POST"])
def approve_payment():
    data = request.json
    payment_id = data.get("paymentId")
    r = requests.post(f"{PI_API_BASE}/payments/{payment_id}/approve", headers=server_headers(), json={})
    if r.status_code not in (200, 201):
        return jsonify({"success": False, "message": "Approval failed"}), 400
    return jsonify({"success": True}), 200

# ✅ Complete payment (server side)
@pi_routes.route("/payments/complete", methods=["POST"])
def complete_payment():
    data = request.json
    payment_id = data.get("paymentId")
    txid = data.get("txid")

    # Complete with Pi server
    r = requests.post(f"{PI_API_BASE}/payments/{payment_id}/complete",
                      headers=server_headers(), json={"txid": txid})
    if r.status_code not in (200, 201):
        return jsonify({"success": False, "message": "Completion failed"}), 400

    # Get payment details
    pr = requests.get(f"{PI_API_BASE}/payments/{payment_id}", headers=server_headers())
    if pr.status_code != 200:
        return jsonify({"success": False, "message": "Cannot fetch payment details"}), 400
    payment = pr.json()

    uid = str(payment.get("from_uid") or payment.get("actor_uid"))
    amount = float(payment.get("amount", 0))

    if not uid:
        return jsonify({"success": False, "message": "User not identified"}), 400

    # Business rule: 2π = 30 days premium
    add_days = 30 if amount >= 2 else 0
    user = users.find_one({"pi_uid": uid})

    if not user:
        user = {"pi_uid": uid, "username": "Pioneer", "is_premium": False, "premium_expiry": None}
        users.insert_one(user)

    start_from = user.get("premium_expiry") if user.get("is_premium") and user["premium_expiry"] and user["premium_expiry"] > now_utc() else now_utc()
    new_expiry = start_from + timedelta(days=add_days)

    # Update DB
    users.update_one({"pi_uid": uid}, {"$set": {"is_premium": True, "premium_expiry": new_expiry}})
    transactions.insert_one({
        "pi_uid": uid,
        "amount": amount,
        "status": "completed",
        "txid": txid,
        "paymentId": payment_id,
        "timestamp": now_utc()
    })

    return jsonify({"success": True, "new_expiry": new_expiry}), 200

# ✅ User Info (with remaining days)
@pi_routes.route("/user/<pi_uid>", methods=["GET"])
def user_info(pi_uid):
    user = users.find_one({"pi_uid": pi_uid}, {"_id": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    remaining_days = 0
    if user.get("is_premium") and user.get("premium_expiry"):
        remaining_days = max(0, (user["premium_expiry"] - now_utc()).days)
    user["remaining_days"] = remaining_days
    return jsonify({"success": True, "user": user}), 200