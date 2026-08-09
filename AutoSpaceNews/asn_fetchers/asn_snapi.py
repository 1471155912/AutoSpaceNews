"""
ASN Spaceflight News API 数据源
免费、无需 API 密钥的航天新闻 REST API
文档: https://spaceflightnewsapi.net/
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict

import httpx

import asn_config as config

logger = logging.getLogger(__name__)

_SNAPI_BASE = "https://api.spaceflightnewsapi.net/v4/articles/"


async def fetch() -> List[Dict]:
    """
    从 Spaceflight News API 获取最近 7 天的航天新闻
    返回统一格式的文章列表：{title, content, url, source, published_at, lang}
    """
    articles = []
    seen_urls = set()

    # 取最近 7 天，按发布时间倒序，最多 50 篇
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "limit": 50,
        "published_at__gt": since,
        "ordering": "-published_at",
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(_SNAPI_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                url = item.get("url", "").strip()
                title = item.get("title", "").strip()
                if not title or not url:
                    continue

                # URL 去重
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # 解析发布时间（ISO 8601 格式）
                published_at = item.get("published_at", "")
                if published_at:
                    try:
                        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                        published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 提取摘要作为内容（截断到 CONTENT_PREVIEW 长度）
                summary = item.get("summary", "").strip()
                if len(summary) > config.CONTENT_PREVIEW:
                    summary = summary[:config.CONTENT_PREVIEW]

                articles.append({
                    "title": title,
                    "content": summary,
                    "url": url,
                    "source": item.get("news_site", "SpaceflightNewsAPI"),
                    "published_at": published_at,
                    "lang": "en",
                })

    except Exception as e:
        logger.error(f"SpaceflightNewsAPI: {e}")

    logger.info(f"SpaceflightNewsAPI: {len(articles)} articles")
    return articles
