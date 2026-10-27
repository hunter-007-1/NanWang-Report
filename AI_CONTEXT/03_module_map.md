# 模块地图

## 统一服务与规划

| 文件 | 职责 | 常见修改原因 |
| --- | --- | --- |
| `powergrid_pipeline/bridge_server.py` | 8080 服务、文件上传、任务调度、报告 API 挂载 | 页面接口、任务路径、统一启动问题 |
| `powergrid_pipeline/powergrid_pipeline_v2/functional_tests/main_scc.py` | 规划与仿真主流程 | 真实方案生成、仿真阶段问题 |
| `powergrid_pipeline/powergrid_pipeline_v2/config/settings.yaml` | DSP 路径、模型 API、仿真参数 | 环境或仿真配置问题 |
| `frame_fore-end_design/app.js` | 首页交互、Mock/真实后端切换 | 按钮、接口调用、任务状态问题 |

## 报告生成

| 路径 | 职责 | 调用方/消费者 | 常见修改原因 | 验证 |
| --- | --- | --- | --- | --- |
| `dianwang_report_gen/main_api.py` | 报告任务 API、状态、结构质量与导出接口 | `bridge_server.py`、前端 | 报告按钮、输入目录、任务状态 | API/流程测试与历史案例 |
| `dianwang_report_gen/src/workflow.py` | 报告节点编排 | CLI/工作流入口 | 节点顺序或状态传递 | 工作流测试 |
| `dianwang_report_gen/src/graph_state.py` | 报告工作流状态模型 | 全部节点、`main_api.py` | 新增跨节点结果 | 编译与节点测试 |
| `dianwang_report_gen/src/nodes/data_preprocessing_pcn.py` | 保留输入字段、构建 `derived_metrics.json`、生成 Claim | 洞察、报告、校验 | 新指标、字段、汇总表 | 第一/二批指标测试 |
| `dianwang_report_gen/src/nodes/second_batch_adapters.py` | 把 PF/N-1/暂态/方案明细转成统一指标输入 | 预处理节点 | 第二批指标缺值或口径 | 第二批指标测试 |
| `dianwang_report_gen/src/tools/grid_calculator.py` | 指标公式、校验、单位和错误处理 | 预处理、洞察工具 | 公式、边界条件 | 指标专项测试 |
| `dianwang_report_gen/src/skills/resources/compare_rules.yaml` | 指标单位、公式、阈值、默认经济参数 | 指标与提示词 | 业务规则或阈值 | 规则/指标测试 |
| `dianwang_report_gen/src/nodes/retrieve_claims_for_insights.py` | 固定核心 Claim 和洞察检索 | 报告生成 | 报告拿不到已计算指标 | 检索压缩测试 |
| `dianwang_report_gen/src/nodes/generate_report.py` | 受控生成、程序化表图、保护式润色、结构检查 | 工作流、`main_api.py` | 报告结构与内容质量 | `test_report_generation_quality` |
| `dianwang_report_gen/src/nodes/report_quality.py` | 核心表补齐、固定图表、保护块、结构门禁 | `generate_report.py`、`main_api.py` | 报告质量规则 | `test_report_generation_quality` |
| `dianwang_report_gen/src/skills/insights_generation/` | 安全优先的三阶段洞察方法 | 洞察节点 | 比选方法或表达约束 | 提示词测试 |
| `dianwang_report_gen/src/skills/report_generation/` | 固定章节、证据边界与 AI/规则分工 | 报告生成节点 | 报告结构 | 提示词测试 |
| `dianwang_report_gen/src/skills/report_optimization/` | 不改事实块的保守润色 | 报告生成节点 | 表达优化范围 | 保护块测试 |
| `dianwang_report_gen/src/nodes/verify_calculate_tags.py` | 严格校验 `<calculate>` 标签 | PCN 校验 | 数值溯源格式 | Calculate 测试 |
| `dianwang_report_gen/src/nodes/safety_recommendation.py` | 强制安全硬约束结论 | 报告生成、校验 | 错误推荐或重复结论 | PCN/安全测试 |
| `dianwang_report_gen/src/nodes/convert_report.py` | 保存 Markdown、生成 DOCX/PDF | API、工作流 | 导出或文件落地 | 转换与人工视觉检查 |

## 修改指标时的最小追踪链

```text
原始 JSON 字段
  -> FIELD_FILTERS / adapter
  -> calculate_grid_metric
  -> derived_metrics.json
  -> 核心汇总表
  -> Claim
  -> 报告正文
  -> 专项测试
```

只在 `SUPPORTED_METRICS` 中出现，不代表指标已经完整进入最终报告。
