# 端到端测试用例（5 条主用例 + 5 条边界用例）

> 被测对象：`汽车销售接待工作流`（节点规格见 [`../prompts/nodes.md`](../prompts/nodes.md)）。
> 依赖：[`api_stub.py`](../../../tools/dify/api_stub.py) 已启动、知识库已导入 4 份文档、工作流已发布/可测试运行。
> 判定原则：**走对分支 → 关键要素齐全 → 不编造 → 话术合规**，四者全部满足才算通过。

---

## 0. 前置检查

| # | 检查 | 命令/操作 | 通过标准 |
| --- | --- | --- | --- |
| 1 | stub 在跑 | `curl.exe http://127.0.0.1:8000/health` | `{"status":"ok"}` |
| 2 | 容器可达 stub | `docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' http://host.docker.internal:8000/health"` | `200` |
| 3 | SSRF 是否放行 | `docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' -x http://ssrf_proxy:3128 http://host.docker.internal:8000/health"` | `200` 才可测用例 2/3；`403` 见 backend_stub.md §5 |
| 4 | 知识库可用 | 控制台「知识库 → 汽车销售知识库 → 命中测试」搜「家用 15 万 SUV」 | 能召回含「车型A」的段落（dataset_id 见 nodes.md §0.3） |
| 5 | 模型可用 | 工作流任一 LLM 节点「测试运行」 | 不报 provider/model 错误 |

---

## 1. 怎么跑

### 方式 A：控制台「测试运行」（推荐先跑）

画布右上「测试运行」→ 输入 `user_query` → 运行 → 在结果面板看 `response`，并点开「运行历史/追踪」确认实际经过的节点（判断分支是否正确）。

### 方式 B：v1 API（发布后）

```powershell
$headers = @{ Authorization = "Bearer app-xxxxxxxx" }   # API 密钥：应用「访问 API」页生成
$body = @{
  inputs        = @{ user_query = "我家用，预算15万，有固定车位能装充电桩，推荐个SUV" }
  response_mode = "blocking"
  user          = "e2e-test-01"
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost/v1/workflows/run" -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

返回里关注：`data.outputs.response`（最终话术）、`data.status`（`succeeded`/`failed`）、`data.error`（失败原因）。

### 方式 C：控制台 draft 运行（未发布时，需 console token）

```text
POST http://localhost/console/api/apps/{app_id}/workflows/draft/run
Authorization: Bearer {console_access_token}
Body: {"inputs":{"user_query":"..."},"files":[]}
```

### 记录表（每次回归都填）

| 用例 | 实际分支（看追踪） | response 摘要 | HTTP/节点异常 | 结论 |
| --- | --- | --- | --- | --- |
| E2E-1 | | | | |
| … | | | | |

---

## 2. 主用例（5 条）

### E2E-1 车型咨询：家用 15 万有充电桩 → 推荐 SUV

- **输入**：`我家用，预算15万左右，有固定车位能装充电桩，推荐个SUV`
- **期望路径**：`start → intent_classifier(1) → profile_extract → profile_parse → profile_check(true) → kb_query_build → kb_models → recommend → merge_reply → end`
- **预期关键输出**：
  - 推荐 **车型A**（紧凑型家用 SUV、纯电、CLTC 550km、轴距 2750mm），可顺带提车型C 作为预算备选，但不能主推车型B；
  - 说明「为什么适合我」（家用/通勤/有充电桩/预算匹配），并按 FABE 至少覆盖 F/B 两层；
  - 结尾有试驾邀约或询问方便时间；
  - 不编造知识库外的参数（如「续航 700km」「空气悬架」安在车型A 上）。
- **判定标准**：
  - [ ] `response` 包含「车型A」
  - [ ] 包含 `550`（续航）或 `2750`（轴距）等知识库真实参数之一
  - [ ] 包含 `试驾` 或 `到店` 或具体时间问句（如 `周六`/`周日下午`）
  - [ ] 不出现「车型A 空气悬架」「续航 600 公里以上」等虚构表述
  - [ ] 运行状态 `succeeded`，`profile_parse.is_complete=true`
- **失败排查**：分类到了 2/3 类 → 检查 N02 instruction；`is_complete=false` → 检查 N03 抽取与 N04 判定；检索为空 → 知识库未索引/阈值过高；断言参数错误 → 检查知识库文档是否导入完整。

### E2E-2 报价库存：落地多少钱、有没有现车

- **输入**：`车型A落地多少钱？现在有没有现车？`
- **期望路径**：`intent_classifier(2) → quote_extract(brand/model) → inventory_api(GET 200) → inventory_ok(true) → quote_reply → merge_reply → end`
- **预期关键输出**：
  - 说明库存状态：**有现车**（可当天试驾）；
  - 参考落地价约 **17.2 万**（`reference_price`），并说明由车价/保险/上牌等构成；
  - 至少一条优惠/金融信息（现金优惠、置换补贴、24 期 0 息之一）；
  - 明确「最终价格以门店销售顾问核算为准」；
  - 不承诺具体成交价，不编造接口没有的优惠。
- **判定标准**：
  - [ ] `response` 包含 `现车`
  - [ ] 包含 `17.2`（允许「17万2」「约 17.2 万」）
  - [ ] 包含 `以门店` / `以销售顾问` / `最终以` 之一（价格免责声明）
  - [ ] 追踪中 `inventory_api.status_code == 200`
  - [ ] 不出现「保证最低价」「今天定就这个价」等承诺
- **失败排查**：SSRF 403 → backend_stub.md §5；车型抽空（`model` 为空）导致 404 → 检查 N10 description；接口 200 但话术漏价格 → 检查 N13 Prompt 是否强制引用字段。

### E2E-3 预约试驾：要素齐全 → 提工单

- **输入**：`我想预约这周六上午试驾车型A，我叫张三，手机号13800138000`
- **期望路径**：`intent_classifier(3) → appt_extract(name/phone/model/time 齐全) → appt_complete(true) → appt_api(POST 200) → appt_ok(true) → appt_confirm → merge_reply → end`
- **预期关键输出**：
  - 告知预约已提交成功，**工单号形如 `APPT-20261117-0001`**；
  - 复述预约时间（本周六上午）与车型（车型A）；
  - 提醒到店带身份证/驾驶证；
  - 不承诺具体试驾车位/销售人员，不重复建单。
- **判定标准**：
  - [ ] `response` 包含 `APPT-` 且工单号匹配 `^APPT-\d{8}-\d{4}$`
  - [ ] 包含 `周六` 或 `上午`（时间被复述）
  - [ ] 包含 `身份证` 或 `驾驶证`（到店提醒）
  - [ ] 追踪中 `appt_api` 只执行 1 次（无重试导致重复工单）
  - [ ] 运行状态 `succeeded`
- **失败排查**：`appt_extract` 漏字段 → 检查 N15 参数 description；POST 405/400 → 检查 Body 类型是否为 json、字段名是否一致；重复工单 → 关闭节点重试。

### E2E-4 价格异议：这个车太贵了

- **输入**：`这个车太贵了，能不能再便宜点？`
- **期望路径**：`intent_classifier(4) → kb_scripts → objection_reply → merge_reply → end`
- **预期关键输出**：
  - 先共情（「理解，买车肯定要算清楚」类），不硬顶；
  - 价值拆解（配置/续航/质保/用车成本/服务权益）或给出置换补贴、24 期 0 息等解法；
  - 不承诺降价、不贬低竞品、不说「网上都是假的」；
  - 给出下一步（到店核算/试驾）并询问时间；
  - 可引用话术库内容，但不整段照抄长文。
- **判定标准**：
  - [ ] `response` 包含共情词（`理解`/`明白`/`确实` 之一）
  - [ ] 包含 `置换` 或 `金融` 或 `0 息` 或 `利息` 之一
  - [ ] 不出现「直接给您降」「保证全网最低」「便宜多少都行」等承诺
  - [ ] 结尾含下一步动作（`到店`/`试驾`/`算` 之一）
- **失败排查**：分类到了 1 类（被当成车型咨询）→ 检查 N02 类别 4 的说明；`kb_scripts` 空 → 检查话术文档是否入库、阈值 0.6；回答像背话术 → 调 N23 temperature/规则 1。

### E2E-5 闲聊兜底：今天吃什么

- **输入**：`今天中午吃什么好`
- **期望路径**：`intent_classifier(5) → smalltalk_reply → merge_reply → end`（不经过任何 LLM 生成分支）
- **预期关键输出**：固定兜底话术（「我是门店的购车助手…帮您推荐车型/查现车和落地价/约试驾」，引导说预算和用途）。
- **判定标准**：
  - [ ] `response` 与 N24 模板一致（允许尾部空白差异）
  - [ ] 不出现任何车型名、价格数字、库存状态
  - [ ] 运行状态 `succeeded`，追踪中无 LLM 话术节点执行
- **失败排查**：被分到 1 类 → 检查类别 5 描述与优先级；模板节点变量映射报错 → 检查 N24 变量是否为空数组/是否误加变量。

---

## 3. 边界用例（5 条）

### B-1 画像缺失 → 追问（不推荐）

- **输入**：`帮我推荐个车`
- **期望路径**：`intent_classifier(1) → profile_extract(多为 null) → profile_parse(is_complete=false) → profile_check(false) → profile_followup → merge_reply → end`
- **判定标准**：
  - [ ] `is_complete=false`，`missing_text` 至少含 2 项（预算/用途/充电条件）
  - [ ] `response` 追问覆盖「预算」+「家用还是通勤/用途」+「充电桩/车位」中的至少 2 项
  - [ ] 不出现具体车型推荐、不出现价格数字
  - [ ] 长度 ≤ 200 字，语气礼貌
- **常见错误**：LLM 把预算默认成 15 万 → 检查 N03 规则 1/2；追问一次只问一个 → 检查 N06 规则 1/2。

### B-2 知识库无命中 → 不编造、转顾问

- **输入**：`我预算100万，家用，有充电桩，想看看你们在售的氢能源重卡`
- **期望路径**：`… → profile_check(true) → kb_models(空结果) → recommend(上下文为空) → merge_reply → end`
- **判定标准**：
  - [ ] `kb_models.result` 为空数组（追踪可见）
  - [ ] `response` 说明该车型资料暂无/需要销售顾问确认（含 `顾问`/`确认`/`暂无` 之一）
  - [ ] 不出现虚构车型（如「氢能源重卡 车型D」）或虚构参数
  - [ ] 结尾有邀约/留资（`到店`/`试驾`/`联系` 之一）
- **常见错误**：模型用常识补全「氢能源重卡续航 800km」→ 检查 N09 规则 1/4 与 temperature。

### B-3 库存接口超时 → 兜底话术

- **输入**：`车型B落地多少钱？有现车吗？`
- **制造故障（任选其一）**：
  1. 临时把 `inventory_api` 的 URL 改为 `http://host.docker.internal:8000/api/inventory?__delay_ms=30000`，读取超时设 10s，运行后改回；
  2. 直接停掉 stub 进程（连接拒绝）；
  3. SSRF 未放行时天然就是 403（此时节点报错，需要在 HTTP 节点开「异常分支」接到 `quote_fallback`，否则整个工作流失败——这也是为什么建议给 HTTP 节点开异常分支）。
- **期望路径**：`inventory_api` 失败/超时 → `inventory_ok(false)`（或异常分支）→ `quote_fallback → merge_reply → end`
- **判定标准**：
  - [ ] `response` 含 `系统` / `繁忙` / `暂时` 之一 + 致歉
  - [ ] 不出现具体库存（现车/排期）或价格数字
  - [ ] 给出留手机号/到店选项，结尾有推进问题
  - [ ] 若节点直接抛错导致 `status=failed`，判为**未通过**并记录（需补异常分支）
- **常见错误**：节点超时设置成 600s，测试要等 10 分钟 → 按 backend_stub.md §3 把读取超时改 10s。

### B-4 手机号格式非法 → 不谎称预约成功

- **输入**：`预约周六试驾车型A，我叫李四，手机号是12345`
- **期望路径（两种都接受）**：
  - a) `appt_extract` 把 `phone` 留空 → `appt_complete(false)` → `appt_followup`；
  - b) `appt_extract` 抽出 `12345` → `appt_api` 返回 400（`INVALID_ARGUMENT`）→ `appt_ok(false)` → `appt_fallback`。
- **判定标准**：
  - [ ] 最终话术包含 `手机号` 且提示格式/重新提供（含 `11 位`/`格式`/`重新` 之一）
  - [ ] 不出现 `预约成功`/`已受理`/`工单号`，不出现 `APPT-`
  - [ ] 不虚构预约时间点
  - [ ] 追踪中若调用了 `appt_api`，其 `status_code == 400`
- **常见错误**：N15 抽取把 `12345` 当手机号且未触发 400（stub 校验已覆盖）→ 检查 N19 判定是否只看了 `status_code` 200 而 body 是错误 JSON（用 `contains ticket_id` 更稳）。

### B-5 多意图 → 按优先级只走一条

- **输入**：`我预算15万家用，车型A有现车吗？这周六能试驾吗？`
- **期望路径**：按 N02 优先级（预约试驾 > 报价库存 > 车型咨询 > 异议 > 闲聊）应走 **3 预约试驾**；但缺姓名/手机号 → `appt_complete(false)` → `appt_followup`。
- **判定标准**：
  - [ ] 实际分支为 3（追踪可见 `appt_extract` 执行）
  - [ ] `response` 追问姓名 + 手机号（车型/时间已提供则不应重复问）
  - [ ] 不出现价格/库存的具体数字（避免和「报价库存」混淆）
- **备注**：若实际走 2（报价库存），记录为**分类偏差**并调整 N02 instruction（提高「试驾/预约」关键词权重）；走 3 但一次性把 4 项全问一遍也判为轻度问题（可接受但不理想）。

---

## 4. 断言脚本草案（PowerShell，发布后可用）

```powershell
$token = "app-xxxxxxxx"        # 应用 API 密钥
$base  = "http://localhost/v1"
$cases = @(
  @{ id = "E2E-1"; q = "我家用，预算15万左右，有固定车位能装充电桩，推荐个SUV"; must = @("车型A"); anyof = @("550","2750"); forbid = @() },
  @{ id = "E2E-2"; q = "车型A落地多少钱？现在有没有现车？"; must = @("现车"); anyof = @("17.2","17万2"); forbid = @() },
  @{ id = "E2E-3"; q = "我想预约这周六上午试驾车型A，我叫张三，手机号13800138000"; must = @("APPT-"); anyof = @("周六"); forbid = @() },
  @{ id = "E2E-4"; q = "这个车太贵了，能不能再便宜点？"; must = @(); anyof = @("置换","金融","0 息"); forbid = @("保证全网最低") },
  @{ id = "E2E-5"; q = "今天中午吃什么好"; must = @(); anyof = @("购车助手"); forbid = @("车型A","车型B","车型C") }
)
foreach ($c in $cases) {
  $body = @{ inputs = @{ user_query = $c.q }; response_mode = "blocking"; user = "e2e" } | ConvertTo-Json -Depth 5
  $resp = Invoke-RestMethod -Uri "$base/workflows/run" -Method Post -ContentType "application/json" `
            -Headers @{ Authorization = "Bearer $token" } -Body ([Text.Encoding]::UTF8.GetBytes($body))
  $text = $resp.data.outputs.response
  $ok = ($c.must | Where-Object { $text -notmatch [regex]::Escape($_) }).Count -eq 0
  if ($c.anyof.Count -gt 0) { $ok = $ok -and (($c.anyof | Where-Object { $text -match $_ }).Count -gt 0) }
  if ($c.forbid.Count -gt 0) { $ok = $ok -and (($c.forbid | Where-Object { $text -match [regex]::Escape($_) }).Count -eq 0) }
  "{0} status={1} pass={2}`n{3}`n" -f $c.id, $resp.data.status, $ok, $text
}
```

> 注意：PowerShell 里 `$resp.data.outputs.response` 是中文时直接用 `-match` 匹配中文没问题；`Invoke-RestMethod` 对 UTF-8 body 建议显式转字节（上面的写法）。

---

## 5. 失败 → 定位速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| 用例 2/3 节点报 `blocked by SSRF protection` | SSRF 代理拦私网 | backend_stub.md §5 放行 |
| 用例 2/3 报连接失败/超时 | stub 没启动、端口不对、host.docker.internal 不通 | backend_stub.md §6 |
| 分类器总走 1 类 | instruction 关键词不足、temperature 高、模型弱 | 强化 N02 类别说明，temperature 0.1，换 qwen3.8-flash 试 |
| 画像永远 `is_complete=false` | N03 输出不是合法 JSON / N04 正则没匹配 | 看 `profile_extract.text`，必要时 N03 加「只输出 JSON」并在 N04 放宽解析 |
| 推荐出现不存在车型/参数 | 知识库没导入该文档 / N09 规则被忽略 | 重新索引，强化 N09 规则 1/4，降低 temperature |
| 聚合器输出为空 | 分支终点没连到 `merge_reply` 或 `output` 类型不匹配 | 按 nodes.md §2 补边，检查 output_type=string |
| 追问/兜底话术重复问已有信息 | N06/N17 Prompt 没拿到已知字段 | 检查占位符是否选到 `profile_summary`/抽取字段 |
| 预约工单重复 | HTTP POST 开了重试 | 关闭 `appt_api` 的 retry |
| End 输出缺字段 | End 的 outputs 选择器失效 | 重新在结束节点选变量 |

---

## 6. 回归约定

- 每次修改 Prompt、模型、知识库文档后，**10 条用例全跑一遍**，记录表留档。
- 修复一个缺陷后，至少重跑该用例 + 相邻分支 1 条，避免回归。
- SSRF 未放行期间：用例 2/3 以「兜底话术正确」为通过标准（另记环境阻塞项），放行后必须重跑到「返回真实占位数据」才算最终通过。
