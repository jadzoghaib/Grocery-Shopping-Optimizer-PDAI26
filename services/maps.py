import math
import requests

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_PLACES_URL  = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_mercadona(address: str, api_key: str) -> dict:
    """
    Return info about the nearest Mercadona to `address`.
    Raises RuntimeError with a human-readable message on any failure.
    """
    geo_resp = requests.get(_GEOCODE_URL, params={"address": address, "key": api_key}, timeout=10)
    geo_data = geo_resp.json()

    if geo_data.get("status") != "OK":
        raise RuntimeError(
            f"Geocoding failed: {geo_data.get('status')} — {geo_data.get('error_message', 'no detail')}"
        )

    location = geo_data["results"][0]["geometry"]["location"]
    user_lat, user_lng = location["lat"], location["lng"]

    places_resp = requests.get(
        _PLACES_URL,
        params={"location": f"{user_lat},{user_lng}", "radius": 10000, "keyword": "Mercadona", "key": api_key},
        timeout=10,
    )
    places_data = places_resp.json()
    status = places_data.get("status")

    if status == "ZERO_RESULTS":
        raise RuntimeError("No Mercadona stores found within 10 km of that location.")
    if status != "OK":
        raise RuntimeError(f"Places API error: {status} — {places_data.get('error_message', 'no detail')}")

    best, best_dist = None, float("inf")
    for place in places_data["results"]:
        ploc = place["geometry"]["location"]
        dist = _haversine_km(user_lat, user_lng, ploc["lat"], ploc["lng"])
        if dist < best_dist:
            best_dist = dist
            best = place

    if best is None:
        raise RuntimeError("Could not determine the nearest store.")

    store_lat = best["geometry"]["location"]["lat"]
    store_lng = best["geometry"]["location"]["lng"]

    return {
        "name":           best.get("name", "Mercadona"),
        "address":        best.get("vicinity", "Address not available"),
        "distance_km":    round(best_dist, 2),
        "lat":            store_lat,
        "lng":            store_lng,
        "directions_url": (
            f"https://www.google.com/maps/dir/?api=1"
            f"&origin={user_lat},{user_lng}"
            f"&destination={store_lat},{store_lng}"
            f"&travelmode=driving"
        ),
    }
