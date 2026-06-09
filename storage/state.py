"""状态持久化 — 存储航班上次查询结果"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from monitor.flight import FlightInfo

logger = logging.getLogger(__name__)

# 默认状态文件路径
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "state.json"


class StateStore:
    """航班状态存储

    使用 JSON 文件持久化每个航班的上次查询结果，
    用于对比价格和余票变化。
    """

    def __init__(self, state_file: str | Path | None = None):
        self.state_file = Path(state_file) if state_file else DEFAULT_STATE_FILE
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"已加载状态文件: {self.state_file} ({len(self._data)} 条记录)")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"状态文件读取失败，将使用空状态: {e}")
                self._data = {}
        else:
            logger.info("状态文件不存在，将创建新文件")
            self._data = {}

    def _save(self) -> None:
        """将状态写入文件"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        logger.debug("状态已保存")

    def get_last_state(self, flight_key: str) -> dict | None:
        """获取航班的上次状态

        Args:
            flight_key: 航班唯一标识 (flight.flight.key)

        Returns:
            上次的状态字典，如 {"price": 1280.0, "seats_remaining": 15, ...}
            若无记录则返回 None
        """
        return self._data.get(flight_key)

    def update_state(self, flight: FlightInfo) -> None:
        """更新航班状态

        Args:
            flight: 最新的航班信息
        """
        self._data[flight.key] = {
            "flight_no": flight.flight_no,
            "dep_city": flight.dep_city,
            "arr_city": flight.arr_city,
            "date": flight.date,
            "price": flight.price,
            "seats_remaining": flight.seats_remaining,
            "cabin_class": flight.cabin_class,
            "last_check": flight.update_time,
            "updated_at": datetime.now().isoformat(),
        }
        self._save()

    def update_states(self, flights: list[FlightInfo]) -> None:
        """批量更新航班状态"""
        for flight in flights:
            self._data[flight.key] = {
                "flight_no": flight.flight_no,
                "dep_city": flight.dep_city,
                "arr_city": flight.arr_city,
                "date": flight.date,
                "price": flight.price,
                "seats_remaining": flight.seats_remaining,
                "cabin_class": flight.cabin_class,
                "last_check": flight.update_time,
                "updated_at": datetime.now().isoformat(),
            }
        self._save()

    def remove_state(self, flight_key: str) -> bool:
        """删除指定航班的状态记录"""
        if flight_key in self._data:
            del self._data[flight_key]
            self._save()
            return True
        return False

    def get_all_states(self) -> dict[str, dict]:
        """获取所有航班状态"""
        return dict(self._data)
