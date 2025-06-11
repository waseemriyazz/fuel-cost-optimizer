import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .utility import load_fuel_prices, determine_optimal_fuel_stops

# Load fuel data and spatial index
fuel_data, fuel_tree = load_fuel_prices()

@csrf_exempt
def get_optimal_fuel_stops(request):
    if request.method == 'GET':
        try:
            start_latitude = float(request.GET.get('start_latitude'))
            start_longitude = float(request.GET.get('start_longitude'))
            finish_latitude = float(request.GET.get('finish_latitude'))
            finish_longitude = float(request.GET.get('finish_longitude'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid or missing latitude/longitude values.'}, status=400)

        mpg = 10
        max_range = 500

        if not fuel_data or not fuel_tree:
            return JsonResponse({'error': 'Fuel price data not loaded.'}, status=500)

        try:
            result = determine_optimal_fuel_stops(
                start_latitude, start_longitude,
                finish_latitude, finish_longitude,
                fuel_data, fuel_tree, mpg, max_range
            )
            stops, stats = result[0], result[1]

            # Reformat stop keys for frontend consistency
            formatted_stops = []
            for stop in stops:
                formatted_stops.append({
                    "latitude": stop.get("Latitude", 0),
                    "longitude": stop.get("Longitude", 0),
                    "price_per_gallon": stop.get("Retail Price", 0),
                    "fuel_added": stop.get("Fuel Added (gallons)", 0),
                    "cost": stop.get("Cost ($)", 0),
                    "name": stop.get("Truckstop Name", "Unknown")
                })

            return JsonResponse({
                'optimal_stops': formatted_stops,
                'start_lat': start_latitude,
                'start_lon': start_longitude,
                'finish_lat': finish_latitude,
                'finish_lon': finish_longitude,
                'summary': stats
            })
        except Exception as e:
            logging.exception("Error calculating optimal fuel stops")
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method.'}, status=405)


def map_view(request):
    return render(request, 'index.html')
