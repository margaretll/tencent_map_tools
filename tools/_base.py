from client import TencentMapClient


def client_for(tool):
    return TencentMapClient(str(tool.runtime.credentials["tmap_key"]))
