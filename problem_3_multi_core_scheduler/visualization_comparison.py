#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能优化对比可视化程序
用于生成问题2和问题3优化结果的对比图
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import os

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def load_schedule(file_path):
    """加载调度序列"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return [int(line.strip()) for line in f if line.strip()]

def load_memory_allocation(file_path):
    """加载内存分配结果"""
    addr_alloc = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                buf_id, offset = line.split(':')
                addr_alloc[int(buf_id)] = int(offset)
    return addr_alloc

def load_spill_operations(file_path):
    """加载SPILL操作列表"""
    spill_list = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                buf_id, new_offset = line.split(':')
                spill_list.append((int(buf_id), int(new_offset)))
    return spill_list

def get_buf_lifecycle(schedule, nodes):
    """计算缓冲区生命周期"""
    buf_lifecycle = {}
    
    for node_id in schedule:
        if node_id not in nodes:
            continue
            
        node = nodes[node_id]
        op = node.get('Op')
        
        if op == 'ALLOC':
            buf_id = node['BufId']
            if buf_id not in buf_lifecycle:
                buf_lifecycle[buf_id] = {
                    'alloc': node_id,
                    'free': None,
                    'producers': [],
                    'consumers': []
                }
        
        elif op == 'FREE':
            buf_id = node['BufId']
            if buf_id in buf_lifecycle:
                buf_lifecycle[buf_id]['free'] = node_id
        
        elif 'Bufs' in node:
            for buf_id in node['Bufs']:
                if buf_id in buf_lifecycle:
                    # 简化判断：COPY_IN和MOVE等为生产者，其他为消费者
                    if op in ['COPY_IN', 'MOVE']:
                        buf_lifecycle[buf_id]['producers'].append(node_id)
                    else:
                        buf_lifecycle[buf_id]['consumers'].append(node_id)
    
    return buf_lifecycle

def calculate_execution_time(schedule, nodes, buf_lifecycle, addr_alloc, spill_list):
    """计算总执行时间"""
    
    # 构建依赖图（包含SPILL节点）
    all_nodes = {node['Id']: node for node in nodes.values()}  # 复制节点
    edges = []
    
    # 添加SPILL节点
    spill_nodes = []
    next_id = max(all_nodes.keys()) + 1 if all_nodes else 1
    
    for i, (buf_id, new_offset) in enumerate(spill_list):
        # 获取缓冲区信息
        buf_size = None
        buf_type = None
        for node in nodes.values():
            if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                buf_size = node['Size']
                buf_type = node['Type']
                break
        
        if buf_size is not None:
            # 检查是否被COPY_IN使用
            is_copy_in_buf = any(
                node.get('Op') == 'COPY_IN' and buf_id in node.get('Bufs', [])
                for node in nodes.values()
            )
            
            # SPILL_OUT节点
            spill_out_cycles = 0 if is_copy_in_buf else buf_size * 2 + 150
            spill_out_node = {
                'Id': next_id,
                'Op': 'SPILL_OUT',
                'Pipe': 'MTE3',
                'Cycles': spill_out_cycles,
                'Bufs': [buf_id]
            }
            all_nodes[next_id] = spill_out_node
            spill_nodes.append(next_id)
            next_id += 1
            
            # SPILL_IN节点
            spill_in_cycles = buf_size * 2 + 150
            spill_in_node = {
                'Id': next_id,
                'Op': 'SPILL_IN',
                'Pipe': 'MTE2',
                'Cycles': spill_in_cycles,
                'Bufs': [buf_id]
            }
            all_nodes[next_id] = spill_in_node
            spill_nodes.append(next_id)
            next_id += 1
    
    # 构建依赖边
    for buf_id, lifecycle in buf_lifecycle.items():
        alloc_node = lifecycle['alloc']
        free_node = lifecycle['free']
        producers = lifecycle['producers']
        consumers = lifecycle['consumers']
        
        # ALLOC -> producers
        for prod in producers:
            edges.append((alloc_node, prod))
        
        # producers -> consumers（数据流依赖）
        for prod in producers:
            for cons in consumers:
                edges.append((prod, cons))
        
        # consumers -> FREE
        if free_node:
            for cons in consumers:
                edges.append((cons, free_node))
    
    # 添加缓存复用依赖：如果两个缓冲区地址重叠，则前一个缓冲区释放后才能分配后一个缓冲区
    cache_usage = defaultdict(list)  # cache_type -> [(buf_id, alloc_node, free_node, start_addr, end_addr)]
    
    for buf_id, addr in addr_alloc.items():
        if buf_id in buf_lifecycle:
            alloc_node = buf_lifecycle[buf_id]['alloc']
            free_node = buf_lifecycle[buf_id]['free']
            
            # 获取缓存类型和大小
            if alloc_node in all_nodes:
                alloc_node_obj = all_nodes[alloc_node]
                cache_type = alloc_node_obj['Type']
                size = alloc_node_obj['Size']
                start_addr = addr
                end_addr = start_addr + size - 1
                
                cache_usage[cache_type].append((buf_id, alloc_node, free_node, start_addr, end_addr))
    
    # 为每种缓存类型添加地址复用依赖
    for cache_type, usage_list in cache_usage.items():
        usage_list.sort(key=lambda x: x[3])  # 按起始地址排序
        
        for i in range(len(usage_list)):
            for j in range(i + 1, len(usage_list)):
                buf1_id, alloc1, free1, start1, end1 = usage_list[i]
                buf2_id, alloc2, free2, start2, end2 = usage_list[j]
                
                # 检查地址重叠
                if start2 <= end1:  # 地址重叠
                    if free1 and alloc2:
                        edges.append((free1, alloc2))  # buf1释放后buf2才能分配
    
    # 构建前驱图
    predecessors = defaultdict(list)
    for src, dst in edges:
        predecessors[dst].append(src)
    
    # 各单元的结束时间
    unit_end_time = defaultdict(int)
    
    start_times = {}
    end_times = {}
    
    for node_id in schedule + spill_nodes:
        if node_id in all_nodes:
            node = all_nodes[node_id]
            cycles = node.get('Cycles', 0)
            pipe = node.get('Pipe', None)
            
            # 计算最早开始时间
            earliest_start = 0
            
            # 依赖约束
            for pred_id in predecessors.get(node_id, []):
                if pred_id in end_times:
                    earliest_start = max(earliest_start, end_times[pred_id])
            
            # 资源约束
            if pipe:
                earliest_start = max(earliest_start, unit_end_time[pipe])
            
            start_times[node_id] = earliest_start
            end_times[node_id] = earliest_start + cycles
            
            # 更新单元结束时间
            if pipe:
                unit_end_time[pipe] = end_times[node_id]
    
    total_time = max(end_times.values()) if end_times else 0
    return total_time

def plot_execution_time_comparison(task2_time, task3_time):
    """绘制执行时间对比图"""
    plt.figure(figsize=(10, 6))
    
    methods = ['问题2优化', '问题3优化']
    times = [task2_time, task3_time]
    
    bars = plt.bar(methods, times, color=['#1f77b4', '#ff7f0e'])
    plt.ylabel('总执行时间')
    plt.title('问题2与问题3优化结果执行时间对比')
    plt.grid(axis='y', alpha=0.3)
    
    # 在柱状图上添加数值标签
    for bar, time in zip(bars, times):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + time*0.01,
                f'{time:,}', ha='center', va='bottom')
    
    # 计算改善百分比
    if task2_time > 0:
        improvement = (task2_time - task3_time) / task2_time * 100
        plt.figtext(0.15, 0.85, f'时间改善: {improvement:.2f}%', fontsize=12,
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))
    
    plt.tight_layout()
    plt.savefig('execution_time_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()

def plot_cache_allocation_comparison(task2_addr_alloc, task3_addr_alloc, nodes):
    """绘制缓存分配对比图"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
    
    # 按缓存类型分组
    cache_types = ['L1', 'UB', 'L0A', 'L0B', 'L0C']
    
    for idx, (addr_alloc, ax, title) in enumerate(zip([task2_addr_alloc, task3_addr_alloc], 
                                                     [ax1, ax2], 
                                                     ['问题2缓存分配', '问题3缓存分配'])):
        cache_buffers = defaultdict(list)
        for buf_id, addr in addr_alloc.items():
            # 获取缓冲区信息
            for node in nodes.values():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    cache_type = node['Type']
                    size = node['Size']
                    cache_buffers[cache_type].append({
                        'buf_id': buf_id,
                        'start': addr,
                        'end': addr + size - 1,
                        'size': size
                    })
                    break
        
        # 绘制每种缓存类型的分配情况
        y_pos = 0
        colors = plt.cm.Set3(np.linspace(0, 1, len(cache_types)))
        
        for i, cache_type in enumerate(cache_types):
            if cache_type in cache_buffers:
                buffers = cache_buffers[cache_type]
                # 按起始地址排序
                buffers.sort(key=lambda x: x['start'])
                
                for buf in buffers:
                    ax.barh(y_pos, buf['size'], left=buf['start'], 
                           height=0.8, color=colors[i], alpha=0.7, 
                           edgecolor='black', linewidth=0.5)
            
            y_pos += 1
        
        ax.set_yticks(range(len(cache_types)))
        ax.set_yticklabels(cache_types)
        ax.set_xlabel('地址空间')
        ax.set_title(title)
        ax.grid(axis='x', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('cache_allocation_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()

def plot_spill_operations_comparison(task2_spill_list, task3_spill_list):
    """绘制SPILL操作对比图"""
    plt.figure(figsize=(12, 6))
    
    methods = ['问题2 SPILL操作', '问题3 SPILL操作']
    spill_counts = [len(task2_spill_list), len(task3_spill_list)]
    
    bars = plt.bar(methods, spill_counts, color=['#2ca02c', '#d62728'])
    plt.ylabel('SPILL操作数量')
    plt.title('问题2与问题3 SPILL操作数量对比')
    plt.grid(axis='y', alpha=0.3)
    
    # 在柱状图上添加数值标签
    for bar, count in zip(bars, spill_counts):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + count*0.01,
                f'{count}', ha='center', va='bottom')
    
    # 计算SPILL操作减少百分比
    if len(task2_spill_list) > 0:
        reduction = (len(task2_spill_list) - len(task3_spill_list)) / len(task2_spill_list) * 100
        plt.figtext(0.15, 0.85, f'SPILL操作减少: {reduction:.2f}%', fontsize=12,
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))
    
    plt.tight_layout()
    plt.savefig('spill_operations_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()

def plot_unit_utilization_comparison(task2_metrics, task3_metrics):
    """绘制单元利用率对比图"""
    # 获取所有单元类型
    all_pipes = set()
    for metrics in [task2_metrics, task3_metrics]:
        if 'unit_stats' in metrics:
            all_pipes.update(metrics['unit_stats'].keys())
    
    if not all_pipes:
        return
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    x = np.arange(len(all_pipes))
    width = 0.35
    
    # 获取问题2和问题3的利用率
    task2_utilization = []
    task3_utilization = []
    
    for pipe in all_pipes:
        task2_util = task2_metrics.get('unit_stats', {}).get(pipe, {}).get('utilization', 0) if task2_metrics else 0
        task3_util = task3_metrics.get('unit_stats', {}).get(pipe, {}).get('utilization', 0) if task3_metrics else 0
        
        task2_utilization.append(task2_util * 100)  # 转换为百分比
        task3_utilization.append(task3_util * 100)
    
    # 绘制对比柱状图
    bars1 = ax.bar(x - width/2, task2_utilization, width, label='问题2优化', color='#1f77b4')
    bars2 = ax.bar(x + width/2, task3_utilization, width, label='问题3优化', color='#ff7f0e')
    
    # 添加数值标签
    for bar, util in zip(bars1, task2_utilization):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{util:.1f}%', ha='center', va='bottom', fontsize=8)
    
    for bar, util in zip(bars2, task3_utilization):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{util:.1f}%', ha='center', va='bottom', fontsize=8)
    
    ax.set_xlabel('处理单元')
    ax.set_ylabel('利用率 (%)')
    ax.set_title('问题2与问题3处理单元利用率对比')
    ax.set_xticks(x)
    ax.set_xticklabels(all_pipes, rotation=45)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('unit_utilization_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()

def analyze_l0_cache_constraints(schedule, nodes, buf_lifecycle, addr_alloc):
    """分析L0缓存约束"""
    # 找到所有L0缓存的缓冲区
    l0_buf_ids = set()
    for node in nodes.values():
        if node.get('Op') == 'ALLOC' and node.get('Type') in ['L0A', 'L0B', 'L0C']:
            l0_buf_ids.add(node['BufId'])
    
    # 构建时间线：记录每个时刻哪些缓冲区在驻留
    timeline = defaultdict(set)  # time -> set of buffer ids
    
    # 遍历调度序列，记录每个缓冲区的生命周期
    # 使用调度序列中的位置作为时间
    for time, node_id in enumerate(schedule):
        if node_id in nodes:
            node = nodes[node_id]
            if node.get('Op') == 'ALLOC' and node.get('BufId') in l0_buf_ids:
                buf_id = node['BufId']
                # 缓冲区开始驻留
                alloc_time = time  # 使用调度序列中的位置作为时间
                if buf_id in buf_lifecycle and buf_lifecycle[buf_id]['free']:
                    free_node_id = buf_lifecycle[buf_id]['free']
                    # 找到释放节点在调度序列中的位置
                    if free_node_id in schedule:
                        free_time = schedule.index(free_node_id)
                        # 在这个时间段内，缓冲区驻留
                        for t in range(alloc_time, free_time + 1):
                            timeline[t].add(buf_id)
    
    # 检查时间线中是否有违反约束的时刻
    violations = []
    for time, buf_ids in timeline.items():
        if len(buf_ids) > 1:
            violations.append((time, len(buf_ids), sorted(buf_ids)))
    
    return violations

def plot_l0_cache_analysis(task2_violations, task3_violations):
    """绘制L0缓存约束分析图"""
    plt.figure(figsize=(12, 6))
    
    methods = ['问题2 L0缓存违反次数', '问题3 L0缓存违反次数']
    violation_counts = [len(task2_violations), len(task3_violations)]
    
    bars = plt.bar(methods, violation_counts, color=['#9467bd', '#8c564b'])
    plt.ylabel('违反约束次数')
    plt.title('问题2与问题3 L0缓存约束违反次数对比')
    plt.grid(axis='y', alpha=0.3)
    
    # 在柱状图上添加数值标签
    for bar, count in zip(bars, violation_counts):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + count*0.01,
                f'{count}', ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig('l0_cache_analysis.png', dpi=300, bbox_inches='tight')
    plt.close()

def generate_visualization_report():
    """生成可视化对比报告"""
    print("正在生成可视化对比报告...")
    
    # 加载计算图
    with open('1.json', 'r', encoding='utf-8') as f:
        graph_data = json.load(f)
    nodes = {n['Id']: n for n in graph_data['Nodes']}
    
    # 加载问题2结果
    try:
        task2_schedule = load_schedule('task2_schedule.json')
        task2_addr_alloc = load_memory_allocation('task2_memory.json')
        task2_spill_list = load_spill_operations('task2_spill.json')
        
        # 计算问题2指标
        task2_buf_lifecycle = get_buf_lifecycle(task2_schedule, nodes)
        task2_time = calculate_execution_time(
            task2_schedule, nodes, task2_buf_lifecycle, task2_addr_alloc, task2_spill_list
        )
        print(f"问题2执行时间: {task2_time:,}")
        
        # 分析问题2 L0缓存约束
        task2_l0_violations = analyze_l0_cache_constraints(
            task2_schedule, nodes, task2_buf_lifecycle, task2_addr_alloc
        )
        print(f"问题2 L0缓存违反次数: {len(task2_l0_violations)}")
    except Exception as e:
        print(f"加载问题2数据时出错: {e}")
        return
    
    # 加载问题3结果
    try:
        task3_schedule = load_schedule('FlashAttention_Case0_schedule.txt')
        task3_addr_alloc = load_memory_allocation('FlashAttention_Case0_memory.txt')
        task3_spill_list = load_spill_operations('FlashAttention_Case0_spill.txt')
        
        # 计算问题3指标
        task3_buf_lifecycle = get_buf_lifecycle(task3_schedule, nodes)
        task3_time = calculate_execution_time(
            task3_schedule, nodes, task3_buf_lifecycle, task3_addr_alloc, task3_spill_list
        )
        print(f"问题3执行时间: {task3_time:,}")
        
        # 分析问题3 L0缓存约束
        task3_l0_violations = analyze_l0_cache_constraints(
            task3_schedule, nodes, task3_buf_lifecycle, task3_addr_alloc
        )
        print(f"问题3 L0缓存违反次数: {len(task3_l0_violations)}")
    except Exception as e:
        print(f"加载问题3数据时出错: {e}")
        return
    
    # 生成对比图
    print("正在生成执行时间对比图...")
    plot_execution_time_comparison(task2_time, task3_time)
    
    print("正在生成缓存分配对比图...")
    plot_cache_allocation_comparison(task2_addr_alloc, task3_addr_alloc, nodes)
    
    print("正在生成SPILL操作对比图...")
    plot_spill_operations_comparison(task2_spill_list, task3_spill_list)
    
    print("正在生成L0缓存约束分析图...")
    plot_l0_cache_analysis(task2_l0_violations, task3_l0_violations)
    
    print("可视化对比报告生成完成！")
    print("生成的图表文件:")
    print("  - execution_time_comparison.png")
    print("  - cache_allocation_comparison.png")
    print("  - spill_operations_comparison.png")
    print("  - l0_cache_analysis.png")

if __name__ == "__main__":
    generate_visualization_report()