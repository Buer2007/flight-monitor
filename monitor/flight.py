"""携程机票数据抓取 — 通过 Playwright 无头浏览器获取航班价格与余票

采用多重反检测策略：
1. 持久化浏览器 Profile（保留 Cookie/登录态）
2. 注入 Stealth JS（隐藏自动化特征）
3. 真实 User-Agent / Viewport / 时区
4. 智能等待 + 重试机制
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Stealth JS：在页面加载前注入，隐藏 Playwright 自动化指纹 ────────────
_STEALTH_JS = """
// 1. 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. 伪造 chrome 对象（Edge/Chrome 都有）
if (!window.chrome) {
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
}

// 3. 伪造 plugins（无头浏览器默认为空）
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ],
});

// 4. 伪造 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
});

// 5. 覆盖 permissions query（防止被检测 Notification 权限异常）
const origQuery = window.navigator.permissions?.query;
if (origQuery) {
    window.navigator.permissions.query = (params) => {
        if (params.name === 'notifications') {
            return Promise.resolve({ state: Notification.permission });
        }
        return origQuery(params);
    };
}

// 6. 隐藏 Headless 特征
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// 7. 修复 iframe contentWindow
try {
    const origFunc = HTMLIFrameElement.prototype.__lookupGetter__('contentWindow');
    if (origFunc) {
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
            get: function() {
                const iframe = origFunc.call(this);
                if (iframe && iframe.chrome === undefined) {
                    iframe.chrome = window.chrome;
                }
                return iframe;
            }
        });
    }
} catch(e) {}
"""

# ── 常用 User-Agent 池（真实浏览器 UA，定期更新） ───────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


@dataclass
class FlightInfo:
    """标准化的航班信息"""
    flight_no: str
    dep_city: str
    arr_city: str
    date: str
    price: float
    seats_remaining: int
    cabin_class: str = "经济舱"
    dep_time: str = ""
    arr_time: str = ""
    dep_airport: str = ""
    arr_airport: str = ""
    airline: str = ""
    update_time: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def key(self) -> str:
        """唯一标识一个航班查询"""
        return f"{self.flight_no}_{self.dep_city}_{self.arr_city}_{self.date}"


class CtripClient:
    """携程机票数据抓取客户端（增强反检测版）

    使用 Playwright 无头浏览器访问携程航班列表页，
    拦截XHR响应获取航班数据，通过多重反检测绕过风控。
    """

    _LIST_URL = "https://flights.ctrip.com/online/list/oneway-{dep}-{arr}?depdate={date}"

    # 持久化浏览器 Profile 目录（保留 Cookie，避免每次冷启动被风控）
    _PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser_profile"

    def __init__(self):
        self._browser = None
        self._context = None  # 持久化上下文
        self._playwright = None

    async def _ensure_browser(self):
        """延迟初始化浏览器（优先使用系统 Edge，带完整反检测）"""
        if self._browser is not None and self._context is not None:
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        # ── 浏览器启动参数（反检测） ──
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--metrics-recording-only",
            "--disable-default-apps",
            "--mute-audio",
            "--window-size=1920,1080",
        ]

        # 随机选一个 UA
        ua = random.choice(_USER_AGENTS)

        try:
            browser = await self._playwright.chromium.launch(
                headless=True,
                executable_path=edge_path,
                args=launch_args,
            )
            logger.info("使用系统 Edge 浏览器（反检测模式）")
        except Exception:
            browser = await self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
            )
            logger.info("使用 Playwright Chromium（反检测模式）")

        # 使用持久化上下文（保留 Cookie / localStorage）
        self._PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._context = await browser.new_context(
                user_agent=ua,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                color_scheme="light",
                # 持久化 storage state
                storage_state=self._PROFILE_DIR / "state.json"
                if (self._PROFILE_DIR / "state.json").exists()
                else None,
            )
        except Exception:
            # storage state 损坏时降级为新上下文
            self._context = await browser.new_context(
                user_agent=ua,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

        self._browser = browser
        logger.debug(f"浏览器初始化完成，UA: {ua[:60]}...")

    async def close(self) -> None:
        """关闭浏览器并保存会话状态"""
        try:
            if self._context:
                # 保存 cookies / localStorage 供下次复用
                try:
                    await self._context.storage_state(
                        path=self._PROFILE_DIR / "state.json"
                    )
                    logger.debug("已保存浏览器会话状态")
                except Exception as e:
                    logger.debug(f"保存会话状态失败（非致命）: {e}")
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        if self._playwright:
            await self._playwright.stop()
            self._browser = None
            self._context = None
            self._playwright = None

    async def query_flights(
        self, dep_city: str, arr_city: str, date: str
    ) -> list[FlightInfo]:
        """查询指定航线和日期的航班信息

        Args:
            dep_city: 出发城市三字码 (如 SHA)
            arr_city: 到达城市三字码 (如 PEK)
            date: 出发日期 (YYYY-MM-DD)

        Returns:
            航班信息列表
        """
        await self._ensure_browser()

        url = self._LIST_URL.format(dep=dep_city, arr=arr_city, date=date)
        logger.info(f"查询航班: {dep_city}→{arr_city} {date}")

        flight_data: list[FlightInfo] = []
        page = None

        # ── XHR 拦截回调 ──
        async def on_response(response):
            try:
                resp_url = response.url
                # 携程航班搜索 API 的常见关键词
                if any(kw in resp_url for kw in ("batchSearch", "flightList", "search", "FlightSearch")):
                    if response.status == 200:
                        data = await response.json()
                        parsed = self._parse_api_response(data, dep_city, arr_city, date)
                        if parsed:
                            flight_data.extend(parsed)
                            logger.info(f"✓ 从API拦截到 {len(parsed)} 个航班 (URL: ...{resp_url[-80:]})")
            except Exception as e:
                logger.debug(f"处理响应异常: {e}")

        try:
            page = await self._context.new_page()
            page.on("response", on_response)

            # 注入 stealth JS（在每个新页面加载前执行）
            await page.add_init_script(_STEALTH_JS)

            # ── 访问页面 ──
            logger.debug(f"正在加载: {url}")
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            if resp and resp.status != 200:
                logger.warning(f"页面返回 HTTP {resp.status}")

            # ── 智能等待：先等 XHR，再等 DOM ──
            # 等待航班列表元素出现（携程的 class 经常变，多试几个选择器）
            selectors = [
                "[class*='flight-item']",
                "[class*='FlightItem']",
                "[class*='list-item']",
                "[class*='flight_list']",
                "[class*='FlightList']",
                "[class*='search-result']",
                "[class*='o-flight']",
            ]

            for sel in selectors:
                try:
                    await page.wait_for_selector(sel, timeout=5000)
                    logger.debug(f"找到航班列表元素: {sel}")
                    break
                except Exception:
                    continue
            else:
                # 没找到任何已知选择器，多等一会儿让 XHR 完成
                logger.debug("未找到已知航班列表选择器，等待页面加载...")
                await asyncio.sleep(5)

            # 额外等待让异步请求完成
            await asyncio.sleep(3)

            # ── 检查是否遇到验证码 / 风控页面 ──
            page_text = await page.inner_text("body")
            if any(kw in page_text for kw in ("验证", "captcha", "滑块", "请完成验证", "访问验证")):
                logger.warning("⚠️ 检测到验证码/风控页面，本次查询跳过")
                # 截图存证以便调试
                try:
                    screenshot_path = Path(__file__).parent.parent / "data" / "captcha_debug.png"
                    await page.screenshot(path=str(screenshot_path))
                    logger.info(f"验证码截图已保存: {screenshot_path}")
                except Exception:
                    pass
                return []

            # ── 如果 XHR 拦截没拿到数据，从 DOM 提取 ──
            if not flight_data:
                logger.debug("XHR 未拦截到数据，尝试从页面DOM提取")
                flight_data = await self._extract_from_page(page, dep_city, arr_city, date)

            # ── 保存 storage state（cookies 等） ──
            try:
                await self._context.storage_state(
                    path=self._PROFILE_DIR / "state.json"
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"页面加载失败: {e}")
        finally:
            if page:
                await page.close()

        logger.info(f"查询到 {len(flight_data)} 个航班 ({dep_city}→{arr_city} {date})")

        # 调试：查询结果为 0 时截图 + 保存 HTML，排查页面实际内容
        if not flight_data and page:
            try:
                debug_dir = Path(__file__).parent.parent / "data"
                debug_dir.mkdir(parents=True, exist_ok=True)

                await page.screenshot(path=str(debug_dir / "debug_no_result.png"), full_page=True)
                logger.info(f"📸 查询结果为空，页面截图已保存: {debug_dir / 'debug_no_result.png'}")

                html = await page.content()
                (debug_dir / "debug_page.html").write_text(html[:200_000], encoding="utf-8")
                logger.info(f"📄 页面 HTML 已保存: {debug_dir / 'debug_page.html'}")
            except Exception as e:
                logger.debug(f"保存调试信息失败: {e}")

        return flight_data

    async def query_single_flight(
        self, flight_no: str, dep_city: str, arr_city: str, date: str
    ) -> FlightInfo | None:
        """查询单个航班"""
        flights = await self.query_flights(dep_city, arr_city, date)
        for flight in flights:
            if flight.flight_no.upper() == flight_no.upper():
                return flight

        # 宽松匹配
        num_part = re.sub(r"[^0-9]", "", flight_no)
        for flight in flights:
            if re.sub(r"[^0-9]", "", flight.flight_no) == num_part:
                return flight

        logger.warning(f"未找到航班 {flight_no} ({dep_city}→{arr_city} {date})")
        return None

    def _parse_api_response(
        self, data: dict, dep_city: str, arr_city: str, date: str
    ) -> list[FlightInfo]:
        """解析API响应中的航班数据"""
        flights = []

        # batchSearch 格式
        route_list = (
            data.get("data", {}).get("routeList", [])
            if isinstance(data.get("data"), dict)
            else []
        )

        for route in route_list:
            for leg in route.get("legs", []):
                try:
                    flight = leg.get("flight", {})
                    characteristic = leg.get("characteristic", {})

                    price = 0.0
                    price_str = characteristic.get("lowestPrice", "")
                    if price_str:
                        price = float(price_str)
                    elif leg.get("cabins"):
                        price = float(leg["cabins"][0].get("price", {}).get("price", 0))

                    seats = flight.get("seatCount", -1)
                    if seats == "" or seats is None:
                        seats = -1
                    seats = int(seats)

                    flight_no = flight.get("flightNumber", "")
                    dep_time = flight.get("departureDate", "")
                    arr_time = flight.get("arrivalDate", "")
                    if "T" in dep_time:
                        dep_time = dep_time.split("T")[1][:5]
                    if "T" in arr_time:
                        arr_time = arr_time.split("T")[1][:5]

                    info = FlightInfo(
                        flight_no=flight_no,
                        dep_city=dep_city,
                        arr_city=arr_city,
                        date=date,
                        price=price,
                        seats_remaining=seats,
                        dep_time=dep_time,
                        arr_time=arr_time,
                        dep_airport=flight.get("departureAirportShortName", ""),
                        arr_airport=flight.get("arrivalAirportShortName", ""),
                        airline=flight.get("airlineName", ""),
                    )
                    if flight_no:
                        flights.append(info)
                except (ValueError, TypeError, KeyError):
                    continue

        return flights

    async def _extract_from_page(
        self, page, dep_city: str, arr_city: str, date: str
    ) -> list[FlightInfo]:
        """从页面DOM提取航班数据（兜底方案）"""
        flights = []
        try:
            # 尝试获取页面中所有航班卡片的文本内容
            items = await page.query_selector_all(
                "[class*='flight-item'], [class*='FlightItem'], "
                "[class*='list-item'], [class*='flight_item']"
            )
            if not items:
                # 再试：获取整个页面文本做正则提取
                text = await page.inner_text("body")
                return self._parse_text_flights(text, dep_city, arr_city, date)

            for item in items:
                try:
                    text = await item.inner_text()
                    info = self._parse_single_item_text(text, dep_city, arr_city, date)
                    if info:
                        flights.append(info)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"DOM提取失败: {e}")

        return flights

    def _parse_text_flights(
        self, text: str, dep_city: str, arr_city: str, date: str
    ) -> list[FlightInfo]:
        """从页面纯文本中用正则提取航班信息"""
        flights = []
        # 匹配航班号模式: 2字母+数字 (如 MU5101, CA1234)
        flight_pattern = re.compile(
            r'([A-Z]{2}\d{3,4}).*?(\d{2}:\d{2}).*?(\d{2}:\d{2}).*?[¥￥](\d+)',
            re.DOTALL,
        )
        for m in flight_pattern.finditer(text):
            try:
                flights.append(FlightInfo(
                    flight_no=m.group(1),
                    dep_city=dep_city,
                    arr_city=arr_city,
                    date=date,
                    price=float(m.group(4)),
                    seats_remaining=-1,  # 文本提取拿不到余票
                    dep_time=m.group(2),
                    arr_time=m.group(3),
                ))
            except (ValueError, IndexError):
                continue
        return flights

    def _parse_single_item_text(
        self, text: str, dep_city: str, arr_city: str, date: str
    ) -> FlightInfo | None:
        """从单个航班卡片文本提取信息"""
        flight_match = re.search(r'([A-Z]{2}\d{3,4})', text)
        time_match = re.findall(r'(\d{2}:\d{2})', text)
        price_match = re.search(r'[¥￥](\d+)', text)

        if flight_match and price_match:
            return FlightInfo(
                flight_no=flight_match.group(1),
                dep_city=dep_city,
                arr_city=arr_city,
                date=date,
                price=float(price_match.group(1)),
                seats_remaining=-1,
                dep_time=time_match[0] if len(time_match) > 0 else "",
                arr_time=time_match[1] if len(time_match) > 1 else "",
            )
        return None


class CtripAPIError(Exception):
    """携程接口调用异常"""
