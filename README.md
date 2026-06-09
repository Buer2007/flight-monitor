# ✈️ 机票监控系统

监控指定航班的机票余量和价格变化，当价格变动或余票不足时通过飞书实时推送提醒。

## 功能特性

- 🔍 **航班监控** — 定时抓取携程航班价格和余票数据（Playwright 无头浏览器 + 反检测）
- 💰 **价格告警** — 价格有任何变动即触发提醒
- ⚠️ **余票告警** — 余票低于阈值（默认9张）即触发提醒
- 📋 **价格汇总** — 每次检查后推送全部航班的价格/余票汇总
- 🟢 **启动通知** — 系统启动时推送监控配置信息
- 📱 **飞书通知** — 通过飞书自定义机器人 Webhook 推送消息
- ⏰ **定时轮询** — 可配置检查间隔（默认30分钟）
- 💾 **状态持久化** — 记录上次查询结果，精确对比变化
- 🛡️ **反检测** — Stealth JS、持久化 Cookie、真实 UA，绕过携程风控

## 项目结构

```
机票监控/
├── config.yaml          # 配置文件（不提交，含密钥）
├── config.yaml.example  # 配置模板
├── config_loader.py     # 配置加载与校验
├── main.py              # 主入口
├── requirements.txt     # Python依赖
├── monitor/
│   ├── flight.py        # 携程机票数据抓取（Playwright + 反检测）
│   ├── checker.py       # 核心检查逻辑（状态对比+告警判断）
│   └── scheduler.py     # 定时调度器
├── notifier/
│   └── feishu.py        # 飞书 Webhook 通知客户端
├── storage/
│   └── state.py         # 状态持久化（JSON文件）
└── data/                # 运行时数据（不提交）
    ├── state.json       # 航班状态快照
    ├── browser_profile/ # 浏览器持久化 Cookie
    ├── monitor.log      # 运行日志
    └── debug_*.png/html # 调试截图/页面快照
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 创建飞书机器人

1. 打开飞书，进入一个群聊（或新建一个告警专用群）
2. 点击群聊右上角 **设置** → **群机器人** → **添加机器人**
3. 选择 **自定义机器人**
4. 填写机器人名称（如"机票监控"），点击添加
5. 复制 **Webhook 地址**

### 3. 配置

复制配置模板并编辑：

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`：

```yaml
# 飞书通知设置
feishu:
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址"

# 监控航班列表
flights:
  - dep_city: "SHA"          # 上海虹桥
    arr_city: "PEK"          # 北京首都
    date: "2026-06-15"
    min_seats: 9             # 余票低于9张告警
    alert_on_price_change: true

# 检查间隔
interval_minutes: 30
```

### 4. 启动监控

```bash
python main.py
```

程序将：
1. 向飞书推送启动通知（监控配置信息）
2. 立即执行一次检查，推送航班价格汇总
3. 之后每30分钟自动检查一次，每次推送价格汇总
4. 发现价格变动或余票不足时额外推送告警消息
5. 按 `Ctrl+C` 优雅退出

## 告警消息示例

```
✈️ 机票监控提醒

航班: MU5101 (SHA→PEK)
日期: 2026-06-15
航司: 中国东方航空
时间: 08:00 → 10:30

🔻 降价: ¥1350 → ¥1280 (-¥70)
⚠️ 余票不足: 剩余 5 张（阈值: 9）

查询时间: 2026-06-08 14:30:00
```

## 常用机场三字码

| 代码 | 机场 |
|------|------|
| PEK | 北京首都 |
| PKX | 北京大兴 |
| SHA | 上海虹桥 |
| PVG | 上海浦东 |
| CAN | 广州白云 |
| SZX | 深圳宝安 |
| CTU | 成都天府 |
| CKG | 重庆江北 |
| HGH | 杭州萧山 |
| NKG | 南京禄口 |

## 监控模式

**指定航班号** — 只监控特定航班：
```yaml
flights:
  - flight_no: "MU5101"
    dep_city: "SHA"
    arr_city: "PEK"
    date: "2026-06-15"
```

**不指定航班号** — 监控该航线所有航班，任一满足条件即告警：
```yaml
flights:
  - dep_city: "SHA"
    arr_city: "PEK"
    date: "2026-06-15"
```

## 注意事项

- 数据来源为携程网页，接口可能变化，如遇抓取失败请检查 `data/debug_*.png` 截图
- 程序内置反检测（Stealth JS、持久化 Cookie），但仍可能被风控，建议间隔不低于15分钟
- 首次查询航班只记录状态，不会触发告警
- 状态文件保存在 `data/state.json`，删除可重置记录
- `config.yaml` 包含飞书密钥，已在 `.gitignore` 中排除，不会提交到仓库
