# 通用神经网络处理器核内调度算法研究 | NPU Operator Scheduler

[![Language](https://img.shields.io/badge/Language-Python-blue.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)
[![Award](https://img.shields.io/badge/Award-National%202nd%20Prize-red.svg)](#)

本工程是 **第二十二届中国研究生数学建模竞赛全国二等奖** 核心算法的实现源码。针对通用神经网络处理器（NPU）在执行复杂多维深度学习算子（如 Conv、Matmul、FlashAttention）时的多维存储和执行调度问题，设计并实现了拓扑排序、启发式优先级调度算法、数据溢出（Spill）成本动态优化算法以及内存碎片的图形化可视化分析系统。

This project is the core implementation of our award-winning work (National 2nd Prize in the 22nd China Graduate Mathematical Modeling Competition). It solves the multi-dimensional memory allocation and operation scheduling problems for deep learning operators on a Neural Processing Unit (NPU).

---

## 🌟 核心技术亮点 / Key Features

### 1. 计算图解析与拓扑排序 (Graph Analysis & Topological Sorting)
- **图依赖解析**：对复杂算子生成的数据流图 (Dataflow Graph, JSON 格式) 进行拓扑解析，深入分析数据块的生命周期 (Liveness Analysis) 和数据依赖关系。
- **算子调度编排**：设计多种拓扑遍历策略，在满足计算依赖的硬约束下，尽可能优化算子的并行度和局部性。

### 2. 优先级搜索与调度算法 (Priority Explorer)
- **多准则贪心启发式算法**：设计了基于依赖出度、数据块大小、关键路径权重等多维度指标的算子优先级分配器。
- **动态规划局部剪枝**：利用高效的剪枝搜索策略寻找最优的调度顺序，以最小化整体计算周期 (Cycles) 延迟。

### 3. 数据溢出 (Spill) 与内存碎片优化 (Spill Cost Optimization)
- **Spill 策略最小化**：在 NPU 有限的片上高速缓存 (L1 / UB) 物理容量约束下，当数据量溢出时，基于最小换入换出代价动态决定哪些数据块溢出到主存 (L3 DDR)。
- **内存块分配算法**：实现高效的一维内存段分配算法，极大降低内存碎片率与 Cache Miss 率。

### 4. 交互式可视化分析 GUI (Interactive Visualization GUI)
- **内存布局热力图**：基于 Python tkinter / matplotlib 开发了交互式调度验证器，能够动态输出内存碎片的时空占用热力图、执行时间甘特图以及 Spill 成本折线图。
- **验证与基准测试**：提供自动化验证脚本，能对生成的调度序列进行完整性和可行性检查。

---

## 📂 项目结构 / Directory Structure

```text
NPU-Operator-Scheduler/
├── data_generation/                    # 神经网络算子数据生成与分析 / Data generators for DL ops
│   ├── Conv_Case*.json                 # 卷积算子计算图数据样例 / Conv graph samples
│   ├── Matmul_Case*.json               # 矩阵乘法算子计算图数据样例 / Matmul graph samples
│   ├── FlashAttention_Case*.json       # 注意力机制算子计算图数据样例 / FlashAttention samples
│   └── data_analysis.py                # 原始数据流图结构特征统计 / Dataflow graph statistics script
│
├── problem_1_priority_scheduler/      # 第一问：基于优先级的单核调度算法 / Problem 1 scheduler
│   ├── priority_explorer.py            # 核心启发式优先级搜索器 / Heuristic priority searcher
│   ├── interactive_scheduler_gui.py    # 可视化调度验证与展示 GUI / Tkinter GUI validator
│   ├── plot_max_L1_UB.py               # L1/UB缓存限制与周期折线图绘制 / L1/UB cycle plotter
│   └── schedule_validator.py           # 调度方案合法性检验脚本 / Schedule validator
│
├── problem_2_spill_optimizer/         # 第二问：带 Spill 优化的数据局部性调度 / Problem 2 spill optimizer
│   ├── main.py                         # 算子调度与 Spill 混合决策核心 / Spill decision engine
│   ├── spill_visualization.py          # 溢出代价与空间动态分布图谱 / Spill cost plotter
│   ├── detailed_address_analysis.py    # 内存详细编址与碎片率统计 / Memory segment compiler
│   └── validator.py                    # 溢出控制合法性检查器 / Spill validator
│
└── problem_3_multi_core_scheduler/     # 第三问：多核异构处理器下的并行调度 / Problem 3 multi-core scheduler
    ├── problem3_optimization.py        # 多核算子分割与调度分配引擎 / Multi-core partitioning scheduler
    ├── calculate_spill_cost.py         # 多核溢出成本评估模型 / Multi-core spill cost evaluator
    └── visualization_comparison.py     # 多维度性能指标对比可视化 / Performance comparator
```

---

## 🚀 快速运行演示 / Getting Started

### 1. 安装可视化依赖
```bash
pip install matplotlib numpy pandas
```

### 2. 运行第一问的交互式可视化 GUI
进入 `problem_1_priority_scheduler` 文件夹并运行主界面：
```bash
cd problem_1_priority_scheduler
python interactive_scheduler_gui.py
```
这会弹出一个交互式窗口，展示 Conv 和 Matmul 算子各层节点的内存分配曲线和拓扑执行甘特图。

### 3. 运行第二问 Spill 算法与验证
```bash
cd problem_2_spill_optimizer
python main.py
```
程序将读取 `data_generation` 中的复杂算子大包数据，自动计算最优的 Spill 地址段规划，并输出执行总延迟。
