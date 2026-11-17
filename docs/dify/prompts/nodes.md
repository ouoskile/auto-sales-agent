# 汽车销售接待工作流 —— 逐节点规格（可直接照抄进 Dify 1.19）

> 适用：Dify 1.19.0（本机 `http://localhost/`），应用类型 **Workflow（工作流）**，单轮入参 `user_query`，统一用 **结束节点** 输出。
> 配套：[`backend_stub.md`](../guide/backend_stub.md)（HTTP 节点/SSRF）、[`e2e_tests.md`](../guide/e2e_tests.md)（验收用例）、知识库素材 `docs/dify/knowledge/01–04`。
> 本文所有 Prompt 均为**中文全文**，可直接粘贴；`{{#...#}}` 占位符按本文写法插入即可（UI 里也可用变量选择器点选，效果相同）。
> **已按本机环境落地的版本**（app「汽车销售接待智能体」，26 节点/33 边）见
> [`workflow_build.md`](../guide/workflow_build.md) 与 `tools/dify/workflow_draft.json`；
> 与本文的差异：模型统一为 `deepseek-flash`、LLM 节点加 `reasoning_format:"separated"`、
> 知识库检索 `top_k=3 / score_threshold=0.5`、检索词模板以 JSON 为准。

---

## 0. 先读：变量与占位符写法

### 0.1 Dify 变量引用语法

| 场景 | 写法 | 说明 |
| --- | --- | --- |
| 引用开始节点入参 | `{{#start.user_query#}}` | 格式固定为 `{{#节点ID.变量名#}}`；节点 ID 在本文用可读名（如 `start`），手动建图时以画布实际 ID 为准 |
| 引用任意节点输出 | `{{#profile_parse.is_complete#}}`、`{{#inventory_api.body#}}` | 只能引用**节点输出变量**，不能写函数/表达式/Jinja |
| 系统变量 | `{{#sys.query#}}`、`{{#sys.user_id#}}`、`{{#sys.workflow_run_id#}}` | `sys.query` 是 Chatflow 的当前用户输入；本方案 Workflow 模式统一用 `{{#start.user_query#}}` |
| 知识检索结果（注入上下文） | `{{#context#}}` | 仅当 LLM 节点打开「上下文」并选中知识检索节点的 `result` 时可用 |
| 变量选择器（DSL/API 里是数组） | `["start", "user_query"]` | 例如 HTTP 节点参数、if-else 条件、结束节点输出 |

注意：
1. 占位符在**发给大模型之前**就被 Dify 替换成真实值，模型看到的是值本身；因此 Prompt 的「示例输出」里**绝不能**出现占位符，否则模型会照抄。
2. 代码节点内部不能写 `{{#...#}}`，输入输出通过 `variables` / `outputs` 映射（见 N04、N15 示例）。
3. 节点 ID 必须全局唯一。API/DSL 建图时用本文的可读 ID（如 `intent_classifier`）；手动建图时 Dify 会生成随机数字 ID，插入变量时请用变量选择器，不要手打。
4. 本次只有 `user_query` 是必填入参；若要让前端带上多轮上文，再加 `chat_history`（可选，paragraph）。

### 0.2 开始节点变量

| 变量名 | 类型 | 必填 | 长度 | 说明 |
| --- | --- | --- | --- | --- |
| `user_query` | text-input | 是 | 2000 | 用户本轮原话，例如「家用，预算 15 万，有充电桩，推荐个 SUV」 |
| `chat_history` | paragraph | 否 | 4000 | 可选：前几轮对话摘要/追问记录，用于画像补全（不填则留空） |

### 0.3 知识库依赖

知识库名 **汽车销售知识库**，已导入 4 份文档：`01_门店车型库.md`、`02_销售标准话术库.md`、`03_购车流程与服务说明.md`、`04_客户画像匹配规则.md`（建库过程见 [`kb_setup.md`](../guide/kb_setup.md)，文档 ID 见 `tools/dify/kb_manifest.json`）。

**本机实际数据集 ID：`403fbc9d-3c82-4077-8033-6761821f68f3`**（索引方式：高质量、向量检索、embedding `text-embedding-v4`（langgenius/tongyi/tongyi）、Top K 3、阈值 0.5）。本文 N08、N23 的 `dataset_ids` 直接填这个 ID；若重建知识库，用 `GET /console/api/datasets` 取新 ID 替换。

阈值说明：规划要求 0.7，但该中文短 query 的相似度分布偏低，0.5 更容易召回（见 kb_setup.md §5.4 校准方法）。建议先按 0.7 跑用例；若关键 query 空召回，降到 0.5–0.6 再回归，不要凭感觉调。

---

## 1. 节点总览（26 个节点 / 33 条边）

| # | 节点名 | 类型 | node_id | 入参（变量选择器） | 出参 | 关键参数 |
| --- | --- | --- | --- | --- | --- | --- |
| N01 | 开始 | start | `start` | — | `user_query`(string)、`chat_history`(string) | 见 0.2 |
| N02 | 意图分类 | question-classifier | `intent_classifier` | `start.user_query` | `class_name`(string，可选) | qwen2.5:7b / temp 0.1；5 类 |
| N03 | 画像抽取 | llm | `profile_extract` | `start.user_query`、`start.chat_history` | `text`(string，JSON) | qwen2.5:7b / temp 0.1，max_tokens 400 |
| N04 | 画像解析 | code | `profile_parse` | `profile_extract.text`、`start.user_query` | `budget`/`scene`/`family_num`/`charge`/`intend_car`(string)、`profile_json`(string)、`is_complete`(boolean)、`missing_text`(string)、`profile_summary`(string) | python3，见全文 |
| N05 | 画像完整性 | if-else | `profile_check` | `profile_parse.is_complete` | — | case true / ELSE |
| N06 | 画像追问 | llm | `profile_followup` | `profile_parse.missing_text`、`start.user_query` | `text`(string) | qwen2.5:7b / temp 0.6 |
| N07 | 检索词拼装 | template-transform | `kb_query_build` | `profile_parse.profile_summary`、`start.user_query` | `output`(string) | 见全文 |
| N08 | 车型知识检索 | knowledge-retrieval | `kb_models` | `kb_query_build.output` | `result`(array[object]) | top_k 3、阈值 0.7、**关**重排 |
| N09 | 车型推荐 | llm | `recommend` | `profile_parse.profile_summary`、`start.user_query`、`context`←`kb_models.result` | `text`(string) | qwen3.8-flash / temp 0.6，上下文开启 |
| N10 | 报价要素抽取 | parameter-extractor | `quote_extract` | `start.user_query` | `brand`(string)、`model`(string) | qwen2.5:7b / prompt 模式 |
| N11 | 库存接口 | http-request | `inventory_api` | `quote_extract.brand`、`quote_extract.model` | `body`(string)、`status_code`(number)、`headers`(object) | GET，见 backend_stub.md §3 |
| N12 | 库存接口是否成功 | if-else | `inventory_ok` | `inventory_api.status_code` | — | `=` 200 / ELSE |
| N13 | 报价话术 | llm | `quote_reply` | `inventory_api.body`、`start.user_query` | `text`(string) | qwen3.8-flash / temp 0.5 |
| N14 | 报价兜底 | llm | `quote_fallback` | `start.user_query` | `text`(string) | qwen3.8-flash / temp 0.5 |
| N15 | 预约要素抽取 | parameter-extractor | `appt_extract` | `start.user_query`、`start.chat_history` | `name`/`phone`/`model`/`time`(string) | qwen2.5:7b / prompt 模式 |
| N16 | 预约要素是否齐全 | if-else | `appt_complete` | 4 个字段 | — | and：4 个 not empty |
| N17 | 预约追问 | llm | `appt_followup` | 4 个字段、`start.user_query` | `text`(string) | qwen2.5:7b / temp 0.6 |
| N18 | 提交预约工单 | http-request | `appt_api` | 4 个字段 | `body`(string)、`status_code`(number)、`headers`(object) | POST json，重试关闭 |
| N19 | 工单是否受理 | if-else | `appt_ok` | `appt_api.body` | — | contains `ticket_id` / ELSE |
| N20 | 预约成功通知 | llm | `appt_confirm` | `appt_api.body` | `text`(string) | qwen3.8-flash / temp 0.3 |
| N21 | 预约失败兜底 | llm | `appt_fallback` | `start.user_query` | `text`(string) | qwen3.8-flash / temp 0.5 |
| N22 | 话术知识检索 | knowledge-retrieval | `kb_scripts` | `start.user_query` | `result`(array[object]) | top_k 2、阈值 0.6 |
| N23 | 异议回复 | llm | `objection_reply` | `start.user_query`、`context`←`kb_scripts.result` | `text`(string) | qwen3.8-flash / temp 0.7，上下文开启 |
| N24 | 闲聊兜底 | template-transform | `smalltalk_reply` | `start.user_query` | `output`(string) | 固定话术模板 |
| N25 | 汇聚回复 | variable-aggregator | `merge_reply` | 9 个分支终态 | `output`(string) | output_type=string |
| N26 | 结束 | end | `end` | `merge_reply.output` | 输出 `response`(string) | 见 §9 |

模型统一约定：
- **抽取/分类类**（N02/N03/N10/N15）：`qwen2.5:7b`（`langgenius/ollama/ollama`），temperature `0.1`，top_p `0.9`，max_tokens `512`。
- **生成话术类**（N06/N09/N13/N14/N17/N20/N21/N23）：`qwen3.8-flash`（`langgenius/tongyi/tongyi`），temperature `0.5–0.7`，max_tokens `800`。
- 若模型列表里没有 qwen3.8-flash，改用 `qwen2.5:7b`（temp 0.6）或 `deepseek-chat`；**不要在节点里选到未配置凭据的模型**，否则运行会报 provider 错误。
- 所有 LLM 节点：`上下文` 关闭（除 N09、N23 明确开启）；`视觉` 关闭；`记忆` 关闭（Workflow 模式无记忆）。

---

## 2. 连线（edges）表

普通节点 `sourceHandle="source"`；分类器按类别 ID（`"1"…"5"`）；条件分支按 `"true"` / `"false"`。

| 源节点 | sourceHandle | 目标节点 |
| --- | --- | --- |
| start | source | intent_classifier |
| intent_classifier | `1` | profile_extract |
| intent_classifier | `2` | quote_extract |
| intent_classifier | `3` | appt_extract |
| intent_classifier | `4` | kb_scripts |
| intent_classifier | `5` | smalltalk_reply |
| profile_extract | source | profile_parse |
| profile_parse | source | profile_check |
| profile_check | `true` | kb_query_build |
| profile_check | `false` | profile_followup |
| kb_query_build | source | kb_models |
| kb_models | source | recommend |
| quote_extract | source | inventory_api |
| inventory_api | source | inventory_ok |
| inventory_ok | `true` | quote_reply |
| inventory_ok | `false` | quote_fallback |
| appt_extract | source | appt_complete |
| appt_complete | `true` | appt_api |
| appt_complete | `false` | appt_followup |
| appt_api | source | appt_ok |
| appt_ok | `true` | appt_confirm |
| appt_ok | `false` | appt_fallback |
| kb_scripts | source | objection_reply |
| profile_followup | source | merge_reply |
| recommend | source | merge_reply |
| quote_reply | source | merge_reply |
| quote_fallback | source | merge_reply |
| appt_followup | source | merge_reply |
| appt_confirm | source | merge_reply |
| appt_fallback | source | merge_reply |
| objection_reply | source | merge_reply |
| smalltalk_reply | source | merge_reply |
| merge_reply | source | end |

> 分类器/条件分支的 handle 在 UI 上表现为节点右侧的分支圆点；API/DSL 里必须写成上表的 `"1"…"5"`、`"true"`、`"false"`，写错会报「找不到分支」或运行时分支悬空。

---

## 3. 分支 1：车型咨询（N03–N09）

### N02 意图分类（question-classifier）

- 输入变量：`user_query` = `["start","user_query"]`；**不要**给分类器加「记忆」。
- 类别（class id 顺序固定，ID 即分支 handle）：

| class id | 类别名 | 判定标准（写进 instruction，不写进类别名） |
| --- | --- | --- |
| 1 | 车型咨询 | 了解车型/参数/续航/空间/配置、让推荐、对比、问适不适合家用通勤 |
| 2 | 报价库存 | 问价格、落地价、优惠、现车、库存、提车周期、金融/置换 |
| 3 | 预约试驾 | 想试驾/看车/约时间/到店，或给出姓名手机号要预约 |
| 4 | 价格异议 | 嫌贵、要降价、拿别家/网上比价、质疑配置或性价比、犹豫 |
| 5 | 闲聊无关 | 问候、感谢、与购车无关的问题 |

- `instruction`（全文粘贴）：

```text
你是汽车门店销售接待前台的意图分类器。只判断用户这句话属于哪一类，不要回答用户问题。

分类标准：
1. 车型咨询：想了解车型、参数、续航、空间、配置、动力、安全，要求推荐车型，对比车型，问“家用/通勤买什么车合适”。
2. 报价库存：问价格、落地价、优惠、活动、现车、库存、提车周期、金融方案、置换、上牌费用、保险。
3. 预约试驾：想试驾、想看车、想约到店时间，或直接提供姓名/手机号要预约。
4. 价格异议：觉得贵、要求再便宜、说别家更便宜、说网上价格更低、质疑配置/续航/保值率、表达犹豫或砍价。
5. 闲聊无关：打招呼、感谢、告别、问天气/吃饭/写代码等与购车无关的内容。

多意图处理：一句话包含多个意图时，按优先级归类：预约试驾 > 报价库存 > 车型咨询 > 价格异议 > 闲聊无关。
只输出一个类别名，不要解释，不要输出编号以外的内容。
```

- 出参：`class_name`（string，可选，仅用于调试/结束节点回传；分支路由不依赖它）。

### N03 画像抽取（llm，严格 JSON）

- 模型参数：temperature `0.1`，max_tokens `400`；上下文关闭。
- 系统提示词：

```text
你是汽车门店销售顾问的需求分析师。任务：从用户对话中抽取客户画像字段，输出一个严格 JSON 对象。

字段定义：
- budget：购车预算，字符串。保留用户原话的量级，例如 "15万左右"、"12-20万"、"预算20万以上"。
- scene：主要用车场景，字符串。取值优先用 "通勤" / "家用" / "商务"，可组合，如 "家用+通勤"。
- family_num：家庭人数，字符串，例如 "3口之家"、"一家五口"、"两个人"。
- charge：是否有固定车位或家用充电桩，字符串。只能取 "有" / "无" / "不确定"。
- intend_car：意向车型或车型线索，字符串，例如 "SUV"、"轿车"、"车型A"、"还没定"。
- missing：数组，列出上面 5 个字段中用户没有明确说到的字段名（英文键名），没有缺失就输出空数组。

硬性规则：
1. 只抽取用户**明确表达**的信息；没提到的字段一律填 null，绝不猜测、绝不用常识补全。
2. 用户说“随便看看”“帮我推荐”但没有预算时，budget 填 null，不要默认 15 万。
3. 用户说“有车位”不等于“有充电桩”：只有明确提到充电桩/能装桩/可充电才填 "有"；只说车位则 charge 填 "不确定"。
4. 输出必须是**单个 JSON 对象**，不要 markdown 代码块、不要解释文字、不要前后缀。键名固定为 budget、scene、family_num、charge、intend_car、missing。
```

- 用户提示词：

```text
用户本句话：
{{#start.user_query#}}

历史对话（可能为空）：
{{#start.chat_history#}}

请输出画像 JSON。
```

> 若未在开始节点声明 `chat_history`，请把「历史对话」整段删掉（保留占位符会运行报错）。

### N04 画像解析（code，python3）

- 输入变量：`profile_raw` ← `["profile_extract","text"]`；`user_query` ← `["start","user_query"]`。
- 输出变量（全部在 outputs 中声明）：`budget`(string)、`scene`(string)、`family_num`(string)、`charge`(string)、`intend_car`(string)、`profile_json`(string)、`is_complete`(boolean)、`missing_text`(string)、`profile_summary`(string)。
- 代码全文：

```python
import json
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

    # 完整画像的最小要求：预算 + 场景 + 充电条件（人数/意向车型可后补）
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
```

> 代码节点首次运行会自动安装依赖？不需要——只用 `json`/`re` 标准库。若 Dify 提示 outputs 类型不符，确认 `is_complete` 类型选 `boolean`，其余选 `string`。

### N05 画像完整性（if-else）

| case | 条件 | 变量选择器 | varType | 操作符 | 值 | 出边 |
| --- | --- | --- | --- | --- | --- | --- |
| IF | 画像完整 | `["profile_parse","is_complete"]` | boolean | `is` | `true` | `true` |
| ELSE | 画像缺失 | — | — | — | — | `false` |

> 布尔值在 if-else 里填 `true`（小写字符串）。

### N06 画像追问（llm）

- 入参：`missing_text` ← `["profile_parse","missing_text"]`；`user_query` ← `["start","user_query"]`。
- temperature `0.6`，上下文关闭。
- 系统提示词：

```text
你是汽车门店的销售助理，说话亲切、口语化，像真人顾问。当前客户信息不全，需要你追问补齐。

规则：
1. 只问缺失的信息，一次问完，最多 3 个问题，不要反复追问已有的信息。
2. 问题要具体、好回答，给出例子，例如“预算大概多少？12-20 万这个区间可以吗”。
3. 必须覆盖缺失字段对应的问题：预算 / 家用还是通勤 / 有无固定车位或充电桩。
4. 不要编造车型、价格、优惠；不要长篇推销。
5. 结尾用一句轻松的话鼓励客户回复，例如“您说个大概就行，我帮您筛两台合适的”。
6. 输出直接给客户看的话术，150 字以内，不要 JSON、不要标题、不要分点符号堆砌。
```

- 用户提示词：

```text
缺失字段：{{#profile_parse.missing_text#}}
客户刚才说：{{#start.user_query#}}
已知画像：{{#profile_parse.profile_summary#}}
请生成追问话术。
```

### N07 检索词拼装（template-transform）

- 变量：`summary` ← `["profile_parse","profile_summary"]`；`query` ← `["start","user_query"]`。
- 模板（模板节点用 `{{ 变量名 }}`，不加 `#`）：

```text
客户画像：{{ summary }}
客户原话：{{ query }}
检索目标：适合该客户的在售车型、参数配置、续航/能耗、空间表现与推荐理由。
```

- 输出变量：`output`（string）。

### N08 车型知识检索（knowledge-retrieval）

| 配置 | 值 |
| --- | --- |
| 查询变量 | `["kb_query_build","output"]` |
| 知识库 | 汽车销售知识库（`403fbc9d-3c82-4077-8033-6761821f68f3`） |
| 检索模式 | 多路召回（multiple） |
| Top K | 3 |
| 相似度阈值 | 0.7 |
| 重排序 | 关闭（本机未配置 rerank 模型；若开启必须选到可用模型，否则报错） |
| 元数据过滤 | 不启用 |

出参：`result`（array[object]，元素含 `content`、`score`、`title`/`metadata`），下游由 LLM 上下文自动注入。

### N09 车型推荐（llm，FABE）

- 上下文：**开启**，变量选择器 `["kb_models","result"]`。
- temperature `0.6`，max_tokens `800`。
- 系统提示词：

```text
你是汽车门店的金牌销售顾问，按 FABE 结构给客户推荐车型。

规则：
1. 只推荐知识库上下文中真实存在的车型（车型A / 车型B / 车型C），推荐 1–2 款，不要编造不存在的车型或配置。
2. 每款车按 FABE 讲清楚：
   - F（Feature 配置/参数）：引用上下文里的真实参数（续航、轴距、能源类型、亮点配置）。
   - A（Advantage 优势）：这款车相对其他车型强在哪。
   - B（Benefit 利益）：对这位客户的具体用车场景意味着什么（例如带娃空间、通勤成本、长途补能）。
   - E（Evidence 依据）：用“知识库显示/门店资料”这类说法，不夸大。
3. 必须结合客户画像（预算、场景、家庭人数、充电条件）说明“为什么适合你”，并诚实点出 1 个“不一定适合的点”。
4. 如果上下文为空或没有可用车型信息：不要编造参数，直接说明“这部分资料需要销售顾问帮您确认”，并邀请到店/留资。
5. 涉及价格、优惠、库存、交付周期时，只说“以门店最新报价/库存为准”，不要给出具体数字。
6. 结尾主动邀约试驾，问一句方便的时间（例如“这周六上午还是周日下午方便？”）。
7. 输出给客户看的自然话术，结构清晰（可用短标题+短段落），300 字以内，不要 JSON、不要表格。
```

- 用户提示词：

```text
客户画像：{{#profile_parse.profile_summary#}}
客户原话：{{#start.user_query#}}
知识库检索结果：
{{#context#}}
```

---

## 4. 分支 2：报价 / 库存（N10–N14）

### N10 报价要素抽取（parameter-extractor）

- 输入：`query` = `["start","user_query"]`。
- 推理模式：`prompt`（若模型支持 function_call 且更稳，可切 `function_call`）。
- 参数：

| 参数名 | 类型 | 必填 | 描述（填进 description） |
| --- | --- | --- | --- |
| `brand` | string | 否 | 用户提到的品牌，如“星辰”“远航”；没提就输出空字符串，不要猜 |
| `model` | string | 是 | 用户要问的车型，如“车型A”“B”“SUV”“那台混动”；只能从用户话里提取；仍无法确定时输出“车型A”以外的空值并让下游兜底 |

- instruction（全文）：

```text
从用户的问题中提取“要查询库存/报价的车型”信息。
- brand：品牌名，用户没提就留空。
- model：车型名或车型线索，例如 车型A、车型B、车型C、SUV、轿车、混动、那台车。
- 只提取用户明确说过的内容，不要根据上下文猜测车型，不要编造。
- 如果用户只问“落地多少钱”而没提任何车型，model 留空。
```

### N11 库存接口（http-request）

| 配置 | 值 |
| --- | --- |
| 方法 | GET |
| URL | `http://host.docker.internal:8000/api/inventory` |
| 参数 | `brand` = `{{#quote_extract.brand#}}`；`model` = `{{#quote_extract.model#}}` |
| Headers | `Accept: application/json` |
| Body | none |
| 超时 | 连接 5s / 读取 10s / 写入 5s |
| 重试 | 关闭（或 GET 2 次、间隔 500ms） |
| 异常处理 | 不设默认值，交给 N12 判断（SSRF 未放行时这里会直接失败，见 backend_stub.md §5） |

出参：`body`(string)、`status_code`(number)、`headers`(object)。

### N12 库存接口是否成功（if-else）

| case | 条件 | 变量选择器 | varType | 操作符 | 值 | 出边 |
| --- | --- | --- | --- | --- | --- | --- |
| IF | 状态码 200 | `["inventory_api","status_code"]` | number | `=` | `200` | `true` |
| ELSE | 失败/超时 | — | — | — | — | `false` |

### N13 报价话术（llm）

- 入参：`body` ← `["inventory_api","body"]`；`user_query` ← `["start","user_query"]`。
- temperature `0.5`，max_tokens `700`，上下文关闭。
- 系统提示词：

```text
你是汽车门店的销售顾问，负责把库存/报价接口返回的数据整理成口语化的报价话术。

规则：
1. 只使用接口返回 JSON 里出现的字段和数字，不要编造价格、优惠、库存、交付周期。
2. 必须覆盖：车型、库存状态（有现车/需排期/需预订）、参考落地价、当前优惠方案、预计交付时间。
3. 把优惠说清楚（现金优惠/置换补贴/金融贴息/礼包），并说明可叠加情况以门店为准。
4. 结尾必须加一句“以上是门店参考价，最终价格以销售顾问现场核算为准”。
5. 如果接口返回里字段缺失或含义不明，就说“这部分需要顾问帮您确认”，不要猜数字。
6. 追问一句客户大概什么时候用车/是否方便到店，自然过渡到邀约。
7. 输出给客户看的自然话术，200 字以内，不要 JSON、不要 Markdown 表格。
```

- 用户提示词：

```text
客户原话：{{#start.user_query#}}
库存/报价接口返回（JSON）：
{{#inventory_api.body#}}
```

### N14 报价兜底（llm）

- temperature `0.5`；系统提示词：

```text
你是汽车门店销售顾问。现在库存/报价系统暂时无法返回数据，请生成一段得体的兜底话术。

规则：
1. 先致歉并说明“报价/库存系统暂时查询不到”。
2. 绝对不要编造库存状态、价格、优惠或交付时间。
3. 给客户两个可行选择：留手机号由顾问核实后回复；或直接到店看车（现车可当天试驾）。
4. 语气诚恳、简短（120 字以内），结尾用一个问题推进对话。
```

- 用户提示词：`客户原话：{{#start.user_query#}}`

---

## 5. 分支 3：预约试驾（N15–N21）

### N15 预约要素抽取（parameter-extractor）

- 输入：`query` = `["start","user_query"]`、`["start","chat_history"]`（未声明 chat_history 则删掉）。
- 参数：

| 参数名 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| `name` | string | 否 | 客户姓名/称呼，如“张三”“王女士”；没提留空 |
| `phone` | string | 否 | 11 位手机号，去掉空格和横线；没提留空 |
| `model` | string | 否 | 意向车型，如“车型A”“SUV”；没提留空 |
| `time` | string | 否 | 预约时间，保留用户原话，如“本周六上午”“11 月 21 日 10 点”；没提留空 |

- instruction：

```text
从用户的话中提取预约试驾需要的 4 个要素。
- 只提取用户明确说出的内容，没提到就留空字符串，不要编造姓名、手机号或时间。
- 手机号必须原样保留 11 位数字（可去掉空格/横线）。
- 时间保留用户原话，不要自己换算成具体日期。
- 如果用户说“这周六”而没说具体几点，time 填“本周六”，不要补时间。
```

### N16 预约要素是否齐全（if-else）

一个 case，`logical_operator = and`，4 个条件全部 `not empty`：

| 变量选择器 | varType | 操作符 |
| --- | --- | --- |
| `["appt_extract","name"]` | string | `not empty` |
| `["appt_extract","phone"]` | string | `not empty` |
| `["appt_extract","model"]` | string | `not empty` |
| `["appt_extract","time"]` | string | `not empty` |

出边：`true` → `appt_api`；`false` → `appt_followup`。

### N17 预约追问（llm）

- 入参：4 个抽取字段 + `user_query`；temperature `0.6`。
- 系统提示词：

```text
你是汽车门店销售助理，客户想预约试驾但信息不全。请生成追问话术。

规则：
1. 只追问缺失的要素（姓名 / 手机号 / 意向车型 / 预约时间），已提供的不要重复问。
2. 一次问完所有缺失项，问题要具体，给出格式例子，例如“手机号方便留 11 位吗，用来给您排试驾”。
3. 说明用途：留手机号是为了安排试驾车和到店接待，不会骚扰。
4. 不编造车型库存和价格；语气亲切，100 字以内。
5. 输出直接给客户看的话术，不要 JSON。
```

- 用户提示词：

```text
客户原话：{{#start.user_query#}}
已提取：姓名={{#appt_extract.name#}}；手机号={{#appt_extract.phone#}}；车型={{#appt_extract.model#}}；时间={{#appt_extract.time#}}
请生成追问。
```

### N18 提交预约工单（http-request）

| 配置 | 值 |
| --- | --- |
| 方法 | POST |
| URL | `http://host.docker.internal:8000/api/appointment` |
| Body 类型 | json |
| Body 字段 | `name`=`{{#appt_extract.name#}}`、`phone`=`{{#appt_extract.phone#}}`、`model`=`{{#appt_extract.model#}}`、`time`=`{{#appt_extract.time#}}` |
| Headers | 可不填（json 自动带 Content-Type） |
| 超时 | 连接 5s / 读取 10s / 写入 5s |
| 重试 | **必须关闭**（避免重复建单） |

### N19 工单是否受理（if-else）

| case | 变量选择器 | varType | 操作符 | 值 | 出边 |
| --- | --- | --- | --- | --- | --- |
| IF | `["appt_api","body"]` | string | `contains` | `ticket_id` | `true` |
| ELSE | — | — | — | — | `false` |

> 也可再加一个条件 `status_code = 200`（and）；但 400 校验失败时 body 里没有 ticket_id，单条件已够。

### N20 预约成功通知（llm）

- 入参：`body` ← `["appt_api","body"]`；temperature `0.3`。
- 系统提示词：

```text
你是汽车门店销售助理。预约工单接口已返回结果，请生成给客户的确认话术。

规则：
1. 从接口返回 JSON 中提取：工单号 ticket_id、车型、预约时间、门店。
2. 明确告诉客户“预约已提交成功，顾问会在 30 分钟内电话确认”。
3. 提醒到店携带：身份证、驾驶证（试驾需要），以及可提前准备的问题。
4. 绝不要编造接口里没有的工单号、时间或门店名；字段缺失就只说“已提交，顾问确认后回复您具体安排”。
5. 语气热情、简短（120 字以内），结尾祝一句。
```

- 用户提示词：

```text
客户原话：{{#start.user_query#}}
工单接口返回（JSON）：
{{#appt_api.body#}}
```

### N21 预约失败兜底（llm）

- temperature `0.5`；系统提示词：

```text
你是汽车门店销售助理。预约接口提交失败（网络或系统原因），请生成兜底话术。

规则：
1. 先致歉，说明“预约系统暂时繁忙，没有提交成功”。
2. 不要谎称已经预约成功，不要编造工单号。
3. 请客户再发一次手机号/时间，或建议直接电话门店/到店登记。
4. 简短（100 字以内），语气负责。
```

- 用户提示词：`客户原话：{{#start.user_query#}}`

---

## 6. 分支 4：价格/配置异议（N22–N23）

### N22 话术知识检索（knowledge-retrieval）

| 配置 | 值 |
| --- | --- |
| 查询变量 | `["start","user_query"]` |
| 知识库 | 汽车销售知识库（`403fbc9d-3c82-4077-8033-6761821f68f3`） |
| Top K | 2 |
| 相似度阈值 | 0.6（话术类文本短，阈值略低） |
| 重排序 | 关闭 |

### N23 异议回复（llm）

- 上下文：**开启**，变量选择器 `["kb_scripts","result"]`。
- temperature `0.7`，max_tokens `600`。
- 系统提示词：

```text
你是汽车门店经验丰富的销售顾问，专门处理客户的价格/配置异议。

规则：
1. 先共情认同（例如“理解，买车肯定要算清楚”），不要一上来就反驳。
2. 用价值拆解回应：把价格拆到配置、用料、续航、质保、用车成本、服务权益上，引用知识库话术里的具体点。
3. 价格类异议可给两种解法：置换补贴、金融方案（24 期 0 息等），帮客户把落地价算下来；但不能承诺额外降价或编造优惠。
4. 对比类异议（别家更便宜/网上更便宜）：说明报价口径差异（引流价、捆绑、是否含税险），强调门店报价透明，邀请到店核算。
5. 不贬低竞品，不说“网上都是假的”，不承诺成交价。
6. 如果知识库上下文为空：用通用异议处理框架回答，并说明具体政策以门店为准。
7. 结尾给一个明确下一步：到店对比/试驾/置换评估，并问客户方便时间。
8. 输出给客户看的自然话术，200 字以内，不要 JSON。
```

- 用户提示词：

```text
客户原话：{{#start.user_query#}}
话术库检索结果：
{{#context#}}
```

---

## 7. 分支 5：闲聊 / 无关（N24）

### N24 闲聊兜底（template-transform）

- 变量：`query` ← `["start","user_query"]`（模板里可不用，但保留便于以后改成 LLM）。
- 模板全文：

```text
您好，我是门店的购车助手 😊
我主要帮您做三件事：按预算和用车场景推荐车型、查现车和落地价、约试驾。
您方便说下预算和主要用途吗？比如“15 万左右，家用，有固定车位”，我就能帮您筛两台合适的车。
```

- 输出：`output`(string)。
- 说明：这里故意用固定话术，保证兜底确定、不浪费 token；如需更自然，可换成 LLM（temperature 0.7，系统提示词限定「不回答无关问题，一句话拉回购车」）。

---

## 8. 汇聚与输出（N25–N26）

### N25 汇聚回复（variable-aggregator）

- `output_type`：`string`
- `variables`（顺序即优先级，取第一个实际有值的分支）：

```text
["profile_followup","text"]
["recommend","text"]
["quote_reply","text"]
["quote_fallback","text"]
["appt_followup","text"]
["appt_confirm","text"]
["appt_fallback","text"]
["objection_reply","text"]
["smalltalk_reply","output"]
```

- 出参：`output`(string)。因为一次运行只会走一个分支，其余分支节点未执行、其变量为空，聚合器自然取到唯一有值的那条。

### N26 结束（end）

| 输出变量 | 变量选择器 | 类型 |
| --- | --- | --- |
| `response` | `["merge_reply","output"]` | string |

可选（便于测试断言，取不到就省略）：
| `intent` | `["intent_classifier","class_name"]` | string |
| `profile_json` | `["profile_parse","profile_json"]` | string |

> Workflow 模式必须用「结束」节点（Answer/直接回复只用于 Chatflow）。一个工作流可以有多个结束节点（Dify 1.19 支持），但本方案汇聚到单个 End，API 调用返回结构更稳定。

---

## 9. 异常 / 兜底矩阵

| 失败点 | 表现 | 兜底路径 | 客户可见结果 |
| --- | --- | --- | --- |
| 意图分类模型超时/报错 | 节点报错，流程中断 | 分类器节点「异常处理 → 默认值」（class 填 `5`）或「异常分支」接 `smalltalk_reply` | 固定引导话术 |
| 画像 JSON 解析失败 | `profile_parse.is_complete=false`、`missing_text` 含全部字段 | N05 ELSE → N06 追问 | 追问预算/用途/充电条件 |
| 知识库无命中 | `kb_models.result` 为空数组 | N09 Prompt 规则 4 已覆盖（说明需顾问确认 + 邀约） | 不编造参数，转人工/到店 |
| 库存接口 404（车型不存在） | `status_code=404` | N12 ELSE → N14 报价兜底 | 不编价格，留资核实 |
| 库存接口超时/SSRF 拦截 | 节点失败或 `status_code` 非 200 | N12 ELSE → N14（若节点直接失败则需开异常分支接 N14） | 系统繁忙兜底 |
| 预约接口 400（手机号非法） | body 含 `INVALID_ARGUMENT`，无 `ticket_id` | N19 ELSE → N21 | 致歉并请重新提供手机号/时间 |
| 预约接口超时/重复提交 | 重试关闭后不会重复；超时走 N19 ELSE | N21 | 致歉，不谎称成功 |
| 话术库无命中 | `kb_scripts.result` 空 | N23 Prompt 规则 6 兜底 | 通用异议框架 + 以门店为准 |
| 所有分支都空（异常兜底） | 聚合器输出空 | 在 End 前加「默认值」或在聚合器最后追加 `["smalltalk_reply","output"]` 作为兜底（本方案已把它列在最后） | 至少返回引导话术 |

---

## 10. 多轮追问怎么“回到开始”（重要架构说明）

Dify 的 Workflow 图必须是 **DAG（无环）**，不能真的把「追问节点」连回「开始节点」，否则建图/运行会报环错误。实现多轮有两种做法：

**方案 A（本方案，推荐 4 小时落地）**：追问节点直接作为本轮结果返回。前端把追问话术发给用户，用户补充后发起**新一轮**运行，把上一轮追问与回答拼进 `user_query`（或填 `chat_history`）。工作流本身不保存状态，简单、可测、无副作用。
- 前端拼装示例：`user_query = "（上轮追问：预算大概多少？家用还是通勤？）用户补充：15 万，家用，有充电桩"`。

**方案 B（升级为 Chatflow）**：把应用类型换成「高级对话（Chatflow）」，用**会话变量** `customer_profile`（object/string）+ 「变量赋值」节点保存已抽取画像，下一轮从会话变量读取合并；结束用「直接回复」节点。节点拓扑与本文一致，只替换开始/结束/记忆三处。若要走这条路，建议先用方案 A 验收 5 条用例，再迁移。

---

## 11. 手动建图顺序（UI 点击路径）

1. Dify 控制台 →「工作室」→「创建空白应用」→ 选「工作流」→ 命名「汽车销售接待工作流」。
2. 点开始节点 →「+ 添加变量」→ 变量名 `user_query`、类型「文本」、必填；再加 `chat_history`（段落，非必填）。
3. 依次点 `+` 添加节点（类型见 §1），按 §2 连线；连线时注意分类器/条件分支要接到对应分支圆点（handle）。
4. 变量引用：在 Prompt/参数输入框里点 `{x}` 图标 → 选择来源节点与变量，会自动插入 `{{#...#}}`；不要手打节点 ID。
5. 两个知识检索节点先选好「汽车销售知识库」数据集；画布右上「测试运行」输入一条用例（见 e2e_tests.md）验证。
6. 「发布」前检查：所有分支都能到达结束节点（画布上不能有悬空节点）、必填变量都有值、HTTP 节点 URL 可用。
7. 需要 API 自动化建图时，见本文 §12 的 DSL 片段与 `docs/dify/guide/` 后续补充。

---

## 12. 关键节点 DSL 片段（API 建图用，字段名与 Dify 1.19 一致）

> 以下为 `workflows.graph` / draft API 里的 `data` 片段（不含 position 与 edges 的 id 字段；edge 结构见 §2）。用 API 建图时可直接拼装。

**开始节点**

```json
{
  "type": "start",
  "title": "开始",
  "variables": [
    {"variable": "user_query", "label": "用户问题", "type": "text-input", "required": true, "max_length": 2000, "options": [], "placeholder": "例如：家用，预算15万，有充电桩，推荐个SUV", "default": ""},
    {"variable": "chat_history", "label": "历史对话", "type": "paragraph", "required": false, "max_length": 4000, "options": [], "placeholder": "", "default": ""}
  ]
}
```

**意图分类**

```json
{
  "type": "question-classifier",
  "title": "意图分类",
  "query_variable_selector": ["start", "user_query"],
  "model": {"provider": "langgenius/ollama/ollama", "name": "qwen2.5:7b", "mode": "chat", "completion_params": {"temperature": 0.1}},
  "classes": [
    {"id": "1", "name": "车型咨询"},
    {"id": "2", "name": "报价库存"},
    {"id": "3", "name": "预约试驾"},
    {"id": "4", "name": "价格异议"},
    {"id": "5", "name": "闲聊无关"}
  ],
  "instruction": "<粘贴 §3 N02 的 instruction 全文>",
  "vision": {"enabled": false}
}
```

**条件分支（画像完整性）**

```json
{
  "type": "if-else",
  "title": "画像完整性",
  "logical_operator": "and",
  "cases": [
    {
      "case_id": "true",
      "logical_operator": "and",
      "conditions": [
        {"id": "c1", "varType": "boolean", "variable_selector": ["profile_parse", "is_complete"], "comparison_operator": "is", "value": "true"}
      ]
    }
  ]
}
```

**HTTP 库存接口**

```json
{
  "type": "http-request",
  "title": "库存接口",
  "method": "get",
  "url": "http://host.docker.internal:8000/api/inventory",
  "variables": [
    {"variable": "brand", "value_selector": ["quote_extract", "brand"]},
    {"variable": "model", "value_selector": ["quote_extract", "model"]}
  ],
  "params": "brand={{#quote_extract.brand#}}&model={{#quote_extract.model#}}",
  "headers": "Accept: application/json",
  "authorization": {"type": "no-auth", "config": null},
  "body": {"type": "none", "data": []},
  "ssl_verify": true,
  "timeout": {"max_connect_timeout": 5, "max_read_timeout": 10, "max_write_timeout": 5},
  "retry_config": {"retry_enabled": false, "max_retries": 0, "retry_interval": 500}
}
```

**变量聚合**

```json
{
  "type": "variable-aggregator",
  "title": "汇聚回复",
  "output_type": "string",
  "variables": [
    ["profile_followup", "text"],
    ["recommend", "text"],
    ["quote_reply", "text"],
    ["quote_fallback", "text"],
    ["appt_followup", "text"],
    ["appt_confirm", "text"],
    ["appt_fallback", "text"],
    ["objection_reply", "text"],
    ["smalltalk_reply", "output"]
  ]
}
```

**结束节点**

```json
{
  "type": "end",
  "title": "结束",
  "outputs": [
    {"variable": "response", "value_selector": ["merge_reply", "output"], "value_type": "string"}
  ]
}
```

---

## 13. 建图完成后的自检清单

- [ ] 26 个节点、33 条边，与 §1/§2 完全一致，没有悬空节点。
- [ ] 分类器 5 个分支、条件分支 2 个出口都接到下游。
- [ ] 所有 Prompt 占位符都能在变量选择器里选到（没有 `{{#...#}}` 报红）。
- [ ] 两个知识检索节点都选中了有效数据集，Top K/阈值符合 §3、§6。
- [ ] 3 个 HTTP 节点 URL 指向 stub，且 stub 正在运行（`/health` 200）。
- [ ] 5 条端到端用例全部按预期分支返回（见 e2e_tests.md）。
- [ ] 发布前确认模型供应商里 `qwen2.5:7b`、`qwen3.8-flash` 均可用；不可用时按 §1 替换。

---

## 14. 附：拿到 console 凭据后如何用 API 建 workflow（草案，路由已按本机 1.19.0 源码核对）

> 本机已具备可用的控制台调用链（队友产出，直接复用即可，不要重复造）：
> `tools/dify/dify.py`（宿主机入口，自动把 `tools/dify/dify_console.py` 同步进 `docker-api-1:/tmp` 并用容器内 venv 执行）+ `tools/dify/dify_console.py`（登录、发请求、job 模式）。
> 例：`python tools/dify/dify.py job tools/dify/jobs/xxx.json`，job 文件格式 `{"method":"POST","path":"/console/api/...","json":{...},"out":"..."}`。
> 注意：Dify 1.19 控制台是 **cookie 会话**（access_token + csrf_token），所有请求（含 GET）都必须带 `X-CSRF-Token` 头且与 csrf_token cookie 一致；登录 body 的密码是 **base64 编码**。不要用 Bearer 调 console API（Bearer 只用于 `/v1/*` 应用 API）。

### 14.1 调用顺序

| 步骤 | 方法与路由 | 关键 body / 说明 | 期望 |
| --- | --- | --- | --- |
| 0 | `GET /console/api/apps?page=1&limit=30` | 查重，避免重复建同名应用 | 200，`data[]` |
| 0 | `GET /console/api/datasets?page=1&limit=50` | 取「汽车销售知识库」id，本机已建好：`403fbc9d-3c82-4077-8033-6761821f68f3` | 200 |
| 1 | `POST /console/api/apps` | `{"name":"汽车销售接待工作流","description":"门店销售接待 AI：5 意图分支","mode":"workflow","icon_type":"emoji","icon":"🚗","icon_background":"#FFEAD5"}` | 201，返回 `id`（app_id） |
| 2 | `GET /console/api/apps/{app_id}/workflows/draft` | 新应用一般已带默认 start 节点；记录返回的 `graph`、`features`、`hash` | 200 |
| 3 | 组装 graph | 26 个节点（§1 的 node_id 直接用）+ 33 条边（§2，注意 sourceHandle=`source`/`"1"–"5"`/`"true"`/`"false"`）；节点 data 按 §1/§12 填，`position` 按列布局（x=列×320、y=行×160），start 在最左、end 在最右；edges 至少含 `id`、`source`、`target`、`sourceHandle`、`targetHandle`，`data` 可复制 GET 返回的既有边结构 | — |
| 4 | `POST /console/api/apps/{app_id}/workflows/draft` | `{"graph":{...},"features":<步骤 2 原样>,"hash":<步骤 2 原样>}`；payload 为 strict（多字段会 400），`features` 必须带 | 200（保存成功）；400 会带具体校验错误 |
| 5 | `POST /console/api/apps/{app_id}/workflows/draft/run` | `{"inputs":{"user_query":"我家用，预算15万…"},"files":[]}`；先跑 E2E-1/4/5（不依赖 HTTP 接口） | 200，`data.status=succeeded`、`data.outputs.response` |
| 6 | （可选）节点级调试 | `POST /console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run` | 200 |
| 7 | `POST /console/api/apps/{app_id}/workflows/publish` | `{"marked_name":"v1","marked_comment":"首版：26 节点 5 分支"}`（name ≤20、comment ≤100） | 200 |
| 8 | `POST /console/api/apps/{app_id}/api-keys` | body 可空；创建应用 API 密钥 | 201，返回 `app-xxxx` |
| 9 | `POST /v1/workflows/run` | `Authorization: Bearer app-xxxx`，`{"inputs":{"user_query":"..."},"response_mode":"blocking","user":"e2e"}` | 200，按 e2e_tests.md 断言 |

### 14.2 执行顺序与阻塞点

1. **先建骨架再填肉**：步骤 4 一次提交全量 graph 失败排查成本高；可先提交「start + intent_classifier + 5 条空分支 + 1 个 end」的最小图验证路由与 handle 写法，保存成功后再全量替换（draft 可反复覆盖）。
2. **HTTP 分支的 SSRF 阻塞**：步骤 5 跑 E2E-2/3 前，要么按 [`backend_stub.md`](../guide/backend_stub.md) §5 放行私网（`docker/envs/infrastructure/ssrf-proxy.env` + 重建 ssrf_proxy，需 Lead 批准），要么接受这两个用例走兜底话术先把图验通；本机当前实测仍是 403（`dify_allow_private.conf` 只有注释头、无放行 ACL）。
3. **知识库阈值先按 0.7 建，不通过再降**：与 kb_setup.md §5.4 的校准结论联动，改完重跑 E2E-1 与 B-2。
4. **不要直接改数据库**：`workflows.graph` 虽然可直接 UPDATE，但会绕过 DAG/handle 校验，后续 UI 打开会报错；一律走 draft API。
5. 出错速查：400 `invalid graph` → 看返回 message（最常见是 handle 不存在、节点 data 缺必填字段、有环/不可达节点）；hash 冲突 → 重新 GET draft 拿新 hash；403 → 当前账号角色无 `APP_CREATE_AND_MANAGEMENT`/发布权限；模型报错 → 检查 provider 凭据与模型名。

### 14.3 建图数据从哪来

- 节点 data 字段：本文 §1 总览 + §3–§8 逐节点规格 + §12 DSL 片段。
- Prompt 全文：直接复制 §3–§7 的代码块（中文全文，无需改写）。
- 边与 handle：§2 表格逐行照抄，`intent_classifier` 的 5 条出边 handle 必须是 `"1"`–`"5"`。
- 变量选择器：§1 表格「入参（变量选择器）」列，如 `["start","user_query"]`。
- 数据集 ID：`403fbc9d-3c82-4077-8033-6761821f68f3`（知识库「汽车销售知识库」）。
