"""
AutoSpaceNews (ASN) - 主程序
FastAPI 服务 + 定时调度 + 系统托盘
提供 Web API 供前端调用，系统托盘图标供用户快捷操作
"""
import asyncio
import json
import logging
import os
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

import asn_config as config
from asn_scheduler import run_update, start_scheduler, stop_scheduler, get_status, update_interval, cancel_update
from asn_storage import load_news, get_paginated
import asn_token_tracker as token_tracker

# ============================================================
# 日志配置
# 同时输出到控制台和日志文件（asn.log）
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "asn.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
# FastAPI 应用生命周期
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的钩子"""
    logger.info("ASN starting...")
    token_tracker.init_tracker()
    # 加载用户设置（恢复上次保存的更新间隔）
    settings = _load_settings()
    if settings.get("interval"):
        config.FETCH_INTERVAL_MINUTES = int(settings["interval"])
    start_scheduler()
    # 不自动更新新闻，仅加载已有数据；用户点击刷新按钮才触发更新
    # 延迟 1.5 秒打开浏览器（等待服务器完全启动）
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{config.PORT}")).start()
    yield
    stop_scheduler()
    logger.info("ASN stopped")


app = FastAPI(title="AutoSpaceNews", lifespan=lifespan)


# ============================================================
# Web 路由
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端页面（static/index.html）"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/api/news")
async def api_news(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    search: str = Query("", max_length=200),
):
    """获取新闻列表（支持分页和搜索）"""
    stories = load_news()
    result = get_paginated(stories, page=page, page_size=page_size, search=search)
    return JSONResponse(content=result)


@app.post("/api/update")
async def api_update():
    """手动触发更新（检查 API 密钥后启动异步更新任务）"""
    # 检查 API 密钥是否已配置
    if not config.has_api_key():
        return JSONResponse(
            content={"message": "请先配置API密钥", "status": "no_key"},
            status_code=400,
        )
    status = get_status()
    if status["is_running"]:
        return JSONResponse(
            content={"message": "更新正在进行中", "status": "running"},
            status_code=202,
        )
    # 异步执行更新（不阻塞响应），标记为手动刷新
    asyncio.create_task(run_update(operation_type="manual_refresh"))
    return JSONResponse(content={"message": "更新已启动", "status": "started"})


@app.post("/api/cancel")
async def api_cancel():
    """中止当前正在执行的更新任务"""
    msg = cancel_update()
    return JSONResponse(content={"message": msg, "ok": True})


@app.get("/api/status")
async def api_status():
    """获取当前状态（更新中/完成/错误）和新闻总数"""
    status = get_status()
    stories = load_news()
    status["total_stories"] = len(stories)
    status["has_key"] = config.has_api_key()
    return JSONResponse(content=status)


# ============================================================
# API 密钥管理
# ============================================================
@app.get("/api/key/check")
async def check_key():
    """检查 API 密钥是否已配置（前端用于决定是否弹出输入框）"""
    return JSONResponse(content={"has_key": config.has_api_key()})


@app.post("/api/key/save")
async def save_key(data: dict):
    """保存用户提交的 API 密钥（验证格式后写入文件）"""
    key = data.get("key", "").strip()
    if not key:
        return JSONResponse(content={"ok": False, "message": "密钥不能为空"})
    if not key.startswith("sk-"):
        return JSONResponse(content={"ok": False, "message": "密钥格式不正确（应以 sk- 开头）"})
    ok = config.save_api_key(key)
    if ok:
        return JSONResponse(content={"ok": True, "message": "密钥已保存"})
    return JSONResponse(content={"ok": False, "message": "保存失败，请检查文件权限"})


# ============================================================
# 注销 & API 开销
# ============================================================
@app.post("/api/logout")
async def logout():
    """
    注销：清空 API 密钥、新闻数据、Token 开销记录、用户设置，还原到初始状态
    下次打开程序需要重新输入 API 密钥
    """
    errors = []

    # 1. 删除 API 密钥文件并清除内存缓存
    try:
        if os.path.exists(config._KEY_FILE):
            os.remove(config._KEY_FILE)
        config.clear_key_cache()
    except Exception as e:
        errors.append(f"清除密钥失败: {e}")

    # 2. 删除新闻数据文件
    try:
        if os.path.exists(config.NEWS_FILE):
            os.remove(config.NEWS_FILE)
    except Exception as e:
        errors.append(f"清除新闻数据失败: {e}")

    # 3. 重置 Token 开销追踪
    token_tracker.reset()

    # 4. 删除用户设置文件（恢复默认主题和间隔）
    try:
        settings_file = os.path.join(config.DATA_DIR, "settings.json")
        if os.path.exists(settings_file):
            os.remove(settings_file)
    except Exception as e:
        errors.append(f"清除设置失败: {e}")

    if errors:
        logger.warning(f"Logout completed with errors: {errors}")
        return JSONResponse(content={"ok": False, "message": "; ".join(errors)})

    logger.info("Logout complete: all data cleared")
    return JSONResponse(content={"ok": True, "message": "已注销，所有数据已清空"})


@app.get("/api/costs")
async def api_costs():
    """获取 API 开销统计（Token 用量和费用估算）"""
    return JSONResponse(content=token_tracker.get_stats())


# ============================================================
# 强制去重
# ============================================================
@app.post("/api/dedup")
async def api_force_dedup(data: dict = {}):
    """
    强制执行去重 + 内容过滤：清理现有数据中的重复故事和不相关内容
    
    参数:
        re_filter (bool): 是否重新运行 AI 过滤（默认 False，仅去重）
                         True 时会消耗 API token，用于删除"On this day"、天文观测等不相关内容
    """
    from asn_storage import load_news, save_news, dedup_stories
    from asn_ai import _should_skip_by_title
    
    re_filter = data.get("re_filter", False)
    
    stories = load_news()
    before_count = len(stories)
    
    if before_count == 0:
        return JSONResponse(content={
            "removed": 0,
            "remaining": 0,
            "filtered_out": 0,
            "message": "没有新闻数据"
        })
    
    # 步骤 1: 如果启用重新过滤，先过滤掉明显不相关的内容
    filtered_out = 0
    if re_filter:
        # 基于标题快速过滤（不消耗 API）
        filtered_stories = []
        for story in stories:
            title = story.get("title", "")
            if not _should_skip_by_title(title):
                filtered_stories.append(story)
            else:
                filtered_out += 1
        
        logger.info(f"Re-filter: filtered out {filtered_out} stories by title rules")
        stories = filtered_stories
    
    # 步骤 2: 执行去重（包含标题和摘要相似度检查）
    deduped = dedup_stories(stories)
    
    # 步骤 3: 为缺少中文标题的故事补翻译
    from asn_ai import translate_missing_titles
    
    translated, translate_usage = await translate_missing_titles(deduped)
    
    # 记录翻译的 Token 开销（如果有）
    if translate_usage.get("input_tokens", 0) > 0 or translate_usage.get("output_tokens", 0) > 0:
        token_tracker.record_usage(
            translate_usage["input_tokens"],
            translate_usage["output_tokens"],
            duration_seconds=0,
            story_count=len(translated),
            operation_type="dedup_filter",
        )
        logger.info(f"Dedup translation cost recorded: {translate_usage['input_tokens']}+{translate_usage['output_tokens']} tokens")
    
    after_count = len(translated)
    removed = before_count - after_count - filtered_out
    
    # 保存去重后的数据
    save_news(translated)
    
    # 更新当前显示的故事数
    token_tracker.set_current_displayed_stories(after_count)
    
    total_removed = removed + filtered_out
    message_parts = []
    if filtered_out > 0:
        message_parts.append(f"过滤了 {filtered_out} 条不相关内容")
    if removed > 0:
        message_parts.append(f"合并了 {removed} 条重复故事")
    
    message = "，".join(message_parts) if message_parts else "无变更"
    message += f"，剩余 {after_count} 条"
    
    logger.info(f"Force dedup: {before_count} -> {after_count} (filtered={filtered_out}, merged={removed})")
    
    return JSONResponse(content={
        "removed": removed,
        "filtered_out": filtered_out,
        "remaining": after_count,
        "total_removed": total_removed,
        "message": message
    })


# ============================================================
# 定价管理
# ============================================================
@app.get("/api/pricing")
async def api_get_pricing():
    """获取当前 DeepSeek 定价信息"""
    return JSONResponse(content=token_tracker.get_pricing())


@app.post("/api/pricing")
async def api_update_pricing(data: dict):
    """手动更新 DeepSeek 定价（单位：元/百万Token）"""
    input_price = data.get("input_price")
    output_price = data.get("output_price")
    if input_price is None or output_price is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing input_price or output_price"}
        )
    success = token_tracker.update_pricing(
        float(input_price),
        float(output_price),
        source="manual"
    )
    if success:
        return JSONResponse(content={"ok": True, "message": "定价已更新"})
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "无效的定价数值"}
        )


# ============================================================
# 用户设置（主题、更新间隔等）
# ============================================================
_SETTINGS_FILE = os.path.join(config.DATA_DIR, "settings.json")


def _load_settings() -> dict:
    """从 data/settings.json 读取用户设置"""
    try:
        if os.path.exists(_SETTINGS_FILE):
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"theme": "dark", "interval": config.FETCH_INTERVAL_MINUTES}


def _save_settings(settings: dict):
    """将用户设置写入 data/settings.json"""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


@app.get("/api/settings")
async def get_settings():
    """获取用户设置（主题、更新间隔等）"""
    return JSONResponse(content=_load_settings())


@app.post("/api/settings")
async def save_settings(data: dict):
    """保存用户设置，并在间隔变更时动态更新调度器"""
    import json as _json
    current = _load_settings()
    current.update(data)
    _save_settings(current)

    # 如果更新了更新间隔，动态调整调度器
    interval = data.get("interval")
    if interval:
        interval = int(interval)
        if interval != config.FETCH_INTERVAL_MINUTES:
            update_interval(interval)

    return JSONResponse(content={"ok": True})


# ============================================================
# 系统托盘
# ============================================================
def _create_tray_icon():
    try:
        from PIL import Image, ImageDraw
        import pystray

        img = Image.new("RGBA", (64, 64), (30, 60, 114, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([24, 16, 40, 48], fill="white")
        draw.polygon([(32, 6), (24, 16), (40, 16)], fill="white")
        draw.polygon([(26, 48), (32, 58), (38, 48)], fill=(255, 165, 0, 255))
        draw.ellipse([28, 24, 36, 32], fill=(30, 60, 114, 255))

        def on_open(icon, item):
            webbrowser.open(f"http://localhost:{config.PORT}")

        def on_update(icon, item):
            import httpx as _httpx
            try:
                _httpx.post(f"http://localhost:{config.PORT}/api/update", timeout=5)
            except Exception:
                pass

        def on_quit(icon, item):
            icon.stop()
            sys.exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("打开浏览器", on_open, default=True),
            pystray.MenuItem("手动更新", on_update),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        )
        return pystray.Icon("asn", img, "AutoSpaceNews", menu)
    except ImportError:
        logger.warning("pystray/Pillow not installed, tray disabled")
        return None


def _run_tray():
    icon = _create_tray_icon()
    if icon:
        try:
            icon.run()
        except Exception as e:
            logger.error(f"Tray error: {e}")


# ============================================================
# 入口
# ============================================================
def main():
    print("=" * 50)
    print("  AutoSpaceNews (ASN)")
    print(f"  http://localhost:{config.PORT}")
    print(f"  Interval: {config.FETCH_INTERVAL_MINUTES} min")
    if not config.has_api_key():
        print("  [!] API key not configured - will prompt in web UI")
    print("=" * 50)

    tray_thread = threading.Thread(target=_run_tray, daemon=True)
    tray_thread.start()

    uvicorn.run(
        "asn_main:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
