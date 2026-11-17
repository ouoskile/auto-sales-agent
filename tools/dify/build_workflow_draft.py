#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 tools/dify/workflow_draft.json（Dify 1.19 Workflow 草稿提交体）。

用法：python tools/dify/build_workflow_draft.py
输出：tools/dify/workflow_draft.json
节点结构/字段依据：tools/dify/refs/app_ref_unzipped/app.yaml（1.19 导出样本）
+ 容器内 graphon 0.8.0 节点实体（/app/api/.venv/.../graphon/nodes/*/entities.py）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATASET_ID = "403fbc9d-3c82-4077-8033-6761821f68f3"
LLM_MODEL = {
    "provider": "langgenius/deepseek/deepseek",
    "name": "deepseek-flash",
    "mode": "chat",
    "completion_params": {"temperature": 0.3},
}
STUB_BASE = "http://host.docker.internal:8000"

OUT_DIR = Path(__file__).resolve().parent
OUT_FILE = OUT_DIR / "workflow_draft.json"


# ---------------------------------------------------------------- 合规校验（task-9）
# 词库与 Prompt 由 Lead 维护在 compliance_words.json，构建时读取并内联进 code 节点；
# 词库更新后重新执行本脚本 → 重新提交 draft 即可生效。
COMPLIANCE_FILE = OUT_DIR / "compliance_words.json"


def load_compliance() -> dict[str, Any]:
    words = json.loads(COMPLIANCE_FILE.read_text(encoding="utf-8"))
    level1: list[str] = []
    for group in words["level1"].values():
        for word in group:
            if word not in level1:
                level1.append(word)
    level1.sort(key=len, reverse=True)
    return {**words, "level1_flat": level1}


COMPLIANCE = load_compliance()
LEVEL1_WORDS = COMPLIANCE["level1_flat"]
COMPLIANCE_FALLBACK_TEXT = COMPLIANCE["fallback"]["hit_level1"]
COMPLIANCE_UNFIXABLE_TEXT = COMPLIANCE["fallback"]["llm_unfixable"]
COMPLIANCE_SYSTEM = COMPLIANCE["llm_compliance_system_prompt"].replace(
    "{{answer_text}}", "{{#compliance_scan.text#}}"
)

SCAN_CODE_TEMPLATE = '''import re

LEVEL1_WORDS = __LEVEL1_WORDS__


def _normalize(text):
    value = (text or "").lower()
    value = value.replace("％", "%").replace("　", "")
    return re.sub(r"\\s+", "", value)


def main(text: str) -> dict:
    """一级硬拦截扫词：命中任一 level1 词即 passed=False。"""
    raw = text or ""
    compact = _normalize(raw)
    hits = []
    for word in LEVEL1_WORDS:
        normalized = _normalize(word)
        if normalized and normalized in compact:
            hits.append(word)
    return {
        "passed": len(hits) == 0,
        "hit_words": "，".join(hits[:10]),
        "text": raw,
    }
'''

VERIFY_CODE_TEMPLATE = '''import re

LEVEL1_WORDS = __LEVEL1_WORDS__
UNFIXABLE_MARKER = "以上信息仅供参考"


def _normalize(text):
    value = (text or "").lower()
    value = value.replace("％", "%").replace("　", "")
    return re.sub(r"\\s+", "", value)


def main(llm_text: str, original_text: str) -> dict:
    """二级复核：LLM 修正后的文本不得再含 level1 词；若 LLM 整段返回兜底话术则判不可修正。"""
    raw = (llm_text or "").strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    compact = _normalize(raw)
    hits = []
    for word in LEVEL1_WORDS:
        normalized = _normalize(word)
        if normalized and normalized in compact:
            hits.append(word)
    # 仅当整段就是兜底话术时才判不可修正：正常回答末尾顺带一句“以上信息仅供参考…”不算。
    bare = re.sub(r"\\s+", "", raw)
    marker = re.sub(r"\\s+", "", UNFIXABLE_MARKER)
    is_fallback = bare.startswith(marker) and len(bare) <= 140
    passed2 = (len(hits) == 0) and (not is_fallback)
    flag = "passed" if (original_text or "").strip() == raw else "llm_fixed"
    return {
        "passed2": passed2,
        "final_text": raw,
        "hit_words2": "，".join(hits[:10]),
        "verify_flag": flag,
    }
'''

FINALIZE_CODE_TEMPLATE = '''FALLBACK_TEXT = __FALLBACK_TEXT__


def main(fallback_text: str, unfixable_text: str, fixed_text: str, verify_flag: str) -> dict:
    """合规链路唯一出口：按实际执行到的分支给出最终文本与合规标记。

    未执行分支的变量为 None/空串；判定顺序：三级兜底 > LLM 修正稿 > 一级拦截兜底。
    """
    fallback_text = (fallback_text or "").strip()
    unfixable_text = (unfixable_text or "").strip()
    fixed_text = (fixed_text or "").strip()
    if unfixable_text:
        return {"response": unfixable_text, "compliance_flag": "llm_unfixed"}
    if fixed_text:
        return {"response": fixed_text, "compliance_flag": verify_flag or "passed"}
    if fallback_text:
        return {"response": fallback_text, "compliance_flag": "blocked_level1"}
    return {"response": FALLBACK_TEXT, "compliance_flag": "blocked_level1"}
'''


SOURCES_CODE_TEMPLATE = '''import json


def main(response: str, compliance_flag: str, kb_models: list, kb_scripts: list) -> dict:
    """在最终回答末尾追加本次命中的知识库片段，并输出结构化 sources。

    只在 passed / llm_fixed 时追加；一级拦截或不可修正兜底不追加，避免把命中内容带出去。
    """
    text = (response or "").strip()
    flag = compliance_flag or ""
    rows = []
    seen = set()
    for items in (kb_models or [], kb_scripts or []):
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            content = " ".join(str(it.get("content") or "").split())
            if not content:
                continue
            meta = it.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            doc = it.get("title") or meta.get("document_name") or meta.get("doc_id") or "知识库文档"
            raw_score = it.get("score")
            if raw_score is None:
                raw_score = meta.get("score")
            try:
                score_text = f"{float(raw_score):.2f}"
            except (TypeError, ValueError):
                score_text = "-"
            key = (str(doc), content[:40])
            if key in seen:
                continue
            seen.add(key)
            rows.append({"document": str(doc), "score": score_text, "snippet": content[:90]})
            if len(rows) >= 3:
                break
        if len(rows) >= 3:
            break
    if not rows or flag not in ("passed", "llm_fixed"):
        return {"response": text, "sources": "", "compliance_flag": flag}
    lines = ["", "", "---", "参考来源（知识库检索，非实时价格/库存）："]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {row['document']} · 相关度 {row['score']} · {row['snippet']}")
    return {
        "response": text + "\\n".join(lines),
        "sources": json.dumps(rows, ensure_ascii=False),
        "compliance_flag": flag,
    }
'''


def _with_words(template: str) -> str:
    return template.replace(
        "__LEVEL1_WORDS__", json.dumps(LEVEL1_WORDS, ensure_ascii=False)
    )


def selector(node_id: str, variable: str) -> list[str]:
    return [node_id, variable]


def cond(
    node_id: str,
    variable: str,
    operator: str,
    value: Any,
    var_type: str,
) -> dict[str, Any]:
    return {
        "id": f"cond-{node_id}-{variable}-{operator}".replace(" ", "_"),
        "variable_selector": selector(node_id, variable),
        "comparison_operator": operator,
        "value": value,
        "varType": var_type,
    }


def llm(
    title: str,
    desc: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "llm",
        "title": title,
        "desc": desc,
        "model": {**LLM_MODEL, "completion_params": {"temperature": temperature}},
        "model_selector": None,
        "prompt_template": [
            {"role": "system", "text": system},
            {"role": "user", "text": user},
        ],
        "context": context or {"enabled": False, "variable_selector": []},
        "vision": {"enabled": False},
        # deepseek-flash 会输出 <think>…</think>，separated 让节点返回去掉
        # 推理标记的 clean text（reasoning_content 另存），避免污染最终回答。
        "reasoning_format": "separated",
    }


# ---------------------------------------------------------------- 提示词
INTENT_INSTRUCTION = """你是汽车门店销售接待前台的意图分类器。只判断用户这句话属于哪一类，不要回答用户问题。

分类标准：
1. 车型咨询：想了解车型、参数、续航、空间、配置、动力、安全，要求推荐车型，对比车型，问"家用/通勤买什么车合适"。
2. 报价库存：问价格、落地价、优惠、活动、现车、库存、提车周期、金融方案、置换、上牌费用、保险。
3. 预约试驾：想试驾、想看车、想约到店时间，或直接提供姓名/手机号要预约。
4. 价格异议：觉得贵、要求再便宜、说别家更便宜、说网上价格更低、质疑配置/续航/保值率、表达犹豫或砍价。
5. 闲聊无关：打招呼、感谢、告别、问天气/吃饭/写代码等与购车无关的内容。

多意图处理：一句话包含多个意图时，按优先级归类：预约试驾 > 报价库存 > 车型咨询 > 价格异议 > 闲聊无关。
判定时只看用户意图归属，不要回答用户的问题；边界模糊时选最接近的一类。"""

PROFILE_SYSTEM = """你是汽车门店销售顾问的需求分析师。任务：从用户对话中抽取客户画像字段，输出一个严格 JSON 对象。

字段定义：
- budget：购车预算，字符串。保留用户原话的量级，例如 "15万左右"、"12-20万"、"预算20万以上"。
- scene：主要用车场景，字符串。取值优先用 "通勤" / "家用" / "商务"，可组合，如 "家用+通勤"。
- family_num：家庭人数，字符串，例如 "3口之家"、"一家五口"、"两个人"。
- charge：是否有固定车位或家用充电桩，字符串。只能取 "有" / "无" / "不确定"。
- intend_car：意向车型或车型线索，字符串，例如 "五菱宏光 MINIEV"、"比亚迪海鸥"、"SUV"、"轿车"、"还没定"。
- missing：数组，列出上面 5 个字段中用户没有明确说到的字段名（英文键名），没有缺失就输出空数组。

硬性规则：
1. 只抽取用户明确表达的信息；没提到的字段一律填 null，绝不猜测、绝不用常识补全。
2. 用户说"随便看看""帮我推荐"但没有预算时，budget 填 null，不要默认 15 万。
3. 用户说"有车位"不等于"有充电桩"：只有明确提到充电桩/能装桩/可充电才填 "有"；只说车位则 charge 填 "不确定"。
4. 输出必须是单个 JSON 对象，不要 markdown 代码块、不要解释文字、不要前后缀。键名固定为 budget、scene、family_num、charge、intend_car、missing。"""

PROFILE_USER = """用户本句话：
{{#start.user_query#}}

请输出画像 JSON。"""

FOLLOWUP_SYSTEM = """你是汽车门店的销售助理，说话亲切、口语化，像真人顾问。当前客户信息不全，需要你追问补齐。

规则：
1. 只问缺失的信息，一次问完，最多 3 个问题，不要反复追问已有的信息。
2. 问题要具体、好回答，给出例子，例如"预算大概多少？12-20 万这个区间可以吗"。
3. 必须覆盖缺失字段对应的问题：预算 / 家用还是通勤 / 有无固定车位或充电桩。
4. 不要编造车型、价格、优惠；不要长篇推销。
5. 结尾用一句轻松的话鼓励客户回复，例如"您说个大概就行，我帮您筛两台合适的"。
6. 输出直接给客户看的话术，150 字以内，不要 JSON、不要标题、不要分点符号堆砌。"""

FOLLOWUP_USER = """缺失字段：{{#profile_parse.missing_text#}}
客户刚才说：{{#start.user_query#}}
已知画像：{{#profile_parse.profile_summary#}}
请生成追问话术。"""

# 检索词实测校准（v2 用旧 4 篇知识库做命中测试，top_k=5 无阈值）：
#   "画像+原话+检索目标" → 04(0.7567)、04(0.6882)、02(0.6864)、01_门店车型库(0.6344)
#   本模板（原话在前 + 画像 + 想了解关键词）→ 04(0.7048)、01_门店车型库(0.6155)、02(0.5963)
# 旧知识库在 top_k=3、阈值 0.5 下这样能召回 01_门店车型库（550km/2750mm 等参数）。
# v3 已换成真实知识库 9 篇（knowledge_real），车型名与参数以真实文档为准；
# 本模板保留「客户原话开头 + 关注点关键词」，如真实库召回分布变化需重新 hit-testing 校准。
KB_QUERY_TEMPLATE = """客户问题：{{ query }}
客户画像：{{ summary }}
想了解：续航 轴距 空间 配置 指导价"""

RECOMMEND_SYSTEM = """你是汽车门店的金牌销售顾问，按 FABE 结构给客户推荐车型。

规则：
1. 只推荐知识库上下文中真实存在的车型（例如 五菱宏光 MINIEV、比亚迪海鸥、零跑 A10 等），不得编造知识库中没有的车型，也不得编造任何参数；上下文没提到的车型与参数一律不说。
2. 每款车按 FABE 讲清楚：
   - F（Feature 配置/参数）：引用上下文里的真实参数（续航、轴距、能源类型、亮点配置）。
   - A（Advantage 优势）：这款车相对其他车型强在哪。
   - B（Benefit 利益）：对这位客户的具体用车场景意味着什么（例如带娃空间、通勤成本、长途补能）。
   - E（Evidence 依据）：用"知识库显示/门店资料"这类说法，不夸大。
3. 必须结合客户画像（预算、场景、家庭人数、充电条件）说明"为什么适合你"，并诚实点出 1 个"不一定适合的点"。
4. 如果上下文为空或没有可用车型信息：不要编造参数，直接说明"这部分资料需要销售顾问帮您确认"，并邀请到店/留资。
5. 涉及价格、优惠、库存、交付周期时，只说"以门店最新报价/库存为准"，不要给出具体数字。
6. 结尾主动邀约试驾，问一句方便的时间（例如"这周六上午还是周日下午方便？"）。
7. 输出给客户看的自然话术，结构清晰（可用短标题+短段落），300 字以内，不要 JSON、不要表格。"""

RECOMMEND_USER = """客户画像：{{#profile_parse.profile_summary#}}
客户原话：{{#start.user_query#}}
知识库检索结果：
{{#context#}}"""

QUOTE_EXTRACT_INSTRUCTION = """从用户的问题中提取"要查询库存/报价的车型"信息。
- brand：品牌名，用户没提就留空。
- model：车型名或车型线索，例如 五菱宏光 MINIEV、比亚迪海鸥、零跑 A10、SUV、轿车、混动、那台车。
- 只提取用户明确说过的内容，不要根据上下文猜测车型，不要编造。
- 如果用户只问"落地多少钱"而没提任何车型，model 留空。"""

QUOTE_REPLY_SYSTEM = """你是汽车门店的销售顾问，负责把库存/报价接口返回的数据整理成口语化的报价话术。

规则：
1. 只使用接口返回 JSON 里出现的字段和数字，不要编造价格、优惠、库存、交付周期。
2. 必须覆盖：车型、库存状态（有现车/需排期/需预订）、参考落地价、当前优惠方案、预计交付时间。
3. 把优惠说清楚（现金优惠/置换补贴/金融贴息/礼包），并说明可叠加情况以门店为准。
4. 结尾必须加一句"以上是门店参考价，最终价格以销售顾问现场核算为准"。
5. 如果接口返回里字段缺失或含义不明，就说"这部分需要顾问帮您确认"，不要猜数字。
6. 追问一句客户大概什么时候用车/是否方便到店，自然过渡到邀约。
7. 输出给客户看的自然话术，200 字以内，不要 JSON、不要 Markdown 表格。"""

QUOTE_REPLY_USER = """客户原话：{{#start.user_query#}}
库存/报价接口返回（JSON）：
{{#inventory_api.body#}}"""

QUOTE_FALLBACK_SYSTEM = """你是汽车门店销售顾问。现在库存/报价系统暂时无法返回数据，请生成一段得体的兜底话术。

规则：
1. 先致歉并说明"报价/库存系统暂时查询不到"。
2. 绝对不要编造库存状态、价格、优惠或交付时间。
3. 给客户两个可行选择：留手机号由顾问核实后回复；或直接到店看车（现车可当天试驾）。
4. 语气诚恳、简短（120 字以内），结尾用一个问题推进对话。"""

APPT_EXTRACT_INSTRUCTION = """从用户的话中提取预约试驾需要的 4 个要素。
- 只提取用户明确说出的内容，没提到就留空字符串，不要编造姓名、手机号或时间。
- 手机号必须原样保留 11 位数字（可去掉空格/横线）。
- 时间保留用户原话，不要自己换算成具体日期。
- 如果用户说"这周六"而没说具体几点，time 填"本周六"，不要补时间。"""

APPT_FOLLOWUP_SYSTEM = """你是汽车门店销售助理，客户想预约试驾但信息不全。请生成追问话术。

规则：
1. 只追问缺失的要素（姓名 / 手机号 / 意向车型 / 预约时间），已提供的不要重复问。
2. 一次问完所有缺失项，问题要具体，给出格式例子，例如"手机号方便留 11 位吗，用来给您排试驾"。
3. 说明用途：留手机号是为了安排试驾车和到店接待，不会骚扰。
4. 不编造车型库存和价格；语气亲切，100 字以内。
5. 输出直接给客户看的话术，不要 JSON。"""

APPT_FOLLOWUP_USER = """客户原话：{{#start.user_query#}}
已提取：姓名={{#appt_extract.name#}}；手机号={{#appt_extract.phone#}}；车型={{#appt_extract.model#}}；时间={{#appt_extract.time#}}
请生成追问。"""

APPT_CONFIRM_SYSTEM = """你是汽车门店销售助理。预约工单接口已返回结果，请生成给客户的确认话术。

规则：
1. 从接口返回 JSON 中提取：工单号 ticket_id、车型、预约时间、门店。
2. 明确告诉客户"预约已提交成功，顾问会在 30 分钟内电话确认"。
3. 提醒到店携带：身份证、驾驶证（试驾需要），以及可提前准备的问题。
4. 绝不要编造接口里没有的工单号、时间或门店名；字段缺失就只说"已提交，顾问确认后回复您具体安排"。
5. 语气热情、简短（120 字以内），结尾祝一句。"""

APPT_CONFIRM_USER = """客户原话：{{#start.user_query#}}
工单接口返回（JSON）：
{{#appt_api.body#}}"""

APPT_FALLBACK_SYSTEM = """你是汽车门店销售助理。预约接口提交失败（网络或系统原因），请生成兜底话术。

规则：
1. 先致歉，说明"预约系统暂时繁忙，没有提交成功"。
2. 不要谎称已经预约成功，不要编造工单号。
3. 请客户再发一次手机号/时间，或建议直接电话门店/到店登记。
4. 简短（100 字以内），语气负责。"""

OBJECTION_SYSTEM = """你是汽车门店经验丰富的销售顾问，专门处理客户的价格/配置异议。

规则：
1. 先共情认同（例如"理解，买车肯定要算清楚"），不要一上来就反驳。
2. 用价值拆解回应：把价格拆到配置、用料、续航、质保、用车成本、服务权益上，引用知识库话术里的具体点。
3. 价格类异议可给两种解法：置换补贴、金融方案（24 期 0 息等），帮客户把落地价算下来；但不能承诺额外降价或编造优惠。
4. 对比类异议（别家更便宜/网上更便宜）：说明报价口径差异（引流价、捆绑、是否含税险），强调门店报价透明，邀请到店核算。
5. 不贬低竞品，不说"网上都是假的"，不承诺成交价。
6. 客户没有指明具体车型时（例如只说"这个车太贵了""能不能便宜点"）：不要引用任何具体车型的参数（车长、续航、轴距、配置数量），先共情并讲通用价值与政策，再问客户关注的是具体哪一款（如五菱宏光 MINIEV、比亚迪海鸥），避免张冠李戴。
7. 如果知识库上下文为空：用通用异议处理框架回答，并说明具体政策以门店为准。
8. 结尾给一个明确下一步：到店对比/试驾/置换评估，并问客户方便时间。
9. 输出给客户看的自然话术，200 字以内，不要 JSON。"""

OBJECTION_USER = """客户原话：{{#start.user_query#}}
话术库检索结果：
{{#context#}}"""

SMALLTALK_TEMPLATE = """您好，我是门店的购车助手 😊
我主要帮您做三件事：按预算和用车场景推荐车型、查现车和落地价、约试驾。
您方便说下预算和主要用途吗？比如"15 万左右，家用，有固定车位"，我就能帮您筛两台合适的车。"""

PROFILE_PARSE_CODE = r'''import json
import re


def main(profile_raw: str, user_query: str) -> dict:
    """把 LLM 输出的画像 JSON 洗成稳定结构，并判断画像是否完整。"""
    text = (profile_raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    data = {}
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    def pick(key):
        value = data.get(key)
        if value is None:
            return ""
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return "、".join(str(x) for x in value if x not in (None, ""))
        return str(value).strip()

    budget = pick("budget")
    scene = pick("scene")
    family_num = pick("family_num")
    charge = pick("charge")
    intend_car = pick("intend_car")
    if charge not in ("有", "无", "不确定"):
        charge = "" if not charge else "不确定"

    # 完整画像的最小要求：预算 + 场景（或家庭人数）+ 充电条件
    missing = []
    if not budget:
        missing.append("预算")
    if not scene and not family_num:
        missing.append("主要用途（家用还是通勤）")
    if not charge:
        missing.append("有无固定车位/充电桩")

    summary_parts = []
    if budget:
        summary_parts.append("预算：" + budget)
    if scene:
        summary_parts.append("场景：" + scene)
    if family_num:
        summary_parts.append("家庭人数：" + family_num)
    if charge:
        summary_parts.append("充电条件：" + charge)
    if intend_car:
        summary_parts.append("意向车型：" + intend_car)

    profile = {
        "budget": budget or None,
        "scene": scene or None,
        "family_num": family_num or None,
        "charge": charge or None,
        "intend_car": intend_car or None,
    }
    return {
        "budget": budget,
        "scene": scene,
        "family_num": family_num,
        "charge": charge,
        "intend_car": intend_car,
        "profile_json": json.dumps(profile, ensure_ascii=False),
        "is_complete": len(missing) == 0,
        "missing_text": "、".join(missing),
        "profile_summary": "；".join(summary_parts) if summary_parts else "（用户尚未提供有效画像信息）",
    }
'''


# ---------------------------------------------------------------- 节点定义
def build_nodes() -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def add(
        node_id: str,
        title: str,
        data: dict[str, Any],
        x: float,
        y: float,
        height: int = 98,
    ) -> None:
        data = {"selected": False, **data}
        nodes.append(
            {
                "id": node_id,
                "type": "custom",
                "position": {"x": x, "y": y},
                "positionAbsolute": {"x": x, "y": y},
                "width": 242,
                "height": height,
                "selected": False,
                "sourcePosition": "right",
                "targetPosition": "left",
                "zIndex": 0,
                "data": data,
            }
        )

    add(
        "start",
        "开始",
        {
            "type": "start",
            "title": "开始",
            "desc": "接收用户输入 user_query；chat_history 可选，用于前端把上一轮追问拼进来",
            "variables": [
                {
                    "variable": "user_query",
                    "label": "用户问题",
                    "type": "text-input",
                    "required": True,
                    "max_length": 2000,
                    "default": "",
                    "hint": "客户这一轮说的话；补充追问时可把上一轮问答拼进来",
                    "placeholder": "例如：15 万左右，家用，有固定车位，帮我推荐一台 SUV",
                    "options": [],
                },
                {
                    "variable": "chat_history",
                    "label": "历史对话",
                    "type": "paragraph",
                    "required": False,
                    "max_length": 4000,
                    "default": "",
                    "hint": "可选；前端拼装的多轮历史，当前 Prompt 未引用",
                    "placeholder": "",
                    "options": [],
                },
            ],
        },
        0,
        400,
        120,
    )

    add(
        "intent_classifier",
        "意图分类",
        {
            "type": "question-classifier",
            "title": "意图分类",
            "desc": "5 类意图，分支 handle 即 class id：1 车型咨询 / 2 报价库存 / 3 预约试驾 / 4 价格异议 / 5 闲聊无关",
            "query_variable_selector": selector("start", "user_query"),
            "model": {**LLM_MODEL, "completion_params": {"temperature": 0.1}},
            "classes": [
                {"id": "1", "name": "车型咨询", "label": "车型咨询"},
                {"id": "2", "name": "报价库存", "label": "报价库存"},
                {"id": "3", "name": "预约试驾", "label": "预约试驾"},
                {"id": "4", "name": "价格异议", "label": "价格异议"},
                {"id": "5", "name": "闲聊无关", "label": "闲聊无关"},
            ],
            "instruction": INTENT_INSTRUCTION,
            "vision": {"enabled": False},
        },
        360,
        400,
        240,
    )

    # ---------------- 分支 1
    add(
        "profile_extract",
        "画像抽取",
        llm(
            "画像抽取",
            "从用户话里抽客户画像，输出严格 JSON；缺字段填 null",
            PROFILE_SYSTEM,
            PROFILE_USER,
            temperature=0.1,
        ),
        720,
        0,
        160,
    )
    add(
        "profile_parse",
        "画像解析",
        {
            "type": "code",
            "title": "画像解析",
            "desc": "解析画像 JSON，输出 is_complete / missing_text / profile_summary",
            "code_language": "python3",
            "code": PROFILE_PARSE_CODE,
            "variables": [
                {
                    "variable": "profile_raw",
                    "value_selector": selector("profile_extract", "text"),
                    "value_type": "string",
                },
                {
                    "variable": "user_query",
                    "value_selector": selector("start", "user_query"),
                    "value_type": "string",
                },
            ],
            "outputs": {
                "budget": {"type": "string", "children": None},
                "scene": {"type": "string", "children": None},
                "family_num": {"type": "string", "children": None},
                "charge": {"type": "string", "children": None},
                "intend_car": {"type": "string", "children": None},
                "profile_json": {"type": "string", "children": None},
                "is_complete": {"type": "boolean", "children": None},
                "missing_text": {"type": "string", "children": None},
                "profile_summary": {"type": "string", "children": None},
            },
        },
        1080,
        0,
        200,
    )
    add(
        "profile_check",
        "画像是否完整",
        {
            "type": "if-else",
            "title": "画像是否完整",
            "desc": "预算 + 用途 + 充电条件齐全才直接推荐，否则追问",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("profile_parse", "is_complete", "is", True, "boolean"),
                    ],
                }
            ],
        },
        1440,
        0,
    )
    add(
        "profile_followup",
        "画像追问",
        llm(
            "画像追问",
            "画像不全时生成追问话术，作为本轮结果返回",
            FOLLOWUP_SYSTEM,
            FOLLOWUP_USER,
            temperature=0.6,
        ),
        1800,
        200,
        160,
    )
    add(
        "kb_query_build",
        "检索词拼装",
        {
            "type": "template-transform",
            "title": "检索词拼装",
            "desc": "把客户画像 + 原话拼成知识库检索 query",
            "template": KB_QUERY_TEMPLATE,
            "variables": [
                {
                    "variable": "summary",
                    "value_selector": selector("profile_parse", "profile_summary"),
                },
                {"variable": "query", "value_selector": selector("start", "user_query")},
            ],
        },
        1800,
        0,
    )
    add(
        "kb_models",
        "车型知识检索",
        {
            "type": "knowledge-retrieval",
            "title": "车型知识检索",
            "desc": "汽车销售知识库，多路召回 top_k=3，阈值 0.5",
            "query_variable_selector": selector("kb_query_build", "output"),
            "query_attachment_selector": [],
            "dataset_ids": [DATASET_ID],
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": 3,
                "score_threshold": 0.5,
                "score_threshold_enabled": True,
                "reranking_enable": False,
                "reranking_mode": "reranking_model",
                "reranking_model": None,
                "weights": None,
            },
        },
        2160,
        0,
        140,
    )
    add(
        "recommend",
        "车型推荐",
        llm(
            "车型推荐",
            "基于知识库检索结果按 FABE 推荐 1-2 款车并邀约试驾",
            RECOMMEND_SYSTEM,
            RECOMMEND_USER,
            temperature=0.6,
            context={"enabled": True, "variable_selector": selector("kb_models", "result")},
        ),
        2520,
        0,
        170,
    )

    # ---------------- 分支 2
    add(
        "quote_extract",
        "报价要素抽取",
        {
            "type": "parameter-extractor",
            "title": "报价要素抽取",
            "desc": "抽取 brand/model 用于查库存与报价",
            "model": {**LLM_MODEL, "completion_params": {"temperature": 0.1}},
            "query": selector("start", "user_query"),
            "parameters": [
                {
                    "name": "brand",
                    "type": "string",
                    "options": [],
                    "description": "用户提到的品牌，如“五菱”“比亚迪”“零跑”；没提就留空，不要猜",
                    "required": False,
                },
                {
                    "name": "model",
                    "type": "string",
                    "options": [],
                    "description": "用户要问的车型，如“五菱宏光 MINIEV”“比亚迪海鸥”“SUV”“那台混动”；只从用户话里提取，没提留空",
                    "required": False,
                },
            ],
            "instruction": QUOTE_EXTRACT_INSTRUCTION,
            "reasoning_mode": "prompt",
            "vision": {"enabled": False},
        },
        720,
        440,
        200,
    )
    add(
        "inventory_api",
        "库存报价接口",
        {
            "type": "http-request",
            "title": "库存报价接口",
            "desc": "GET 宿主机 api_stub 的 /api/inventory（SSRF 已放行 192.168.65.0/24）",
            "method": "get",
            "url": STUB_BASE + "/api/inventory?brand={{#quote_extract.brand#}}&model={{#quote_extract.model#}}",
            "authorization": {"type": "no-auth", "config": None},
            "headers": "Accept: application/json",
            "params": "",
            "body": {"type": "none", "data": []},
            "timeout": {"connect": 5, "read": 10, "write": 5},
            "ssl_verify": True,
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 0},
            "error_strategy": "default-value",
            "default_value": [
                {"key": "status_code", "type": "number", "value": 0},
                {"key": "body", "type": "string", "value": ""},
                {"key": "headers", "type": "object", "value": {}},
            ],
        },
        1080,
        440,
        160,
    )
    add(
        "inventory_ok",
        "库存接口是否成功",
        {
            "type": "if-else",
            "title": "库存接口是否成功",
            "desc": "status_code == 200 走报价话术，否则走兜底",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("inventory_api", "status_code", "=", "200", "number"),
                    ],
                }
            ],
        },
        1440,
        440,
    )
    add(
        "quote_reply",
        "报价话术",
        llm(
            "报价话术",
            "把库存/报价接口 JSON 整理成口语化报价，注明以门店核算为准",
            QUOTE_REPLY_SYSTEM,
            QUOTE_REPLY_USER,
            temperature=0.5,
        ),
        1800,
        380,
        170,
    )
    add(
        "quote_fallback",
        "报价兜底",
        llm(
            "报价兜底",
            "库存/报价接口失败时的不编数字兜底话术",
            QUOTE_FALLBACK_SYSTEM,
            "客户原话：{{#start.user_query#}}",
            temperature=0.5,
        ),
        1800,
        600,
        150,
    )

    # ---------------- 分支 3
    add(
        "appt_extract",
        "预约要素抽取",
        {
            "type": "parameter-extractor",
            "title": "预约要素抽取",
            "desc": "抽取 name/phone/model/time 四个预约要素",
            "model": {**LLM_MODEL, "completion_params": {"temperature": 0.1}},
            "query": selector("start", "user_query"),
            "parameters": [
                {
                    "name": "name",
                    "type": "string",
                    "options": [],
                    "description": "客户姓名/称呼，如“张三”“王女士”；没提留空",
                    "required": False,
                },
                {
                    "name": "phone",
                    "type": "string",
                    "options": [],
                    "description": "11 位手机号，去掉空格和横线；没提留空",
                    "required": False,
                },
                {
                    "name": "model",
                    "type": "string",
                    "options": [],
                    "description": "意向车型，如“五菱宏光 MINIEV”“比亚迪海鸥”；没提留空",
                    "required": False,
                },
                {
                    "name": "time",
                    "type": "string",
                    "options": [],
                    "description": "预约时间，保留用户原话，如“本周六上午”“11 月 21 日 10 点”；没提留空",
                    "required": False,
                },
            ],
            "instruction": APPT_EXTRACT_INSTRUCTION,
            "reasoning_mode": "prompt",
            "vision": {"enabled": False},
        },
        720,
        840,
        220,
    )
    add(
        "appt_complete",
        "预约要素是否齐全",
        {
            "type": "if-else",
            "title": "预约要素是否齐全",
            "desc": "姓名/手机号/车型/时间四个都非空才提交工单",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("appt_extract", "name", "not empty", None, "string"),
                        cond("appt_extract", "phone", "not empty", None, "string"),
                        cond("appt_extract", "model", "not empty", None, "string"),
                        cond("appt_extract", "time", "not empty", None, "string"),
                    ],
                }
            ],
        },
        1080,
        840,
        160,
    )
    add(
        "appt_followup",
        "预约追问",
        llm(
            "预约追问",
            "预约要素不全时追问姓名/手机号/车型/时间",
            APPT_FOLLOWUP_SYSTEM,
            APPT_FOLLOWUP_USER,
            temperature=0.6,
        ),
        1440,
        1040,
        160,
    )
    add(
        "appt_api",
        "提交预约工单",
        {
            "type": "http-request",
            "title": "提交预约工单",
            "desc": "POST 宿主机 api_stub 的 /api/appointment；重试必须关闭，避免重复建单",
            "method": "post",
            "url": STUB_BASE + "/api/appointment",
            "authorization": {"type": "no-auth", "config": None},
            "headers": "Content-Type: application/json",
            "params": "",
            "body": {
                "type": "json",
                "data": [
                    {
                        "key": "",
                        "type": "text",
                        "value": '{"name":"{{#appt_extract.name#}}","phone":"{{#appt_extract.phone#}}","model":"{{#appt_extract.model#}}","time":"{{#appt_extract.time#}}"}',
                    }
                ],
            },
            "timeout": {"connect": 5, "read": 10, "write": 5},
            "ssl_verify": True,
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 0},
            "error_strategy": "default-value",
            "default_value": [
                {"key": "status_code", "type": "number", "value": 0},
                {"key": "body", "type": "string", "value": ""},
            ],
        },
        1440,
        840,
        160,
    )
    add(
        "appt_ok",
        "工单是否受理",
        {
            "type": "if-else",
            "title": "工单是否受理",
            "desc": "接口 body 含 ticket_id 视为受理成功",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("appt_api", "body", "contains", "ticket_id", "string"),
                    ],
                }
            ],
        },
        1800,
        840,
    )
    add(
        "appt_confirm",
        "预约成功通知",
        llm(
            "预约成功通知",
            "从工单 JSON 取 ticket_id/车型/时间，生成确认话术",
            APPT_CONFIRM_SYSTEM,
            APPT_CONFIRM_USER,
            temperature=0.3,
        ),
        2160,
        780,
        160,
    )
    add(
        "appt_fallback",
        "预约失败兜底",
        llm(
            "预约失败兜底",
            "预约提交失败时致歉，不谎称成功、不编工单号",
            APPT_FALLBACK_SYSTEM,
            "客户原话：{{#start.user_query#}}",
            temperature=0.5,
        ),
        2160,
        1040,
        150,
    )

    # ---------------- 分支 4 / 5
    add(
        "kb_scripts",
        "话术知识检索",
        {
            "type": "knowledge-retrieval",
            "title": "话术知识检索",
            "desc": "汽车销售知识库，多路召回 top_k=3，阈值 0.5",
            "query_variable_selector": selector("start", "user_query"),
            "query_attachment_selector": [],
            "dataset_ids": [DATASET_ID],
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": 3,
                "score_threshold": 0.5,
                "score_threshold_enabled": True,
                "reranking_enable": False,
                "reranking_mode": "reranking_model",
                "reranking_model": None,
                "weights": None,
            },
        },
        720,
        1240,
        140,
    )
    add(
        "objection_reply",
        "异议回复",
        llm(
            "异议回复",
            "共情 + 价值拆解 + 置换/金融方案，不承诺成交价",
            OBJECTION_SYSTEM,
            OBJECTION_USER,
            temperature=0.7,
            context={"enabled": True, "variable_selector": selector("kb_scripts", "result")},
        ),
        1080,
        1240,
        170,
    )
    add(
        "smalltalk_reply",
        "闲聊兜底",
        {
            "type": "template-transform",
            "title": "闲聊兜底",
            "desc": "固定引导话术，不回答无关问题，一句话拉回购车",
            "template": SMALLTALK_TEMPLATE,
            "variables": [
                {"variable": "query", "value_selector": selector("start", "user_query")}
            ],
        },
        720,
        1440,
        120,
    )

    # ---------------- 汇聚与输出
    add(
        "merge_reply",
        "汇聚回复",
        {
            "type": "variable-aggregator",
            "title": "汇聚回复",
            "desc": "9 路分支汇聚，取第一个实际有值的变量；最后一路是闲聊兜底",
            "output_type": "string",
            "variables": [
                selector("profile_followup", "text"),
                selector("recommend", "text"),
                selector("quote_reply", "text"),
                selector("quote_fallback", "text"),
                selector("appt_followup", "text"),
                selector("appt_confirm", "text"),
                selector("appt_fallback", "text"),
                selector("objection_reply", "text"),
                selector("smalltalk_reply", "output"),
            ],
            "advanced_settings": {"group_enabled": False, "groups": []},
        },
        2880,
        640,
        120,
    )
    # ---------------- 合规校验链路（task-9）
    # merge_reply → compliance_scan → compliance_if
    #   ├─ 命中 level1 → compliance_fallback（标准话术，直接拦）
    #   └─ 未命中 → compliance_llm（二级修正）→ compliance_verify → compliance_if2
    #        ├─ 仍有残留/不可修正 → compliance_fallback2（llm_unfixable 话术）
    #        └─ 通过 → 放行修正稿
    # 四条路径统一进 compliance_finalize（输出文本 + compliance_flag）→ end
    add(
        "compliance_scan",
        "一级合规扫描",
        {
            "type": "code",
            "title": "一级合规扫描",
            "desc": "内联 level1 硬拦截词库（77 词），命中即拦截；输出 passed / hit_words / text",
            "code_language": "python3",
            "code": _with_words(SCAN_CODE_TEMPLATE),
            "variables": [
                {
                    "variable": "text",
                    "value_selector": selector("merge_reply", "output"),
                    "value_type": "string",
                }
            ],
            "outputs": {
                "passed": {"type": "boolean", "children": None},
                "hit_words": {"type": "string", "children": None},
                "text": {"type": "string", "children": None},
            },
        },
        3240,
        640,
        180,
    )
    add(
        "compliance_if",
        "一级是否通过",
        {
            "type": "if-else",
            "title": "一级是否通过",
            "desc": "passed == true 进 LLM 二级校验；false 直接走一级拦截兜底",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("compliance_scan", "passed", "is", True, "boolean"),
                    ],
                }
            ],
        },
        3600,
        640,
    )
    add(
        "compliance_llm",
        "二级合规修正",
        llm(
            "二级合规修正",
            "按 compliance_words.json 的合规 Prompt 审核并修正回答；只输出最终文本",
            COMPLIANCE_SYSTEM,
            "请审核上面的待审核内容。需要修正则直接输出修正后的完整回答，合规则原样输出，无法修正则只输出兜底话术。",
            temperature=0.1,
        ),
        3960,
        500,
        170,
    )
    add(
        "compliance_verify",
        "二级合规复核",
        {
            "type": "code",
            "title": "二级合规复核",
            "desc": "再扫 level1 残留 + 判定 LLM 是否直接回兜底话术；输出 passed2 / final_text / verify_flag",
            "code_language": "python3",
            "code": _with_words(VERIFY_CODE_TEMPLATE),
            "variables": [
                {
                    "variable": "llm_text",
                    "value_selector": selector("compliance_llm", "text"),
                    "value_type": "string",
                },
                {
                    "variable": "original_text",
                    "value_selector": selector("compliance_scan", "text"),
                    "value_type": "string",
                },
            ],
            "outputs": {
                "passed2": {"type": "boolean", "children": None},
                "final_text": {"type": "string", "children": None},
                "hit_words2": {"type": "string", "children": None},
                "verify_flag": {"type": "string", "children": None},
            },
        },
        4320,
        500,
        200,
    )
    add(
        "compliance_if2",
        "二级是否通过",
        {
            "type": "if-else",
            "title": "二级是否通过",
            "desc": "passed2 == true 放行修正稿；false 走不可修正兜底话术",
            "logical_operator": "and",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        cond("compliance_verify", "passed2", "is", True, "boolean"),
                    ],
                }
            ],
        },
        4680,
        500,
    )
    add(
        "compliance_fallback",
        "一级拦截兜底",
        {
            "type": "template-transform",
            "title": "一级拦截兜底",
            "desc": "level1 命中时的标准话术（fallback.hit_level1），不进入 LLM",
            "template": COMPLIANCE_FALLBACK_TEXT,
            "variables": [],
        },
        3960,
        760,
        120,
    )
    add(
        "compliance_fallback2",
        "不可修正兜底",
        {
            "type": "template-transform",
            "title": "不可修正兜底",
            "desc": "LLM 修正后仍违规/无法修正时的标准话术（fallback.llm_unfixable）",
            "template": COMPLIANCE_UNFIXABLE_TEXT,
            "variables": [],
        },
        5040,
        760,
        120,
    )
    add(
        "compliance_finalize",
        "合规结果汇聚",
        {
            "type": "code",
            "title": "合规结果汇聚",
            "desc": "四条合规路径的唯一出口：输出 response 与 compliance_flag",
            "code_language": "python3",
            "code": FINALIZE_CODE_TEMPLATE.replace(
                "__FALLBACK_TEXT__",
                json.dumps(COMPLIANCE_FALLBACK_TEXT, ensure_ascii=False),
            ),
            "variables": [
                {
                    "variable": "fallback_text",
                    "value_selector": selector("compliance_fallback", "output"),
                    "value_type": "string",
                },
                {
                    "variable": "unfixable_text",
                    "value_selector": selector("compliance_fallback2", "output"),
                    "value_type": "string",
                },
                {
                    "variable": "fixed_text",
                    "value_selector": selector("compliance_verify", "final_text"),
                    "value_type": "string",
                },
                {
                    "variable": "verify_flag",
                    "value_selector": selector("compliance_verify", "verify_flag"),
                    "value_type": "string",
                },
            ],
            "outputs": {
                "response": {"type": "string", "children": None},
                "compliance_flag": {"type": "string", "children": None},
            },
        },
        5400,
        640,
        200,
    )
    add(
        "sources_attach",
        "检索来源附注",
        {
            "type": "code",
            "title": "检索来源附注",
            "desc": "在回答末尾追加命中的知识库片段（文档名 / 相关度 / 摘要），并输出结构化 sources",
            "code_language": "python3",
            "code": SOURCES_CODE_TEMPLATE,
            "variables": [
                {
                    "variable": "response",
                    "value_selector": selector("compliance_finalize", "response"),
                    "value_type": "string",
                },
                {
                    "variable": "compliance_flag",
                    "value_selector": selector("compliance_finalize", "compliance_flag"),
                    "value_type": "string",
                },
                {
                    "variable": "kb_models",
                    "value_selector": selector("kb_models", "result"),
                    "value_type": "array[object]",
                },
                {
                    "variable": "kb_scripts",
                    "value_selector": selector("kb_scripts", "result"),
                    "value_type": "array[object]",
                },
            ],
            "outputs": {
                "response": {"type": "string", "children": None},
                "sources": {"type": "string", "children": None},
                "compliance_flag": {"type": "string", "children": None},
            },
        },
        5580,
        640,
        200,
    )
    add(
        "end",
        "结束",
        {
            "type": "end",
            "title": "结束",
            "desc": "输出合规后的 response（含知识库来源附注）、结构化 sources，以及便于统计的 compliance_flag",
            "outputs": [
                {
                    "variable": "response",
                    "value_selector": selector("sources_attach", "response"),
                    "value_type": "string",
                },
                {
                    "variable": "sources",
                    "value_selector": selector("sources_attach", "sources"),
                    "value_type": "string",
                },
                {
                    "variable": "compliance_flag",
                    "value_selector": selector("sources_attach", "compliance_flag"),
                    "value_type": "string",
                },
            ],
        },
        5760,
        640,
        120,
    )
    return nodes


EDGES_SPEC: list[tuple[str, str, str]] = [
    ("start", "source", "intent_classifier"),
    ("intent_classifier", "1", "profile_extract"),
    ("intent_classifier", "2", "quote_extract"),
    ("intent_classifier", "3", "appt_extract"),
    ("intent_classifier", "4", "kb_scripts"),
    ("intent_classifier", "5", "smalltalk_reply"),
    ("profile_extract", "source", "profile_parse"),
    ("profile_parse", "source", "profile_check"),
    ("profile_check", "true", "kb_query_build"),
    ("profile_check", "false", "profile_followup"),
    ("kb_query_build", "source", "kb_models"),
    ("kb_models", "source", "recommend"),
    ("quote_extract", "source", "inventory_api"),
    ("inventory_api", "source", "inventory_ok"),
    ("inventory_ok", "true", "quote_reply"),
    ("inventory_ok", "false", "quote_fallback"),
    ("appt_extract", "source", "appt_complete"),
    ("appt_complete", "true", "appt_api"),
    ("appt_complete", "false", "appt_followup"),
    ("appt_api", "source", "appt_ok"),
    ("appt_ok", "true", "appt_confirm"),
    ("appt_ok", "false", "appt_fallback"),
    ("kb_scripts", "source", "objection_reply"),
    ("profile_followup", "source", "merge_reply"),
    ("recommend", "source", "merge_reply"),
    ("quote_reply", "source", "merge_reply"),
    ("quote_fallback", "source", "merge_reply"),
    ("appt_followup", "source", "merge_reply"),
    ("appt_confirm", "source", "merge_reply"),
    ("appt_fallback", "source", "merge_reply"),
    ("objection_reply", "source", "merge_reply"),
    ("smalltalk_reply", "source", "merge_reply"),
    ("merge_reply", "source", "compliance_scan"),
    # 合规链路（task-9）
    ("compliance_scan", "source", "compliance_if"),
    ("compliance_if", "true", "compliance_llm"),
    ("compliance_if", "false", "compliance_fallback"),
    ("compliance_llm", "source", "compliance_verify"),
    ("compliance_verify", "source", "compliance_if2"),
    ("compliance_if2", "true", "compliance_finalize"),
    ("compliance_if2", "false", "compliance_fallback2"),
    ("compliance_fallback", "source", "compliance_finalize"),
    ("compliance_fallback2", "source", "compliance_finalize"),
    ("compliance_finalize", "source", "sources_attach"),
    ("sources_attach", "source", "end"),
]


def build_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    types = {node["id"]: node["data"]["type"] for node in nodes}
    edges = []
    for source, handle, target in EDGES_SPEC:
        edges.append(
            {
                "id": f"{source}-{handle}-{target}-target",
                "source": source,
                "sourceHandle": handle,
                "target": target,
                "targetHandle": "target",
                "type": "custom",
                "selected": False,
                "zIndex": 0,
                "data": {
                    "sourceType": types[source],
                    "targetType": types[target],
                    "isInIteration": False,
                    "isInLoop": False,
                    "iteration_id": None,
                    "loop_id": None,
                },
            }
        )
    return edges


def build_document() -> dict[str, Any]:
    nodes = build_nodes()
    edges = build_edges(nodes)
    return {
        # 顶层即 POST /console/api/apps/{id}/workflows/draft 的 body。
        # 注意：1.19 的 SyncDraftWorkflowPayload(extra="forbid") 不接受
        # environment_variables / environment_variable_patch 之外的同名字段；
        # 本工作流不使用环境变量，故顶层放 graph/features/hash/conversation_variables。
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
        "features": {
            "file_upload": {},
            "retriever_resource": {"enabled": True},
            "sensitive_word_avoidance": {"enabled": False},
            "text_to_speech": {"enabled": False, "language": "", "voice": ""},
        },
        "hash": None,
        "conversation_variables": [],
    }


def main() -> None:
    doc = build_document()
    OUT_FILE.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    nodes = doc["graph"]["nodes"]
    edges = doc["graph"]["edges"]
    print(f"written: {OUT_FILE}")
    print(f"nodes={len(nodes)} edges={len(edges)} bytes={OUT_FILE.stat().st_size}")


if __name__ == "__main__":
    main()
