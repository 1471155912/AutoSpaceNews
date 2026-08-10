"""
AutoSpaceNews (ASN) - AI 处理模块
使用 DeepSeek V4 Flash 完成：过滤非航天内容 / 生成中文摘要 / 提取标签 / 跨源去重
"""
import asyncio
import json
import logging
import time
from typing import List, Dict, Tuple

import httpx

import asn_config as config

logger = logging.getLogger(__name__)


def _clean_unicode(text: str) -> str:
    """
    清理 AI 输出中的无效 Unicode 代理字符（U+D800 ~ U+DFFF）。
    DeepSeek 偶尔会输出这些非法字符，直接写入 JSON 会导致编码错误。
    """
    if not text:
        return text
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))


def _strip_markdown_code_block(text: str) -> str:
    """
    清理 AI 输出中可能包裹的 Markdown 代码块标记（```json ... ```）。
    DeepSeek 有时会在 JSON 外再包一层代码块，需要去掉。
    """
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


# ============================================================
# 标题级快速过滤关键词（匹配即跳过，不送 AI 处理）
# 全部小写，匹配时 title 也转小写
# ============================================================
_EXCLUDE_TITLE_KEYWORDS = [
    # 天文图片 / 产品评测
    "apod", "astronomy picture of the day", "今日天文", "每日天文图片",
    "product review", "产品评测", "开箱", "unboxing",
    # 天文观测（月相、行星观测、流星雨、日/月食、彗星肉眼观测等，不属于航天工程）
    "crescent moon", "moon shine close", "meteor shower", "solar eclipse",
    "lunar eclipse", "comet visible", "planet alignment", "stargazing",
    "night sky guide", "what to see in the sky", "astronomy event",
    "skywatching", "skywatch", "observe the", "before dawn on",
    "tonight's sky", "this week in the sky", "monthly sky",
    "safely observe", "how to observe", "observing guide", "viewing guide",
    "smart telescope", "eclipses",  # 捕获 "eclipses" 复数形式和观测指南类文章
    # 航空类（战斗机、民航、航展等不属于航天）
    "fighter jet", "air show", "airshow", "air race",
    "boeing 737", "boeing 777", "boeing 787", "airbus a320", "airbus a350",
    "airline", "commercial flight", "passenger jet",
    "f-16", "f-22", "f-35", "a-10", "su-27", "su-35", "rafale", "typhoon jet",
    "fighter aircraft", "combat aircraft",
    "drone", "uav", "helicopter",
    # 历史回顾类内容（"On this day in space!" 等不属于实时新闻）
    "on this day", "this day in space", "today in space history", "space history",
    "historical", "anniversary", "retrospective", "looking back",
    "in space history", "space milestones", "historic space", "remembering",
    "space history timeline", "past achievements", "throwback", "flashback",
    "today in aerospace", "historical moment", "anniversary celebration",
    # 每日卫星类（"风云三号A星：当日卫星" 等属于"历史上的今天"，不是实时新闻）
    "每日卫星", "当日卫星", "今日卫星",
    # 游戏和虚拟内容
    "game", "gaming", "simulator", "virtual", "fictional", "made up",
    "science fiction", "sci-fi", "movie", "film", "tv show", "entertainment",
    # 广告和营销内容
    "sale", "discount", "promotion", "deal", "offer", "buy now", "shop now",
    "advertisement", "sponsored", "marketing", "campaign",
]


def _should_skip_by_title(title: str) -> bool:
    """标题级快速过滤：匹配关键词则直接跳过（节省 API 调用）"""
    t = title.lower()
    return any(kw in t for kw in _EXCLUDE_TITLE_KEYWORDS)


# ============================================================
# AI 系统提示词
# 定义 AI 的角色和返回格式
# ============================================================
SYSTEM_PROMPT = """你是航天新闻分析师。本系统仅收集航天(SPACE)新闻，不收集航空/飞机新闻，也不收集纯天文观测内容（如月相、行星观测、流星雨、日/月食、彗星肉眼观测等）。
处理新文章，完成：
1.过滤：排除以下类型内容
  - 产品评测、开箱、体验分享
  - APOD（天文图片）、纯天文观测（月相、行星、流星雨、日食等）
  - 历史回顾（"On this day in space"、周年纪念、历史时刻回顾等）
  - 游戏、模拟器、虚拟内容
  - 电影、娱乐、虚构内容
  - 广告、促销、营销内容
  - 纯航空新闻（战斗机、民航客机、航展、航空公司等不属于航天）
2.标题翻译：将英文标题翻译为简洁准确的中文标题，保留专有名词原文（如Starlink、SpaceX等）
3.摘要：生成<=300字中文简介，外文翻译，专有名词保留原文
4.标签：提取国家(c)、机构(o)、领域(d)
5.去重：与已有故事同一事件则归入

返回JSON数组，字段：i(编号),a(是否航天),s(匹配故事ID或null),tz(中文标题),m(简介),t标签{c,o,d}。
a为false只需{"i":编号,"a":false}。只返回JSON。"""


def _build_user_prompt(new_articles: List[Dict], existing_stories: List[Dict]) -> str:
    """
    构建发送给 AI 的用户提示词
    包含：已有故事列表（用于去重）+ 新文章列表（用于处理）
    精简格式以节省 Token
    """
    parts = []

    # 已有故事（只给 ID + 标题，限制数量避免 Token 过多）
    if existing_stories:
        parts.append("## 已有故事(去重用):")
        for i, story in enumerate(existing_stories[:config.EXISTING_STORIES_LIMIT]):
            parts.append(f"  故事ID_{i}: {story.get('title', '')}")
        parts.append("")

    # 新文章（内容截断到 CONTENT_PREVIEW 字符）
    parts.append("## 新文章:")
    preview_len = config.CONTENT_PREVIEW
    for i, art in enumerate(new_articles):
        content = (art.get("content", "") or "")[:preview_len]
        parts.append(
            f"  [{i}] {art.get('title', '')}\n"
            f"    内容:{content}\n"
            f"    来源:{art.get('source', '')} 时间:{art.get('published_at', '')}\n"
            f"    链接:{art.get('url', '')}"
        )

    parts.append("\n返回JSON数组。i=编号,a=是否航天,s=匹配故事ID或null,tz=中文标题,m=简介,t={c:[],o:[],d:[]}。a=false只需{i,a}。")
    return "\n".join(parts)


def _try_recover_json(text: str):
    """
    从截断的 JSON 中恢复有效的对象数组
    DeepSeek 有时会因 max_tokens 限制而截断输出，此函数尝试提取完整的 JSON 对象
    """
    start = text.find("[")
    if start < 0:
        return None
    results = []
    depth = 0
    obj_start = -1
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start >= 0:
                try:
                    results.append(json.loads(text[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = -1
        i += 1
    return results if results else None


async def process_articles(
    new_articles: List[Dict], existing_stories: List[Dict]
) -> Tuple[List[Dict], List[Dict], Dict]:
    """
    处理新文章：过滤、摘要、标签、去重
    分批发送给 AI，每批 BATCH_SIZE 篇
    返回: (processed_articles, [], token_usage)
      token_usage = {"input_tokens": int, "output_tokens": int}
    """
    if not new_articles:
        return [], [], {"input_tokens": 0, "output_tokens": 0}

    # 标题级快速过滤
    articles = [a for a in new_articles if not _should_skip_by_title(a.get("title", ""))]
    skipped_title = len(new_articles) - len(articles)
    if skipped_title:
        logger.info(f"Title filter skipped {skipped_title} articles")

    results = []
    story_counter = 0  # 批次内计数器，用于生成唯一 ID
    total_input_tokens = 0   # Token 用量累计
    total_output_tokens = 0

    # 延迟导入避免循环依赖（asn_scheduler 已导入本模块）
    from asn_scheduler import get_cancel_event

    for batch_start in range(0, len(articles), config.BATCH_SIZE):
        # 检查是否被用户取消
        if get_cancel_event().is_set():
            logger.info("AI processing cancelled by user")
            break

        batch = articles[batch_start:batch_start + config.BATCH_SIZE]
        user_prompt = _build_user_prompt(batch, existing_stories)

        try:
            # 调用 DeepSeek API（每批独立请求，避免长连接超时）
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.DEEPSEEK_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,  # 低温度保证输出稳定性
                        "max_tokens": 16384,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            # 累计 Token 用量（用于开销统计）
            usage = data.get("usage", {})
            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)

            content = data["choices"][0]["message"]["content"]
            finish_reason = data["choices"][0].get("finish_reason", "")
            if finish_reason == "length":
                logger.warning("AI response truncated, will attempt recovery")

            # 清理 Markdown 代码块标记（AI 有时会包裹 ```json ... ```）
            content = _strip_markdown_code_block(content)

            # 解析 JSON（失败则尝试从截断内容中恢复）
            ai_results = None
            try:
                ai_results = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("JSON parse failed, attempting recovery")
                ai_results = _try_recover_json(content)

            if ai_results is None:
                logger.error("Failed to parse AI response")
                continue

            # 兼容 AI 可能返回的包装格式
            if isinstance(ai_results, dict):
                ai_results = ai_results.get("results", ai_results.get("data", [ai_results]))

            # 处理每篇文章的结果
            for result in ai_results:
                idx = result.get("i", result.get("article_index", -1))
                if idx < 0 or idx >= len(batch):
                    continue

                article = batch[idx]
                is_aero = result.get("a", result.get("is_aerospace", False))
                if not is_aero:
                    continue  # AI 判定为非航天内容，跳过

                matched_story_id = result.get("s", result.get("story_id"))
                tags = result.get("t", result.get("tags", {}))
                summary = _clean_unicode(result.get("m", result.get("summary", "")))
                title_zh = _clean_unicode(result.get("tz", result.get("title_zh", "")))

                # 提取标签（国家/机构/领域）
                raw_c = tags.get("c", tags.get("countries", []))
                raw_o = tags.get("o", tags.get("organizations", []))
                raw_d = tags.get("d", tags.get("domains", []))
                countries = [_clean_unicode(t) for t in raw_c if _clean_unicode(t)]
                orgs = [_clean_unicode(t) for t in raw_o if _clean_unicode(t)]
                domains = [_clean_unicode(t) for t in raw_d if _clean_unicode(t)]

                processed = {
                    **article,
                    "title_zh": title_zh,
                    "summary": summary[:config.SUMMARY_MAX_LENGTH],
                    "tags": {"countries": countries, "organizations": orgs, "domains": domains},
                    "source_name": article.get("source", ""),
                }

                # 判断是归入已有故事还是创建新故事
                matched_str = str(matched_story_id) if matched_story_id is not None else ""
                if matched_str.startswith("故事ID_"):
                    # 归入已有故事（通过索引匹配）
                    try:
                        story_idx = int(matched_str.replace("故事ID_", ""))
                        processed["_match_story_index"] = story_idx
                    except ValueError:
                        processed["_match_story_index"] = None
                else:
                    # 创建新故事（生成唯一 ID：时间戳 + 批次内计数器）
                    story_id = f"story_{int(time.time())}_{story_counter}"
                    story_counter += 1
                    processed["_new_story"] = True
                    processed["_story_id"] = story_id

                results.append(processed)

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
        except httpx.HTTPError as e:
            logger.error(f"DeepSeek API error: {e}")
        except Exception as e:
            logger.error(f"AI processing error: {e}")

        # 批次间限流（避免触发 API 频率限制）
        if batch_start + config.BATCH_SIZE < len(articles):
            await asyncio.sleep(1)

    logger.info(f"AI: {len(results)}/{len(new_articles)} articles passed filter, tokens: {total_input_tokens}in/{total_output_tokens}out")
    return results, [], {"input_tokens": total_input_tokens, "output_tokens": total_output_tokens}


# ============================================================
# 补翻译：为缺少 title_zh 的已有故事批量翻译标题
# ============================================================
_TRANSLATE_SYSTEM_PROMPT = """你是标题翻译员。将以下英文新闻标题翻译为简洁准确的中文。
规则：
- 保留专有名词原文（如Starlink、SpaceX、NASA等）
- 翻译要自然通顺，符合中文新闻标题风格
- 只返回JSON数组，格式：[{"i":编号,"tz":"中文标题"}]
- 不要返回任何其他内容"""


async def translate_missing_titles(stories: list) -> tuple:
    """
    扫描所有故事，为缺少 title_zh 的批量发送 AI 翻译。
    返回 (updated_stories, token_usage)
    """
    # 收集缺少 title_zh 的故事
    missing = []
    for i, story in enumerate(stories):
        if not story.get("title_zh"):
            title = story.get("title", "")
            if title and any(c.isascii() and c.isalpha() for c in title):
                missing.append((i, title))

    if not missing:
        logger.info("No stories missing title_zh")
        return stories, {"input_tokens": 0, "output_tokens": 0}

    logger.info(f"Translating {len(missing)} missing titles...")
    total_input = 0
    total_output = 0
    success_count = 0

    # 延迟导入
    from asn_scheduler import get_cancel_event

    # 分批翻译（每批 30 条）
    TRANSLATE_BATCH = 30
    MAX_RETRIES = 2
    
    for batch_start in range(0, len(missing), TRANSLATE_BATCH):
        if get_cancel_event().is_set():
            break

        batch = missing[batch_start:batch_start + TRANSLATE_BATCH]
        titles_text = "\n".join(f'[{j}] {title}' for j, (_, title) in enumerate(batch))

        # 重试逻辑
        batch_success = False
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                logger.info(f"Retrying translation batch {batch_start // TRANSLATE_BATCH + 1} (attempt {attempt + 1})...")
                await asyncio.sleep(2)  # 重试前等待 2 秒
            
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": config.DEEPSEEK_MODEL,
                            "messages": [
                                {"role": "system", "content": _TRANSLATE_SYSTEM_PROMPT},
                                {"role": "user", "content": titles_text},
                            ],
                            "temperature": 0.2,
                            "max_tokens": 4096,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                usage = data.get("usage", {})
                batch_input = usage.get("prompt_tokens", 0)
                batch_output = usage.get("completion_tokens", 0)
                total_input += batch_input
                total_output += batch_output

                content = _strip_markdown_code_block(data["choices"][0]["message"]["content"])

                results = json.loads(content)
                if isinstance(results, dict):
                    results = results.get("results", results.get("data", []))

                for item in results:
                    idx = item.get("i", -1)
                    tz = _clean_unicode(item.get("tz", ""))
                    if 0 <= idx < len(batch) and tz:
                        story_idx = batch[idx][0]
                        stories[story_idx]["title_zh"] = tz
                
                batch_success = True
                success_count += 1
                logger.info(f"Translation batch {batch_start // TRANSLATE_BATCH + 1} succeeded: {batch_input}+{batch_output} tokens")
                break  # 成功后退出重试循环

            except httpx.HTTPError as e:
                logger.warning(f"Translation batch {batch_start // TRANSLATE_BATCH + 1} HTTP error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRIES:
                    logger.error(f"Translation batch {batch_start // TRANSLATE_BATCH + 1} failed after {MAX_RETRIES + 1} attempts")
            except Exception as e:
                logger.error(f"Translation batch {batch_start // TRANSLATE_BATCH + 1} failed: {e}")
                break  # 非 HTTP 错误不重试
        
        # 批次间限流（仅在还有下一批时）
        if batch_start + TRANSLATE_BATCH < len(missing):
            await asyncio.sleep(0.5)

    translated = sum(1 for story_idx, _ in missing if stories[story_idx].get("title_zh"))
    logger.info(f"Translated {translated}/{len(missing)} titles ({success_count} batches), tokens: {total_input}in/{total_output}out")
    return stories, {"input_tokens": total_input, "output_tokens": total_output}
