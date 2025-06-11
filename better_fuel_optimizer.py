import csv
import requests
import os
import logging
from typing import List, Tuple, Dict
from dotenv import load_dotenv
from math import radians, sin, cos, asin, sqrt
from functools import lru_cache
from scipy.spatial import cKDTree

load_dotenv()
API_KEY = os.getenv("GRAPH_HOPPER_API_KEY")
logging.basicConfig(level=logging.INFO)

@lru_cache(maxsize=None)
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
            return [(coord[1], coord[0]) for coord in coordinates]
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during route calculation: {e}")
        return []

def clean_fuel_data(fuel_prices: List[Dict]) -> Tuple[List[Dict], cKDTree]:
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
            points.append((lat, lon))
        except (ValueError, KeyError, AttributeError):
            continue
    tree = cKDTree(points)
    return cleaned, tree

def find_potential_fuel_stops(route: List[Tuple[float, float]], fuel_prices: List[Dict], tree: cKDTree, max_distance: float = 10) -> List[Dict]:
    potential_stops = set()
    for lat, lon in route:
        nearby_indices = tree.query_ball_point([lat, lon], r=max_distance)
        for idx in nearby_indices:
            potential_stops.add(idx)
    potential_stops_list = [fuel_prices[i] for i in potential_stops]
    logging.info(f"Found {len(potential_stops_list)} potential fuel stops within {max_distance} miles")
    return potential_stops_list

def determine_optimal_fuel_stops(start_latitude: float, start_longitude: float, finish_latitude: float, finish_longitude: float, fuel_prices: List[Dict], tree: cKDTree, mpg: int, max_range: int) -> List[Dict]:
    logging.info(f"Determining optimal fuel stops from ({start_latitude}, {start_longitude}) to ({finish_latitude}, {finish_longitude}) with mpg={mpg} and max_range={max_range}")
    route = calculate_route(start_latitude, start_longitude, finish_latitude, finish_longitude)
    if not route:
        return []

    optimal_stops = []
    current_location = (start_latitude, start_longitude)
    remaining_range = max_range

    while get_distance(current_location, (finish_latitude, finish_longitude)) > remaining_range:
        potential_stops = []

        nearby_indices = tree.query_ball_point(current_location, r=remaining_range)
        for idx in nearby_indices:
            stop = fuel_prices[idx]
            stop_location = (stop['Latitude'], stop['Longitude'])
            if get_distance(stop_location, (finish_latitude, finish_longitude)) < get_distance(current_location, (finish_latitude, finish_longitude)):
                potential_stops.append(stop)

        logging.info(f"{len(potential_stops)} possible fuel stops within {remaining_range} miles")

        if not potential_stops:
            logging.warning("No fuel stops within range. Unable to complete the route.")
            return []

        cheapest_stop = min(potential_stops, key=lambda stop: stop['Retail Price'])
        optimal_stops.append(cheapest_stop)
        current_location = (cheapest_stop['Latitude'], cheapest_stop['Longitude'])
        remaining_range = max_range

    return optimal_stops

if __name__ == '__main__':
    fuel_prices_csv = "fuel-prices-geocoded.csv"
    with open(fuel_prices_csv, 'r') as f:
        reader = csv.DictReader(f)
        raw_data = [row for row in reader]

    cleaned_fuel_prices, fuel_tree = clean_fuel_data(raw_data)

    start_latitude = 24.5551
    start_longitude = -81.7800
    finish_latitude = 48.3871
    finish_longitude = -124.7146
    mpg = 10
    max_range = 500

    route = calculate_route(start_latitude, start_longitude, finish_latitude, finish_longitude)
    if route:
        logging.info("Route calculated successfully.")
        potential_stops = find_potential_fuel_stops(route, cleaned_fuel_prices, fuel_tree)
        logging.info(f"Found {len(potential_stops)} potential fuel stops.")
        optimal_stops = determine_optimal_fuel_stops(start_latitude, start_longitude, finish_latitude, finish_longitude, cleaned_fuel_prices, fuel_tree, mpg, max_range)
        logging.info(f"Optimal stops: {optimal_stops}")
    else:
        logging.error("Could not calculate route.")
