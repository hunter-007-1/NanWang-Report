## 数值引用格式（兼容模式）
**重要**：原始、可精确匹配的数值使用 `<claim>`；只有通过明确公式由一个或多个输入值计算得到的派生值才使用 `<calculate>`。若没有精确匹配 claim，原始数值必须保留为普通文本；不得用 `<calculate>` 包裹原始值复述。

### Claim 标签格式
```xml
<claim id="claim_id" source_path="文件路径" path_to_value="数据路径" policy="验证策略">数值</claim>
```

### 使用规则
1. 从下方 `相关 Claims 数据证据` 中找到与你要使用的原始数值对应的 claim。
2. 使用该 claim 的 `claim_id`、`source_path`、`path_to_value`、`policy`、`value`、`unit` 必须**整体来自同一条** retrieved_claim，禁止自行拼接不同证据的字段。
3. 生成 claim 标签前，必须核对 `claim_id`、`source_path`、`path_to_value`、`value` 和 `unit` 属于同一条证据。
4. 使用 `policy` 属性声明验证策略；原始数据使用 `exact`，仅小数位处理使用 `round(0)` / `round(1)` 等。
5. **标签内显示值必须与 claim 原始 `value` 在数值和单位上保持一致**；不得因为表格列标题是“亿元”就把元 claim 写成亿元数值。
6. **单位换算规则（强制）**：
   - 元 → 万元 / 亿元 时，禁止直接用原始元 claim 包裹换算后的数值。
   - 必须使用 `<calculate>` 明确写出换算，或引用已经完成单位换算的派生 claim。
   - 亿元换算统一公式：`亿元 = 元 / 100000000`；万元：`万元 = 元 / 10000`。
   - **禁止**把 `1.62` 亿元绑定到 `value=162000000` 元的 claim。
   - **禁止**仅通过 `round` 策略处理单位倍率换算；`round` 只处理小数位，不处理元/万元/亿元数量级转换。
   - 表格中的单位换算同样必须遵守上述规则。推荐经济表直接使用“元/元/年”并绑定 exact claim。
7. 当同一 `path_to_value` 的字符串中包含多个数字时，必须逐项核对 `claim_id` 对应的 `value`。例如 description 字段中同时出现轮次、方案号、建设投资、运维成本和年费用时，不得把轮次或方案号的 claim 用于建设投资或年费用。
8. 对从多个原始值计算得到的派生值，如 N-1 通过率、越限比例、年费用、差值、百分比换算、单位换算等，必须使用 `<calculate>`；除非 retrieved_claims 中明确存在同一派生结果的 claim，禁止用原始输入 claim 包裹派生结果。
9. `<calculate>` 必须包含真实计算公式，且 `output` 必须由 `input` 和 `formula` 推导得到。禁止使用 `formula: none`、`formula: 无`、`formula: 原样引用`、`formula: 直接引用` 或等价写法。
10. 排序名次、最优/最低/最高等判断如果只是比较表中已有数值，应以普通文本表达；需要展示排序依据时引用各原始值的 `<claim>`，不要把排序名次本身包装成 `<calculate>`。
11. 原始值复述的决策规则：有精确匹配 claim 时用 `<claim>`；没有精确匹配 claim 时写普通文本；不得把 `input` 与 `output` 相同且无公式的内容写成 `<calculate>`。

### 单位换算示例（正确）
原始建设投资为
`<claim id="000006" source_path="derived_metrics.json" path_to_value="schemes[0].metrics.construction_cost.value" policy="exact">162000000</claim>`元。
若需显示亿元：
`<calculate> input: construction_cost_yuan=162000000; input_source: construction_cost_yuan=claim_000006; formula: construction_cost_yi_yuan = construction_cost_yuan / 100000000; output: 1.62 </calculate>`

### 单位换算示例（错误，禁止）
`<claim id="000006" ... policy="round(2)">1.62</claim>亿元`

# 相关 Claims 数据证据
<retrieved_claims>
{retrieved_claims}
</retrieved_claims>

# Claim/Calculate 兼容要求
- 原始数值必须优先使用 `<claim>`；没有精确匹配 claim 时只能写普通文本，不得改用 `<calculate>`。
- `<claim>` 的属性必须从上面的 retrieved_claims 证据中精确拷贝，不得编造。复制属性前必须确认标签内数值与该 claim 的 `value` 匹配。
- IMPORTANT: keys like insight_0, insight_1 are retrieval group names, not claim IDs。
- Do not use insight_0, insight_1, or any insight_* value as a `<claim id>`。
- Only claim_id inside an element of a claims array is a valid `<claim id>`。
- If the matching claims array is empty or no exact claim_id is available, do not generate `<claim>`; keep raw numbers as plain text. Use `<calculate>` only when there is a real formula and the output is derived from the inputs.
- Derived values must not be wrapped with source-input claims. For example, do not wrap 93.15% N-1 pass rate with a total_contingencies_run=73 claim; use `<calculate>` with the real formula unless an exact 93.15 claim exists.
- Never emit `<calculate>` with `formula: none` or equivalent. A direct restatement such as `input: 5400000; output: 5400000` must be a `<claim>` when an exact claim exists, otherwise plain text.
- Do not use `<calculate>` for visual formatting, raw-value copying, or evidence fallback. Unit conversion is allowed only with an explicit `/100000000` or `/10000` formula.
- Never use placeholder claim IDs such as 未提供, 未知, N/A, none, null, or empty strings.
- claims 数组为空时不得生成 `<claim>`；只有 claims 数组元素里的 claim_id 才能作为 `<claim id>`；不得使用 insight_0 / insight_1 / insight_* / 未提供 / 未知 / N/A 作为 claim id。
