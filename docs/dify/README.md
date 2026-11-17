# 汽车销售 Dify 工作流 · 操作手册

本目录是「汽车销售接待智能体」在 Dify 上的落地产物与操作手册。目标：门店销售接待 AI，按
意图识别 → 客户画像采集 → 车型推荐 RAG → 报价/库存 → 预约试驾 → 异议处理 → 兜底 跑通一条完整链路。

## 1. 当前状态（2026-11-17 实测）

| 项目 | 值 |
|---|---|
| Dify 版本 | 1.19.0（Docker，`http://localhost/`） |
| 控制台账号 | 本机管理员账号，凭据不入库（运行脚本前设 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量） |
| 向量库 | qdrant（`VECTOR_STORE=qdrant`，容器 `docker-qdrant-1`） |
| 知识库 | `汽车销售知识库`，dataset id `403fbc9d-3c82-4077-8033-6761821f68f3` |
| 嵌入模型 | `langgenius/tongyi/tongyi` + `text-embedding-v4`（工作区默认模型已设为它） |
| 知识库文档 | **9 篇真实资料**（`docs/dify/knowledge_real/`），全部 `completed`；tokens 7845 / 7620 / 6261 / 2008 / 47403 / 15345 / 34907 / 10508 / 12559 |
| 检索配置 | 语义检索，top_k=3，相似度阈值 0.5（15 条真实召回用例：14 命中 / 1 条闲聊正确拦截） |
| 应用 | `汽车销售接待智能体`，app id `479d4779-9f96-4553-a8d8-e0401da50d35`（mode=workflow） |
| 画布规模 | 35 节点 / 44 边（合规链路 8 节点 + 检索来源附注 1 节点）；已发布 `v1-初版`、`v2-合规校验`、`v3-真实知识库`、`v3.1-合规兜底判定修正`、`v4-检索上下文`、`v4.1-检索来源含相关度`（当前线上版本） |
| 合规校验 | 一级 77 个违禁词硬拦截（命中直接返回 58 字兜底）→ 二级 LLM 合规改写 → 二次复核；词库 `tools/dify/compliance_words.json` |
| 检索上下文 | 回答末尾自动附「参考来源」：命中文档名 · 相关度 · 片段摘要（最多 3 条）；API 额外返回结构化 `sources` 字段；仅 `passed`/`llm_fixed` 时附，拦截/兜底不附 |
| 联调结果 | 8 条用例（5 业务 + 3 合规拦截）7 条 succeeded、case8 partial-succeeded（分支内节点失败但合规兜底输出正确）；追问类边界用例（「我想买辆车」「帮我约个试驾」）正常追问、无环 |

页面入口：

- 画布：`http://localhost/app/479d4779-9f96-4553-a8d8-e0401da50d35/workflow`
- 知识库：`http://localhost/datasets/403fbc9d-3c82-4077-8033-6761821f68f3/documents`
- 应用 API 文档：`http://localhost/app/479d4779-9f96-4553-a8d8-e0401da50d35/develop`

## 2. 目录导航

```
docs/dify/
├── knowledge/                  # 早期 4 份占位示例文档（已被 knowledge_real 取代，仅作参考）
│   ├── 01_门店车型库.md
│   ├── 02_销售标准话术库.md
│   ├── 03_购车流程与服务说明.md
│   └── 04_客户画像匹配规则.md
├── knowledge_real/             # 真实资料拆分后的 9 篇知识库文档（已导入 Dify）
│   ├── 01_微型入门代步与紧凑型轿车.md   # 10 款车型
│   ├── 02_中型轿车与紧凑型SUV.md       # 10 款车型
│   ├── 03_中大型SUV与MPV.md            # 8 款车型
│   ├── 04_高端特色代表.md              # 2 款车型（共 30 款）
│   ├── 05_购车基础与三电.md            # 术语 01–13
│   ├── 06_智能驾驶与座舱.md            # 术语 14–16（14 号合规重写）
│   ├── 07_价格交易与权益保险.md        # 术语 17–23
│   ├── 08_需求分析与产品介绍.md        # 术语 24–25
│   └── 09_客户跟进与竞品对比.md        # 术语 26–27（28/29 违规词清单未入库）
├── prompts/
│   └── nodes.md                # 节点 Prompt、分支条件、兜底矩阵、DSL 片段
└── guide/
    ├── kb_setup.md             # 知识库手动搭建手册（分段、metadata、命中测试、12 条 FAQ）
    ├── recall_tests.md         # 20 条召回用例 + 阈值对照表（占位版，真实版见 tools/dify/recall_cases.json）
    ├── kb_real_report.md       # 真实资料拆分报告：清单/切分建议/61 条变更/额外补充/问题清单/合规自检
    ├── compliance.md           # 两级合规校验链路设计与实现说明
    ├── workflow_build.md       # 画布生成/提交/验证/回滚 + 节点映射表 + 踩坑
    ├── backend_stub.md         # 库存/报价/预约三接口契约、SSRF 原理与排查
    └── e2e_tests.md            # 5 主用例 + 5 边界用例 + 断言脚本

tools/dify/
├── dify.py                     # 宿主机侧控制台 API 入口（把请求送进 docker-api-1 容器执行）
├── dify_console.py             # 容器内执行脚本（登录 + CSRF + 通用 HTTP 调用）
├── import_kb.py                # 批量上传文档 → 建文档 → 轮询索引状态（支持 --kb-dir/--purge/--delete-only）
├── check_recall.py             # 召回测试：逐条 hit-testing，输出 TopN 与命中判定
├── recall_cases.json           # 15 条真实内容召回用例
├── compliance_words.json       # 合规词库（level1 77 / level2 39 / level3 28 + 兜底话术 + LLM Prompt）
├── build_workflow_draft.py     # 生成 workflow_draft.json（34 节点/43 边）
├── validate_workflow_draft.py  # 本地结构校验
├── submit_draft.py             # 带服务端 hash 提交 draft（避免 409）
├── run_cases.py                # 走服务 API 跑 8 条 E2E 用例
├── api_stub.py                 # 库存/报价/预约接口 stub（0.0.0.0:8000，车型与真实知识库一致）
└── jobs/                       # 每个 console API 调用一个 job JSON
```

## 3. 本机环境改动记录（重装/迁移时必看）

1. **向量库从 pgvector 切到 qdrant**：原 `docker/.env` 里 `VECTOR_STORE=pgvector`，但 pgvector
   的 compose profile 没有启动，索引任务全部报 `could not translate host name "pgvector"`。
   现改为 `COMPOSE_PROFILES=qdrant,postgresql,collaboration` + `VECTOR_STORE=qdrant`（qdrant 镜像本机已有）。
   改完执行 `docker compose up -d api worker` 重建。
2. **SSRF 放行内网地址**：Dify 的 HTTP 节点走 `ssrf_proxy`（squid），默认拒绝内网 IP。
   已在 `docker/.env` 追加 `SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.65.0/24`（`host.docker.internal = 192.168.65.254`），
   并重建 `ssrf_proxy` / `agent_ssrf_proxy`。验证：
   `docker exec docker-api-1 sh -c "curl -s -x http://ssrf_proxy:3128 http://host.docker.internal:8000/health"`。
3. **工作区默认 embedding 模型**：新工作区没设默认模型时建知识库会报
   `Default model not found for text-embedding`。已通过
   `POST /console/api/workspaces/current/default-model` 设为 `text-embedding-v4`（llm 默认 `deepseek-flash`）。
   换机器或重置数据后需要重设。

## 4. 启动与自检

```powershell
cd C:\Users\zhou\Desktop\dify\docker
docker compose ps                      # 需要 db_postgres / redis / qdrant / api / worker / plugin_daemon / web / nginx
docker compose up -d                   # 起全栈（profile 已在 .env 配好）
# 自检
Invoke-WebRequest http://localhost/console/api/setup | Select-Object -Expand Content   # 应返回 step:finished
```

冷启动常见现象：`plugin_daemon` 起来后的头 1–2 分钟内，索引任务可能报
`PluginDaemonInternalServerError ... /dispatch/text_embedding/num_tokens`。等 1 分钟后对失败文档
`POST /console/api/datasets/{id}/retry` 即恢复（本项目就是这样恢复 01/02/03 的）。

## 5. 控制台 API 用法（脚本化操作的基础）

宿主机不能直接复用浏览器 Cookie，所以 `tools/dify/dify.py` 的做法是：同步 `dify_console.py` 进
`docker-api-1:/tmp`，在容器内用 `requests.Session` 登录（密码 base64 编码）、带
`X-CSRF-Token`，再访问 `127.0.0.1:5001`。

```powershell
# 登录 + 列模型
python tools\dify\dify.py login
python tools\dify\dify.py models text-embedding

# 任意接口：写一个 job JSON
# {"method":"GET","path":"/console/api/apps","params":{"page":1},"out":"tools/dify/refs/apps.json"}
python tools\dify\dify.py job tools\dify\jobs\get_draft.json
```

job 字段：`method` / `path` / `json`（body）/ `params` / `files[]`（本地附件，自动 `docker cp` 进容器）/
`data`（表单）/ `out`（把响应保存回本机）/ `raw`（直接打印）。响应 `>=400` 时退出码非 0，但
`out` 文件仍会保存错误体，便于排查。

## 6. 知识库导入与验证

```powershell
# 真实知识库（9 篇）导入：上传 + 建文档 + 轮询索引
python tools\dify\import_kb.py --kb-dir docs\dify\knowledge_real --manifest tools\dify\kb_real\manifest.json
# 清空旧文档（只删不导，GET 后 DELETE）
python tools\dify\import_kb.py --delete-only
# 只查索引状态
python tools\dify\import_kb.py --status --manifest tools\dify\kb_real\manifest.json
# 单篇索引失败时（plugin_daemon 抖动）
python tools\dify\dify.py job tools\dify\jobs\retry_index.json
```

召回测试（`tools/dify/check_recall.py`，默认读 `recall_cases.json`，结果写 `refs/recall_real.json`）：

```powershell
python tools\dify\check_recall.py --cases tools\dify\recall_cases.json --top 3 --threshold 0.5 --out tools\dify\refs\recall_real.json
```

真实知识库召回基线（top3 / 阈值 0.5，15 条用例：hit 14、empty 1）：

| 查询 | Top1 | 分数 |
|---|---|---|
| 五菱宏光 MINIEV 续航多少 | 01 五菱宏光 MINIEV | 0.714 |
| 比亚迪海鸥多少钱、续航怎么样 | 01 比亚迪海鸥 | 0.813 |
| 吉利银河星愿车机和空间 | 01 吉利银河星愿 | 0.791 |
| 什么是 CLTC 续航 | 05 CLTC 工况 | 0.787 |
| L2 级辅助驾驶能脱手吗 | 06 L2 级说明 | 0.794 |
| 保值率是什么意思 | 07 残值与保值率 | 0.812 |
| 今天中午吃什么 | —（阈值拦截） | 低于 0.5 |

结论：阈值 0.5 在 9 篇真实文档下可用（14/15 命中，Top1 全中对应文档）；若后续召回不足，
优先把 top_k 调到 4 再考虑 rerank，不建议先降阈值（会更易召回无关段）。

## 7. 工作流：生成 → 校验 → 提交 → 发布 → 联调

```powershell
# 1) 生成 draft graph（35 节点/44 边，含合规链路 + 检索来源附注）
python tools\dify\build_workflow_draft.py
# 2) 本地结构校验
python tools\dify\validate_workflow_draft.py
# 3) 提交（会自动拉服务端 hash，避免 409 draft_workflow_not_sync）
python tools\dify\submit_draft.py
# 4) 发布
python tools\dify\dify.py job tools\dify\jobs\publish_v1.json
# 5) 首次需要建 API key（保存到 .dify_api_key，已 gitignore）
python tools\dify\dify.py job tools\dify\jobs\create_api_key.json
# 6) 走服务 API 跑 8 条用例（5 业务 + 3 合规拦截）
python tools\dify\run_cases.py --all
python tools\dify\run_cases.py --case 1
python tools\dify\run_cases.py --q "帮我约个试驾"
```

服务 API 直连 `http://localhost/v1/workflows/run`（blocking），请求体：

```json
{"inputs": {"user_query": "...", "customer_profile": ""}, "response_mode": "blocking", "user": "case-runner"}
```

stub 接口（HTTP 节点调用）：

```powershell
Start-Process C:\Python314\python.exe -ArgumentList 'tools\dify\api_stub.py','--port','8000' -WindowStyle Hidden
Invoke-WebRequest http://127.0.0.1:8000/health
```

## 8. 在页面上怎么操作（不写脚本的手动路径）

1. 登录 `http://localhost/`（邮箱 + 密码）。
2. **知识库** → 选 `汽车销售知识库` → 可看 9 篇真实文档与分段；右上「召回测试」可用同一套查询做命中验证；
   换内容直接在文档列表里删除旧文档再上传新文件（或走 `import_kb.py`）。
3. **应用** → `汽车销售接待智能体` → 编排画布可看 35 个节点（含合规链路与来源附注）；右侧「运行」可直接用 8 条用例调试。
4. 点「发布」→「发布」后，服务 API 才运行最新版本（只改 draft 不发布，`/v1/workflows/run` 仍是旧版本）。
5. 「访问 API」→ 创建 API 密钥 → 用 curl/PowerShell 调 `/v1/workflows/run`。

## 9. 换成真实知识库内容的 SOP

当前知识库已经是**真实资料拆分后的 9 篇**（`docs/dify/knowledge_real/`），导入流程已跑通；以后换新资料按同样路径：

1. 把新资料放到 `txt/`（或直接改 `knowledge_real/` 对应篇目），按「一篇一主题、表格保留表头、一问一答不混排」拆成 Markdown。
2. 入库前做合规预处理：删 level1 违禁词、level2 改客观表述、补前提条件（详见 `docs/dify/guide/compliance.md`）。
3. `python tools\dify\import_kb.py --kb-dir docs\dify\knowledge_real --manifest tools\dify\kb_real\manifest.json`，
   索引失败单篇用 `jobs/retry_index.json` 重试，直到全部 `completed`。
4. `python tools\dify\check_recall.py ...` 跑召回确认 Top1 命中；再 `run_cases.py --all` 跑 8 条用例。
5. 若改了 Prompt/节点 → `build_workflow_draft.py` → `validate_workflow_draft.py` → `submit_draft.py` → 发布。

注意：`tools/dify/api_stub.py` 里的价格、库存、优惠、金融方案仍是**示例口径**（车型与知识库一致，
数字非真实门店数据），对客演示前必须替换成真实接口；知识库里的参数来自用户提供的资料，使用前需业务复核时效性。

## 10. 两级合规校验链路（已实现）

用户给的方案已落到画布（`docs/dify/guide/compliance.md` 有完整设计与实现说明）：

```
业务节点回答 merge_reply
  └─ compliance_scan（Code：77 个 level1 违禁词，lower + ％→% + 去空白后包含匹配）
       └─ compliance_if
            ├─ 命中 → compliance_fallback（58 字标准兜底话术）→ compliance_finalize
            └─ 未命中 → compliance_llm（deepseek-flash，六条合规规则改写）
                 └─ compliance_verify（Code 二次复核 + UNFIXABLE 标记）
                      └─ compliance_if2
                           ├─ 修正失败 → compliance_fallback2（异常兜底话术）
                           └─ 通过 → compliance_finalize
                                └─ end（outputs: response + compliance_flag）
```

- 词库：`tools/dify/compliance_words.json`（level1 77 / level2 39 / level3 28，含两段兜底话术与 LLM 审核 Prompt）；
  改词库后必须重新 `build_workflow_draft.py` → submit → publish 才生效（词库在构建时内联进 Code 节点）。
- 兜底话术一字不改：一级 58 字「抱歉，相关表述不符合广告宣传规范…」；异常兜底「以上信息仅供参考…」。
- 已实测：命中 level1 的三条用例（自动驾驶/解放双手、100%安全/永不自燃、零首付零利息）全部 `blocked_level1`，
  返回 58 字兜底；正常 5 条用例 level1 命中 0，其中 3 条被 LLM 做客观化改写（`llm_fixed`）。
- 已知偏差：一级硬拦截对否定式提及也生效（「不是自动驾驶」也会整条换成兜底），当前按「安全优先」保留；
  如需降低误杀，可给词库加「不是/并非/没有」前缀白名单（尚未做）。

## 11. 检索上下文展示（v4.1）

回答生成后追加一个 `sources_attach`（Code）节点：把两条知识检索节点（`kb_models` / `kb_scripts`）的命中结果
去重后取前 3 条，拼到回答末尾，并作为结构化字段输出。

对话窗口里看到的形态（`response` 末尾）：

```
---
参考来源（知识库检索，非实时价格/库存）：
1. 01_微型入门代步与紧凑型轿车.md · 相关度 0.63 · 吉利银河星愿 - **级别**：小型纯电轿车 - **动力类型**：纯电动 …
2. 01_微型入门代步与紧凑型轿车.md · 相关度 0.62 · 零跑 A10 - **级别**：小型纯电 SUV …
3. 05_购车基础与三电.md · 相关度 0.62 · 三、不同动力类型选购决策树 …
```

服务 API 的 `outputs` 里同时多一个 `sources` 字段（JSON 字符串），便于前端自己渲染成卡片：

```json
{"data": {"outputs": {
  "response": "…（含上面的参考来源区块）",
  "sources": "[{\"document\": \"01_微型入门代步与紧凑型轿车.md\", \"score\": \"0.63\", \"snippet\": \"吉利银河星愿 …\"}]",
  "compliance_flag": "llm_fixed"
}}}
```

规则与边界：

- 只在 `compliance_flag` 为 `passed` / `llm_fixed` 时追加；一级拦截（`blocked_level1`）与不可修正兜底（`llm_unfixed`）
  **不追加**，避免把触发拦截的内容带出去。
- 只有走「车型推荐」或「价格异议」分支（即真的查了知识库）才有来源；报价库存、预约试驾、闲聊、兜底分支
  不查知识库，所以没有来源区块（不会伪造来源）。
- 相关度取自检索结果的 `metadata.score`（Dify 1.19 的 chunk 对象里 `score` 在 metadata 内，v4 曾取错位置显示 `-`，
  v4.1 已修）；片段截断 90 字、空白折叠。
- 改这段逻辑：`tools/dify/build_workflow_draft.py` 里的 `SOURCES_CODE_TEMPLATE` → 重新 build → submit → publish。

## 12. 已知坑与限制

- 宿主机 PowerShell 5.1 不能自定义 `Cookie`/`Authorization` 受限头，所以控制台 API 必须走容器内 requests；
  `pwsh` 不存在，`.ps1` 被执行策略拦截。
- PowerShell 控制台是 GBK，直接 `Get-Content` 看 UTF-8 中文文档/JSON 会乱码；用 `python -c "print(open(...))"`
  或编辑器查看。
- Workflow 是 DAG，「画像不完整 → 追问」实现为**本轮结束输出追问话术**，多轮拼接依赖前端把上轮对话拼进
  `user_query`；若要多轮记忆需升级为 Chatflow + 会话变量。
- 真实知识库 9 篇由 `txt/` 原始资料拆分而来，共 61 条变更（详见 `docs/dify/guide/kb_real_report.md`）：
  28/29 两份违规词清单**未入库**（仅作词库同步来源），碰撞安全/充电桩安装/置换评估/上牌材料等主题仍缺失。
- `deepseek-flash` 偶发输出 think 文本或 JSON 块解析失败（已通过 `reasoning_format=separated` 与
  instruction 约束缓解）；仍不稳可切 `qwen3.8-flash`。
- 索引 `plugin_daemon` 首启 500、`pgvector` 未启动、SSRF 拦内网 IP —— 三个环境坑都在第 3/4 节。
- `dataset` 的 `retrieval_model` 在「未设置」时返回 `null`，设置后返回字段名叫 `retrieval_model_dict`。
- 检索来源区块只在检索分支出现；如果你希望报价/库存回答也显示「数据来源：库存接口」，
  可以再给 `sources_attach` 加一段接口来源说明（当前未做，避免伪造知识库来源）。
- 控制台 draft 提交必须带服务端最新 `hash`，否则 409 `draft_workflow_not_sync`。

## 13. 安全提醒

- `.dify_api_key`、`.dify_token`、登录密码都只在本机使用，已加入 `.gitignore`；不要把 API key 贴到聊天/仓库。
- 演示用手机号 13812345678 等为假数据；真实知识库入库前先脱敏（客户信息、内部价格政策）。
- 当前部署为单机 Docker + 默认密钥（`QDRANT_API_KEY=difyai123456` 等），仅限本机/内网，不要直接暴露公网。
