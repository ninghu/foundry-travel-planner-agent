import json
import math
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from langchain_core.tools import tool

from travel_planner_agent.chaos import maybe_raise_tool_failure
from travel_planner_agent.config import get_settings


USER_AGENT = "foundry-travel-planner-agent/0.1"


def _timeout() -> float:
    return get_settings().tool_timeout_seconds


def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=_timeout(), headers=headers, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2, default=str)


def _geocode_raw(place: str) -> dict[str, Any]:
    data = _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": place, "count": 1, "language": "en", "format": "json"},
    )
    results = data.get("results") or []
    if not results:
        raise ValueError(f"No geocoding result found for '{place}'.")
    item = results[0]
    return {
        "name": item.get("name"),
        "admin1": item.get("admin1"),
        "country": item.get("country"),
        "country_code": item.get("country_code"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "timezone": item.get("timezone"),
        "population": item.get("population"),
    }


def _haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius_km = 6371.0
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    delta_lat = math.radians(b_lat - a_lat)
    delta_lon = math.radians(b_lon - a_lon)
    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(h))


def _exchange_rate_raw(base_currency: str, target_currency: str) -> float:
    base = base_currency.upper().strip()
    target = target_currency.upper().strip()
    if base == target:
        return 1.0
    data = _get_json(
        "https://api.frankfurter.app/latest",
        {"from": base, "to": target},
    )
    rates = data.get("rates") or {}
    if target not in rates:
        raise ValueError(f"No exchange rate returned for {base}->{target}.")
    return float(rates[target])


def _weather_code_label(code: int | None) -> str:
    labels = {
        0: "clear",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "light drizzle",
        53: "drizzle",
        55: "dense drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
    }
    return labels.get(code or -1, f"weather code {code}")


@tool
def geocode_place(place: str) -> str:
    """Resolve a destination, city, or airport-area name to coordinates and country metadata."""
    try:
        maybe_raise_tool_failure("geocode_place")
        return _json(_geocode_raw(place))
    except Exception as exc:
        return _json({"error": str(exc), "place": place})


@tool
def get_weather_forecast(place: str, start_date: str | None = None, days: int = 7) -> str:
    """Get a daily weather forecast for a destination using Open-Meteo."""
    try:
        maybe_raise_tool_failure("get_weather_forecast")
        location = _geocode_raw(place)
        day_count = max(1, min(int(days), 14))
        start = date.fromisoformat(start_date) if start_date else date.today()
        end = start + timedelta(days=day_count - 1)
        data = _get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                        "precipitation_sum",
                    ]
                ),
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        daily = data.get("daily") or {}
        rows = []
        for index, day in enumerate(daily.get("time", [])):
            code = (daily.get("weather_code") or [None])[index]
            rows.append(
                {
                    "date": day,
                    "condition": _weather_code_label(code),
                    "high_f": (daily.get("temperature_2m_max") or [None])[index],
                    "low_f": (daily.get("temperature_2m_min") or [None])[index],
                    "precipitation_probability_pct": (
                        daily.get("precipitation_probability_max") or [None]
                    )[index],
                    "precipitation_inches": (daily.get("precipitation_sum") or [None])[
                        index
                    ],
                }
            )
        return _json({"location": location, "forecast": rows})
    except Exception as exc:
        return _json({"error": str(exc), "place": place, "start_date": start_date})


@tool
def search_destination_places(query: str, limit: int = 3) -> str:
    """Search OpenStreetMap/Nominatim for destination or attraction place matches."""
    try:
        maybe_raise_tool_failure("search_destination_places")
        data = _get_json(
            "https://nominatim.openstreetmap.org/search",
            {
                "q": query,
                "format": "jsonv2",
                "limit": max(1, min(int(limit), 5)),
                "extratags": 1,
                "namedetails": 1,
            },
        )
        places = []
        for item in data if isinstance(data, list) else []:
            places.append(
                {
                    "display_name": item.get("display_name"),
                    "category": item.get("category"),
                    "type": item.get("type"),
                    "importance": item.get("importance"),
                    "latitude": item.get("lat"),
                    "longitude": item.get("lon"),
                    "bounding_box": item.get("boundingbox"),
                    "extra_tags": item.get("extratags"),
                }
            )
        return _json(
            {
                "query": query,
                "places": places,
                "source": "OpenStreetMap Nominatim",
            }
        )
    except Exception as exc:
        return _json({"error": str(exc), "query": query})


@tool
def get_country_profile(place_or_country: str) -> str:
    """Return country-level facts such as currencies, languages, timezones, and capital."""
    try:
        maybe_raise_tool_failure("get_country_profile")
        try:
            country_name = _geocode_raw(place_or_country).get("country") or place_or_country
        except Exception:
            country_name = place_or_country
        data = _get_json(f"https://restcountries.com/v3.1/name/{quote(country_name)}")
        item = data[0] if isinstance(data, list) and data else {}
        currencies = item.get("currencies") or {}
        return _json(
            {
                "country": (item.get("name") or {}).get("common", country_name),
                "official_name": (item.get("name") or {}).get("official"),
                "capital": item.get("capital"),
                "region": item.get("region"),
                "subregion": item.get("subregion"),
                "currencies": {
                    code: details.get("name") for code, details in currencies.items()
                },
                "languages": item.get("languages"),
                "timezones": item.get("timezones"),
                "driving_side": (item.get("car") or {}).get("side"),
                "maps": (item.get("maps") or {}).get("googleMaps"),
            }
        )
    except Exception as exc:
        return _json({"error": str(exc), "place_or_country": place_or_country})


@tool
def estimate_route_distance(origin: str, destination: str) -> str:
    """Estimate straight-line distance and rough flight duration between two places."""
    try:
        maybe_raise_tool_failure("estimate_route_distance")
        start = _geocode_raw(origin)
        end = _geocode_raw(destination)
        km = _haversine_km(
            float(start["latitude"]),
            float(start["longitude"]),
            float(end["latitude"]),
            float(end["longitude"]),
        )
        return _json(
            {
                "origin": start,
                "destination": end,
                "straight_line_km": round(km, 1),
                "straight_line_miles": round(km * 0.621371, 1),
                "rough_flight_hours": round(max(1.0, km / 800.0 + 1.5), 1),
                "note": "Distance is great-circle distance, not a booked route.",
            }
        )
    except Exception as exc:
        return _json({"error": str(exc), "origin": origin, "destination": destination})


@tool
def get_exchange_rate(base_currency: str, target_currency: str) -> str:
    """Return the latest exchange rate from one ISO currency code to another."""
    try:
        maybe_raise_tool_failure("get_exchange_rate")
        rate = _exchange_rate_raw(base_currency, target_currency)
        return _json(
            {
                "base_currency": base_currency.upper(),
                "target_currency": target_currency.upper(),
                "rate": rate,
                "source": "Frankfurter public exchange-rate API",
            }
        )
    except Exception as exc:
        return _json(
            {
                "error": str(exc),
                "base_currency": base_currency,
                "target_currency": target_currency,
            }
        )


@tool
def estimate_trip_budget(
    origin: str,
    destination: str,
    nights: int,
    travelers: int,
    style: str = "standard",
    target_currency: str = "USD",
) -> str:
    """Estimate a practical trip budget by lodging, meals, activities, local transport, and flight distance."""
    try:
        maybe_raise_tool_failure("estimate_trip_budget")
        nights_count = max(1, min(int(nights), 45))
        traveler_count = max(1, min(int(travelers), 12))
        normalized_style = style.lower().strip()
        multipliers = {
            "budget": 0.7,
            "standard": 1.0,
            "comfort": 1.35,
            "luxury": 2.3,
        }
        multiplier = multipliers.get(normalized_style, 1.0)

        destination_geo = _geocode_raw(destination)
        distance_km = 0.0
        if origin.strip():
            origin_geo = _geocode_raw(origin)
            distance_km = _haversine_km(
                float(origin_geo["latitude"]),
                float(origin_geo["longitude"]),
                float(destination_geo["latitude"]),
                float(destination_geo["longitude"]),
            )

        lodging_usd = nights_count * 155 * multiplier
        meals_usd = traveler_count * (nights_count + 1) * 55 * multiplier
        activities_usd = traveler_count * (nights_count + 1) * 45 * multiplier
        local_transport_usd = traveler_count * (nights_count + 1) * 18 * multiplier
        flight_usd = 0.0
        if distance_km:
            flight_usd = traveler_count * max(120.0, distance_km * 0.105)

        subtotal_usd = (
            lodging_usd
            + meals_usd
            + activities_usd
            + local_transport_usd
            + flight_usd
        )
        contingency_usd = subtotal_usd * 0.12
        total_usd = subtotal_usd + contingency_usd

        target = target_currency.upper().strip() or "USD"
        rate = _exchange_rate_raw("USD", target)

        def money(value: float) -> float:
            return round(value * rate, 2)

        return _json(
            {
                "destination": destination_geo,
                "inputs": {
                    "origin": origin,
                    "nights": nights_count,
                    "travelers": traveler_count,
                    "style": normalized_style,
                    "target_currency": target,
                },
                "breakdown": {
                    "lodging": money(lodging_usd),
                    "meals": money(meals_usd),
                    "activities": money(activities_usd),
                    "local_transport": money(local_transport_usd),
                    "estimated_round_trip_flights": money(flight_usd),
                    "contingency_12_percent": money(contingency_usd),
                    "total": money(total_usd),
                },
                "usd_total": round(total_usd, 2),
                "exchange_rate_usd_to_target": rate,
                "notes": [
                    "This is a planning estimate, not live airfare or hotel pricing.",
                    "Use booking sites for final prices before purchase.",
                ],
            }
        )
    except Exception as exc:
        return _json(
            {
                "error": str(exc),
                "origin": origin,
                "destination": destination,
                "nights": nights,
                "travelers": travelers,
                "style": style,
                "target_currency": target_currency,
            }
        )


DESTINATION_RESEARCH_TOOLS = [
    geocode_place,
    get_country_profile,
    get_weather_forecast,
    search_destination_places,
]

LOGISTICS_TOOLS = [geocode_place, estimate_route_distance, get_weather_forecast]

BUDGET_TOOLS = [estimate_trip_budget, get_exchange_rate, get_country_profile]

ITINERARY_TOOLS = [get_weather_forecast, search_destination_places]
