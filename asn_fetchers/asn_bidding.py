"""
ASN 招投标数据源
中国招投标公共服务平台（bulletin.cebpubservice.com）
通过关键词搜索方式抓取最新招投标公告
注意：配置中的 url 字段仅用于文档记录，实际抓取使用下方硬编码的搜索接口 URL
"""
import hashlib
import logging
from datetime import datetime
from typing import List, Dict

import httpx
from bs4 import BeautifulSoup

import asn_config as config

logger = logging.getLogger(__name__)

# 实际抓取的搜索接口 URL（与配置中的 url 不同，配置 url 仅供文档参考）
_SEARCH_URL = "https://bulletin.cebpubservice.com/xxfbcmses/search/bulletin.html"


def _detect_chinese_encoding(raw_bytes: bytes, content_type: str = "") -> str:
    """
    检测中文网页编码（UTF-8 / GB18030 / GBK / GB2312）
    优先尝试 UTF-8，若乱码率 < 5% 则认为有效，否则依次尝试 GB 系列编码
    """
    try:
        text = raw_bytes.decode("utf-8")
        if text.count("\ufffd") < len(text) * 0.05:
            return "utf-8"
    except (UnicodeDecodeError, ValueError):
        pass
    for enc in ("gb18030", "gbk", "gb2312"):
        try:
            raw_bytes.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


async def fetch() -> List[Dict]:
    """
    遍历配置中的关键词，在招投标平台搜索最新公告
    每个关键词取前 10 条结果，URL 使用标题 MD5 做去重标识
    """
    articles = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    if not config.BIDDING_SOURCES:
        return articles

    src = config.BIDDING_SOURCES[0]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in src["keywords"]:
            try:
                params = {"word": keyword, "page": 1}
                resp = await client.get(_SEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()

                # 自动检测编码（中文网站常见 GBK/GB2312）
                raw = resp.content
                enc = _detect_chinese_encoding(raw, resp.headers.get("content-type", ""))
                text = raw.decode(enc, errors="replace")

                soup = BeautifulSoup(text, "html.parser")
                rows = soup.select("table tr")

                # 取前 10 条结果（跳过表头第 0 行）
                for row in rows[1:11]:
                    try:
                        cells = row.select("td")
                        if len(cells) < 5:
                            continue
                        link_el = cells[0].select_one("a")
                        if not link_el:
                            continue
                        title = link_el.get_text(strip=True)
                        date_str = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                        if not date_str:
                            date_str = datetime.now().strftime("%Y-%m-%d")

                        # 用标题 MD5 前 12 位做唯一标识（因原始链接是 JavaScript 无法直接使用）
                        title_hash = hashlib.md5(title.encode("utf-8")).hexdigest()[:12]
                        url = f"{_SEARCH_URL}?word={keyword}&ref={title_hash}"

                        if title and len(title) > 4:
                            articles.append({
                                "title": title,
                                "content": title,  # 招投标无正文内容，用标题代替
                                "url": url,
                                "source": src["name"],
                                "published_at": date_str,
                                "lang": "zh",
                            })
                    except Exception as e:
                        logger.debug(f"CEB item error: {e}")
            except Exception as e:
                logger.error(f"CEB search '{keyword}': {e}")

    # URL 去重（不同关键词可能返回相同结果）
    seen = set()
    unique = []
    for a in articles:
        key = a.get("url") or a.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(a)

    logger.info(f"Bidding: {len(unique)} unique articles")
    return unique
