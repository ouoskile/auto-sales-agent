#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
门店销售 Dify 工作流 —— 后端接口占位服务（零外部依赖，仅标准库）

用途：在 Dify「HTTP 请求」节点里被调用，返回库存 / 报价 / 预约工单的**占位数据**。
数据口径与 docs/dify/knowledge/01_门店车型库.md、03_购车流程与服务说明.md 保持一致；
价格为门店参考价，最终以销售顾问核算为准（与知识库口吻一致）。

启动（默认 0.0.0.0:8000，容器内可经 host.docker.internal 访问）：
    python tools/dify/api_stub.py
    python tools/dify/api_stub.py --port 8000 --host 0.0.0.0
    py tools/dify/api_stub.py

自检：
    curl http://127.0.0.1:8000/health
    curl "http://127.0.0.1:8000/api/inventory?model=车型A"
    curl "http://127.0.0.1:8000/api/price?brand=星辰&model=车型A"
    curl -X POST http://127.0.0.1:8000/api/appointment -H "Content-Type: application/json" \
         -d '{"name":"张三","phone":"13800138000","model":"车型A","time":"本周六 10:00"}'

接口（全部返回 application/json; charset=utf-8）：
    GET  /health                     健康检查
    GET  /api/inventory?brand=&model= 库存状态（model / stock_status / reference_price / discount / delivery_days）
    GET  /api/price?brand=&model=     报价明细（指导价 / 参考落地价 / 优惠 / 金融方案 / 费用拆分）
    POST /api/appointment             预约试驾工单（name / phone / model / time，可选 brand）
    GET  /                           接口索引（浏览器可读）

联调用的故障注入（仅测试用，不影响正常请求）：
    ?__delay_ms=30000   先睡 30 秒再返回 —— 用于验证 Dify HTTP 节点的读取超时/兜底分支
    ?__status=500       直接返回 500 —— 用于验证异常分支
    ?__body=not-json    返回非 JSON 文本 —— 用于验证大模型解析失败兜底
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 占位数据：与 docs/dify/knowledge/01_门店车型库.md 对齐（价格单位：万元）
# ---------------------------------------------------------------------------

MODELS = [
    {
        "brand": "五菱",
        "model": "五菱宏光 MINIEV",
        "aliases": ["miniev", "宏光miniev", "宏光mini", "宏光", "五菱宏光", "代步车", "微型车", "a00"],
        "category": "A00 级微型轿车（纯电）",
        "energy": "纯电",
        "seats": 4,
        "guide_price": 4.48,
        "purchase_tax": 0.0,        # 纯电减免（示例口径）
        "insurance": 0.45,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "有现车",
        "stock_detail": "门店现车 2 台，可当天看车、当天试驾（示例库存）",
        "delivery_days": 1,
        "discount": ["现金优惠 2,000 元", "置换补贴最高 3,000 元", "24 期低息（首付 30% 起）", "提车礼包（脚垫）"],
        "specs": {"CLTC 续航": "120-215km", "轴距": "2010mm", "驱动": "后置后驱", "亮点": "三门四座 / 好开好停 / 用车成本低"},
        "fit_for": "市区短途代步、买菜接娃、家庭第二台车、预算 5 万左右的首次购车用户",
    },
    {
        "brand": "吉利",
        "model": "吉利银河星愿",
        "aliases": ["星愿", "银河星愿", "吉利星愿", "小型纯电轿车"],
        "category": "小型纯电轿车",
        "energy": "纯电",
        "seats": 5,
        "guide_price": 6.48,
        "purchase_tax": 0.0,
        "insurance": 0.55,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "有现车",
        "stock_detail": "门店现车 1 台，可当天看车（示例库存）",
        "delivery_days": 3,
        "discount": ["现金优惠 3,000 元", "置换补贴最高 5,000 元", "36 期低息（年化约 3.5%）", "提车礼包（贴膜 + 脚垫）"],
        "specs": {"CLTC 续航": "310-410km", "轴距": "2650mm", "座数": "五门五座", "亮点": "Flyme Auto 车机 / 快充 / 同级大轴距"},
        "fit_for": "年轻上班族、三口之家、预算 10 万内看重智能座舱与空间的用户",
    },
    {
        "brand": "比亚迪",
        "model": "比亚迪海鸥",
        "aliases": ["海鸥", "byd海鸥", "小型纯电轿车", "刀片电池"],
        "category": "小型纯电轿车",
        "energy": "纯电",
        "seats": 5,
        "guide_price": 7.38,
        "purchase_tax": 0.0,
        "insurance": 0.55,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "有现车",
        "stock_detail": "门店现车 3 台，可当天看车、当天试驾（示例库存）",
        "delivery_days": 2,
        "discount": ["现金优惠 4,000 元", "置换补贴最高 6,000 元", "24 期 0 息（首付 30% 起）", "提车礼包（脚垫 + 贴膜）"],
        "specs": {"CLTC 续航": "305-405km", "轴距": "2500mm", "电池": "刀片电池", "亮点": "快充 / 三电技术 / 售后网点多"},
        "fit_for": "看重品牌与可靠性、市区通勤为主的家庭第二台车、求稳看重售后的用户",
    },
    {
        "brand": "零跑",
        "model": "零跑 A10",
        "aliases": ["a10", "零跑a10", "零跑", "小型纯电suv"],
        "category": "小型纯电 SUV",
        "energy": "纯电",
        "seats": 5,
        "guide_price": 6.58,
        "purchase_tax": 0.0,
        "insurance": 0.52,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "需排期",
        "stock_detail": "当前无现车，排期生产，预计 7 天左右到店（示例排期）",
        "delivery_days": 7,
        "discount": ["现金优惠 3,000 元", "置换补贴最高 5,000 元", "36 期低息（年化约 3.8%）", "基础礼包（脚垫）"],
        "specs": {"CLTC 续航": "400-510km", "轴距": "2630mm", "辅助驾驶": "标配 L2 级智能辅助驾驶", "亮点": "快充 / 同价位配置高 / 续航长"},
        "fit_for": "预算有限但想要高配置的年轻用户、注重性价比的代步用户",
    },
    {
        "brand": "比亚迪",
        "model": "比亚迪宋 Pro DM-i",
        "aliases": ["宋pro", "宋 pro", "宋pro dm-i", "宋pro dmi", "比亚迪宋", "插混suv"],
        "category": "紧凑型插混 SUV",
        "energy": "插电混动",
        "seats": 5,
        "guide_price": 10.98,
        "purchase_tax": 0.49,       # 插混减半征收（示例口径）
        "insurance": 0.62,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "有现车",
        "stock_detail": "门店现车 2 台，可当天看车、当天试驾（示例库存）",
        "delivery_days": 3,
        "discount": ["现金优惠 6,000 元", "置换补贴最高 8,000 元", "24 期 0 息（首付 30% 起）", "免费家充桩安装（30 米内）"],
        "specs": {"纯电续航": "55-120km", "亏电油耗": "3.8L/100km", "轴距": "2712mm", "亮点": "DM-i 可油可电 / 绿牌 / 无续航焦虑"},
        "fit_for": "普通家庭首台车、有充电条件、想要低用车成本与绿牌的用户",
    },
    {
        "brand": "理想",
        "model": "理想 L6",
        "aliases": ["l6", "理想l6", "增程suv", "中大型suv"],
        "category": "中型增程 SUV",
        "energy": "增程式电动",
        "seats": 5,
        "guide_price": 24.98,
        "purchase_tax": 1.11,       # 增程按减半征收测算（示例口径）
        "insurance": 0.95,
        "plate_fee": 0.05,
        "other_fees": 0.00,
        "stock_status": "需预订",
        "stock_detail": "需预订排产，预计 15 天左右到店（示例排期）",
        "delivery_days": 15,
        "discount": ["现金优惠 5,000 元", "置换补贴最高 10,000 元", "36 期低息（年化约 3.2%）", "提车礼包（脚垫 + 贴膜）"],
        "specs": {"纯电续航": "212km（CLTC）", "综合续航": "1390km（CLTC）", "轴距": "2920mm", "亮点": "增程无焦虑 / 大空间 / 智能座舱"},
        "fit_for": "预算 25 万左右、二胎家庭、看重空间与长途出行的用户",
    },
]

FINANCE_PLANS = [
    {"name": "全款", "down_payment_ratio": 1.0, "months": 0, "rate": "无", "note": "一次性付清，可享现金优惠"},
    {"name": "24 期 0 息", "down_payment_ratio": 0.3, "months": 24, "rate": "0%", "note": "首付 30% 起，需通过金融审批"},
    {"name": "36 期低息", "down_payment_ratio": 0.3, "months": 36, "rate": "年化约 3.5%", "note": "月供更低，具体以金融机构审批为准"},
]

DISCLAIMER = "以上为门店参考价与示例优惠，最终成交价与金融方案以销售顾问现场核算及审批结果为准。"

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


# ---------------------------------------------------------------------------
# 查询 / 校验辅助
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """归一化：去空白、转小写、去掉常见后缀，便于品牌/车型模糊匹配。"""
    return re.sub(r"[\s\-_/]+", "", (text or "")).lower()


def find_model(brand: str = "", model: str = ""):
    """按 brand+model 精确/别名匹配；只给 model 或只给 brand 也可。返回 (car, err)。"""
    b, m = _norm(brand), _norm(model)
    if not b and not m:
        return None, ("缺少 brand 与 model 参数", "MODEL_REQUIRED")
    candidates = []
    for car in MODELS:
        keys = [_norm(car["model"])] + [_norm(x) for x in car["aliases"]]
        brand_keys = [_norm(car["brand"])]
        model_ok = (not m) or any(m == k or m in k or k in m for k in keys if k)
        brand_ok = (not b) or any(b in k or k in b for k in brand_keys if k)
        if model_ok and brand_ok:
            candidates.append(car)
    if not candidates:
        return None, (
            "未找到车型：brand=%r model=%r；可选车型为 五菱宏光 MINIEV / 吉利银河星愿 / 比亚迪海鸥 / 零跑 A10 / 比亚迪宋 Pro DM-i / 理想 L6" % (brand, model),
            "MODEL_NOT_FOUND",
        )
    # 多命中时优先“精确等于车型名”的那条
    for car in candidates:
        if _norm(model) in (_norm(car["model"]),) or _norm(model) in [_norm(x) for x in car["aliases"]]:
            return car, None
    return candidates[0], None


def landed_total(car) -> float:
    """参考落地价 = 车价 + 购置税 + 保险 + 上牌 + 其他（示例口径，与 docs/dify/knowledge_real/01_微型入门代步与紧凑型轿车.md 等真实资料中的指导价区间对齐（价格为示例口径））。"""
    return round(
        car["guide_price"] + car["purchase_tax"] + car["insurance"] + car["plate_fee"] + car["other_fees"], 2
    )


def inventory_payload(car) -> dict:
    return {
        "model": car["model"],
        "brand": car["brand"],
        "category": car["category"],
        "energy": car["energy"],
        "stock_status": car["stock_status"],
        "stock_detail": car["stock_detail"],
        "reference_price": landed_total(car),
        "reference_price_unit": "万元",
        "discount": car["discount"],
        "delivery_days": car["delivery_days"],
        "delivery_note": "现车付款后约 3–7 个工作日提车；排期车 15–45 天" if car["stock_status"] == "有现车"
        else "排期/预订车预计 %d 天到店，具体以订单确认为准" % car["delivery_days"],
        "can_test_drive_today": car["stock_status"] == "有现车",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "门店库存系统（占位数据）",
    }


def price_payload(car) -> dict:
    breakdown = {
        "vehicle_price": car["guide_price"],
        "purchase_tax": car["purchase_tax"],
        "insurance": car["insurance"],
        "plate_fee": car["plate_fee"],
        "other_fees": car["other_fees"],
    }
    total = round(sum(breakdown.values()), 2)
    return {
        "model": car["model"],
        "brand": car["brand"],
        "guide_price": car["guide_price"],
        "reference_price": total,
        "price_unit": "万元",
        "price_breakdown": breakdown,
        "breakdown_total": total,
        "discount": car["discount"],
        "finance_plans": FINANCE_PLANS,
        "disclaimer": DISCLAIMER,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "门店报价系统（占位数据）",
    }


def mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone


def appointment_payload(body: dict, seq: int) -> tuple[dict, int]:
    """校验并生成预约工单；返回 (payload, http_status)。"""
    name = str(body.get("name") or "").strip()
    phone = re.sub(r"[\s\-]", "", str(body.get("phone") or ""))
    model = str(body.get("model") or "").strip()
    when = str(body.get("time") or body.get("appointment_time") or "").strip()
    brand = str(body.get("brand") or "").strip()

    errors = []
    if not name:
        errors.append({"field": "name", "message": "缺少姓名"})
    elif len(name) > 20:
        errors.append({"field": "name", "message": "姓名过长（≤20 字）"})
    if not phone:
        errors.append({"field": "phone", "message": "缺少手机号"})
    elif not PHONE_RE.match(phone):
        errors.append({"field": "phone", "message": "手机号格式不正确，需为 11 位大陆手机号（1 开头，第二位 3–9）"})
    if not model:
        errors.append({"field": "model", "message": "缺少意向车型"})
    if not when:
        errors.append({"field": "time", "message": "缺少预约时间"})
    elif len(when) > 64:
        errors.append({"field": "time", "message": "预约时间过长（≤64 字），建议格式如 2026-11-21 10:00"})

    car = None
    if model:
        car, err = find_model(brand, model)
        if err:
            errors.append({"field": "model", "message": "未找到意向车型：%s" % model})

    if errors:
        return {
            "ok": False,
            "code": "INVALID_ARGUMENT",
            "message": "预约信息不完整或格式不正确，请补充后再试。",
            "errors": errors,
        }, 400

    ticket = "APPT-%s-%04d" % (datetime.now().strftime("%Y%m%d"), seq)
    return {
        "ok": True,
        "ticket_id": ticket,
        "status": "已受理",
        "message": "预约已提交成功，门店销售顾问将在 30 分钟内与您电话确认。",
        "appointment": {
            "name": name,
            "phone": mask_phone(phone),
            "brand": car["brand"],
            "model": car["model"],
            "time": when,
            "store": "示例门店（占位）",
        },
        "stock_hint": car["stock_status"],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "门店预约系统（占位数据）",
    }, 200


# ---------------------------------------------------------------------------
# HTTP 处理
# ---------------------------------------------------------------------------

class StubHandler(BaseHTTPRequestHandler):
    server_version = "CarSalesStub/1.0"
    appointment_seq = 0

    # ---- 基础输出 ----
    def _send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, text: str, status: int = 200) -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:  # 简化日志
        sys.stdout.write("[%s] %s - %s\n" % (datetime.now().strftime("%H:%M:%S"), self.address_string(), fmt % args))
        sys.stdout.flush()

    # ---- 故障注入（联调用） ----
    def _fault_inject(self, query: dict) -> bool:
        """返回 True 表示已经由故障注入接管响应。"""
        delay = query.get("__delay_ms")
        if delay:
            try:
                time.sleep(max(0.0, int(delay) / 1000.0))
            except ValueError:
                pass
        status = query.get("__status")
        if status:
            try:
                code = int(status)
            except ValueError:
                code = 500
            self._send_json({"error": "injected fault", "status": code, "hint": "由 __status 参数注入"}, code)
            return True
        body = query.get("__body")
        if body is not None:
            self._send_text(body, 200)
            return True
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if self._fault_inject({k: v[0] for k, v in query.items()}):
            return

        if path == "/":
            self._send_json({
                "service": "汽车销售 Dify 后端占位服务",
                "version": "1.0",
                "endpoints": {
                    "GET /health": "健康检查",
                    "GET /api/inventory?brand=&model=": "库存查询",
                    "GET /api/price?brand=&model=": "报价查询",
                    "POST /api/appointment": "预约试驾工单",
                },
                "models": [{"brand": c["brand"], "model": c["model"]} for c in MODELS],
                "disclaimer": DISCLAIMER,
            })
            return

        if path == "/health":
            self._send_json({"status": "ok", "service": "car-sales-api-stub", "time": datetime.now().isoformat(timespec="seconds")})
            return

        if path == "/api/inventory":
            car, err = find_model(query.get("brand", [""])[0], query.get("model", [""])[0])
            if err:
                self._send_json({"ok": False, "code": err[1], "error": err[0], "hint": "示例：/api/inventory?brand=星辰&model=车型A"}, 404)
                return
            data = inventory_payload(car)
            data["ok"] = True
            self._send_json(data)
            return

        if path == "/api/price":
            car, err = find_model(query.get("brand", [""])[0], query.get("model", [""])[0])
            if err:
                self._send_json({"ok": False, "code": err[1], "error": err[0], "hint": "示例：/api/price?brand=星辰&model=车型A"}, 404)
                return
            data = price_payload(car)
            data["ok"] = True
            self._send_json(data)
            return

        self._send_json({"ok": False, "code": "NOT_FOUND", "error": "未知路径：%s" % path}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if self._fault_inject({k: v[0] for k, v in query.items()}):
            return

        if path != "/api/appointment":
            self._send_json({"ok": False, "code": "NOT_FOUND", "error": "未知路径：%s" % path}, 404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = {}
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"ok": False, "code": "BAD_JSON", "error": "请求体不是合法 JSON", "hint": "Content-Type 应为 application/json"}, 400)
                return
        if not isinstance(body, dict):
            self._send_json({"ok": False, "code": "BAD_JSON", "error": "请求体应为 JSON 对象"}, 400)
            return

        StubHandler.appointment_seq += 1
        payload, status = appointment_payload(body, StubHandler.appointment_seq)
        self._send_json(payload, status)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="汽车销售 Dify 后端占位服务（标准库版）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（容器可访问）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), StubHandler)
    server.daemon_threads = True
    print("汽车销售后端占位服务已启动： http://%s:%d/" % (args.host, args.port))
    print("自检： http://127.0.0.1:%d/health" % args.port)
    print("Dify 容器内地址： http://host.docker.internal:%d/api/inventory?brand=星辰&model=车型A" % args.port)
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
