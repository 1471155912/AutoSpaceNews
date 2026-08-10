"""
AutoSpaceNews (ASN) - Token 开销追踪模块
记录每次刷新的 Token 用量和费用估算，支持：
- 会话级累计统计（自登录/启动以来）
- 最近一次刷新详情
- 平均值计算
- 持久化到 data/token_usage.json（进程重启后保留）
注销时调用 reset() 清空所有记录
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List

import asn_config as config

logger = logging.getLogger(__name__)

# ============================================================
# DeepSeek V4 Flash 定价（单位：元/百万Token）
# 默认值：输入 ¥1/M，输出 ¥2/M（2026-08 最新）
# 可通过 /api/pricing 端点动态更新，每日首次更新时自动查询
# ============================================================
DEFAULT_INPUT_PRICE = 1.0
DEFAULT_OUTPUT_PRICE = 2.0

# 运行时定价（可从 API 动态更新）
_input_price = DEFAULT_INPUT_PRICE
_output_price = DEFAULT_OUTPUT_PRICE
_last_pricing_date = ""  # 最后更新定价的日期 (YYYY-MM-DD)

# 持久化文件路径
_USAGE_FILE = os.path.join(config.DATA_DIR, "token_usage.json")

# ============================================================
# 内存状态
# ============================================================
_session_data: Dict = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cost": 0.0,
    "refresh_count": 0,           # 手动+自动刷新次数（不包括去重/过滤）
    "last_update_time": "",
    "last_input_tokens": 0,
    "last_output_tokens": 0,
    "last_cost": 0.0,
    "last_duration_seconds": 0.0,
    "last_story_count": 0,
    "total_duration_seconds": 0.0,
    "total_story_count": 0,       # 累计处理的故事数（所有API操作）
    "login_time": "",             # 本次登录时间（会话级，不持久化）
    "history": [],                # 每次刷新的记录列表
    
    # 新增：区分刷新类型
    "manual_refresh_count": 0,    # 手动刷新次数
    "auto_refresh_count": 0,      # 自动刷新次数
    "dedup_filter_count": 0,      # 去重/过滤操作次数
    
    # 新增：当前显示的故事数（用于计算"累计/显示"格式）
    "current_displayed_stories": 0,
}

_loaded_from_file = False   # 标记是否已从文件恢复


def _ensure_dir():
    """确保 data/ 目录存在"""
    os.makedirs(config.DATA_DIR, exist_ok=True)


def _calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """根据 Token 数量和当前定价计算费用（元）"""
    global _input_price, _output_price
    return (input_tokens * _input_price + output_tokens * _output_price) / 1_000_000


def get_pricing() -> Dict:
    """获取当前定价信息"""
    return {
        "input_price_per_million": _input_price,
        "output_price_per_million": _output_price,
        "last_updated": _last_pricing_date,
    }


def update_pricing(input_price: float, output_price: float, source: str = "manual") -> bool:
    """
    更新定价并持久化
    source: "manual"（手动）或 "auto"（自动查询）
    """
    global _input_price, _output_price, _last_pricing_date
    try:
        _input_price = float(input_price)
        _output_price = float(output_price)
        _last_pricing_date = datetime.now().strftime("%Y-%m-%d")
        _save_pricing_to_file()
        logger.info(f"Pricing updated ({source}): input=¥{_input_price}/M, output=¥{_output_price}/M")
        return True
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid pricing values: {e}")
        return False


def should_update_pricing() -> bool:
    """检查是否需要更新定价（每天首次更新时）"""
    today = datetime.now().strftime("%Y-%m-%d")
    return _last_pricing_date != today


async def fetch_and_update_pricing() -> bool:
    """
    从 DeepSeek 官方渠道获取最新定价并更新
    由于定价页面是 JS 渲染的，目前采用硬编码默认值
    未来可通过浏览器自动化或 API 端点获取
    """
    # 当前 DeepSeek V4 Flash 定价（2026-08 最新）
    # 输入 ¥1/M tokens，输出 ¥2/M tokens
    # 如果未来需要实时抓取，可使用 builtin_browser MCP 工具
    today = datetime.now().strftime("%Y-%m-%d")
    if _last_pricing_date == today:
        logger.info("Pricing already updated today, skip")
        return True

    # 使用已知最新价格更新
    return update_pricing(DEFAULT_INPUT_PRICE, DEFAULT_OUTPUT_PRICE, source="auto")


def _save_pricing_to_file():
    """将定价信息追加到 token_usage.json"""
    _ensure_dir()
    try:
        data = {}
        if os.path.exists(_USAGE_FILE):
            with open(_USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["pricing"] = {
            "input_price_per_million": _input_price,
            "output_price_per_million": _output_price,
            "last_updated": _last_pricing_date,
        }
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to save pricing: {e}")


def _load_pricing_from_file():
    """从文件恢复定价信息"""
    global _input_price, _output_price, _last_pricing_date
    if not os.path.exists(_USAGE_FILE):
        return
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "pricing" in data:
            pricing = data["pricing"]
            _input_price = pricing.get("input_price_per_million", DEFAULT_INPUT_PRICE)
            _output_price = pricing.get("output_price_per_million", DEFAULT_OUTPUT_PRICE)
            _last_pricing_date = pricing.get("last_updated", "")
            logger.info(f"Pricing loaded: input=¥{_input_price}/M, output=¥{_output_price}/M, last={_last_pricing_date}")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load pricing: {e}")


def _save_to_file():
    """将累计数据持久化到 JSON 文件"""
    _ensure_dir()
    try:
        data = {
            "total_input_tokens": _session_data["total_input_tokens"],
            "total_output_tokens": _session_data["total_output_tokens"],
            "total_cost": _session_data["total_cost"],
            "refresh_count": _session_data["refresh_count"],
            "last_update_time": _session_data["last_update_time"],
            "last_input_tokens": _session_data["last_input_tokens"],
            "last_output_tokens": _session_data["last_output_tokens"],
            "last_cost": _session_data["last_cost"],
            "last_duration_seconds": _session_data["last_duration_seconds"],
            "last_story_count": _session_data["last_story_count"],
            "total_duration_seconds": _session_data["total_duration_seconds"],
            "total_story_count": _session_data["total_story_count"],
            "manual_refresh_count": _session_data["manual_refresh_count"],
            "auto_refresh_count": _session_data["auto_refresh_count"],
            "dedup_filter_count": _session_data["dedup_filter_count"],
            "current_displayed_stories": _session_data["current_displayed_stories"],
            "history": _session_data["history"][-100:],  # 只保留最近100条
        }
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.warning(f"Failed to save token usage: {e}")


def _load_from_file():
    """从文件恢复上次的累计数据（进程重启时调用）"""
    global _loaded_from_file
    if not os.path.exists(_USAGE_FILE):
        return
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in ("total_input_tokens", "total_output_tokens", "total_cost",
                     "refresh_count", "last_update_time", "last_input_tokens",
                     "last_output_tokens", "last_cost", "last_duration_seconds",
                     "last_story_count", "total_duration_seconds", "total_story_count",
                     "manual_refresh_count", "auto_refresh_count", "dedup_filter_count",
                     "current_displayed_stories"):
            if key in data:
                _session_data[key] = data[key]
        if "history" in data and isinstance(data["history"], list):
            _session_data["history"] = data["history"]
        _loaded_from_file = True
        logger.info(f"Token usage restored: {_session_data['refresh_count']} records, "
                     f"{_session_data['total_input_tokens'] + _session_data['total_output_tokens']} total tokens")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load token usage: {e}")


def init_tracker():
    """
    初始化追踪器（程序启动时调用一次）
    从文件恢复历史数据和定价信息，设置登录时间
    """
    _load_from_file()
    _load_pricing_from_file()
    if not _session_data["login_time"]:
        _session_data["login_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_usage(input_tokens: int, output_tokens: int, duration_seconds: float = 0.0, 
                 story_count: int = 0, operation_type: str = "auto_refresh"):
    """
    记录一次 API 调用的 Token 用量、耗时和故事数量
    自动计算费用并更新累计统计
    
    参数:
        operation_type: 操作类型，可选值：
            - "manual_refresh": 手动刷新
            - "auto_refresh": 自动刷新（定时任务）
            - "dedup_filter": 去重/过滤操作
            - "translation": 纯翻译操作
    """
    cost = _calculate_cost(input_tokens, output_tokens)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 更新累计值
    _session_data["total_input_tokens"] += input_tokens
    _session_data["total_output_tokens"] += output_tokens
    _session_data["total_cost"] += cost
    _session_data["total_duration_seconds"] += duration_seconds
    _session_data["total_story_count"] += story_count
    
    # 根据操作类型更新对应的计数器
    if operation_type in ("manual_refresh", "auto_refresh"):
        _session_data["refresh_count"] += 1
        if operation_type == "manual_refresh":
            _session_data["manual_refresh_count"] += 1
        else:
            _session_data["auto_refresh_count"] += 1
    elif operation_type == "dedup_filter":
        _session_data["dedup_filter_count"] += 1

    # 更新最近一次记录
    _session_data["last_update_time"] = now_str
    _session_data["last_input_tokens"] = input_tokens
    _session_data["last_output_tokens"] = output_tokens
    _session_data["last_cost"] = cost
    _session_data["last_duration_seconds"] = duration_seconds
    _session_data["last_story_count"] = story_count

    # 追加历史记录（包含操作类型）
    _session_data["history"].append({
        "time": now_str,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost": round(cost, 6),
        "duration_seconds": duration_seconds,
        "story_count": story_count,
        "operation_type": operation_type,
    })

    # 持久化
    _save_to_file()
    logger.info(f"Token usage recorded ({operation_type}): {input_tokens}+{output_tokens}={input_tokens+output_tokens} tokens, "
                f"¥{cost:.4f}, {duration_seconds:.1f}s, {story_count} stories")


def get_stats() -> Dict:
    """
    获取开销统计（供 API 返回给前端）
    返回：最近一次、累计总量、平均值（含耗时和故事数量）
    """
    total_tokens = _session_data["total_input_tokens"] + _session_data["total_output_tokens"]
    count = _session_data["refresh_count"]
    total_dur = _session_data["total_duration_seconds"]
    last_dur = _session_data["last_duration_seconds"]
    total_stories = _session_data["total_story_count"]
    last_stories = _session_data["last_story_count"]

    return {
        "last": {
            "time": _session_data["last_update_time"],
            "input_tokens": _session_data["last_input_tokens"],
            "output_tokens": _session_data["last_output_tokens"],
            "total_tokens": _session_data["last_input_tokens"] + _session_data["last_output_tokens"],
            "cost": round(_session_data["last_cost"], 4),
            "duration_seconds": last_dur,
            "story_count": last_stories,
        },
        "total": {
            "input_tokens": _session_data["total_input_tokens"],
            "output_tokens": _session_data["total_output_tokens"],
            "total_tokens": total_tokens,
            "cost": round(_session_data["total_cost"], 4),
            "refresh_count": count,
            "manual_refresh_count": _session_data["manual_refresh_count"],
            "auto_refresh_count": _session_data["auto_refresh_count"],
            "dedup_filter_count": _session_data["dedup_filter_count"],
            "total_duration_seconds": total_dur,
            "total_story_count": total_stories,
            "current_displayed_stories": _session_data["current_displayed_stories"],
        },
        "average": {
            "input_tokens": round(_session_data["total_input_tokens"] / count) if count else 0,
            "output_tokens": round(_session_data["total_output_tokens"] / count) if count else 0,
            "total_tokens": round(total_tokens / count) if count else 0,
            "cost": round(_session_data["total_cost"] / count, 4) if count else 0,
            "duration_seconds": round(total_dur / count, 1) if count else 0,
            "story_count": round(total_stories / count) if count else 0,
        },
        "history": _session_data["history"][-100:],
        "login_time": _session_data["login_time"],
    }


def reset():
    """
    重置所有追踪数据（注销时调用）
    同时删除持久化文件
    """
    for key in _session_data:
        if key == "history":
            _session_data[key] = []
        elif isinstance(_session_data[key], (int, float)):
            _session_data[key] = 0
        else:
            _session_data[key] = ""
    # 删除持久化文件
    try:
        if os.path.exists(_USAGE_FILE):
            os.remove(_USAGE_FILE)
    except IOError:
        pass
    logger.info("Token usage tracker reset")


def set_current_displayed_stories(count: int):
    """
    更新当前显示的故事数（用于前端显示"累计XXX条/显示XX条"格式）
    在每次刷新或去重操作完成后调用
    """
    _session_data["current_displayed_stories"] = count
    _save_to_file()
    logger.info(f"Current displayed stories updated: {count}")
