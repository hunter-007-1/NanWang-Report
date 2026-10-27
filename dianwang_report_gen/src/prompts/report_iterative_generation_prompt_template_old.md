# 任务
你的任务是根据`大纲`将`洞察`和`数据表格`组织起来，生成一份结构完整、逻辑清晰的工程可研报告。

# 任务细节

## 内容
- 根据大纲的需要保留`数据表格`中的内容：将输入中的内容整理后按照报告模板的要求保留在报告中，尽量不进行任何修改或解释。
- 叙述连贯性：报告内容必须使用流畅、专业的中文工程语言，保持各部分之间的逻辑连贯。
- 洞察整合：洞察是对输入内容的分析和总结，需要根据洞察组织语言然后在报告中进行展示。
- 大纲中的每一个项目分点对应生成一个或多个段落，避免使用分点直接展示。
- 如果地点之间用波浪号`~`连接，在输出时添加转义符`\~`，避免与Markdown的链接语法冲突。
- 只需要根据输入的内容进行分析，不需要自己生成数据。即使大纲模板中要求展示某些内容的数据，也只需要根据输入的内容进行展示。

## 数值引用格式
**重要**：当报告中使用数值时，必须使用 `<claim>` 标签包裹数值，以提供数据溯源和验证能力。

### Claim 标签格式
```xml
<claim id="claim_id" source_path="文件路径" path_to_value="数据路径" policy="验证策略">数值</claim>
```

### 使用规则
1. **查找对应 Claim**：从下方 `相关 Claims 数据证据`（JSON 格式）中找到与你要使用的数值对应的 claim
2. **复制属性**：使用该 claim 的 `claim_id`、`source_path` 和 `path_to_value` 属性
3. **声明验证策略**：使用 `policy` 属性声明验证策略（见下方策略说明）
4. **包裹数值**：将数值用 `<claim>` 标签包裹，保留原数值不变

### 验证策略（policy）说明
`policy` 属性声明该数值的验证方式，支持以下策略：

| 策略 | 格式 | 说明 | 示例 |
|------|------|------|------|
| 精确匹配 | `exact` | 数值必须完全一致 | `<claim policy="exact">12.34</claim>` |
| 四舍五入 | `round(d)` | 四舍五入到d位小数后匹配 | `<claim policy="round(1)">12.3</claim>` |

**策略选择建议**：
- 使用原始数据时：**`exact`**（默认，可省略）
- 取整后的数值：**`round(0)`**（整数）或 **`round(1)`**（1位小数）

### 示例
假设相关 Claims 数据中包含：
```json
{{
  "insight_0": {{
    "insight": "系统潮流分析显示损耗较低",
    "claims": [
      {{
        "claim_id": "00001",
        "indicator": "损耗_MW",
        "value": 12.34,
        "source_path": "analysis_1/pf_report_1.json",
        "path_to_value": "analysis.power_summary[0].损耗_MW"
      }}
    ]
  }}
}}
```

在报告中使用该数值时应写成：
```markdown
系统的损耗为 <claim id="00001" source_path="analysis_1/pf_report_1.json" path_to_value="analysis.power_summary[0].损耗_MW" policy="exact">12.34</claim> MW。
```

如果使用四舍五入值：
```markdown
系统的损耗约为 <claim id="00001" source_path="analysis_1/pf_report_1.json" path_to_value="analysis.power_summary[0].损耗_MW" policy="round1">12.3</claim> MW。
```

### 注意事项
- **必须使用**：所有从数据表格和洞察中引用的数值都必须使用 `<claim>` 标签
- **精确匹配**：从 `相关 Claims 数据证据` 中精确匹配 claim，不要自己编造属性
- **策略声明**：根据数值的实际情况声明合适的验证策略
- **保持原值**：标签内的数值必须与 claim 中的 value 在声明的策略下匹配
- **JSON 格式**：Claims 数据以 JSON 格式提供，包含完整的 claim_id、source_path、path_to_value 等信息

## 表格
- 在需要展示表格的地方，使用下面提供的`Pandoc表格语法`组织表格数据，确保表格的可读性和专业性。
- 每个表格都应该新起一段；每个表格都应该与其他内容用空行隔开。

## 可视化
- 占位符：在需要展示可视化图表的地方，加入一个“可视化占位符”`<visualization>...</visualization>`。每个可视化占位符还应建议一个该图表所支持或解释的叙事元素。
- 标签中应该包含全部数据：可视化占位符中的标签应包含图表所需的所有数据，避免在标签中使用占位符或自己生成数据。
- 信息：可视化占位符必须包含有关该图表的必要信息，例如：
    - 图表标题（英文）
    - 图表类型
    - x轴和y轴标签（中文）
    - x轴和y轴的数据值等。
- 标签：可视化图表必须位于一对 `<visualization></visualization>` 标签之间。
- 在可视化标签后会由外部添加`<visualization_result></visualization_result>`标签，用于展示可视化图表。你需要根据结果继续组织报告内容。

# Pandoc表格语法
请参考以下Pandoc表格语法文档，确保输出的markdown表格的语法符合下面的格式：
<pandoc_tables_syntax>
{pandoc_tables_syntax}
</pandoc_tables_syntax>

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

# 相关 Claims 数据证据
<retrieved_claims>
{retrieved_claims}
</retrieved_claims>

# 输出格式
- 直接以Markdown格式输出报告，不要添加任何额外的解释或说明。
- 分段书写，不要使用分点。