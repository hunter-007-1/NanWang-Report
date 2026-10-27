# PowerGrid Pipeline 后端说明

本目录是项目的后端部分，包含两层能力：

- `powergrid_pipeline_v2/`：电网规划算法流水线
- `bridge_server.py`：前后端桥接服务

如果你是第一次接手这个项目，建议优先把它理解成：

“算法脚本负责跑分析和生成，`bridge_server.py` 负责把这些结果包装成前端页面能直接消费的接口。”

## 1. 目录结构

```text
powergrid_pipeline/
├── README.txt
├── bridge_server.py
├── requirements.txt
├── fulfillment_scc_test/             # 示例基础模型与分析结果
├── fulfillment_scc/                  # 实际运行时输出目录（运行后生成）
└── powergrid_pipeline_v2/
    ├── main_cli.py
    ├── requirements.txt
    ├── config/
    │   └── settings.yaml
    ├── data/
    │   ├── base_models/
    │   ├── prompts/
    │   ├── proposals/
    │   └── context_v3.json
    ├── data_test/                    # bridge 上传落盘目录
    ├── functional_tests/
    │   └── main_scc.py               # 当前实际主流程入口
    ├── logs/                         # task 日志与进度
    └── src/
        ├── core/
        ├── services/
        ├── utils/
        └── cli/
```

## 2. 功能概览

### 算法流水线

`powergrid_pipeline_v2` 主要负责：

- 预处理：模型和上下文准备
- 初始分析：潮流、N-1、短路电流
- 方案生成：调用 LLM 生成候选改造方案
- 方案应用：将方案应用到基础模型
- 迭代评估：筛选并保留最优方案

### Bridge 服务

`bridge_server.py` 主要负责：

- 托管前端静态文件
- 接收前端上传的基础模型文件
- 创建任务并异步启动 `functional_tests/main_scc.py`
- 读取 `logs/task_xxx/` 下的日志和进度
- 汇总 `fulfillment_scc/run_*` 下的最终方案
- 向前端返回异常、方案详情和拓扑结构

## 3. 运行环境

建议环境：

- Python 3.11
- Windows 本地算法环境
- DSP/BPA 已正确安装
- `pybpa` 已可用

说明：

- `settings.yaml` 当前默认写的是 Windows 风格路径
- `main_scc.py` 中有部分硬编码路径更适合 Windows 环境
- 如果在 macOS/Linux 上做说明文档或前端联调可以，但要真正跑算法，通常仍需要对应的 BPA/DSP 环境

## 4. 依赖安装

先进入本目录：

```bash
cd powergrid_pipeline
```

再安装依赖：

```bash
pip install -r requirements.txt
```

根据代码实际 import，通常还需要补充：

```bash
pip install flask flask-cors pandas pyyaml
```

另外：

- `pybpa` 往往需要通过本地 wheel 安装
- `requirements.txt` 中已有被注释掉的 `pybpa` 安装示例，可按本机环境调整

## 5. 配置说明

配置文件：

- `powergrid_pipeline_v2/config/settings.yaml`

重点字段：

- `paths.dsp_bin_dir`：DSP/BPA Bin 目录
- `api.modelscope_api_key`：模型调用密钥
- `api.modelscope_base_url`
- `api.llm_model_name`
- `assessment_thresholds.overload_ratio`
- `assessment_thresholds.short_circuit_current_kA`
- `simulation_params.power_flow_mode`

## 6. 推荐启动方式

### 6.1 启动 bridge 服务

这是当前前后端联调的标准入口：

```bash
cd powergrid_pipeline
python bridge_server.py
```

服务启动后：

- 默认地址：`http://127.0.0.1:8080`
- 首页会直接返回前端 Demo

### 6.2 直接运行算法主流程

```bash
cd powergrid_pipeline
python powergrid_pipeline_v2/functional_tests/main_scc.py <base_model.dat> [target_count]
```

示例：

```bash
python powergrid_pipeline_v2/functional_tests/main_scc.py D:/models/yunnan_base.dat 3
```

参数：

- `base_model.dat`：基础模型 `.dat` 文件路径
- `target_count`：目标成功方案数，默认 `5`

环境变量：

- `PROGRESS_FILE`：写入进度 JSON 的文件路径
- `TARGET_SCHEME_COUNT`：目标方案数

## 7. `bridge_server.py` 工作方式

`bridge_server.py` 启动后会做两类事：

### 7.1 托管前端

它会把静态目录指向仓库根下的：

- `../frame_fore-end_design`

因此访问 `/` 时会返回前端首页，访问 CSS/JS 时也由 Flask 直接提供。

### 7.2 管理任务

当调用 `POST /api/tasks` 时，它会：

1. 校验 `baseModelPath`
2. 创建 `task_<timestamp>` 任务 ID
3. 在 `powergrid_pipeline_v2/logs/task_xxx/` 下创建日志目录
4. 启动 `powergrid_pipeline_v2/functional_tests/main_scc.py`
5. 通过 `progress.json` 和 `main_scc.log` 向前端反馈执行状态

任务结束后，它会读取：

- `fulfillment_scc/run_*`

并自动构建：

- 最终方案摘要
- 改造动作统计
- 拓扑图节点和边
- 初始异常报告摘要

## 8. API 说明

### 文件上传

- `POST /api/files/upload`

说明：

- 支持多文件上传
- 文件会保存到 `powergrid_pipeline_v2/data_test/`
- 返回上传后的绝对路径，以及自动识别出的 `.dat` 主文件路径

### 创建任务

- `POST /api/tasks`

请求体关键字段：

- `baseModelPath`
- `targetSchemeCount`

### 查询日志与进度

- `GET /api/tasks/<taskId>/log`
- `GET /api/tasks/<taskId>/progress`
- `GET /api/tasks/<taskId>/status`

### 查询异常与结果

- `GET /api/tasks/<taskId>/anomalies`
- `GET /api/tasks/<taskId>/schemes?limit=n`
- `GET /api/tasks/<taskId>/schemes/<schemeId>`
- `GET /api/tasks/<taskId>/schemes/<schemeId>/topology`

## 9. 输出结果说明

### 初始分析结果

通常写入：

- `fulfillment_scc/analysis_1/pf_report_1.json`
- `fulfillment_scc/analysis_1/n1_report_1.json`
- `fulfillment_scc/analysis_1/scc_report_1.json`

### 每次成功运行

通常会保留：

- `fulfillment_scc/run_1/`
- `fulfillment_scc/run_2/`
- ...

每个 `run_*` 下可能包含：

- `result/proposal/*.json`
- `test_output_v*/generation/`
- `test_output_v*/application/`
- `test_output_v*/analysis_*/`

### 任务日志

保存在：

- `powergrid_pipeline_v2/logs/task_xxx/main_scc.log`
- `powergrid_pipeline_v2/logs/task_xxx/progress.json`

## 10. 关于 `USE_PRECOMPUTED_RESULTS`

`bridge_server.py` 中有一个开关：

- `USE_PRECOMPUTED_RESULTS = False`

含义：

- `False`：真实启动 `main_scc.py`
- `True`：不跑算法，直接读取已有结果目录给前端展示

这个模式很适合：

- 前端联调
- 演示环境
- 算法环境尚未就绪时的 UI 测试

## 11. 当前代码使用建议

从仓库现状看，建议优先使用这两个入口：

- `bridge_server.py`
- `powergrid_pipeline_v2/functional_tests/main_scc.py`

## 12. 相关文档

- 仓库总 README：`../README.md`
- 前端 README：`../frame_fore-end_design/README.md`
- 前端使用说明：`../frame_fore-end_design/前端使用说明.md`
