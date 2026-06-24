#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
问题3优化结果验证程序
用于检测优化输出的有效性
"""

import json
from collections import defaultdict

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

def validate_schedule_order(schedule, nodes, buf_lifecycle):
    """验证调度序列的正确性"""
    print("正在验证调度序列...")
    
    # 检查所有节点是否都在序列中
    all_node_ids = set(nodes.keys())
    schedule_node_ids = set(schedule)
    
    if all_node_ids != schedule_node_ids:
        missing_nodes = all_node_ids - schedule_node_ids
        extra_nodes = schedule_node_ids - all_node_ids
        if missing_nodes:
            print(f"  错误：缺少节点 {missing_nodes}")
        if extra_nodes:
            print(f"  错误：多余节点 {extra_nodes}")
        return False
    
    # 检查依赖约束
    node_positions = {node_id: i for i, node_id in enumerate(schedule)}
    
    for buf_id, lifecycle in buf_lifecycle.items():
        alloc_node = lifecycle['alloc']
        free_node = lifecycle['free']
        producers = lifecycle['producers']
        consumers = lifecycle['consumers']
        
        # ALLOC必须在producers之前
        if alloc_node in node_positions:
            alloc_pos = node_positions[alloc_node]
            for prod in producers:
                if prod in node_positions and node_positions[prod] < alloc_pos:
                    print(f"  错误：生产者节点 {prod} 在分配节点 {alloc_node} 之前")
                    return False
        
        # producers必须在consumers之前
        for prod in producers:
            if prod in node_positions:
                prod_pos = node_positions[prod]
                for cons in consumers:
                    if cons in node_positions and node_positions[cons] < prod_pos:
                        print(f"  错误：消费者节点 {cons} 在生产者节点 {prod} 之前")
                        return False
        
        # consumers必须在FREE之前
        if free_node is not None and free_node in node_positions:
            free_pos = node_positions[free_node]
            for cons in consumers:
                if cons in node_positions and node_positions[cons] > free_pos:
                    # 检查消费者节点是否使用了被释放的缓冲区
                    cons_node = nodes.get(cons, {})
                    free_node_obj = nodes.get(free_node, {})
                    cons_bufs = cons_node.get('Bufs', [])
                    free_buf_id = free_node_obj.get('BufId')
                    
                    # 只有当消费者节点使用了被释放的缓冲区时，才需要检查顺序
                    if free_buf_id in cons_bufs:
                        print(f"  错误：消费者节点 {cons} 在释放节点 {free_node} 之后")
                        return False
    
    print("  调度序列验证通过")
    return True

def validate_memory_allocation(addr_alloc, nodes, cache_config):
    """验证内存分配的正确性""" 
    print("正在验证内存分配...")
    
    # 找到所有ALLOC节点
    alloc_nodes = {node['BufId']: node for node in nodes.values() if node.get('Op') == 'ALLOC'}
    
    # 检查地址不重叠
    cache_buffers = defaultdict(list)
    for buf_id, addr in addr_alloc.items():
        if buf_id in alloc_nodes:
            alloc_node = alloc_nodes[buf_id]
            cache_type = alloc_node['Type']
            size = alloc_node['Size']
            cache_buffers[cache_type].append({
                'buf_id': buf_id,
                'start': addr,
                'end': addr + size - 1,
                'size': size,
                'cache_type': cache_type  # 添加缓存类型信息
            })
    
    # 检查每种缓存类型的地址重叠
    for cache_type, buffers in cache_buffers.items():
        capacity = cache_config.get(cache_type, float('inf'))
        buffers.sort(key=lambda x: x['start'])
        
        for i in range(len(buffers) - 1):
            if buffers[i]['end'] >= buffers[i+1]['start']:
                print(f"  错误：缓存类型 {cache_type} 中缓冲区 {buffers[i]['buf_id']} 和 {buffers[i+1]['buf_id']} 地址重叠")
                return False
        
        # 检查是否超出缓存容量
        if buffers and capacity != float('inf'):
            max_addr = max(buf['end'] for buf in buffers)
            if max_addr >= capacity:
                print(f"  错误：缓存类型 {cache_type} 超出容量限制 (最大地址: {max_addr}, 容量: {capacity})")
                return False
    
    # 检查L0缓存特殊约束：L0A/L0B/L0C缓存各自同时最多仅1个缓冲区驻留
    # 这个约束是指L0A、L0B、L0C各自最多只能有一个缓冲区驻留
    l0_cache_types = ['L0A', 'L0B', 'L0C']
    for cache_type in l0_cache_types:
        if cache_type in cache_buffers and len(cache_buffers[cache_type]) > 1:
            print(f"  错误：{cache_type} 缓存类型同时驻留了 {len(cache_buffers[cache_type])} 个缓冲区，违反L0缓存约束")
            # 列出具体的缓冲区信息
            for buf in cache_buffers[cache_type]:
                print(f"    缓冲区 {buf['buf_id']} 在 {buf['start']}-{buf['end']} 地址范围")
            return False
    
    print("  内存分配验证通过")
    return True

def validate_l0_cache_constraints_detailed(schedule, nodes, buf_lifecycle, addr_alloc):
    """详细验证L0缓存约束：在任何时刻L0A/L0B/L0C缓存中各自最多只能有一个缓冲区驻留"""
    print("正在验证L0缓存详细约束...")
    
    # 找到所有L0缓存的缓冲区，并按缓存类型分类
    l0_buf_ids = {'L0A': set(), 'L0B': set(), 'L0C': set()}
    buf_to_cache_type = {}  # buf_id -> cache_type
    
    for node in nodes.values():
        if node.get('Op') == 'ALLOC' and node.get('Type') in ['L0A', 'L0B', 'L0C']:
            buf_id = node['BufId']
            cache_type = node['Type']
            l0_buf_ids[cache_type].add(buf_id)
            buf_to_cache_type[buf_id] = cache_type
    
    # 构建时间线：记录每个时刻每种L0缓存类型中驻留的缓冲区
    timeline = defaultdict(lambda: defaultdict(set))  # time -> cache_type -> set of buffer ids
    
    # 遍历调度序列，记录每个缓冲区的生命周期
    # 使用调度序列中的位置作为时间
    for time, node_id in enumerate(schedule):
        if node_id in nodes:
            node = nodes[node_id]
            if node.get('Op') == 'ALLOC' and node.get('BufId') in buf_to_cache_type:
                buf_id = node['BufId']
                cache_type = buf_to_cache_type[buf_id]
                # 缓冲区开始驻留
                alloc_time = time  # 使用调度序列中的位置作为时间
                if buf_id in buf_lifecycle and buf_lifecycle[buf_id]['free']:
                    free_node_id = buf_lifecycle[buf_id]['free']
                    # 找到释放节点在调度序列中的位置
                    if free_node_id in schedule:
                        free_time = schedule.index(free_node_id)
                        # 在这个时间段内，缓冲区驻留
                        for t in range(alloc_time, free_time + 1):
                            timeline[t][cache_type].add(buf_id)
    
    # 检查时间线中是否有违反约束的时刻
    for time, cache_types in timeline.items():
        for cache_type, buf_ids in cache_types.items():
            if len(buf_ids) > 1:
                print(f"  错误：在时刻 {time}，{cache_type} 缓存中有 {len(buf_ids)} 个缓冲区同时驻留: {sorted(buf_ids)}")
                # 找到具体的节点ID以便调试
                if time < len(schedule):
                    node_id = schedule[time]
                    print(f"    时刻对应节点ID: {node_id}")
                return False
    
    print("  L0缓存详细约束验证通过")
    return True

def validate_spill_operations(spill_list, nodes):
    """验证SPILL操作的正确性"""
    print("正在验证SPILL操作...")
    
    # 检查SPILL操作中的缓冲区ID是否有效
    alloc_buf_ids = {node['BufId'] for node in nodes.values() if node.get('Op') == 'ALLOC'}
    
    for buf_id, new_offset in spill_list:
        if buf_id not in alloc_buf_ids:
            print(f"  错误：SPILL操作中的缓冲区ID {buf_id} 无效")
            return False
    
    print("  SPILL操作验证通过")
    return True

def calculate_performance_metrics(schedule, nodes, buf_lifecycle, addr_alloc, spill_list):
    """计算性能指标"""
    print("正在计算性能指标...")
    
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
    
    # 计算SPILL成本
    total_spill_cost = 0
    for buf_id, new_offset in spill_list:
        # 获取缓冲区大小
        buf_size = None
        for node in nodes.values():
            if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                buf_size = node['Size']
                break
        if buf_size is not None:
            total_spill_cost += buf_size * 2
    
    print(f"  总执行时间: {total_time}")
    print(f"  额外数据搬运量: {total_spill_cost}")
    
    return {
        'total_exec_time': total_time,
        'total_spill_cost': total_spill_cost
    }

def validate_optimization_results(case_name, graph_path, cache_config, baseline_time=None, baseline_spill_cost=None):
    """验证优化结果的有效性"""
    print(f"开始验证 {case_name} 的优化结果...")
    
    # 加载计算图
    try:
        with open(graph_path, 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        nodes = {n['Id']: n for n in graph_data['Nodes']}
    except FileNotFoundError:
        print(f"错误：找不到计算图文件 {graph_path}")
        return False
    except json.JSONDecodeError:
        print(f"错误：计算图文件 {graph_path} 格式不正确")
        return False
    
    # 加载优化后的结果
    schedule_path = f'{case_name}_schedule.txt'
    memory_path = f'{case_name}_memory.txt'
    spill_path = f'{case_name}_spill.txt'
    
    try:
        optimized_schedule = load_schedule(schedule_path)
        optimized_addr_alloc = load_memory_allocation(memory_path)
        optimized_spill_list = load_spill_operations(spill_path)
    except FileNotFoundError as e:
        print(f"错误：找不到文件 {e.filename}")
        return False
    except Exception as e:
        print(f"错误：读取文件时发生异常 {e}")
        return False
    
    # 计算缓冲区生命周期
    buf_lifecycle = get_buf_lifecycle(optimized_schedule, nodes)
    
    # 验证各项约束
    schedule_valid = validate_schedule_order(optimized_schedule, nodes, buf_lifecycle)
    memory_valid = validate_memory_allocation(optimized_addr_alloc, nodes, cache_config)
    spill_valid = validate_spill_operations(optimized_spill_list, nodes)
    
    # 详细验证L0缓存约束
    l0_valid = validate_l0_cache_constraints_detailed(optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc)
    
    # 计算性能指标
    metrics = calculate_performance_metrics(
        optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc, optimized_spill_list
    )
    
    # 总体验证结果
    overall_valid = schedule_valid and memory_valid and spill_valid and l0_valid
    
    print(f"\n验证结果:")
    print(f"  调度序列: {'通过' if schedule_valid else '失败'}")
    print(f"  内存分配: {'通过' if memory_valid else '失败'}")
    print(f"  SPILL操作: {'通过' if spill_valid else '失败'}")
    print(f"  L0缓存约束: {'通过' if l0_valid else '失败'}")
    print(f"  总体结果: {'通过' if overall_valid else '失败'}")
    print(f"  总执行时间: {metrics['total_exec_time']}")
    print(f"  额外数据搬运量: {metrics['total_spill_cost']}")
    
    # 如果提供了基线数据，验证优化效果
    if baseline_time is not None and baseline_spill_cost is not None:
        time_improvement = (baseline_time - metrics['total_exec_time']) / baseline_time if baseline_time > 0 else 0
        spill_cost_increase = (metrics['total_spill_cost'] - baseline_spill_cost) / baseline_spill_cost if baseline_spill_cost > 0 else 0
        
        print(f"\n优化效果分析:")
        print(f"  时间改善: {time_improvement:.1%}")
        print(f"  SPILL成本增加: {spill_cost_increase:.1%}")
        
        # 检查是否满足问题3的要求：总额外数据搬运量不显著增加，最小化总执行时间
        if spill_cost_increase <= 0.1:  # SPILL成本增加不超过10%
            print(f"  SPILL成本约束: 满足 (增加 <= 10%)")
        else:
            print(f"  SPILL成本约束: 不满足 (增加 > 10%)")
            overall_valid = False
        
        if time_improvement > 0:  # 时间有所改善
            print(f"  时间优化: 满足 (有改善)")
        else:
            print(f"  时间优化: 不满足 (无改善)")
    
    return overall_valid

def main():
    """主函数"""
    cache_config = {
        'L1': 4096,
        'UB': 1024,
        'L0A': 256,
        'L0B': 256,
        'L0C': 512
    }
    
    case_name = 'FlashAttention_Case0'
    graph_path = '1.json'
    
    # 如果有基线数据，可以传入进行优化效果分析
    # 基线数据示例（需要根据实际结果替换）
    # baseline_time = 888535
    # baseline_spill_cost = 29312
    # validate_optimization_results(case_name, graph_path, cache_config, baseline_time, baseline_spill_cost)
    
    validate_optimization_results(case_name, graph_path, cache_config)

if __name__ == "__main__":
    main()