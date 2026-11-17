# 后端占位接口（api_stub.py）与 Dify HTTP 节点配置指南

> 目的：在真实库存/报价/预约系统接入前，用零依赖的本地 stub 把工作流跑通。
> 相关文件：[`tools/dify/api_stub.py`](../../../tools/dify/api_stub.py)；数据口径对齐 [`docs/dify/knowledge/01_门店车型库.md`](../knowledge/01_门店车型库.md)、[`03_购车流程与服务说明.md`](../knowledge/03_购车流程与服务说明.md)。

---

## 1. 启动与自检

```powershell
# 在项目根目录 C:\Users\zhou\Desktop\汽车销售智能体 下执行
python tools\dify\api_stub.py
# 或指定端口/地址
python tools\dify\api_stub.py --host 0.0.0.0 --port 8000
```

启动后监听 `0.0.0.0:8000`（必须是 `0.0.0.0` 而不是 `127.0.0.1`，否则 Dify 容器访问不到）。

```powershell
# 宿主机自检
curl.exe http://127.0.0.1:8000/health
curl.exe "http://127.0.0.1:8000/api/inventory?brand=%E6%98%9F%E8%BE%B0&model=%E8%BD%A6%E5%9E%8BA"
```

```powershell
# 容器内自检（验证 Dify 侧网络可达，实测应输出 200）
docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' http://host.docker.internal:8000/health"
```

若 8000 被占用：`netstat -ano | findstr :8000` 找到 PID 后结束，或换 `--port 8010`（Dify 节点 URL 同步改）。
Windows 首次运行可能弹出防火墙提示，允许「专用网络」即可。

---

## 2. 接口契约

所有响应 `application/json; charset=utf-8`，金额单位 **万元**，`ok` 字段表示业务成功。

### 2.1 `GET /api/inventory` —— 库存查询

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `brand` | 否 | 品牌，如 `星辰`（可空，只按车型匹配） |
| `model` | 是 | 车型：`车型A` / `车型B` / `车型C`，也接受别名（`A`、`SUV`、`混动`、`代步车`…） |

响应示例（200）：

```json
{
  "ok": true,
  "model": "车型A",
  "brand": "星辰",
  "category": "紧凑型家用 SUV（纯电）",
  "energy": "纯电",
  "stock_status": "有现车",
  "stock_detail": "门店现车 3 台，可当天看车、当天试驾",
  "reference_price": 17.2,
  "reference_price_unit": "万元",
  "discount": ["现金优惠 5,000 元", "置换补贴最高 8,000 元", "24 期 0 息（首付 30% 起）", "提车礼包（脚垫 + 贴膜）"],
  "delivery_days": 3,
  "delivery_note": "现车付款后约 3–7 个工作日提车；排期车 15–45 天",
  "can_test_drive_today": true,
  "updated_at": "2026-11-17 17:13:59",
  "source": "门店库存系统（占位数据）"
}
```

错误：车型匹配不到返回 **404** `{"ok": false, "code": "MODEL_NOT_FOUND", "error": "未找到车型：..."}`。
三款车口径：车型A `有现车` / 参考落地 17.2 万 / 3 天；车型B `需排期` / 25.84 万 / 30 天；车型C `需预订` / 8.6 万 / 45 天。

### 2.2 `GET /api/price` —— 报价查询

参数同上。响应在库存字段基础上增加：

```json
{
  "ok": true,
  "model": "车型B",
  "brand": "远航",
  "guide_price": 23.98,
  "reference_price": 25.84,
  "price_unit": "万元",
  "price_breakdown": {"vehicle_price": 23.98, "purchase_tax": 1.06, "insurance": 0.75, "plate_fee": 0.05, "other_fees": 0.0},
  "breakdown_total": 25.84,
  "discount": ["现金优惠 10,000 元", "置换补贴最高 12,000 元", "36 期低息（年化约 3.5%）", "免费家充桩安装（30 米内）"],
  "finance_plans": [
    {"name": "全款", "down_payment_ratio": 1.0, "months": 0, "rate": "无", "note": "一次性付清，可享现金优惠"},
    {"name": "24 期 0 息", "down_payment_ratio": 0.3, "months": 24, "rate": "0%", "note": "首付 30% 起，需通过金融审批"},
    {"name": "36 期低息", "down_payment_ratio": 0.3, "months": 36, "rate": "年化约 3.5%", "note": "月供更低，具体以金融机构审批为准"}
  ],
  "disclaimer": "以上为门店参考价与示例优惠，最终成交价与金融方案以销售顾问现场核算及审批结果为准。",
  "source": "门店报价系统（占位数据）"
}
```

### 2.3 `POST /api/appointment` —— 预约试驾工单

请求体（`Content-Type: application/json`）：

```json
{"name": "张三", "phone": "13800138000", "brand": "星辰", "model": "车型A", "time": "2026-11-21 10:00"}
```

| 字段 | 必填 | 校验 |
| --- | --- | --- |
| `name` | 是 | 非空，≤20 字 |
| `phone` | 是 | 11 位大陆手机号 `^1[3-9]\d{9}$` |
| `model` | 是 | 必须匹配三款在售车型之一 |
| `time` | 是 | 非空，≤64 字，可以是「2026-11-21 10:00」或「本周六上午」等自然语言 |
| `brand` | 否 | 品牌 |

成功（200）：

```json
{
  "ok": true,
  "ticket_id": "APPT-20261117-0001",
  "status": "已受理",
  "message": "预约已提交成功，门店销售顾问将在 30 分钟内与您电话确认。",
  "appointment": {"name": "张三", "phone": "138****8000", "brand": "星辰", "model": "车型A", "time": "2026-11-21 10:00", "store": "示例门店（占位）"},
  "stock_hint": "有现车",
  "created_at": "2026-11-17 17:13:59"
}
```

校验失败（400）：`{"ok": false, "code": "INVALID_ARGUMENT", "errors": [{"field": "phone", "message": "手机号格式不正确，需为 11 位大陆手机号（1 开头，第二位 3–9）"}]}`。
工单号内存自增，进程重启后从 0001 重新开始（占位实现，不落库）。

### 2.4 其他

- `GET /`：接口索引（浏览器直接打开 `http://127.0.0.1:8000/` 可看）。
- `GET /health`：健康检查。
- 故障注入（仅联调）：`?__delay_ms=30000` 延迟 30 秒（验证超时分支）、`?__status=500`（验证异常分支）、`?__body=not-json`（验证大模型解析失败兜底）。

---

## 3. Dify「HTTP 请求」节点怎么填

工作流中三个 HTTP 节点：`inventory_api`（库存）、`price_api`（报价）、`appt_api`（提交预约）。以库存节点为例：

| 配置项 | 填写值 |
| --- | --- |
| 方法 | `GET` |
| URL | `http://host.docker.internal:8000/api/inventory` |
| 查询参数（Params） | `brand` = `{{#quote_extract.brand#}}`；`model` = `{{#quote_extract.model#}}`（UI「参数」表格逐行填，不要拼在 URL 里） |
| Headers | 不填（GET 无需 Content-Type；若需要可加 `Accept: application/json`） |
| Authorization | 无 |
| Body | `none` |
| 超时 | 连接 5 秒、读取 10 秒、写入 5 秒（Dify 默认 10/60/20，本地 stub 用不到这么长，短一点能更快触发兜底） |
| 重试 | GET 可开 2 次、间隔 500ms；**POST 预约必须关闭自动重试**，否则可能重复建工单 |
| SSL 校验 | 开（HTTP 无影响） |

输出变量（HTTP 节点固定三个，引用方式）：

| 变量 | 类型 | 用途 | 引用写法 |
| --- | --- | --- | --- |
| `body` | string | 响应体（JSON 字符串，需靠 LLM/代码节点解析） | `{{#inventory_api.body#}}` |
| `status_code` | number | HTTP 状态码 | `{{#inventory_api.status_code#}}` |
| `headers` | object | 响应头 | `{{#inventory_api.headers#}}` |

下游用法：
- 条件分支：`{{#inventory_api.status_code#}}` `is` `200` → 正常话术；ELSE → 兜底话术。
- LLM 整理话术：把 `{{#inventory_api.body#}}` 放进 Prompt 的「接口返回」段，并明确要求「只引用返回中出现的价格/库存，缺失就说需要顾问确认」。
- 建议在 HTTP 节点后接一个 Code 节点 `inventory_parse` 用 `json.loads` 解析（比让 LLM 读 JSON 更稳），输出 `stock_status`、`reference_price`、`discount_text` 等字段供 End 节点回传。

`price_api` 与 `inventory_api` 相同，URL 换 `/api/price`。
`appt_api` 配置：

| 配置项 | 填写值 |
| --- | --- |
| 方法 | `POST` |
| URL | `http://host.docker.internal:8000/api/appointment` |
| Body 类型 | `json` |
| Body 字段 | `name` = `{{#appt_extract.name#}}`；`phone` = `{{#appt_extract.phone#}}`；`brand` = `{{#appt_extract.brand#}}`（可空）；`model` = `{{#appt_extract.model#}}`；`time` = `{{#appt_extract.time#}}` |
| Headers | 可不填（选 json 会自动带 `Content-Type: application/json`） |
| 重试 | 关闭 |

若要让「HTTP 节点失败」也产出友好话术，给节点开「异常处理 → 异常分支」，失败分支接到 LLM 兜底节点；或保留 ELSE 分支用状态码判断。

---

## 4. 容器访问宿主机：为什么是 host.docker.internal

- Docker Desktop（Windows）把 `host.docker.internal` 解析到 Docker Desktop 网关 `192.168.65.254`，宿主机上监听 `0.0.0.0:8000` 的服务即可被容器访问。
- **本机实测**：`docker exec docker-api-1 curl http://host.docker.internal:8000/health` → `200`（直连 OK）。
- 不要用 `172.17.0.1` 或 `127.0.0.1`：容器里的 `127.0.0.1` 是容器自己；本机实测 `172.17.0.1:11434` 不通，`host.docker.internal` 可通。
- Linux 部署时 `host.docker.internal` 默认不存在，需要在 compose 的 `api`/`worker` 服务加 `extra_hosts: ["host.docker.internal:host-gateway"]`。

---

## 5. 坑：Dify 的 SSRF 代理会拦截私网地址（本机必踩）

### 5.1 现象

HTTP 节点请求 `http://host.docker.internal:8000/...` 失败，Dify 节点报错（`api/core/helper/ssrf_proxy.py` 的 `ToolSSRFError` 文案）：

> Access to 'http://host.docker.internal:8000/api/inventory' was blocked by SSRF protection (e.g. SSRF_PROXY_ALLOW_PRIVATE_IPS=172.21.0.0/16 to allow 172.21.0.0/16). The URL resolves to a private, loopback, link-local, or otherwise non-public network address. See https://github.com/langgenius/dify/issues/38443.

### 5.2 根因（已在本机验证）

Dify 的 HTTP 节点强制走内部 Squid 代理（`SSRF_PROXY_HTTP_URL=http://ssrf_proxy:3128`）。Squid 默认 **deny 私网**（`docker/ssrf_proxy/squid-common.conf.template` 的 `acl to_private_networks` 包含 `192.168.0.0/16` 等，随后 `http_access deny to_private_networks`）。
`host.docker.internal` 解析为 `192.168.65.254`，正好落在 `192.168.0.0/16`，于是被 403 拦掉：

```text
# 实测：直连 200，走代理 403
docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' http://host.docker.internal:8000/health"                                   # 200
docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' -x http://ssrf_proxy:3128 http://host.docker.internal:8000/health"        # 403
# 403 响应头：Server: squid/6.13 / X-Squid-Error: ERR_ACCESS_DENIED 0
```

结论：**网络通、代理拦**。不是 stub 的问题，也不是防火墙问题。

### 5.3 放行（需要改 Dify 部署，动手前先确认权限；本机由 lead 决定）

思路：Squid 的入口脚本会把 `SSRF_PROXY_ALLOW_PRIVATE_IPS` 里的网段写成放行 ACL，再 `http_access allow`。

```powershell
cd C:\Users\zhou\Desktop\dify\docker

# 1) 新建（或编辑）ssrf-proxy.env，字面量写要放行的网段/主机
@"
SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.65.0/24
SSRF_HTTP_PORT=3128
SSRF_COREDUMP_DIR=/var/spool/squid
"@ | Set-Content -Encoding ascii .\envs\infrastructure\ssrf-proxy.env

# 2) 重建 ssrf_proxy 容器（env_file 变化必须重建，restart 不生效）
docker compose up -d --force-recreate ssrf_proxy

# 3) 验证配置已生成
docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf
#   期望看到 acl ... dst 192.168.65.0/24 与 http_access allow client_localnet ...

# 4) 再测：应输出 200
docker exec docker-api-1 sh -c "curl -s -o /dev/null -w '%{http_code}' -x http://ssrf_proxy:3128 http://host.docker.internal:8000/health"
```

要点与安全提示：

- 放行范围最小化：只放 `192.168.65.254/32` 或 `192.168.65.0/24`，不要放 `0.0.0.0/0`；Dify 文档注释里的 `172.21.0.0/16` 只是示例网段，与本机无关。
- 该放行对**所有**使用该 Dify 的用户/应用生效，属于安全边界变更；生产环境更推荐把接口发布到受控域名并只放行该域名（`SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=api.example.internal`）。
- `docker/.env` 里同名变量的优先级更高（`ssrf-proxy.defaults` 有说明）；若两处都写，以 `docker/.env` 为准，排查时两边都看。
- 回滚：删除 `ssrf-proxy.env`（或清空该变量）后 `docker compose up -d --force-recreate ssrf_proxy`。
- 改了没生效的常见原因：没重建容器（只 restart）、改的是 `ssrf-proxy.defaults` 而不是 `ssrf-proxy.env`、放行网段与 `host.docker.internal` 实际解析 IP 不一致（用 `docker exec docker-api-1 getent hosts host.docker.internal` 确认）。

### 5.4 暂不放行时的替代方案

1. **先交付画布**：HTTP 节点保留「异常分支 → 兜底话术」，让分支 2/3 在 SSRF 未放行时也能优雅失败；放行后无需改图即可跑通。
2. **用 `?__status=500` / `?__delay_ms=30000` 造异常**，先把超时/失败话术与判定标准测完（见 [`e2e_tests.md`](e2e_tests.md) 边界用例）。
3. **临时公网 mock**（ngrok/cloudflared 等）可绕过 SSRF，但引入外网依赖与数据外发，仅限本地演练且不推荐。
4. 不要试图用 Code 节点访问 stub：Code 节点跑在隔离沙箱里，没有网络访问能力。

---

## 6. 排查清单（按顺序）

| # | 检查 | 命令 / 判据 |
| --- | --- | --- |
| 1 | stub 活着 | `curl.exe http://127.0.0.1:8000/health` → `{"status":"ok"}` |
| 2 | 容器网络可达 | `docker exec docker-api-1 curl -s -o /dev/null -w '%{http_code}' http://host.docker.internal:8000/health` → 200 |
| 3 | 代理是否拦 | 同上加 `-x http://ssrf_proxy:3128`，403 即 SSRF |
| 4 | 放行是否生效 | `docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf` |
| 5 | Dify 侧报错 | 节点运行详情看 `ToolSSRFError` / `blocked by SSRF protection` 字样 |
| 6 | 超时分支 | stub 加 `?__delay_ms=30000`，节点应在读取超时（10s）后走异常分支 |
| 7 | 预约重复 | POST 节点「重试」必须关闭，检查工单号是否重复 |
| 8 | 中文乱码 | 请求/响应均为 UTF-8；`Content-Type: application/json`（不带 charset 也可） |

---

## 7. 边界

- stub 无鉴权、只读、数据全为占位示例；只允许本机/内网联调，**不要暴露到公网**。
- 真实接口接入时替换 URL、加鉴权（HTTP 节点「Authorization → API Key」或 Header），并保留同一套输出契约（`body`/`status_code`），工作流无需改结构。
