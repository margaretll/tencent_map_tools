from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class DirectionTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = client_for(self)
        origin = client.geocode(str(tool_parameters["origin"]))
        destination = client.geocode(str(tool_parameters["destination"]))
        result = client.direction(origin, destination, str(tool_parameters.get("mode", "transit")))
        yield self.create_variable_message("result", result)
        yield self.create_json_message(result)
