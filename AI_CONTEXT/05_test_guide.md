# 测试与验收指南

## 测试环境

克隆后先安装仓库依赖：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

测试应从 `dianwang_report_gen/` 目录运行，避免导入到错误的 `src`。

## 指标专项测试

```powershell
cd dianwang_report_gen
..\.venv\Scripts\python.exe -m unittest tests.test_first_batch_metrics tests.test_second_batch_metrics
```

最近一次只读复核结果：`Ran 152 tests ... OK`。

## PCN 与安全结论测试

```powershell
cd dianwang_report_gen
..\.venv\Scripts\python.exe -m unittest tests.test_pcn_claim_and_safety_fixes
```

## 报告生成方法专项测试

```powershell
cd dianwang_report_gen
..\.venv\Scripts\python.exe -m unittest tests.test_report_generation_quality
```

覆盖核心表幂等插入、固定图表、润色保护块、结构检查、安全结论标题和安全优先提示词。报告生成方法变化后，至少同时运行本组、PCN/安全组和两批指标组。

## 报告专用历史案例

不重新执行 DSP/BPA 时，可以指定已有输入：

```powershell
$env:REPORT_TEST_INPUT_DIR='<local path to a run_* input directory>'
cd powergrid_pipeline
..\.venv\Scripts\python.exe bridge_server.py
```

然后打开：

```text
http://127.0.0.1:8080/?reportInputOverride=1
```

## 报告完成信号

按以下顺序检查最新的 `outputs/<时间戳>_compare_pcn/`：

1. `result.json`：`failed=false`、`ready=true`；
2. `report/report.md` 存在且有实际内容；
3. `out.log` 没有未处理异常；
4. `working_dir/derived_metrics.json` 的指标状态符合输入；
5. Claim 和 Calculate 校验全部通过，才属于可直接交付版本。
6. `report_quality_result.structure_passed=true`，且必选章节和三张核心汇总表没有缺项。

`DRAFT_READY` 或网页 HTTP 200 只说明阶段/服务可用，不单独证明全部数值和报告结论正确。

当前任务状态只区分可直接查看草稿和需要复核；Word/PDF 企业版式与逐页视觉检查尚未自动纳入门禁。

## 指标改动验收

每项指标至少验证：正常输入、缺字段、非法类型、零分母/空集合、单位、方案级汇总、Claim 入库、最终表格展示。
