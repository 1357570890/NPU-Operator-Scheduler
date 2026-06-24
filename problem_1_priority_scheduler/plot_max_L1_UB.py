# -*- coding: utf-8 -*-
"""
绘制 max(L1 + UB) 的散点图
- 读取节点定义文件（默认：1.json，包含 Nodes 列表）
- 读取调度序列文件（默认：2.json，按行或JSON数组均支持，包含节点Id的顺序）

用法示例：
    python plot_max_L1_UB.py --nodes 1.json --schedule 2.json --out max_L1_UB.png

生成结果：
- 保存并显示一个散点图，横轴为调度步（节点序号在序列中的位置），纵轴为当前时刻 L1+UB 缓存驻留大小。
- 在图上标注最大值及其出现的位置。

本脚本对输入格式有基本鲁棒性：
- 如果调度文件中存在不是整数的行，会尝试从文本中抽取所有整数作为节点Id序列。
- 如果在调度过程中遇到无法识别的 FREE 节点（无 BufId），会尝试从节点的 "Bufs" 字段中寻找要释放的缓冲区。

注意：按题目定义，仅把 ALLOC 计入驻留、FREE 计入释放；其它操作（MOVE/COPY 等）不改变驻留总量。
"""

from __future__ import annotations
import json
import re
import argparse
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt
import os
import numpy as np


def load_nodes(nodes_path: str) -> Dict[int, dict]:
    """从 nodes JSON 文件中读取并返回 id->node 映射。"""
    with open(nodes_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 支持两种结构：{"Nodes": [...]} 或直接 [...]
    if isinstance(data, dict) and 'Nodes' in data:
        nodes_list = data['Nodes']
    elif isinstance(data, list):
        nodes_list = data
    else:
        raise ValueError('无法识别的节点文件结构：应为包含 "Nodes" 的对象或节点数组')

    nodes = {}
    for n in nodes_list:
        if 'Id' not in n:
            continue
        nodes[int(n['Id'])] = n
    return nodes


def load_schedule(schedule_path: str) -> List[int]:
    """读取调度文件。支持纯数字行、文本中提取整数或 JSON 数组。"""
    with open(schedule_path, 'r', encoding='utf-8') as f:
        txt = f.read()

    # 试着解析为 JSON（JSON数组）
    try:
        parsed = json.loads(txt)
        if isinstance(parsed, list) and all(isinstance(x, int) for x in parsed):
            return parsed
    except Exception:
        pass

    # 否则按行解析：每行可能是一个整数，或者整个文件是多个整数换行的形式
    ids: List[int] = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        # 直接尝试把行转换成整数
        if re.fullmatch(r"-?\d+", line):
            ids.append(int(line))
            continue
        # 否则从行中抽取所有整数
        found = re.findall(r"-?\d+", line)
        if found:
            ids.extend(int(x) for x in found)

    # 如果仍为空，作为备份尝试从整个文本抽取整数
    if not ids:
        found_all = re.findall(r"-?\d+", txt)
        ids = [int(x) for x in found_all]

    return ids


def compute_L1_UB_over_time(nodes: Dict[int, dict], schedule: List[int]) -> Tuple[List[int], List[str], int, int]:
    """遍历调度序列，返回每一步的 L1+UB 大小列表、每一步操作类型列表，以及最大值与最大值出现的索引。

    规则：仅处理 ALLOC 增加驻留，FREE 减少驻留。只有 Type 为 'L1' 或 'UB' 的 ALLOC/ FREE 会影响统计。
    同时返回每一步的操作名用于绘图时按操作上色。
    """
    current_bufs: Dict[int, Tuple[int, str]] = {}  # BufId -> (Size, Type)
    sizes_over_time: List[int] = []
    ops_over_time: List[str] = []
    current_sum = 0

    for step_idx, node_id in enumerate(schedule):
        node = nodes.get(node_id)
        if node is None:
            # 如果节点在 nodes 文件中找不到，忽略并记录当前值，并标记为 MISSING
            sizes_over_time.append(current_sum)
            ops_over_time.append('MISSING')
            continue

        op = str(node.get('Op', '')).upper()

        if op == 'ALLOC':
            bufid = node.get('BufId')
            size = int(node.get('Size', 0))
            btype = node.get('Type', '')
            if bufid is not None:
                current_bufs[int(bufid)] = (int(size), str(btype))
                if str(btype) in ('L1', 'UB'):
                    current_sum += int(size)
        elif op == 'FREE':
            # 优先按 BufId 字段释放
            freed_any = False
            if 'BufId' in node and node['BufId'] is not None:
                bid = int(node['BufId'])
                info = current_bufs.pop(bid, None)
                if info is not None and info[1] in ('L1', 'UB'):
                    current_sum -= int(info[0])
                    freed_any = True
            # 如果没有 BufId，尝试从 "Bufs" 字段获取
            if (not freed_any) and 'Bufs' in node and node['Bufs']:
                for bid in node['Bufs']:
                    info = current_bufs.pop(int(bid), None)
                    if info is not None and info[1] in ('L1', 'UB'):
                        current_sum -= int(info[0])
                        freed_any = True
            # 如果仍然没有释放（结构不明），再尝试按 Size/Type 匹配（可能有重复，不建议但做容错处理）
            if (not freed_any) and ('Size' in node or 'Type' in node):
                target_size = int(node.get('Size', 0)) if 'Size' in node else None
                target_type = node.get('Type') if 'Type' in node else None
                # 从 current_bufs 中找第一个匹配的释放
                for bid, info in list(current_bufs.items()):
                    if ((target_size is None or info[0] == target_size) and
                            (target_type is None or info[1] == target_type)):
                        cur = current_bufs.pop(bid)
                        if cur[1] in ('L1', 'UB'):
                            current_sum -= int(cur[0])
                        freed_any = True
                        break

        # 其他操作不影响驻留总量
        sizes_over_time.append(current_sum)
        ops_over_time.append(op if op else 'UNKNOWN')

    # 计算最大值和索引（若多个索引，返回第一个）
    if sizes_over_time:
        max_val = max(sizes_over_time)
        max_idx = sizes_over_time.index(max_val)
    else:
        max_val = 0
        max_idx = -1

    return sizes_over_time, ops_over_time, max_val, max_idx


def plot_sizes(sizes: List[int], ops: List[str], max_val: int, max_idx: int, out_path: str, title: str = '') -> None:
    plt.figure(figsize=(15, 8))
    
    # 设置中文字体支持
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    # 定义已知操作的样式映射 - 改善配色方案
    styles_map = {
        'ALLOC': {'color': '#2E8B57', 'marker': 'o', 'size': 25},      # 海绿色
        'FREE': {'color': '#DC143C', 'marker': 's', 'size': 25},       # 猩红色
        'COPY_IN': {'color': '#4169E1', 'marker': '^', 'size': 25},    # 皇家蓝
        'COPY_OUT': {'color': '#9932CC', 'marker': 'v', 'size': 25},   # 深紫色
        'MOVE': {'color': '#FF8C00', 'marker': 'D', 'size': 25},       # 深橙色
        'MATMUL': {'color': '#FF1493', 'marker': 'P', 'size': 25},     # 深粉色
        'MISSING': {'color': '#A9A9A9', 'marker': 'x', 'size': 25},    # 深灰色
        'UNKNOWN': {'color': '#000000', 'marker': '*', 'size': 25},    # 黑色
        'OTHER': {'color': '#708090', 'marker': 'h', 'size': 25}       # 石板灰
    }

    # 确保每个x值只对应一个y值，通过去重处理
    unique_points = {}
    op_mapping = {}
    
    for i, (op, size) in enumerate(zip(ops, sizes)):
        # 使用调度步骤作为x值
        x_val = i
        y_val = size
        key = op if op else 'UNKNOWN'
        # 所有未知操作统一归为 'OTHER'
        if key not in styles_map:
            key = 'OTHER'
        
        # 保存每个x值对应的y值和操作类型
        unique_points[x_val] = y_val
        op_mapping[x_val] = key

    # 提取唯一的x和y值
    x_vals = list(unique_points.keys())
    y_vals = list(unique_points.values())
    
    # 按操作类型分组绘制点
    op_groups = {}
    for x_val, op_key in op_mapping.items():
        if op_key not in op_groups:
            op_groups[op_key] = {'x': [], 'y': []}
        op_groups[op_key]['x'].append(x_val)
        op_groups[op_key]['y'].append(unique_points[x_val])

    # 绘制每个操作类型的点
    legend_handles = []
    for op_key, points in op_groups.items():
        style = styles_map.get(op_key, styles_map['OTHER'])
        scatter = plt.scatter(points['x'], points['y'], 
                             s=style['size'], 
                             c=style['color'], 
                             marker=style['marker'], 
                             alpha=0.7, 
                             edgecolors='black', 
                             linewidth=0.5,
                             label=op_key)
        legend_handles.append(scatter)

    # 标注最大点（使用特殊标记）
    if max_idx >= 0 and 0 <= max_idx < len(sizes):
        plt.scatter([max_idx], [max_val], 
                   s=200, 
                   c='red', 
                   marker='*', 
                   edgecolors='black', 
                   linewidth=1.5,
                   label=f'最大值={max_val} (步骤 {max_idx})', 
                   zorder=5)
        plt.axhline(y=max_val, color='red', linestyle='--', linewidth=1, alpha=0.8)

    # 绘制内存使用趋势线（使用所有点）
    all_x_vals = np.arange(len(sizes))
    all_y_vals = np.array(sizes)
    plt.plot(all_x_vals, all_y_vals, color='#1E90FF', linewidth=1.5, alpha=0.6, zorder=1)

    plt.xlabel('调度步骤 (Schedule Step)', fontsize=12, fontweight='bold')
    plt.ylabel('L1 + UB 内存驻留大小 (Resident Size)', fontsize=12, fontweight='bold')
    plt.title(title or 'L1+UB 内存使用情况随调度步骤变化图', fontsize=14, fontweight='bold')
    
    # 设置网格
    plt.grid(True, linestyle=':', alpha=0.6)
    
    # 设置图例
    plt.legend(loc='upper right', bbox_to_anchor=(1, 1), ncol=2)
    
    # 优化布局
    plt.tight_layout()
    
    # 创建输出目录（如有必要）
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    print(f'图已保存到: {out_path}')
    
    try:
        plt.show()
    except Exception:
        # 有些环境下无法显示图形（例如无显示的服务器），此时只保存文件
        pass


def main():
    parser = argparse.ArgumentParser(description='绘制调度序列中 max(L1+UB) 的散点图')
    parser.add_argument('--nodes', '-n', help='节点定义文件（默认1.json）', default='1.json')
    parser.add_argument('--schedule', '-s', help='调度序列文件（默认2.json）', default='2.json')
    parser.add_argument('--out', '-o', help='输出图片路径（默认max_L1_UB.png）', default='max_L1_UB.png')
    args = parser.parse_args()

    nodes = load_nodes(args.nodes)
    schedule = load_schedule(args.schedule)
    sizes, ops, max_val, max_idx = compute_L1_UB_over_time(nodes, schedule)
    title = f"L1+UB 最大内存 = {max_val} (出现在步骤 {max_idx})"

    plot_sizes(sizes, ops, max_val, max_idx, args.out, title)


if __name__ == '__main__':
    main()