# AI 上下文变更记录

本文件记录会影响 AI 理解、开发或验收方式的变更。它不是 Git 提交记录的替代品。

## 2026-10-27

- 变更目标：让公开 GitHub 仓库可独立克隆、启动 Mock 演示，并移除本机配置和样例数据泄漏风险。
- 修改文件：根 README、根 `.gitignore`、根依赖清单、Windows 启动脚本、Flask bridge、前端 Mock 默认项、规划配置加载器、规划配置模板、报告 `.env.example`、AI 上下文文档及两个含固定本机路径的 Python 脚本。
- 数据结构或接口变化：配置加载器支持 `DSP_BIN_DIR` 和 `MODELSCOPE_API_KEY` 环境变量覆盖；bridge 支持 `HOST`、`PORT` 配置，默认只监听本机。
- 新增/调整业务规则：新克隆默认进入 Mock 演示；模型、上传数据、运行结果、密钥和区域案例数据不进入 Git。
- 验证命令及结果：`python -m pytest tests dianwang_report_gen/tests` 为 283 passed；`python -m compileall -q powergrid_pipeline dianwang_report_gen` 通过；Flask 测试客户端 GET `/` 返回 200；`pip install --dry-run -r requirements.txt` 解析成功。
- 剩余风险：真实仿真依赖 BPA/DSP 和本机 `pybpa`；报告生成依赖用户提供的 OpenAI 兼容模型配置。

## 2026-08-17

- 创建 `AI_CONTEXT/`。
- 记录三个子项目的职责和统一启动入口。
- 记录规划到报告的完整数据流。
- 记录指标实现链、分层比选规则和缺数原则。
- 记录专项测试命令与报告验收信号。
- 记录 24 项指标的当前实现情况和剩余输入缺口。
- 变更目标：在不修改任何指标的前提下优化报告生成方法。
- 修改文件：报告生成/润色/洞察技能，新增 `report_quality.py` 和专项测试，并扩展 `State`、报告 API 状态。
- 数据结构或接口变化：新增可选 `report_quality_result`，状态接口新增 `reportQualityResult`；指标数据结构没有变化。
- 新增/调整业务规则：三阶段安全优先；核心表和固定图由程序生成；AI 润色不得修改可验证块；结构检查与 PCN 共同决定草稿复核状态。
- 验证命令及结果：编译检查通过；报告质量 12 项、背景/检索/PCN/安全 70 项、指标 152 项、Calculate+报告质量+PCN/安全组合 87 项均通过。
- 剩余风险：尚未完成真实 LLM 端到端重跑、正式 Word/PDF 模板和逐页视觉验收。

## 后续记录模板

```markdown
## YYYY-MM-DD

- 变更目标：
- 修改文件：
- 数据结构或接口变化：
- 新增/调整业务规则：
- 验证命令及结果：
- 剩余风险：
```

## 维护规则

- 架构入口变化：同步更新 `01_architecture.md` 和 `03_module_map.md`。
- 输入/输出字段变化：同步更新 `02_data_flow.md`。
- 指标公式或阈值变化：同步更新 `04_business_rules.md`。
- 测试命令或验收标准变化：同步更新 `05_test_guide.md`。
- 完成或新增待办：同步更新 `06_current_status.md`。
