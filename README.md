# 汽车销售智能体（Dify 工作流版）

用 **Dify 1.19 工作流**落地的门店销售接待 AI：意图识别 → 客户画像采集 → 知识库 RAG 车型推荐 → 报价/库存查询 → 预约试驾 → 异议处理 → 兜底，并带**两级合规审核**与**检索来源附注**。

> 本仓库主分支当前是 Dify 版实现。更早的 V1 原型（Python 知识库工具链 + QA 报告）保留在提交历史 `b507a66` 中，可 `git checkout b507a66` 查看。

## 一、它能做什么

| 场景 | 行为 |
|---|---|
| 车型咨询 / 参数查询 | 提取客户画像（预算、用途、家庭人数、充电条件、意向车型），追问缺失项，命中知识库后用 FABE 推荐 1–2 款真实车型，结尾邀约试驾 |
| 报价 / 库存查询 | 抽取车型 → 调用门店 HTTP 接口 → 整理报价话术，标注「以门店核算为准」 |
| 预约试驾 | 抽取姓名/手机号/车型/时间 → 缺失项追问 → 提交工单（ticket_id） |
| 价格 / 配置异议 | 检索异议话术库 → 生成共情 + 价值拆解式回复，不承诺降价 |
| 闲聊 / 无关 | 标准兜底话术 |
| 合规风险表述 | 一级关键词硬拦截（命中直接返回标准兜底）→ 二级 LLM 合规改写 → 二次复核 |
| 所有检索类回答 | 末尾附「参考来源」：文档名 · 相关度 · 片段摘要（最多 3 条），API 额外返回结构化 `sources` |

实测样例（8 条用例详见 `docs/dify/README.md`）：

- 「我刚结婚，小两口，预算 10 万左右，家里有充电桩，上下班通勤 + 周末家用，想买空间大一点的纯电」→ 推荐**吉利银河星愿**（轴距 2650mm、CLTC 310–410km）与**零跑 A10**（2630mm、400–510km、L2 智能辅助驾驶），附来源与合规提示。
- 「这个车太贵了」→ 共情 + 产品价值拆解 + 置换/金融方案，不承诺降价。
- 「这车能自动驾驶吗，可以解放双手吧」→ 被一级违禁词拦截，返回 58 字标准合规话术。

## 二、整体架构

```
开始 → 意图分类（问题分类器，5 类）
  ├─1 车型咨询 → 画像提取(LLM) → 完整性判断 ─┬─ 不完整 → 追问并结束本轮
  │                                          └─ 完整 → 知识库检索(车型库+画像规则) → 推荐(LLM)
  ├─2 报价库存 → 车型抽取 → HTTP 库存/报价接口 → 报价整理(LLM) → 接口失败兜底
  ├─3 预约试驾 → 信息抽取 → 完整性判断 → HTTP 提交工单 → 确认话术
  ├─4 价格异议 → 话术库检索 → 异议回复(LLM)
  └─5 闲聊/无关 → 兜底话术
        ↓
  合并回答 → 合规扫描(Code, 77 词) → 命中? → 标准兜底
                                   └─ 未命中 → 合规改写(LLM) → 复核(Code) → 异常兜底 / 放行
        ↓
  来源附注(Code) → 结束（输出 response / sources / compliance_flag）
```

- **画布规模**：35 节点 / 44 条边，Workflow 模式（DAG，单轮追问即结束本轮，前端拼接下一轮）。
- **知识库**：`汽车销售知识库`，9 篇真实资料（约 7.8 万字，30 款车型 + 术语 + 流程 + 话术 + 画像规则），语义检索 top_k=3、阈值 0.5，15 条召回用例命中 14 条、Top1 全部命中。
- **模型**：Dify 内置供应商 `langgenius/deepseek/deepseek`（deepseek-flash）+ `langgenius/tongyi/tongyi`（text-embedding-v4）。
- **向量库**：qdrant（Docker 容器，`VECTOR_STORE=qdrant`）。

## 三、目录结构

```
.
├── docs/dify/
│   ├── README.md                 # 操作手册（状态表、目录、启动自检、API、导入、发布、联调、坑）
│   ├── knowledge_real/           # 9 篇真实知识库文档（已导入 Dify）
│   ├── knowledge/                # 早期 4 篇占位示例（已被 knowledge_real 取代）
│   ├── prompts/nodes.md          # 35 节点逐节点中文 Prompt / 分支条件 / 兜底矩阵
│   └── guide/
│       ├── kb_real_report.md     # 真实资料拆分报告（61 条变更、问题清单、缺口）
│       ├── kb_setup.md           # 知识库搭建手册
│       ├── compliance.md         # 两级合规链路设计与实测
│       ├── workflow_build.md     # 画布生成 / 提交 / 发布 / 回滚
│       ├── backend_stub.md       # 门店接口契约与 SSRF 排查
│       └── e2e_tests.md          # 端到端用例与断言
├── tools/dify/
│   ├── dify.py                   # 宿主机侧控制台 API 包装（docker exec 进容器）
│   ├── dify_console.py           # 容器内执行的控制台客户端（cookie + CSRF）
│   ├── import_kb.py              # 批量上传 / 建文档 / 轮询索引 / 删除
│   ├── check_recall.py           # 召回评测（hit-testing）
│   ├── build_workflow_draft.py   # 代码生成 35 节点 DSL（单一事实源）
│   ├── validate_workflow_draft.py
│   ├── submit_draft.py           # 提交草稿（hash 防冲突）
│   ├── run_cases.py              # 发布版 API 跑 8 条用例
│   ├── api_stub.py               # 门店库存/报价/预约接口 mock（纯标准库）
│   ├── compliance_words.json     # 三级违规词库 + 合规 Prompt + 兜底话术
│   ├── workflow_draft.json       # 生成的画布 DSL
│   ├── jobs/ · refs/             # 请求体与响应证据（脱敏后）
│   └── kb_real/                  # 真实文档构建脚本与变更记录
└── txt/                          # 原始销售资料（拆分前的 28 份源文件）
```

## 四、快速开始

前置：Docker + Dify 1.19（`http://localhost/`）、可用的 DeepSeek/Tongyi 模型供应商、管理员账号。

```bash
# 0) 凭据只走环境变量，不写进仓库
export DIFY_EMAIL=you@example.com
export DIFY_PASSWORD='***'

# 1) 导入 9 篇真实知识库文档（自动上传、建文档、轮询索引）
python tools/dify/import_kb.py --kb-dir docs/dify/knowledge_real --manifest tools/dify/kb_real/manifest.json --status

# 2) 召回评测（15 条真实用例）
python tools/dify/check_recall.py --cases tools/dify/recall_cases.json

# 3) 生成画布 DSL 并校验
python tools/dify/build_workflow_draft.py
python tools/dify/validate_workflow_draft.py

# 4) 提交草稿并发布
python tools/dify/submit_draft.py
python tools/dify/dify.py --job-file tools/dify/jobs/publish_v41.json

# 5) 起门店接口 mock，跑 8 条端到端用例
python tools/dify/api_stub.py --port 8000
python tools/dify/run_cases.py
```

> 环境变量/路径细节、SSRF 放行（`SSRF_PROXY_ALLOW_PRIVATE_IPS`）、默认 embedding 模型设置、plugin_daemon 偶发 500 等踩坑，都写在 `docs/dify/README.md` 与 `docs/dify/guide/`。

## 五、合规设计（核心亮点）

| 层级 | 实现 | 说明 |
|---|---|---|
| 一级硬拦截 | Code 节点扫描 77 个违规词（绝对化 / 安全虚假 / 智驾违规 / 金融违规 / 违法违规 / 贬低竞品 / 虚假承诺），归一化大小写与全角后匹配 | 命中直接返回 58 字标准兜底话术，不进入 LLM 生成 |
| 二级合规改写 | LLM 合规审核员（DeepSeek，温度 0.1）按 6 条规则改写：绝对化改客观描述、智驾只称「智能辅助驾驶」并补「驾驶员需全程把控车辆安全」、续航标 CLTC 并补浮动说明、质保补「首任非营运车主」前提、金融政策补适用条件、不贬低竞品 | 输出仅最终文本，不解释过程 |
| 二次复核 | Code 节点检查是否仍含违规词 / 是否已退化为整段兜底话术 | 不可修正时替换为异常兜底话术 |
| 来源附注 | 合并检索结果去重取前 3 条，附「文档名 · 相关度 · 摘要」，API 返回结构化 `sources` | 拦截/兜底分支不附来源，避免暗示有依据 |

词库与 Prompt 在 `tools/dify/compliance_words.json`；设计与实测见 `docs/dify/guide/compliance.md`。

## 六、实测结果

| 用例 | 结果 |
|---|---|
| 完整画像 → 推荐 | ✅ 推荐 2 款真实车型，FABE 结构，附来源 |
| 车型报价 / 现车 | ✅ 现车 3 台、参考价、优惠明细、以门店核算为准 |
| 预约试驾 | ✅ 工单 `APPT-YYYYMMDD-NNNN` |
| 价格异议 | ✅ 共情 + 价值拆解 + 置换/金融方案，不承诺降价 |
| 闲聊 | ✅ 兜底话术 |
| 自动驾驶 / 解放双手 | ✅ blocked_level1，58 字兜底 |
| 100% 安全 / 永不自燃 | ✅ blocked_level1 |
| 零首付零利息 | ✅ blocked_level1（partial-succeeded：分支内有节点失败但输出正确） |

## 七、已知限制

- **示例数据口径**：知识库中的指导价、库存、优惠为演示用示例值，接入真实门店前需替换；报价/库存以 `api_stub.py` 的 mock 接口演示，非真实 DMS。
- **单轮对话**：Workflow 模式不支持会话变量，追问需前端拼下一轮；如要多轮记忆可升级为 Chatflow。
- **检索**：仅语义检索、未启用 rerank（rerank 需额外模型）；缺失主题（碰撞安全、充电桩安装、置换评估、上牌材料）暂未入库。
- **稳定性**：Dify 1.19 的 plugin_daemon 偶发 `num_tokens` 500，重试即可；一级硬拦截对否定式表述同样生效（安全优先，可后续加白名单）。
- **未上线**：本项目为原型，未做并发压测、权限体系与真实业务系统对接。

## 八、安全说明

- 仓库不含任何 token / 密码 / cookie：控制台凭据只从 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量读取，`.dify_api_key`、`.dify_token`、`.dify_csrf` 与 `tools/dify/refs/api_key.json` 均已被 `.gitignore` 排除。
- `tools/dify/refs/` 下的响应样本已去除密钥；`txt/` 为个人整理的销售资料，价格与库存为示例口径。
- 若你要复跑：请使用自己的 Dify 实例与账号，并在发布前检查 `docs/dify/README.md` 的环境改动记录（尤其是 SSRF 放行）。

## 九、版本记录

| 版本 | 内容 |
|---|---|
| v1-初版 | 26 节点 5 分支主干，占位知识库 |
| v2-合规校验 | 加两级合规链路（8 节点），77 词硬拦截 |
| v3-真实知识库 | 9 篇真实文档入库，Prompt 去占位化 |
| v3.1 | 修正合规兜底判定（仅当整段为兜底话术才判不可修正） |
| v4 / v4.1 | 回答附检索来源与相关度（35 节点 / 44 边，当前线上版本） |

更详细的运行状态、页面入口与操作步骤见 [docs/dify/README.md](docs/dify/README.md)。
