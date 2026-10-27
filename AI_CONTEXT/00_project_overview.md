---
ai_context_version: 1
last_verified_at: 2026-08-17T12:38:55Z
git_commit: UNKNOWN
scope: repository
status: verified
---

# 项目概述

## 项目目标

本项目用于完成 500kV 及以上电网规划方案的生成、仿真校核、方案比选和可研报告生成。

主要能力：

1. 上传和整理 `.dat`、`.swi`、`.scset` 等基础模型文件。
2. 执行潮流、N-1、短路电流等分析。
3. 调用大模型生成候选网架方案并应用到模型。
4. 计算安全、技术、工程和经济指标。
5. 生成带 Claim/Calculate 数值溯源的比选报告。
6. 在网页中查看、编辑并导出报告。

## 三个主要子项目

| 目录 | 主要职责 |
| --- | --- |
| `powergrid_pipeline/` | 规划、仿真、方案生成和统一 Web 服务 |
| `dianwang_report_gen/` | 数据预处理、指标计算、报告生成和 PCN 校验 |
| `frame_fore-end_design/` | 首页、任务进度和报告编辑页面 |

## AI 开始工作前的阅读顺序

1. 根目录 `AGENTS.md`。
2. 本目录 `00_project_overview.md`。
3. 根据任务读取 `01_architecture.md`、`02_data_flow.md` 或 `04_business_rules.md`。
4. 只打开 `03_module_map.md` 中与任务直接相关的源码。
5. 修改前确认 `06_current_status.md`，修改后更新 `07_change_log.md`。

## 当前统一入口

从项目根目录进入 `powergrid_pipeline` 后运行：

```powershell
python bridge_server.py
```

浏览器访问：`http://127.0.0.1:8080/`。

不要把 `frame_fore-end_design/index.html` 当成完整系统入口；完整流程需要 `bridge_server.py` 提供接口和静态文件。

## 已验证

- 统一网页入口、三个子项目职责和报告主链已按当前源码核对。
- 报告生成已接入程序化核心表格、固定指标图表、保护式润色和结构质量检查。

## 推测

- 当前固定图表能提升可读性，但企业模板和真实 LLM 端到端效果仍需用新生成报告评估。

## 待确认

- 尚未取得正式可研报告 Word 母版，因此封面、目录、页眉页脚和签审栏的最终样式未定。
