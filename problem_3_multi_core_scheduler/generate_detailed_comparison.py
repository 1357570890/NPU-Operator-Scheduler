#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
详细性能优化对比分析程序
用于生成问题2和问题3优化结果的详细对比分析报告
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
    return total_time, start_times, end_times

def calculate_unit_stats(schedule, nodes, start_times, end_times):
    """计算各单元的统计信息"""
    unit_times = defaultdict(list)
    
    for node_id in schedule:
        if node_id in nodes:
            node = nodes[node_id]
            if 'Pipe' in node:
                pipe = node['Pipe']
                cycles = node.get('Cycles', 0)
                unit_times[pipe].append({
                    'start': start_times.get(node_id, 0),
                    'end': end_times.get(node_id, 0),
                    'cycles': cycles
                })
    
    unit_stats = {}
    total_exec_time = max(end_times.values()) if end_times else 0
    
    for pipe, time_slots in unit_times.items():
        total_cycles = sum(slot['cycles'] for slot in time_slots)
        idle_time = total_exec_time - total_cycles
        idle_ratio = idle_time / total_exec_time if total_exec_time > 0 else 0
        
        unit_stats[pipe] = {
            'total_cycles': total_cycles,
            'idle_time': idle_time,
            'idle_ratio': idle_ratio,
            'utilization': 1 - idle_ratio
        }
    
    return unit_stats

def analyze_cache_fragmentation(schedule, nodes, buf_lifecycle, addr_alloc, cache_config):
    """分析缓存碎片率"""
    fragmentation_stats = {}
    
    # 按缓存类型分组
    cache_buffers = defaultdict(list)
    for buf_id, addr in addr_alloc.items():
        # 只处理在buf_lifecycle中存在的缓冲区
        if buf_id in buf_lifecycle:
            alloc_node_id = buf_lifecycle[buf_id]['alloc']
            alloc_node = nodes[alloc_node_id]
            cache_type = alloc_node['Type']
            size = alloc_node['Size']
            
            cache_buffers[cache_type].append({
                'buf_id': buf_id,
                'start': addr,
                'end': addr + size - 1,
                'size': size
            })
    
    # 计算每种缓存的碎片率
    for cache_type, buffers in cache_buffers.items():
        capacity = cache_config[cache_type]
        
        # 排序缓冲区
        buffers.sort(key=lambda x: x['start'])
        
        # 计算碎片
        total_used = sum(buf['size'] for buf in buffers)
        fragments = []
        
        # 开始的碎片
        if buffers and buffers[0]['start'] > 0:
            fragments.append(buffers[0]['start'])
        
        # 中间的碎片
        for i in range(len(buffers) - 1):
            gap = buffers[i+1]['start'] - buffers[i]['end'] - 1
            if gap > 0:
                fragments.append(gap)
        
        # 结尾的碎片
        if buffers and buffers[-1]['end'] < capacity - 1:
            fragments.append(capacity - 1 - buffers[-1]['end'])
        
        total_fragments = sum(fragments)
        fragmentation_rate = total_fragments / capacity if capacity > 0 else 0
        
        fragmentation_stats[cache_type] = {
            'capacity': capacity,
            'used': total_used,
            'fragments': total_fragments,
            'fragmentation_rate': fragmentation_rate,
            'fragments_list': fragments
        }
    
    return fragmentation_stats

def plot_detailed_execution_timeline(task2_schedule, task3_schedule, nodes, 
                                   task2_start_times, task2_end_times,
                                   task3_start_times, task3_end_times):
    """绘制详细的执行时间线对比图"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 12))
    
    # 定义颜色映射
    pipe_colors = {
        'MTE1': '#1f77b4', 'MTE2': '#ff7f0e', 'MTE3': '#2ca02c',
        'CUBE': '#d62728', 'VEC': '#9467bd', 'SCL': '#8c564b'
    }
    
    # 选择前100个节点进行可视化
    sample_size = min(100, len(task2_schedule))
    task2_sample = task2_schedule[:sample_size]
    task3_sample = task3_schedule[:sample_size]
    
    for idx, (schedule, start_times, end_times, ax, title) in enumerate(
        zip([task2_sample, task3_sample], 
            [task2_start_times, task3_start_times], 
            [task2_end_times, task3_end_times], 
            [ax1, ax2], 
            ['问题2执行时间线(前100个节点)', '问题3执行时间线(前100个节点)'])):
        
        # 绘制每个节点的执行时间线
        y_pos = 0
        for node_id in schedule:
            if node_id in nodes and node_id in start_times and node_id in end_times:
                node = nodes[node_id]
                if 'Pipe' in node:
                    pipe = node['Pipe']
                    start = start_times[node_id]
                    end = end_times[node_id]
                    duration = end - start
                    
                    color = pipe_colors.get(pipe, '#7f7f7f')
                    ax.barh(y_pos, duration, left=start, height=0.8, 
                           color=color, alpha=0.7, edgecolor='black', linewidth=0.5)
                    y_pos += 1
        
        ax.set_xlabel('时间周期')
        ax.set_ylabel('节点顺序')
        ax.set_title(title)
        ax.grid(axis='x', alpha=0.3)
        
        # 添加图例
        legend_elements = [plt.Rectangle((0,0),1,1, facecolor=color, label=pipe) 
                          for pipe, color in pipe_colors.items()]
        ax.legend(handles=legend_elements, loc='upper right')
    
    plt.tight_layout()
    plt.savefig('detailed_execution_timeline.png', dpi=300, bbox_inches='tight')
    plt.close()

def plot_cache_utilization_comparison(task2_fragmentation, task3_fragmentation):
    """绘制缓存利用率对比图"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
    
    cache_types = ['L1', 'UB', 'L0A', 'L0B', 'L0C']
    
    for idx, (fragmentation, ax, title) in enumerate(
        zip([task2_fragmentation, task3_fragmentation], 
            [ax1, ax2], 
            ['问题2缓存利用率', '问题3缓存利用率'])):
        
        cache_names = []
        utilization_rates = []
        fragmentation_rates = []
        
        for cache_type in cache_types:
            if cache_type in fragmentation:
                frag_data = fragmentation[cache_type]
                capacity = frag_data['capacity']
                used = frag_data['used']
                fragmentation_rate = frag_data['fragmentation_rate']
                
                utilization_rate = used / capacity * 100 if capacity > 0 else 0
                
                cache_names.append(cache_type)
                utilization_rates.append(utilization_rate)
                fragmentation_rates.append(fragmentation_rate * 100)
        
        x = np.arange(len(cache_names))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, utilization_rates, width, label='利用率', color='#1f77b4')
        bars2 = ax.bar(x + width/2, fragmentation_rates, width, label='碎片率', color='#ff7f0e')
        
        # 添加数值标签
        for bar, rate in zip(bars1, utilization_rates):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{rate:.1f}%', ha='center', va='bottom', fontsize=8)
        
        for bar, rate in zip(bars2, fragmentation_rates):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{rate:.1f}%', ha='center', va='bottom', fontsize=8)
        
        ax.set_xlabel('缓存类型')
        ax.set_ylabel('百分比 (%)')
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(cache_names)
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('cache_utilization_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()

def generate_detailed_report():
    """生成详细对比报告"""
    print("正在生成详细对比报告...")
    
    cache_config = {
        'L1': 4096,
        'UB': 1024,
        'L0A': 256,
        'L0B': 256,
        'L0C': 512
    }
    
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
        task2_time, task2_start_times, task2_end_times = calculate_execution_time(
            task2_schedule, nodes, task2_buf_lifecycle, task2_addr_alloc, task2_spill_list
        )
        task2_unit_stats = calculate_unit_stats(
            task2_schedule, nodes, task2_start_times, task2_end_times
        )
        task2_fragmentation = analyze_cache_fragmentation(
            task2_schedule, nodes, task2_buf_lifecycle, task2_addr_alloc, cache_config
        )
        print(f"问题2执行时间: {task2_time:,}")
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
        task3_time, task3_start_times, task3_end_times = calculate_execution_time(
            task3_schedule, nodes, task3_buf_lifecycle, task3_addr_alloc, task3_spill_list
        )
        task3_unit_stats = calculate_unit_stats(
            task3_schedule, nodes, task3_start_times, task3_end_times
        )
        task3_fragmentation = analyze_cache_fragmentation(
            task3_schedule, nodes, task3_buf_lifecycle, task3_addr_alloc, cache_config
        )
        print(f"问题3执行时间: {task3_time:,}")
    except Exception as e:
        print(f"加载问题3数据时出错: {e}")
        return
    
    # 生成详细对比图
    print("正在生成详细执行时间线对比图...")
    plot_detailed_execution_timeline(
        task2_schedule, task3_schedule, nodes,
        task2_start_times, task2_end_times,
        task3_start_times, task3_end_times
    )
    
    print("正在生成缓存利用率对比图...")
    plot_cache_utilization_comparison(task2_fragmentation, task3_fragmentation)
    
    # 生成文本报告
    print("\n=== 详细性能对比分析报告 ===")
    print(f"问题2总执行时间: {task2_time:,}")
    print(f"问题3总执行时间: {task3_time:,}")
    if task2_time > 0:
        improvement = (task2_time - task3_time) / task2_time * 100
        print(f"时间改善: {improvement:.2f}%")
    
    print("\n=== 各处理单元利用率对比 ===")
    all_pipes = set(task2_unit_stats.keys()) | set(task3_unit_stats.keys())
    for pipe in sorted(all_pipes):
        task2_util = task2_unit_stats.get(pipe, {}).get('utilization', 0) * 100
        task3_util = task3_unit_stats.get(pipe, {}).get('utilization', 0) * 100
        print(f"{pipe:6}: 问题2={task2_util:6.2f}%  问题3={task3_util:6.2f}%  改善={task3_util-task2_util:6.2f}%")
    
    print("\n=== 缓存利用率对比 ===")
    all_cache_types = set(task2_fragmentation.keys()) | set(task3_fragmentation.keys())
    for cache_type in sorted(all_cache_types):
        task2_frag = task2_fragmentation.get(cache_type, {})
        task3_frag = task3_fragmentation.get(cache_type, {})
        
        task2_util = task2_frag.get('used', 0) / task2_frag.get('capacity', 1) * 100 if task2_frag.get('capacity', 0) > 0 else 0
        task3_util = task3_frag.get('used', 0) / task3_frag.get('capacity', 1) * 100 if task3_frag.get('capacity', 0) > 0 else 0
        
        task2_frag_rate = task2_frag.get('fragmentation_rate', 0) * 100
        task3_frag_rate = task3_frag.get('fragmentation_rate', 0) * 100
        
        print(f"{cache_type:4}: 问题2利用率={task2_util:6.2f}% 碎片率={task2_frag_rate:6.2f}% | 问题3利用率={task3_util:6.2f}% 碎片率={task3_frag_rate:6.2f}%")
    
    print("\n=== SPILL操作对比 ===")
    print(f"问题2 SPILL操作数量: {len(task2_spill_list)}")
    print(f"问题3 SPILL操作数量: {len(task3_spill_list)}")
    if len(task2_spill_list) > 0:
        reduction = (len(task2_spill_list) - len(task3_spill_list)) / len(task2_spill_list) * 100
        print(f"SPILL操作减少: {reduction:.2f}%")
    
    print("\n详细对比报告生成完成！")
    print("生成的图表文件:")
    print("  - detailed_execution_timeline.png")
    print("  - cache_utilization_comparison.png")

if __name__ == "__main__":
    generate_detailed_report()