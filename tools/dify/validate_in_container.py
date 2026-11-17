# -*- coding: utf-8 -*-
"""在 docker-api-1 容器内用 Dify/graphon 真实 pydantic 模型校验 draft 提交体。

容器内运行：
    docker cp tools/dify/workflow_draft.json docker-api-1:/tmp/workflow_draft.json
    docker cp tools/dify/validate_in_container.py docker-api-1:/tmp/validate_in_container.py
    docker exec docker-api-1 sh -lc "cd /app/api && .venv/bin/python /tmp/validate_in_container.py"
"""

import json
import sys
import traceback

sys.path.insert(0, "/app/api")

DOC = "/tmp/workflow_draft.json"


def main() -> int:
    with open(DOC, encoding="utf-8") as fh:
        doc = json.load(fh)

    ok = True

    # 1) 顶层提交体：controllers.console.app.workflow.SyncDraftWorkflowPayload
    try:
        from controllers.console.app.workflow import SyncDraftWorkflowPayload

        payload = SyncDraftWorkflowPayload.model_validate(doc)
        print(f"[payload] OK  graph nodes={len(payload.graph['nodes'])} "
              f"edges={len(payload.graph['edges'])} features={sorted(payload.features)}")
    except Exception:
        ok = False
        print("[payload] FAIL")
        traceback.print_exc()

    # 2) 每个节点 data：graphon 节点实体模型
    mapping = {}
    try:
        from graphon.nodes.start.entities import StartNodeData
        from graphon.nodes.code.entities import CodeNodeData
        from graphon.nodes.llm.entities import LLMNodeData
        from graphon.nodes.if_else.entities import IfElseNodeData
        from graphon.nodes.http_request.entities import HttpRequestNodeData
        from graphon.nodes.question_classifier.entities import QuestionClassifierNodeData
        from graphon.nodes.parameter_extractor.entities import ParameterExtractorNodeData
        from graphon.nodes.template_transform.entities import TemplateTransformNodeData
        from graphon.nodes.variable_aggregator.entities import VariableAggregatorNodeData
        from graphon.nodes.end.entities import EndNodeData

        mapping = {
            "start": StartNodeData,
            "code": CodeNodeData,
            "llm": LLMNodeData,
            "if-else": IfElseNodeData,
            "http-request": HttpRequestNodeData,
            "question-classifier": QuestionClassifierNodeData,
            "parameter-extractor": ParameterExtractorNodeData,
            "template-transform": TemplateTransformNodeData,
            "variable-aggregator": VariableAggregatorNodeData,
            "end": EndNodeData,
        }
    except Exception:
        ok = False
        print("[import graphon entities] FAIL")
        traceback.print_exc()

    try:
        from core.workflow.nodes.knowledge_retrieval.entities import (
            KnowledgeRetrievalNodeData,
        )

        mapping["knowledge-retrieval"] = KnowledgeRetrievalNodeData
        print("[import knowledge_retrieval entities] OK")
    except Exception as exc:
        print(f"[import knowledge_retrieval entities] SKIP（用字段白名单兜底校验）：{exc}")
        mapping["knowledge-retrieval"] = None

    for node in doc["graph"]["nodes"]:
        nid = node["id"]
        data = dict(node["data"])
        ntype = data.get("type")
        cls = mapping.get(ntype)
        if cls is None:
            if ntype == "knowledge-retrieval":
                missing = [
                    k
                    for k in ("query_variable_selector", "dataset_ids", "retrieval_mode")
                    if k not in data
                ]
                print(f"[node {nid}] {ntype}: 白名单校验 "
                      f"{'OK' if not missing else 'FAIL missing ' + str(missing)}")
            else:
                ok = False
                print(f"[node {nid}] 未知类型 {ntype}")
            continue
        try:
            cls.model_validate(data)
            print(f"[node {nid}] {ntype}: OK")
        except Exception as exc:
            ok = False
            print(f"[node {nid}] {ntype}: FAIL {exc.__class__.__name__}")
            print(str(exc)[:1500])

    print("\nRESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
