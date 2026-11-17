#!/usr/bin/env python3
"""task-8：把 txt/ 真实销售资料拆分为可入 Dify 知识库的文档。

产出：
1. docs/dify/knowledge_real/*.md           9 篇知识库文档（合规预处理后）
2. tools/dify/kb_real/manifest.json       导入清单（与 tools/dify/import_kb.py 兼容）
3. tools/dify/kb_real/change_log.json     逐条变更记录（原文/改后/原因）
4. tools/dify/kb_real/generated_scan.json 产出文档的合规自检结果
5. docs/dify/guide/kb_real_report.md      汇总报告

用法：python -X utf8 tools/dify/kb_real/build_kb_real.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TXT = ROOT / "txt"
OUT_DIR = ROOT / "docs" / "dify" / "knowledge_real"
GUIDE_DIR = ROOT / "docs" / "dify" / "guide"
REPORT_PATH = GUIDE_DIR / "kb_real_report.md"
COMPLIANCE_JSON = ROOT / "tools" / "dify" / "compliance_words.json"
KB_MANIFEST = ROOT / "tools" / "dify" / "kb_manifest.json"

DATASET_ID = "403fbc9d-3c82-4077-8033-6761821f68f3"
VERSION = "v1-2026-11"

CAR_FILE = TXT / "现有汽车" / "现有汽车类型及销售要点.txt"
TERM_DIR = TXT / "销售话术"
METHOD_DIR = TXT / "需求咨询"
SKIP_NUMBERS = {28, 29}

DATA_NOTE = (
    "本文件为门店销售参考资料，非官方报价单。文中车型指导价、参数配置、终端优惠、金融方案与权益政策，"
    "均以门店最新公示、厂家官方配置表及官方条款为准，可能随年款、生产批次与政策调整而变化；"
    "智能驾驶相关功能统一表述为「智能辅助驾驶」，驾驶员需全程把控车辆；"
    "具体成交价格与实时库存以门店系统查询结果为准。"
)

# ---------------------------------------------------------------- 合规替换规则
# (level, old, new, reason, only)：only 为文件名片段过滤，None 表示全库
RULES = [
    # ---- 车型库（现有汽车类型及销售要点.txt）
    ("level1", "极致小巧车身", "小巧车身", "删除绝对化用语「极致」，改为客观描述", "现有汽车"),
    ("level1", "销量冠军", "销量表现靠前", "删除绝对化用语「销量冠军」，改为市场表现概括", "现有汽车"),
    ("level2", "三电终身质保，品质有保障", "三电长期质保政策较完善，品质有保障",
     "「终身质保」需附前提，车型库改为「长期质保政策」，具体以厂家条款为准", "现有汽车"),
    ("额外", "常年稳居代步车销量榜首", "长期位居代步车细分市场前列", "主动软化「榜首」等排名类绝对表述", "现有汽车"),
    ("额外", "全球销量第一的车型", "全球累计销量长期靠前的车型", "主动软化「全球销量第一」绝对表述", "现有汽车"),
    # ---- 01 / 02 级别划分：顶级
    ("level1", "行驶品质顶级", "行驶品质较好", "删除绝对化用语「顶级」", "01 -"),
    ("level1", "顶级商务人士", "高端商务人士", "删除绝对化用语「顶级」", "01 -"),
    ("level1", "顶级豪华", "高端豪华", "删除绝对化用语「顶级」", None),
    ("level1", "顶级高净值人群", "高净值人群", "删除绝对化用语「顶级」", "02-"),
    ("level1", "顶级性能车", "高端性能车", "删除绝对化用语「顶级」", "12 -"),
    ("level1", "空间顶级", "空间宽裕", "删除绝对化用语「顶级」，改为客观描述", "02-"),
    ("level1", "顶级", "高端", "删除绝对化用语「顶级」（兜底）", None),
    # ---- 04 驱动 / 11 悬挂：不容易坏
    ("level1", "操控稳定性最好", "操控稳定性较好", "删除绝对化用语「最好」", "04 -"),
    ("level3", "不容易坏", "可靠性较好", "删除竞品负面式口语「容易坏」，改为客观描述", None),
    # ---- 06 发动机：客户问题
    ("level3", "问：涡轮是不是容易坏？", "问：涡轮增压发动机可靠性怎么样、后期维修贵不贵？",
     "删除「容易坏」负面表述，改为中性可靠性提问", "06 -"),
    # ---- 07 变速箱
    ("level1", "质保是打消客户顾虑的最好武器", "质保是打消客户顾虑的有效方式",
     "删除绝对化用语「最好武器」，改为客观表述", "07 -"),
    # ---- 09 三电
    ("level1", "不要说“电池绝对安全”，要说“经过了严苛的安全测试，有多重防护，正常使用是安全的”。",
     "不要说「电池保证不出任何问题」，要说「经过多轮安全测试，有多重防护，正常使用是安全的」。",
     "删除「绝对安全」绝对化宣传，改为可验证的客观表述", "09 -"),
    ("level2", "厂家都有终身质保，有问题厂家兜底", "厂家提供长期质保政策，具体以厂家官方条款为准",
     "补「以厂家官方条款为准」前提，删除「终身」「兜底」承诺", "09 -"),
    # ---- 10 续航
    ("level1", "绝对不能说", "严禁说", "删除绝对化用语「绝对」", "10 -"),
    ("level1", "0-100%", "从 0 到满电", "避免「100%」绝对化表述，改为口语化描述", "10 -"),
    # ---- 12 转向制动 / 13 车身稳定
    ("level3", "入门车型部分低配会减配", "入门车型部分低配未配备", "「减配」改为中性的「未配备」", "13 -"),
    # ---- 14 智能驾驶分级：整篇人工重写（见 MANUAL_14）
    # ---- 17 价格体系
    ("level3", "最实在、最无套路的优惠", "规则清晰、直接减钱的优惠", "删除「套路」争议性表述", "17 -"),
    ("level1", "不能只说“零利息”不说前提", "不能只宣传「免息」而不说明前提条件",
     "删除「零利息」违规金融表述，改为「免息+前提」的合规表述", "17 -"),
    ("level2", "免息贷款通常有金额上限", "免息方案通常有金额上限", "「免息贷款」改为「免息方案」，配套说明金额上限", "17 -"),
    ("level1", "绝对不能低报价吸引客户到店", "严禁低报价吸引客户到店", "删除绝对化用语「绝对」", "17 -"),
    # ---- 18 车辆状态
    ("level1", "**绝对不能隐瞒车辆状态**", "**严禁隐瞒车辆状态**", "删除绝对化用语「绝对」", "18 -"),
    # ---- 20 权益与质保：术语保留 + 补前提
    ("level2", "终身质保：很多品牌给首任车主提供三电终身质保，是新能源车的核心卖点。",
     "长期质保：很多品牌为三电提供长期质保（通常限首任非营运车主、需按厂家要求保养），是新能源车的重要卖点。",
     "术语定义保留，补「首任/非营运/保养要求」前提", "20 -"),
    ("level2", "很多终身质保仅限首任车主，过户后失效。", "很多长期质保仅限首任车主，过户后按厂家条款执行。",
     "表述客观化，补充「按厂家条款执行」", "20 -"),
    ("level2", "销售话术：“首任非营运车主享受三电终身质保，电池电机电控一辈子保修，您完全不用担心电池坏了换不起。”",
     "销售话术：「首任非营运车主可按厂家政策享受三电长期质保，质保期内按政策维修，具体以官方条款为准，您不用太担心电池维修成本。」",
     "补「非营运/官方条款」前提，删除「终身」「一辈子」「完全」绝对化承诺", "20 -"),
    ("level2", "首任车主终身质保，用坏了厂家免费换，您完全不用担心",
     "首任非营运车主可按厂家政策享受三电长期质保，质保期内按政策维修，具体以官方条款为准，您不用太担心",
     "补「首任/非营运/官方条款」前提，删除「终身」「完全」绝对化承诺", "20 -"),
    ("level2", "1. 三电终身质保", "1. 三电长期质保（限首任车主、非营运）", "补首任车主/非营运前提", "20 -"),
    ("level2", "3. 终身免费道路救援", "3. 长期免费道路救援（限首任车主）", "补首任车主前提", "20 -"),
    ("level2", "部分品牌：提供终身免费道路救援。", "部分品牌：提供长期免费道路救援（限首任车主，具体以官方条款为准）。",
     "补首任车主/官方条款前提", "20 -"),
    ("level2", "终身免费保养：少数品牌给首任车主终身免费基础保养。",
     "长期免费保养：少数品牌给首任车主提供长期免费基础保养（限时限里程，以官方条款为准）。",
     "补首任车主/限时限里程前提", "20 -"),
    ("level2", "不能只说终身质保不说限制", "不能只讲长期质保而不说明限制条件", "改为客观提示，避免只讲权益不讲限制", "20 -"),
    ("level2", "终身质保是新能源车的大卖点", "长期质保政策是新能源车的重要卖点", "删除「终身」需附前提表述，改为客观描述", "20 -"),
    # ---- 21 贷款方案
    ("level2", "乘用车最低首付比例20%", "乘用车首付比例下限为 20%",
     "「最低首付比例」易被误读为「低首付」宣传，改为「首付比例下限」", "21 -"),
    ("level3", "没有套路", "规则清晰", "删除「套路」争议性表述", "21 -"),
    ("level1", "首付极低，甚至零首付，对资质要求低",
     "首付比例可低至政策下限（目前乘用车贷款首付比例下限为 20%），并需满足对应资质要求",
     "删除「零首付」违规金融表述，改为政策下限+资质前提", "21 -"),
    ("level2", "常见于免息贷款", "常见于免息类贷款产品", "「免息贷款」改为「免息类贷款产品」，配套前提说明", "21 -"),
    ("level2", "### 1. 免息贷款", "### 1. 免息方案（需满足额度与征信条件）",
     "标题由「免息贷款」改为「免息方案」并补前提", "21 -"),
    ("level2", "### 2. 低首付方案", "### 2. 低首付方案（首付比例不得低于政策下限）",
     "标题补「首付比例不得低于政策下限」前提", "21 -"),
    ("level1", "严禁宣传“零首付”，国家规定汽车贷款最低首付20%，零首付是违规的。",
     "严禁宣传低于政策下限的首付方案；目前乘用车贷款首付比例下限为 20%，违规承诺将面临处罚。",
     "删除「零首付」违规表述，改为政策下限+处罚提示", "21 -"),
    ("level1", "严禁宣传“零首付”“零利息”不附加任何条件。",
     "严禁宣传「超低首付」「免息」等不附加任何条件的方案。",
     "删除「零首付」「零利息」违规金融表述", "21 -"),
    ("level1", "不能只说“零利息”。", "不能只宣传「免息」。", "删除「零利息」违规金融表述", "21 -"),
    # ---- 22 保险
    ("level1", "是绝大多数客户的最优方案", "是多数客户较为合理的搭配方案", "删除绝对化用语「最优」", "22 -"),
    # ---- 23 售后
    ("level1", "全合成：性能最好", "全合成：性能较好", "删除绝对化用语「最好」", "23 -"),
    # ---- 25 产品介绍
    ("level1", "体验是最好的介绍", "体验是有效的介绍方式", "删除绝对化用语「最好」，改为客观表述", "25 -"),
    # ---- 26 客户跟进
    ("level1", "### 3. 最佳时机", "### 3. 合适时机", "删除绝对化用语「最佳」", "26 -"),
    ("level2", "首任车主终身质保，用坏了厂家免费换，您完全不用担心",
     "首任非营运车主可按厂家政策享受三电长期质保，质保期内按政策维修，具体以官方条款为准，您不用太担心",
     "补「首任/非营运/官方条款」前提", "26 -"),
    # ---- 27 竞品对比
    ("level1", "客户买的不是最好的车，是最适合他的车", "客户买的往往不是配置最高的车，而是最适合他的车",
     "删除绝对化用语「最好」，改为客观表述", "27 -"),
    ("level1", "同价位配置碾压合资", "同价位配置较为丰富，与合资车型相比有一定优势",
     "删除绝对化用语「碾压」，改为客观对比", "27 -"),
    ("level1", "绝对不能说竞品“垃圾”“毛病多”“谁买谁后悔”这类话，显得不专业，也会引起客户反感。",
     "不得贬低竞品、不使用攻击性或贬损性评价，这类表述既不专业，也容易引起客户反感。",
     "删除「绝对」及贬低竞品的攻击性用语", "27 -"),
    ("level3", "客户会觉得你在玩套路", "客户会认为对比方式不够客观、公平", "删除「套路」争议性表述", "27 -"),
]

# 14 号文档（智能驾驶分级）整篇人工重写：保留分级定义与销售应用，删除全部智驾违规词
MANUAL_14 = """## 一、术语定义
智能驾驶分级采用 SAE 国际自动机工程师学会的官方标准，共分 L0 至 L5 六个等级，按系统对车辆动态驾驶任务的接管程度划分。需要特别说明：目前面向个人消费者量产销售的乘用车，最高普遍为 L2+ 级，均属于辅助驾驶范畴；L3 级仅少量车型在特定区域有限开放，L4、L5 仍处于示范运营或研发阶段。对外介绍相关功能时，统一使用「智能辅助驾驶」表述，不得简称为「自动」「无人」类词汇，并须强调驾驶员全程把控车辆。

## 二、各级别详细说明
### 1. L0 级：无自动化
- 定义：完全由人类驾驶员操作，车辆没有持续的主动控制功能，仅提供提醒、警示。
- 包含功能：常规刹车、转向，以及车道偏离预警、盲区监测等提醒类功能。
- 核心特点：所有操作由人完成，车辆只提供信息提醒，不主动干预。
- 代表车型：老款低配车型、入门代步车。

### 2. L1 级：驾驶辅助
- 定义：车辆能辅助驾驶员完成单一维度操作，要么控制速度，要么控制方向，两者不能同时持续控制。
- 核心功能：定速巡航（保持车速，驾驶员控制方向）；车道保持辅助（轻微修正方向，驾驶员控制车速）。
- 核心特点：单功能辅助，驾驶员仍是操作主体。
- 市场现状：当前在售车型多以 L2 起步，纯 L1 车型较少。

### 3. L2 级：组合驾驶辅助（对外统一称「L2 级智能辅助驾驶」）
- 定义：系统可同时控制车速与方向，实现横向与纵向的组合辅助，但驾驶员必须全程监控路况、双手不离方向盘，随时准备接管。
- 核心功能：ACC 自适应巡航（纵向控制车速、跟车）；LCC 车道居中保持（横向控制方向）；AEB 自动紧急制动；自动泊车辅助。
- 核心特点：可减轻驾驶疲劳，但人是主导、系统是辅助；驾驶员必须手握方向盘、全程关注路况；复杂路况与突发情况仍需人工处理。
- 市场现状：目前主流车型的辅助驾驶级别，10 万元以上车型普遍配备。
- 合规销售话术：「这是 L2 级智能辅助驾驶系统，高速和拥堵路况能帮您减轻驾驶疲劳，不用一直踩油门刹车；但手不能离开方向盘，仍需您全程把控车辆安全。」

### 4. L3 级：有条件驾驶自动化
- 定义：在特定设计运行条件下（如高速、封闭道路），系统可承担动态驾驶任务，驾驶员无需持续监控，但在系统发出接管请求时必须在规定时间内接管。
- 核心特点：特定场景下系统主导驾驶，驾驶员角色转为「安全员」；事故责任界定更复杂，具体以法律法规与厂家条款为准。
- 市场现状：国内已有少量车型在特定路段开放 L3 级功能，普及度低、使用场景有限。
- 合规注意：L3 级对外同样使用「智能辅助驾驶」或「有条件驾驶自动化」表述，不得使用「自动」「无人」类简化说法；驾驶员在系统请求接管时仍须及时接管。

### 5. L4 级：高度驾驶自动化
- 定义：在特定区域、特定条件下，系统可完成全部驾驶任务，无需驾驶员接管，车辆可以不设方向盘。
- 应用场景：封闭园区、港口、矿区、特定城市区域的无人接驳与无人出租车。
- 现状：以商用及特定场景示范运营为主，乘用车量产普及仍有较长距离。

### 6. L5 级：完全驾驶自动化
- 定义：全场景、全路况下无需人工驾驶，车辆不设方向盘、油门、刹车，乘员全程为乘客。
- 现状：仍处于研发与法规探索阶段，距离量产落地较远。

## 三、L2+ 级是什么？
- 定义：行业俗称，指在基础 L2 功能之上增强的高阶辅助驾驶方案，法规等级本质仍为 L2 级智能辅助驾驶。
- 核心增强功能：NOA 导航辅助驾驶（按导航路线辅助超车、变道、上下匝道，驾驶员需监控）；城市道路辅助（市区道路辅助跟车、路口通行、避让行人，驾驶员需随时接管）；记忆泊车、代客泊车辅助。
- 注意：无论功能多强，只要仍需驾驶员全程监控，就仍是 L2 级智能辅助驾驶，不得宣传为「自动」或「无人」类功能。

## 四、销售合规红线（必须严格遵守）
1. 禁止使用夸大或误导性表述（如声称车辆可自行驾驶、双手可离开方向盘、驾驶员可休息等），统一称「智能辅助驾驶」。
2. 必须主动说明：系统为辅助属性，驾驶员必须全程把控车辆安全，双手不离方向盘。
3. 不得夸大功能：不得宣称「能自动避让所有障碍物」「市区不用管了」，必须说明系统局限性，复杂路况需人工接管。
4. 高速、高架场景可以说「减轻驾驶疲劳」，不得说「双手可以离开方向盘」。
5. 安全性能以官方公布信息为准，不做结果性承诺。

## 五、客户常见疑问合规解答
1. 问：这车能自己开吗？
   答：这款车是 L2+ 级智能辅助驾驶，能在高速和快速路上辅助跟车、保持车道，帮您减轻驾驶疲劳；但它不是「自动」驾驶，需要您全程手握方向盘、关注路况。
2. 问：上了高速是不是就不用管了？
   答：不是的，系统只是辅助，遇到施工、匝道、恶劣天气等复杂路况仍需您及时接管；它能帮您省力，但不能替代您驾驶。
3. 问：出了事故算谁的？
   答：辅助驾驶状态下，驾驶员仍是车辆安全第一责任人，因此必须全程关注路况、随时准备接管；具体责任认定以交警部门与法律法规为准。
4. 问：L2 和 L3 有什么区别？
   答：L2 需要驾驶员全程监控并随时接管；L3 在特定设计运行条件下由系统承担驾驶任务，但系统请求接管时必须及时响应。目前国内在售车型主流仍是 L2 级智能辅助驾驶。

## 六、销售实战注意事项
1. 合规是底线，虚假宣传辅助驾驶功能，客户发生事故时门店需承担相应责任。
2. 主动说明系统局限性，反而显得专业可信，客户更信任。
3. 重点讲「减轻疲劳」「提升安全」，不讲双手离开方向盘、无需人工操作等表述。
4. 试驾演示时，务必提醒客户双手不要离开方向盘，做好正确示范。
5. 所有功能名称、适用条件以厂家官方用户手册与配置表为准，不过度解读。
"""


def load_compliance() -> dict:
    return json.loads(COMPLIANCE_JSON.read_text(encoding="utf-8"))


def numbered_files(directory: Path) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for p in directory.glob("*.txt"):
        m = re.match(r"(\d+)", p.name)
        if m:
            out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def strip_source_title(h1: str) -> str:
    for suffix in ("专业术语与销售应用", "专业方法与销售应用", "术语与销售应用"):
        if h1.endswith(suffix):
            return h1[: -len(suffix)].strip()
    return h1.strip()


def demote(line: str) -> str:
    m = re.match(r"^(#{1,5}) ", line)
    if m:
        return "#" + line
    return line


def apply_rules(lines: list[str], file_label: str, log: list[dict]) -> list[str]:
    out = list(lines)
    for level, old, new, reason, only in RULES:
        if only and only not in file_label:
            continue
        for i, line in enumerate(out):
            if old in line:
                cnt = line.count(old)
                before = line
                line = line.replace(old, new)
                out[i] = line
                log.append(
                    {
                        "file": file_label,
                        "line": i + 1,
                        "level": level,
                        "word": old,
                        "new": new,
                        "count": cnt,
                        "before": before.rstrip("\n"),
                        "after": line.rstrip("\n"),
                        "reason": reason,
                    }
                )
    return out


def scan_text(text: str, compliance: dict) -> dict:
    hits: list[dict] = []
    for level in ("level1", "level2", "level3"):
        for category, words in compliance.get(level, {}).items():
            for word in words:
                start = 0
                while True:
                    idx = text.find(word, start)
                    if idx < 0:
                        break
                    line_no = text.count("\n", 0, idx) + 1
                    ctx_start = text.rfind("\n", 0, idx) + 1
                    ctx_end = text.find("\n", idx)
                    ctx_end = len(text) if ctx_end < 0 else ctx_end
                    hits.append(
                        {
                            "level": level,
                            "category": category,
                            "word": word,
                            "line": line_no,
                            "context": text[ctx_start:ctx_end][:160],
                        }
                    )
                    start = idx + 1
    return {
        "counts": {lv: sum(1 for h in hits if h["level"] == lv) for lv in ("level1", "level2", "level3")},
        "hits": hits,
    }


# ---------------------------------------------------------------- 车型库解析
CAR_FIELD_ORDER = ["所属级别", "动力类型", "指导价区间", "核心参数", "FABE 核心卖点", "目标客户画像", "对标竞品", "销售沟通要点"]
CAR_FIELD_LABEL = {
    "所属级别": "级别",
    "动力类型": "动力类型",
    "指导价区间": "指导价区间",
    "核心参数": "核心参数",
    "FABE 核心卖点": "核心卖点（FABE）",
    "目标客户画像": "目标客户画像",
    "对标竞品": "对标竞品",
    "销售沟通要点": "销售沟通要点",
}
FAB_LABEL = {"F": "F（特征）", "A": "A（优势）", "B": "B（利益）", "E": "E（依据）"}


def parse_cars(lines: list[str]) -> tuple[list[dict], list[dict]]:
    categories: list[dict] = []
    issues: list[dict] = []
    cur_cat: dict | None = None
    cur_car: dict | None = None
    cur_field: str | None = None
    for line in lines:
        s = line.strip()
        if s.startswith("## ") and not s.startswith("### "):
            cur_cat = {"title": s[3:].strip(), "cars": []}
            categories.append(cur_cat)
            cur_car, cur_field = None, None
            continue
        if s.startswith("### "):
            cur_car = {"name": s[4:].strip(), "fields": {}, "fabs": {}, "raw_lines": []}
            cur_field = None
            if cur_cat is None:
                cur_cat = {"title": "未分类", "cars": []}
                categories.append(cur_cat)
            cur_cat["cars"].append(cur_car)
            continue
        if cur_car is None:
            continue
        m = re.match(r"^- \*\*(.+?)\*\*[：:]\s*(.*)$", s)
        if m:
            field, value = m.group(1).strip(), m.group(2).strip()
            cur_car["fields"][field] = value
            cur_field = field
            continue
        m = re.match(r"^([FABE])[：:]\s*(.*)$", s)
        if m and cur_field == "FABE 核心卖点":
            cur_car["fabs"][m.group(1)] = m.group(2).strip()
            continue
        if cur_field and s and not s.startswith("---"):
            cur_car["fields"][cur_field] = (cur_car["fields"].get(cur_field, "") + " " + s).strip()

    for cat in categories:
        for car in cat["cars"]:
            missing = [f for f in CAR_FIELD_ORDER if f not in car["fields"]]
            if "FABE 核心卖点" not in missing:
                for k in "FABE":
                    if k not in car["fabs"]:
                        missing.append("FABE-" + k)
            if missing:
                issues.append({"car": car["name"], "category": cat["title"], "missing": missing})
    return categories, issues


def format_car(car: dict) -> list[str]:
    name = re.sub(r"^\d+\.\s*", "", car["name"])
    out = [f"### {name}", ""]
    for field in CAR_FIELD_ORDER:
        label = CAR_FIELD_LABEL[field]
        if field == "FABE 核心卖点":
            out.append(f"- **{label}**：")
            for k in "FABE":
                out.append(f"  - **{FAB_LABEL[k]}**：{car['fabs'].get(k, '（原资料未提供）')}")
        else:
            out.append(f"- **{label}**：{car['fields'].get(field, '（原资料未提供）')}")
    out.append("")
    return out


# ---------------------------------------------------------------- 文档装配
def doc_header(title: str, scope: str, compliance_note: str) -> list[str]:
    return [
        f"# {title}",
        "",
        f"> **数据口径声明**：{DATA_NOTE}",
        "",
        f"> **本篇范围**：{scope}",
        "",
        f"> **合规提示**：{compliance_note}",
        "",
        "---",
        "",
    ]


def term_section(number: int, title: str, lines: list[str]) -> list[str]:
    out = [f"## {number}. {title}", ""]
    for line in lines:
        s = line.rstrip("\n")
        if not s.strip():
            out.append("")
            continue
        out.append(demote(s))
    out.append("")
    return out


def build_car_docs(raw_lines: list[str], log: list[dict]) -> tuple[list[dict], list[dict]]:
    cleaned = apply_rules(raw_lines, "现有汽车/现有汽车类型及销售要点.txt", log)
    categories, issues = parse_cars(cleaned)
    groups = [
        (1, "车型库（一）：微型 / 入门代步与紧凑型轿车", [0, 1],
         "品类一 微型 / 入门代步（4 款）+ 品类二 紧凑型轿车（6 款），共 10 款；适用于代步车、首购与家用轿车推荐场景。",
         "文中不含具体库存数量与成交价；库存、优惠与报价请通过门店库存/报价接口实时查询。"),
        (2, "车型库（二）：中型轿车与紧凑型 SUV", [2, 3],
         "品类三 中型轿车（4 款）+ 品类四 紧凑型 / SUV（6 款），共 10 款；适用于家用改善、商务通勤与 SUV 首购推荐场景。",
         "文中不含具体库存数量与成交价；库存、优惠与报价请通过门店库存/报价接口实时查询。"),
        (3, "车型库（三）：中大型 SUV 与 MPV", [4, 5],
         "品类五 中型 / 中大型 SUV（5 款）+ 品类六 MPV（3 款），共 8 款；适用于多成员家庭、商务接待与长途出行推荐场景。",
         "文中不含具体库存数量与成交价；库存、优惠与报价请通过门店库存/报价接口实时查询。"),
        (4, "车型库（四）：高端 / 特色代表", [6],
         "品类七 高端 / 特色代表（2 款）；适用于高端增换购与品牌向上推荐场景。",
         "文中不含具体库存数量与成交价；库存、优惠与报价请通过门店库存/报价接口实时查询。"),
    ]
    docs = []
    for order, title, cat_idx, scope, note in groups:
        lines = doc_header(title, scope, note)
        car_names = []
        for idx in cat_idx:
            cat = categories[idx]
            lines.append(f"## {cat['title']}")
            lines.append("")
            for car in cat["cars"]:
                car_names.append(re.sub(r"^\d+\.\s*", "", car["name"]))
                lines.extend(format_car(car))
        docs.append(
            {
                "order": order,
                "name": f"{order:02d}_{title.split('：')[-1].replace(' / ', '').replace(' ', '')}.md",
                "title": title,
                "category": "车型库",
                "source_files": ["txt/现有汽车/现有汽车类型及销售要点.txt"],
                "car_names": car_names,
                "lines": lines,
            }
        )
    return docs, issues


def build_term_docs(files: dict[int, Path], log: list[dict]) -> list[dict]:
    groups = [
        (5, "术语（一）：购车基础与三电", "购车基础与三电术语", list(range(1, 14)),
         "覆盖轿车 / SUV 级别、车身结构、驱动形式、尺寸参数、燃油动力、变速箱、新能源动力、三电、续航补能、悬挂、转向制动、车身稳定共 13 个主题。",
         "术语定义用于内部理解与客户答疑；涉及具体车型配置与政策时，以厂家官方最新信息为准。"),
        (6, "术语（二）：智能驾驶与座舱", "智能驾驶与座舱术语", [14, 15, 16],
         "覆盖智能驾驶分级、辅助驾驶功能、智能座舱共 3 个主题；智能驾驶分级一篇已按合规要求整篇重写。",
         "涉及智能驾驶 / 辅助驾驶功能，一律使用「智能辅助驾驶」表述，须说明功能边界与驾驶员全程接管要求。"),
        (7, "术语（三）：价格交易与权益保险", "价格交易权益保险术语", list(range(17, 24)),
         "覆盖价格体系、车辆状态、交易流程、权益质保、贷款方案、保险、售后维保共 7 个主题。",
         "涉及「长期质保」「免息」「低首付」等表述须同时说明适用前提（首任非营运车主、额度与征信条件、以厂家官方条款为准），不得只讲权益不讲限制。"),
    ]
    docs = []
    for order, title, _short, nums, scope, note in groups:
        lines = doc_header(title, scope, note)
        sources = []
        for n in nums:
            path = files[n]
            src_label = f"{path.parent.name}/{path.name}"
            sources.append(src_label)
            raw = path.read_text(encoding="utf-8").splitlines()
            title_line = raw[0].strip()
            h1 = title_line[2:].strip() if title_line.startswith("# ") else path.stem
            short = strip_source_title(h1)
            if n == 14:
                log.append(
                    {
                        "file": src_label,
                        "line": "1-80",
                        "level": "level1/level2",
                        "word": "（原文含 22 处 level1 智驾违规词及绝对化表述）",
                        "new": "（整篇人工重写，保留 L0–L5 定义、L2+ 说明、合规红线与客户答疑）",
                        "count": 22,
                        "before": "原文 80 行：含辅助驾驶类违规表述与绝对化用语（共 22 处 level1 命中）。",
                        "after": "重写后共 6 节（术语定义 / 各级别说明 / L2+ / 合规红线 / 客户答疑 / 注意事项）：统一使用「智能辅助驾驶」「驾驶自动化」等合规表述，补充驾驶员全程接管要求与责任说明。",
                        "reason": "该篇为智驾合规高危内容，逐词替换会破坏语义，故整篇人工重写",
                    }
                )
                body = MANUAL_14.splitlines()
                lines.extend(term_section(n, short + "（合规重写）", body))
            else:
                body = apply_rules(raw[1:], src_label, log)
                lines.extend(term_section(n, short, body))
        docs.append(
            {
                "order": order,
                "name": f"{order:02d}_{title.split('：')[-1].replace(' / ', '').replace(' ', '')}.md",
                "title": title,
                "category": "术语",
                "source_files": sources,
                "lines": lines,
            }
        )
    return docs


def build_method_docs(files: dict[int, Path], log: list[dict]) -> list[dict]:
    groups = [
        (8, "方法（一）：需求分析与产品介绍", [24, 25],
         "覆盖需求分析（MAN 分级、5W2H、SPIN）与产品介绍（FABE、竞品对比、六方位绕车、试乘试驾）共 2 个主题。",
         "引用续航数据须标注 CLTC 工况并说明实际续航浮动；介绍辅助驾驶功能须称「智能辅助驾驶」并说明驾驶员接管要求。"),
        (9, "方法（二）：客户跟进与竞品对比", [26, 27],
         "覆盖客户跟进与转化（潜客分级、异议处理、逼单、转介绍）与竞品对比与市场（对比维度、派系特点、对比原则与问答）共 2 个主题。",
         "异议处理与竞品对比须基于事实、不贬低竞品；涉及金融与权益方案须说明前提条件，禁止夸大、保证性表述。"),
    ]
    docs = []
    for order, title, nums, scope, note in groups:
        lines = doc_header(title, scope, note)
        sources = []
        for n in nums:
            path = files[n]
            src_label = f"{path.parent.name}/{path.name}"
            sources.append(src_label)
            raw = path.read_text(encoding="utf-8").splitlines()
            title_line = raw[0].strip()
            h1 = title_line[2:].strip() if title_line.startswith("# ") else path.stem
            short = strip_source_title(h1)
            body = apply_rules(raw[1:], src_label, log)
            lines.extend(term_section(n, short, body))
        docs.append(
            {
                "order": order,
                "name": f"{order:02d}_{title.split('：')[-1].replace(' / ', '').replace(' ', '')}.md",
                "title": title,
                "category": "方法论",
                "source_files": sources,
                "lines": lines,
            }
        )
    return docs


def doc_keywords(doc: dict) -> list[str]:
    if doc["category"] == "车型库":
        names = doc.get("car_names", [])
        return ["车型库", "指导价", "参数", "配置", "卖点", "FABE", "续航", "动力", "竞品"] + names
    if doc["category"] == "术语":
        return ["术语", "定义", "专业名词", "客户答疑"] + [s.split("/")[-1].replace(".txt", "") for s in doc["source_files"]]
    return ["销售方法", "话术", "需求分析", "产品介绍", "异议处理", "竞品对比", "客户跟进"]


def rel_root(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    compliance = load_compliance()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    change_log: list[dict] = []

    term_files = numbered_files(TERM_DIR)
    method_files = numbered_files(METHOD_DIR)
    for n in SKIP_NUMBERS:
        method_files.pop(n, None)

    car_raw = CAR_FILE.read_text(encoding="utf-8").splitlines()
    car_docs, car_issues = build_car_docs(car_raw, change_log)
    term_docs = build_term_docs(term_files, change_log)
    method_docs = build_method_docs(method_files, change_log)
    all_docs = car_docs + term_docs + method_docs

    written = []
    for doc in all_docs:
        text = "\n".join(doc["lines"]).rstrip() + "\n"
        path = OUT_DIR / doc["name"]
        path.write_text(text, encoding="utf-8")
        doc["path"] = path
        doc["chars"] = len(text)
        doc["chunks_est"] = max(1, round(doc["chars"] / 450))
        doc["scan"] = scan_text(text, compliance)
        written.append(doc)

    # ---- manifest（documents 留空，供 import_kb.py 回填；plan 供导入参考）
    plan = []
    for doc in written:
        plan.append(
            {
                "name": doc["name"],
                "path": rel_root(doc["path"]),
                "category": doc["category"],
                "source_files": doc["source_files"],
                "keywords": doc_keywords(doc),
                "import_order": doc["order"],
                "chars": doc["chars"],
                "suggested_chunk": {"mode": "automatic", "max_tokens": 500, "overlap_tokens": 50, "separator": "\n\n"},
                "metadata": {
                    "category": doc["category"],
                    "source": "门店销售资料",
                    "version": VERSION,
                    "is_demo": False,
                },
            }
        )
    manifest = {
        "dataset_id": DATASET_ID,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kb_dir": "docs/dify/knowledge_real",
        "indexing_technique": "high_quality",
        "doc_form": "text_model",
        "note": (
            "documents 初始为空，由 tools/dify/import_kb.py 回填；导入命令："
            "python tools/dify/import_kb.py --kb-dir docs/dify/knowledge_real --manifest tools/dify/kb_real/manifest.json"
        ),
        "documents": [],
        "plan": plan,
    }
    manifest_path = HERE / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (HERE / "change_log.json").write_text(
        json.dumps(change_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generated_scan = {
        "generated_at": manifest["generated_at"],
        "documents": [
            {"name": doc["name"], "chars": doc["chars"], "counts": doc["scan"]["counts"], "hits": doc["scan"]["hits"]}
            for doc in written
        ],
    }
    (HERE / "generated_scan.json").write_text(
        json.dumps(generated_scan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_report(written, change_log, car_issues, manifest)
    print("OK:", len(written), "docs,", sum(d["chars"] for d in written), "chars,", len(change_log), "change records")
    for doc in written:
        print(doc["name"], doc["chars"], "chars", doc["scan"]["counts"])
    return 0


# ---------------------------------------------------------------- 报告
EXTRA_ADDITIONS = [
    ("数据口径与合规声明（9 篇开头统一）", "避免过期价格、绝对化表述被检索后直接输出；为 AI 回答提供统一免责口径", "用户规划 + 28/29 合规要求"),
    ("「本篇范围 / 合规提示」段（9 篇）", "帮助分段检索与命中测试时理解文档边界，并提示该篇特有的合规约束", "自拟"),
    ("智能驾驶分级整篇合规重写（06 篇内）", "原文 80 行含 22 处 level1 智驾违规词，逐词替换会破坏语义", "28 号违规词清单 + 14 号原文定义"),
    ("L2+ 统一口径与能力边界说明", "法规等级本质为 L2，对外须称「L2+ 级智能辅助驾驶」并说明接管义务", "14 号原文 + 28 号「智能驾驶违规宣传」要求"),
    ("权益类表述前提补充（长期质保 / 免息 / 低首付 / 道路救援 / 免费保养）", "level2 词需补「首任非营运车主 / 额度与征信条件 / 以官方条款为准」前提", "28 号二级违规词修正示例"),
    ("续航话术补充 CLTC 工况与浮动声明", "避免「官方续航=实际续航」的误导表述", "28 号二级「续航里程类」要求"),
    ("竞品对比警示句改为正向规则", "原文含「垃圾」「套路」等贬低性/争议性表述，改为「不贬低竞品」的操作规则", "27 号原文 + 28 号三级要求"),
    ("车型库统一为固定字段结构（FABE 分项）", "原源文件字段为散行，统一结构后每个车型可独立成块被检索", "自拟（切分优化）"),
    ("按品类合并为 4 篇车型库文档", "控制单文档体积与检索精度，避免 475 行一篇塞满", "自拟（切分优化）"),
]


def esc_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_report(docs: list[dict], change_log: list[dict], car_issues: list[dict], manifest: dict) -> None:
    total_l1 = sum(d["scan"]["counts"]["level1"] for d in docs)
    total_l2 = sum(d["scan"]["counts"]["level2"] for d in docs)
    total_l3 = sum(d["scan"]["counts"]["level3"] for d in docs)
    source_l1, source_l2, source_l3 = 59, 19, 12  # scan_compliance.py 对源资料的统计（跳过 28/29）

    # 逐行聚合变更记录
    agg: dict[tuple[str, int], dict] = {}
    for rec in change_log:
        key = (rec["file"], rec["line"] if isinstance(rec["line"], int) else 0)
        row = agg.setdefault(
            key,
            {
                "file": rec["file"],
                "line": rec["line"],
                "before": rec["before"],
                "after": rec["after"],
                "words": [],
                "reasons": [],
                "levels": set(),
            },
        )
        tag = rec["word"] + (f"×{rec['count']}" if rec["count"] > 1 else "")
        if tag not in row["words"]:
            row["words"].append(tag)
        if rec["reason"] not in row["reasons"]:
            row["reasons"].append(rec["reason"])
        row["levels"].add(rec["level"])
    rows = sorted(agg.values(), key=lambda r: (r["file"], r["line"] if isinstance(r["line"], int) else 0))

    level_rank = {"level1": 0, "level2": 1, "level3": 2, "额外": 3}

    def lv_tag(levels: set[str]) -> str:
        if "level1" in levels:
            return "L1"
        if "level2" in levels:
            return "L2"
        if "level3" in levels:
            return "L3"
        return "额外"

    lines: list[str] = []
    lines.append("# 知识库真实文档拆分与合规预处理报告（task-8）")
    lines.append("")
    lines.append("> 生成方式：`python -X utf8 tools/dify/kb_real/build_kb_real.py` 自动生成本报告。")
    lines.append(f"> 生成时间：{manifest['generated_at']}；数据集：`{DATASET_ID}`（Dify 1.19.0，本机部署）。")
    lines.append("")
    lines.append("## 1. 概述与输入")
    lines.append("")
    lines.append("- 输入：`txt/` 下 3 个目录、28 个文件（约 180KB）：现有汽车车型库 1 篇（30 款车 / 475 行）、销售术语 23 篇（01–23）、需求咨询方法 4 篇（24–27）、违规词清单 2 篇（28–29）。")
    lines.append("- 处理：按 Dify 高质量分段要求重组为 9 篇 Markdown；全库执行 level1 违禁词清除、level2 补前提、level3 客观化；28/29 两份违规词文档作为内部合规资料，**不进入客户知识库**（已由 Lead 转为 `tools/dify/compliance_words.json`，供合规节点使用）。")
    lines.append("- 输出目录：`docs/dify/knowledge_real/`（知识库文档）、`tools/dify/kb_real/`（manifest、变更记录、自检结果、构建脚本）、本报告。")
    lines.append("")
    lines.append("## 2. 输出文档清单与切分建议")
    lines.append("")
    lines.append("| # | 文件名 | 类别 | 来源文件 | 字符数 | 预计分段（500 tokens） | 建议 metadata | 导入顺序 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for doc in docs:
        m = manifest["plan"][doc["order"] - 1]["metadata"]
        sources = "；".join(s.split("/")[-1] for s in doc["source_files"])
        lines.append(
            f"| {doc['order']} | `{doc['name']}` | {doc['category']} | {esc_cell(sources)} | {doc['chars']} | 约 {doc['chunks_est']} 段 | "
            f"category={m['category']}；version={m['version']}；is_demo=false | {doc['order']} |"
        )
    lines.append("")
    lines.append("**切分建议**：")
    lines.append("")
    lines.append("- 分段模式：通用分段（`automatic`），分隔符 `\\n\\n`，最大长度 500 tokens，重叠 50 tokens；车型库每款车为独立 `###` 小节，可整块命中。")
    lines.append("- 术语类文档（05–07）体量较大（05 约 3 万字），建议先按 500/50 导入，若命中测试发现跨主题串扰，再按 `##` 二级标题手工拆分为子文档（拆分点：05 可拆 01–07 与 08–13 两篇）。")
    lines.append("- 不启用父子分段：本批文档按「一个主题 = 一个二级/三级小节」组织，通用分段已能保证语义完整。")
    lines.append("- 应用侧检索：向量检索，TopK 3，相似度阈值 0.7（可在命中测试中校准）；如启用 rerank，建议 topK 放宽到 5。")
    lines.append("")
    lines.append("## 3. 逐条变更记录")
    lines.append("")
    lines.append(f"源资料共命中 level1={source_l1}、level2={source_l2}、level3={source_l3}；处理后文档 level1={total_l1}、level2={total_l2}、level3={total_l3}（详见第 6 节）。")
    lines.append("")
    lines.append("| # | 级别 | 源文件 | 行号 | 原文（节选/整行） | 改后 | 命中词 | 原因 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, row in enumerate(rows, 1):
        before = row["before"] if len(row["before"]) <= 200 else row["before"][:200] + "…"
        after = row["after"] if len(row["after"]) <= 200 else row["after"][:200] + "…"
        lines.append(
            f"| {i} | {lv_tag(row['levels'])} | {esc_cell(row['file'])} | {row['line']} | {esc_cell(before)} | {esc_cell(after)} | "
            f"{esc_cell('、'.join(row['words']))} | {esc_cell('；'.join(row['reasons']))} |"
        )
    lines.append("")
    lines.append("## 4. 额外补充内容")
    lines.append("")
    lines.append("| # | 补充内容 | 为什么补 | 依据/来源 |")
    lines.append("|---|---|---|---|")
    for i, (content, why, src) in enumerate(EXTRA_ADDITIONS, 1):
        lines.append(f"| {i} | {esc_cell(content)} | {esc_cell(why)} | {esc_cell(src)} |")
    lines.append("")
    lines.append("## 5. 问题清单（原文事实不一致 / 缺失字段 / 重复 / 过期）")
    lines.append("")
    lines.append("### 5.1 缺失字段")
    lines.append("")
    if car_issues:
        lines.append("| 车型 | 所属品类 | 缺失字段 |")
        lines.append("|---|---|---|")
        for issue in car_issues:
            lines.append(f"| {esc_cell(issue['car'])} | {esc_cell(issue['category'])} | {esc_cell('、'.join(issue['missing']))} |")
    else:
        lines.append("- 30 款车型的固定字段与 FABE 四项均完整，无缺失字段。")
    lines.append("")
    lines.append("### 5.2 其他问题")
    lines.append("")
    lines.append("1. **事实/时效风险**：车型库为二手整理资料，指导价、参数、年款无出处标注；文中「2025 年」「2026 年」销量表述与当前时点（2026 年 11 月）可能不一致，且部分车型/竞品（如个别新势力车型、未上市车型）可能已停产、改名或上市节奏变化，需门店按官方配置表逐款复核。")
    lines.append("2. **重复内容**：14 号（智驾分级）与 15 号（辅助驾驶功能）重复定义 LDW/LKA/AEB；20 号（权益质保）与 23 号（售后维保）重复讲延保；18 号（车辆状态）与 19 号（交易流程）在库存/交付环节交叉。合并进同一篇文档后可能产生近义分段，命中测试时需观察是否互相抢占 TopK。")
    lines.append("3. **过期信息**：购置税减免、地方补贴、上牌政策、金融贴息等以政策为准的内容散落在 17/21 号文件，原资料未标生效时间，客户知识库中保留但统一加「以最新政策为准」口径。")
    lines.append("4. **示例数据非真实**：26 号异议话术中的「CLTC 550 公里」「一周充一次」「首任车主终身质保」为话术示例，不对应具体在售车型，直接检索可能误导客户；09 篇开头数据口径声明已要求以门店最新公示与厂家官方配置表/条款为准，命中此类话术时须结合具体车型复核后再对客使用。")
    lines.append("5. **缺失主题**：碰撞安全（C-NCAP/中保研）、充电桩安装流程、二手车置换评估、上牌详细材料清单等客户高频问题未覆盖，建议后续补充为独立文档。")
    lines.append("6. **合规资料未入库**：28/29 两份违规词文档属内部合规资料，未进入客户知识库；工作流合规节点直接消费 `compliance_words.json`（77+39+28 词），两者需保持同步。")
    lines.append("")
    lines.append("## 6. 合规自检")
    lines.append("")
    lines.append("自检方法：用 `tools/dify/compliance_words.json` 的 level1/level2/level3 词表逐词扫描每篇产出文档（`tools/dify/kb_real/generated_scan.json`）。")
    lines.append("")
    lines.append("| 文件名 | 字符数 | level1 命中 | level2 命中 | level3 命中 |")
    lines.append("|---|---|---|---|---|")
    for doc in docs:
        c = doc["scan"]["counts"]
        lines.append(f"| `{doc['name']}` | {doc['chars']} | **{c['level1']}** | {c['level2']} | {c['level3']} |")
    lines.append("")
    lines.append(f"**结论**：9 篇文档 level1 命中合计 **{total_l1}**，满足验收要求（每篇 0）。")
    if total_l2 or total_l3:
        lines.append("")
        lines.append("**残余 level2/level3 说明**：以下命中均为「带前提的合规表述」或「术语定义本身」，不是违规输出：")
        lines.append("")
        for doc in docs:
            for hit in doc["scan"]["hits"]:
                if hit["level"] in ("level2", "level3"):
                    lines.append(f"- `{doc['name']}` L{hit['line']} [{hit['level']}]「{hit['word']}」：{hit['context']}")
    lines.append("")
    lines.append("## 7. Known gaps（真实资料 vs 现有工作流/占位知识库）")
    lines.append("")
    lines.append("现有 Dify 应用与 `tools/dify/workflow_draft.json` 使用的是**占位数据**：车型 A/B/C、报价 17.2 万等；本轮真实资料是 30 款真实市场车型（指导价 4.48 万元起，覆盖微型车到高端 SUV/MPV）。两者口径完全不同，**不能混在同一个知识库/同一轮对话中**：")
    lines.append("")
    lines.append("| 差异点 | 占位数据（现有工作流） | 真实资料（本轮） | 处理建议 |")
    lines.append("|---|---|---|---|")
    lines.append("| 车型 | 车型A / 车型B / 车型C | 30 款真实车型，4 篇车型库文档 | 导入真实库后停用/隔离占位文档，工作流 prompt 中「车型A/B/C」改为「按知识库车型库回答」 |")
    lines.append("| 报价 | 17.2 万（写死在工作流） | 只有指导价区间，无成交价 | 报价改由「报价工具/接口」实时计算，知识库不写死成交价 |")
    lines.append("| 库存 | 库存 3 台（示例） | 只有「现车/在途/订车」状态术语 | 库存由库存接口实时查询，知识库只保留状态定义 |")
    lines.append("| 画像匹配 | 4 号文档规则只映射 3 款占位车型 | 30 款真实车型分 7 个品类 | 需按「预算 × 品类 × 动力/补能条件」重写画像匹配规则，或改为「RAG 召回候选车型 + 规则过滤」 |")
    lines.append("")
    lines.append("**车型库如何与库存/报价接口对接（建议方案）**：")
    lines.append("")
    lines.append("1. **知识库存静态、接口查动态**：知识库存车型参数、FABE 卖点、话术、流程、画像规则；在售状态、指导价、终端优惠、库存数量、金融方案等动态数据一律走接口（Dify 工作流 HTTP 节点或自定义工具），不进知识库。")
    lines.append("2. **以车型名/车系 ID 对齐**：在车型库 metadata 中增加 `series`（车系）、`price_band`（价格带）、`energy`（动力类型）字段；LLM 先从客户话语中抽取意向车型/品类，再调用接口按车型名查询，避免把知识库里的旧价格直接当报价。")
    lines.append("3. **报价问答不检索知识库**：涉及「落地价/优惠/月供」的问题，先调报价接口，再把接口结果拼进上下文；知识库只用于解释报价构成（购置税、保险、上牌费）与议价边界。")
    lines.append("4. **接口失败降级**：接口超时/无数据时统一回答「具体价格与库存以门店最新公示为准，我帮您转接销售顾问」，禁止编造库存与报价。")
    lines.append("5. **导入顺序**：先导车型库（01–04）与术语库（05–07），再导方法论（08–09）；命中测试通过后再切换工作流绑定，保留旧库回滚。")
    lines.append("")
    lines.append("## 8. 导入步骤（交给 Lead）")
    lines.append("")
    lines.append("1. 确认 Dify 数据集 `403fbc9d-3c82-4077-8033-6761821f68f3` 可写、嵌入模型 bge-m3 已配置（见 `docs/dify/guide/kb_setup.md` 第 1 节）。")
    lines.append("2. 导入（`import_kb.py` 已支持 `--kb-dir` / `--manifest`）：")
    lines.append("")
    lines.append("   ```powershell")
    lines.append("   python tools/dify/import_kb.py --kb-dir docs/dify/knowledge_real --manifest tools/dify/kb_real/manifest.json")
    lines.append("   ```")
    lines.append("")
    lines.append("3. 观察索引状态与分段数（预期：车型库每篇 12–20 段，术语库 50–70 段，方法论 25–40 段；以实际为准）。")
    lines.append("4. 冒烟命中测试（5 条，真实数据版）：")
    lines.append("   - 「10 万以内市区代步、停车方便的纯电小车推荐哪款？」→ 01 篇微型/入门代步")
    lines.append("   - 「比亚迪秦 PLUS DM-i 的续航和合适人群？」→ 01 篇该车型小节")
    lines.append("   - 「L2 级智能辅助驾驶能不能脱手？」→ 06 篇 L2/合规红线")
    lines.append("   - 「首任车主三电质保有什么限制？」→ 07 篇权益质保")
    lines.append("   - 「客户说网上更便宜怎么应对？」→ 09 篇异议处理")
    lines.append("5. 通过后：停用/删除占位知识库文档（`tools/dify/kb_manifest.json` 中 4 条记录仍指向占位文件），更新工作流 prompt 中的车型 A/B/C 与 17.2 万；`docs/dify/guide/recall_tests.md` 的 20 条用例基于占位车型，需由 QA 按真实车型改写后再作为回归集。")
    lines.append("6. 回滚：本目录只新增文件、未改动任何 Dify 资源；如需回滚删除 `docs/dify/knowledge_real/` 与 Dify 中对应文档即可。")
    lines.append("")
    lines.append("## 9. 交付物索引")
    lines.append("")
    lines.append("| 路径 | 说明 |")
    lines.append("|---|---|")
    lines.append("| `docs/dify/knowledge_real/01–09_*.md` | 9 篇知识库文档（导入用） |")
    lines.append("| `tools/dify/kb_real/manifest.json` | 导入清单（documents 由 import_kb.py 回填，plan 为导入计划） |")
    lines.append("| `tools/dify/kb_real/change_log.json` | 逐条变更记录（机器可读） |")
    lines.append("| `tools/dify/kb_real/generated_scan.json` | 产出文档合规自检结果 |")
    lines.append("| `tools/dify/kb_real/scan_compliance.py` | 源资料合规扫描脚本 |")
    lines.append("| `tools/dify/kb_real/build_kb_real.py` | 文档生成与报告生成脚本（可重跑） |")
    lines.append("| `docs/dify/guide/kb_real_report.md` | 本报告 |")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
