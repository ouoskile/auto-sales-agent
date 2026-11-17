# Dify 工作流建图与提交流程（workflow_draft.json）

本文件说明如何把 `tools/dify/workflow_draft.json` 提交成 Dify 1.19 的 Workflow 草稿、
每个节点怎么配、怎么验证、出错怎么回滚，以及目前已知的风险。
prompt 全文、分支条件文字说明在 `docs/dify/prompts/nodes.md`；
**两者冲突时以 `workflow_draft.json`（由 `tools/dify/build_workflow_draft.py` 生成）为准**。

- 应用：`汽车销售接待智能体`，mode = `workflow`，app_id `479d4779-9f96-4553-a8d8-e0401da50d35`
- 画布：26 节点 / 33 边（11 种节点类型），JSON 约 69.9 KB
- 知识库：`汽车销售知识库`，dataset_id `403fbc9d-3c82-4077-8033-6761821f68f3`
- 模型：`langgenius/deepseek/deepseek` + `deepseek-flash`（LLM 节点）
- 后端桩：宿主机 `http://localhost:8000`（`tools/dify/api_stub.py`），容器内用 `http://host.docker.internal:8000`

## 1. 前置条件

| 项 | 要求 | 自检 |
|---|---|---|
| Dify | 1.19.0，`http://localhost/`，控制台可登录 | 浏览器能进控制台 |
| 控制台 API | 容器内 `python tools/dify/dify_console.py login` 可登录 | `python tools/dify/dify.py models llm` 有输出 |
| 知识库 | 4 篇文档 indexing_status = completed | 控制台命中测试能出结果 |
| 模型 | deepseek-flash 在「模型供应商」里 active | 模型列表可见 |
| api_stub | 宿主机 8000 端口在跑 | `curl http://localhost:8000/health` 返回 200 |
| SSRF 放行 | `docker/.env` 中 `SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.65.0/24`，ssrf_proxy 已重建 | `docker exec docker-api-1 curl -s -o /dev/null -w '%{http_code}' -x http://ssrf_proxy:3128 http://host.docker.internal:8000/health` → `200` |

启动桩：`python tools/dify/api_stub.py`（默认 `0.0.0.0:8000`，见 `docs/dify/guide/backend_stub.md`）。

## 2. 生成与提交（推荐流程）

```powershell
cd C:\Users\zhou\Desktop\汽车销售智能体

# 1) 生成 draft JSON（唯一可信来源，改 prompt/参数后必须重新生成）
python tools/dify/build_workflow_draft.py

# 2) 本地结构校验（节点/边计数、端点、可达性、无环、selector、聚合器、坐标、占位符）
python tools/dify/validate_workflow_draft.py

# 3) 用 Dify 真实 pydantic 模型校验提交体 + 每个节点 data
docker cp tools/dify/validate_in_container.py docker-api-1:/tmp/validate_in_container.py
docker cp tools/dify/workflow_draft.json docker-api-1:/tmp/workflow_draft.json
docker exec docker-api-1 sh -lc "cd /app/api && .venv/bin/python /tmp/validate_in_container.py"

# 4) 提交草稿（自动 GET 当前草稿 hash，再 POST，避免 409）
python tools/dify/submit_draft.py
```

成功输出形如：

```json
{"result": "success", "hash": "<新 hash>", "updated_at": 1794908105}
```

只生成 job 不发请求：`python tools/dify/submit_draft.py --print-only`
（job 文件 `.tmp_tests/job_save_draft.json`，实际发送由容器内 `dify_console.py` 完成。）

## 3. 提交体结构（为什么是这 4 个键）

`POST /console/api/apps/{app_id}/workflows/draft` 的 body 是
`SyncDraftWorkflowPayload`（`api/controllers/console/app/workflow.py:147`，`extra="forbid"`）：

| 键 | 类型 | 说明 |
|---|---|---|
| `graph` | dict | `{nodes:[...], edges:[...], viewport:{x,y,zoom}}`，必须非空 |
| `features` | dict | 只需 `file_upload` / `text_to_speech` / `sensitive_word_avoidance`，其余被服务端过滤 |
| `hash` | str \| null | 当前草稿 hash；**第二次起必须带**，否则 409 `draft_workflow_not_sync` |
| `conversation_variables` | list | 本工作流未使用，`[]` |

注意：
- **顶层不能写 `environment_variables`**（extra=forbid 会 400）。环境变量只能通过
  `environment_variable_patch` 提交；本工作流不需要环境变量，故不写。
- 空图必须带 `force=true`，否则 400 `Saving an empty workflow requires force=true.`
- 节点包装（前端依赖，缺一不可）：`id / type:"custom" / position / positionAbsolute /
  width:242 / height / selected:false / sourcePosition:"right" / targetPosition:"left" /
  zIndex:0 / data`。
- 边包装：`{id:"{source}-{handle}-{target}-target", source, sourceHandle, target,
  targetHandle:"target", type:"custom", zIndex:0, selected:false,
  data:{sourceType,targetType,isInIteration:false,isInLoop:false,iteration_id:null,loop_id:null}}`。
- 分支出边 `sourceHandle`：问题分类器用 class id `"1".."5"`，条件分支用 `"true"`/`"false"`，
  普通节点用 `"source"`。

## 4. 节点映射表（26 个）

| # | 节点 ID | 类型 | 标题 | 关键配置 / 输出 |
|---|---|---|---|---|
| N01 | `start` | start | 开始 | 入参 `user_query`(text-input,必填,≤2000)、`chat_history`(paragraph,可选) |
| N02 | `intent_classifier` | question-classifier | 意图分类 | query=`start.user_query`；5 类 id `1..5`（车型咨询/报价库存/预约试驾/价格异议/闲聊无关） |
| N03 | `profile_extract` | llm | 画像抽取 | 严格 JSON：budget/scene/family_num/charge/intend_car/missing；temp 0.1 |
| N04 | `profile_parse` | code | 画像解析 | 输入 `profile_extract.text`；输出 budget/scene/family_num/charge/intend_car/profile_json/is_complete/missing_text/profile_summary |
| N05 | `profile_check` | if-else | 画像是否完整 | `profile_parse.is_complete is true` → true 分支 |
| N06 | `profile_followup` | llm | 画像追问 | 追问话术，作为本轮最终回复 |
| N07 | `kb_query_build` | template-transform | 检索词拼装 | 输出 `output` = 「客户问题：… / 客户画像：… / 想了解：续航 轴距 空间 配置 指导价」 |
| N08 | `kb_models` | knowledge-retrieval | 车型知识检索 | query=`kb_query_build.output`；dataset 见上；`top_k:3`、`score_threshold:0.5`（enabled）；输出 `result` |
| N09 | `recommend` | llm | 车型推荐 | context=`kb_models.result`（Prompt 里用 `{{#context#}}`）；FABE + 邀约；temp 0.5 |
| N10 | `quote_extract` | parameter-extractor | 报价要素抽取 | 参数 `brand`、`model`（string，非必填）；prompt 模式 |
| N11 | `inventory_api` | http-request | 库存报价接口 | GET `{STUB}/api/inventory?brand=…&model=…`；超时 5/10/5；`retry_enabled:false`；`error_strategy:"default-value"` |
| N12 | `inventory_ok` | if-else | 库存接口是否成功 | `inventory_api.status_code = "200"`（字符串存值） |
| N13 | `quote_reply` | llm | 报价话术 | 输入 `inventory_api.body`；必须带「以门店核算为准」 |
| N14 | `quote_fallback` | llm | 报价兜底 | 不编库存/价格，引导到店或留资 |
| N15 | `appt_extract` | parameter-extractor | 预约要素抽取 | 参数 `name`/`phone`/`model`/`time` |
| N16 | `appt_complete` | if-else | 预约要素是否齐全 | 四个 `not empty` 且 and |
| N17 | `appt_followup` | llm | 预约追问 | 只问缺失项 |
| N18 | `appt_api` | http-request | 提交预约工单 | POST JSON 单 item；**retry 关闭**（防重复建单）；`error_strategy:"default-value"` |
| N19 | `appt_ok` | if-else | 工单是否受理 | `appt_api.body contains "ticket_id"` |
| N20 | `appt_confirm` | llm | 预约成功通知 | 从 `appt_api.body` 取 ticket_id/车型/时间，不得编造 |
| N21 | `appt_fallback` | llm | 预约失败兜底 | 致歉、不谎称成功 |
| N22 | `kb_scripts` | knowledge-retrieval | 话术知识检索 | query=`start.user_query`；`top_k:3`、阈值 0.5 |
| N23 | `objection_reply` | llm | 异议回复 | context=`kb_scripts.result`；未指明车型时不得引用具体参数 |
| N24 | `smalltalk_reply` | template-transform | 闲聊兜底 | 固定话术，不回答无关问题 |
| N25 | `merge_reply` | variable-aggregator | 汇聚回复 | `output_type:"string"`，9 路变量，输出 `output` |
| N26 | `end` | end | 结束 | 输出 `response = merge_reply.output` |

### 4.1 边（33 条）

```text
start → intent_classifier (source)
intent_classifier → 1 profile_extract / 2 quote_extract / 3 appt_extract / 4 kb_scripts / 5 smalltalk_reply
profile_extract → profile_parse → profile_check
profile_check → true kb_query_build / false profile_followup
kb_query_build → kb_models → recommend
quote_extract → inventory_api → inventory_ok
inventory_ok → true quote_reply / false quote_fallback
appt_extract → appt_complete
appt_complete → true appt_api / false appt_followup
appt_api → appt_ok → true appt_confirm / false appt_fallback
kb_scripts → objection_reply
profile_followup / recommend / quote_reply / quote_fallback / appt_followup /
appt_confirm / appt_fallback / objection_reply / smalltalk_reply → merge_reply (9 条)
merge_reply → end
```

### 4.2 运行期关键参数

| 项 | 值 | 原因 |
|---|---|---|
| LLM 模型 | deepseek-flash，`mode:"chat"` | 环境已配置且实测可用 |
| temperature | 抽取/分类 0.1，推荐/异议 0.5–0.7，默认 0.3 | 抽取要稳定，话术要自然 |
| `reasoning_format` | `"separated"`（所有 LLM 节点） | deepseek-flash 会吐 `<think>…</think>`；separated 让节点返回去掉推理的 clean text，避免污染最终回答 |
| 检索阈值 | 0.5（不是规划里的 0.7） | 实测命中分 0.52–0.75，0.7 会全部过滤 |
| HTTP 超时 | connect 5 / read 10 / write 5 秒 | 桩接口本地毫秒级返回 |
| HTTP 异常 | `error_strategy:"default-value"` | 超时/连接失败时输出默认 `status_code=0`，走兜底分支且不增加边 |
| POST 重试 | 关闭 | 预约接口重放会重复建单 |
| 聚合器 | 取第一个有值的分支 | 9 路互斥，正常只会有一路有值 |

### 4.3 检索词为什么这么写

命中测试（dataset hit-testing，top_k=5、无阈值）对比：

| query | top1 | top2 | top3 | 是否含 01 车型库 |
|---|---|---|---|---|
| 「画像+原话+检索目标」旧模板 | 04 0.7567 | 04 0.6882 | 02 0.6864 | 否（01 排第 4，0.6344） |
| 现模板（原话在前 + 画像 + 想了解关键词） | 04 0.7048 | **01 0.6155** | 02 0.5963 | 是 ✅ |

现模板让 `top_k=3` 就能召回 `01_门店车型库.md`（550km / 2750mm 等参数），
E2E-1 才能引用真实参数而不是「没有资料」。知识库文档或分块改动后需重新跑命中测试校准。

## 5. 验证

### 5.1 结构 + schema

- `python tools/dify/validate_workflow_draft.py` → `OK: 结构校验全部通过`
- 容器内 `validate_in_container.py` → `[payload] OK` + 26 个节点逐行 `OK` + `RESULT: OK`

### 5.2 端到端（draft/run）

```powershell
python tools/dify/dify.py job tools\dify\jobs\run_case1.json
python .tmp_tests\parse_run.py .tmp_tests\run_case1.txt
```

5 条主用例的 job 在 `tools/dify/jobs/run_case1.json` … `run_case5.json`，
SSE 输出落 `.tmp_tests/run_caseN.txt`。用例定义与断言见 `docs/dify/guide/e2e_tests.md`。

最近一次全量结果（draft hash `f3f7f4f6…`）：

| 用例 | 输入摘要 | 实际路径 | 结果 |
|---|---|---|---|
| case1 | 三口之家/预算15万/有桩/家用通勤/推荐SUV | start→分类(1)→画像→完整→检索→推荐→汇聚 | succeeded；推荐车型A，引用 CLTC 550km、轴距 2750mm，结尾邀约试驾，无 `<think>` |
| case2 | 车型A落地多少钱、有没有现车、优惠 | 分类(2)→抽参数→库存接口→报价话术 | succeeded；「有现车3台 / 参考落地价17.2万 / 现金5000+置换8000+24期0息」，带「以门店核算为准」 |
| case3 | 周六上午试驾车型A，张三+手机号 | 分类(3)→抽4要素→齐全→POST→确认 | succeeded；工单 `APPT-20261117-0003`，提醒带身份证/驾驶证 |
| case4 | 这个车太贵了，能不能便宜点 | 分类(4)→话术检索→异议回复 | succeeded（连跑 3 次稳定）；共情+价值拆解+置换/金融，先问客户看的是 A/B/C 哪款，未张冠李戴 |
| case5 | 今天吃什么 | 分类(5)→固定话术 | succeeded；固定引导话术，不出现车型/价格 |

## 6. 问题与修复记录（踩过的坑）

1. **parameter-extractor 的 `query` 必须是扁平的变量选择器**（`["start","user_query"]`）。
   写成 `[["start","user_query"]]` 会报 `query.0 Input should be a valid string`，
   运行时 `variable_pool.get(node_data.query)` 直接当选择器用。
2. **if-else 的数字条件值要存字符串**：`status_code = "200"`。
   `Condition.value` 类型是 `str|Sequence[str]|bool|None`，传 int 200 会校验失败；
   运行时 `_normalize_numeric_values` 会 `float("200")` 再比较。
3. **knowledge-retrieval 的实体类路径**在 `core.workflow.nodes.knowledge_retrieval.entities`，
   不在 graphon 里；容器内校验脚本需要 `sys.path.insert(0, "/app/api")`。
4. **deepseek-flash 的 `<think>` 推理文本**会混进最终回答：LLM 节点加
   `reasoning_format:"separated"` 解决。question-classifier / parameter-extractor
   没有这个开关，靠 instruction 约束输出。
5. **分类器偶尔不吐 JSON**：一次「这个车太贵了」的运行报
   `could not find json block in the output.`（分类器解析的是 JSON 块）。
   根因是 instruction 里写了「只输出一个类别名」，与节点模板的 JSON 输出要求冲突。
   改成只描述判定边界、不规定输出格式后，连跑 8 次全部正常。
6. **重复提交 409**：第二次 POST 必须带服务端当前 `hash`，否则
   `draft_workflow_not_sync`。`submit_draft.py` 已自动 `GET draft` 取 hash。
7. **空应用首次保存**：旧 graph 为空时 hash 为 null 也能成功；换成 `--no-hash` 时只适用于空应用。

## 7. 回滚与发布

- **改坏了想回退**：`python tools/dify/dify.py get /console/api/apps/479d4779-9f96-4553-a8d8-e0401da50d35/workflows/draft`
  可拿到当前草稿 graph，覆盖/导出备份后再重新提交；所有版本也可在
  `GET /console/api/apps/{id}/workflows` 里看到。
- **发布**：控制台点「发布」或
  `POST /console/api/apps/{id}/workflows/publish`（body `{marked_name, marked_comment}`）。
  发布后用应用 API Key 走 `POST /v1/workflows/run`（blocking，inputs 传 `user_query`）。
- **重新生成后重新提交**：改 `build_workflow_draft.py` 里的 prompt/参数 → 重跑第 2 节 4 条命令。
  不建议在控制台 UI 手改后不回写脚本，否则下次提交会把 UI 改动覆盖掉。

## 8. 已知风险 / 待确认

| 风险 | 影响 | 现状与建议 |
|---|---|---|
| deepseek-flash 是推理模型 | 分类器/参数抽取偶发 JSON 解析失败 | 已通过 instruction 规避；若线上仍偶发，可把 N02/N10/N15 的模型换成 `qwen3.7-flash` 或 `qwen2.5:7b`（节点单独换，不影响话术节点） |
| 检索阈值 0.5 偏低 | 可能召回弱相关片段 | 命中分 0.50–0.75；如答案开始跑偏，调高到 0.55 并同步更新本文件与 nodes.md |
| 追问是「本轮结束」 | 不是真正的多轮会话 | Workflow 图必须 DAG，不能连回 start；前端需把历史拼进 `chat_history` 再调一次，或后续升级为 Chatflow + 会话变量（见 nodes.md §10） |
| 客户画像每次重新抽取 | 多轮时预算等信息不会累积 | 同上：升级 Chatflow 后用变量赋值节点持久化 `customer_profile` |
| SSRF 放行依赖 Docker 网关网段 | 换机器/改网段后 HTTP 节点 403 | 放行值 `192.168.65.0/24`；报错文案见 `docs/dify/guide/backend_stub.md` |
| api_stub 无鉴权、工单在内存 | 仅演示用，重启即丢 | 生产要换真实预约系统 + 鉴权 |
| 生成脚本与画布双来源 | UI 手改会被覆盖 | 以脚本为准；UI 只做查看/试跑 |
| `height` 是估算值 | 画布卡片高度可能不完美 | 不影响执行，只影响 UI 观感 |
| 单一 end 节点 | 所有分支汇聚到 `response` | API 调用方只需读 `outputs.response`；如需调试信息，可在 end 增加 `intent`/`profile_json` 输出 |

### 待 Lead 确认的字段/取舍

1. `top_k`：任务单要求 3，实测 3 能覆盖 01/04/02；若希望推荐更稳，可改 4。
2. `score_threshold`：任务单写 0.5，已按实测保留；0.7 会过滤掉全部命中。
3. 顶层 `environment_variables`：任务单要求写 `[]`，但 1.19 的 payload `extra="forbid"`
   会 400，故**不写**；需要环境变量时改走 `environment_variable_patch`。
4. 分类器/抽取节点模型是否统一 deepseek-flash：目前统一；如要降低 JSON 失败率可换 qwen。
5. `chat_history` 入参：已声明但 Prompt 未引用，留给前端后续拼多轮。

## 9. 变更记录（v1 → v3）

> 第 4 节的「26 节点 / 33 边」与节点映射表是 **v1 基线**；v2 起在 `merge_reply` 与 `end`
> 之间插入 8 个合规节点（+10 边），当前共 **34 节点 / 43 边**，合规链路细节见
> [`compliance.md`](./compliance.md)。本节只记录版本流转与 v3 改动。

| 版本 | 发布 marked_name | draft hash（提交后） | 发布 version id | 节点/边 | 要点 |
|---|---|---|---|---|---|
| v1 | （未标记） | `f3f7f4f6…ba71` | `0e7aabe9-e5e9-4b3e-94f3-6d3605fd7278` 等 | 26 / 33 | 5 分支、RAG 推荐、报价/预约 HTTP、异议话术、闲聊兜底 |
| v2 | `v2-合规校验` | `a839409ddfd383de1f138292a63b3550befba22fe039a02c5ade0e68aca18012` | `8cfde6e5-c1fc-4eb9-b833-b29614eb965a`（created_at 1794909150） | 34 / 43 | 两级合规：level1 硬拦截 + LLM 修正与复核，end 增加 `compliance_flag` |
| v3 | `v3-真实知识库` | `a30b2da96486b2efe5ee23056f5fd53798758c3772ab3aedcd8999076bb1cf37` | `90604d4b-9fdf-4b1d-a59d-ece3a08b4d92`（created_at 1794909700） | 34 / 43 | 真实知识库 9 篇上线后，Prompt 去掉占位车型口径 |

### 9.1 v3 改了什么（只改 Prompt 文案，结构不动）

真实知识库 `docs/dify/knowledge_real/`（9 篇）导入后，`build_workflow_draft.py` 中以下位置
把「车型A/B/C、17.2 万、星辰/远航/灵动」替换为真实车型示例：

1. `PROFILE_SYSTEM`：`intend_car` 示例改为「五菱宏光 MINIEV」「比亚迪海鸥」。
2. `RECOMMEND_SYSTEM` 规则 1：只推荐知识库上下文中真实存在的车型（示例 五菱宏光 MINIEV、
   比亚迪海鸥、零跑 A10 等），**不得编造知识库中没有的车型与参数**，上下文没提到的一律不说。
3. `QUOTE_EXTRACT_INSTRUCTION`：`model` 示例改为真实车型；`quote_extract` 的 `brand`/`model`
   字段 description 同步改为「五菱/比亚迪/零跑」与真实车型。
4. `OBJECTION_SYSTEM` 规则 6：未指明车型时，改问「关注的是具体哪一款（如五菱宏光 MINIEV、比亚迪海鸥）」，
   避免张冠李戴引用参数。
5. `appt_extract` 的 `model` 字段 description 改为真实车型示例。
6. `KB_QUERY_TEMPLATE` 上方注释补充：v2 的命中分是在旧 4 篇库上校准的，真实库（9 篇）口径变化后
   如召回漂移，需重新做 hit-testing 校准（模板本身未改）。

改后 `build_workflow_draft.py` 内 `车型A/B/C`、`星辰/远航/灵动`、`17.2` 的计数均为 0；
重新生成得到 34 节点 / 43 边 / 93547 bytes，本地结构校验与容器内 pydantic 校验均通过，
提交后草稿 hash `a30b2da9…`，发布为 `v3-真实知识库`（发布 warning 与 v2 相同：finalize 读
三分支输出，属预期行为，实测兼容）。

### 9.2 v3 实测（draft/run，7 条全部 succeeded）

| # | 输入 | 意图/路径 | compliance_flag | 关键输出 |
|---|---|---|---|---|
| 1 | 五菱宏光 MINIEV 续航多少？ | 车型咨询 → 画像追问 | passed | 未直接报数，先确认「预算 4-6 万 / 代步还是通勤 / 能否装桩」 |
| 2 | 比亚迪海鸥怎么样？ | 车型咨询 → 画像追问 | passed | 认可城市代步定位，追问预算/用途/充电条件 |
| 3 | 这个车太贵了 | 价格异议 → 话术检索 | llm_fixed | 共情 + 透明落地口径 + 置换/24 期免息（附条件），反问具体车型（宏光 MINIEV、海鸥） |
| 4 | 今天中午吃什么 | 闲聊 → 固定话术 | passed | 固定引导话术，无车型/价格 |
| 5 | 我家三口人，预算8万左右，有充电桩，比亚迪海鸥是不是能自动驾驶、解放双手？ | 车型咨询 → 推荐 | **blocked_level1** | hit「自动驾驶」，整条换一级兜底话术 |
| 6 | …五菱宏光 MINIEV 续航多少，和海鸥比怎么样？ | 车型咨询 → 检索 → 推荐 | llm_fixed | 知识库显示 CLTC 120–215km、轴距 2010mm、三门四座、家充每公里电费约 5 分，并说明三口之家后排进出的不适合点 |
| 7 | 五菱宏光 MINIEV 落地多少钱，有没有现车？ | 报价库存 → 库存接口 | llm_fixed | 现车 2 台、参考价 4.98 万、现金优惠 2000 + 置换 3000（附条件）+ 24 期低息，注明以门店核算为准 |

- 7 条输出均**不含** `车型A/B/C` 占位名；case 5 的 `blocked_level1` 证明合规链路未被 v3 改动破坏。
- case 1/2 走追问而非直接推荐，是「画像不全先追问」的既定设计，不是回归问题。
- case 7 的报价数字来自 `tools/dify/api_stub.py` 当前数据（真实车型口径，Lead 维护），
  接口不可用时仍走 `quote_fallback`，不会编造数字。

### 9.3 v3.1 合规兜底判定修正（Lead，2026-11-17）

v3 发布后 Lead 复跑 8 条用例时发现 case1（完整画像→RAG 推荐）返回的是异常兜底话术、
`compliance_flag=llm_unfixed`，但草稿运行时该次查询实际是正常的画像追问。

- 根因：`VERIFY_CODE_TEMPLATE` 用 `is_fallback = UNFIXABLE_MARKER in raw` 判断「LLM 未修正」，
  而 `UNFIXABLE_MARKER` = `以上信息仅供参考`。正常回答只要结尾带这句免责声明，就被判为不可修正，
  整条被替换成异常兜底话术。
- 修复：改成「整段就是兜底话术」才算不可修正——
  `bare = re.sub(r"\s+", "", raw)`、`marker = re.sub(r"\s+", "", UNFIXABLE_MARKER)`、
  `is_fallback = bare.startswith(marker) and len(bare) <= 140`。
- 重新生成：34 节点 / 43 边 / 93802 bytes，本地校验 + 容器内 pydantic 校验通过，
  草稿 hash `6699ee6c…`，发布为 `v3.1-合规兜底判定修正`。
- 复跑 8 条：7 条 succeeded，case8 为 partial-succeeded（分支内有节点失败，但 end 输出的
  `blocked_level1` 兜底话术正确，属已知现象）；case1 修复后按完整画像正常推荐
  吉利银河星愿 + 零跑 A10（FABE、续航工况声明、智驾免责），`llm_fixed`。
- 坑：`POST /workflows/publish` 的 `marked_comment` **最多 100 字符**，超长直接 422
  `string_too_long`（本次踩过一次）；`marked_name` 也建议精简。

### 9.4 检索来源附注（v4 / v4.1）

需求：在对话窗口的回答下方展示本次命中的知识库片段。

- 新增 `sources_attach`（Code）节点，接在 `compliance_finalize` 与 `end` 之间：
  合并 `kb_models.result` / `kb_scripts.result`，按（文档名, 片段前 40 字）去重取前 3 条，
  在 `response` 末尾追加「参考来源（知识库检索，非实时价格/库存）」区块，同时输出结构化 `sources`。
- 只在 `passed` / `llm_fixed` 时追加；`blocked_level1` / `llm_unfixed` 不追加（避免带出被拦截内容）。
- `end` 输出变为三个：`response`（含来源区块）、`sources`（JSON 字符串）、`compliance_flag`。
- 规模 35 节点 / 44 边；`compliance_finalize → sources_attach → end`。
- v4 第一版相关度显示 `-`：Dify 1.19 检索结果把 `score` 放在 `metadata.score` 里，`it["score"]` 取不到；
  v4.1 改为两处兜底取值，实测显示 0.63 / 0.62 / 0.62。
- 提交 hash：v4 `7771532e…`（含修正），发布版本名 `v4.1-检索来源含相关度`。

### 9.5 回滚

`POST /console/api/apps/479d4779-9f96-4553-a8d8-e0401da50d35/workflows/publish`
按需把任一历史 version 重新发布即可；v2 = `8cfde6e5…`、v1 见
`GET /console/api/apps/{id}/workflows` 列表。
