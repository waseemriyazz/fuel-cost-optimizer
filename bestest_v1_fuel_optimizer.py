# This won't work with free tier GraphHopper API key because limit for matrix is 5 locations at once.

import csv
import requests
import os
import logging
from typing import List, Tuple, Dict, Any
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
    """Calculates haversine distance between two lat/lon coordinates in miles."""
    logging.debug(f"Calculating haversine distance between {coord1} and {coord2}")
    lat1, lon1 = map(radians, coord1)
    lat2, lon2 = map(radians, coord2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return EARTH_RADIUS_MILES * c

def calculate_route_with_distance(start_latitude: float, start_longitude: float, 
                                  finish_latitude: float, finish_longitude: float) -> Tuple[List[Tuple[float, float]], float]:
    """
    Calculates a driving route and its total distance using GraphHopper.
    Returns a list of (latitude, longitude) points and the total distance in miles.
    """
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
            distance_meters = data['paths'][0]['distance'] # Distance in meters
            distance_miles = distance_meters * 0.000621371 # Convert meters to miles
            return [(coord[1], coord[0]) for coord in coordinates], distance_miles
        return [], 0.0
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during route calculation: {e}")
        return [], 0.0

def get_distance_matrix(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """
    Fetches a distance matrix from GraphHopper for a given list of points.
    Returns a dictionary containing 'distances' (in meters) and 'times' (in milliseconds).
    """
    logging.info(f"Getting distance matrix for {len(points)} points")
    if not points:
        return {'distances': [], 'times': []}

    try:
        url = "https://graphhopper.com/api/1/matrix"
        headers = {'Content-Type': 'application/json'}
        
        # Format points for the Matrix API
        # GraphHopper expects [longitude, latitude] for point arrays
        formatted_points = [[p[1], p[0]] for p in points] 
        
        payload = {
            "points": formatted_points,
            "out_arrays": ["distances"], # We only need distances for this problem
            "vehicle": "car",
            "key": API_KEY
        }

        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'distances' in data:
            # Convert distances from meters to miles
            data['distances_miles'] = [[d * 0.000621371 for d in row] for row in data['distances']]
            return data
        
        logging.error(f"Matrix API response missing 'distances': {data}")
        return {}

    except requests.exceptions.RequestException as e:
        logging.error(f"Error during Matrix API call: {e}")
        return {}

def clean_fuel_data(fuel_prices: List[Dict]) -> Tuple[List[Dict], BallTree]:
    """
    Cleans fuel price data, converts relevant fields, and builds a BallTree for efficient spatial querying.
    """
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
            logging.warning(f"Skipping malformed row: {row}")
            continue
    tree = BallTree(np.array(points), metric='haversine')
    return cleaned, tree

def find_potential_fuel_stops(route_points: List[Tuple[float, float]], 
                               fuel_prices: List[Dict], tree: BallTree, max_distance: float = 3) -> List[int]:
    """
    Finds indices of potential fuel stops (from the cleaned_data list) within a certain
    'as the crow flies' distance from any point on the driving route.
    Returns a list of unique indices.
    """
    potential_stop_indices = set()
    rad_dist = max_distance / EARTH_RADIUS_MILES # Convert miles to radians for BallTree query
    
    # Iterate through route points (can sample if route is very dense)
    # For now, let's use all points for maximum coverage
    for lat, lon in route_points:
        # Query BallTree for points within radius from the current route point
        # tree.query_radius expects radians
        idxs = tree.query_radius([[radians(lat), radians(lon)]], r=rad_dist)[0]
        potential_stop_indices_list = list(potential_stop_indices)
    logging.info(f"Found {len(potential_stop_indices_list)} potential fuel stops within {max_distance} miles")
    return potential_stop_indices_list

def determine_optimal_fuel_stops(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
                                 cleaned_fuel_data: List[Dict], fuel_tree: BallTree, mpg: int, tank_range: int) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Determines the optimal sequence of fuel stops along a route, minimizing cost.
    Utilizes GraphHopper Matrix API for efficient distance lookups.
    """
    logging.info(f"Determining optimal fuel stops from ({start_lat}, {start_lon}) to ({end_lat}, {end_lon}) with mpg={mpg} and tank_range={tank_range}")
    start_location = (start_lat, start_lon)
    end_location = (end_lat, end_lon)

    # 1. Calculate overall route and its distance (1 API call)
    overall_route_points, total_route_distance = calculate_route_with_distance(start_lat, start_lon, end_lat, end_lon)
    if not overall_route_points:
        logging.error("Failed to calculate overall route. Cannot determine optimal stops.")
        return [], {}

    logging.info(f"Overall route distance: {total_route_distance:.2f} miles")

    # 2. Find all potential fuel stops along the entire route (BallTree - no API calls)
    potential_stop_indices = find_potential_fuel_stops(overall_route_points[::500], cleaned_fuel_data, fuel_tree, max_distance=5) # Increased max_distance for broader initial search
    if not potential_stop_indices:
        logging.warning("No potential fuel stops found near the route.")
        # Even if no stops are found, we need to check if the initial range is enough
        if total_route_distance > tank_range:
            logging.error("No fuel stops and initial range is insufficient for the trip.")
            return [], {}
        else:
            logging.info("No fuel stops needed. Trip can be completed on a single tank.")
            # Create a final leg placeholder
            final_leg = {
                'Truckstop Name': 'Destination',
                'Latitude': end_lat,
                'Longitude': end_lon,
                'Fuel Added (gallons)': round(total_route_distance / mpg, 2),
                'Cost ($)': 0.0 # No cost as no stop made
            }
            return [[final_leg], {"Number Of Fuel Stops": 0, "Total Fuel Cost": 0.0, "Total Fuel Added": round(total_route_distance / mpg, 2)}]

    potential_stops = [cleaned_fuel_data[i] for i in potential_stop_indices]
    logging.info(f"Found {len(potential_stops)} potential fuel stops after initial filter.")

    # 3. Prepare all points for Matrix API call
    # Mapping for Matrix API: start_idx=0, end_idx=1, potential_stop_idx starts from 2
    matrix_points_coords = [start_location, end_location] + [(s['Latitude'], s['Longitude']) for s in potential_stops]
    
    # Create a reverse lookup for original fuel stop index from matrix point index
    # matrix_idx_to_fuel_data_idx[matrix_point_index] = original_index_in_cleaned_fuel_data
    matrix_idx_to_fuel_data_idx = {i + 2: potential_stop_indices[i] for i in range(len(potential_stops))}
    
    # 4. Get the full distance matrix (1 API call)
    # This matrix contains distances from each point to every other point.
    # distances_miles[i][j] gives distance from point i to point j.
    matrix_response = get_distance_matrix(matrix_points_coords)
    distance_matrix_miles = matrix_response.get('distances_miles', [])

    if not distance_matrix_miles:
        logging.error("Failed to get distance matrix. Cannot determine optimal stops.")
        return [], {}

    optimal_stops_details = []
    visited_indices = set() # To prevent visiting the same station multiple times unnecessarily
    current_location_coords = start_location
    remaining_range = float(tank_range) # Use float for calculations

    # Map current_location_coords to its index in matrix_points_coords
    # Initially, current_location_coords is start_location (index 0)
    current_matrix_idx = 0 

    # Main loop for finding optimal stops
    while haversine_distance(current_location_coords, end_location) > remaining_range: # Using Haversine here as a quick check for termination
        
        # Find potential candidates for the next stop
        candidates = [] # List of (price, original_fuel_data_idx, dist_to_stop_driving, dist_stop_to_end_driving)

        # Iterate through all potential stops from the initial filter
        # Get their matrix index (which starts from 2)
        for i, original_fuel_data_idx in matrix_idx_to_fuel_data_idx.items():
            stop_data = cleaned_fuel_data[original_fuel_data_idx]
            stop_matrix_idx = i # The index of this stop in the matrix_points_coords list

            if original_fuel_data_idx in visited_indices:
                continue

            # Look up driving distance from current_location to this potential stop
            # current_matrix_idx is the source, stop_matrix_idx is the destination
            dist_to_stop_driving = distance_matrix_miles[current_matrix_idx][stop_matrix_idx]

            # Look up driving distance from this potential stop to the end_location
            # stop_matrix_idx is the source, end_location (index 1) is the destination
            dist_stop_to_end_driving = distance_matrix_miles[stop_matrix_idx][1] # end_location is at index 1

            if dist_to_stop_driving > remaining_range:
                continue # Cannot reach this station

            # Compare if going to this stop moves us forward towards the destination
            # This is key to prevent zig-zagging
            # We need the driving distance from current_location to end_location for comparison
            dist_current_to_end_driving = distance_matrix_miles[current_matrix_idx][1]

            if dist_stop_to_end_driving < dist_current_to_end_driving:
                candidates.append((stop_data['Retail Price'], original_fuel_data_idx, dist_to_stop_driving, dist_stop_to_end_driving))

        if not candidates:
            logging.warning("No forward fuel stops reachable. Route cannot be completed.")
            return [], {}

        # Sort candidates by price (cheapest first)
        candidates.sort(key=lambda x: x[0]) 

        found_next_stop = False
        for price, original_fuel_data_idx, dist_to_stop_driving, _ in candidates:
            stop_data = cleaned_fuel_data[original_fuel_data_idx]
            
            gallons_needed = dist_to_stop_driving / mpg
            stop_data['Fuel Added (gallons)'] = float(round(gallons_needed, 2))
            stop_data['Cost ($)'] = float(round(gallons_needed * stop_data['Retail Price'], 2))
            
            optimal_stops_details.append(stop_data)
            visited_indices.add(original_fuel_data_idx)
            current_location_coords = (stop_data['Latitude'], stop_data['Longitude'])
            remaining_range = float(tank_range) # Tank is refilled
            
            # Update current_matrix_idx to the index of the newly chosen stop
            # This requires a reverse lookup from coords to matrix index.
            # A more robust solution might pass the matrix_idx directly in candidates.
            for idx_in_matrix, coord_in_matrix in enumerate(matrix_points_coords):
                if coord_in_matrix == current_location_coords:
                    current_matrix_idx = idx_in_matrix
                    break
            
            found_next_stop = True
            break # Move to the next leg of the journey

        if not found_next_stop:
            logging.warning("Could not find a suitable next fuel stop that advances the route or is within range.")
            return [], {}

    # Calculate final leg cost (if any fuel is needed to reach destination)
    final_leg_distance = distance_matrix_miles[current_matrix_idx][1] # Distance from last stop/start to end
    gallons_needed_final_leg = final_leg_distance / mpg

    final_leg_info = {
        'Truckstop Name': 'Final Leg to Destination',
        'Latitude': end_lat,
        'Longitude': end_lon,
        'Fuel Added (gallons)': float(round(gallons_needed_final_leg, 2)),
        'Cost ($)': 0.0 # No cost associated with reaching the destination itself
    }
    optimal_stops_details.append(final_leg_info)

    # --- Summary Statistics ---
    real_stops_made = [stop for stop in optimal_stops_details if stop.get('Cost ($)', 0) > 0]
    num_stops = len(real_stops_made)
    total_cost = round(sum(stop['Cost ($)'] for stop in real_stops_made), 2)
    total_fuel_added = round(sum(stop['Fuel Added (gallons)'] for stop in real_stops_made), 2)
    
    # Add fuel needed for the final leg
    total_fuel_added += final_leg_info['Fuel Added (gallons)']

    summary_stats = {
        "Number Of Fuel Stops": num_stops,
        "Total Fuel Cost": total_cost,
        "Total Fuel Added": total_fuel_added
    }

    logging.info(f"Route Optimization Summary: {summary_stats}")
    return optimal_stops_details, summary_stats

if __name__ == '__main__':
    fuel_prices_csv = "fuel-prices-cleaned.csv"
    if not os.path.exists(fuel_prices_csv):
        logging.error(f"Error: CSV file '{fuel_prices_csv}' not found. Please ensure it's in the same directory.")
        exit()

    with open(fuel_prices_csv, 'r') as f:
        reader = csv.DictReader(f)
        raw_data = [row for row in reader]

    cleaned_data, fuel_tree = clean_fuel_data(raw_data)
    logging.info(f"Cleaned {len(cleaned_data)} fuel data entries and built BallTree.")

    start_latitude = 24.5551
    start_longitude = -81.7800
    finish_latitude = 48.3871
    finish_longitude = -124.7146
    mpg = 10
    max_range = 500 # miles

    logging.info(f"Starting fuel stop optimization for trip from ({start_latitude}, {start_longitude}) to ({finish_latitude}, {finish_longitude})")
    optimal_stops, summary = determine_optimal_fuel_stops(
        start_latitude, start_longitude, finish_latitude, finish_longitude,
        cleaned_data, fuel_tree, mpg, max_range
    )

    if optimal_stops:
        logging.info("--- Optimal Fuel Stops Details ---")
        for stop in optimal_stops:
            logging.info(stop)
        logging.info("--- Summary ---")
        logging.info(summary)
    else:
        logging.error("Could not determine optimal fuel stops.")
