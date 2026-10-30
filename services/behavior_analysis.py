import math
import statistics
from datetime import datetime, timedelta


def _parse_timestamp(raw_dt):
    """Parse a MongoDB-stored timestamp (datetime or formatted string) safely."""
    if isinstance(raw_dt, datetime):
        return raw_dt
    if isinstance(raw_dt, str):
        for fmt in (
            "%d-%m-%Y %I:%M %p",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f"
        ):
            try:
                return datetime.strptime(raw_dt, fmt)
            except ValueError:
                continue
    return None


def _within_last_24h(raw_dt, reference_time):
    """True if a parsed timestamp falls within 24 hours before reference_time."""
    parsed = _parse_timestamp(raw_dt)
    if parsed is None:
        return False
    return parsed >= (reference_time - timedelta(hours=24))


def analyze_behavior(
    previous_transactions=None,
    amount=0.0,
    merchant="",
    location="",
    transaction_time=None
):
    """
    Analyze user transaction behavior relative to their historical profile.
    
    Factors evaluated:
    1. Amount: Compares current amount to historical average & standard deviation.
    2. Time: Evaluates whether the transaction hour deviates from normal active hours.
    3. Location: Checks if the transaction location is new / unobserved.
    4. Frequency/Velocity: Counts transactions in the past 1 hour and 24 hours.
    5. Historical Baseline: Evaluates profile maturity (new vs established user).
    
    Returns:
        dict: Detailed behavioral risk score (0-100), risk level (LOW/MEDIUM/HIGH),
              sub-feature scores, statistics, and explainable human-readable signals.
    """
    if transaction_time is None:
        transaction_time = datetime.now()

    previous_transactions = previous_transactions or []
    amount = float(amount)
    merchant = str(merchant or "").strip()
    location = str(location or "").strip()

    # ---------------------------------------------------------
    # CASE 1: NO PREVIOUS HISTORY (NEW USER / FIRST TRANSACTION)
    # ---------------------------------------------------------
    if len(previous_transactions) == 0:
        # For a new user, a modest amount is low risk, but high initial amount has slight uncertainty
        amount_score = 30.0 if amount > 25000 else 10.0
        
        signals = [
            "First transaction on this account (establishing baseline profile)"
        ]
        if amount > 25000:
            signals.append("High initial transaction amount for a new account")

        behavior_score = round(amount_score, 2)
        behavior_risk = "LOW" if behavior_score < 40 else "MEDIUM"

        return {
            "behavior_score": behavior_score,
            "behavior_risk": behavior_risk,
            "profile_status": "NEW_PROFILE",
            "signals": signals,
            "features": {
                "amount_score": round(amount_score, 2),
                "time_score": 0.0,
                "location_score": 0.0,
                "frequency_score": 0.0,
                "merchant_score": 0.0,
                "structuring_score": 0.0
            },
            "statistics": {
                "previous_transactions": 0,
                "average_amount": round(amount, 2),
                "maximum_amount": round(amount, 2),
                "recent_transactions_1h": 0,
                "recent_transactions_24h": 0
            }
        }

    # ---------------------------------------------------------
    # EXTRACT HISTORICAL STATISTICS
    # ---------------------------------------------------------
    amounts = []
    historical_hours = []
    historical_locations = set()
    historical_merchants = set()
    one_hour_ago = transaction_time - timedelta(hours=1)
    twenty_four_hours_ago = transaction_time - timedelta(hours=24)
    
    recent_1h_count = 0
    recent_24h_count = 0

    for tx in previous_transactions:
        # Amount
        try:
            val = float(tx.get("amount", 0))
            if val > 0:
                amounts.append(val)
        except (ValueError, TypeError):
            pass

        # Location
        loc = str(tx.get("location", "")).strip().lower()
        if loc:
            historical_locations.add(loc)

        # Merchant
        mch = str(tx.get("merchant", "")).strip().lower()
        if mch:
            historical_merchants.add(mch)

        # Timestamp parsing
        raw_dt = tx.get("created_at") or tx.get("date")
        parsed_dt = None
        if isinstance(raw_dt, datetime):
            parsed_dt = raw_dt
        elif isinstance(raw_dt, str):
            for fmt in (
                "%d-%m-%Y %I:%M %p",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f"
            ):
                try:
                    parsed_dt = datetime.strptime(raw_dt, fmt)
                    break
                except ValueError:
                    continue

        if parsed_dt:
            historical_hours.append(parsed_dt.hour)
            if parsed_dt >= one_hour_ago:
                recent_1h_count += 1
            if parsed_dt >= twenty_four_hours_ago:
                recent_24h_count += 1

    if not amounts:
        amounts = [amount]

    average_amount = statistics.mean(amounts)
    max_amount = max(amounts)

    signals = []

    # ---------------------------------------------------------
    # 1. AMOUNT BEHAVIOR (Weight: 40%)
    # ---------------------------------------------------------
    amount_ratio = amount / average_amount if average_amount > 0 else 1.0

    if amount_ratio <= 1.5:
        amount_score = 0.0
    elif amount_ratio <= 2.5:
        amount_score = 25.0
        signals.append(f"Transaction amount is {amount_ratio:.1f}x higher than historical average (PKR {average_amount:.0f})")
    elif amount_ratio <= 5.0:
        amount_score = 60.0
        signals.append(f"Unusual high spending: {amount_ratio:.1f}x your normal average (PKR {average_amount:.0f})")
    else:
        amount_score = 90.0
        signals.append(f"Critical spending anomaly: {amount_ratio:.1f}x higher than usual average")

    # If amount exceeds historical maximum by a large factor
    if amount > max_amount * 2.0 and len(amounts) >= 3:
        amount_score = min(100.0, amount_score + 15.0)
        signals.append(f"Exceeds previous all-time highest transaction (PKR {max_amount:.0f})")

    # ---------------------------------------------------------
    # 2. TEMPORAL / TIME BEHAVIOR (Weight: 20%)
    # ---------------------------------------------------------
    time_score = 0.0
    current_hour = transaction_time.hour

    if historical_hours:
        # Minimum circular distance in 24h clock
        min_hour_diff = min(
            min(abs(current_hour - h), 24 - abs(current_hour - h))
            for h in historical_hours
        )

        if min_hour_diff >= 6:
            time_score = 75.0
            signals.append(f"Transaction time ({transaction_time.strftime('%I:%M %p')}) is outside your regular active hours")
        elif min_hour_diff >= 4:
            time_score = 40.0
            signals.append("Transaction time differs somewhat from normal patterns")
        else:
            time_score = 0.0

    # Night penalty for high amounts between 1:00 AM and 5:00 AM
    if 1 <= current_hour <= 5 and amount > average_amount * 2:
        time_score = min(100.0, time_score + 25.0)
        signals.append("High-value transaction initiated during late night hours (1 AM - 5 AM)")

    # ---------------------------------------------------------
    # 3. LOCATION BEHAVIOR (Weight: 15%)
    # ---------------------------------------------------------
    location_score = 0.0
    if location and historical_locations:
        curr_loc_norm = location.strip().lower()
        if curr_loc_norm not in historical_locations:
            location_score = 65.0
            signals.append(f"Transaction from a new location ({location}) not seen in your history")
        else:
            location_score = 0.0

    # ---------------------------------------------------------
    # 4. FREQUENCY / VELOCITY BEHAVIOR (Weight: 15%)
    # ---------------------------------------------------------
    frequency_score = 0.0
    if recent_1h_count >= 5:
        frequency_score = 90.0
        signals.append(f"High velocity burst: {recent_1h_count} transactions initiated in the past hour")
    elif recent_1h_count >= 3:
        frequency_score = 60.0
        signals.append(f"Frequent activity: {recent_1h_count} transactions in the past hour")
    elif recent_1h_count >= 1:
        frequency_score = 15.0
    else:
        frequency_score = 0.0

    # ---------------------------------------------------------
    # 5. MERCHANT NOVELTY (Weight: 5%)
    # ---------------------------------------------------------
    merchant_score = 0.0
    if merchant and historical_merchants:
        curr_mch_norm = merchant.strip().lower()
        if curr_mch_norm not in historical_merchants:
            merchant_score = 30.0
            if amount > average_amount * 2:
                signals.append(f"First-time purchase at {merchant} with high amount")
        else:
            merchant_score = 0.0

    # ---------------------------------------------------------
    # 6. STRUCTURING / VELOCITY-VOLUME (Weight: 10%)
    # ---------------------------------------------------------
    # Catches "smurfing": unusually MANY similar-value transactions to the
    # SAME merchant/recipient, compared against this specific user's own
    # normal daily pattern for that merchant — not a flat number for
    # everyone. A user who genuinely sends the same amount to the same
    # merchant every day should never be flagged just for doing that;
    # only a spike ABOVE their own established baseline is suspicious.
    structuring_score = 0.0
    curr_merchant_norm = merchant.strip().lower()

    # Only look at this user's past transactions to the SAME merchant —
    # comparing across different merchants/recipients is what caused
    # false positives before.
    same_merchant_txns = [
        tx for tx in previous_transactions
        if str(tx.get("merchant", "")).strip().lower() == curr_merchant_norm
    ]

    similar_amount_same_merchant = [
        tx for tx in same_merchant_txns
        if abs(float(tx.get("amount", 0)) - amount) / max(amount, 1.0) <= 0.25
    ]

    # Group by calendar day to build "how many times per day does this
    # user normally send a similar amount to this merchant?"
    daily_counts = {}
    for tx in similar_amount_same_merchant:
        dt = _parse_timestamp(tx.get("created_at") or tx.get("date"))
        if dt is None:
            continue
        day_key = dt.date()
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

    today_key = transaction_time.date()
    today_count_before_this = daily_counts.pop(today_key, 0)
    today_count_with_this = today_count_before_this + 1

    distinct_prior_days = len(daily_counts)

    if distinct_prior_days >= 3:
        # Enough history to know this user's normal daily pattern for
        # this merchant — flag only a real spike above their own baseline.
        avg_daily_count = sum(daily_counts.values()) / distinct_prior_days
        if today_count_with_this > avg_daily_count + 2:
            structuring_score = 65.0
            signals.append(
                f"Unusual spike: {today_count_with_this} similar-value transactions to "
                f"{merchant} today vs your normal ~{avg_daily_count:.1f}/day — possible structuring pattern"
            )
    else:
        # Not enough history yet to know what's "normal" for this user and
        # this merchant — stay conservative so a genuinely new daily habit
        # isn't punished on day one, but still flag a same-day burst.
        if today_count_with_this >= 4:
            structuring_score = 55.0
            signals.append(
                f"{today_count_with_this} similar-value transactions to {merchant} "
                f"today — insufficient history to confirm this is your normal pattern"
            )
        elif today_count_with_this >= 3:
            structuring_score = 30.0
            signals.append(
                f"Multiple similar-value transactions to {merchant} today"
            )

    total_volume_24h = sum(
        float(tx.get("amount", 0))
        for tx in previous_transactions
        for raw_dt in [tx.get("created_at") or tx.get("date")]
        if _within_last_24h(raw_dt, transaction_time)
    ) + amount

    if structuring_score < 55.0 and recent_24h_count >= 3 and average_amount > 0 and total_volume_24h > average_amount * 6:
        structuring_score = max(structuring_score, 55.0)
        signals.append(
            f"Cumulative spending of PKR {total_volume_24h:.0f} across {recent_24h_count + 1} "
            f"transactions today is far above your typical single-transaction pattern"
        )

    # ---------------------------------------------------------
    # COMPOSITE WEIGHTED BEHAVIOR SCORE
    # ---------------------------------------------------------
    weighted_score = (
        amount_score * 0.35
        + time_score * 0.20
        + location_score * 0.15
        + frequency_score * 0.15
        + merchant_score * 0.05
        + structuring_score * 0.10
    )

    # Mature vs Limited history dampening
    profile_status = "ESTABLISHED" if len(previous_transactions) >= 5 else "LIMITED_HISTORY"
    if profile_status == "LIMITED_HISTORY" and weighted_score < 50:
        weighted_score = min(weighted_score, 45.0)

    final_behavior_score = round(min(max(weighted_score, 0.0), 100.0), 2)

    if final_behavior_score >= 65.0:
        behavior_risk = "HIGH"
    elif final_behavior_score >= 35.0:
        behavior_risk = "MEDIUM"
    else:
        behavior_risk = "LOW"

    if not signals:
        signals.append("Transaction behavior aligns with established profile patterns")

    return {
        "behavior_score": final_behavior_score,
        "behavior_risk": behavior_risk,
        "profile_status": profile_status,
        "signals": signals,
        "features": {
            "amount_score": round(amount_score, 2),
            "time_score": round(time_score, 2),
            "location_score": round(location_score, 2),
            "frequency_score": round(frequency_score, 2),
            "merchant_score": round(merchant_score, 2),
            "structuring_score": round(structuring_score, 2)
        },
        "statistics": {
            "previous_transactions": len(previous_transactions),
            "average_amount": round(average_amount, 2),
            "maximum_amount": round(max_amount, 2),
            "recent_transactions_1h": recent_1h_count,
            "recent_transactions_24h": recent_24h_count
        }
    }