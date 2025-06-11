import csv
import logging


def is_valid_row(row):
    logging.debug(f"Validating row: {row}")
    try:
        lat = float(row["Latitude"].strip())
        lon = float(row["Longitude"].strip())
        _ = float(row["Retail Price"].strip())  # Optional: validate price too
        return True
    except (KeyError, ValueError, AttributeError):
        return False


def clean_csv(input_file: str, output_file: str):
    logging.info(f"Cleaning CSV file: {input_file} and saving to {output_file}")
    seen = set()  # Optional deduplication
    rows_processed = 0
    rows_skipped = 0
    with open(input_file, mode="r", newline="", encoding="utf-8") as infile, open(
        output_file, mode="w", newline="", encoding="utf-8"
    ) as outfile:

        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            rows_processed += 1
            # Strip all values
            cleaned_row = {k: v.strip() for k, v in row.items() if v is not None}

            # Skip malformed rows
            if not is_valid_row(cleaned_row):
                rows_skipped += 1
                continue

            # Optional deduplication (based on Lat, Lon, and Truckstop Name)
            key = (
                cleaned_row.get("Truckstop Name", "").lower(),
                cleaned_row["Latitude"],
                cleaned_row["Longitude"],
            )
            if key in seen:
                continue
            seen.add(key)

            writer.writerow(cleaned_row)
    logging.info(f"Processed {rows_processed} rows, skipped {rows_skipped} rows.")


if __name__ == "__main__":
    clean_csv("fuel-prices-geocoded.csv", "fuel-prices-cleaned.csv")
    logging.info("Cleaning complete. Output saved to 'fuel-prices-cleaned.csv'")
