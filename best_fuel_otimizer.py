import csv
import requests
import os
import logging
from typing import List, Tuple, Dict
from dotenv import load_dotenv
from math import radians
import numpy as np
from functools import lru_cache
from sklearn.neighbors import BallTree

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
                                 fuel_prices: List[Dict], tree: BallTree, mpg: int, max_range: int) -> List[Dict]:
    logging.info(f"Determining optimal fuel stops from ({start_lat}, {start_lon}) to ({end_lat}, {end_lon}) with mpg={mpg} and max_range={max_range}")
    route = calculate_route(start_lat, start_lon, end_lat, end_lon)
    if not route:
        return []

    optimal_stops = []
    current_location = (start_lat, start_lon)
    visited_indices = set()
    remaining_range = max_range

    while haversine_distance(current_location, (end_lat, end_lon)) > remaining_range:
        current_rad = [radians(current_location[0]), radians(current_location[1])]
        max_rad = remaining_range / EARTH_RADIUS_MILES
        idxs = tree.query_radius([current_rad], r=max_rad)[0]

        potential_stops = []
        for idx in idxs:
            if idx in visited_indices:
                continue
            stop = fuel_prices[idx]
            stop_loc = (stop['Latitude'], stop['Longitude'])
            if haversine_distance(stop_loc, (end_lat, end_lon)) < haversine_distance(current_location, (end_lat, end_lon)):
                potential_stops.append((idx, stop))

        logging.info(f"{len(potential_stops)} stops within {remaining_range} miles")

        if not potential_stops:
            logging.warning("No fuel stops within range. Cannot complete route.")
            return []

        best_idx, cheapest_stop = min(potential_stops, key=lambda s: s[1]['Retail Price'])
        optimal_stops.append(cheapest_stop)
        visited_indices.add(best_idx)
        current_location = (cheapest_stop['Latitude'], cheapest_stop['Longitude'])
        remaining_range = max_range

    return optimal_stops

if __name__ == '__main__':
    fuel_prices_csv = "fuel-prices-geocoded.csv"
    with open(fuel_prices_csv, 'r') as f:
        reader = csv.DictReader(f)
        raw_data = [row for row in reader]

    cleaned_data, fuel_tree = clean_fuel_data(raw_data)

    start_latitude = 24.5551
    start_longitude = -81.7800
    finish_latitude = 48.3871
    finish_longitude = -124.7146
    mpg = 10
    max_range = 500

    route = calculate_route(start_latitude, start_longitude, finish_latitude, finish_longitude)
    if route:
        logging.info("Route calculated successfully.")
        potential_stops = find_potential_fuel_stops(route, cleaned_data, fuel_tree)
        logging.info(f"Found {len(potential_stops)} potential fuel stops.")
        optimal_stops = determine_optimal_fuel_stops(start_latitude, start_longitude, finish_latitude, finish_longitude, cleaned_data, fuel_tree, mpg, max_range)
        logging.info(f"Optimal stops: {optimal_stops}")
    else:
        logging.error("Could not calculate route.")
