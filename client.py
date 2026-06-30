"""
tencent_map_tools · client
调用腾讯地图 WebService API，参考 skill tmap_client.py 实现。
"""

import re
import json
import time
import requests
from typing import Any, Dict, List, Optional, Tuple
from collections.abc import Generator


# 常量
_WS_BASE = "https://apis.map.qq.com"
_TIMEOUT = 60
_RICH_ADDED_FIELDS = "star_level,avg_price,opening_hours"

# 路线 polyline 解压
def decode_polyline(encoded: str) -> List[List[float]]:
    points: List[List[float]] = []
    lat = lng = 0
    i = 0
    while i < len(encoded):
        b = 0
        shift = 0
        while True:
            v = ord(encoded[i]) - 63
            i += 1
            b |= (v & 0x1F) << shift
            shift += 5
            if v < 0x20:
                break
        dlat = ~(b >> 1) if b & 1 else b >> 1
        lat += dlat
        b = 0
        shift = 0
        while True:
            v = ord(encoded[i]) - 63
            i += 1
            b |= (v & 0x1F) << shift
            shift += 5
            if v < 0x20:
                break
        dlng = ~(b >> 1) if b & 1 else b >> 1
        lng += dlng
        points.append([lat * 1e-6, lng * 1e-6])
    return points


class TencentMapError(RuntimeError):
    def __init__(self, code: Any, message: str, api: str):
        self.code = code
        self.message = message
        self.api = api
        super().__init__(f"Tencent Map {code}: {message} (api={api})")


class TencentMapClient:
    """腾讯地图 WebService API 客户端，参考 skill tmap_client.py"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    # ----------------------------------------------------------------
    # 底层 GET
    # ----------------------------------------------------------------
    def _ws_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params = {k: v for k, v in params.items() if v is not None and v != ""}
        params["key"] = self.api_key
        url = f"{_WS_BASE}{path}"
        try:
            r = requests.get(url, params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.Timeout:
            raise TencentMapError("TIMEOUT", f"请求超时: {url}", path)
        except Exception as e:
            raise TencentMapError("REQUEST_FAIL", str(e), path)
        if data.get("status") != 0:
            raise TencentMapError(data.get("status"), data.get("message", "unknown"), path)
        return data

    # ----------------------------------------------------------------
    # POI 搜索
    # ----------------------------------------------------------------
    def search_pois(self, keyword: str, city: str, page_size: int = 20, page_index: int = 1) -> List[Dict[str, Any]]:
        """按城市关键词搜索 POI，返回标准化列表"""
        params: Dict[str, Any] = {
            "keyword": keyword,
            "boundary": f"region({city})",
            "page_size": min(page_size, 20),
            "page_index": page_index,
        }
        # 不加 get_rich/added_fields，避免 113（免费 Key 无此权限）
        data = self._ws_get("/ws/place/v1/search", params)
        raw_list = data.get("data") or []
        results: List[Dict[str, Any]] = []
        for p in raw_list:
            loc = p.get("location") or {}
            results.append({
                "tencent_poi_id": p.get("id", ""),
                "name": p.get("title", ""),
                "address": p.get("address", ""),
                "category": p.get("category", ""),
                "location": {"lat": loc.get("lat") or 0.0, "lng": loc.get("lng") or 0.0},
                "average_price": (p.get("detail") or {}).get("average_price"),
            })
        return results

    # ----------------------------------------------------------------
    # POI 详情
    # ----------------------------------------------------------------
    def poi_detail(self, poi_id: str) -> Dict[str, Any]:
        data = self._ws_get("/ws/place/v1/detail", {"id": poi_id})
        raw = (data.get("data") or [{}])[0]
        loc = raw.get("location") or {}
        return {
            "tencent_poi_id": raw.get("id", poi_id),
            "name": raw.get("title", ""),
            "address": raw.get("address", ""),
            "category": raw.get("category", ""),
            "location": {"lat": loc.get("lat") or 0.0, "lng": loc.get("lng") or 0.0},
            "average_price": (raw.get("detail") or {}).get("average_price"),
        }

    # ----------------------------------------------------------------
    # 地址解析（地名 → 坐标）
    # ----------------------------------------------------------------
    def geocoder(self, address: str) -> Dict[str, float]:
        data = self._ws_get("/ws/geocoder/v1", {"address": address, "policy": 1})
        loc = (data.get("result") or {}).get("location") or {}
        return {"lat": loc.get("lat") or 0.0, "lng": loc.get("lng") or 0.0}

    # ----------------------------------------------------------------
    # 路线规划
    # ----------------------------------------------------------------
    def direction(self, from_loc: Dict[str, float], to_loc: Dict[str, float], mode: str = "walking") -> Dict[str, Any]:
        mode = mode if mode in ("driving", "transit", "walking", "bicycling") else "walking"
        params = {
            "from": f"{from_loc['lat']},{from_loc['lng']}",
            "to": f"{to_loc['lat']},{to_loc['lng']}",
        }
        data = self._ws_get(f"/ws/direction/v1/{mode}", params)
        routes = (data.get("result") or {}).get("routes") or []
        if not routes:
            return {"distance_meters": 0, "duration_minutes": 0, "polyline": []}
        route = routes[0]
        polyline: list[list[float]] = []
        if mode == "transit":
            polyline = self._decode_transit(route)
        else:
            raw_poly = route.get("polyline")
            if isinstance(raw_poly, str) and raw_poly:
                polyline = decode_polyline(raw_poly)
            elif isinstance(raw_poly, list) and raw_poly:
                # API 直接返回坐标数组（如 [[lat,lng], ...]）
                try:
                    polyline = [[float(p[0]), float(p[1])] for p in raw_poly]
                except Exception:
                    polyline = []
        return {
            "distance_meters": route.get("distance", 0),
            "duration_minutes": round((route.get("duration") or 0) / 60, 2),
            "polyline": polyline,
        }

    @staticmethod
    def _decode_transit(route: dict) -> list[list[float]]:
        points = []
        for step in route.get("steps", []):
            for line in step.get("lines", []):
                raw_poly = line.get("polyline")
                seg: list[list[float]] = []
                if isinstance(raw_poly, str) and raw_poly:
                    seg = decode_polyline(raw_poly)
                elif isinstance(raw_poly, list) and raw_poly:
                    try:
                        seg = [[float(p[0]), float(p[1])] for p in raw_poly]
                    except Exception:
                        seg = []
                if seg:
                    if points and seg and points[-1] == seg[0]:
                        points.extend(seg[1:])
                    else:
                        points.extend(seg)
        return points

    # ----------------------------------------------------------------
    # 日期解析（支持多种格式）
    # ----------------------------------------------------------------
    @staticmethod
    def _parse_date(s: str):
        import datetime
        s = s.strip()
        patterns = [
            (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", lambda m: datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
            (r"^(\d{1,2})[./](\d{1,2})$", lambda m: _infer_date(int(m.group(1)), int(m.group(2)))),
            (r"^(\d{1,2})[./](\d{1,2})[./](\d{1,2})$", lambda m: _infer_date(int(m.group(1)), int(m.group(2)))),
        ]
        for pat, fn in patterns:
            m = re.match(pat, s)
            if m:
                try:
                    return fn(m)
                except Exception:
                    pass
        # 兜底：返回今天
        return datetime.date.today()

    # ----------------------------------------------------------------
    # 行程构建（核心）
    # ----------------------------------------------------------------
    def build_itinerary(
        self,
        city: str,
        days: int,
        locale: str = "zh",
    ) -> Dict[str, Any]:
        """生成行程规划（只需城市和天数）"""
        days = max(1, min(7, int(days)))
        travel_mode = "walking"  # 内置默认值
        
        # 内置默认兴趣（覆盖历史文化、美食、自然、夜生活）
        interests: List[str] = ["文化", "美食", "自然", "夜生活"]
        
        # 内置默认出发日期（今天）
        from datetime import date as date_type
        start_date = date_type.today().isoformat()

        # 兴趣关键词映射（支持中英文）
        keyword_map: Dict[str, List[str]] = {
            "culture": ["博物馆", "文化场馆"],
            "food": [f"{city}美食", f"{city}烤鸭"],
            "shopping": ["热门商圈", "购物中心"],
            "history": ["历史博物馆", "古迹", "文化遗址"],
            "nature": ["自然风景区", "公园"],
            "nightlife": ["酒吧街", "夜景"],
            "art": ["美术馆", "艺术馆"],
            "technology": ["科技馆", "科技博物馆"],
            "文化": ["博物馆", "文化场馆"],
            "美食": [f"{city}美食", f"{city}烤鸭"],
            "购物": ["热门商圈", "购物中心"],
            "历史": ["历史博物馆", "古迹", "文化遗址"],
            "自然": ["自然风景区", "公园"],
            "夜生活": ["酒吧街", "夜景"],
            "艺术": ["美术馆", "艺术馆"],
            "科技": ["科技馆", "科技博物馆"],
        }

        # 搜索 POI
        interest_pools: Dict[str, List[Dict]] = {}
        seen: set = set()
        for interest in interests:
            kws = keyword_map.get(interest, [interest])
            pool: List[Dict] = []
            for kw in kws:
                if len(pool) >= 8:
                    break
                for poi in self.search_pois(kw, city, page_size=20):
                    pid = poi["tencent_poi_id"]
                    if pid and pid not in seen:
                        poi["interest"] = interest
                        seen.add(pid)
                        pool.append(poi)
            if pool:
                interest_pools[interest] = pool

        # 兜底：搜索必游景点
        candidates = [p for pool in interest_pools.values() for p in pool]
        required = days * 3
        if len(candidates) < required:
            for kw in ["必游景点", "热门景点", "著名景点", "旅游景点"]:
                if len(candidates) >= required:
                    break
                for poi in self.search_pois(kw, city, page_size=20):
                    pid = poi["tencent_poi_id"]
                    if pid and pid not in seen:
                        poi["interest"] = "culture"
                        seen.add(pid)
                        interest_pools.setdefault("culture", []).append(poi)
                        candidates.append(poi)

        if len(candidates) < required:
            raise TencentMapError(
                "INSUFFICIENT_POIS",
                f"只找到 {len(candidates)} 个有效景点，需要 {required} 个。请尝试更通用的兴趣关键词。",
                "build_itinerary"
            )

        # 构建每日行程
        from datetime import timedelta
        parsed_start = self._parse_date(start_date)
        times = ["09:00", "11:30", "14:30", "17:30"]
        per_day = min(4, max(3, len(candidates) // days))
        output_days: List[Dict] = []
        total_distance = 0.0
        total_budget = 0.0
        warnings: List[str] = []

        for day_number in range(1, days + 1):
            selected: List[Dict] = []
            for slot in range(per_day):
                desired = interests[slot % len(interests)]
                pool = interest_pools.get(desired, [])
                if not pool:
                    for v in interest_pools.values():
                        if v:
                            pool = v
                            break
                if not pool:
                    break
                if not selected:
                    selected.append(pool.pop(0))
                    continue
                # 选最近的
                prev = selected[-1]["location"]
                nearest = min(
                    range(len(pool)),
                    key=lambda i: (pool[i]["location"]["lat"] - prev["lat"]) ** 2
                    + (pool[i]["location"]["lng"] - prev["lng"]) ** 2,
                )
                selected.append(pool.pop(nearest))

            pois: List[Dict] = []
            for idx, poi in enumerate(selected):
                raw_price = float(poi.get("average_price") or 0)
                default_price = 120 if poi["interest"] == "food" else 50
                price = raw_price if poi["interest"] == "food" and 0 < raw_price <= 300 else default_price
                total_budget += price
                pois.append({
                    "id": f"day-{day_number}-poi-{idx + 1}",
                    "tencentPoiId": poi["tencent_poi_id"],
                    "name": poi["name"],
                    "category": poi["interest"],
                    "startTime": times[idx] if idx < len(times) else f"{9 + idx * 3}:00",
                    "durationMinutes": 90 if poi["interest"] == "food" else 120,
                    "address": poi["address"] or city,
                    "location": poi["location"],
                    "description": (f"{poi['category']}，位于{poi['address'] or city}。" if locale == "zh"
                                   else f"{poi['category']} in {poi['address'] or city}."),
                    "estimatedCostCny": round(price, 2),
                })

            # 路线规划
            route_points: List[List[float]] = []
            route_distance = 0.0
            route_duration = 0.0
            for idx in range(len(pois) - 1):
                try:
                    route = self.direction(pois[idx]["location"], pois[idx + 1]["location"], travel_mode)
                    route_distance += route["distance_meters"]
                    route_duration += route["duration_minutes"]
                    rp = route["polyline"]
                    if rp:
                        if route_points and rp and route_points[-1] == rp[0]:
                            route_points.extend(rp[1:])
                        else:
                            route_points.extend(rp)
                except Exception as e:
                    warnings.append(f"Day {day_number} 路线规划失败: {e}")

            total_distance += route_distance
            output_days.append({
                "day": day_number,
                "date": (parsed_start + timedelta(days=day_number - 1)).isoformat(),
                "title": f"{city} Day {day_number}" if locale != "zh" else f"{city}·第 {day_number} 天",
                "summary": "基于腾讯地图真实 POI 与路线规划。" if locale == "zh" else "Real POIs and routes from Tencent Map.",
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
            "title": f"{days}天{city}行程" if locale == "zh" else f"{days}-day {city} trip",
            "summary": "根据你的兴趣生成，景点与路线均经腾讯地图校验。" if locale == "zh"
                       else "A personalized itinerary built from verified Tencent Map places and routes.",
            "startDate": start_date,
            "travelMode": travel_mode,
            "stats": {
                "totalDays": days,
                "poiCount": sum(len(d["pois"]) for d in output_days),
                "totalDistanceKm": round(total_distance / 1000, 1),
                "estimatedBudgetCny": round(total_budget + days * 80, 2),
            },
            "days": output_days,
            "warnings": warnings,
        }


# ----------------------------------------------------------------
# 日期推断（缺少年份时自动推断）
# ----------------------------------------------------------------
def _infer_date(month: int, day: int):
    import datetime
    today = datetime.date.today()
    y = today.year
    try:
        d = datetime.date(y, month, day)
    except ValueError:
        d = datetime.date(y, month, 28)
    if d < today:
        d = datetime.date(y + 1, month, day)
    return d
