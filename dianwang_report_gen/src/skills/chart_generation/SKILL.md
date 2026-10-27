## 任务
你的任务是根据下面提供的描述，生成一段可执行的、用于 Matplotlib 可视化的 Python 代码。

## 要求
- 代码必须是自包含的、可执行的，并且**只**能导入 `matplotlib.pyplot` 库用于绘图。
- 可视化图表必须准确、有效地展示 `可视化描述` 中提到的数据、关键发现和趋势。
- 使用 `可视化描述` 中提供的*具体数据*，不能自己生成数据。
- 所有一同使用的数据数组（例如 X 轴和 Y 轴的数据）必须具有兼容的长度。
- 最终代码中**不得**包含 `plt.show()`。
- *严格*遵守 `输出格式` 模板，包括其中的注释。
- 在编写 Matplotlib 代码时，请注意：不要假定所有类都在 `matplotlib.pyplot (plt)` 下。特殊图表（如 Sankey、Animation 等）必须从其子模块显式导入。错误示例：`sankey = plt.Sankey(...)`。正确要求：从 `matplotlib.sankey` 子模块导入 `Sankey` 类，然后使用 `sankey = Sankey(...)`。

## 可视化描述
```markdown
{visualization_description}
```

## 输出格式
在一个 Markdown 代码块中生成 Python 代码。严格遵循此模板：
```python
# 导入必要的库，如：
# import matplotlib.pyplot as plt

# 定义图表标题（使用英文标题）
chart_title = "The title of the chart"

# 数据：描述用于生成可视化的所有数值数据和文本元素。
# 使用可视化描述中提供的具体数据，不能自己生成数据。
# 示例：
# x_data = [1, 2, 3]
# y_data = [10, 20, 15]

# 整体布局：详细说明子图的构成及其空间排列。示例：
# fig, ax = plt.subplots()

# 标记：描述每个视觉元素的设计规格。
# 示例：
# ax.bar(x_data, y_data) # Example: Bar Chart
# ax.plot(x_values, y_values)  # Example: Line Chart
# ax.scatter(x_values, y_values) # Example: Scatter Plot

# 绘图比例：描述每个数据到视觉的映射（如位置、颜色）的缩放逻辑及其注释。
# 包括但不限于：数据范围、坐标轴比例、颜色映射、透明度、大小缩放等。
# 示例：
# ax.set_title(chart_title)
# ax.set_xlim()
# ax.set_ylim()
# ax.set_xticks()
# ax.set_yticks()
# ax.set_xlabel("X轴的标签名")
# ax.set_ylabel("Y轴的标签名")
# ax.tick_params()
# ax.legend()
# ax.grid(True)
```