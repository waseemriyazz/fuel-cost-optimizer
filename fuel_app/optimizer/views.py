import csv
import os
import logging
from typing import List, Tuple, Dict
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from math import radians
import numpy as np
from functools import lru_cache
from sklearn.neighbors import BallTree
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GRAPH_HOPPER_API_KEY")
logging.basicConfig(level=logging.INFO)

EARTH_RADIUS_MILES = 3958.8

@lru_cache(maxsize=None)
def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    logging.debug(f"Calculating haversine distance between {coord1} and {coord2}")
    lat1, lon1 = map(radians, coord1)
    lat2, lon2 = map(radians, coord2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return EARTH_RADIUS_MILES * c

def calculate_route(start_latitude: float, start_longitude: float, finish_latitude: float, finish_longitude: float) -> List[Tuple[float, float]]:
    logging.info(f"Calculating route from ({start_latitude}, {start_longitude}) to ({finish_latitude}, {finish_longitude})")
    try:
        url = "https://graphhopper.com/api/1/route"
        params = {
            "point": [f"{start_latitude},{start_longitude}", f"{finish_latitude},{finish_longitude}"],
            "vehicle": "car",
            "locale": "en",
            "calc_points": "true",
            "points_encoded": "false",
            "key": API_KEY
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data['paths']:
            coordinates = data['paths'][0]['points']['coordinates']
            return [(coord[1], coord[0]) for coord in coordinates]  # lat, lon
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during route calculation: {e}")
        return []

def clean_fuel_data(fuel_prices: List[Dict]) -> Tuple[List[Dict], BallTree]:
    logging.info(f"Cleaning {len(fuel_prices)} fuel prices")
    cleaned = []
    points = []
    for row in fuel_prices:
        try:
            lat = float(row['Latitude'].strip())
            lon = float(row['Longitude'].strip())
            price = float(row['Retail Price'].strip())
            row['Latitude'] = lat
            row['Longitude'] = lon
            row['Retail Price'] = price
            cleaned.append(row)
            points.append([radians(lat), radians(lon)])
        except (ValueError, KeyError, AttributeError):
            continue
    tree = BallTree(np.array(points), metric='haversine')
    return cleaned, tree

def find_potential_fuel_stops(route: List[Tuple[float, float]], fuel_prices: List[Dict], tree: BallTree, max_distance: float = 3) -> List[Dict]:
    potential_stops = set()
    rad_dist = max_distance / EARTH_RADIUS_MILES
    for lat, lon in route:
        idxs = tree.query_radius([[radians(lat), radians(lon)]], r=rad_dist)[0]
        potential_stops.update(idxs)
    potential_stops_list = [fuel_prices[i] for i in potential_stops]
    logging.info(f"Found {len(potential_stops_list)} potential fuel stops within {max_distance} miles")
    return potential_stops_list
def determine_optimal_fuel_stops(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
                                 fuel_prices: List[Dict], tree: BallTree, mpg: int, tank_range: int) -> List[Dict]:
    logging.info(f"Determining optimal fuel stops from ({start_lat}, {start_lon}) to ({end_lat}, {end_lon}) with mpg={mpg} and tank_range={tank_range}")
    route = calculate_route(start_lat, start_lon, end_lat, end_lon)
    if not route:
        logging.error("Failed to calculate route.")
        return []

    optimal_stops = []
    visited_indices = set()
    current_location = (start_lat, start_lon)
    remaining_range = tank_range

    while haversine_distance(current_location, (end_lat, end_lon)) > remaining_range:
        current_rad = [radians(current_location[0]), radians(current_location[1])]
        max_rad = tank_range / EARTH_RADIUS_MILES
        idxs = tree.query_radius([current_rad], r=max_rad)[0]

        if not len(idxs):
            logging.warning("No reachable stations. Route cannot be completed.")
            return []

        candidates = []
        for idx in idxs:
            if idx in visited_indices:
                continue
            stop = fuel_prices[idx]
            stop_loc = (stop['Latitude'], stop['Longitude'])
            dist_to_stop = haversine_distance(current_location, stop_loc)
            dist_stop_to_end = haversine_distance(stop_loc, (end_lat, end_lon))

            # Only consider if this moves us forward
            if dist_stop_to_end < haversine_distance(current_location, (end_lat, end_lon)):
                candidates.append((idx, stop, dist_to_stop, dist_stop_to_end))

        if not candidates:
            logging.warning("No forward fuel stops found. Route cannot be completed.")
            return []

        # Sort by price
        candidates.sort(key=lambda x: x[1]['Retail Price'])

        for idx, stop, dist_to_stop, _ in candidates:
            if dist_to_stop <= tank_range:
                gallons_needed = dist_to_stop / mpg
                stop['Fuel Added (gallons)'] = float(round(gallons_needed, 2))
                stop['Cost ($)'] = float(round(gallons_needed * stop['Retail Price'], 2))
                optimal_stops.append(stop)
                visited_indices.add(idx)
                current_location = (stop['Latitude'], stop['Longitude'])
                remaining_range = tank_range
                break
        else:
            logging.warning("All reachable stops are more expensive or unreachable. Cannot proceed.")
            return []
    real_stops = [stop for stop in optimal_stops if stop.get('Cost ($)', 0) > 0]

# Number of fuel stops
    num_stops = len(real_stops)

    # Total fuel cost
    total_cost = round(sum(stop['Cost ($)'] for stop in real_stops), 2)

    # Optional: Total fuel added
    total_fuel = round(sum(stop['Fuel Added (gallons)'] for stop in real_stops), 2)

    logging.info(f"Number of fuel stops: {num_stops}")
    logging.info(f"Total fuel cost: ${total_cost}")
    logging.info(f"Total fuel added: {total_fuel} gallons")
    # Final leg
    final_leg_distance = haversine_distance(current_location, (end_lat, end_lon))
    gallons_needed = final_leg_distance / mpg
    final_leg = {
        'Truckstop Name': 'Final Leg to Destination',
        'Latitude': end_lat,
        'Longitude': end_lon,
        'Fuel Added (gallons)': float(round(gallons_needed, 2)),
        'Cost ($)': 0.0
    }
    optimal_stops.append(final_leg)
    return [optimal_stops,{"Number Of Fuel Stops": num_stops, "Total Fuel Cost":total_cost, "Total Fuel Added":total_fuel}]

FUEL_PRICES_CSV = "fuel-prices-cleaned.csv"

def load_fuel_prices():
    fuel_prices = []
    try:
        with open(FUEL_PRICES_CSV, 'r') as f:
            reader = csv.DictReader(f)
            fuel_prices = [row for row in reader]
    except FileNotFoundError:
        logging.error(f"Fuel price file not found: {FUEL_PRICES_CSV}")
        return [], None

    cleaned_data, fuel_tree = clean_fuel_data(fuel_prices)
    return cleaned_data, fuel_tree

fuel_data, fuel_tree = load_fuel_prices()

@csrf_exempt
def get_optimal_fuel_stops(request):
    if request.method == 'GET':
        start_latitude = float(request.GET.get('start_latitude'))
        start_longitude = float(request.GET.get('start_longitude'))
        finish_latitude = float(request.GET.get('finish_latitude'))
        finish_longitude = float(request.GET.get('finish_longitude'))
        mpg = 10
        max_range = 500

        if not fuel_data or not fuel_tree:
            return JsonResponse({'error': 'Fuel price data not loaded.'}, status=500)

        try:
            optimal_stops = determine_optimal_fuel_stops(start_latitude, start_longitude, finish_latitude, finish_longitude, fuel_data, fuel_tree, mpg, max_range)
            return JsonResponse({'optimal_stops': optimal_stops})
        except Exception as e:
            logging.exception("Error calculating optimal fuel stops")
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'Invalid request method.'}, status=405)
