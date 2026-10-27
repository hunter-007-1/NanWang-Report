# 系统架构

## 总体结构

```text
浏览器
  |
  v
frame_fore-end_design
  |
  v
powergrid_pipeline/bridge_server.py : 8080
  |-- 规划任务 -> powergrid_pipeline_v2/functional_tests/main_scc.py
  |-- 报告接口 -> 进程内加载 dianwang_report_gen/main_api.py
  `-- 静态页面 -> ../frame_fore-end_design/

规划输出 fulfillment_scc/<时间戳>/run_*
  |
  v
dianwang_report_gen 工作流
  |
  v
outputs/<时间戳>_compare_pcn/
```

## 关键入口

| 场景 | 入口 |
| --- | --- |
| 完整网页系统 | `powergrid_pipeline/bridge_server.py` |
| 直接运行规划算法 | `powergrid_pipeline/powergrid_pipeline_v2/functional_tests/main_scc.py` |
| 报告 API | `dianwang_report_gen/main_api.py`，由 bridge 进程内加载 |
| 报告工作流编排 | `dianwang_report_gen/src/workflow.py` |

## 运行边界

- 真实规划仿真依赖 Windows、DSP/BPA 和 `pybpa`。
- 报告模块可以使用已经生成的 `fulfillment_scc/<时间戳>` 目录单独验证。
- `bridge_server.py` 同时负责前端静态资源、规划接口和报告接口。
- 8080 页面能打开只说明服务启动，不代表规划或报告已经执行成功。

## 报告工作流

```text
数据预处理
  -> 指标计算和 derived_metrics.json
  -> 洞察生成
  -> 人工确认洞察
  -> Claim 检索
  -> 安全优先的报告生成
  -> 程序补入核心表格和固定指标图
  -> 保护 Claim/Calculate/表图的保守润色
  -> 报告结构质量检查
  -> Claim/Calculate 校验
  -> report.md / DOCX / PDF
```

报告质量结果保存在 `State.report_quality_result`，由 `main_api.py` 与 PCN 校验结果共同决定草稿进入 `DRAFT_READY` 还是 `DRAFT_REVIEW_REQUIRED`。旧版 LLM 自由绘图代码路径默认关闭，仅保留显式兼容开关。
