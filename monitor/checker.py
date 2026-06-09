"""核心检查逻辑 — 对比航班状态，判断是否需要告警"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from monitor.flight import CtripClient, FlightInfo
from storage.state import StateStore

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """告警信息"""
    flight: FlightInfo
    alert_type: str          # "price_change" | "low_seats" | "both"
    old_price: float | None
    new_price: float
    price_diff: float        # 正数=涨价, 负数=降价
    old_seats: int | None
    new_seats: int
    threshold_seats: int

    def format_message(self) -> str:
        """格式化为告警消息"""
        lines = [
            "✈️ 机票监控提醒",
            "",
            f"航班: {self.flight.flight_no} ({self.flight.dep_city}→{self.flight.arr_city})",
            f"日期: {self.flight.date}",
        ]

        if self.flight.airline:
            lines.append(f"航司: {self.flight.airline}")
        if self.flight.dep_time and self.flight.arr_time:
            lines.append(f"时间: {self.flight.dep_time} → {self.flight.arr_time}")

        lines.append("")

        if "price_change" in self.alert_type and self.old_price is not None:
            direction = "📈 涨价" if self.price_diff > 0 else "📉 降价"
            sign = "+" if self.price_diff > 0 else ""
            lines.append(f"💰 {direction}: ¥{self.old_price:.0f} → ¥{self.new_price:.0f} ({sign}¥{self.price_diff:.0f})")
        elif "price_change" in self.alert_type:
            lines.append(f"💰 当前价格: ¥{self.new_price:.0f}")

        if "low_seats" in self.alert_type:
            lines.append(f"⚠️ 余票不足: 剩余 {self.new_seats} 张（阈值: {self.threshold_seats}）")

        lines.extend([
            "",
            f"查询时间: {self.flight.update_time}",
        ])

        return "\n".join(lines)


class FlightChecker:
    """航班检查器

    负责：
    1. 调用 CtripClient 查询航班数据
    2. 与 StateStore 中的上次状态对比
    3. 判断是否触发告警并生成 Alert

    支持两种监控模式:
    - 指定航班号: 只监控该航班的价格和余票
    - 不指定航班号: 监控该航线所有航班，任一满足条件即告警
    """

    def __init__(self, client: CtripClient, store: StateStore):
        self.client = client
        self.store = store

    async def check_flight(self, flight_config: dict) -> tuple[list[Alert], list[FlightInfo]]:
        """检查单个配置项的状态变化

        Args:
            flight_config: 航班配置字典，来自 config.yaml 的 flights 列表项

        Returns:
            (触发的告警列表, 本次查询到的所有航班信息)
        """
        flight_no = flight_config.get("flight_no")  # 可选
        dep_city = flight_config["dep_city"]
        arr_city = flight_config["arr_city"]
        date = flight_config["date"]
        min_seats = flight_config.get("min_seats", 9)
        alert_on_price_change = flight_config.get("alert_on_price_change", True)

        route_label = f"{dep_city}→{arr_city} {date}"

        if flight_no:
            # 模式1: 监控指定航班
            flight_info = await self.client.query_single_flight(
                flight_no, dep_city, arr_city, date
            )
            if flight_info is None:
                logger.warning(f"未查询到航班 {flight_no} ({route_label})，跳过")
                return [], []
            flights_to_check = [flight_info]
        else:
            # 模式2: 监控整条航线所有航班
            flights_to_check = await self.client.query_flights(
                dep_city, arr_city, date
            )
            if not flights_to_check:
                logger.warning(f"未查询到 {route_label} 的航班数据")
                return [], []
            logger.info(f"{route_label} 共 {len(flights_to_check)} 个航班待检查")

        alerts = []
        for flight_info in flights_to_check:
            alert = self._evaluate_flight(
                flight_info, min_seats, alert_on_price_change
            )
            if alert:
                alerts.append(alert)

        return alerts, flights_to_check

    def _evaluate_flight(
        self,
        flight_info: FlightInfo,
        min_seats: int,
        alert_on_price_change: bool,
    ) -> Alert | None:
        """评估单个航班是否需要告警

        Args:
            flight_info: 最新航班信息
            min_seats: 余票阈值
            alert_on_price_change: 是否检测价格变化

        Returns:
            需要告警返回 Alert，否则 None
        """
        # 获取上次状态
        last_state = self.store.get_last_state(flight_info.key)
        old_price = last_state["price"] if last_state else None
        old_seats = last_state["seats_remaining"] if last_state else None

        # 价格变化检测
        price_changed = False
        price_diff = 0.0
        if alert_on_price_change and old_price is not None:
            price_diff = flight_info.price - old_price
            if abs(price_diff) > 0.01:  # 浮点精度容差
                price_changed = True
                logger.info(
                    f"{flight_info.flight_no} 价格变动: ¥{old_price:.0f} → ¥{flight_info.price:.0f}"
                )

        # 余票不足检测（seats_remaining 为 -1 表示未知，跳过检测）
        low_seats = (
            flight_info.seats_remaining >= 0
            and flight_info.seats_remaining < min_seats
        )
        if low_seats:
            logger.info(
                f"{flight_info.flight_no} 余票不足: {flight_info.seats_remaining} < {min_seats}"
            )

        # 更新状态（无论是否告警都更新）
        self.store.update_state(flight_info)

        # 首次查询只记录状态，不告警
        if last_state is None:
            logger.info(
                f"{flight_info.flight_no} 首次记录: ¥{flight_info.price:.0f}, "
                f"余票 {flight_info.seats_remaining}"
            )
            return None

        # 构造告警
        if price_changed and low_seats:
            alert_type = "both"
        elif price_changed:
            alert_type = "price_change"
        elif low_seats:
            alert_type = "low_seats"
        else:
            return None

        return Alert(
            flight=flight_info,
            alert_type=alert_type,
            old_price=old_price,
            new_price=flight_info.price,
            price_diff=price_diff,
            old_seats=old_seats,
            new_seats=flight_info.seats_remaining,
            threshold_seats=min_seats,
        )

    async def check_all(self, flight_configs: list[dict]) -> tuple[list[Alert], list[FlightInfo]]:
        """检查所有配置的航班

        Args:
            flight_configs: 航班配置列表

        Returns:
            (触发的告警列表, 本次查询到的所有航班信息)
        """
        all_alerts = []
        all_flights = []
        for config in flight_configs:
            route_label = (
                f"{config.get('flight_no', '*')} "
                f"({config['dep_city']}→{config['arr_city']} {config['date']})"
            )
            try:
                alerts, flights = await self.check_flight(config)
                all_alerts.extend(alerts)
                all_flights.extend(flights)
            except Exception as e:
                logger.error(f"检查 {route_label} 时出错: {e}", exc_info=True)

        return all_alerts, all_flights
