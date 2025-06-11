import csv
import requests
import time
import re
import logging

logging.basicConfig(level=logging.INFO)


def clean_text(text):
    """
    Cleans input strings by removing unwanted characters and extra whitespace.
    """
    cleaned_text = re.sub(r"[&#]", "", text)  # Remove problematic characters
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)  # Normalize whitespace
    cleaned_text = cleaned_text.strip()
    logging.debug(f"Cleaning text: Input='{text}', Output='{cleaned_text}'")
    return cleaned_text


def geocode_address(name, city, state):
    """
    Geocodes a truck stop using its name, city, and state via the Nominatim API.
    Falls back to city+state if the full query fails.
    """
    headers = {"User-Agent": "FuelPriceGeocoder/1.0 (waseemriyaz718@gmail.com)"}

    queries = [f"{name}, {city}, {state}, USA", f"{city}, {state}, USA"]

    for query in queries:
        logging.info(f"Geocoding with query: '{query}'")
        try:
            url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data:
                return data[0]["lat"], data[0]["lon"]
        except requests.exceptions.RequestException as e:
            logging.error(f"Error during geocoding for query '{query}': {e}")
            return None, None

    return None, None


def main():
    input_csv_file = "fuel-prices-for-be-assessment.csv"
    output_csv_file = "fuel-prices-geocoded.csv"
    logging.info(
        f"Geocoding fuel prices from '{input_csv_file}' to '{output_csv_file}'"
    )

    rows_processed = 0
    rows_geocoded = 0

    try:
        with open(input_csv_file, "r", newline="") as infile, open(
            output_csv_file, "w", newline=""
        ) as outfile:

            reader = csv.reader(infile)
            writer = csv.writer(outfile)

            header = next(reader)
            writer.writerow(header + ["Latitude", "Longitude"])

            for row in reader:
                rows_processed += 1
                (
                    truckstop_id,
                    truckstop_name,
                    address,
                    city,
                    state,
                    rack_id,
                    retail_price,
                ) = row

                # Clean input fields
                truckstop_name = clean_text(truckstop_name)
                city = clean_text(city)
                state = clean_text(state)

                latitude, longitude = geocode_address(truckstop_name, city, state)

                if latitude and longitude:
                    writer.writerow(row + [latitude, longitude])
                    logging.info(
                        f"Geocoded {truckstop_name} in {city}, {state} to ({latitude}, {longitude})"
                    )
                    rows_geocoded += 1
                else:
                    writer.writerow(row + ["", ""])
                    logging.info(
                        f"Could not geocode {truckstop_name} in {city}, {state}"
                    )

                time.sleep(1)  # Respect Nominatim usage policy

    except FileNotFoundError:
        logging.error(f"Error: Input file '{input_csv_file}' not found.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

    logging.info(f"Processed {rows_processed} rows, geocoded {rows_geocoded} rows.")


if __name__ == "__main__":
    main()
