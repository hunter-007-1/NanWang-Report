# 南网规划与比选报告系统

本仓库包含电网规划流程、比选报告生成服务和网页前端。克隆后可先运行 Mock 演示；接入真实报告生成需要配置 OpenAI 兼容模型，运行网架仿真还需要 Windows、BPA/DSP 和 `pybpa`。

## 快速启动（Windows）

要求 Python 3.11 或 3.12（64 位）和 Git。克隆后在仓库目录双击 `start_project.cmd`。首次启动会创建本地 `.venv`、安装 Python 依赖并启动服务；之后启动会直接复用环境。

也可以在 PowerShell 中手动执行：

```powershell
py -3.11 -m venv .venv  # 也可使用 py -3.12
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item dianwang_report_gen\.env.example dianwang_report_gen\.env
.\.venv\Scripts\python.exe -X utf8 powergrid_pipeline\bridge_server.py
```

打开 <http://127.0.0.1:8080/>。页面默认使用 Mock 数据，适合检查界面与报告编辑流程。Mock 模式不会运行电网仿真或调用模型服务。

## 配置真实模型服务

复制 `dianwang_report_gen/.env.example` 为 `dianwang_report_gen/.env`，填写模型提供方给出的模型名、API 地址和密钥：

```dotenv
OPENAI_API_KEY=your-api-key
LLM_MODEL=your-model-name
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
```

规划模型密钥可通过环境变量 `MODELSCOPE_API_KEY` 设置。真实规划仿真还需设置 `DSP_BIN_DIR` 指向本机 BPA/DSP 的 `Bin` 目录，并在本机安装适配版本的 `pybpa`。这两项不随仓库分发。真实运行时在页面切换到真实接口模式（或使用 `?mock=0`）。

PDF 导出需要本机安装 MiKTeX/XeLaTeX；DOCX 导出和网页编辑不需要 LaTeX。

## 项目结构

```text
powergrid_pipeline/       统一 Flask 服务、规划算法和 DSP/BPA 仿真流程
dianwang_report_gen/      比选报告生成、校验、编辑与导出
frame_fore-end_design/    前端页面及本地 Markdown/公式渲染依赖
tests/                    前端功能回归测试
AI_CONTEXT/               架构、数据流、业务规则与验证说明
```

统一入口为 `powergrid_pipeline/bridge_server.py`。它托管前端，调度规划任务，并将报告 API 加载在同一进程中。服务默认只监听本机 `127.0.0.1`；需要调整时可设置 `HOST` 和 `PORT` 环境变量。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests dianwang_report_gen\tests
```

规划算法中的仿真脚本需要真实 BPA/DSP 环境和电网模型输入，普通克隆环境无法执行真实仿真。网页 Mock 演示不依赖电网样例数据。

## 数据与密钥

上传的模型、规划运行结果、报告输出、虚拟环境和本地 `.env` 均保存在本机，不纳入版本控制。公开仓库仅保留源代码、通用模板和启动说明。请在本机配置真实密钥与仿真路径，不要提交这些内容。
