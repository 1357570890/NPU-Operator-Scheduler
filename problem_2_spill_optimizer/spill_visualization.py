import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

def load_data():
    """加载必要的数据文件"""
    with open('1.json', 'r', encoding='utf-8') as f:
        graph_data = json.load(f)
    with open('2.json', 'r', encoding='utf-8') as f:
        schedule_data = f.read().strip().split('\n')
        schedule = [int(x) for x in schedule_data if x.strip()]
    with open('3.json', 'r', encoding='utf-8') as f:
        solution_data = json.load(f)
    
    return graph_data, schedule, solution_data

def analyze_memory_usage(graph_data, schedule, solution_data):
    """分析调度过程中L1和UB缓存的使用情况"""
    nodes = graph_data['Nodes']
    node_dict = {node['Id']: node for node in nodes}
    memory_allocation = solution_data['memory_allocation']
    spill_operations = solution_data['spill_operations']
    
    # 初始化缓存使用情况跟踪
    l1_usage = []
    ub_usage = []
    timeline = []
    
    # 构建缓冲区信息映射
    buffer_info = {}
    for node in nodes:
        if node.get('Op') == 'ALLOC':
            buf_id = node['BufId']
            buffer_info[buf_id] = {
                'size': node['Size'],
                'type': node['Type']
            }
    
    # 计算缓冲区生命周期
    buffer_lifetime = {}
    for buf_id in buffer_info:
        alloc_pos = free_pos = None
        for pos, node_id in enumerate(schedule):
            node = node_dict[node_id]
            if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                alloc_pos = pos
            elif node.get('Op') == 'FREE' and node.get('BufId') == buf_id:
                free_pos = pos
        if alloc_pos is not None and free_pos is not None:
            buffer_lifetime[buf_id] = (alloc_pos, free_pos)
    
    # 创建spill操作映射
    spill_buffer_map = {}
    for op in spill_operations:
        buf_id = op['buf_id']
        spill_buffer_map[str(buf_id)] = op['new_offset']
    
    # 在调度序列中跟踪缓存使用情况
    active_buffers = {}  # buf_id: (offset, size)
    
    # 记录spill操作点
    spill_operation_points = []  # 记录spill操作发生的位置
    spill_details = []  # 记录spill操作的详细信息
    
    # 计算每个时间点的内存使用情况
    for pos, node_id in enumerate(schedule):
        node = node_dict[node_id]
        op = node.get('Op')
        
        # 更新活跃缓冲区集合
        if op == 'ALLOC':
            buf_id = node['BufId']
            if str(buf_id) in memory_allocation:
                offset = memory_allocation[str(buf_id)]
                if offset >= 0:  # 只跟踪成功分配的缓冲区
                    size = buffer_info[buf_id]['size']
                    active_buffers[buf_id] = (offset, size)
        elif op == 'FREE':
            buf_id = node['BufId']
            if buf_id in active_buffers:
                del active_buffers[buf_id]
        
        # 计算当前时刻L1和UB的实际使用量（考虑地址分配）
        current_l1 = 0
        current_ub = 0
        
        # 计算实际使用的地址范围
        l1_blocks = []
        ub_blocks = []
        
        for buf_id, (offset, size) in active_buffers.items():
            cache_type = buffer_info[buf_id]['type']
            if cache_type == 'L1':
                l1_blocks.append((offset, offset + size))
            elif cache_type == 'UB':
                ub_blocks.append((offset, offset + size))
        
        # 计算L1实际使用量
        if l1_blocks:
            l1_blocks.sort()
            merged_l1 = [l1_blocks[0]]
            for current in l1_blocks[1:]:
                last = merged_l1[-1]
                if last[1] >= current[0]:  # 重叠或相邻
                    merged_l1[-1] = (last[0], max(last[1], current[1]))
                else:
                    merged_l1.append(current)
            current_l1 = sum(end - start for start, end in merged_l1)
        
        # 计算UB实际使用量
        if ub_blocks:
            ub_blocks.sort()
            merged_ub = [ub_blocks[0]]
            for current in ub_blocks[1:]:
                last = merged_ub[-1]
                if last[1] >= current[0]:  # 重叠或相邻
                    merged_ub[-1] = (last[0], max(last[1], current[1]))
                else:
                    merged_ub.append(current)
            current_ub = sum(end - start for start, end in merged_ub)
        
        # 检查是否是spill操作点
        if op == 'ALLOC' and str(node['BufId']) in spill_buffer_map:
            spill_operation_points.append(pos)
            spill_details.append({
                'position': pos,
                'buffer_id': node['BufId'],
                'cache_type': buffer_info[node['BufId']]['type']
            })
        
        l1_usage.append(current_l1)
        ub_usage.append(current_ub)
        timeline.append(pos)
    
    return timeline, l1_usage, ub_usage, spill_operation_points, spill_details

def plot_memory_usage(timeline, l1_usage, ub_usage, spill_points, spill_details):
    """绘制L1和UB缓存使用情况图表"""
    plt.figure(figsize=(20, 10))
    
    # 绘制L1使用情况
    plt.plot(timeline, l1_usage, label='L1 Usage', color='blue', linewidth=1.5)
    
    # 绘制UB使用情况
    plt.plot(timeline, ub_usage, label='UB Usage', color='red', linewidth=1.5)
    
    # 添加L1和UB的容量限制线
    plt.axhline(y=4096, color='blue', linestyle='--', alpha=0.5, label='L1 Capacity (4096)')
    plt.axhline(y=1024, color='red', linestyle='--', alpha=0.5, label='UB Capacity (1024)')
    
    # 在spill操作点添加大的彩色点
    l1_spill_points = []
    ub_spill_points = []
    l1_spill_values = []
    ub_spill_values = []
    
    # 分离L1和UB的spill操作点
    for detail in spill_details:
        pos = detail['position']
        cache_type = detail['cache_type']
        if cache_type == 'L1':
            l1_spill_points.append(pos)
            l1_spill_values.append(l1_usage[pos])
        elif cache_type == 'UB':
            ub_spill_points.append(pos)
            ub_spill_values.append(ub_usage[pos])
    
    # 绘制spill操作点
    if l1_spill_points:
        plt.scatter(l1_spill_points, l1_spill_values, color='green', s=150, label='SPILL Operations (L1)', zorder=5, marker='^')
    if ub_spill_points:
        plt.scatter(ub_spill_points, ub_spill_values, color='orange', s=150, label='SPILL Operations (UB)', zorder=5, marker='v')
    
    # 添加标题和标签
    plt.xlabel('Schedule Position', fontsize=14)
    plt.ylabel('Memory Usage (Bytes)', fontsize=14)
    plt.title('L1 and UB Memory Usage Over Schedule with SPILL Operations', fontsize=16)
    plt.legend(fontsize=12)
    plt.grid(True, alpha=0.3)
    
    # 设置图表样式
    plt.tight_layout()
    plt.savefig('memory_usage_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

def main():
    """主函数"""
    print("正在加载数据...")
    graph_data, schedule, solution_data = load_data()
    
    print("正在分析内存使用情况...")
    timeline, l1_usage, ub_usage, spill_points, spill_details = analyze_memory_usage(graph_data, schedule, solution_data)
    
    print("正在生成可视化图表...")
    plot_memory_usage(timeline, l1_usage, ub_usage, spill_points, spill_details)
    
    print("图表已保存为 memory_usage_analysis.png")
    print(f"总共 {len(spill_details)} 个SPILL操作")
    
    # 输出一些统计信息
    max_l1 = max(l1_usage) if l1_usage else 0
    max_ub = max(ub_usage) if ub_usage else 0
    print(f"L1最大使用量: {max_l1} bytes")
    print(f"UB最大使用量: {max_ub} bytes")
    print(f"L1是否超出容量: {'是' if max_l1 > 4096 else '否'}")
    print(f"UB是否超出容量: {'是' if max_ub > 1024 else '否'}")

if __name__ == "__main__":
    main()