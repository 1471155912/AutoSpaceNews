"""
ASN RSS 数据源
使用 feedparser 解析 RSS/Atom feeds，支持多语种源
所有源并发抓取，单个源超时不影响其他源
"""
import asyncio
import re
import logging
from datetime import datetime
from typing import List, Dict

import feedparser
import httpx

import asn_config as config

logger = logging.getLogger(__name__)


def _parse_entry_time(entry) -> str:
    """
    从 RSS entry 中解析发布时间
    优先 published_parsed，其次 updated_parsed，都没有则用当前时间
    """
    for attr in ("published_parsed", "updated_parsed"):
        if hasattr(entry, attr) and getattr(entry, attr):
            try:
                dt = datetime(*getattr(entry, attr)[:6])
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _extract_content(entry) -> str:
    """
    从 RSS entry 中提取纯文本内容（去除 HTML 标签）
    优先 summary，其次 description，截断到 CONTENT_PREVIEW 长度
    """
    content = ""
    if hasattr(entry, "summary"):
        content = entry.summary
    elif hasattr(entry, "description"):
        content = entry.description
    content = re.sub(r"<[^>]+>", "", content).strip()
    # 截断到配置长度（送入 AI 的内容不宜过长，节省 Token）
    if len(content) > config.CONTENT_PREVIEW:
        content = content[:config.CONTENT_PREVIEW]
    return content


async def _fetch_single_feed(client: httpx.AsyncClient, feed_info: dict) -> List[Dict]:
    """
    抓取并解析单个 RSS 源
    返回该源的文章列表，失败时返回空列表
    """
    articles = []
    try:
        resp = await client.get(feed_info["url"])
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        for entry in feed.entries[:30]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            articles.append({
                "title": title,
                "content": _extract_content(entry),
                "url": entry.get("link", ""),
                "source": feed_info["name"],
                "published_at": _parse_entry_time(entry),
                "lang": feed_info.get("lang", "en"),
            })
    except Exception as e:
        logger.error(f"RSS [{feed_info['name']}]: {e}")

    return articles


async def fetch() -> List[Dict]:
    """
    并发抓取所有 RSS 源并合并结果
    每个源独立超时，慢源不会阻塞快源
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        tasks = [_fetch_single_feed(client, feed) for feed in config.RSS_FEEDS]
        results = await asyncio.gather(*tasks)

    articles = []
    for result in results:
        articles.extend(result)

    logger.info(f"RSS: {len(articles)} articles total")
    return articles
