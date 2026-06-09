"""配置加载模块"""

import os
from pathlib import Path
from typing import Any

import yaml


# 项目根目录（config_loader.py 位于项目根目录）
BASE_DIR = Path(__file__).resolve().parent


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """加载 YAML 配置文件

    Args:
        config_path: 配置文件路径，默认为项目根目录下的 config.yaml

    Returns:
        解析后的配置字典
    """
    if config_path is None:
        config_path = os.environ.get(
            "FLIGHT_MONITOR_CONFIG",
            str(BASE_DIR / "config.yaml"),
        )

    return load_config_from(config_path)


def load_config_from(config_path: str | Path) -> dict[str, Any]:
    """从指定路径加载配置（无文件时返回空配置）"""
    path = Path(config_path)
    if not path.exists():
        return {
            "feishu": {"webhook_url": ""},
            "flights": [],
            "interval_minutes": 30,
            "log_level": "INFO",
        }
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict, config_path: str | Path | None = None) -> None:
    """保存配置到 YAML 文件"""
    if config_path is None:
        config_path = BASE_DIR / "config.yaml"
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def _validate_config(config: dict) -> None:
    """校验配置文件关键字段"""
    # 飞书通知配置
    feishu = config.get("feishu", {})
    webhook = feishu.get("webhook_url", "")
    if not webhook or 'xxxxxxx' in webhook:
        raise ValueError(
            "请在 config.yaml 中配置飞书 Webhook 地址 (feishu.webhook_url)\n"
            "在飞书群聊 → 设置 → 群机器人 → 添加自定义机器人 即可获取"
        )

    # 航班列表
    flights = config.get("flights", [])
    if not flights:
        raise ValueError("请在 config.yaml 中配置至少一个监控航班 (flights)")

    for i, flight in enumerate(flights):
        for field in ("dep_city", "arr_city", "date"):
            if not flight.get(field):
                raise ValueError(f"航班 #{i+1} 缺少必填字段: {field}")
