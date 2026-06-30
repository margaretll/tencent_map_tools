import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class BuildItineraryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        result = client_for(self).build_itinerary(
            city=str(tool_parameters["city"]),
            days=int(tool_parameters["days"]),
            locale=str(tool_parameters.get("locale", "zh")),
        )
        itinerary_json = json.dumps(result, ensure_ascii=False)
        yield self.create_variable_message("itinerary_json", itinerary_json)
        yield self.create_json_message(result)
