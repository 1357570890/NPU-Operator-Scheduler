# 数据结构分析工具

这是一个用于分析JSON格式数据结构文件的Python工具，可以生成各种统计图表和分析报告。

## 功能特性

- 📊 **操作统计分析**：统计各种操作类型（ALLOC、COPY_IN等）的分布
- 📈 **内存使用分析**：分析内存使用情况和类型分布
- 🔄 **图结构分析**：计算节点的入度和出度，分析图的拓扑结构
- 📋 **缓冲区分析**：分析缓冲区大小分布
- 📊 **周期分析**：分析操作的周期信息
- 🎨 **可视化图表**：生成直方图、饼状图、散点图等
- 📄 **综合报告**：生成详细的分析报告

## 数据格式

程序期望的JSON文件格式：

```json
{
  "Nodes": [
    {
      "Id": 0,
      "Op": "ALLOC",
      "BufId": 0,
      "Size": 1,
      "Type": "L1"
    },
    {
      "Id": 1,
      "Op": "COPY_IN",
      "Pipe": "MTE2",
      "Cycles": 80,
      "Bufs": [2]
    }
  ],
  "Edges": [
    [0, 10],
    [1, 5]
  ]
}
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本使用

```bash
python data_analysis.py
```

### 自定义输出目录

```python
from data_analysis import DataStructureAnalyzer

analyzer = DataStructureAnalyzer()
analyzer.run_complete_analysis("my_analysis_output")
```

### 单独使用分析功能

```python
analyzer = DataStructureAnalyzer()

# 加载数据
analyzer.load_data()

# 分析操作类型
op_stats = analyzer.analyze_operations()
print("操作统计:", op_stats)

# 分析内存使用
memory_info = analyzer.analyze_memory_usage()
print("内存使用:", memory_info)

# 生成图表
analyzer.generate_operation_charts(op_stats, "charts")
```

## 输出结果

程序会生成以下输出：

1. **操作统计图表** (`operation_stats.png`)
   - 饼状图：操作类型分布
   - 直方图：操作类型统计

2. **内存分析图表** (`memory_analysis.png`)
   - 内存类型分布饼状图
   - 内存类型使用直方图
   - 缓冲区大小分布直方图
   - 节点度数分布直方图

3. **度数分析图表** (`degree_analysis.png`)
   - 入度分布直方图
   - 出度分布直方图
   - 入度vs出度散点图

4. **分析报告** (`analysis_report.txt`)
   - 基本信息统计
   - 操作类型统计
   - 内存使用统计
   - 度数统计
   - 周期信息

## 分析指标

- **操作类型统计**：统计各种操作（ALLOC、FREE、COPY_IN等）的数量
- **内存使用统计**：按类型统计内存使用量
- **图结构分析**：计算节点的入度和出度
- **缓冲区分析**：分析缓冲区大小分布
- **周期分析**：统计操作的执行周期

## 技术特点

- 支持中文显示
- 高分辨率图表输出（300 DPI）
- 自动创建输出目录
- 详细的错误处理
- 模块化设计，易于扩展

## 系统要求

- Python 3.6+
- matplotlib
- numpy
- seaborn

## 作者

数据结构分析工具 v1.0