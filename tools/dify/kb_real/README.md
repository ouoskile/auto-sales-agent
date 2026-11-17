# tools/dify/kb_real —— 真实知识库构建工具（task-8）

把 `txt/` 下的真实销售资料（30 款车型 + 23 篇术语 + 4 篇方法论）装配为可导入 Dify 的 9 篇 Markdown，并做合规预处理与自检。

## 文件说明

| 文件 | 说明 |
|---|---|
| `scan_compliance.py` | 扫描 `txt/` 源资料（默认跳过 28/29 违规词文档）的 level1/2/3 违规词命中，输出 `compliance_scan.json` |
| `build_kb_real.py` | 主构建脚本：切分装配 + 合规替换 + 人工重写 14 号 + 生成 manifest/变更记录/自检结果/报告 |
| `manifest.json` | 导入清单。`documents` 初始为空，由 `import_kb.py` 导入后回填；`plan` 是 9 篇文档的导入计划 |
| `change_log.json` | 逐条合规变更记录（机器可读，报告第 3 节即由它生成） |
| `compliance_scan.json` | 源资料扫描结果 |
| `generated_scan.json` | 产出文档的合规自检结果（每篇 level1/2/3 命中） |

## 运行步骤

```powershell
# 1) 扫描源资料
python -X utf8 tools/dify/kb_real/scan_compliance.py

# 2) 生成文档 + 报告 + 清单（可反复重跑，输出目录会被覆盖）
python -X utf8 tools/dify/kb_real/build_kb_real.py

# 3) 导入 Dify（需 console 凭据已在 tools/dify/dify.py 中配置）
python tools/dify/import_kb.py --kb-dir docs/dify/knowledge_real --manifest tools/dify/kb_real/manifest.json
```

产物：
- `docs/dify/knowledge_real/01–09_*.md`（9 篇）
- `docs/dify/guide/kb_real_report.md`（拆分/变更/问题/known gaps/导入步骤报告）

## 验收标准

- 每篇文档 `level1` 命中 = 0（`generated_scan.json` 与报告第 6 节）；
- 28/29 违规词文档不进客户知识库（内部合规资料，已转为 `tools/dify/compliance_words.json`）；
- 报告含逐条变更记录与额外补充内容表。

## 注意

- 车型指导价/参数为源资料整理值，非门店实时报价；成交价、库存、金融方案应走接口查询，知识库只放静态内容。
- 26 号异议话术中的续航/价格示例不对应具体车型，对客使用前需按具体配置复核。
