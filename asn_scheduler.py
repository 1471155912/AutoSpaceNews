"""
AutoSpaceNews (ASN) - 定时调度器
每 2 小时自动执行数据抓取 + AI 处理
管理更新状态、错误信息，供 API 查询
"""
import asyncio
import logging
import threading
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import asn_config as config
from asn_fetchers import asn_rss, asn_bidding, asn_snapi, asn_sina
from asn_ai import process_articles, translate_missing_titles
from asn_storage import load_news, save_news, cleanup_old_news, merge_new_results, dedup_stories, calculate_title_similarity
import asn_token_tracker as token_tracker

logger = logging.getLogger(__name__)

# 调度器实例（全局单例）
_scheduler = None
# 更新状态标志
_is_running = False
_last_update = ""
_last_error = ""
_refresh_start_time = ""   # 本次刷新开始时间（年月日时分秒）
_new_count = 0             # 本次刷新新增条数
_duration_seconds = 0.0    # 本次刷新耗时（秒）

# 取消事件（前端请求中止时 set，AI 处理循环中检查）
_cancel_event = threading.Event()


def get_latest_news_timestamp(stories: list) -> str:
    """
    获取已有新闻中最新的发布时间戳
    返回格式：ISO 8601 字符串（如 "2026-08-09T12:00:00Z"）
    用于后续抓取时过滤掉旧新闻
    """
    latest = ""
    for story in stories:
        # 检查故事级别的 published_at
        pub_time = story.get("published_at", "")
        if pub_time and pub_time > latest:
            latest = pub_time
        # 检查来源级别的 published_at（每个来源可能有不同时间）
        for source in story.get("sources", []):
            src_time = source.get("published_at", "")
            if src_time and src_time > latest:
                latest = src_time
    return latest


async def fetch_all_sources() -> list:
    """
    从所有数据源并发抓取文章
    使用 asyncio.gather 并行执行 RSS 和招投标抓取，提升速度
    不再使用 since_time 过滤，改由标题相似度去重
    """
    all_articles = []

    # 并发执行所有抓取任务（即使某个失败也不影响其他）
    tasks = [
        ("RSS", asn_rss.fetch()),
        ("Bidding", asn_bidding.fetch()),
        ("SpaceflightNewsAPI", asn_snapi.fetch()),
        ("SinaTech", asn_sina.fetch()),
    ]

    results = await asyncio.gather(
        *[task for _, task in tasks],
        return_exceptions=True
    )

    for (name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.error(f"[{name}] failed: {result}")
        else:
            articles = result
            all_articles.extend(articles)
            logger.info(f"[{name}] {len(articles)} articles")

    # 全局 URL 去重（不同源可能报道同一事件）
    seen = set()
    unique = []
    for a in all_articles:
        key = a.get("url") or a.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(a)
        elif not key:
            unique.append(a)

    logger.info(f"Total: {len(unique)} unique articles")
    return unique


def filter_duplicate_titles(new_articles: list, existing_stories: list, threshold: float = 0.85) -> list:
    """
    通过标题相似度过滤掉与已有故事重复的文章
    避免将已处理过的新闻再次送入 AI 处理，节省 API 调用
    
    参数:
        new_articles: 新抓取的文章列表
        existing_stories: 已有的故事列表
        threshold: 相似度阈值，>= 此值视为重复（默认 0.85）
    
    返回:
        过滤后的新文章列表（只保留不重复的）
    """
    if not existing_stories:
        return new_articles
    
    # 收集已有故事的标题（英文和中文）
    existing_titles = []
    for story in existing_stories:
        title_en = story.get("title", "")
        title_zh = story.get("title_zh", "")
        if title_en:
            existing_titles.append(title_en)
        if title_zh:
            existing_titles.append(title_zh)
    
    filtered = []
    duplicate_count = 0
    
    for article in new_articles:
        article_title = article.get("title", "")
        if not article_title:
            filtered.append(article)
            continue
        
        # 检查是否与任何已有标题相似
        is_duplicate = False
        for existing_title in existing_titles:
            sim = calculate_title_similarity(article_title, existing_title)
            if sim >= threshold:
                is_duplicate = True
                break
        
        if is_duplicate:
            duplicate_count += 1
        else:
            filtered.append(article)
    
    if duplicate_count > 0:
        logger.info(f"Title similarity filter: {duplicate_count} duplicates removed, {len(filtered)} new articles kept")
    
    return filtered


async def run_update(operation_type: str = "auto_refresh"):
    """
    执行一次完整更新流程：
    1. 抓取所有数据源
    2. AI 处理（过滤/摘要/标签/去重）
    3. 合并到已有数据
    4. 清理过期数据
    5. 保存到文件
    
    参数:
        operation_type: "auto_refresh"（定时任务）或 "manual_refresh"（手动触发）
    """
    global _is_running, _last_update, _last_error, _duration_seconds

    # 防止并发更新（用户快速点击刷新时）
    if _is_running:
        logger.warning("Update already running, skip")
        return

    # 检查 API 密钥
    if not config.has_api_key():
        logger.warning("No API key configured, skipping update")
        _last_update = "未配置API密钥"
        return

    # 每日首次更新时查询最新定价
    if token_tracker.should_update_pricing():
        logger.info("First update of the day: checking latest DeepSeek pricing")
        await token_tracker.fetch_and_update_pricing()

    _is_running = True
    _last_error = ""
    _cancel_event.clear()
    _refresh_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _new_count = 0
    _start_ts = time.time()

    try:
        logger.info("=== Update cycle start ===")

        # 1. 加载已有新闻
        existing_stories = load_news()

        # 2. 抓取所有数据源（不再使用时间过滤）
        new_articles = await fetch_all_sources()
        if not new_articles:
            logger.info("No articles fetched")
            _last_update = "完成（无数据）"
            _duration_seconds = time.time() - _start_ts
            # 记录刷新操作（即使没有新数据，也计入刷新次数）
            token_tracker.record_usage(
                0, 0,
                duration_seconds=round(_duration_seconds, 1),
                story_count=len(existing_stories),
                operation_type=operation_type,
            )
            # 更新当前显示的故事数（保持不变）
            token_tracker.set_current_displayed_stories(len(existing_stories))
            return

        # 2.5 通过标题相似度过滤掉与已有故事重复的文章
        new_articles = filter_duplicate_titles(new_articles, existing_stories)
        if not new_articles:
            logger.info("All fetched articles are duplicates of existing stories")
            _last_update = "完成（无新内容）"
            _duration_seconds = time.time() - _start_ts
            token_tracker.record_usage(
                0, 0,
                duration_seconds=round(_duration_seconds, 1),
                story_count=len(existing_stories),
                operation_type=operation_type,
            )
            token_tracker.set_current_displayed_stories(len(existing_stories))
            return

        # 3. AI 处理
        old_count = len(existing_stories)
        processed, _, token_usage = await process_articles(new_articles, existing_stories)

        if not processed:
            logger.info("No articles passed filter")
            _last_update = "完成（无相关新闻）"
            _duration_seconds = time.time() - _start_ts
            # 记录刷新操作（使用实际API token消耗，即使没有通过过滤的文章）
            token_tracker.record_usage(
                token_usage["input_tokens"],
                token_usage["output_tokens"],
                duration_seconds=round(_duration_seconds, 1),
                story_count=len(existing_stories),
                operation_type=operation_type,
            )
            # 更新当前显示的故事数（保持不变）
            token_tracker.set_current_displayed_stories(len(existing_stories))
            return

        # 4. 合并（新文章归入已有故事或创建新故事）
        merged = merge_new_results(existing_stories, processed)

        # 4.5 去重（合并标题高度相似的故事）
        deduped = dedup_stories(merged)

        # 5. 清理过期数据（超过 MAX_DAYS_TO_KEEP 天）
        cleaned = cleanup_old_news(deduped)

        # 5.5 补翻译：为缺少中文标题的已有故事批量翻译
        cleaned, translate_usage = await translate_missing_titles(cleaned)
        token_usage["input_tokens"] += translate_usage["input_tokens"]
        token_usage["output_tokens"] += translate_usage["output_tokens"]

        # 6. 保存
        save_news(cleaned)

        # 7. 记录 Token 开销（含耗时和故事数量）
        _duration_seconds = time.time() - _start_ts
        token_tracker.record_usage(
            token_usage["input_tokens"],
            token_usage["output_tokens"],
            duration_seconds=round(_duration_seconds, 1),
            story_count=len(cleaned),
            operation_type=operation_type,
        )
        
        # 更新当前显示的故事数
        token_tracker.set_current_displayed_stories(len(cleaned))

        _new_count = len(cleaned) - old_count
        if _new_count < 0:
            _new_count = 0
        _last_update = f"完成，共 {len(cleaned)} 条"
        logger.info(f"=== Update done: {len(cleaned)} stories ({_new_count} new) in {_duration_seconds:.1f}s ===")

    except Exception as e:
        _last_error = str(e)
        _duration_seconds = time.time() - _start_ts
        logger.error(f"Update failed: {e}", exc_info=True)
    finally:
        _is_running = False


def get_status() -> dict:
    """获取当前更新状态（供 API 查询）"""
    return {
        "is_running": _is_running,
        "last_update": _last_update,
        "last_error": _last_error,
        "refresh_start_time": _refresh_start_time,
        "new_count": _new_count,
        "duration_seconds": round(_duration_seconds, 1),
    }


def cancel_update() -> str:
    """
    中止当前正在执行的更新任务
    设置 _cancel_event，AI 处理循环检测到后会提前退出
    返回描述性消息
    """
    if not _is_running:
        return "当前没有正在执行的更新任务"
    _cancel_event.set()
    logger.info("Cancel requested by user")
    return "已发送中止信号，正在停止..."


def get_cancel_event() -> threading.Event:
    """获取取消事件对象（供 asn_ai.py 轮询检查）"""
    return _cancel_event


def start_scheduler():
    """启动定时调度器（每 FETCH_INTERVAL_MINUTES 分钟执行一次）"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_update,
        "interval",
        minutes=config.FETCH_INTERVAL_MINUTES,
        id="asn_update",
        name="ASN定时更新",
        max_instances=1,  # 同一时刻最多一个实例运行
        coalesce=True,    # 合并错过的执行（如系统休眠后）
    )
    _scheduler.start()
    logger.info(f"Scheduler started: every {config.FETCH_INTERVAL_MINUTES} min")


def stop_scheduler():
    """停止定时调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def update_interval(minutes: int):
    """动态更新调度器的执行间隔"""
    global _scheduler
    if _scheduler and _scheduler.running:
        try:
            _scheduler.reschedule_job(
                "asn_update",
                trigger="interval",
                minutes=minutes,
            )
            config.FETCH_INTERVAL_MINUTES = minutes
            logger.info(f"Scheduler interval updated to {minutes} min")
            return True
        except Exception as e:
            logger.error(f"Failed to update interval: {e}")
            return False
    return False
