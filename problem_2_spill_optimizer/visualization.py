import json
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import os
from matplotlib.colors import ListedColormap

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def load_data_from_dir(dir_path):
    """从指定目录加载数据文件"""
    with open(os.path.join(dir_path, '1.json'), 'r', encoding='utf-8') as f:
        graph_data = json.load(f)
    
    with open(os.path.join(dir_path, '3.json'), 'r', encoding='utf-8') as f:
        result_data = json.load(f)
    
    with open(os.path.join(dir_path, 'task2_schedule.json'), 'r') as f:
        schedule_data = [int(line.strip()) for line in f.readlines() if line.strip()]
    
    return graph_data, result_data, schedule_data

def visualize_memory_allocation_timeline(graph_data, result_data, save_dir='.'):
    """可视化内存分配时间线图"""
    # 获取节点信息
    node_dict = {node['Id']: node for node in graph_data['Nodes']}
    
    # 获取内存分配信息
    memory_allocation = result_data['memory_allocation']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 创建时间线图数据
    timeline_data = []
    for buf_id, offset in memory_allocation.items():
        if offset >= 0 and buf_id in buffer_info:  # 只显示成功分配的缓冲区
            info = buffer_info[buf_id]
            timeline_data.append({
                'buf_id': int(buf_id),
                'offset': offset,
                'size': info['size'],
                'type': info['type']
            })
    
    # 按照内存地址排序
    timeline_data.sort(key=lambda x: x['offset'])
    
    # 限制显示的数据量以避免图像过大
    timeline_data = timeline_data[:50]  # 进一步减少显示的缓冲区数量
    
    # 创建图表，减小图像尺寸以避免超出限制
    fig, ax = plt.subplots(figsize=(10, 4))  # 进一步减小图像尺寸
    
    # 为不同缓存类型设置颜色
    cache_colors = {
        'L1': '#1f77b4',
        'UB': '#ff7f0e',
        'L0A': '#2ca02c',
        'L0B': '#d62728',
        'L0C': '#9467bd'
    }
    
    # 绘制每个缓冲区
    y_positions = {}
    cache_tracks = {}
    
    for item in timeline_data:
        cache_type = item['type']
        if cache_type not in cache_tracks:
            cache_tracks[cache_type] = 0
        else:
            cache_tracks[cache_type] += 1
            
        y_pos = cache_tracks[cache_type]
        y_positions[item['buf_id']] = y_pos
        
        # 绘制矩形表示缓冲区
        color = cache_colors.get(cache_type, '#888888')
        rect = plt.Rectangle((item['offset'], y_pos), item['size'], 0.8, 
                           facecolor=color, edgecolor='black', linewidth=0.5)
        ax.add_patch(rect)  # type: ignore
        
        # 添加缓冲区ID标签（只显示部分以避免过于拥挤）
        if item['size'] > 100:  # 增加显示标签的大小阈值
            ax.text(item['offset'] + item['size']/2, y_pos + 0.4, str(item['buf_id']), 
                    ha='center', va='center', fontsize=6, color='white', weight='bold')  # type: ignore
    
    ax.set_xlabel('内存地址')  # type: ignore
    ax.set_ylabel('缓存类型/轨道')  # type: ignore
    ax.set_title('内存分配时间线图（前50个缓冲区）')  # type: ignore
    
    # 设置y轴标签
    cache_types = list(cache_tracks.keys())
    ax.set_yticks(range(len(cache_types)))  # type: ignore
    ax.set_yticklabels(cache_types)  # type: ignore
    
    # 添加图例
    legend_elements = [plt.Rectangle((0,0),1,1, facecolor=cache_colors[ct], edgecolor='black') 
                      for ct in cache_colors if ct in cache_tracks]
    legend_labels = [ct for ct in cache_colors if ct in cache_tracks]
    ax.legend(legend_elements, legend_labels, title='缓存类型')  # type: ignore
    
    # 限制图像尺寸并保存到指定目录
    save_path = os.path.join(save_dir, '内存分配时间线图.png')
    plt.savefig(save_path, dpi=60, bbox_inches='tight')  # 进一步降低dpi以减小图像尺寸
    plt.close()

def visualize_spill_operations(graph_data, result_data, save_dir='.'):
    """可视化spill操作图"""
    # 获取spill操作信息
    spill_operations = result_data['spill_operations']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 统计spill操作
    spill_stats = {}
    for op in spill_operations:
        buf_id = str(op['buf_id'])
        if buf_id in buffer_info:
            info = buffer_info[buf_id]
            cache_type = info['type']
            if cache_type not in spill_stats:
                spill_stats[cache_type] = 0
            spill_stats[cache_type] += 1
    
    # 创建柱状图
    fig, ax = plt.subplots(figsize=(10, 6))
    
    cache_types = list(spill_stats.keys())
    spill_counts = [spill_stats[ct] for ct in cache_types]
    
    bars = ax.bar(cache_types, spill_counts, color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd'])  # type: ignore
    
    ax.set_xlabel('缓存类型')  # type: ignore
    ax.set_ylabel('Spill操作次数')  # type: ignore
    ax.set_title('各缓存类型的Spill操作统计')  # type: ignore
    
    # 在柱状图上添加数值标签
    for bar, count in zip(bars, spill_counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                str(count), ha='center', va='bottom')  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, 'spill操作统计.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_buffer_sizes_distribution(graph_data, result_data, save_dir='.'):
    """可视化缓冲区大小分布图"""
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 分离不同缓存类型的缓冲区大小
    size_data = {}
    for buf_id, info in buffer_info.items():
        cache_type = info['type']
        if cache_type not in size_data:
            size_data[cache_type] = []
        size_data[cache_type].append(info['size'])
    
    # 创建子图
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    
    # 左图：箱线图
    cache_types = list(size_data.keys())
    size_lists = [size_data[ct] for ct in cache_types]
    
    # 使用labels参数而不是tick_labels（兼容旧版本matplotlib）
    axes[0].boxplot(size_lists, labels=cache_types)  # type: ignore
    axes[0].set_xlabel('缓存类型')  # type: ignore
    axes[0].set_ylabel('缓冲区大小')  # type: ignore
    axes[0].set_title('各缓存类型缓冲区大小分布（箱线图）')  # type: ignore
    axes[0].tick_params(axis='x', rotation=45)  # type: ignore
    
    # 右图：直方图
    for cache_type in cache_types:
        axes[1].hist(size_data[cache_type], alpha=0.7, label=cache_type, bins=30)  # type: ignore
    
    axes[1].set_xlabel('缓冲区大小')  # type: ignore
    axes[1].set_ylabel('频次')  # type: ignore
    axes[1].set_title('缓冲区大小分布（直方图）')  # type: ignore
    axes[1].legend()  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '缓冲区大小分布.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_schedule_with_spill_markers(graph_data, result_data, schedule_data, save_dir='.'):
    """可视化调度序列并标记spill操作"""
    # 获取spill操作涉及的缓冲区
    spill_buffers = set(str(op['buf_id']) for op in result_data['spill_operations'])
    
    # 获取节点信息
    node_dict = {node['Id']: node for node in graph_data['Nodes']}
    
    # 限制显示的数据量
    schedule_data = schedule_data[:1000]  # 只显示前1000个节点
    
    # 创建调度序列图
    fig, ax = plt.subplots(figsize=(15, 6))
    
    # 标记spill操作在调度序列中的位置
    spill_positions = []
    for i, node_id in enumerate(schedule_data):
        node = node_dict.get(node_id, {})
        # 检查节点是否涉及spill缓冲区
        buf_ids = []
        if 'Bufs' in node:
            buf_ids = [str(b) for b in node['Bufs']]
        elif 'In' in node:
            buf_ids = [str(b) for b in node['In']]
        elif node.get('Op') == 'ALLOC':
            buf_ids = [str(node['BufId'])]
        elif node.get('Op') == 'FREE':
            buf_ids = [str(node['BufId'])]
        
        if any(buf_id in spill_buffers for buf_id in buf_ids):
            spill_positions.append(i)
    
    # 绘制调度序列
    positions = range(len(schedule_data))
    ax.scatter(positions, [1] * len(schedule_data), alpha=0.5, s=1, color='blue', label='调度节点')  # type: ignore
    
    # 标记spill操作位置
    if spill_positions:
        ax.scatter(spill_positions, [1] * len(spill_positions), color='red', s=10, label='涉及Spill的节点')  # type: ignore
    
    ax.set_xlabel('调度序列位置')  # type: ignore
    ax.set_ylabel('标记')  # type: ignore
    ax.set_title('调度序列中的Spill操作位置（前1000个节点）')  # type: ignore
    ax.legend()  # type: ignore
    
    # 设置y轴
    ax.set_yticks([1])  # type: ignore
    ax.set_yticklabels(['节点'])  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '调度序列spill标记.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_memory_utilization(result_data, save_dir='.'):
    """可视化内存利用率"""
    # 获取缓存利用率信息
    cache_utilization = result_data['cache_utilization']
    
    # 过滤掉无效值
    valid_cache_types = []
    valid_rates = []
    valid_used = []
    valid_cap = []
    
    for cache_type, info in cache_utilization.items():
        rate = info['utilization_rate']
        # 检查是否为有效数值
        if isinstance(rate, (int, float)) and not np.isnan(rate) and not np.isinf(rate) and rate >= 0 and rate <= 1:
            valid_cache_types.append(cache_type)
            valid_rates.append(rate)
            valid_used.append(info['used'])
            valid_cap.append(info['capacity'])
    
    # 如果没有有效数据，跳过绘图
    if not valid_rates or sum(valid_rates) == 0:
        print("没有有效的内存利用率数据")
        return
    
    # 确保所有比率之和为1
    total_rate = sum(valid_rates)
    if total_rate > 0:
        valid_rates = [rate/total_rate for rate in valid_rates]
    
    # 创建饼图
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 绘制饼图显示利用率
    wedges, texts, autotexts = ax.pie(valid_rates, labels=valid_cache_types, autopct='%1.1f%%', startangle=90)  # type: ignore
    
    ax.set_title('各缓存类型内存利用率')  # type: ignore
    
    # 添加图例显示实际使用量和容量
    legend_labels = [f'{ct}\n使用: {used}/{cap}' for ct, used, cap in zip(valid_cache_types, valid_used, valid_cap)]
    ax.legend(wedges, legend_labels, title="缓存类型 (使用量/容量)", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '内存利用率.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_spill_cost_analysis(result_data, save_dir='.'):
    """可视化spill成本分析"""
    # 获取性能指标
    performance_metrics = result_data['performance_metrics']
    total_spill_cost = result_data['total_spill_cost']
    spill_operations_count = result_data['spill_operations_count']
    
    # 创建指标对比图
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # 准备数据
    metrics = ['内存效率', '分配成功率']
    values = [performance_metrics['memory_efficiency'], performance_metrics['allocation_success_rate']]
    
    # 创建柱状图
    bars = ax.bar(metrics, values, color=['#1f77b4', '#ff7f0e'])  # type: ignore
    
    # 添加数值标签
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01, 
                f'{value:.3f}', ha='center', va='bottom')  # type: ignore
    
    ax.set_ylim(0, 1.2)  # type: ignore
    ax.set_ylabel('比率')  # type: ignore
    ax.set_title(f'性能指标分析\n总Spill成本: {total_spill_cost}, Spill操作数: {spill_operations_count}')  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, 'spill成本分析.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_buffer_lifetime_distribution(graph_data, result_data, schedule_data, save_dir='.'):
    """可视化缓冲区生命周期分布"""
    # 获取节点信息
    node_dict = {node['Id']: node for node in graph_data['Nodes']}
    
    # 获取内存分配信息
    memory_allocation = result_data['memory_allocation']
    
    # 计算缓冲区生命周期
    buffer_lifetime = {}
    for buf_id_str, offset in memory_allocation.items():
        if offset >= 0:  # 只考虑成功分配的缓冲区
            buf_id = int(buf_id_str)
            alloc_pos = free_pos = None
            for pos, node_id in enumerate(schedule_data):
                node = node_dict[node_id]
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    alloc_pos = pos
                elif node.get('Op') == 'FREE' and node.get('BufId') == buf_id:
                    free_pos = pos
            if alloc_pos is not None and free_pos is not None:
                buffer_lifetime[buf_id] = free_pos - alloc_pos
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = node['BufId']
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 创建散点图数据
    lifetime_data = []
    for buf_id, lifetime in buffer_lifetime.items():
        if buf_id in buffer_info:
            info = buffer_info[buf_id]
            lifetime_data.append({
                'buf_id': buf_id,
                'lifetime': lifetime,
                'size': info['size'],
                'type': info['type']
            })
    
    # 按缓存类型分组绘制散点图
    fig, ax = plt.subplots(figsize=(15, 8))
    
    cache_colors = {
        'L1': '#1f77b4',
        'UB': '#ff7f0e',
        'L0A': '#2ca02c',
        'L0B': '#d62728',
        'L0C': '#9467bd'
    }
    
    for cache_type in cache_colors.keys():
        type_data = [item for item in lifetime_data if item['type'] == cache_type]
        if type_data:
            lifetimes = [item['lifetime'] for item in type_data]
            sizes = [item['size'] for item in type_data]
            ax.scatter(lifetimes, sizes, c=cache_colors[cache_type], label=cache_type, alpha=0.6)  # type: ignore
    
    ax.set_xlabel('缓冲区生命周期')  # type: ignore
    ax.set_ylabel('缓冲区大小')  # type: ignore
    ax.set_title('缓冲区生命周期与大小关系散点图')  # type: ignore
    ax.legend()  # type: ignore
    ax.grid(True, alpha=0.3)  # type: ignore
    
    # 移除tight_layout()以避免警告
    # 保存到指定目录
    save_path = os.path.join(save_dir, '缓冲区生命周期分布.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_spill_comparison(graph_data, result_data, save_dir='.'):
    """可视化spill操作对比图"""
    # 获取spill操作信息
    spill_operations = result_data['spill_operations']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 分析spill操作涉及的缓冲区类型和大小
    spill_sizes = []
    spill_types = []
    
    for op in spill_operations:
        buf_id = str(op['buf_id'])
        if buf_id in buffer_info:
            info = buffer_info[buf_id]
            spill_sizes.append(info['size'])
            spill_types.append(info['type'])
    
    # 创建对比图
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    
    # 左图：spill缓冲区大小分布
    axes[0].hist(spill_sizes, bins=30, color='#1f77b4', alpha=0.7)
    axes[0].set_xlabel('缓冲区大小')
    axes[0].set_ylabel('频次')
    axes[0].set_title('Spill操作涉及的缓冲区大小分布')
    axes[0].grid(True, alpha=0.3)
    
    # 右图：spill缓冲区类型统计
    type_counts = {}
    for cache_type in spill_types:
        type_counts[cache_type] = type_counts.get(cache_type, 0) + 1
    
    cache_types = list(type_counts.keys())
    counts = [type_counts[ct] for ct in cache_types]
    
    bars = axes[1].bar(cache_types, counts, color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd'])
    axes[1].set_xlabel('缓存类型')
    axes[1].set_ylabel('Spill操作次数')
    axes[1].set_title('Spill操作涉及的缓冲区类型统计')
    
    # 添加数值标签
    for bar, count in zip(bars, counts):
        axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(count), ha='center', va='bottom')
    
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, 'spill操作对比分析.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_memory_fragmentation(graph_data, result_data, save_dir='.'):
    """可视化内存碎片化分析"""
    # 获取内存分配信息
    memory_allocation = result_data['memory_allocation']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 按缓存类型分析碎片化
    fragmentation_data = {}
    
    for buf_id_str, offset in memory_allocation.items():
        if offset >= 0:  # 只考虑成功分配的缓冲区
            buf_id = int(buf_id_str)
            if buf_id_str in buffer_info:
                info = buffer_info[buf_id_str]
                cache_type = info['type']
                
                if cache_type not in fragmentation_data:
                    fragmentation_data[cache_type] = []
                
                fragmentation_data[cache_type].append({
                    'buf_id': buf_id,
                    'offset': offset,
                    'size': info['size']
                })
    
    # 限制显示的数据量以避免图像过大
    max_buffers_per_type = 15  # 每种缓存类型最多显示15个缓冲区
    for cache_type in fragmentation_data:
        fragmentation_data[cache_type] = fragmentation_data[cache_type][:max_buffers_per_type]
    
    # 如果没有数据，直接返回
    if not any(fragmentation_data.values()):
        print("没有内存碎片化数据")
        return
    
    # 创建碎片化分析图，使用较小的图像尺寸
    fig, ax = plt.subplots(figsize=(12, 6))
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    color_idx = 0
    
    for cache_type, buffers in fragmentation_data.items():
        if not buffers:
            continue
            
        # 按地址排序
        buffers.sort(key=lambda x: x['offset'])
        
        # 为了防止图像过大，我们只显示相对位置
        # 计算相对位置
        base_offset = buffers[0]['offset'] if buffers else 0
        for i, buf in enumerate(buffers):
            # 使用相对位置和索引而不是绝对地址
            relative_pos = i * 100  # 每个缓冲区间隔100单位
            rect_width = min(buf['size'] / 100, 80)  # 缩放宽度以适应显示
            
            rect = plt.Rectangle((relative_pos, color_idx), rect_width, 0.8, 
                               facecolor=colors[color_idx % len(colors)], 
                               edgecolor='black', linewidth=0.5)
            ax.add_patch(rect)  # type: ignore
            
            # 添加缓冲区大小标签（只显示较大的缓冲区）
            if rect_width > 20:
                ax.text(relative_pos + rect_width/2, color_idx + 0.4, str(buf['size']), 
                        ha='center', va='center', fontsize=6, color='white', weight='bold')  # type: ignore
        
        color_idx += 1
    
    ax.set_xlabel('缓冲区位置 (相对)')  # type: ignore
    ax.set_ylabel('缓存类型')  # type: ignore
    ax.set_title('内存碎片化分析 (简化版)')  # type: ignore
    
    # 设置y轴标签
    cache_types = [ct for ct in fragmentation_data.keys() if fragmentation_data[ct]]
    ax.set_yticks(range(len(cache_types)))  # type: ignore
    ax.set_yticklabels(cache_types)  # type: ignore
    
    # 保存到指定目录
    save_path = os.path.join(save_dir, '内存碎片化分析.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_allocation_success_rate_by_type(graph_data, result_data, save_dir='.'):
    """按缓存类型可视化分配成功率"""
    # 获取内存分配信息
    memory_allocation = result_data['memory_allocation']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 按缓存类型统计分配成功率
    allocation_stats = {}
    
    for buf_id_str, offset in memory_allocation.items():
        if buf_id_str in buffer_info:
            info = buffer_info[buf_id_str]
            cache_type = info['type']
            
            if cache_type not in allocation_stats:
                allocation_stats[cache_type] = {'success': 0, 'failed': 0}
            
            if offset >= 0:
                allocation_stats[cache_type]['success'] += 1
            else:
                allocation_stats[cache_type]['failed'] += 1
    
    # 创建柱状图
    fig, ax = plt.subplots(figsize=(12, 6))
    
    cache_types = list(allocation_stats.keys())
    success_rates = []
    
    for cache_type in cache_types:
        stats = allocation_stats[cache_type]
        total = stats['success'] + stats['failed']
        success_rate = stats['success'] / total if total > 0 else 0
        success_rates.append(success_rate)
    
    bars = ax.bar(cache_types, success_rates, color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd'])  # type: ignore
    
    ax.set_xlabel('缓存类型')  # type: ignore
    ax.set_ylabel('分配成功率')  # type: ignore
    ax.set_title('各缓存类型分配成功率')  # type: ignore
    ax.set_ylim(0, 1.2)  # type: ignore
    
    # 添加数值标签
    for bar, rate in zip(bars, success_rates):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01, 
                f'{rate:.3f}', ha='center', va='bottom')  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '各缓存类型分配成功率.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_schedule_scatter_comparison(graph_data, result_data, schedule_data, save_dir='.'):
    """可视化调度序列散点图对比（加入spill前后的对比）"""
    # 获取节点信息
    node_dict = {node['Id']: node for node in graph_data['Nodes']}
    
    # 获取spill操作涉及的缓冲区
    spill_buffers = set(str(op['buf_id']) for op in result_data['spill_operations'])
    
    # 限制显示的数据量
    schedule_data = schedule_data[:500]  # 只显示前500个节点
    
    # 创建调度序列散点图数据
    positions = []
    buffer_sizes = []
    buffer_types = []
    is_spill_related = []
    
    # 定义缓存类型颜色映射
    cache_colors = {
        'L1': '#1f77b4',
        'UB': '#ff7f0e',
        'L0A': '#2ca02c',
        'L0B': '#d62728',
        'L0C': '#9467bd'
    }
    
    # 遍历调度序列，收集数据
    for i, node_id in enumerate(schedule_data):
        node = node_dict.get(node_id, {})
        
        # 获取节点涉及的缓冲区
        buf_ids = []
        if 'Bufs' in node:
            buf_ids = [str(b) for b in node['Bufs']]
        elif 'In' in node:
            buf_ids = [str(b) for b in node['In']]
        elif node.get('Op') == 'ALLOC':
            buf_ids = [str(node['BufId'])]
        elif node.get('Op') == 'FREE':
            buf_ids = [str(node['BufId'])]
        
        # 获取缓冲区信息
        for buf_id in buf_ids:
            # 获取缓冲区大小和类型
            buf_node = None
            for n in graph_data['Nodes']:
                if n.get('Op') == 'ALLOC' and str(n.get('BufId')) == buf_id:
                    buf_node = n
                    break
            
            if buf_node:
                positions.append(i)
                buffer_sizes.append(buf_node['Size'])
                buffer_types.append(buf_node['Type'])
                # 标记是否与spill相关
                is_spill_related.append(buf_id in spill_buffers)
    
    # 创建对比散点图
    fig, axes = plt.subplots(1, 2, figsize=(20, 8))
    
    # 左图：加入spill前的调度序列（所有节点）
    scatter1 = axes[0].scatter(positions, buffer_sizes, c=[cache_colors.get(t, '#888888') for t in buffer_types], 
                              alpha=0.6, s=20)  # type: ignore
    axes[0].set_xlabel('调度序列位置')  # type: ignore
    axes[0].set_ylabel('缓冲区大小')  # type: ignore
    axes[0].set_title('加入spill前的调度序列')  # type: ignore
    axes[0].grid(True, alpha=0.3)  # type: ignore
    
    # 右图：加入spill后的调度序列（突出显示spill相关节点）
    # 绘制所有节点
    axes[1].scatter(positions, buffer_sizes, c=[cache_colors.get(t, '#888888') for t in buffer_types], 
                   alpha=0.3, s=20)  # type: ignore
    
    # 突出显示spill相关节点
    spill_positions = [pos for pos, is_spill in zip(positions, is_spill_related) if is_spill]
    spill_sizes = [size for size, is_spill in zip(buffer_sizes, is_spill_related) if is_spill]
    spill_types = [t for t, is_spill in zip(buffer_types, is_spill_related) if is_spill]
    
    if spill_positions:
        axes[1].scatter(spill_positions, spill_sizes, 
                       c=[cache_colors.get(t, '#888888') for t in spill_types], 
                       alpha=0.8, s=40, edgecolors='red', linewidth=1)  # type: ignore
    
    axes[1].set_xlabel('调度序列位置')  # type: ignore
    axes[1].set_ylabel('缓冲区大小')  # type: ignore
    axes[1].set_title('加入spill后的调度序列（红色边框表示spill相关节点）')  # type: ignore
    axes[1].grid(True, alpha=0.3)  # type: ignore
    
    # 添加图例
    legend_elements = [plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, 
                                 markersize=10, label=cache_type) 
                      for cache_type, color in cache_colors.items()]
    
    fig.legend(handles=legend_elements, title='缓存类型', loc='upper right')  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '调度序列散点图对比.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_buffer_access_patterns(graph_data, result_data, schedule_data, save_dir='.'):
    """可视化缓冲区访问模式"""
    # 获取节点信息
    node_dict = {node['Id']: node for node in graph_data['Nodes']}
    
    # 获取内存分配信息
    memory_allocation = result_data['memory_allocation']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 统计每个缓冲区的访问次数
    buffer_access_count = {}
    
    # 遍历调度序列，统计访问次数
    for node_id in schedule_data:
        node = node_dict.get(node_id, {})
        
        # 获取节点涉及的缓冲区
        buf_ids = []
        if 'Bufs' in node:
            buf_ids = [str(b) for b in node['Bufs']]
        elif 'In' in node:
            buf_ids = [str(b) for b in node['In']]
        elif node.get('Op') == 'ALLOC':
            buf_ids = [str(node['BufId'])]
        elif node.get('Op') == 'FREE':
            buf_ids = [str(node['BufId'])]
        
        # 统计访问次数
        for buf_id in buf_ids:
            if buf_id in buffer_info:  # 只统计有效的缓冲区
                buffer_access_count[buf_id] = buffer_access_count.get(buf_id, 0) + 1
    
    # 创建访问模式散点图数据
    access_counts = []
    buffer_sizes = []
    buffer_types = []
    
    for buf_id, access_count in buffer_access_count.items():
        if buf_id in buffer_info:
            info = buffer_info[buf_id]
            access_counts.append(access_count)
            buffer_sizes.append(info['size'])
            buffer_types.append(info['type'])
    
    # 创建散点图
    fig, ax = plt.subplots(figsize=(15, 8))
    
    # 定义缓存类型颜色映射
    cache_colors = {
        'L1': '#1f77b4',
        'UB': '#ff7f0e',
        'L0A': '#2ca02c',
        'L0B': '#d62728',
        'L0C': '#9467bd'
    }
    
    # 按缓存类型绘制散点图
    for cache_type in cache_colors.keys():
        type_access_counts = [count for count, ctype in zip(access_counts, buffer_types) if ctype == cache_type]
        type_buffer_sizes = [size for size, ctype in zip(buffer_sizes, buffer_types) if ctype == cache_type]
        
        if type_access_counts:
            ax.scatter(type_access_counts, type_buffer_sizes, 
                      c=cache_colors[cache_type], label=cache_type, alpha=0.6, s=30)  # type: ignore
    
    ax.set_xlabel('缓冲区访问次数')  # type: ignore
    ax.set_ylabel('缓冲区大小')  # type: ignore
    ax.set_title('缓冲区访问模式分析')  # type: ignore
    ax.legend()  # type: ignore
    ax.grid(True, alpha=0.3)  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, '缓冲区访问模式.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def visualize_spill_impact_analysis(graph_data, result_data, save_dir='.'):
    """可视化spill影响分析"""
    # 获取spill操作信息
    spill_operations = result_data['spill_operations']
    
    # 获取缓冲区信息
    buffer_info = {}
    for node in graph_data['Nodes']:
        if node.get('Op') == 'ALLOC':
            buf_id = str(node['BufId'])
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 分析spill操作的时机分布
    spill_timing = [op['timing'] for op in spill_operations if 'timing' in op]
    
    # 分析spill缓冲区的大小分布
    spill_sizes = []
    spill_types = []
    
    for op in spill_operations:
        buf_id = str(op['buf_id'])
        if buf_id in buffer_info:
            info = buffer_info[buf_id]
            spill_sizes.append(info['size'])
            spill_types.append(info['type'])
    
    # 创建子图
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    
    # 左图：spill操作时机分布
    if spill_timing:
        axes[0].hist(spill_timing, bins=30, color='#1f77b4', alpha=0.7)  # type: ignore
        axes[0].set_xlabel('调度序列位置')  # type: ignore
        axes[0].set_ylabel('Spill操作次数')  # type: ignore
        axes[0].set_title('Spill操作时机分布')  # type: ignore
        axes[0].grid(True, alpha=0.3)  # type: ignore
    else:
        axes[0].text(0.5, 0.5, '无spill时机数据', ha='center', va='center', transform=axes[0].transAxes)  # type: ignore
        axes[0].set_title('Spill操作时机分布')  # type: ignore
    
    # 右图：spill缓冲区大小分布
    if spill_sizes:
        # 按缓存类型分组
        type_sizes = {}
        for size, cache_type in zip(spill_sizes, spill_types):
            if cache_type not in type_sizes:
                type_sizes[cache_type] = []
            type_sizes[cache_type].append(size)
        
        # 绘制箱线图
        cache_types = list(type_sizes.keys())
        size_lists = [type_sizes[ct] for ct in cache_types]
        
        if size_lists:
            axes[1].boxplot(size_lists, labels=cache_types)  # type: ignore
            axes[1].set_xlabel('缓存类型')  # type: ignore
            axes[1].set_ylabel('缓冲区大小')  # type: ignore
            axes[1].set_title('Spill缓冲区大小分布')  # type: ignore
            axes[1].tick_params(axis='x', rotation=45)  # type: ignore
            axes[1].grid(True, alpha=0.3)  # type: ignore
        else:
            axes[1].text(0.5, 0.5, '无spill大小数据', ha='center', va='center', transform=axes[1].transAxes)  # type: ignore
            axes[1].set_title('Spill缓冲区大小分布')  # type: ignore
    else:
        axes[1].text(0.5, 0.5, '无spill大小数据', ha='center', va='center', transform=axes[1].transAxes)  # type: ignore
        axes[1].set_title('Spill缓冲区大小分布')  # type: ignore
    
    plt.tight_layout()
    # 保存到指定目录
    save_path = os.path.join(save_dir, 'spill影响分析.png')
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

def process_all_result_dirs():
    """处理所有结果目录（1-6）"""
    base_dir = '结果备份'
    for i in range(1, 7):
        dir_path = os.path.join(base_dir, str(i))
        if os.path.exists(dir_path):
            print(f"正在处理目录: {dir_path}")
            
            # 加载数据
            graph_data, result_data, schedule_data = load_data_from_dir(dir_path)
            
            # 生成各种可视化图表
            print("  正在生成内存分配时间线图...")
            visualize_memory_allocation_timeline(graph_data, result_data, dir_path)
            
            print("  正在生成spill操作统计图...")
            visualize_spill_operations(graph_data, result_data, dir_path)
            
            print("  正在生成缓冲区大小分布图...")
            visualize_buffer_sizes_distribution(graph_data, result_data, dir_path)
            
            print("  正在生成调度序列spill标记图...")
            visualize_schedule_with_spill_markers(graph_data, result_data, schedule_data, dir_path)
            
            print("  正在生成内存利用率图...")
            visualize_memory_utilization(result_data, dir_path)
            
            print("  正在生成spill成本分析图...")
            visualize_spill_cost_analysis(result_data, dir_path)
            
            print("  正在生成缓冲区生命周期分布图...")
            visualize_buffer_lifetime_distribution(graph_data, result_data, schedule_data, dir_path)
            
            print("  正在生成spill操作对比分析图...")
            visualize_spill_comparison(graph_data, result_data, dir_path)
            
            print("  正在生成内存碎片化分析图...")
            visualize_memory_fragmentation(graph_data, result_data, dir_path)
            
            print("  正在生成各缓存类型分配成功率图...")
            visualize_allocation_success_rate_by_type(graph_data, result_data, dir_path)
            
            print("  正在生成调度序列散点图对比...")
            visualize_schedule_scatter_comparison(graph_data, result_data, schedule_data, dir_path)
            
            print("  正在生成缓冲区访问模式图...")
            visualize_buffer_access_patterns(graph_data, result_data, schedule_data, dir_path)
            
            print("  正在生成spill影响分析图...")
            visualize_spill_impact_analysis(graph_data, result_data, dir_path)
            
            print(f"  目录 {dir_path} 的所有可视化图表已生成完成！")

def main():
    """主函数"""
    process_all_result_dirs()
    print("所有目录的可视化图表已生成完成！")

if __name__ == "__main__":
    main()