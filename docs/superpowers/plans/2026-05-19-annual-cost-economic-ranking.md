# Annual Cost Economic Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute annual cost during report input aggregation using `C_annual = C_invest * i(1+i)^n / ((1+i)^n - 1) + C_maintain` with `n=20`, `i=0.07`, then expose it as the economic ranking metric.

**Architecture:** Keep the calculation at the report aggregation boundary in `dianwang_report_gen/main_api.py`, where selected proposals and raw fallback economics are merged. Continue using `data_preprocessing_pcn.py` to extract values from the generated `description`, but rename the summary-table metric from lifecycle cost to annual cost for report clarity.

**Tech Stack:** Python 3.12, standard-library `unittest`, existing report preprocessing flow.

---

### Task 1: Add Annual Cost Tests

**Files:**

- Modify: `dianwang_report_gen/test_data_preprocessing_summary.py`

- [ ]  Add assertions that raw construction and maintenance costs produce `年费用` in the generated proposal description.
- [ ]  Add assertions that the summary table labels the metric as `年费用` and includes the computed value.
- [ ]  Run: `python -m unittest test_data_preprocessing_summary.py` from `dianwang_report_gen`.

### Task 2: Implement Annual Cost Calculation

**Files:**

- Modify: `dianwang_report_gen/main_api.py`

- [ ]  Add constants `ANNUAL_COST_YEARS = 20` and `ANNUAL_COST_INTEREST_RATE = 0.07` near the economic helper functions.
- [X]  Add a numeric parser that accepts plain numeric strings and strips commas/Chinese unit hints conservatively.
- [ ]  Add `_calculate_annual_cost(construction_cost, operation_cost)` using the capital recovery factor formula.
- [ ]  Extend `_economic_fields_from_proposal()` so `annual_cost` is computed when construction and operation costs exist and no explicit annual/lifecycle cost exists.
- [ ]  Update `_build_proposal_description()` to write `年费用：...` instead of `全寿命周期成本：...` for the calculated/existing annual-cost field.

### Task 3: Rename Summary Metric

**Files:**

- Modify: `dianwang_report_gen/src/nodes/data_preprocessing_pcn.py`

- [ ]  Keep internal key `lifecycle_cost` to minimize code churn.
- [ ]  Change the table header from `全寿命周期成本` to `年费用`.
- [ ]  Keep extraction labels `全寿命周期成本`, `全生命周期成本`, and `年费用` for compatibility.

### Task 4: Update Report Prompts

**Files:**

- Modify: `dianwang_report_gen/src/prompts/access_schemes_comparing_principles.md`
- Modify: `dianwang_report_gen/src/prompts/report_outline.md`
- Modify: `dianwang_report_gen/src/agents/insights_generation/system_prompt_template.md`

- [ ]  Replace economic core metric wording so stage two ranks by `年费用`.
- [ ]  Document the formula and fixed parameters `n=20`, `i=0.07`.
- [ ]  Preserve warnings against inventing missing construction or maintenance costs.

### Task 5: Verify

**Files:**

- Test: `dianwang_report_gen/test_data_preprocessing_summary.py`

- [ ]  Run: `python -m unittest test_data_preprocessing_summary.py` from `dianwang_report_gen`.
- [ ]  Confirm tests pass and no unrelated generated output was modified.
