import os
import logging
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_mongo_client: Optional[Any] = None
_space_id_safe: str = "default_space"

def _get_space_id_safe() -> str:
    space_id_raw = os.environ.get("SPACE_ID", "default_space")
    return space_id_raw.replace("/", "_").replace("-", "_").replace(".", "_")

async def init_db() -> None:
    global _mongo_client, _space_id_safe
    _space_id_safe = _get_space_id_safe()
    mongo_uri = os.environ.get("MONGO_URI", "").strip()
    if mongo_uri:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            _mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
            logger.info(f"MongoDB 异步客户端连接成功，隔离集合后缀: {_space_id_safe}")
        except Exception as e:
            logger.error(f"MongoDB 连接初始化失败: {e}，将使用内存降级模式")
            _mongo_client = None
    else:
        _mongo_client = None
        logger.info("未检测到 MONGO_URI 环境变量，以纯内存模式运行")

async def close_db() -> None:
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None

def is_db_enabled() -> bool:
    return _mongo_client is not None

def get_nav_collections() -> Tuple[Optional[Any], Optional[Any]]:
    if not is_db_enabled():
        return None, None
    db = _mongo_client["portal_sites_db"]
    return db[f"nav_ips_{_space_id_safe}"], db[f"nav_meta_{_space_id_safe}"]

def get_news_collections() -> Tuple[Optional[Any], Optional[Any]]:
    if not is_db_enabled():
        return None, None
    db = _mongo_client["portal_sites_db"]
    return db[f"news_items_{_space_id_safe}"], db[f"news_meta_{_space_id_safe}"]

def get_image_collection() -> Optional[Any]:
    if not is_db_enabled():
        return None
    db = _mongo_client["portal_sites_db"]
    return db[f"images_{_space_id_safe}"]
