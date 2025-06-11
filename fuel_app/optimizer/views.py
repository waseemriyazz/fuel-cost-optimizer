import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .utility import load_fuel_prices, determine_optimal_fuel_stops

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
