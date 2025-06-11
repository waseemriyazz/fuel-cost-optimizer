from django.urls import path
from . import views

urlpatterns = [
    path(
        "optimal_fuel_stops/", views.get_optimal_fuel_stops, name="optimal_fuel_stops"
    ),
]
