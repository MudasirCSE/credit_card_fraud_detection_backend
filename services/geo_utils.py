import math

# Approximate coordinates for major Pakistani cities (and a few common
# international ones) used to estimate distance between transaction
# locations. This is a lightweight lookup table for the FYP demo — a
# production system would use a real geocoding API instead.
CITY_COORDS = {
    "karachi": (24.8607, 67.0011),
    "lahore": (31.5497, 74.3436),
    "islamabad": (33.6844, 73.0479),
    "rawalpindi": (33.5651, 73.0169),
    "faisalabad": (31.4504, 73.1350),
    "multan": (30.1575, 71.5249),
    "peshawar": (34.0151, 71.5249),
    "quetta": (30.1798, 66.9750),
    "hyderabad": (25.3960, 68.3578),
    "nawabshah": (26.2442, 68.4100),
    "sukkur": (27.7052, 68.8574),
    "larkana": (27.5590, 68.2123),
    "gujranwala": (32.1877, 74.1945),
    "sialkot": (32.4945, 74.5229),
    "bahawalpur": (29.3956, 71.6836),
    "sargodha": (32.0836, 72.6711),
    "abbottabad": (34.1463, 73.2117),
    "mardan": (34.1989, 72.0404),
    "jamshoro": (25.4300, 68.2800),
    "dubai": (25.2048, 55.2708),
    "london": (51.5074, -0.1278),
    "new york": (40.7128, -74.0060),
}


def haversine_km(coord1, coord2):
    """Great-circle distance between two (lat, lon) points, in kilometres."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    r = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def check_impossible_travel(
    prev_location, prev_time, curr_location, curr_time,
    max_speed_kmh=900,
    prev_lat=None, prev_lon=None,
    curr_lat=None, curr_lon=None
):
    """
    Returns (is_impossible, distance_km, hours_elapsed, implied_speed_kmh)
    using the same distance/time/speed logic real fraud & identity-security
    systems use (e.g. Google, banking impossible-travel detectors): if the
    implied travel speed between two consecutive transaction locations
    exceeds what's physically possible (~900 km/h, faster than a
    commercial flight), the second transaction is flagged.

    Prefers real device GPS coordinates (prev_lat/lon, curr_lat/lon) when
    available — this is far more reliable than matching free-text city
    names, and works for ANY location on Earth, not just the small lookup
    table below. Falls back to the city-name table only for older records
    that don't have stored coordinates.
    """
    if prev_time is None or curr_time is None:
        return False, 0.0, 0.0, 0.0

    if prev_lat is not None and prev_lon is not None and curr_lat is not None and curr_lon is not None:
        p1 = (float(prev_lat), float(prev_lon))
        p2 = (float(curr_lat), float(curr_lon))
    else:
        if not prev_location or not curr_location:
            return False, 0.0, 0.0, 0.0
        p1 = CITY_COORDS.get(prev_location.strip().lower())
        p2 = CITY_COORDS.get(curr_location.strip().lower())
        if p1 is None or p2 is None or prev_location.strip().lower() == curr_location.strip().lower():
            return False, 0.0, 0.0, 0.0

    distance_km = haversine_km(p1, p2)
    hours_elapsed = abs((curr_time - prev_time).total_seconds()) / 3600.0

    if hours_elapsed <= 0:
        hours_elapsed = 1 / 3600.0  # avoid divide-by-zero for same-second transactions

    implied_speed = distance_km / hours_elapsed

    # Require a meaningful distance so tiny coordinate/rounding differences
    # near a city boundary don't trigger false positives.
    is_impossible = distance_km >= 50 and implied_speed > max_speed_kmh

    return is_impossible, round(distance_km, 1), round(hours_elapsed, 2), round(implied_speed, 1)