from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class PoiDetailTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        result = client_for(self).poi_detail(str(tool_parameters["poi_id"]))
        yield self.create_variable_message("result", result)
        yield self.create_json_message(result)
