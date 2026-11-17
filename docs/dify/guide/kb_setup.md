# Dify 1.19.0 知识库搭建手册（汽车销售知识库）

> 适用实例：本机 Docker 部署的 Dify（镜像 `langgenius/dify-api:1.19.0`，访问入口 `http://localhost/`，nginx 80 端口）。
> 文档来源：`docs/dify/knowledge/` 下 4 份 Markdown（车型库 / 话术库 / 流程服务 / 画像规则）。
> 状态标注：**✅ 已实测** = 已用本机实例的只读 HTTP 路由探测确认；**📝 待登录验证** = 按 Dify 通用行为编写，拿到 console token 后需用真实响应校准。
> 本轮（凭据未交付前）只做「不依赖登录」的准备工作；第 8 节为拿到 token 后的执行草案。

## 0. 目标配置一览

| 配置项 | 目标值 | 备注 |
|---|---|---|
| 知识库数量 | 1 个 | 名称建议「汽车销售知识库」 |
| 文档数量 | 4 份 | 对应 `01`–`04` 四个 md 文件，同一知识库 |
| 嵌入模型 | bge-m3 | 以「模型供应商」中实际名称为准（provider + model 名） |
| 索引方式 | 高质量 | 使用嵌入模型的向量索引 |
| 分段模式 | 通用分段 | 第一版基线；父子分段见 3.3，作为后续优化 |
| 分段参数 | 分隔符 `\n\n`；最大 500 tokens；重叠 50 tokens | 4 份文档每个小节已控制在 800 字以内（多数 150–400 字） |
| 检索方式 | 向量检索 | 混合检索作为对照实验，不进入首轮验收 |
| Top K | 3 | 规划「召回 3 条」 |
| Score 阈值 | 0.7（开启） | 规划值；执行时按 recall_tests.md 第 5 节做阈值校准观察 |
| Rerank | 关闭 | 首轮基线，避免多变量 |
| 元数据 | category / source / version / is_demo | 见第 4 节 |

## 1. 前置检查：模型供应商与嵌入模型

### 1.1 确认 bge-m3 已配置（UI 路径）

1. 打开 `http://localhost/`，用管理员账号登录。
2. 进入「设置」→「模型供应商」（Settings → Model Provider）。
3. 在已配置的供应商列表中找到能提供 **Text Embedding** 的供应商（常见为 Ollama、Xinference、OpenAI-API-compatible、LocalAI 等）。
4. 展开该供应商的「Text Embedding」分组，确认列表中存在 `bge-m3`；可点「模型设置 / 测试」验证连通性。
5. 记录两个值：**供应商名称（provider）** 与 **模型名称（model）**，后续 API 的 `embedding_model_provider` / `embedding_model` 必须与之完全一致。

### 1.2 若 bge-m3 尚未配置

1. 在「模型供应商」页安装/启用对应供应商插件（本机插件守护进程容器为 `docker-plugin_daemon-1`，需处于运行状态）。
2. 按供应商类型填写 Base URL 与 API Key（本机模型服务地址不要写 `localhost`，容器内访问宿主机需用 `host.docker.internal` 或宿主机局域网 IP，具体以部署方式为准）。
3. 添加模型，类型选 **Text Embedding**，模型名填 `bge-m3`，维度 `1024`（bge-m3 输出维度），上下文长度按模型能力填写（bge-m3 支持 8192）。
4. 保存后用「测试」或新建知识库时的模型下拉框验证可见。

### 1.3 需要交付给自动化的信息

| 信息 | 示例 | 用途 |
|---|---|---|
| 供应商名称 | `ollama` / `langgenius/openai_api_compatible/openai_api_compatible` | API `embedding_model_provider` |
| 模型名 | `bge-m3` 或 `bge-m3:latest` | API `embedding_model` |
| 维度 | 1024 | 校验向量库写入 |
| 是否配置 Rerank | 否 / bge-reranker | 决定 `reranking_enable` |

> 📝 待确认：bge-m3 是否已在 Dify 中配置、供应商与模型名到底叫什么。这是 API 自动化的第一个阻塞项。

## 2. 新建知识库（UI 操作）

### 2.1 创建入口

1. 顶部导航进入「知识库」。
2. 点「创建知识库」。
3. 本机若出现「知识流水线（Knowledge Pipeline）」与「传统知识库」两种入口，**选择传统知识库的数据源方式「导入已有文本」**（原因见 8.5 注意事项：流水线知识库用 API 上传的文件可能不按流水线处理）。
4. 进入分段与索引设置向导。

### 2.2 命名与权限

- 名称：`汽车销售知识库`
- 描述：`汽车销售智能体 V1 知识库，含门店车型库、销售话术库、购车流程与服务说明、客户画像匹配规则（示例数据）`
- 可见范围：按团队要求选择「仅自己」或「所有成员」；单机演示建议「所有成员」，便于后续 Agent 引用。
- 索引方式：**高质量**。
- 嵌入模型：**bge-m3**。

### 2.3 上传 4 份文档

1. 在创建向导的「上传文件」步骤，选择 `docs/dify/knowledge/` 下的 4 个文件：
   - `01_门店车型库.md`
   - `02_销售标准话术库.md`
   - `03_购车流程与服务说明.md`
   - `04_客户画像匹配规则.md`
2. 下一步进入「分段设置」，按第 3 节填写参数，先看分段预览再提交。
3. 点「保存并处理」，开始异步索引。

### 2.4 等待索引完成

- 文档列表中每份文档状态会经历：排队中 → 解析中 → 分段中 → 索引中 → **已索引**（失败则显示「索引失败」）。
- 4 份文档全部显示「已索引」，且分段数不为 0，才算入库完成。
- 若长时间停在排队/索引中，检查 `docker-worker-1` 是否健康；索引失败时查看该文档的「错误信息」或容器日志。

### 2.5 验收检查点

- [ ] 知识库详情共 4 份文档，0 份失败
- [ ] 每份文档分段数 > 0
- [ ] 抽查 3 个分段：车型A 参数段、异议1 话术段、匹配规则表段，内容完整且不跨主题
- [ ] 元数据字段已建（第 4 节）
- [ ] 检索设置已按第 5 节配置

## 3. 分段（Chunk）设置

### 3.1 通用分段 vs 父子分段

| 对比项 | 通用分段（General） | 父子分段（Parent-Child） |
|---|---|---|
| 原理 | 按分隔符 + 最大长度把文档切成同质分段 | 父块保留大段上下文，子块用于向量召回，命中后返回父块 |
| 适合场景 | 内容结构清晰、段落独立的 FAQ/话术/参数库 | 长文档、需要大段上下文才能理解的说明文 |
| 召回粒度 | 中 | 子块细、上下文更完整 |
| 风险 | 段落超长时被硬切，可能丢表头 | 配置更复杂，父子块比例不当会返回重复内容 |
| 本轮选择 | **使用**（4 份文档已按小节控制长度） | 暂不使用，作为后续优化 |

### 3.2 本轮推荐：通用分段参数

| 参数 | 取值 | 说明 |
|---|---|---|
| 分段标识符 | `\n\n`（空行） | 4 份文档均以空行分隔小节，`\n\n` 能优先按小节切 |
| 最大分段长度 | 500 tokens | 约 350 个中文字；文档小节约 150–400 字，基本可整段落入 |
| 分段重叠长度 | 50 tokens | 防止跨段语义断裂 |
| 替换连续空格/换行符 | 开启 | 清理 Markdown 转换残留 |
| 删除 URL 和邮箱地址 | 关闭 | 文档内无 URL/邮箱，开启反而可能误删 |

> 为什么是 500/50：本批文档按「一节一主题」重写，标题层级为 `#`/`##`/`###`，每节自解释，多数小节约 150–400 字。500 tokens 上限可保证「一个异议」「一个车型参数块」「一条匹配规则表」整段落入同一个 chunk，不会被硬切；50 tokens 重叠用于兜住少数超长小节被切开的情况。若预览显示分段过碎（1–2 行一块），可把最大长度调到 300–400 tokens；若表格被切断，先拆表再考虑父子分段。

### 3.3 父子分段（后续优化可选）

若首轮召回出现「上下文缺失、答非所问」，可改用父子分段重做一版对照：

| 参数 | 建议 |
|---|---|
| 父段 | 按段落（`paragraph`）或整篇（`full-doc`）；长度上限 1000–1500 tokens |
| 子段 | 分隔符 `\n\n`，最大 300–500 tokens，重叠 50 |
| 文档形态 | `hierarchical_model`（API 字段，📝 待实测） |

### 3.4 分段预览与调参

提交前在预览中检查三类样本：

1. **车型参数段**：`车型A 指导价 / 续航 / 配置` 是否在同一 chunk，或至少同一车型的字段不被拆到互不相邻的位置。
2. **异议话术段**：一条异议的「客户原话 + 应对 + 话术 + 边界」应在同一 chunk（文档已用 `###` 分条）。
3. **匹配规则表**：表头与数据行应在同一 chunk；若表格被切断，考虑把表格改为「一行一条、行内含车型名」的列表（本轮文档已采用带表头的短表）。

若预览发现大量 1–2 行的碎块，说明 `\n\n` 命中过密：可把最大长度调大或改用「段落」模式；若大量分段跨车型，说明最大长度过大，调小到 300–400 tokens。

## 4. 元数据（Metadata）

### 4.1 字段定义

| 字段名 | 类型 | 取值 | 用途 |
|---|---|---|---|
| `category` | 字符串（枚举） | `车型库` / `话术库` / `流程服务` / `画像规则` | 检索时按类别过滤；对应用户规划的知识库分册 |
| `source` | 字符串 | 文件名，如 `01_门店车型库.md` | 溯源与替换真实数据时定位 |
| `version` | 字符串 | `v1.0-demo` | 版本管理；替换真实资料后升级 |
| `is_demo` | 字符串 | `是` / `否` | 标识示例数据，防止误用于对客场景 |

### 4.2 UI 配置步骤

1. 知识库详情 →「设置」→「元数据」（Metadata）→ 添加字段，按上表建 4 个字段。
2. 回到「文档」列表，逐份文档打开「编辑元数据」，按文件填 `category` 等值：
   - `01_门店车型库.md` → `车型库`
   - `02_销售标准话术库.md` → `话术库`
   - `03_购车流程与服务说明.md` → `流程服务`
   - `04_客户画像匹配规则.md` → `画像规则`
3. 保存后在命中测试里可切换「按元数据过滤」做验证（例如只查 `category = 车型库`）。

### 4.3 与 V1 元数据的关系

V1 原型有 19 个治理字段（品牌/车系/年款/区域/门店/版本/审核状态/保密级别等）。Dify 的元数据类型有限（字符串/数字/时间），首轮只保留检索真正用得到的 4 个。后续如需完整治理，可在应用层维护映射表，或把治理字段写进文件头注释后由 API 批量写入。

## 5. 检索设置与命中测试

### 5.1 检索设置

知识库详情 →「设置」→「检索设置」（部分版本在「命中测试」右侧的设置图标里）：

| 参数 | 首轮取值 | 说明 |
|---|---|---|
| 检索方式 | 向量检索（Vector Search） | 与 bge-m3 对应；混合检索作为对照实验 |
| Rerank 模型 | 不启用 | 首轮不加变量 |
| Top K | 3 | 规划要求 |
| Score 阈值 | 开启，0.7 | 规划要求；bge-m3 实际分布见 5.4 |

### 5.2 命中测试入口与操作

1. 知识库详情页右上角点「命中测试」（Retrieval Test）。
2. 确认检索配置（Top K = 3、阈值 0.7、向量检索）与下方一致。
3. 输入 query → 查看返回的 chunk、来源文档、相似度 score、元数据。
4. 可切换元数据过滤条件，验证分类召回是否准确。
5. 若结果为空：先关闭阈值重试，判断是「没有相关内容」还是「阈值过滤掉了」。

### 5.3 执行 20 条召回测试

1. 打开 `docs/dify/guide/recall_tests.md`，按 T01–T20 逐条在命中测试中执行。
2. 每条记录 Top 1–3 的文档/分段/score 与判定（命中/部分/未命中）。
3. 结果回填到 recall_tests.md 第六节表格；同时把原始响应另存为 `docs/dify/guide/recall_results.json`（执行时由 API 自动导出，见 8.8）。

### 5.4 阈值校准观察（重要）

bge-m3 的 cosine 相似度对中文短 query 往往整体偏低（相关内容常见 0.5–0.7）。规划要求阈值 0.7，但 0.7 可能过滤掉部分正确结果。执行时：

1. 先按 0.7 跑完 20 条，记录空召回条数与平均 Top1 score。
2. 对空召回用例临时关阈值 / 调 0.5 重跑，判断是语义真的不相关，还是阈值过严。
3. 若 0.7 下相关结果被过滤超过 3 条，向 Lead 反馈并提出校准建议（0.5–0.6，或改混合检索），**不擅自改线上配置**。

### 5.5 结果导出

- UI 方式：命中测试结果手动回填表格；截图存档。
- API 方式：用第 8.7 节脚本批量跑 20 条，输出 `recall_results.json` + Markdown 摘要表（推荐，可复现）。

## 6. 应用侧接入（后续，不属本轮）

后续在 Dify 中创建 Agent / Chatflow 时：

1. 添加「知识检索」（Knowledge Retrieval）节点，选择「汽车销售知识库」。
2. 节点参数与命中测试保持一致：Top K = 3、Score 阈值 0.7、向量检索。
3. 开启「引用与归属」（Citation and Attribution），让回答带出处。
4. 系统提示词中约束：只依据检索结果回答；无命中则兜底说「我帮您转顾问确认」；报价/库存/交付不承诺具体数字。

## 7. 常见问题（FAQ）

1. **创建知识库时嵌入模型下拉为空 / 没有 bge-m3**
   模型供应商未配置或未启用 Text Embedding 模型。到「设置 → 模型供应商」检查；插件类供应商确认 `docker-plugin_daemon-1` 运行正常；模型类型必须是 Text Embedding 而不是 LLM。
2. **索引一直「排队中 / 索引中」**
   检查 `docker-worker-1` 日志与 `docker-api-1` 健康状态；确认模型服务可达（容器内访问宿主机的地址不要写 localhost）。
3. **索引失败**
   看文档错误详情/容器日志；常见原因：文件编码非 UTF-8、文件为空、嵌入服务调用失败（超时/限流/维度不匹配）。
4. **分段数异常少或异常多**
   检查最大分段长度与分隔符；过少说明分隔符没命中，过多说明按行切碎。用分段预览确认后再重建。
5. **表格内容被切断、表头丢失**
   表格超过单段上限时会被硬切。把大表拆成多张小表（带表头），或改「一行一条、行内自解释」的列表；父子分段也可缓解。
6. **命中测试结果为空**
   先关闭 score 阈值重试；若关闭后有结果，说明阈值过严（见 5.4）；若仍为空，检查索引是否完成、问题是否超出知识库范围。
7. **结果偏题 / 召回其他车型**
   加元数据过滤；考虑启用 Rerank（bge-reranker）或混合检索；检查 chunk 是否把多车型参数混在一个段里。
8. **嵌入模型能改吗**
   知识库创建后嵌入模型通常不可更换；需新建知识库重新索引，删除旧库前确认无应用引用。
9. **删除知识库/重建**
   删除 dataset 会级联删除其文档与分段；仅在本机演示库上操作，执行前先 `GET /console/api/datasets` 确认 id，并在 Lead 同意后执行。
10. **API 上传的文档没被处理**
   若知识库是用「知识流水线」创建的，API 上传的文档可能不经过流水线。请用传统知识库方式创建，或改走流水线导入。
11. **`/console/api/datasets/{id}/retrieve` 返回 404**
    本机 1.19.0 的命中测试接口是 `POST /console/api/datasets/{id}/hit-testing`；`/retrieve` 是 Service API 的路径（`/v1/datasets/{id}/retrieve`），两者不要混用。
12. **console token 很快失效**
    access token 有有效期；401 时用 refresh token 换新，或重新登录。不要把 token 写入 git 或日志。

## 8. API 自动化章节（拿到 console access token 后执行）

> 本节所有路径均基于 `http://localhost/console/api`。✅ 标记的路径已在本机实例用 OPTIONS 只读探测确认存在（返回 Allow 头而非 404）；请求体字段为草案（📝），首次执行时以实际响应校准并回填本手册。

### 8.1 认证与通用约定

- Base URL：`http://localhost/console/api`
- 登录：`POST /console/api/login` ✅
  ```json
  {
    "email": "<管理员邮箱>",
    "password": "<管理员密码>",
    "language": "zh-Hans",
    "remember_me": true
  }
  ```
  响应中取 `access_token`（通常在 `data.access_token`，📝 以实际响应为准；若账号开启两步验证，按响应提示补充验证步骤）。
- 请求头：`Authorization: Bearer <access_token>`；JSON 请求加 `Content-Type: application/json`。
- 刷新：`POST /console/api/refresh-token` ✅，body 带 `refresh_token`；失败则重新登录。
- 安全：token 只放环境变量/本地临时文件，不写入仓库、不打印到日志。
- 写操作前先 `GET` 确认现状（幂等）：已有同名 dataset 时复用，避免重复建库。

### 8.2 已实测路由清单（本机 1.19.0）

| 用途 | 方法 | 路径 | 状态 |
|---|---|---|---|
| 登录 | POST | `/console/api/login` | ✅ |
| 刷新 token | POST | `/console/api/refresh-token` | ✅ |
| 查询可用嵌入模型 | GET | `/console/api/workspaces/current/models/model-types/text-embedding` | ✅ |
| 知识库列表 / 创建 | GET / POST | `/console/api/datasets` | ✅ |
| 知识库详情 / 更新 / 删除 | GET / PATCH / DELETE | `/console/api/datasets/{dataset_id}` | ✅ |
| 上传文件创建文档 | POST | `/console/api/datasets/{dataset_id}/documents` | ✅ |
| 文档列表 | GET | `/console/api/datasets/{dataset_id}/documents?page=1&limit=20` | ✅ |
| 文档详情 / 删除 | GET / DELETE | `/console/api/datasets/{dataset_id}/documents/{document_id}` | ✅ |
| 文档索引状态 | GET | `/console/api/datasets/{dataset_id}/documents/{document_id}/indexing-status` | ✅ |
| 分段列表 | GET | `/console/api/datasets/{dataset_id}/documents/{document_id}/segments` | ✅ |
| 命中测试 | POST | `/console/api/datasets/{dataset_id}/hit-testing` | ✅ |
| 查询记录 | GET | `/console/api/datasets/{dataset_id}/queries` | ✅ |
| 元数据字段 | GET / POST | `/console/api/datasets/{dataset_id}/metadata` | ✅ |
| 文档元数据赋值 | PUT | `/console/api/datasets/{dataset_id}/documents/{document_id}/metadata` | ✅ |
| 知识库 API Key | GET / POST | `/console/api/datasets/{dataset_id}/api-keys` | ✅ |
| 删除 API Key | DELETE | `/console/api/datasets/{dataset_id}/api-keys/{api_key_id}` | ✅ |
| Service API 检索（备选） | POST | `/v1/datasets/{dataset_id}/retrieve` | ✅（需 dataset API Key） |

> 注意：本机没有 `/console/api/datasets/{id}/documents/create-by-file` 与 `create-by-text`（探测 404），上传统一走 `POST /datasets/{id}/documents` 的 multipart 表单。

### 8.3 Step 1 预检

1. 登录拿 token。
2. `GET /console/api/workspaces/current/models/model-types/text-embedding`，确认 `bge-m3` 存在，记录 `provider` 与 `model` 字段值。
3. `GET /console/api/datasets?page=1&limit=50`，记录已有知识库；若已存在「汽车销售知识库」则复用其 id 并跳到 8.6，避免重复上传。

### 8.4 Step 2 创建 dataset（知识库）

`POST /console/api/datasets`

```json
{
  "name": "汽车销售知识库",
  "description": "汽车销售智能体 V1 知识库（示例数据）：车型库/话术库/流程服务/画像规则",
  "indexing_technique": "high_quality",
  "embedding_model": "bge-m3",
  "embedding_model_provider": "<provider，例如 ollama>",
  "permission": "all_team_members",
  "provider": "vendor",
  "retrieval_model": {
    "search_method": "semantic_search",
    "reranking_enable": false,
    "reranking_mode": null,
    "reranking_model": {
      "reranking_provider_name": "",
      "reranking_model_name": ""
    },
    "weights": null,
    "top_k": 3,
    "score_threshold_enabled": true,
    "score_threshold": 0.7
  }
}
```

- 响应中取 `id` 存为 `DATASET_ID`；同时记录 `embedding_model_provider` 返回值，校验是否与预期一致。
- 若返回 400/422，优先检查 `embedding_model` 与 `embedding_model_provider` 是否与预检结果完全一致。

### 8.5 Step 3 上传 4 个文件

`POST /console/api/datasets/{DATASET_ID}/documents`

- `Content-Type: multipart/form-data`
- 表单字段（📝 首次执行需验证字段名；本机路由已确认）：

| 字段 | 类型 | 内容 |
|---|---|---|
| `file` | 文件 | `docs/dify/knowledge/01_门店车型库.md` 等 |
| `data` | JSON 字符串 | 处理规则，见下 |

`data` JSON 草案（通用分段）：

```json
{
  "indexing_technique": "high_quality",
  "doc_form": "text_model",
  "doc_language": "Chinese",
  "process_rule": {
    "mode": "custom",
    "rules": {
      "pre_processing_rules": [
        { "id": "remove_extra_spaces", "enabled": true },
        { "id": "remove_urls_emails", "enabled": false }
      ],
      "segmentation": {
        "separator": "\n\n",
        "max_tokens": 500,
        "chunk_overlap": 50
      }
    }
  },
  "retrieval_model": {
    "search_method": "semantic_search",
    "reranking_enable": false,
    "top_k": 3,
    "score_threshold_enabled": true,
    "score_threshold": 0.7
  }
}
```

- 逐份上传，**串行或并发 ≤ 2**，避免 worker 过载；每份记录返回的 `document.id` 与 `batch`。
- 若返回 422：检查 `data` 是否为合法 JSON 字符串、`mode`/`doc_form` 取值是否被实例支持（父子分段对应 `hierarchical_model` + `mode: "hierarchical"`，📝 待实测）。
- 备选（Service API，需先在 UI 创建知识库 API Key）：`POST /v1/datasets/{DATASET_ID}/document/create-by-file`（注意是单数 `document`），同样用 multipart `file` + `data`，Authorization 用 `Bearer dataset-xxx`。

### 8.6 Step 4 等待索引完成

轮询：`GET /console/api/datasets/{DATASET_ID}/documents/{DOCUMENT_ID}/indexing-status`

```json
{
  "data": [
    {
      "id": "<document_id>",
      "indexing_status": "indexing",
      "total_segments": 42,
      "completed_segments": 18,
      "error": null
    }
  ]
}
```

- `indexing_status` 常见取值：`waiting` / `parsing` / `cleaning` / `splitting` / `indexing` / `completed` / `error`。
- 轮询间隔 5 秒，单份超时 300 秒；`completed` 记录分段数，`error` 立即停止并打印 `error` 字段。
- 也可用文档列表接口批量看状态：`GET /console/api/datasets/{DATASET_ID}/documents?page=1&limit=20`。

### 8.7 Step 5 命中测试（20 条）

`POST /console/api/datasets/{DATASET_ID}/hit-testing`

```json
{
  "query": "车型A 续航多少？快充要多久？",
  "retrieval_model": {
    "search_method": "semantic_search",
    "reranking_enable": false,
    "reranking_mode": null,
    "reranking_model": {
      "reranking_provider_name": "",
      "reranking_model_name": ""
    },
    "weights": null,
    "top_k": 3,
    "score_threshold_enabled": true,
    "score_threshold": 0.7
  }
}
```

- 循环执行 `recall_tests.md` 的 T01–T20；每条保存原始响应（含 `records[].score`、`records[].segment.document.name`、`records[].segment.content`）。
- 若需做阈值对照：同一 query 用 `score_threshold_enabled: false` 再跑一次，记录原始 Top1 score（对应 recall_tests.md 第 5 节）。
- 备选 Service API：`POST /v1/datasets/{DATASET_ID}/retrieve`，body 同上，Authorization 用 dataset API Key。

### 8.8 Step 6 导出与判定

1. 把 20 条原始结果写到 `docs/dify/guide/recall_results.json`（字段：`case_id, query, results[{doc, section, score, content}]`）。
2. 生成 `docs/dify/guide/recall_results.md`：每行一条用例的 Top1–3、score、判定（命中/部分/未命中）、备注；末尾给汇总（命中数、平均 Top1 score、阈值过滤数）。
3. 回填 `docs/dify/guide/recall_tests.md` 第六节表格。
4. 对照通过标准：命中 ≥ 18/20；报价库存类与异议类不得未命中；关键数字 100% 准确。
5. 把「阈值校准观察」结论与失败用例一并汇报 Lead。

### 8.9 Step 7 回滚/清理（仅在需要重建时）

- 删除单份文档：`DELETE /console/api/datasets/{DATASET_ID}/documents/{DOCUMENT_ID}` ✅
- 删除整个知识库：`DELETE /console/api/datasets/{DATASET_ID}` ✅（级联文档与分段，不可恢复）
- 执行前确认：无应用引用该知识库；已导出 recall_results；获得 Lead 同意。

### 8.10 PowerShell 脚本草案

> 仅在本机 `pwsh` 7+ 执行；需要 `-Form` 支持（Windows PowerShell 5.1 不支持，可改用 `curl.exe`）。密码/token 用环境变量传入，不要硬编码。

```powershell
$Base = "http://localhost/console/api"
$Email = $env:DIFY_EMAIL
$Password = $env:DIFY_PASSWORD

# 1) 登录
$login = Invoke-RestMethod -Method Post -Uri "$Base/login" -ContentType "application/json" -Body (@{
  email = $Email; password = $Password; language = "zh-Hans"; remember_me = $true
} | ConvertTo-Json)
$Token = $login.data.access_token   # 若响应结构不同，按实际调整
$Headers = @{ Authorization = "Bearer $Token" }

# 2) 预检：嵌入模型
Invoke-RestMethod -Uri "$Base/workspaces/current/models/model-types/text-embedding" -Headers $Headers | ConvertTo-Json -Depth 6

# 3) 创建知识库（先查重）
$datasets = Invoke-RestMethod -Uri "$Base/datasets?page=1&limit=50" -Headers $Headers
$existing = $datasets.data | Where-Object { $_.name -eq "汽车销售知识库" } | Select-Object -First 1
$body = @{
  name = "汽车销售知识库"
  description = "汽车销售智能体 V1 知识库（示例数据）"
  indexing_technique = "high_quality"
  embedding_model = "bge-m3"
  embedding_model_provider = "<provider>"
  permission = "all_team_members"
  provider = "vendor"
  retrieval_model = @{
    search_method = "semantic_search"; reranking_enable = $false; reranking_mode = $null
    reranking_model = @{ reranking_provider_name = ""; reranking_model_name = "" }
    weights = $null; top_k = 3; score_threshold_enabled = $true; score_threshold = 0.7
  }
}
if ($existing) { $DatasetId = $existing.id } else {
  $ds = Invoke-RestMethod -Method Post -Uri "$Base/datasets" -Headers $Headers -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 8)
  $DatasetId = $ds.id
}

# 4) 上传 4 个文件（data 为 JSON 字符串）
$dataJson = @{
  indexing_technique = "high_quality"; doc_form = "text_model"; doc_language = "Chinese"
  process_rule = @{
    mode = "custom"
    rules = @{
      pre_processing_rules = @(
        @{ id = "remove_extra_spaces"; enabled = $true },
        @{ id = "remove_urls_emails"; enabled = $false }
      )
      segmentation = @{ separator = "`n`n"; max_tokens = 500; chunk_overlap = 50 }
    }
  }
} | ConvertTo-Json -Depth 8 -Compress

$docIds = @()
foreach ($f in Get-ChildItem "docs/dify/knowledge/*.md") {
  $resp = Invoke-RestMethod -Method Post -Uri "$Base/datasets/$DatasetId/documents" -Headers $Headers `
    -Form @{ file = Get-Item $f.FullName; data = $dataJson }
  $docIds += $resp.document.id
  Write-Host "uploaded $($f.Name) -> $($resp.document.id)"
}

# 5) 等待索引
foreach ($docId in $docIds) {
  do {
    Start-Sleep -Seconds 5
    $st = Invoke-RestMethod -Uri "$Base/datasets/$DatasetId/documents/$docId/indexing-status" -Headers $Headers
    $item = $st.data[0]
    Write-Host "$docId => $($item.indexing_status) $($item.completed_segments)/$($item.total_segments)"
  } while ($item.indexing_status -notin @("completed", "error"))
  if ($item.indexing_status -eq "error") { throw "index failed: $($item.error)" }
}

# 6) 命中测试：读取 query 列表，逐条保存
$queries = @("车型A 续航多少？快充要多久？", "客户说太贵了，应该怎么回复？")  # 实际从 recall_tests.md 解析 20 条
$results = @()
foreach ($q in $queries) {
  $payload = @{ query = $q; retrieval_model = @{
    search_method = "semantic_search"; reranking_enable = $false; reranking_mode = $null
    reranking_model = @{ reranking_provider_name = ""; reranking_model_name = "" }
    weights = $null; top_k = 3; score_threshold_enabled = $true; score_threshold = 0.7
  }} | ConvertTo-Json -Depth 8
  $r = Invoke-RestMethod -Method Post -Uri "$Base/datasets/$DatasetId/hit-testing" -Headers $Headers -ContentType "application/json" -Body $payload
  $results += [pscustomobject]@{ query = $q; records = $r.records }
}
$results | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 "docs/dify/guide/recall_results.json"
```

> 以上脚本字段为草案：首次运行时先用 1 个 query/1 个文件验证字段名与响应结构，再批量执行；把校准后的差异写回本节。

### 8.11 错误码与排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 401 | token 过期/未带 Authorization | 重新登录或 refresh-token；确认 Bearer 前缀 |
| 403 | 账号无权限/工作区角色不足 | 用管理员账号或申请 workspace 权限 |
| 404 | 路径/版本差异、dataset/document UUID 错误 | 对照 8.2 路由清单；确认 UUID 来自列表接口 |
| 400/422 | 请求体字段缺失或取值不合法 | 检查 `embedding_model*`、`process_rule`、`doc_form`；先小样本试跑 |
| 500 | Dify 服务端异常（模型服务不可达/向量库） | 看 `docker-api-1`、`docker-worker-1` 日志；重试并降并发 |
| 索引卡住 | 模型服务超时、worker 忙 | 降低并发、检查模型服务连通性；必要时重启 worker |

### 8.12 待确认（阻塞项）

1. **console access token / 管理员账号**：凭据未交付，API 自动化无法开始（当前仅完成只读路由探测）。
2. **bge-m3 配置**：是否已在「模型供应商」配置；provider 名称、模型名（`bge-m3` 是否带 tag）、维度。
3. **知识库创建方式**：是否为「知识流水线」实例；本轮建议传统知识库 + 通用分段。
4. **可见范围与权限**：`only_me` 还是 `all_team_members`。
5. **阈值可调空间**：0.7 是硬指标还是可校准（见 5.4 与 recall_tests.md 第 5 节）。
6. **Rerank**：是否允许启用 bge-reranker（会影响召回结果，首轮建议关闭）。
7. **重跑/重建授权**：删除/重建 dataset 需 Lead 明确同意。

## 9. 验收清单

- [ ] 知识库已创建，嵌入模型 = bge-m3，索引方式 = 高质量
- [ ] 4 份文档全部「已索引」，0 失败，分段数合理（预计约 25–50 段）
- [ ] 元数据 4 字段已建并逐文档赋值
- [ ] 检索设置：Top K = 3、阈值 0.7、向量检索
- [ ] 20 条召回测试执行完毕，命中 ≥ 18，关键数字 100% 准确
- [ ] `recall_results.json` 与 `recall_results.md` 已归档，`recall_tests.md` 第六节已回填
- [ ] 阈值校准结论已反馈 Lead
- [ ] 不把 token/密码写入仓库
