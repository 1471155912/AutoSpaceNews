"""
AutoSpaceNews (ASN) - 配置文件
集中管理所有配置项，包括 API 密钥、数据源、存储路径、调度参数等。
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

# ============================================================
# DeepSeek API 配置
# ============================================================
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = "deepseek-v4-flash"

# 密钥文件路径（与程序同目录，文件名以 . 开头为隐藏文件）
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".asn_key")

# XOR 混淆密钥（非安全加密，仅防止密钥以明文形式存储在磁盘上）
# 注意：源代码本身是可见的，所以这只是增加一层间接性，不能抵御有意破解
_XOR_KEY = b"AutoSpaceNews2026"

# 内存缓存，避免每次请求都读文件解密
_key_cache: str | None = None


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR 加密/解密（对称操作，加密和解密用同一函数）"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def get_api_key() -> str:
    """
    获取 API 密钥，优先级：环境变量 > 密钥文件 > 内存缓存
    返回空字符串表示未配置
    """
    global _key_cache

    # 1. 环境变量（最高优先级，适合服务器部署场景）
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        _key_cache = env_key
        return env_key

    # 2. 内存缓存（命中则跳过文件 IO）
    if _key_cache is not None:
        return _key_cache

    # 3. 从密钥文件读取并解密
    if os.path.exists(_KEY_FILE):
        try:
            with open(_KEY_FILE, "rb") as f:
                encrypted = f.read()
            decrypted = _xor_bytes(encrypted, _XOR_KEY)
            key = base64.b64decode(decrypted).decode("utf-8").strip()
            if key:
                _key_cache = key
                return key
        except Exception as e:
            logger.warning(f"Failed to read API key file: {e}")

    return ""


def save_api_key(key: str) -> bool:
    """
    保存 API 密钥到文件
    存储方式：Base64 编码 → XOR 混淆 → 写入 .asn_key
    Windows 下额外设置文件隐藏属性
    """
    key = key.strip()
    if not key:
        return False
    try:
        # 编码流程：明文 → Base64 → XOR → 写入文件
        encoded = base64.b64encode(key.encode("utf-8"))
        encrypted = _xor_bytes(encoded, _XOR_KEY)
        with open(_KEY_FILE, "wb") as f:
            f.write(encrypted)
        # 更新内存缓存
        global _key_cache
        _key_cache = key
        # Windows: 尝试设置文件隐藏属性（非关键，失败不影响功能）
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(_KEY_FILE, 0x02)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Failed to save API key: {e}")
        return False


def has_api_key() -> bool:
    """检查是否已配置 API 密钥"""
    return bool(get_api_key())


def clear_key_cache():
    """清除内存缓存（用于密钥变更后强制重新读取）"""
    global _key_cache
    _key_cache = None


# ============================================================
# API Key 延迟代理
# 使得 config.DEEPSEEK_API_KEY 可以像字符串一样使用，
# 但实际每次访问时才从文件/缓存读取密钥。
# 主要用于 f-string 中的透明插值。
# ============================================================
class _APIKeyProxy:
    """延迟求值的 API key 代理，行为类似字符串"""
    def __str__(self):
        return get_api_key()
    def __eq__(self, other):
        return get_api_key() == other
    def __bool__(self):
        return bool(get_api_key())
    def __len__(self):
        return len(get_api_key())
    def __repr__(self):
        return "****" if get_api_key() else ""
    def startswith(self, prefix):
        return get_api_key().startswith(prefix)


# 全局代理实例，可在 f-string 中直接使用
DEEPSEEK_API_KEY = _APIKeyProxy()
DEEPSEEK_BASE_URL = _DEEPSEEK_BASE_URL
DEEPSEEK_MODEL = _DEEPSEEK_MODEL

# ============================================================
# RSS 源列表（20+ 个源）
# ============================================================
RSS_FEEDS = [
    # --- 核心航天源 ---
    {"name": "SpaceNews", "url": "https://spacenews.com/feed/", "lang": "en"},
    {"name": "NASA Breaking", "url": "https://www.nasa.gov/news-release/feed/", "lang": "en"},
    {"name": "Space.com", "url": "https://www.space.com/feeds.xml", "lang": "en"},
    {"name": "Spaceflight Now", "url": "https://spaceflightnow.com/feed/", "lang": "en"},
    {"name": "The Verge Space", "url": "https://www.theverge.com/rss/space/index.xml", "lang": "en"},
    {"name": "Ars Technica Space", "url": "https://arstechnica.com/space/feed/", "lang": "en"},
    # --- 高频航天源 ---
    {"name": "NASASpaceFlight", "url": "https://www.nasaspaceflight.com/feed/", "lang": "en"},
    {"name": "SpaceFlight Insider", "url": "https://spaceflightinsider.com/feed/", "lang": "en"},
    {"name": "SpaceQ", "url": "https://spaceq.ca/feed/", "lang": "en"},
    {"name": "SatNews", "url": "https://www.satnews.com/rss.xml", "lang": "en"},
    # --- 政策与追踪 ---
    {"name": "Space Policy Online", "url": "https://spacepolicyonline.com/feed/", "lang": "en"},
    {"name": "KeepTrack.Space", "url": "https://www.keeptrack.space/rss.xml", "lang": "en"},
    # --- 综合国防/航天（含太空板块） ---
    {"name": "DefenseScoop", "url": "https://defensescoop.com/feed/", "lang": "en"},
    {"name": "Air & Space Forces", "url": "https://www.airandspaceforces.com/feed/", "lang": "en"},
    # --- 传统媒体科技/科学板块 ---
    {"name": "BBC Science", "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "lang": "en"},
    {"name": "CNN Tech", "url": "https://rss.cnn.com/rss/cnn_tech.rss", "lang": "en"},
    {"name": "Fox News Science", "url": "https://moxie.foxnews.com/google-publisher/science.xml", "lang": "en"},
    {"name": "NYT Science", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "lang": "en"},
    {"name": "The Guardian Science", "url": "https://www.theguardian.com/science/space/rss", "lang": "en"},
]

# ============================================================
# 招投标网站配置
# ============================================================
BIDDING_SOURCES = [
    {
        "name": "中国招投标公共服务平台",
        "url": "http://bulletin.cebpubservice.com/biddingSearch",
        "keywords": ["航天", "火箭", "卫星", "空间站", "载人航天"],
    },
]

# ============================================================
# 数据存储
# ============================================================
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
MAX_DAYS_TO_KEEP = 10
MAX_SOURCES_PER_STORY = 15

# ============================================================
# 调度器
# ============================================================
FETCH_INTERVAL_MINUTES = 240  # 4小时

# ============================================================
# 服务
# ============================================================
HOST = "0.0.0.0"
PORT = 8890

# ============================================================
# AI 处理
# ============================================================
SUMMARY_MAX_LENGTH = 300
BATCH_SIZE = 15          # 每批15篇，减少API调用次数
CONTENT_PREVIEW = 200    # 每篇取前200字送入AI
EXISTING_STORIES_LIMIT = 20  # 去重参考的已有故事上限
