"""定时调度器 — 定期执行航班检查任务"""

import logging
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class FlightScheduler:
    """航班监控调度器

    使用 APScheduler 按配置的间隔定期执行检查任务。
    """

    def __init__(self, interval_minutes: int = 30):
        """
        Args:
            interval_minutes: 检查间隔（分钟）
        """
        self.interval_minutes = interval_minutes
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,       # 错过的任务合并执行一次
                "max_instances": 1,     # 同一任务最多一个实例
                "misfire_grace_time": 60,  # 错过60秒内仍执行
            }
        )
        self._job = None

    def add_check_job(self, func: Callable[..., Coroutine], **kwargs: Any) -> None:
        """添加定时检查任务

        Args:
            func: 异步检查函数
            **kwargs: 传递给检查函数的额外参数
        """
        self._job = self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(minutes=self.interval_minutes),
            kwargs=kwargs,
            id="flight_check",
            name="航班监控检查",
            replace_existing=True,
        )
        logger.info(f"已添加定时任务: 每 {self.interval_minutes} 分钟检查一次")

    def start(self) -> None:
        """启动调度器"""
        self.scheduler.start()
        logger.info("⏰ 调度器已启动")

        # 打印下次执行时间
        if self._job:
            next_run = self._job.next_run_time
            logger.info(f"下次检查时间: {next_run}")

    def stop(self) -> None:
        """停止调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("调度器已停止")

    async def run_once(self, func: Callable[..., Coroutine], **kwargs: Any) -> Any:
        """立即执行一次检查（不通过调度器）"""
        return await func(**kwargs)
