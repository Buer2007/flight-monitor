"""历史记录 — 存储查询历史和告警

与 state.py 不同：state 存的是「航班最新状态」（每个航班只一条），
history 存的是「时间序列」— 每次查询、每次告警都追加一条。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "history.json"
)

# 默认最多保留 2000 条历史
MAX_HISTORY = 2000


class HistoryStore:
    """查询历史与告警记录"""

    def __init__(self, history_file: str | Path | None = None):
        self.history_file = Path(history_file) if history_file else DEFAULT_HISTORY_FILE
        self._records: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.history_file.exists():
            try:
                with open(self.history_file, encoding="utf-8") as f:
                    self._records = json.load(f)
                logger.info(f"已加载历史记录: {len(self._records)} 条")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"历史文件读取失败: {e}")
                self._records = []
        else:
            self._records = []

    def _save(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)

    def add_check(self, flights: list[dict], source: str = "scheduler") -> dict:
        """记录一次查询

        Args:
            flights: 航班数据列表（已序列化的 dict）
            source: 'scheduler' | 'manual' | 'web'
        """
        record = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "type": "check",
            "source": source,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "flight_count": len(flights),
            "flights": flights,
        }
        self._records.append(record)
        self._trim()
        self._save()
        return record

    def add_alert(self, alert: dict, source: str = "scheduler") -> dict:
        """记录一次告警"""
        record = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "type": "alert",
            "source": source,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            **alert,
        }
        self._records.append(record)
        self._trim()
        self._save()
        return record

    def add_error(self, error: str, source: str = "scheduler") -> dict:
        """记录一次错误"""
        record = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "type": "error",
            "source": source,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "error": error,
        }
        self._records.append(record)
        self._trim()
        self._save()
        return record

    def _trim(self) -> None:
        """限制最大记录数"""
        if len(self._records) > MAX_HISTORY:
            self._records = self._records[-MAX_HISTORY:]

    # ── 查询接口 ──
    def get_all(
        self,
        record_type: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """获取历史记录（倒序）"""
        records = self._records
        if record_type:
            records = [r for r in records if r["type"] == record_type]
        return list(reversed(records[-limit:]))

    def get_alerts(self, limit: int = 100) -> list[dict]:
        return self.get_all(record_type="alert", limit=limit)

    def get_checks(self, limit: int = 50) -> list[dict]:
        return self.get_all(record_type="check", limit=limit)

    def clear(self) -> None:
        self._records = []
        self._save()
