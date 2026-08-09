"""
ASN 新浪科技 JSON API 数据源
从新浪科技频道抓取航天相关新闻（国内可访问）
API 文档: feed.mix.sina.com.cn
"""
import logging
from datetime import datetime
from typing import List, Dict

import httpx

import asn_config as config

logger = logging.getLogger(__name__)

# 新浪科技频道 - 科学/航天子类
_SINA_API_URL = "https://feed.mix.sina.com.cn/api/roll/get"
_SINA_PARAMS = {
    "pageid": "153",     # 科技频道
    "lid": "2509",       # 科学子类
    "num": "50",         # 每次取50条
    "page": "1",
}

# 航天相关关键词（用于过滤非航天新闻）
_SPACE_KEYWORDS = [
    "航天", "火箭", "卫星", "空间站", "载人", "探月", "探火",
    "SpaceX", "星舰", "Starship", "星链", "Starlink",
    "NASA", "马斯克", "太空", "轨道", "发射", "长征",
    "天宫", "嫦娥", "天问", "神舟", "月球", "火星",
]


def _is_space_related(title: str) -> bool:
    """检查标题是否包含航天相关关键词"""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in _SPACE_KEYWORDS)


async def fetch() -> List[Dict]:
    """
    从新浪科技 API 抓取航天相关新闻
    只保留标题包含航天关键词的文章
    """
    articles = []

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(_SINA_API_URL, params=_SINA_PARAMS)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("result", {}).get("data", []):
                title = item.get("title", "").strip()
                if not title:
                    continue

                # 只保留航天相关新闻
                if not _is_space_related(title):
                    continue

                # 解析发布时间
                ctime = item.get("ctime", "") or item.get("mtime", "")
                if ctime:
                    try:
                        dt = datetime.fromtimestamp(int(ctime))
                        published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError):
                        published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 提取摘要
                summary = item.get("summary", "").strip()
                if len(summary) > config.CONTENT_PREVIEW:
                    summary = summary[:config.CONTENT_PREVIEW]

                url = item.get("url", "") or item.get("link", "")

                articles.append({
                    "title": title,
                    "content": summary,
                    "url": url,
                    "source": item.get("media_name", "新浪科技"),
                    "published_at": published_at,
                    "lang": "zh",
                })

    except Exception as e:
        logger.error(f"新浪科技: {e}")

    logger.info(f"新浪科技: {len(articles)} space articles")
    return articles
