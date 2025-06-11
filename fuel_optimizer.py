import csv
import requests
import os
from typing import List, Tuple, Dict
from dotenv import load_dotenv
from math import radians, sin, cos, asin, sqrt

load_dotenv()
API_KEY = os.getenv("GRAPH_HOPPER_API_KEY")

import logging
def calculate_route(start_latitude: float, start_longitude: float, finish_latitude: float, finish_longitude: float) -> List[Tuple[float, float]]:
    logging.info(f"Calculating route from ({start_latitude}, {start_longitude}) to ({finish_latitude}, {finish_longitude})")
    """
    Calculates the route between two locations using the GraphHopper API.
    Returns a list of (latitude, longitude) coordinates representing the route.
    """
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
            return [(coord[1], coord[0]) for coord in coordinates]  # Reverse (lon, lat) to (lat, lon)
        else:
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during route calculation: {e}")
        return []

def get_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    logging.debug(f"Calculating distance between {coord1} and {coord2}")
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    r = 3956
    return c * r

def find_potential_fuel_stops(route: List[Tuple[float, float]], fuel_prices: List[Dict], max_range: int) -> List[Dict]:
    potential_stops = []
    for lat, lon in route:
        for stop in fuel_prices:
            lat_str = stop.get('Latitude', '').strip()
            lon_str = stop.get('Longitude', '').strip()
            
            if not lat_str or not lon_str:
                continue  # Skip invalid or empty values
            
            try:
                stop_lat = float(lat_str)
                stop_lon = float(lon_str)
            except ValueError:
                continue  # Skip non-convertible values

            if get_distance((lat, lon), (stop_lat, stop_lon)) <= 10:
                logging.debug(f"Potential stop found at ({stop_lat}, {stop_lon}) for route point ({lat}, {lon})")
                potential_stops.append(stop)

    logging.info(f"Found {len(potential_stops)} potential fuel stops.")
    return potential_stops

def determine_optimal_fuel_stops(start_latitude: float, start_longitude: float, finish_latitude: float, finish_longitude: float, fuel_prices: List[Dict], mpg: int, max_range: int) -> List[Dict]:
    logging.info(f"Determining optimal fuel stops from ({start_latitude}, {start_longitude}) to ({finish_latitude}, {finish_longitude}) with mpg={mpg} and max_range={max_range}")
    route = calculate_route(start_latitude, start_longitude, finish_latitude, finish_longitude)
    if not route:
        return []

    optimal_stops = []
    current_location = (start_latitude, start_longitude)
    remaining_range = max_range

    while get_distance(current_location, (finish_latitude, finish_longitude)) > remaining_range:
        potential_stops = []
        for stop in fuel_prices:
            lat_str = stop.get('Latitude', '').strip()
            lon_str = stop.get('Longitude', '').strip()
            price_str = stop.get('Retail Price', '').strip()

            if not lat_str or not lon_str or not price_str:
                continue

            try:
                stop_lat = float(lat_str)
                stop_lon = float(lon_str)
                stop_price = float(price_str)
            except ValueError:
                continue

            stop_location = (stop_lat, stop_lon)
            distance_to_stop = get_distance(current_location, stop_location)
            distance_stop_to_finish = get_distance(stop_location, (finish_latitude, finish_longitude))
            distance_current_to_finish = get_distance(current_location, (finish_latitude, finish_longitude))

            if distance_to_stop <= remaining_range and distance_stop_to_finish < distance_current_to_finish:
                potential_stops.append({
                    'Latitude': stop_lat,
                    'Longitude': stop_lon,
                    'Retail Price': stop_price,
                    **stop
                })

        logging.info(f"{len(potential_stops)} possible fuel stops within {remaining_range} miles")

        if not potential_stops:
            logging.warning("No fuel stops within range. Unable to complete the route.")
            return []

        cheapest_stop = min(potential_stops, key=lambda stop: float(stop['Retail Price']))
        optimal_stops.append(cheapest_stop)

        current_location = (float(cheapest_stop['Latitude']), float(cheapest_stop['Longitude']))
        remaining_range = max_range

    # FIX: Return the list of optimal stops after the loop completes.
    return optimal_stops

if __name__ == '__main__':
    fuel_prices_csv = "fuel-prices-geocoded.csv"
    fuel_prices = []
    with open(fuel_prices_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fuel_prices.append(row)

    start_latitude = 24.5551
    start_longitude = -81.7800
    finish_latitude = 48.3871
    finish_longitude = -124.7146
    mpg = 10
    max_range = 500

    route = calculate_route(start_latitude, start_longitude, finish_latitude, finish_longitude)
    if route:
        logging.info("Route calculated successfully.")
        potential_stops = find_potential_fuel_stops(route, fuel_prices, max_range)
        logging.info(f"Found {len(potential_stops)} potential fuel stops.")
        optimal_stops = determine_optimal_fuel_stops(start_latitude, start_longitude, finish_latitude, finish_longitude, fuel_prices, mpg, max_range)
        logging.info(f"Optimal stops: {optimal_stops}")
    else:
        logging.error("Could not calculate route.")
