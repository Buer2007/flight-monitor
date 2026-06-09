"""机票监控系统 — 主入口

启动定时任务，监控指定航班的机票余量和价格变化，
当价格变动或余票不足时通过飞书推送消息。
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

from itertools import groupby

from config_loader import load_config
from monitor.flight import CtripClient, FlightInfo
from monitor.checker import FlightChecker
from monitor.scheduler import FlightScheduler
from notifier.feishu import FeishuNotifier
from storage.state import StateStore
from storage.history import HistoryStore
from web.app import init_runtime, start_server_in_background


def setup_logging(level: str = "INFO") -> None:
    """配置日志"""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                Path(__file__).parent / "data" / "monitor.log",
                encoding="utf-8",
            ),
        ],
    )


async def check_and_notify(checker: FlightChecker, notifier: FeishuNotifier, history: HistoryStore, flights: list[dict]) -> None:
    """执行一轮检查，发送航班汇总 + 告警通知

    这是调度器调用的核心任务函数。
    每次查询后会发送一条汇总消息（航班号、价格、余票），
    若有价格变动或余票不足还会额外发送告警。
    """
    logger = logging.getLogger("monitor.main")

    logger.info("=" * 40)
    logger.info("开始执行航班监控检查...")

    try:
        alerts, checked_flights = await checker.check_all(flights)

        # ── 记录查询历史 ──
        if checked_flights:
            history.add_check(
                [_serialize_flight(f) for f in checked_flights],
                source="scheduler",
            )

        # ── 发送航班价格汇总 ──
        if checked_flights:
            summary_lines = build_summary(checked_flights)
            summary_text = "\n".join(summary_lines)
            logger.info(f"\n{summary_text}")
            await notifier.send_message("📋 航班价格汇总", summary_text)
        else:
            logger.warning("本轮未查询到任何航班数据")

        # ── 发送告警通知 ──
        if not alerts:
            logger.info("✅ 本轮检查无告警")
        else:
            logger.info(f"⚠️ 发现 {len(alerts)} 个告警")
            for alert in alerts:
                message = alert.format_message()
                logger.info(f"\n{message}")
                success = await notifier.send_alert(message)
                if success:
                    logger.info(f"告警已推送: {alert.flight.flight_no}")
                else:
                    logger.error(f"告警推送失败: {alert.flight.flight_no}")

                # 记录告警历史
                history.add_alert({
                    "flight_no": alert.flight.flight_no,
                    "alert_type": alert.alert_type,
                    "old_price": alert.old_price,
                    "new_price": alert.new_price,
                    "price_diff": alert.price_diff,
                    "old_seats": alert.old_seats,
                    "new_seats": alert.new_seats,
                    "threshold_seats": alert.threshold_seats,
                }, source="scheduler")

    except Exception as e:
        logger.error(f"检查过程出错: {e}", exc_info=True)
        history.add_error(str(e), source="scheduler")

    logger.info("本轮检查完成")
    logger.info("=" * 40)


def _serialize_flight(f: FlightInfo) -> dict:
    """将 FlightInfo 序列化为字典（供 history 记录使用）"""
    return {
        "flight_no": f.flight_no,
        "dep_city": f.dep_city,
        "arr_city": f.arr_city,
        "date": f.date,
        "price": f.price,
        "seats_remaining": f.seats_remaining,
        "dep_time": f.dep_time,
        "arr_time": f.arr_time,
        "airline": f.airline,
        "update_time": f.update_time,
    }


def build_summary(flights: list) -> list[str]:
    """将航班信息列表格式化为汇总消息

    按航线分组，每行显示：航班号 | 时间 | 价格 | 余票
    """
    lines = [
        f"🕐 查询时间: {flights[0].update_time if flights else 'N/A'}",
        f"📊 共 {len(flights)} 个航班",
        "",
    ]

    # 按航线（出发→到达+日期）分组
    def route_key(f: FlightInfo) -> str:
        return f"{f.dep_city}→{f.arr_city} {f.date}"

    sorted_flights = sorted(flights, key=route_key)
    for route, group in groupby(sorted_flights, key=route_key):
        group_list = sorted(group, key=lambda f: f.price)
        lines.append(f"【{route}】")
        for fl in group_list:
            time_str = f"{fl.dep_time}-{fl.arr_time}" if fl.dep_time else "时间待定"
            seat_str = f"{fl.seats_remaining}张" if fl.seats_remaining >= 0 else "未知"
            airline = f" {fl.airline}" if fl.airline else ""
            lines.append(
                f"  {fl.flight_no}{airline}  {time_str}  ¥{fl.price:.0f}  余{seat_str}"
            )
        lines.append("")

    return lines


async def main() -> None:
    """主函数"""
    # 加载配置
    config = load_config()
    setup_logging(config.get("log_level", "INFO"))
    logger = logging.getLogger("monitor.main")

    logger.info("✈️ 机票监控系统启动中...")
    logger.info(f"监控航班: {len(config['flights'])} 个")
    logger.info(f"检查间隔: {config['interval_minutes']} 分钟")

    # 初始化各模块
    feishu_config = config["feishu"]

    client = CtripClient()
    store = StateStore()
    history = HistoryStore()
    checker = FlightChecker(client, store)
    notifier = FeishuNotifier(webhook_url=feishu_config["webhook_url"])
    scheduler = FlightScheduler(interval_minutes=config["interval_minutes"])

    # 注入 Web 面板运行时并启动后台服务
    init_runtime(client=client, checker=checker, notifier=notifier, state=store, history=history)
    start_server_in_background(host="127.0.0.1", port=8765)

    # 优雅退出处理
    shutdown_event = asyncio.Event()

    def handle_signal(signum, frame):
        logger.info(f"收到退出信号 ({signum})，正在关闭...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        # ── 启动通知：告知飞书机器人系统已上线 ──
        startup_lines = [
            f"🕐 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"📊 监控航班: {len(config['flights'])} 个",
            f"⏱️ 检查间隔: {config['interval_minutes']} 分钟",
            "",
            "监控航线:",
        ]
        for fl in config["flights"]:
            label = fl.get("flight_no", "全部")
            startup_lines.append(
                f"  • {fl['dep_city']}→{fl['arr_city']} {fl['date']} "
                f"(航班: {label}, 余票阈值: {fl.get('min_seats', 9)})"
            )
        startup_lines.append("")
        startup_lines.append("系统已就绪，开始监控 ✈️")

        await notifier.send_message(
            "🟢 机票监控系统已启动",
            "\n".join(startup_lines),
        )

        # 立即执行一次检查
        await check_and_notify(checker, notifier, history, config["flights"])

        # 添加定时任务并启动调度器
        scheduler.add_check_job(
            check_and_notify,
            checker=checker,
            notifier=notifier,
            history=history,
            flights=config["flights"],
        )
        scheduler.start()

        logger.info("🟢 监控已启动，按 Ctrl+C 退出")

        # 等待退出信号
        await shutdown_event.wait()

    except KeyboardInterrupt:
        logger.info("收到键盘中断")
    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
    finally:
        # 清理资源
        scheduler.stop()
        await client.close()
        await notifier.close()
        logger.info("👋 机票监控系统已退出")


if __name__ == "__main__":
    asyncio.run(main())
