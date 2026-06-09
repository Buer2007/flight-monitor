"""Web 面板 — FastAPI 应用

提供 REST API 和静态页面，让用户能：
- 查看/添加/删除监控航班
- 手动触发查询
- 查看历史告警与查询记录
- 浏览机场列表
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config_loader import (
    BASE_DIR,
    load_config_from,
    save_config,
)
from monitor.airports import get_airports, search_airports
from monitor.checker import FlightChecker
from monitor.flight import CtripClient, FlightInfo
from notifier.feishu import FeishuNotifier
from storage.history import HistoryStore
from storage.state import StateStore

logger = logging.getLogger(__name__)

# Web 面板静态文件目录
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
CONFIG_PATH = BASE_DIR / "config.yaml"

# 这些对象在 startup 阶段由 main.py 注入
# （避免 FastAPI 自行初始化业务对象）
_runtime: dict[str, Any] = {}


def init_runtime(
    client: CtripClient,
    checker: FlightChecker,
    notifier: FeishuNotifier,
    state: StateStore,
    history: HistoryStore,
) -> None:
    """由 main.py 在启动时注入运行时对象"""
    _runtime.update(
        client=client,
        checker=checker,
        notifier=notifier,
        state=state,
        history=history,
    )


def get_runtime() -> dict[str, Any]:
    if not _runtime:
        raise RuntimeError("Web runtime 未初始化，请通过 main.py 启动")
    return _runtime


# ── FastAPI 应用 ──
app = FastAPI(title="机票监控面板", version="2.0.0")


# ── Pydantic 模型 ──
class FlightConfig(BaseModel):
    flight_no: str = ""
    dep_city: str
    arr_city: str
    date: str
    min_seats: int = 9
    alert_on_price_change: bool = True


class WebSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


# ── 静态文件 ──
@app.get("/")
async def index():
    """主页"""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            {"error": "Web 页面未找到", "expected": str(index_file)},
            status_code=404,
        )
    return FileResponse(index_file)


# ── 配置接口 ──
@app.get("/api/config")
async def get_config() -> dict:
    """获取当前配置（含航班列表）"""
    config = load_config_from(CONFIG_PATH)
    # 隐藏 webhook 完整地址
    webhook = config.get("feishu", {}).get("webhook_url", "")
    masked = ""
    if webhook and len(webhook) > 30:
        masked = webhook[:50] + "***" + webhook[-10:]
    return {
        "feishu_webhook_masked": masked,
        "flights": config.get("flights", []),
        "interval_minutes": config.get("interval_minutes", 30),
        "log_level": config.get("log_level", "INFO"),
    }


@app.post("/api/flights")
async def add_flight(flight: FlightConfig) -> dict:
    """添加一个监控航班"""
    config = load_config_from(CONFIG_PATH)
    flights = config.setdefault("flights", [])

    # 校验
    if not flight.dep_city or not flight.arr_city or not flight.date:
        raise HTTPException(400, "dep_city / arr_city / date 必填")
    if len(flight.date) != 10:
        raise HTTPException(400, "date 格式应为 YYYY-MM-DD")

    new = flight.model_dump()
    flights.append(new)
    save_config(config, CONFIG_PATH)
    logger.info(f"添加监控航班: {flight.dep_city}→{flight.arr_city} {flight.date}")
    return {"ok": True, "flight": new, "total": len(flights)}


@app.delete("/api/flights/{index}")
async def delete_flight(index: int) -> dict:
    """按索引删除监控航班"""
    config = load_config_from(CONFIG_PATH)
    flights = config.get("flights", [])
    if not (0 <= index < len(flights)):
        raise HTTPException(404, f"航班索引 {index} 不存在")
    removed = flights.pop(index)
    save_config(config, CONFIG_PATH)
    logger.info(f"删除监控航班: {removed}")
    return {"ok": True, "removed": removed, "total": len(flights)}


# ── 机场接口 ──
@app.get("/api/airports")
async def list_airports(q: str = "") -> dict:
    """搜索/列出机场"""
    airports = search_airports(q) if q else get_airports()
    return {"airports": airports, "total": len(airports)}


# ── 手动查询 ──
@app.post("/api/query")
async def manual_query(
    dep_city: str,
    arr_city: str,
    date: str,
    flight_no: str = "",
    background_tasks: BackgroundTasks = None,
) -> dict:
    """立即执行一次查询"""
    rt = get_runtime()
    client: CtripClient = rt["client"]
    history: HistoryStore = rt["history"]

    if not dep_city or not arr_city or not date:
        raise HTTPException(400, "dep_city / arr_city / date 必填")

    logger.info(f"[手动查询] {dep_city}→{arr_city} {date} {flight_no or '全部'}")

    try:
        if flight_no:
            flight = await client.query_single_flight(flight_no, dep_city, arr_city, date)
            flights = [flight] if flight else []
        else:
            flights = await client.query_flights(dep_city, arr_city, date)

        # 记录历史
        history.add_check(
            [_serialize_flight(f) for f in flights],
            source="web",
        )

        return {
            "ok": True,
            "count": len(flights),
            "flights": [_serialize_flight(f) for f in flights],
            "queried_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        history.add_error(f"{dep_city}→{arr_city} {date}: {e}", source="web")
        logger.error(f"手动查询失败: {e}", exc_info=True)
        raise HTTPException(500, f"查询失败: {e}")


# ── 历史接口 ──
@app.get("/api/history")
async def get_history(
    type: str | None = None,
    limit: int = 100,
) -> dict:
    """获取历史记录 (type: check | alert | error)"""
    rt = get_runtime()
    history: HistoryStore = rt["history"]
    return {
        "records": history.get_all(record_type=type, limit=limit),
        "total": len(history.get_all(record_type=type, limit=10_000)),
    }


@app.delete("/api/history")
async def clear_history() -> dict:
    """清空历史"""
    rt = get_runtime()
    rt["history"].clear()
    return {"ok": True}


# ── 状态接口 ──
@app.get("/api/states")
async def get_states() -> dict:
    """获取当前航班状态快照"""
    rt = get_runtime()
    return {"states": rt["state"].get_all_states()}


# ── 工具函数 ──
def _serialize_flight(f: FlightInfo) -> dict:
    return {
        "flight_no": f.flight_no,
        "dep_city": f.dep_city,
        "arr_city": f.arr_city,
        "date": f.date,
        "price": f.price,
        "seats_remaining": f.seats_remaining,
        "dep_time": f.dep_time,
        "arr_time": f.arr_time,
        "dep_airport": f.dep_airport,
        "arr_airport": f.arr_airport,
        "airline": f.airline,
        "update_time": f.update_time,
    }


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """在独立线程中运行 uvicorn"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_server_in_background(host: str = "127.0.0.1", port: int = 8765) -> None:
    """后台启动 Web 服务（非阻塞）"""
    import threading
    t = threading.Thread(
        target=run_server,
        args=(host, port),
        daemon=True,
        name="flight-web",
    )
    t.start()
    logger.info(f"🌐 Web 面板已启动: http://{host}:{port}")
