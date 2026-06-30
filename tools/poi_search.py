from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class PoiSearchTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        result = client_for(self).search_pois(
            str(tool_parameters["keyword"]), str(tool_parameters["region"]), int(tool_parameters.get("page_size", 10))
        )
        yield self.create_variable_message("result", result)
        yield self.create_json_message(result)
