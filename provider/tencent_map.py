from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from client import TencentMapClient


class TencentMapProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            key = str(credentials.get("tmap_key", "")).strip()
            if not key:
                raise ValueError("tmap_key is required; use 'none' only for local experience mode")
            TencentMapClient(key)
        except Exception as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from exc
