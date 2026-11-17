# 两级合规校验改造（v2-合规校验）

> 应用：`汽车销售接待智能体`（app id `479d4779-9f96-4553-a8d8-e0401da50d35`，Workflow 模式）
> 产出版本：**v2-合规校验**（workflow version id `8cfde6e5-c1fc-4eb9-b833-b29614eb965a`，created_at 1794909150）
> 画布规模：**34 节点 / 43 边**（v1 为 26 / 33），提交体 `tools/dify/workflow_draft.json` 93287 bytes
> 词库：`tools/dify/compliance_words.json`（Lead 维护，本改造**只读不改**）

---

## 1. 改造目标与整体链路

原画布 9 个终态先汇聚到 `merge_reply`（variable-aggregator），再直接进 `end`。v2 在二者之间插入两级合规校验：

```
merge_reply (汇聚回复)
   └─→ compliance_scan   一级扫描：code 节点扫 level1 违规词（77 个）
        └─→ compliance_if  if-else：passed is true ?
             ├─ true  ─→ compliance_llm     二级修正：LLM 按合规 Prompt 改写
             │            └─→ compliance_verify  code 复核：改写稿再扫 level1 + 识别「不可修正」
             │                 └─→ compliance_if2  if-else：passed2 is true ?
             │                      ├─ true  ─→ compliance_finalize ─→ end
             │                      └─ false ─→ compliance_fallback2 ┘
             └─ false ─→ compliance_fallback  一级命中兜底（固定话术）
                          └──────────────→ compliance_finalize ─→ end
```

- `end` 输出两个字段：`response`（最终给客户的话术）、`compliance_flag`（`passed` / `llm_fixed` / `blocked_level1` / `llm_unfixed`）。
- 一级命中 → 直接兜底，**不让违规原文进入 LLM 改写**（成本最低、最安全）；只有一级干净的回答才走 LLM 修正，避免把已违规的文案再喂给模型。
- 追问/兜底/闲聊等分支同样经过校验链（它们也可能被 LLM 生成成违规表述），保证「所有出口唯一」。

## 2. 节点清单（8 个新增节点）

| 节点 ID | 类型 | 标题 | 关键配置 | 输入 | 输出 |
| --- | --- | --- | --- | --- | --- |
| `compliance_scan` | code (python3) | 一级合规扫描 | 构建时把 77 个 level1 词内联进代码；`_normalize` 后子串匹配 | `text` = `["merge_reply","output"]` | `passed`(bool)、`hit_words`(str)、`text`(str，原文透传) |
| `compliance_if` | if-else | 一级是否通过 | `["compliance_scan","passed"] is true` | — | 分支 `true` / `false` |
| `compliance_llm` | llm | 二级合规修正 | `deepseek-flash`，temp 0.1，`reasoning_format=separated`；system=`llm_compliance_system_prompt`（`{{answer_text}}`→`{{#compliance_scan.text#}}`） | — | `text`（即“checked_answer”，节点输出变量名固定为 `text`） |
| `compliance_verify` | code (python3) | 二级合规复核 | 去 `<think>`；再扫 level1；`UNFIXABLE_MARKER="以上信息仅供参考"` 判「LLM 判不可修正」 | `llm_text`=`["compliance_llm","text"]`、`original_text`=`["compliance_scan","text"]` | `passed2`(bool)、`final_text`(str)、`hit_words2`(str)、`verify_flag`(passed/llm_fixed) |
| `compliance_if2` | if-else | 二级是否通过 | `["compliance_verify","passed2"] is true` | — | 分支 `true` / `false` |
| `compliance_fallback` | template-transform | 一级拦截兜底 | 固定话术 = `fallback.hit_level1` | 无变量 | `output` |
| `compliance_fallback2` | template-transform | 不可修正兜底 | 固定话术 = `fallback.llm_unfixable` | 无变量 | `output` |
| `compliance_finalize` | code (python3) | 合规结果汇聚 | 非空判定：`unfixable > fixed > fallback` | `fallback_text`、`unfixable_text`、`fixed_text`、`verify_flag` | `response`、`compliance_flag` |

`end` 的 outputs 改为：

```json
[
  {"variable":"response","value_selector":["compliance_finalize","response"],"value_type":"string"},
  {"variable":"compliance_flag","value_selector":["compliance_finalize","compliance_flag"],"value_type":"string"}
]
```

## 3. 新增/变更的边（11 条）

| # | source | sourceHandle | target |
| --- | --- | --- | --- |
| 1 | `merge_reply` | `source` | `compliance_scan` |
| 2 | `compliance_scan` | `source` | `compliance_if` |
| 3 | `compliance_if` | `true` | `compliance_llm` |
| 4 | `compliance_if` | `false` | `compliance_fallback` |
| 5 | `compliance_llm` | `source` | `compliance_verify` |
| 6 | `compliance_verify` | `source` | `compliance_if2` |
| 7 | `compliance_if2` | `true` | `compliance_finalize` |
| 8 | `compliance_if2` | `false` | `compliance_fallback2` |
| 9 | `compliance_fallback` | `source` | `compliance_finalize` |
| 10 | `compliance_fallback2` | `source` | `compliance_finalize` |
| 11 | `compliance_finalize` | `source` | `end` |

> 原 `merge_reply → end` 直连边已删除；`merge_reply` 现在只有一条出边指向 `compliance_scan`。

## 4. 词库与维护方式（`compliance_words.json`）

结构：

```json
{
  "_meta": {...},
  "level1": {"绝对化":[32],"安全虚假宣传":[8],"智能驾驶违规":[10],"金融违规":[9],
             "违法违规":[8],"恶意贬低":[5],"虚假承诺":[5]},   // 共 77 词，硬拦截
  "level2": {"极限描述","质保权益","金融方案","续航里程","服务承诺","性能描述"}, // 39 词，LLM 修正参考
  "level3": {"竞品负面","争议","政策","二手车"},               // 28 词，提示级别
  "fallback": {"hit_level1":"…","llm_unfixable":"…","always_append":"…"},
  "llm_compliance_system_prompt": "…{{answer_text}}…"
}
```

- **level1 = 硬拦截**：命中即整条回答换成兜底话术（本改造实现）。
- **level2 / level3**：不硬拦截，只写进 LLM 系统 Prompt 作为修正依据（Prompt 已覆盖绝对化、智驾、续航/质保、金融、竞品、语气六类规则）。
- **词库内联机制**：`build_workflow_draft.py` 在生成 JSON 时读取 `compliance_words.json`，把 level1 词表（去重、按长度倒序）直接写进 `compliance_scan` / `compliance_verify` 两个 code 节点的 `LEVEL1_WORDS` 常量。运行时不读文件、不依赖挂载，**改词库必须重新生成并提交 draft 才生效**。
- 维护流程：改 `tools/dify/compliance_words.json` → `python tools/dify/build_workflow_draft.py` → `python tools/dify/validate_workflow_draft.py` → 容器内 pydantic 校验 → `python tools/dify/submit_draft.py` → 回归 8 条用例 → 发布新版本。
- 词表按长度倒序是为了少词优先、`hit_words` 更可读；匹配前统一 `_normalize`：转小写、`％→%`、去全角空格、去所有空白字符，因此「１００％」「1 0 0 %」这类规避写法也能命中。
- 只收录「违规短语」而不是单字（如不收录裸「最」，避免误伤「最近/最后」）。

## 5. 二级 LLM 修正 Prompt（`llm_compliance_system_prompt`）

系统 Prompt 全文（运行时把末尾 `{{answer_text}}` 替换为 `{{#compliance_scan.text#}}`，由 Dify 在调用前插值）：

```
角色：汽车销售合规审核员
任务：审核并修正汽车销售回答内容，确保符合《广告法》与行业宣传规范。

审核规则：
1. 绝对化用词处理：删除所有“最、第一、顶级、唯一、100%、永不、绝对”等极限用词，替换为客观描述，例如“同级别中表现较为出色”。
2. 智能驾驶合规：L2/L2+级只能称为“智能辅助驾驶”，严禁出现“自动驾驶、无人驾驶、解放双手”等表述；必须补充说明“驾驶员需全程把控车辆安全”。
3. 续航与质保：续航必须标注工况标准，补充“实际续航受气温、驾驶习惯影响会有浮动”；质保、终身权益必须补充前提条件，如“首任非营运车主，以厂家官方条款为准”。
4. 金融宣传：免息、低首付必须说明适用条件，不得出现无前提的“零首付、零利息”表述。
5. 竞品评价：不得贬低任何竞品品牌，仅客观陈述差异；删除所有恶意贬低、造谣类表述。
6. 语气规范：专业友好，不得出现攻击性、诱导性违规话术，不得虚假承诺。

输出要求：
- 内容需要修正：直接输出修正后的完整回答。
- 内容完全合规：直接输出原文，不做任何修改。
- 如内容存在重大违规且无法自动修正：只输出这句兜底话术——以上信息仅供参考，具体车辆参数、优惠政策与服务详情请以门店官方公示为准，建议您到店咨询专业销售顾问。
- 仅输出最终文本，不要解释、不要标注修改点、不要额外说明。
```

用户 Prompt 只有一句「请审核上面的待审核内容。…」（待审核内容已在 system 末尾）。LLM 节点另设 `reasoning_format="separated"`，避免 deepseek-flash 的 `<think>` 推理文本混进最终输出（v1 踩过这个坑）。

## 6. 兜底话术（与词库 fallback 一致）

- 一级命中（`fallback.hit_level1`）：
  > 抱歉，相关表述不符合广告宣传规范，具体车辆参数、优惠政策与服务条款请以门店官方公示为准，欢迎您到店详细咨询销售顾问。
- LLM 判不可修正（`fallback.llm_unfixable`）：
  > 以上信息仅供参考，具体车辆参数、优惠政策与服务详情请以门店官方公示为准，建议您到店咨询专业销售顾问。

## 7. `compliance_flag` 语义

| 取值 | 含义 | 触发路径 |
| --- | --- | --- |
| `passed` | 原文无 level1 词，LLM 原样放行 | scan passed → LLM 未改动 |
| `llm_fixed` | 原文无 level1 词，LLM 修正了表述 | scan passed → LLM 有改动且复核通过 |
| `blocked_level1` | 一级扫词命中，直接兜底 | scan failed |
| `llm_unfixed` | LLM 判无法修正，输出二级兜底 | verify 命中 `UNFIXABLE_MARKER` 或复核仍有 level1 词 |

`compliance_finalize` 用「非空判定」而不是分支名：Dify code 节点里未执行分支的输入变量是 `None`/空串，因此按 `unfixable_text > fixed_text > fallback_text` 的顺序取第一个非空值，再返回对应 flag。

## 8. 验证证据（8 条用例，全部 `succeeded`）

| 用例 | 输入（摘要） | 意图 | flag | 一级命中 | 关键输出/证据 |
| --- | --- | --- | --- | --- | --- |
| case1 | 三口之家/15万/有桩/家用通勤/推荐SUV | 车型咨询 | `llm_fixed` | 无 | 推荐车型A（550km/2750mm/快充30min）；LLM 把「最贴合」→「较贴合」、L2→「智能辅助驾驶（需全程把控）」、补「CLTC 工况」；563 字 |
| case2 | 车型A落地价、现车、优惠 | 报价库存 | `llm_fixed` | 无 | 现车3台、落地17.2万、现金5000+置换≤8000+24期0息、3–7工作日提车、以门店核算为准 |
| case3 | 周六上午试驾车型A/张三/13800138000 | 预约试驾 | `passed` | 无 | 工单 `APPT-20261117-0005`、周六上午、身份证/驾驶证提醒；原文直接放行 |
| case4 | 这个车太贵了 | 价格异议 | `llm_fixed` | 无 | 共情+价值拆解+置换/金融，不承诺降价；补质保前提、续航浮动说明 |
| case5 | 今天吃什么 | 闲聊无关 | `passed` | 无 | 固定引导话术，无车型/价格 |
| case6 | 三口/15万/有桩：车型A能自动驾驶、解放双手？ | 车型咨询 | `blocked_level1` | `自动驾驶` | 推荐节点原文「车型A是L2级辅助驾驶，**不是自动驾驶**…」→ 命中 `自动驾驶` → 一级兜底 |
| case7 | 三口/15万/有桩：100%安全、永不自燃？ | 车型咨询 | `blocked_level1` | `100%安全，100%，永不自燃，永不` | 原文「没有任何车能做出这种承诺…」→ 命中 `100%` / `永不自燃` → 一级兜底 |
| case8 | 车型A零首付零利息能办吗？有现车吗 | 报价库存 | `blocked_level1` | `零首付` | 原文「零首付能不能办…需顾问确认」→ 命中 `零首付` → 一级兜底 |

- 回归口径：case1–5 全部 `succeeded`，且最终 `response` 中 **level1 命中数为 0**（用同一份词库对输出再扫一遍验证）。
- 对抗口径：case6–8 是「客户主动索要违规承诺」，模型原文其实在**拒绝**这些说法，但一级硬拦截按「出现即拦」处理，输出统一换成 60 字以内的合规兜底，`compliance_flag=blocked_level1`。
- 证据文件：`.tmp_tests/run_case1.txt … run_case8.txt`（draft/run SSE），解析器 `.tmp_tests/parse_run.py`。

## 9. 与用户方案的两处偏差（及原因）

1. **「IF-ELSE 多关键词或匹配」→ 改为 code 节点扫描**
   - 用户方案：在 IF-ELSE 里用「包含任一关键词」条件实现词匹配。
   - 实际问题：77 个词 × 7 类，若都塞进 if-else，条件数量爆炸（77 个 condition 或 77 条分支），画布不可维护、每加一个词都要改图；而且 if-else 没有 `lower()` / 去空白 / `％→%` 归一化能力，`100 ％`、`100％` 之类的规避写法会漏。
   - 采用方案：`compliance_scan` code 节点内置词表 + 归一化 + 子串匹配，输出 `passed` / `hit_words`；**IF-ELSE 保留下来只做「命中/未命中」二分流**（`compliance_if` / `compliance_if2` 仍用 if-else，符合用户「用 IF-ELSE 分流」的意图）。好处：词库只在一处维护、加词只改 JSON 不改图、命中词可回显便于排查、匹配前可归一化。
2. **任务列出的 6 个节点 → 实际 8 个**
   - 增加 `compliance_fallback2`：一级命中与「LLM 判不可修正」的兜底话术不同，不能共用同一节点。
   - 增加 `compliance_finalize`：`end` 节点不能做条件选择，也不能计算 `compliance_flag`；三条路径（一级兜底/二级兜底/修正放行）必须先汇聚成一个节点，才能同时输出 `response` 与 `compliance_flag`。
   - 命名说明：LLM 节点输出变量名在 Dify 里固定为 `text`，任务描述里的 `checked_answer` 是语义名，实际选择器是 `["compliance_llm","text"]`。

## 10. 操作命令（本机已跑通）

```powershell
cd C:\Users\zhou\Desktop\汽车销售智能体

# 1) 改词库/改节点后重新生成 + 本地结构校验
python tools\dify\build_workflow_draft.py
python tools\dify\validate_workflow_draft.py

# 2) 容器内用真实 pydantic 模型校验提交体与 34 个节点 data
docker cp tools/dify/workflow_draft.json docker-api-1:/tmp/workflow_draft.json
docker cp tools/dify/validate_in_container.py docker-api-1:/tmp/validate_in_container.py
docker exec docker-api-1 sh -lc "cd /app/api && .venv/bin/python /tmp/validate_in_container.py"
# 期望最后一行 RESULT: OK

# 3) 提交 draft（自动 GET 服务端 hash，409 会自动用新 hash 重试）
python tools\dify\submit_draft.py
# 本次结果：200 {"result":"success","hash":"a839409ddfd383de1f138292a63b3550befba22fe039a02c5ade0e68aca18012"}

# 4) 回归用例（8 条）
python tools\dify\dify.py job tools\dify\jobs\run_case1.json
python .tmp_tests\parse_run.py .tmp_tests\run_case1.txt
# …case2–case8 同理

# 5) 发布
python tools\dify\dify.py job tools\dify\jobs\publish_v2.json
# 本次结果：200 {"result":"success","created_at":1794909150}
```

**发布结果**：版本 `8cfde6e5-c1fc-4eb9-b833-b29614eb965a`，`marked_name = v2-合规校验`，
`marked_comment = 34 节点/43 边：新增两级合规校验（level1 硬拦截 77 词 + LLM 修正与复核），end 增加 compliance_flag`。
发布接口返回一条 warning：`3 variable references may read a skipped branch output`（指向 `compliance_finalize` 读取三条分支的 `fallback_text` / `unfixable_text` / `fixed_text`）——这是**预期行为**，`compliance_finalize` 用非空判定兼容未执行分支（8 条用例三条路径均已实测通过）。

## 11. 已知限制与风险

1. **否定式提及也会被硬拦截**：case6–8 里模型其实在拒绝违规说法（「不是自动驾驶」「没有任何车能保证 100% 安全」），但字符串包含即命中 level1 → 整条回答被换成兜底。安全优先可以接受，但会牺牲一点信息量。若要放行否定语境，可在 `compliance_scan` 前加「否定词前缀白名单」（如 `不是/并非/不能/没有/无法` 紧邻命中词时不计入），本次**未做**，避免误放行真正的违规话术。
2. **level2 / level3 不硬拦截**：只作为 LLM 修正依据，模型偶尔仍可能漏改；最终正确性依靠 level1 复核兜底。
3. **LLM 修正可能改变原意**：二级修正由模型改写，极端情况下会删掉有用信息（温度 0.1 + 明确规则可缓解）；每次改 Prompt/词库都应重跑 8 条用例。
4. **词库内联**：词库改动必须重新 build + submit + publish 才生效，不能只改 JSON 文件。
5. **发布版与 draft 分离**：线上 `/v1/workflows/run` 用发布版；继续改 draft 不影响线上，直到再次 publish。
6. **Workflow 单轮限制不变**：追问分支仍是「本轮结束」，多轮需前端把上文拼进 `user_query`。
7. **回滚**：v1 版本仍保留（version `b7247ca0-b4e2-4e30-b617-fff56b712897`、`0e7aabe9-…`）。需要回滚时可在控制台「版本历史」切回 v1，或把 `build_workflow_draft.py` 里的合规节点开关关掉后重新提交并发布新版本。

## 12. 文件清单

| 文件 | 说明 |
| --- | --- |
| `tools/dify/build_workflow_draft.py` | 生成器（含 8 个合规节点、词库内联、Prompt 注入） |
| `tools/dify/workflow_draft.json` | 34 节点 / 43 边 / 93287 bytes 的 draft 提交体 |
| `tools/dify/validate_workflow_draft.py` | 本地结构校验（含合规链路专检） |
| `tools/dify/validate_in_container.py` | 容器内 pydantic 校验（payload + 34 节点） |
| `tools/dify/submit_draft.py` | 带服务端 hash 的 draft 提交（409 自动重试） |
| `tools/dify/jobs/run_case1–8.json` | 8 条回归/对抗用例的 draft/run job |
| `tools/dify/jobs/publish_v2.json` | 发布 v2-合规校验 |
| `tools/dify/compliance_words.json` | 词库（Lead 维护，本次未修改） |
| `docs/dify/guide/compliance.md` | 本文档 |
