"""飞书通知模块 — 通过自定义机器人 Webhook 推送消息

使用飞书群聊中的自定义机器人发送告警消息。
只需一个 Webhook URL，无需部署额外服务。
"""

import asyncio
import json
import logging
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书自定义机器人通知客户端

    使用方法:
    1. 在飞书群聊中添加「自定义机器人」
    2. 复制 Webhook 地址填入 config.yaml
    3. 机器人会将告警消息发送到该群聊

    API 文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """

    def __init__(self, webhook_url: str):
        """
        Args:
            webhook_url: 飞书自定义机器人的 Webhook 地址
        """
        self.webhook_url = webhook_url
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_message(self, title: str, content: str) -> bool:
        """发送富文本消息到飞书群

        Args:
            title: 消息标题
            content: 消息正文（支持换行）

        Returns:
            是否发送成功
        """
        session = await self._get_session()

        # 使用富文本消息格式，支持多行和颜色标记
        lines = content.split("\n")
        content_blocks = []
        for line in lines:
            if line.strip():
                # 根据内容添加颜色标签
                styled_line = self._style_line(line)
                content_blocks.append([{"tag": "text", "text": styled_line}])
            else:
                content_blocks.append([{"tag": "text", "text": " "}])

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": content_blocks,
                    }
                }
            },
        }

        try:
            async with session.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                data = await resp.json()
                if data.get("code") == 0 or data.get("StatusCode") == 0:
                    logger.info("✅ 飞书消息发送成功")
                    return True
                else:
                    logger.error(f"❌ 飞书消息发送失败: {data}")
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"❌ 飞书消息发送异常: {e}")
            return False

    async def send_alert(self, alert_message: str) -> bool:
        """发送告警消息（兼容 checker 的调用接口）

        Args:
            alert_message: 格式化后的告警消息文本

        Returns:
            是否发送成功
        """
        return await self.send_message("✈️ 机票监控提醒", alert_message)

    @staticmethod
    def _style_line(line: str) -> str:
        """为消息行添加飞书标签样式"""
        if "涨价" in line:
            return f"🔺 {line}"
        if "降价" in line:
            return f"🔻 {line}"
        if "余票不足" in line:
            return f"⚠️ {line}"
        return line
