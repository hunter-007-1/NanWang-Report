# 数据流

## 规划与仿真数据流

```text
用户上传模型目录
  -> powergrid_pipeline_v2/data_test/
  -> main_scc.py
  -> 潮流 / N-1 / 短路分析
  -> LLM 候选方案
  -> 方案应用和复算
  -> fulfillment_scc/<时间戳>/run_*
```

每个有效 `run_*` 应能提供：

- 最终方案 JSON；
- `pf_report_<N>.json`；
- `n1_report_<N>.json`；
- `scc_report_<N>.json`；
- 可选的暂态结果和大模型原始输出。

## 报告数据流

```text
fulfillment_scc/<时间戳>/run_*
  -> main_api.py 聚合并按方案编号重排
  -> outputs/.../demo_input/
  -> data_preprocessing_pcn.py
  -> grid_calculator.py / second_batch_adapters.py
  -> working_dir/derived_metrics.json
  -> working_dir/pcn_claims.json + pcn_claims.db
  -> 洞察与报告生成
  -> report/report.md
  -> Claim/Calculate 校验结果写入 result.json
```

## 关键中间文件

| 文件 | 用途 |
| --- | --- |
| `demo_input/generation/parsed_proposals.json` | 方案内容和经济字段 |
| `demo_input/analysis_N/pf_report_N.json` | 基态潮流、电压、负载、网损、断面数据 |
| `demo_input/analysis_N/n1_report_N.json` | N-1 故障、故障后负载和电压数据 |
| `demo_input/analysis_N/scc_report_N.json` | 短路电流和断路器开断能力数据 |
| `working_dir/derived_metrics.json` | 方案级统一指标，是报告数值的首要来源 |
| `working_dir/pcn_claims.json` | 可溯源数值 Claim |
| `report/report.md` | 最终 Markdown 报告 |
| `result.json` | 阶段、成功状态和 PCN/Calculate 校验统计 |
| `out.log` | 完整执行日志和模型上下文 |

## 缺数原则

原始数据缺少分子、分母、完整记录或适用场景时，指标必须返回“当前输入不足，未评价”。不得用问题子集冒充全网总体，不得把缺失值补成 0。

