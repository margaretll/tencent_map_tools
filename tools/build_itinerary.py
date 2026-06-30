import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class BuildItineraryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        interests = [item.strip() for item in str(tool_parameters["interests"]).split(",") if item.strip()]
        result = client_for(self).build_itinerary(
            city=str(tool_parameters["city"]),
            days=int(tool_parameters["days"]),
            start_date=str(tool_parameters["start_date"]),
            interests=interests,
            travel_mode=str(tool_parameters["travel_mode"]),
            locale=str(tool_parameters.get("locale", "zh")),
        )
        itinerary_json = json.dumps(result, ensure_ascii=False)
        yield self.create_variable_message("itinerary_json", itinerary_json)
        yield self.create_json_message(result)
