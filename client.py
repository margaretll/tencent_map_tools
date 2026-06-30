from __future__ import annotations

from datetime import date, timedelta
import json
import re
from typing import Any

import requests


API_BASE = "https://apis.map.qq.com"
EXPERIENCE_API_BASE = "https://h5gw.map.qq.com"
TIMEOUT_SECONDS = 30
APPTAGS = {
    "/ws/place/v1/search": "h5mutipos_place_search",
    "/ws/place/v1/detail": "lbsplace_detail",
    "/ws/geocoder/v1": "lbs_geocoder",
    "/ws/direction/v1/driving": "lbsdirection_driving",
    "/ws/direction/v1/walking": "lbsdirection_walking",
    "/ws/direction/v1/bicycling": "lbsdirection_bicycling",
    "/ws/direction/v1/transit": "lbsdirection_transit",
}


class TencentMapError(RuntimeError):
    pass


def decode_polyline(coordinates: list[float]) -> list[list[float]]:
    if len(coordinates) < 2:
        return []
    points = [[float(coordinates[0]), float(coordinates[1])]]
    for index in range(2, len(coordinates) - 1, 2):
        lat = points[-1][0] + float(coordinates[index]) / 1_000_000
        lng = points[-1][1] + float(coordinates[index + 1]) / 1_000_000
        points.append([round(lat, 6), round(lng, 6)])
    return points


class TencentMapClient:
    def __init__(self, key: str, session: Any | None = None):
        self.key = key.strip() or "none"
        self.experience_mode = self.key == "none"
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "key": self.key, "output": "json"}
        if self.experience_mode:
            request_params.update({"apptag": APPTAGS.get(path, "lbs"), "output": "jsonp", "callback": "cb"})
        response = self.session.get(
            f"{EXPERIENCE_API_BASE if self.experience_mode else API_BASE}{path}",
            params=request_params,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if self.experience_mode:
            match = re.search(r"\((.*)\)\s*;?\s*$", response.text or "", re.S)
            if not match:
                raise TencentMapError("Tencent Map returned invalid JSONP")
            payload = json.loads(match.group(1))
        else:
            payload = response.json()
        if payload.get("status") != 0:
            raise TencentMapError(f"Tencent Map {payload.get('status')}: {payload.get('message', 'unknown error')}")
        return payload

    def search_pois(self, keyword: str, region: str, page_size: int = 10) -> list[dict[str, Any]]:
        payload = self._get("/ws/place/v1/search", {
            "keyword": keyword,
            "boundary": f"region({region},0)",
            "page_size": max(1, min(20, page_size)),
            "page_index": 1,
        })
        pois = []
        for item in payload.get("data", []):
            location = item.get("location") or {}
            if not item.get("id") or location.get("lat") is None or location.get("lng") is None:
                continue
            pois.append({
                "tencent_poi_id": str(item["id"]),
                "name": item.get("title", ""),
                "address": item.get("address") or item.get("ad_info", {}).get("name", ""),
                "category": item.get("category", "attraction"),
                "location": {"lat": float(location["lat"]), "lng": float(location["lng"])},
                "rating": item.get("star_level"),
                "average_price": item.get("avg_price"),
                "opening_hours": item.get("opening_hours"),
            })
        return pois

    def poi_detail(self, poi_id: str) -> dict[str, Any]:
        return self._get("/ws/place/v1/detail", {"id": poi_id}).get("detail", {})

    def geocode(self, address: str) -> dict[str, float]:
        payload = self._get("/ws/geocoder/v1", {"address": address, "policy": 1})
        location = payload.get("result", {}).get("location", {})
        return {"lat": float(location["lat"]), "lng": float(location["lng"])}

    def direction(self, origin: dict[str, float], destination: dict[str, float], mode: str) -> dict[str, Any]:
        supported = {"driving", "walking", "bicycling", "transit"}
        if mode not in supported:
            raise TencentMapError(f"Unsupported travel mode: {mode}")
        payload = self._get(f"/ws/direction/v1/{mode}", {
            "from": f"{origin['lat']},{origin['lng']}",
            "to": f"{destination['lat']},{destination['lng']}",
        })
        routes = payload.get("result", {}).get("routes", [])
        if not routes:
            raise TencentMapError("Tencent Map returned no route")
        route = routes[0]
        polyline = decode_polyline(route.get("polyline", []))
        if mode == "transit" and not polyline:
            polyline = self._decode_transit_polyline(route)
        return {
            "distance_meters": float(route.get("distance", 0)),
            "duration_minutes": float(route.get("duration", 0)),
            "polyline": polyline,
        }

    @staticmethod
    def _decode_transit_polyline(route: dict[str, Any]) -> list[list[float]]:
        points: list[list[float]] = []
        for step in route.get("steps", []):
            candidates = [step.get("polyline", [])]
            candidates.extend(line.get("polyline", []) for line in step.get("lines", []))
            for encoded in candidates:
                segment = decode_polyline(encoded)
                if segment:
                    points.extend(segment[1:] if points and points[-1] == segment[0] else segment)
        return points

    def build_itinerary(
        self,
        city: str,
        days: int,
        start_date: str,
        interests: list[str],
        travel_mode: str,
        locale: str,
    ) -> dict[str, Any]:
        days = max(1, min(7, int(days)))
        keyword_map = {
            "culture": "博物馆", "food": f"{city}烤鸭", "shopping": "热门商圈", "history": "历史博物馆",
            "nature": "自然风景区", "nightlife": "酒吧街", "art": "美术馆", "technology": "科技馆",
        }
        interest_pools: dict[str, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        for interest in interests:
            pool: list[dict[str, Any]] = []
            for poi in self.search_pois(keyword_map.get(interest, interest), city, page_size=20):
                if poi["tencent_poi_id"] not in seen:
                    poi["interest"] = interest
                    seen.add(poi["tencent_poi_id"])
                    pool.append(poi)
            if pool:
                interest_pools[interest] = pool

        candidates = [poi for pool in interest_pools.values() for poi in pool]
        required = days * 3
        if len(candidates) < required:
            for poi in self.search_pois("必游景点", city, page_size=20):
                if poi["tencent_poi_id"] not in seen:
                    poi["interest"] = "culture"
                    seen.add(poi["tencent_poi_id"])
                    interest_pools.setdefault("culture", []).append(poi)
                    candidates.append(poi)
        if len(candidates) < required:
            raise TencentMapError(f"Only {len(candidates)} valid POIs found; {required} required")

        output_days = []
        warnings: list[str] = []
        total_distance = 0.0
        total_budget = 0.0
        parsed_start = date.fromisoformat(start_date)
        times = ["09:00", "11:30", "14:30", "17:30"]
        per_day = min(4, max(3, len(candidates) // days))
        for day_number in range(1, days + 1):
            selected: list[dict[str, Any]] = []
            for slot in range(per_day):
                desired_interest = interests[slot % len(interests)]
                pool = interest_pools.get(desired_interest, [])
                if not pool:
                    pool = next((items for items in interest_pools.values() if items), [])
                if not pool:
                    break
                if not selected:
                    selected.append(pool.pop(0))
                    continue
                previous = selected[-1]["location"]
                nearest_index = min(
                    range(len(pool)),
                    key=lambda index: (
                        pool[index]["location"]["lat"] - previous["lat"]
                    ) ** 2 + (
                        pool[index]["location"]["lng"] - previous["lng"]
                    ) ** 2,
                )
                selected.append(pool.pop(nearest_index))
            pois = []
            for index, poi in enumerate(selected):
                raw_price = float(poi.get("average_price") or 0)
                default_price = 120 if poi["interest"] == "food" else 50
                price = raw_price if poi["interest"] == "food" and 0 < raw_price <= 300 else default_price
                total_budget += price
                pois.append({
                    "id": f"day-{day_number}-poi-{index + 1}",
                    "tencentPoiId": poi["tencent_poi_id"],
                    "name": poi["name"],
                    "category": poi["interest"],
                    "startTime": times[index],
                    "durationMinutes": 90 if poi["interest"] == "food" else 120,
                    "address": poi["address"] or city,
                    "location": poi["location"],
                    "description": (f"{poi['category']}，位于{poi['address'] or city}。" if locale == "zh" else f"{poi['category']} in {poi['address'] or city}."),
                    "estimatedCostCny": round(price, 2),
                })

            route_points: list[list[float]] = []
            route_distance = 0.0
            route_duration = 0.0
            for index in range(len(pois) - 1):
                try:
                    route = self.direction(pois[index]["location"], pois[index + 1]["location"], travel_mode)
                    route_distance += route["distance_meters"]
                    route_duration += route["duration_minutes"]
                    points = route["polyline"]
                    route_points.extend(points[1:] if route_points and points and route_points[-1] == points[0] else points)
                except Exception as exc:
                    warnings.append(f"Day {day_number}: {exc}")
            total_distance += route_distance
            output_days.append({
                "day": day_number,
                "date": (parsed_start + timedelta(days=day_number - 1)).isoformat(),
                "title": f"{city} Day {day_number}" if locale == "en" else f"{city}·第 {day_number} 天",
                "summary": "Real POIs and routes from Tencent Map." if locale == "en" else "基于腾讯地图真实 POI 与路线规划。",
                "pois": pois,
                "route": {
                    "mode": travel_mode,
                    "distanceMeters": round(route_distance, 2),
                    "durationMinutes": round(route_duration, 2),
                    "polyline": route_points,
                } if route_distance else None,
            })

        return {
            "version": "1.0",
            "city": city,
            "title": f"{days}-day {city} trip" if locale == "en" else f"{city} {days} 日行程",
            "summary": "A personalized itinerary built from verified Tencent Map places and routes." if locale == "en" else "根据你的兴趣生成，景点与路线均经腾讯地图校验。",
            "startDate": start_date,
            "travelMode": travel_mode,
            "stats": {
                "totalDays": days,
                "poiCount": sum(len(item["pois"]) for item in output_days),
                "totalDistanceKm": round(total_distance / 1000, 1),
                "estimatedBudgetCny": round(total_budget + days * 80, 2),
            },
            "days": output_days,
            "warnings": warnings,
        }
