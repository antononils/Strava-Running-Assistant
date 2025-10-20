import random
import osmnx as ox
import networkx as nx
from osmnx import distance as oxd
from geopy.geocoders import Nominatim


# Helper for checking value within percent of target
def in_interval(value, percent, target):
    """Return True if value is within % of target (or True if target is None)."""
    if target is None:
        return True
    if value is None:
        return False
    lower = target * (1 - percent / 100)
    upper = target * (1 + percent / 100)
    return lower <= value <= upper

# Helper for geocoding a city to (lat, lon)
def map_city_to_coords(city_name):
    """Return (lat, lon) for a city string, or None if not found."""
    city = (city_name or "").strip()
    if not city:
        return None
    geolocator = Nominatim(user_agent="geoapi")
    loc = geolocator.geocode(city)
    if loc:
        return (loc.latitude, loc.longitude)
    return None

# Helper to find activities matching distance and city
def filter_activities(activities, route_info):
    """Filter Strava activities to match distance and rough city."""
    distance_target, elevation_target, time_target, pace_target, heart_rate_target = (
        float(route_info.get(k, 0)) or None for k in ("distance", "elevation_gain", "time", "pace", "heart_rate")
    )
    coords_target = map_city_to_coords(route_info.get("city", ""))

    # List to store matching activities
    filtered = []
    for a in activities or []:
        # Get main values for filtering
        distance, elevation, time, pace, heart_rate = (
            a.get(k, 0) or 0 for k in ("distance", "total_elevation_gain", "moving_time", "average_speed", "average_heartrate")
        )
        coords = a.get("start_latlng")

        # Skip if coords missing/empty or any key values are None
        if (not coords or len(coords) < 2 or any(v == 0 for v in (distance, elevation, time, pace, heart_rate))):
            continue

        # Keep only those within % of targets
        if in_interval(distance, 10, distance_target) and \
           in_interval(elevation, 10, elevation_target) and \
           in_interval(time, 5, time_target) and \
           in_interval(pace, 5, pace_target) and \
           in_interval(heart_rate, 3, heart_rate_target) and \
           (coords_target is None or in_interval(coords[0], 1, coords_target[0])) and \
           (coords_target is None or in_interval(coords[1], 1, coords_target[1])):
            filtered.append(a)
        
    return filtered

# Helper to create route based on city and distance
def generate_route(run_info, network_type="walk"):
    """Generate a short loop route near a given city."""
    try:
        # Get distance and city name from user input
        distance_target = float(run_info.get("distance", 0) or 0)
        city = (run_info.get("city") or "").strip()
        if not city:
            return []
        
        # Convert city to coordinates
        coords = map_city_to_coords(city)
        if not coords:
            return []

        # Build a small street network around the city center
        leg = distance_target / 3.0 if distance_target > 0 else 1800.0
        fetch_dist = max(1200, int(leg * 1.3))
        G = ox.graph_from_point(coords, dist=fetch_dist, network_type=network_type)
        G = oxd.add_edge_lengths(G)

        # Find start node and compute distance from it
        start = oxd.nearest_nodes(G, coords[1], coords[0])
        d_start = nx.single_source_dijkstra_path_length(G, start, weight="length")

        # Get nodes around one leg length from start (25%)
        tol = 0.25
        ring = [n for n, L in d_start.items() if (1 - tol) * leg <= L <= (1 + tol) * leg]

        # If none found, widen tolerance to 40%
        if not ring:
            tol = 0.40
            ring = [n for n, L in d_start.items() if (1 - tol) * leg <= L <= (1 + tol) * leg]
        
        # Stop if no valid nodes found
        if not ring:
            return []

        # Pick first point on the ring
        p1 = random.choice(ring)

        # Get distances from p1
        d_p1 = nx.single_source_dijkstra_path_length(G, p1, weight="length")

        # Find second point that forms a roughly equal triangle
        def p2_score(n):
            return abs(d_start.get(n, 1e12) - leg) + abs(d_p1.get(n, 1e12) - leg)

        # Build list of possible second points
        near_equilateral = [n for n in ring if abs(d_p1.get(n, 1e12) - leg) <= tol * leg and n not in (start, p1)]
        pool = near_equilateral or [n for n in ring if n not in (start, p1)]
        if not pool:
            return []

        # Pick one of the best candidates
        K = 20 if len(pool) > 40 else max(5, len(pool) // 4)
        pool_sorted = sorted(pool, key=p2_score)[:K]
        p2 = random.choice(pool_sorted) if pool_sorted else random.choice(pool)

        # Find shortest paths for each leg of the triangle
        path_a = nx.shortest_path(G, start, p1, weight="length")
        path_b = nx.shortest_path(G, p1, p2, weight="length")
        path_c = nx.shortest_path(G, p2, start, weight="length")

        # Convert node paths into (lat, lon) coordinates
        def nodes_to_latlon(path):
            return [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]

        # Combine all three legs into one continuous loop
        coords_loop = (nodes_to_latlon(path_a) + nodes_to_latlon(path_b)[1:] + nodes_to_latlon(path_c)[1:])
        return coords_loop

    except Exception:
        return []