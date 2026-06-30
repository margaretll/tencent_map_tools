from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools._base import client_for


class PoiSearchMultiTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """
        批量搜索 POI，一次调用获取多个类别的地点。
        
        工作流建议用法：
        1. 调用此工具，传入 keywords="景点,美食,文化" 和 city="成都"
        2. 获取按类别分组的真实 POI 列表
        3. 让 LLM 从中筛选优质 POI（可根据 rating 字段）
        4. 再调用 build_itinerary 生成行程
        """
        # 解析关键词（支持逗号分隔）
        keywords_str = str(tool_parameters["keywords"])
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
        
        result = client_for(self).search_pois_multi(
            keywords=keywords,
            city=str(tool_parameters["city"]),
            page_size_per_keyword=int(tool_parameters.get("page_size_per_keyword", 10)),
            get_rich=bool(tool_parameters.get("get_rich", True))
        )
        
        yield self.create_variable_message("pois_by_category", result)
        yield self.create_json_message(result)
