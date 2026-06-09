"""常用机场三字码数据库

供 Web 面板下拉选择使用。
"""

# 主流机场（按城市分组）
AIRPORTS: list[dict] = [
    # ── 北京 ──
    {"code": "PEK", "city": "北京", "name": "首都国际机场"},
    {"code": "PKX", "city": "北京", "name": "大兴国际机场"},

    # ── 上海 ──
    {"code": "SHA", "city": "上海", "name": "虹桥国际机场"},
    {"code": "PVG", "city": "上海", "name": "浦东国际机场"},

    # ── 广州 / 深圳 ──
    {"code": "CAN", "city": "广州", "name": "白云国际机场"},
    {"code": "SZX", "city": "深圳", "name": "宝安国际机场"},

    # ── 西南 ──
    {"code": "CTU", "city": "成都", "name": "天府国际机场"},
    {"code": "CKG", "city": "重庆", "name": "江北国际机场"},
    {"code": "KMG", "city": "昆明", "name": "长水国际机场"},

    # ── 华东 ──
    {"code": "HGH", "city": "杭州", "name": "萧山国际机场"},
    {"code": "NKG", "city": "南京", "name": "禄口国际机场"},
    {"code": "XMN", "city": "厦门", "name": "高崎国际机场"},
    {"code": "FOC", "city": "福州", "name": "长乐国际机场"},
    {"code": "TNA", "city": "济南", "name": "遥墙国际机场"},
    {"code": "TAO", "city": "青岛", "name": "胶东国际机场"},
    {"code": "NGB", "city": "宁波", "name": "栎社国际机场"},
    {"code": "WUX", "city": "无锡", "name": "硕放国际机场"},
    {"code": "CZX", "city": "常州", "name": "奔牛国际机场"},
    {"code": "HFE", "city": "合肥", "name": "新桥国际机场"},

    # ── 华北 / 东北 ──
    {"code": "TSN", "city": "天津", "name": "滨海国际机场"},
    {"code": "SHE", "city": "沈阳", "name": "桃仙国际机场"},
    {"code": "DLC", "city": "大连", "name": "周水子国际机场"},
    {"code": "CGQ", "city": "长春", "name": "龙嘉国际机场"},
    {"code": "HRB", "city": "哈尔滨", "name": "太平国际机场"},
    {"code": "NBS", "city": "长白山", "name": "长白山机场"},
    {"code": "HET", "city": "呼和浩特", "name": "白塔国际机场"},

    # ── 华中 ──
    {"code": "WUH", "city": "武汉", "name": "天河国际机场"},
    {"code": "CSX", "city": "长沙", "name": "黄花国际机场"},
    {"code": "CGO", "city": "郑州", "name": "新郑国际机场"},

    # ── 华南 ──
    {"code": "HAK", "city": "海口", "name": "美兰国际机场"},
    {"code": "SYX", "city": "三亚", "name": "凤凰国际机场"},
    {"code": "NNG", "city": "南宁", "name": "吴圩国际机场"},

    # ── 西北 ──
    {"code": "XIY", "city": "西安", "name": "咸阳国际机场"},
    {"code": "LJG", "city": "丽江", "name": "三义国际机场"},
    {"code": "DNH", "city": "敦煌", "name": "敦煌国际机场"},
    {"code": "URC", "city": "乌鲁木齐", "name": "地窝堡国际机场"},
    {"code": "LZO", "city": "泸州", "name": "云龙机场"},
    {"code": "JHG", "city": "西双版纳", "name": "嘎洒国际机场"},

    # ── 港澳台 ──
    {"code": "HKG", "city": "香港", "name": "香港国际机场"},
    {"code": "MFM", "city": "澳门", "name": "澳门国际机场"},
    {"code": "TPE", "city": "台北", "name": "桃园国际机场"},
    {"code": "TSA", "city": "台北", "name": "松山机场"},
]


def get_airports() -> list[dict]:
    """获取所有机场列表"""
    return AIRPORTS


def get_city_airports() -> dict[str, list[dict]]:
    """按城市分组返回机场"""
    grouped: dict[str, list[dict]] = {}
    for ap in AIRPORTS:
        grouped.setdefault(ap["city"], []).append(ap)
    return grouped


def search_airports(keyword: str) -> list[dict]:
    """按城市名/机场名/三字码模糊搜索"""
    keyword = keyword.lower().strip()
    if not keyword:
        return AIRPORTS
    return [
        ap for ap in AIRPORTS
        if keyword in ap["code"].lower()
        or keyword in ap["city"].lower()
        or keyword in ap["name"].lower()
    ]
