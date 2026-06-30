from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class PoiSearchTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """
        搜索 POI，返回真实地点数据。
        
        工作流建议用法：
        1. 先调用此工具获取真实 POI 列表（含名称/地址/坐标/评分等）
        2. 让 LLM 根据返回数据筛选优质 POI
        3. 再调用 build_itinerary 生成行程
        """
        result = client_for(self).search_pois(
            keyword=str(tool_parameters["keyword"]),
            city=str(tool_parameters["city"]),
            page_size=int(tool_parameters.get("page_size", 10)),
            get_rich=bool(tool_parameters.get("get_rich", True))
        )
        yield self.create_variable_message("pois", result)
        yield self.create_json_message({"pois": result, "count": len(result)})
