#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据结构分析工具
用于分析JSON格式的数据结构文件，为每个文件生成独立的统计图表和分析报告。
"""

import json
import os
import glob
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Tuple, Any
import seaborn as sns

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号


class DataStructureAnalyzer:
    """数据结构分析器"""

    def __init__(self, data_dir: str = "."):
        """
        初始化分析器
        Args:
            data_dir: 数据文件目录
        """
        self.data_dir = data_dir
        self.json_files: List[str] = []
        self.data_by_file: Dict[str, Dict[str, Any]] = {}

    def find_json_files(self) -> List[str]:
        """查找所有JSON文件"""
        json_files = sorted(glob.glob(os.path.join(self.data_dir, "*.json")))
        self.json_files = json_files
        return json_files

    def load_data(self) -> bool:
        """
        加载所有JSON文件的数据, 按文件分别存储
        """
        if not self.json_files:
            self.find_json_files()

        if not self.json_files:
            print("未找到任何JSON文件。")
            return False

        print("开始加载数据文件...")
        for json_file in self.json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                filename = os.path.basename(json_file)
                nodes = data.get('Nodes', [])
                edges = data.get('Edges', [])
                
                self.data_by_file[filename] = {
                    'nodes': nodes,
                    'edges': edges,
                }
                print(f"  - 成功加载: {filename} (节点: {len(nodes)}, 边: {len(edges)})")

            except Exception as e:
                print(f"  - 加载文件失败 {json_file}: {e}")
        
        if not self.data_by_file:
            print("没有成功加载任何文件。")
            return False
            
        return True

    def analyze_operations(self, nodes: List[Dict]) -> Dict[str, int]:
        """分析单个文件的操作类型统计"""
        op_counter = Counter(node.get('Op', 'UNKNOWN') for node in nodes)
        return dict(op_counter)

    def analyze_memory_usage(self, nodes: List[Dict]) -> Dict[str, Any]:
        """分析单个文件的内存使用情况"""
        memory_by_type = defaultdict(int)
        total_memory = 0
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                size = node.get('Size', 0)
                mem_type = node.get('Type', 'UNKNOWN')
                memory_by_type[mem_type] += size
                total_memory += size
        return {
            'total_memory': total_memory,
            'memory_by_type': dict(memory_by_type)
        }
    
    def analyze_buffer_sizes(self, nodes: List[Dict]) -> Dict[str, List[int]]:
        """分析缓冲区大小分布"""
        buffer_sizes = defaultdict(list)
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                size = node.get('Size', 0)
                mem_type = node.get('Type', 'UNKNOWN')
                buffer_sizes[mem_type].append(size)
        return dict(buffer_sizes)

    def calculate_degrees(self, edges: List[List[int]]) -> Tuple[Dict[int, int], Dict[int, int]]:
        """计算节点的入度和出度"""
        in_degree = defaultdict(int)
        out_degree = defaultdict(int)
        
        edge_dict = defaultdict(list)
        for edge in edges:
            if len(edge) >= 2:
                from_node, to_node = edge[0], edge[1]
                edge_dict[from_node].append(to_node)

        for from_node, to_nodes in edge_dict.items():
            out_degree[from_node] = len(to_nodes)
            for to_node in to_nodes:
                in_degree[to_node] += 1
        return dict(in_degree), dict(out_degree)

    def generate_operation_charts(self, op_stats: Dict[str, int], filename_prefix: str, save_path: str):
        """为单个文件生成操作统计图表"""
        plt.figure(figsize=(12, 6))
        
        labels = list(op_stats.keys())
        sizes = list(op_stats.values())
        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))

        # 饼状图
        plt.subplot(1, 2, 1)
        if sizes:
            plt.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        plt.title('操作类型分布')

        # 直方图
        plt.subplot(1, 2, 2)
        bars = plt.bar(range(len(labels)), sizes, color=colors)
        plt.xlabel('操作类型')
        plt.ylabel('数量')
        plt.title('操作类型统计')
        plt.xticks(range(len(labels)), labels, rotation=45, ha='right')
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, yval, int(yval), va='bottom') # va: vertical alignment

        plt.suptitle(f'文件: {filename_prefix}', fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(os.path.join(save_path, f'{filename_prefix}_operation_stats.png'), dpi=300)
        plt.close()

    def generate_memory_charts(self, memory_info: Dict, buffer_sizes: Dict, degrees: Tuple, filename_prefix: str, save_path: str):
        """为单个文件生成内存和度数图表"""
        plt.figure(figsize=(12, 10))

        # 内存类型分布饼状图
        plt.subplot(2, 2, 1)
        memory_by_type = memory_info['memory_by_type']
        if memory_by_type:
            plt.pie(memory_by_type.values(), labels=memory_by_type.keys(), autopct='%1.1f%%', startangle=90)
        plt.title('内存类型分布')

        # 缓冲区大小分布
        plt.subplot(2, 2, 2)
        for mem_type, sizes in buffer_sizes.items():
            sns.histplot(sizes, bins=20, kde=True, label=mem_type)
        plt.title('缓冲区大小分布')
        plt.xlabel('缓冲区大小 (Bytes)')
        plt.ylabel('频次')
        if buffer_sizes:
            plt.legend()

        # 入度分布
        in_degree, _ = degrees
        plt.subplot(2, 2, 3)
        if in_degree:
            sns.histplot(list(in_degree.values()), bins=30, kde=True, color='skyblue')
        plt.title('节点入度分布')
        plt.xlabel('入度')
        plt.ylabel('节点数量')

        # 出度分布
        _, out_degree = degrees
        plt.subplot(2, 2, 4)
        if out_degree:
            sns.histplot(list(out_degree.values()), bins=30, kde=True, color='salmon')
        plt.title('节点出度分布')
        plt.xlabel('出度')
        plt.ylabel('节点数量')

        plt.suptitle(f'文件: {filename_prefix}', fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(os.path.join(save_path, f'{filename_prefix}_memory_degree.png'), dpi=300)
        plt.close()

    def generate_report_for_file(self, filename: str, data: Dict) -> str:
        """为单个文件生成分析报告"""
        nodes = data['nodes']
        edges = data['edges']
        
        report = []
        report.append("=" * 60)
        report.append(f"数据结构分析报告: {filename}")
        report.append("=" * 60)

        # 基本信息
        report.append("\n1. 基本信息:")
        report.append(f"   - 节点数: {len(nodes)}")
        report.append(f"   - 边数: {len(edges)}")

        # 操作统计
        report.append("\n2. 操作类型统计:")
        op_stats = self.analyze_operations(nodes)
        for op, count in sorted(op_stats.items()):
            report.append(f"   - {op}: {count}")

        # 内存使用
        report.append("\n3. 内存使用统计:")
        memory_info = self.analyze_memory_usage(nodes)
        report.append(f"   - 总内存使用: {memory_info['total_memory']} Bytes")
        for mem_type, size in memory_info['memory_by_type'].items():
            report.append(f"   - {mem_type}: {size} Bytes")

        # 度数统计
        report.append("\n4. 度数统计:")
        in_degree, out_degree = self.calculate_degrees(edges)
        if in_degree or out_degree:
            in_values = list(in_degree.values())
            out_values = list(out_degree.values())
            report.append(f"   - 平均入度: {np.mean(in_values):.2f}" if in_values else "0.00")
            report.append(f"   - 最大入度: {max(in_values) if in_values else 0}")
            report.append(f"   - 平均出度: {np.mean(out_values):.2f}" if out_values else "0.00")
            report.append(f"   - 最大出度: {max(out_values) if out_values else 0}")
        else:
            report.append("   - 无边数据，无法计算度数。")
            
        report.append("\n" + "=" * 60 + "\n")
        return "\n".join(report)

    def run_complete_analysis(self, output_dir: str = "analysis_output"):
        """
        为找到的每个JSON文件运行完整的独立分析
        """
        print("开始数据结构分析...")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"创建输出目录: {output_dir}")

        if not self.load_data():
            print("数据加载失败，分析中止。")
            return

        print("\n开始为每个文件生成分析结果...")
        for filename, data in self.data_by_file.items():
            print(f"--- 正在处理文件: {filename} ---")
            filename_prefix = os.path.splitext(filename)[0]

            # 分析
            nodes = data['nodes']
            edges = data['edges']
            op_stats = self.analyze_operations(nodes)
            memory_info = self.analyze_memory_usage(nodes)
            buffer_sizes = self.analyze_buffer_sizes(nodes)
            degrees = self.calculate_degrees(edges)

            # 生成图表
            print("  - 生成图表...")
            self.generate_operation_charts(op_stats, filename_prefix, output_dir)
            self.generate_memory_charts(memory_info, buffer_sizes, degrees, filename_prefix, output_dir)

            # 生成报告
            print("  - 生成报告...")
            report_content = self.generate_report_for_file(filename, data)
            report_file = os.path.join(output_dir, f"{filename_prefix}_report.txt")
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
        
        print("\n" + "="*40)
        print("所有文件分析完成！")
        print(f"结果已保存在目录: {output_dir}")
        print("="*40)


def main():
    """主函数"""
    analyzer = DataStructureAnalyzer()
    analyzer.run_complete_analysis()


if __name__ == "__main__":
    main()