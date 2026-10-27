# 任务
你的任务是根据`大纲`将`洞察`和`数据表格`组织起来，生成一份结构完整、逻辑清晰的工程可研报告。


## 数值计算规范
- **重要**：报告中凡是涉及计算过程或结果的数值，必须使用 `<calculate></calculate>` 标签包裹。
- **严格格式**：`<calculate>` 是固定开始标签，必须原样写出完整的 `>`；所有字段必须写在标签内容中，不得写在开始标签内。
- **标签属性要求**：
    - `input`: 计算用的原始数据。
    - `input_source`: 原始数据的出处。
    - `formula`: 必须写出该数值的计算公式或公式组，描述如何从输入数据计算到输出结果（推荐使用 LaTeX 格式）。
    - `output`: 最终计算得到的数字结果。
- **标识案例**：
    <calculate> input: construction_cost=108000000; operation_cost=5400000; i=0.07; n=20; input_source: construction_cost=claim_000001; operation_cost=claim_000002; i=compare_rules.metrics.annual_cost.default_inputs.interest_rate; n=compare_rules.metrics.annual_cost.default_inputs.years; formula: construction_cost * i*(1+i)**n / ((1+i)**n - 1) + operation_cost; output: 15594435.98 </calculate>
- **乘方语法**：`<calculate>` 标签内的 `formula` 必须使用 Python 乘方语法 `**`（如 `(1+i)**n`）；中文说明中可保留数学记号 `^`，但标签内不得使用 `^`。
- **禁止格式**：不得输出 `<calculate input: ... </calculate>`、`<calculate input_source: ...>`、`<calculate formula: ...>` 等把字段写进开始标签的形式；这些都是非法格式。


## 表格
- 在需要展示表格的地方，使用下面提供的`Pandoc表格语法`组织表格数据，确保表格的可读性和专业性。
- 每个表格都应该新起一段；每个表格都应该与其他内容用空行隔开。

# Pandoc表格语法
请参考以下Pandoc表格语法文档，确保输出的markdown表格的语法符合下面的格式：
<pandoc_tables_syntax>
{pandoc_tables_syntax}
</pandoc_tables_syntax>

# 工程背景与接入方案原始资料
<background_context>
{background_context}
</background_context>

## 背景资料使用规则
1. 如果背景资料非空，必须视为有效工程输入；不得因仿真节点命名不同而判定“未提供”。
2. “周边500kV电网接入点分析”必须综合使用背景资料、方案数据表、潮流结果、N-1校验结果、短路电流结果和 retrieved_claims 中可核验的真实数据。可以说明周边500kV相关节点、相关线路、电压等级、短路电流水平、断路器开断能力、N-1故障表现和潮流运行情况；不得仅因缺少地理资料而将整个章节写成“无法分析”。
3. 当短路电流结果存在 bus_name、short_circuit_current_kA、breaker_current_kA 等字段时，应选择具有代表性的关键节点进行定量分析；当N-1结果存在故障线路、过载线路和负载率时，应说明相关线路的N-1运行表现。引用具体数值必须遵守现有 `<claim>` 与 `<calculate>` 溯源规则。
4. 仿真报告中的普通故障节点不得直接表述为已经确定的候选接入点，应称为“周边500kV相关节点”或“重点关注节点”。
5. “接入系统方案拟定”优先依据背景资料中的方案思路与拟定方案；仿真 modifications/数据表用于补充真实接线与长度。二者命名不一致时，分别说明来源，不要互相覆盖，也不要因此整节留空。
6. 方案线路和节点信息必须优先使用 parsed_proposals.json 中真实存在的 modifications 数据。
7. 地理位置、站址距离、备用间隔、线路走廊和建设条件只能依据背景资料中的真实内容生成，不得根据电气仿真结果推断或编造。
8. 当背景资料为空但方案数据表、潮流、N-1或短路电流结果存在时，仍须生成电气层面的周边网架和方案分析。仅对输入中确实不存在的地理位置、距离、备用间隔、走廊及建设条件等子项标记“当前输入不足，未提供该项资料”。
9. 不得把方案生成指令、经济指标摘要直接当成接入点分析正文，但可以从中提取明确给出的工程目标、目标节点和约束条件，并注明其属于任务输入。
10. **禁止过度推断**：“具备物理连接条件”仅当 modifications 确实包含对应新增线路时才可使用；“位于重载区域附近/适合作为接入对象”仅当输入明确给出地理或电气邻近关系时才可使用。

## Claim 单位与属性规则（强制）
1. claim 标签内显示值必须与 claim 原始 value/unit 一致。
2. 元→万元/亿元必须用 `<calculate>`（亿元=元/100000000），禁止把亿元数值绑到元 claim；禁止用 round 处理数量级换算。
3. claim_id/source_path/path_to_value/policy/value/unit 必须整体来自同一条证据，禁止拼接。
4. 经济表优先展示元并绑定 exact claim。

## 安全硬约束与最终推荐（强制）
1. 安全硬约束优先于经济排序。
2. 短路电流超断路器能力、最小断路器开断裕度率<0、基态不收敛等任一硬约束失败时，该方案不得成为最终推荐。
3. 全部方案均失败时：写明无可直接推荐实施的方案，仅可给出整改后经济优先候选；禁止“共性问题不影响推荐”。

# 大纲
<outline>
{outline}
</outline>

# 数据表格
<data_tables>
{data_tables}
</data_tables>

# 洞察
<insights>
{insights}
</insights>

# 输出格式
- 直接以Markdown格式输出报告，按照要求解释计算结果。
- 分段书写，不要使用分点。

## Markdown 安全规则
- 当普通比较符号 `>` 或 `<` 出现在列表项、表格单元格或一行文本的开头时，必须转义为 `\>` / `\<`，或改写为中文“大于/小于”，避免被 Markdown 解析为引用块或 HTML 标签。
- 正确示例：`- \>95%：可用良好；`、`- \<90%：风险较高；`。
- 禁止示例：不得直接写成 `- >95%：可用良好；`，因为 `>` 会被 Markdown 当作引用块标记吞掉。
