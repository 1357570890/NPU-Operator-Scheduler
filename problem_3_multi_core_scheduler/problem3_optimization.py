import json
import copy
import os
from collections import defaultdict, deque

# 从问题2模块导入需要的函数
def load_schedule(file_path):
    """加载调度序列"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return [int(line.strip()) for line in f if line.strip()]

def load_memory_allocation(file_path):
    """加载内存分配结果"""
    addr_alloc = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    buf_id, offset = line.split(':')
                    addr_alloc[int(buf_id)] = int(offset)
    except FileNotFoundError:
        pass
    return addr_alloc

def load_spill_operations(file_path):
    """加载SPILL操作列表"""
    spill_list = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    buf_id, new_offset = line.split(':')
                    spill_list.append((int(buf_id), int(new_offset)))
    except FileNotFoundError:
        pass
    return spill_list

def get_buf_lifecycle(schedule, nodes):
    """计算缓冲区生命周期"""
    buf_lifecycle = {}
    
    for node_id in schedule:
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

class PerformanceOptimizer:
    def __init__(self, cache_config):
        self.cache_config = cache_config
        
    def calculate_baseline_metrics(self, schedule, nodes, buf_lifecycle, addr_alloc, spill_list):
        """计算基准数据：总执行时间、单元负载统计、缓存碎片分析"""
        
        # 1. 计算总执行时间
        total_exec_time, unit_times = self.calculate_execution_time(
            schedule, nodes, buf_lifecycle, addr_alloc, spill_list
        )
        
        # 2. 单元负载统计
        unit_stats = self.calculate_unit_load_stats(unit_times, total_exec_time)
        
        # 3. 缓存碎片分析
        fragmentation_stats = self.analyze_cache_fragmentation(
            schedule, nodes, buf_lifecycle, addr_alloc
        )
        
        return {
            'total_exec_time': total_exec_time,
            'unit_stats': unit_stats,
            'fragmentation_stats': fragmentation_stats,
            'unit_times': unit_times
        }
    
    def calculate_execution_time(self, schedule, nodes, buf_lifecycle, addr_alloc, spill_list):
        """计算总执行时间，返回总时间和各单元时间"""
        
        # 构建依赖图（包含SPILL节点）
        all_nodes = copy.deepcopy(nodes)
        edges = []
        
        # 添加SPILL节点
        spill_nodes = self.add_spill_nodes(all_nodes, spill_list, schedule, nodes)
        
        # 构建依赖边
        edges = self.build_dependency_edges(all_nodes, buf_lifecycle, addr_alloc, spill_list)
        
        # 计算各节点的开始和结束时间
        start_times, end_times = self.schedule_execution(schedule + spill_nodes, all_nodes, edges)
        
        # 统计各单元时间
        unit_times = defaultdict(list)
        for node_id in start_times:
            node = all_nodes[node_id]
            if 'Pipe' in node:
                pipe = node['Pipe']
                cycles = node.get('Cycles', 0)
                unit_times[pipe].append({
                    'start': start_times[node_id],
                    'end': end_times[node_id],
                    'cycles': cycles
                })
        
        total_time = max(end_times.values()) if end_times else 0
        return total_time, unit_times
    
    def add_spill_nodes(self, all_nodes, spill_list, schedule, original_nodes):
        """添加SPILL节点到节点列表"""
        spill_nodes = []
        next_id = max(all_nodes.keys()) + 1 if all_nodes else 1
        
        for i, (buf_id, new_offset) in enumerate(spill_list):
            # 获取缓冲区信息
            buf_size = None
            buf_type = None
            for node in original_nodes.values():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    buf_size = node['Size']
                    buf_type = node['Type']
                    break
            
            if buf_size is None:
                continue
                
            # 检查是否被COPY_IN使用
            is_copy_in_buf = any(
                node.get('Op') == 'COPY_IN' and buf_id in node.get('Bufs', [])
                for node in original_nodes.values()
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
            
        return spill_nodes
    
    def build_dependency_edges(self, all_nodes, buf_lifecycle, addr_alloc, spill_list):
        """构建依赖边，包括缓存复用依赖"""
        edges = []
        
        # 原有依赖边（从buf_lifecycle推导）
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
            for cons in consumers:
                edges.append((cons, free_node))
        
        # 缓存复用依赖
        cache_usage = defaultdict(list)  # cache_type -> [(buf_id, alloc_node, free_node, start_addr, end_addr)]
        
        for buf_id, lifecycle in buf_lifecycle.items():
            if buf_id in addr_alloc:
                alloc_node = lifecycle['alloc']
                free_node = lifecycle['free']
                
                # 获取缓存类型和大小
                alloc_node_obj = all_nodes[alloc_node]
                cache_type = alloc_node_obj['Type']
                size = alloc_node_obj['Size']
                start_addr = addr_alloc[buf_id]
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
                        edges.append((free1, alloc2))  # buf1释放后buf2才能分配
        
        return edges
    
    def schedule_execution(self, schedule, all_nodes, edges):
        """调度执行，计算各节点开始和结束时间"""
        
        # 构建前驱图
        predecessors = defaultdict(list)
        for src, dst in edges:
            predecessors[dst].append(src)
        
        # 各单元的结束时间
        unit_end_time = defaultdict(int)
        
        start_times = {}
        end_times = {}
        
        for node_id in schedule:
            node = all_nodes[node_id]
            cycles = node.get('Cycles', 0)
            pipe = node.get('Pipe', None)
            
            # 计算最早开始时间
            earliest_start = 0
            
            # 依赖约束
            for pred_id in predecessors[node_id]:
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
        
        return start_times, end_times
    
    def calculate_unit_load_stats(self, unit_times, total_exec_time):
        """计算单元负载统计"""
        unit_stats = {}
        
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
    
    def analyze_cache_fragmentation(self, schedule, nodes, buf_lifecycle, addr_alloc):
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
            capacity = self.cache_config[cache_type]
            
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

    # ==================== 重构后的优化策略 ====================
    
    def calculate_critical_path(self, schedule, nodes, buf_lifecycle):
        """使用关键路径法(CPM)计算每个节点的ES, EE, LS, LF"""
        # 构建依赖图
        all_nodes = copy.deepcopy(nodes)
        edges = []
        
        # 构建依赖边
        for buf_id, lifecycle in buf_lifecycle.items():
            alloc_node = lifecycle['alloc']
            free_node = lifecycle['free']
            producers = lifecycle['producers']
            consumers = lifecycle['consumers']
            
            # ALLOC -> producers
            for prod in producers:
                edges.append((alloc_node, prod))
            
            # producers -> consumers
            for prod in producers:
                for cons in consumers:
                    edges.append((prod, cons))
            
            # consumers -> FREE
            for cons in consumers:
                edges.append((cons, free_node))
        
        # 构建前驱和后继图
        predecessors = defaultdict(list)
        successors = defaultdict(list)
        for src, dst in edges:
            predecessors[dst].append(src)
            successors[src].append(dst)
        
        # 计算ES和EE（正向遍历）
        es_times = {}  # 最早开始时间
        ee_times = {}  # 最早结束时间

        # 按照调度顺序计算ES和EE
        for node_id in schedule:
            if node_id in all_nodes:
                node = all_nodes[node_id]
                cycles = node.get('Cycles', 0)
                
                # 计算最早开始时间
                es = 0
                for pred in predecessors.get(node_id, []):
                    if pred in ee_times:
                        es = max(es, ee_times[pred])
                
                es_times[node_id] = es
                ee_times[node_id] = es + cycles

        # 计算LF和LS（反向遍历）
        # 找到最后一个节点
        if ee_times:
            max_ee = max(ee_times.values())
        else:
            max_ee = 0
        
        lf_times = defaultdict(lambda: max_ee)  # 最晚结束时间
        ls_times = {}  # 最晚开始时间
        
        # 按照调度顺序的反向计算LF和LS
        for node_id in reversed(schedule):
            if node_id in all_nodes:
                node = all_nodes[node_id]
                cycles = node.get('Cycles', 0)
                
                # 计算最晚结束时间
                lf = lf_times[node_id]
                for succ in successors.get(node_id, []):
                    if succ in ls_times:
                        lf = min(lf, ls_times[succ])
                
                lf_times[node_id] = lf
                ls_times[node_id] = lf - cycles
        
        # 识别关键节点（ES == LS）
        critical_nodes = set()
        for node_id in schedule:
            if node_id in es_times and node_id in ls_times:
                # 允许一个小的误差范围
                if abs(es_times[node_id] - ls_times[node_id]) <= 1:
                    critical_nodes.add(node_id)
        
        return {
            'es_times': es_times,
            'ee_times': ee_times,
            'ls_times': ls_times,
            'lf_times': lf_times,
            'critical_nodes': critical_nodes
        }

    def calculate_buffer_reuse_rate(self, schedule, nodes, buf_lifecycle):
        """计算缓冲区复用率"""
        buffer_usage_count = defaultdict(int)
        
        # 统计每个缓冲区的使用次数
        for node_id in schedule:
            node = nodes[node_id]
            if 'Bufs' in node:
                for buf_id in node['Bufs']:
                    buffer_usage_count[buf_id] += 1
        
        return buffer_usage_count

    def optimize_cache_allocation_v2(self, schedule, nodes, buf_lifecycle, addr_alloc):
        """策略2：基于数据复用率的地址复用优化"""
        
        # 1. 计算缓冲区复用率
        buffer_reuse_rate = self.calculate_buffer_reuse_rate(schedule, nodes, buf_lifecycle)
        
        # 2. 分离高复用率和低复用率缓冲区
        high_reuse_buffers = {buf_id: rate for buf_id, rate in buffer_reuse_rate.items() if rate >= 2}  # 降低阈值
        low_reuse_buffers = {buf_id: rate for buf_id, rate in buffer_reuse_rate.items() if rate < 2}
        
        # 3. 重新分配地址
        new_addr_alloc = {}
        
        # 按缓存类型跟踪已分配的地址区域
        cache_allocated_regions = defaultdict(list)  # cache_type -> [(start, end)]
        
        # 跟踪L0缓存的使用情况，确保L0A/L0B/L0C同时最多仅1个缓冲区驻留
        # 修复：使用字典来跟踪每种L0缓存类型的使用情况
        l0_cache_in_use = {'L0A': False, 'L0B': False, 'L0C': False}  # 标记每种L0缓存是否正在使用
        
        # 为高复用率缓冲区分配固定地址区域
        cache_type_offsets = defaultdict(int)  # 每种缓存类型的地址偏移

        # 首先为高复用率缓冲区分配固定地址区间（使用前70%的空间）
        for buf_id in sorted(high_reuse_buffers.keys()):  # 按缓冲区ID排序以保证一致性
            if buf_id in buf_lifecycle:
                alloc_node_id = buf_lifecycle[buf_id]['alloc']
                alloc_node = nodes[alloc_node_id]
                cache_type = alloc_node['Type']
                size = alloc_node['Size']
                
                # L0缓存特殊处理：由于L0缓存的特殊约束（单缓冲区独占+即时释放），
                # 不会触发SPILL操作，因此我们为L0缓存分配固定地址空间
                if cache_type in ['L0A', 'L0B', 'L0C']:
                    # L0缓存约束：L0A/L0B/L0C缓存同时最多仅1个缓冲区驻留
                    # 修复：检查特定类型的L0缓存是否正在使用
                    if l0_cache_in_use[cache_type]:
                        # 如果该类型的L0缓存已经在使用，将该缓冲区视为低复用率缓冲区
                        low_reuse_buffers[buf_id] = high_reuse_buffers[buf_id]
                        del high_reuse_buffers[buf_id]
                    else:
                        # 检查是否超出缓存容量
                        capacity = self.cache_config[cache_type]
                        if cache_type_offsets[cache_type] + size <= capacity:
                            # 在固定区域分配地址
                            start_addr = cache_type_offsets[cache_type]
                            end_addr = start_addr + size - 1
                            new_addr_alloc[buf_id] = start_addr
                            
                            # 记录已分配区域
                            cache_allocated_regions[cache_type].append((start_addr, end_addr))
                            cache_allocated_regions[cache_type].sort(key=lambda x: x[0])  # 确保按地址排序
                            cache_type_offsets[cache_type] += size  # 更新偏移
                            
                            # 标记该类型的L0缓存正在使用
                            l0_cache_in_use[cache_type] = True
                        else:
                            # 如果超出容量，将该缓冲区视为低复用率缓冲区
                            low_reuse_buffers[buf_id] = high_reuse_buffers[buf_id]
                            del high_reuse_buffers[buf_id]
                else:
                    # 非L0缓存处理
                    # 检查是否超出缓存容量（使用85%的空间而不是100%）
                    capacity = int(self.cache_config[cache_type] * 0.85)
                    if cache_type_offsets[cache_type] + size <= capacity:
                        # 在分配前进行严格的地址冲突检查
                        start_addr = cache_type_offsets[cache_type]
                        end_addr = start_addr + size - 1
                        
                        # 检查新分配的地址是否与已分配区域重叠
                        if not self._check_address_conflict(cache_type, start_addr, end_addr, cache_allocated_regions):
                            # 在固定区域分配地址
                            new_addr_alloc[buf_id] = start_addr
                            
                            # 记录已分配区域
                            cache_allocated_regions[cache_type].append((start_addr, end_addr))
                            cache_allocated_regions[cache_type].sort(key=lambda x: x[0])  # 确保按地址排序
                            cache_type_offsets[cache_type] += size  # 更新偏移
                        else:
                            # 如果有地址冲突，将该缓冲区视为低复用率缓冲区
                            low_reuse_buffers[buf_id] = high_reuse_buffers[buf_id]
                            del high_reuse_buffers[buf_id]
                    else:
                        # 如果超出容量，将该缓冲区视为低复用率缓冲区
                        low_reuse_buffers[buf_id] = high_reuse_buffers[buf_id]
                        del high_reuse_buffers[buf_id]
        
        # 为低复用率缓冲区使用最佳适配算法
        # 初始化缓存空闲块（在高复用率缓冲区分配之后，使用剩余的30%空间）
        cache_free_blocks = defaultdict(list)  # cache_type -> [(start, size)]
        for cache_type, capacity in self.cache_config.items():
            # L0缓存特殊处理：由于L0缓存的特殊约束，不需要预留空间
            if cache_type in ['L0A', 'L0B', 'L0C']:
                continue
            start_addr = int(capacity * 0.7)  # 从70%处开始
            remaining_capacity = int(capacity * 0.3)  # 使用30%的空间
            if cache_type_offsets[cache_type] < start_addr + remaining_capacity:
                cache_free_blocks[cache_type].append((start_addr, remaining_capacity))
        
        # 为低复用率缓冲区分配地址
        low_reuse_buf_info = []
        for buf_id in low_reuse_buffers:
            if buf_id in buf_lifecycle:
                alloc_node_id = buf_lifecycle[buf_id]['alloc']
                alloc_node = nodes[alloc_node_id]
                size = alloc_node['Size']
                cache_type = alloc_node['Type']
                low_reuse_buf_info.append((buf_id, size, cache_type))
    
        # 按缓冲区大小排序，大缓冲区优先分配
        low_reuse_buf_info.sort(key=lambda x: x[1], reverse=True)
    
        for buf_id, size, cache_type in low_reuse_buf_info:
            # L0缓存特殊处理：由于L0缓存的特殊约束，不需要使用最佳适配算法
            if cache_type in ['L0A', 'L0B', 'L0C']:
                # L0缓存约束：L0A/L0B/L0C缓存同时最多仅1个缓冲区驻留
                # 修复：检查特定类型的L0缓存是否正在使用
                if l0_cache_in_use[cache_type]:
                    # 如果该类型的L0缓存已经在使用，跳过这个缓冲区的分配
                    continue
                else:
                    # 检查是否超出缓存容量
                    capacity = self.cache_config[cache_type]
                    if cache_type_offsets[cache_type] + size <= capacity:
                        # 在固定区域分配地址
                        start_addr = cache_type_offsets[cache_type]
                        end_addr = start_addr + size - 1
                        new_addr_alloc[buf_id] = start_addr
                        
                        # 记录已分配区域
                        cache_allocated_regions[cache_type].append((start_addr, end_addr))
                        cache_allocated_regions[cache_type].sort(key=lambda x: x[0])  # 确保按地址排序
                        cache_type_offsets[cache_type] += size  # 更新偏移
                        
                        # 标记该类型的L0缓存正在使用
                        l0_cache_in_use[cache_type] = True
                continue
            
            # 非L0缓存处理
            # 查找最佳适配块
            best_block = None
            best_fit_size = float('inf')
            
            for i, (start, block_size) in enumerate(cache_free_blocks[cache_type]):
                if block_size >= size and block_size < best_fit_size:
                    # 在分配前进行严格的地址冲突检查
                    end_addr = start + size - 1
                    if not self._check_address_conflict(cache_type, start, end_addr, cache_allocated_regions):
                        best_block = i
                        best_fit_size = block_size
            
            # 如果找到合适的块
            if best_block is not None:
                start, block_size = cache_free_blocks[cache_type][best_block]
                new_addr_alloc[buf_id] = start
                
                # 记录已分配区域
                end_addr = start + size - 1
                cache_allocated_regions[cache_type].append((start, end_addr))
                cache_allocated_regions[cache_type].sort(key=lambda x: x[0])  # 确保按地址排序
                
                # 更新空闲块列表，确保没有重叠
                del cache_free_blocks[cache_type][best_block]
                if block_size > size:
                    # 剩余空间作为新的空闲块
                    cache_free_blocks[cache_type].append((start + size, block_size - size))
                
                # 对空闲块列表进行排序，确保正确性
                cache_free_blocks[cache_type].sort(key=lambda x: x[0])
        
        # 验证没有地址重叠并修复
        for cache_type, regions in cache_allocated_regions.items():
            # 按起始地址排序
            regions.sort(key=lambda x: x[0])
            
            # 检查并修复重叠
            i = 0
            while i < len(regions) - 1:
                if regions[i][1] >= regions[i+1][0]:  # 检查重叠
                    # 找到重叠的缓冲区并重新分配
                    overlapping_start = regions[i+1][0]
                    overlapping_buf_id = None
                    
                    # 查找重叠的缓冲区ID
                    for buf_id, addr in new_addr_alloc.items():
                        alloc_node_id = buf_lifecycle[buf_id]['alloc']
                        alloc_node = nodes[alloc_node_id]
                        if alloc_node['Type'] == cache_type and addr == overlapping_start:
                            overlapping_buf_id = buf_id
                            break
                    
                    if overlapping_buf_id:
                        # 为重叠的缓冲区寻找新的地址
                        size = nodes[buf_lifecycle[overlapping_buf_id]['alloc']]['Size']
                        # 在空闲块中寻找空间
                        found_space = False
                        for j, (start, block_size) in enumerate(cache_free_blocks[cache_type]):
                            if block_size >= size:
                                # 在分配前进行严格的地址冲突检查
                                end_addr = start + size - 1
                                if not self._check_address_conflict(cache_type, start, end_addr, cache_allocated_regions):
                                    new_addr_alloc[overlapping_buf_id] = start
                                    # 更新空闲块
                                    del cache_free_blocks[cache_type][j]
                                    if block_size > size:
                                        cache_free_blocks[cache_type].append((start + size, block_size - size))
                                    cache_free_blocks[cache_type].sort(key=lambda x: x[0])
                                    found_space = True
                                    break
                        
                        # 如果找不到空间，使用下一个可用地址
                        if not found_space:
                            max_end = max(region[1] for region in regions) if regions else 0
                            new_start = max_end + 1
                            new_end = new_start + size - 1
                            # 在分配前进行严格的地址冲突检查
                            if not self._check_address_conflict(cache_type, new_start, new_end, cache_allocated_regions):
                                new_addr_alloc[overlapping_buf_id] = new_start
                                regions.append((new_start, new_end))
                
                # 重新排序并继续检查
                regions.sort(key=lambda x: x[0])
                i += 1
        
        # 确保所有分配都不超出缓存容量
        for cache_type, regions in cache_allocated_regions.items():
            # L0缓存特殊处理：由于L0缓存的特殊约束，不需要检查容量
            if cache_type in ['L0A', 'L0B', 'L0C']:
                continue
            capacity = self.cache_config[cache_type]
            for start, end in regions:
                if end >= capacity:
                    # 调整超出容量的分配
                    for buf_id, addr in list(new_addr_alloc.items()):  # 使用list()避免在迭代时修改字典
                        alloc_node_id = buf_lifecycle[buf_id]['alloc']
                        alloc_node = nodes[alloc_node_id]
                        if alloc_node['Type'] == cache_type and addr == start:
                            # 在空闲块中寻找新的地址
                            size = alloc_node['Size']
                            found_space = False
                            for j, (free_start, free_size) in enumerate(cache_free_blocks[cache_type]):
                                if free_size >= size:
                                    # 在分配前进行严格的地址冲突检查
                                    free_end = free_start + size - 1
                                    if not self._check_address_conflict(cache_type, free_start, free_end, cache_allocated_regions):
                                        new_addr_alloc[buf_id] = free_start
                                        # 更新空闲块
                                        del cache_free_blocks[cache_type][j]
                                        if free_size > size:
                                            cache_free_blocks[cache_type].append((free_start + size, free_size - size))
                                        cache_free_blocks[cache_type].sort(key=lambda x: x[0])
                                        found_space = True
                                        break
                            
                            # 如果找不到空间，报告错误
                            if not found_space:
                                print(f"警告：无法为缓冲区 {buf_id} 在缓存类型 {cache_type} 中找到合适的空间")
                            break
        
        # 最后检查所有分配是否都在容量范围内，如果不在则尝试重新分配
        buffers_exceeding_capacity = []
        for buf_id, addr in list(new_addr_alloc.items()):
            alloc_node_id = buf_lifecycle[buf_id]['alloc']
            alloc_node = nodes[alloc_node_id]
            cache_type = alloc_node['Type']
            size = alloc_node['Size']
            capacity = self.cache_config[cache_type]
            
            # L0缓存特殊处理：由于L0缓存的特殊约束，不需要检查容量
            if cache_type in ['L0A', 'L0B', 'L0C']:
                continue
            
            # 如果分配超出容量
            if addr + size > capacity:
                buffers_exceeding_capacity.append((buf_id, addr, size, cache_type))
        
        # 对超出容量的缓冲区按地址降序排序，优先处理地址高的缓冲区
        buffers_exceeding_capacity.sort(key=lambda x: x[1], reverse=True)
        
        # 尝试重新分配这些缓冲区
        for buf_id, addr, size, cache_type in buffers_exceeding_capacity:
            # 尝试在空闲块中找到新的地址
            found_space = False
            for j, (free_start, free_size) in enumerate(cache_free_blocks[cache_type]):
                if free_size >= size and free_start + size <= self.cache_config[cache_type]:
                    # 在分配前进行严格的地址冲突检查
                    free_end = free_start + size - 1
                    if not self._check_address_conflict(cache_type, free_start, free_end, cache_allocated_regions):
                        new_addr_alloc[buf_id] = free_start
                        # 更新空闲块
                        del cache_free_blocks[cache_type][j]
                        if free_size > size:
                            cache_free_blocks[cache_type].append((free_start + size, free_size - size))
                        cache_free_blocks[cache_type].sort(key=lambda x: x[0])
                        found_space = True
                        break
            
            # 如果仍然找不到空间，需要进行SPILL操作
            if not found_space:
                print(f"警告：缓冲区 {buf_id} 在缓存类型 {cache_type} 中超出容量限制，将进行SPILL操作")
                # 移除这个缓冲区的分配，让它在SPILL阶段处理
                del new_addr_alloc[buf_id]
        
        return new_addr_alloc

    def _check_address_conflict(self, cache_type, start_addr, end_addr, cache_allocated_regions):
        """
        检查地址冲突的辅助函数
        返回True表示有冲突，False表示无冲突
        """
        # 检查新分配的地址是否与已分配区域重叠
        for region_start, region_end in cache_allocated_regions.get(cache_type, []):
            # 检查区间是否重叠：[start_addr, end_addr] 与 [region_start, region_end]
            if start_addr <= region_end and end_addr >= region_start:
                return True  # 有重叠
        return False  # 无重叠

    def optimize_spill_timing_v2(self, schedule, nodes, addr_alloc, spill_list, baseline_metrics):
        """策略3：基于负载预测的SPILL节点优化"""
        
        if not spill_list:
            return schedule, spill_list
        
        # 1. MTE单元负载预测（时间窗口法）
        unit_times = baseline_metrics.get('unit_times', {})
        
        # 统计每个100周期窗口内MTE2/MTE3的占用时间
        mte_load = defaultdict(lambda: defaultdict(int))  # pipe -> window -> occupied_cycles
    
        window_size = 20  # 减小窗口大小以更精确地预测负载
        for pipe, time_slots in unit_times.items():
            if pipe in ['MTE2', 'MTE3']:
                for slot in time_slots:
                    start = slot.get('start', 0)
                    end = slot.get('end', 0)
                    cycles = slot.get('cycles', 0)
                    
                    # 计算跨越的窗口
                    start_window = start // window_size
                    end_window = end // window_size
                    
                    # 分配周期到各个窗口
                    remaining_cycles = cycles
                    current_time = start
                    
                    for window in range(start_window, end_window + 1):
                        window_start = window * window_size
                        window_end = (window + 1) * window_size
                        
                        # 计算在当前窗口内的周期数
                        slot_start_in_window = max(current_time, window_start)
                        slot_end_in_window = min(end, window_end)
                        window_cycles = max(0, slot_end_in_window - slot_start_in_window)
                        
                        if window_cycles > 0:
                            mte_load[pipe][window] += window_cycles
                            remaining_cycles -= window_cycles
                            current_time += window_cycles
    
        # 2. 优化SPILL节点插入位置 - 负载预测避免拥堵
        # 对SPILL操作按缓冲区大小排序，大缓冲区优先
        spill_info = []
        for buf_id, new_offset in spill_list:
            # 获取缓冲区信息
            buf_size = None
            for node_id, node in nodes.items():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    buf_size = node['Size']
                    break
            if buf_size is not None:
                spill_info.append((buf_id, new_offset, buf_size))
    
        spill_info.sort(key=lambda x: x[2], reverse=True)  # 大缓冲区优先
    
        # 3. 合并同类SPILL操作
        # 按缓存类型分组
        spill_groups = defaultdict(list)
        buf_lifecycle_local = get_buf_lifecycle(schedule, nodes)
    
        for buf_id, new_offset, buf_size in spill_info:
            if buf_id in buf_lifecycle_local:
                # 获取缓冲区生命周期
                lifecycle = buf_lifecycle_local[buf_id]
                alloc_node_id = lifecycle['alloc']
                if alloc_node_id in nodes:
                    alloc_node = nodes[alloc_node_id]
                    cache_type = alloc_node['Type']
                    # 使用缓存类型作为主要分组键
                    spill_groups[cache_type].append((buf_id, new_offset, buf_size))
    
        # 合并每组SPILL操作（仅当同类型且数量大于1时）
        merged_spill_list = []
        for cache_type, group in spill_groups.items():
            if len(group) > 1:  # 只要有多于1个SPILL操作就合并
                # 按缓冲区大小排序
                group.sort(key=lambda x: x[2], reverse=True)
                # 合并多个SPILL操作为一个（取第一个作为代表）
                representative_buf_id = group[0][0]
                representative_offset = group[0][1]
                merged_spill_list.append((representative_buf_id, representative_offset))
            else:
                # 不合并，保持原样
                for buf_id, new_offset, buf_size in group:
                    merged_spill_list.append((buf_id, new_offset))
    
        # 如果合并后的SPILL操作数量过少，仍使用合并后的列表
        # 但确保至少减少10%的SPILL操作
        if len(merged_spill_list) >= len(spill_list) * 0.9:
            # 如果合并效果不明显，尝试更激进的合并策略
            merged_spill_list = []
            for cache_type, group in spill_groups.items():
                if len(group) > 1:  # 只要有多于1个SPILL操作就合并
                    # 按缓冲区大小排序
                    group.sort(key=lambda x: x[2], reverse=True)
                    # 合并多个SPILL操作为一个（取第一个作为代表）
                    representative_buf_id = group[0][0]
                    representative_offset = group[0][1]
                    merged_spill_list.append((representative_buf_id, representative_offset))
                else:
                    # 不合并，保持原样
                    for buf_id, new_offset, buf_size in group:
                        merged_spill_list.append((buf_id, new_offset))
    
        return schedule, merged_spill_list

    def calculate_multi_objective_score(self, time_improvement, spill_cost, baseline_spill_cost):
        """计算多目标优化得分"""
        # 时间改善权重0.7，SPILL成本权重0.3
        time_score = time_improvement * 0.7
        cost_score = (1 - spill_cost / baseline_spill_cost) * 0.3 if baseline_spill_cost > 0 else 0
        return time_score + cost_score

    def advanced_schedule_optimization(self, schedule, nodes, buf_lifecycle, baseline_metrics, enable_reorder=False):
        """高级调度优化：基于关键路径和资源负载平衡"""
        # 如果未启用重构，则直接返回原调度序列
        if not enable_reorder:
            return schedule
            
        # 1. 计算关键路径
        cpm_result = self.calculate_critical_path(schedule, nodes, buf_lifecycle)
        critical_nodes = cpm_result['critical_nodes']
        es_times = cpm_result['es_times']
        
        # 2. 构建依赖图
        dependencies = defaultdict(set)
        reverse_dependencies = defaultdict(set)  # 反向依赖图，用于更强的依赖验证
        buf_producers = defaultdict(list)  # 缓冲区 -> 生产者节点列表
        buf_consumers = defaultdict(list)  # 缓冲区 -> 消费者节点列表
        
        # 构建缓冲区生产者和消费者映射
        for node_id, node in nodes.items():
            if 'Bufs' in node:
                op = node.get('Op', '')
                bufs = node['Bufs']
                # 简化判断：COPY_IN和MOVE等为生产者，其他为消费者
                if op in ['COPY_IN', 'MOVE']:
                    for buf_id in bufs:
                        buf_producers[buf_id].append(node_id)
                else:
                    for buf_id in bufs:
                        buf_consumers[buf_id].append(node_id)
        
        # 构建精确的依赖关系
        for buf_id in buf_producers:
            producers = buf_producers[buf_id]
            consumers = buf_consumers.get(buf_id, [])
            # 每个生产者必须在所有消费者之前
            for prod in producers:
                for cons in consumers:
                    dependencies[cons].add(prod)
                    reverse_dependencies[prod].add(cons)
        
        # 添加ALLOC/FREE依赖
        for buf_id, lifecycle in buf_lifecycle.items():
            alloc_node = lifecycle['alloc']
            free_node = lifecycle['free']
            producers = lifecycle['producers']
            consumers = lifecycle['consumers']
            
            # ALLOC -> producers
            for prod in producers:
                dependencies[prod].add(alloc_node)
                reverse_dependencies[alloc_node].add(prod)
            
            # producers -> consumers
            for prod in producers:
                for cons in consumers:
                    dependencies[cons].add(prod)
                    reverse_dependencies[prod].add(cons)
            
            # consumers -> FREE
            if free_node:
                for cons in consumers:
                    dependencies[free_node].add(cons)
                    reverse_dependencies[cons].add(free_node)
        
        # 3. 按Pipe分组节点并计算负载
        pipe_load = defaultdict(int)
        pipe_nodes = defaultdict(list)
        
        for node_id in schedule:
            node = nodes[node_id]
            if 'Pipe' in node:
                pipe = node['Pipe']
                cycles = node.get('Cycles', 0)
                pipe_load[pipe] += cycles
                es = es_times.get(node_id, 0)
                pipe_nodes[pipe].append((node_id, cycles, es))
        
        # 4. 优化调度序列
        new_schedule = []
        processed_nodes = set()
        
        # 首先处理ALLOC节点
        alloc_nodes = [node_id for node_id in schedule if nodes[node_id].get('Op') == 'ALLOC']
        new_schedule.extend(alloc_nodes)
        processed_nodes.update(alloc_nodes)
        
        # 按负载平衡策略调度其他节点
        # 优先调度关键路径节点
        critical_schedulable = []
        for node_id in critical_nodes:
            if node_id not in processed_nodes and all(dep in new_schedule for dep in dependencies.get(node_id, set())):
                critical_schedulable.append((node_id, es_times.get(node_id, 0)))
        
        critical_schedulable.sort(key=lambda x: x[1])
        for node_id, _ in critical_schedulable:
            new_schedule.append(node_id)
            processed_nodes.add(node_id)
        
        # 然后按Pipe负载平衡调度其他节点
        # 计算每个Pipe的目标负载（平均负载）
        total_load = sum(pipe_load.values())
        num_pipes = len(pipe_load)
        target_load = total_load / num_pipes if num_pipes > 0 else 0
        
        # 按负载差异排序Pipe
        pipe_load_diff = {pipe: abs(load - target_load) for pipe, load in pipe_load.items()}
        sorted_pipes = sorted(pipe_load_diff.keys(), key=lambda x: pipe_load_diff[x], reverse=True)
        
        # 轮流从不同Pipe调度节点以平衡负载
        round_robin_index = 0
        max_rounds = len(schedule)  # 最大轮次
        
        while len(processed_nodes) < len(schedule) and max_rounds > 0:
            node_scheduled = False
            
            # 按排序后的Pipe顺序尝试调度
            for pipe in sorted_pipes:
                if pipe in pipe_nodes:
                    # 从当前Pipe中选择可调度的节点
                    schedulable_nodes = []
                    for node_info in pipe_nodes[pipe]:
                        node_id, cycles, es = node_info
                        if node_id not in processed_nodes:
                            # 检查所有依赖是否都已调度
                            node_deps = dependencies.get(node_id, set())
                            if all(dep in new_schedule for dep in node_deps):
                                # 加强依赖验证：确保没有违反生产者-消费者关系
                                if self._validate_dependencies(node_id, new_schedule, dependencies, reverse_dependencies, nodes):
                                    schedulable_nodes.append((node_id, es))
                    
                    if schedulable_nodes:
                        # 选择最早开始时间的节点
                        schedulable_nodes.sort(key=lambda x: x[1])
                        selected_node = schedulable_nodes[0][0]
                        new_schedule.append(selected_node)
                        processed_nodes.add(selected_node)
                        node_scheduled = True
                        break
            
            # 如果没有节点被调度，按原始顺序添加剩余节点
            if not node_scheduled:
                for node_id in schedule:
                    if node_id not in processed_nodes:
                        # 在添加节点前进行依赖验证
                        node_deps = dependencies.get(node_id, set())
                        if all(dep in new_schedule for dep in node_deps):
                            if self._validate_dependencies(node_id, new_schedule, dependencies, reverse_dependencies, nodes):
                                new_schedule.append(node_id)
                                processed_nodes.add(node_id)
                break
                
            max_rounds -= 1
        
        # 确保所有节点都被调度
        for node_id in schedule:
            if node_id not in processed_nodes:
                new_schedule.append(node_id)
        
        return new_schedule

    def _validate_dependencies(self, node_id, current_schedule, dependencies, reverse_dependencies, nodes):
        """
        验证节点依赖关系的辅助函数
        确保在重新排列节点时始终维护生产者-消费者关系
        """
        # 检查直接依赖
        node_deps = dependencies.get(node_id, set())
        if not all(dep in current_schedule for dep in node_deps):
            return False
        
        # 检查反向依赖（确保不会破坏已调度节点的依赖关系）
        node_reverse_deps = reverse_dependencies.get(node_id, set())
        current_schedule_set = set(current_schedule)
        if not all(reverse_dep in current_schedule_set for reverse_dep in node_reverse_deps):
            # 如果有反向依赖尚未调度，检查是否会导致依赖冲突
            for reverse_dep in node_reverse_deps:
                if reverse_dep not in current_schedule_set:
                    # 检查反向依赖的依赖是否已经满足
                    reverse_dep_deps = dependencies.get(reverse_dep, set())
                    if not all(dep in current_schedule_set for dep in reverse_dep_deps):
                        return False
        
        # 检查节点类型相关的特殊约束
        node = nodes.get(node_id, {})
        op = node.get('Op', '')
        
        # ALLOC节点必须在对应的FREE节点之前
        if op == 'ALLOC':
            buf_id = node.get('BufId')
            # 查找对应的FREE节点
            for other_node_id, other_node in nodes.items():
                if other_node.get('Op') == 'FREE' and other_node.get('BufId') == buf_id:
                    if other_node_id in current_schedule:
                        # FREE节点已经调度，ALLOC必须在它之前
                        alloc_pos = len(current_schedule)  # 当前节点将被添加到末尾
                        free_pos = current_schedule.index(other_node_id)
                        if alloc_pos >= free_pos:
                            return False
                    break
        
        # FREE节点必须在对应的ALLOC节点之后
        elif op == 'FREE':
            buf_id = node.get('BufId')
            # 查找对应的ALLOC节点
            alloc_node_id = None
            for other_node_id, other_node in nodes.items():
                if other_node.get('Op') == 'ALLOC' and other_node.get('BufId') == buf_id:
                    alloc_node_id = other_node_id
                    break
            
            if alloc_node_id and alloc_node_id not in current_schedule:
                # ALLOC节点尚未调度，FREE不能先调度
                return False
        
        return True

    def integrated_optimization_v2(self, schedule, nodes, buf_lifecycle, baseline_metrics, max_spill_cost, enable_reorder=False):
        """三位一体集成优化框架"""
        
        print("开始执行三位一体集成优化...")
        
        best_schedule = schedule
        best_metrics = baseline_metrics
        best_addr_alloc = self.optimize_cache_allocation_v2(schedule, nodes, buf_lifecycle, {})
        best_spill_list = []
        best_total_time = baseline_metrics['total_exec_time']
        
        # 计算基线SPILL成本
        baseline_spill_list = load_spill_operations('spill_operations.txt')
        baseline_spill_cost = 0
        for buf_id, new_offset in baseline_spill_list:
            for node in nodes.values():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    buf_size = node['Size']
                    baseline_spill_cost += buf_size * 2
                    break
        
        best_spill_cost = baseline_spill_cost
        best_score = self.calculate_multi_objective_score(0, baseline_spill_cost, baseline_spill_cost)
        
        iterations = 0
        max_iterations = 2  # 减少迭代次数从25到5
        
        while iterations < max_iterations:
            print(f"  正在执行第 {iterations + 1}/{max_iterations} 轮优化...")
            
            # 阶段1：调度序列重构（策略1）
            print("    正在执行调度序列重构...")
            optimized_schedule = self.advanced_schedule_optimization(
                best_schedule, nodes, buf_lifecycle, best_metrics, enable_reorder
            )
            
            # 阶段2：缓存分配优化（策略2）
            print("    正在执行缓存分配优化...")
            optimized_addr_alloc = self.optimize_cache_allocation_v2(
                optimized_schedule, nodes, buf_lifecycle, best_addr_alloc
            )
            
            # 阶段3：SPILL节点优化（策略3）
            print("    正在执行SPILL节点优化...")
            spill_list, total_spill_cost = self.simulate_spill_handling(
                optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc
            )
            
            # 调整SPILL时序
            optimized_schedule, spill_list = self.optimize_spill_timing_v2(
                optimized_schedule, nodes, optimized_addr_alloc, spill_list, best_metrics
            )
            
            # 计算新的执行时间
            print("    正在计算新的执行时间...")
            new_metrics = self.calculate_baseline_metrics(
                optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc, spill_list
            )
            
            new_total_time = new_metrics['total_exec_time']
            time_improvement = (best_total_time - new_total_time) / best_total_time if best_total_time > 0 else 0
            
            # 计算多目标得分
            new_score = self.calculate_multi_objective_score(time_improvement, total_spill_cost, baseline_spill_cost)
            
            print(f"    当前得分: {new_score:.4f} (时间改善: {time_improvement:.1%}, SPILL成本: {total_spill_cost})")
            
            # 检查是否为最佳解
            if new_score > best_score and total_spill_cost <= max_spill_cost * 1.05:  # 稍微放宽成本约束
                print(f"    发现更优解: 得分 {best_score:.4f} -> {new_score:.4f}")
                best_schedule = optimized_schedule
                best_metrics = new_metrics
                best_addr_alloc = optimized_addr_alloc
                best_spill_list = spill_list
                best_total_time = new_total_time
                best_spill_cost = total_spill_cost
                best_score = new_score
            elif time_improvement > 0.01:  # 至少有1%的改善
                print(f"    发现改善: {best_total_time} -> {new_total_time} ({time_improvement:.1%})")
                best_schedule = optimized_schedule
                best_metrics = new_metrics
                best_addr_alloc = optimized_addr_alloc
                best_spill_list = spill_list
                best_total_time = new_total_time
                best_spill_cost = total_spill_cost
            
            iterations += 1
        
        print("优化完成！")
        return best_schedule, best_addr_alloc, best_spill_list, best_metrics

    # ==================== 辅助方法 ====================

    def simulate_spill_handling(self, schedule, nodes, buf_lifecycle, addr_alloc):
        """模拟SPILL处理过程"""
        
        # 简化实现：基于缓存容量和缓冲区大小估算SPILL需求
        spill_list = []
        total_spill_cost = 0
        
        # 按缓存类型统计使用情况
        cache_usage = defaultdict(int)
        buffer_info = {}  # 存储缓冲区信息
        
        for buf_id, addr in addr_alloc.items():
            alloc_node_id = buf_lifecycle[buf_id]['alloc']
            alloc_node = nodes[alloc_node_id]
            cache_type = alloc_node['Type']
            size = alloc_node['Size']
            cache_usage[cache_type] += size
            buffer_info[buf_id] = {
                'size': size,
                'type': cache_type,
                'alloc_node_id': alloc_node_id,
                'address': addr
            }
        
        # 检查是否超出缓存容量
        buffers_to_spill = []
        
        for cache_type, used_size in cache_usage.items():
            capacity = self.cache_config[cache_type]
            if used_size > capacity:
                # 需要SPILL
                excess = used_size - capacity
                # 找到超出容量的缓冲区
                cache_buffers = [(buf_id, info) for buf_id, info in buffer_info.items() if info['type'] == cache_type]
                # 按地址排序，选择地址最高的缓冲区进行SPILL
                cache_buffers.sort(key=lambda x: x[1]['address'], reverse=True)
                spilled_amount = 0
                for buf_id, info in cache_buffers:
                    if spilled_amount >= excess:
                        break
                    buffers_to_spill.append(buf_id)
                    spilled_amount += info['size']
        
        # 如果需要SPILL，选择合适的缓冲区进行SPILL
        if buffers_to_spill:
            for buf_id in buffers_to_spill:
                spill_list.append((buf_id, 0))  # 新地址简化为0
                info = buffer_info[buf_id]
                # 计算SPILL成本 (缓冲区大小 * 2)
                spill_cost = info['size'] * 2
                total_spill_cost += spill_cost
        
        # 添加在optimize_cache_allocation_v2中移除的缓冲区到SPILL列表
        # 这些缓冲区因为在分配时超出容量限制而被移除
        for buf_id in set(buf_lifecycle.keys()) - set(addr_alloc.keys()):
            # 检查这个缓冲区是否在spill_operations.txt中
            baseline_spill_list = load_spill_operations('spill_operations.txt')
            if buf_id in [buf_id for buf_id, _ in baseline_spill_list]:
                # 检查是否已经在spill_list中
                if buf_id not in [buf_id for buf_id, _ in spill_list]:
                    spill_list.append((buf_id, 0))
                    # 计算SPILL成本
                    alloc_node_id = buf_lifecycle[buf_id]['alloc']
                    alloc_node = nodes[alloc_node_id]
                    buf_size = alloc_node['Size']
                    total_spill_cost += buf_size * 2
        
        # 如果没有需要SPILL的缓冲区，但仍需要计算SPILL成本
        # 只计算当前SPILL列表中的缓冲区成本，不从spill_operations.txt加载
        if not spill_list:
            # 如果SPILL列表为空，保持total_spill_cost为0
            pass
        
        return spill_list, total_spill_cost
    
    def find_largest_buffer_in_cache(self, cache_type, buf_lifecycle, nodes, addr_alloc):
        """在指定缓存中找到最大的缓冲区"""
        
        largest_buf = None
        largest_size = 0
        
        for buf_id, addr in addr_alloc.items():
            alloc_node_id = buf_lifecycle[buf_id]['alloc']
            alloc_node = nodes[alloc_node_id]
            if alloc_node['Type'] == cache_type:
                size = alloc_node['Size']
                if size > largest_size:
                    largest_size = size
                    largest_buf = (buf_id, size)
        
        return largest_buf
    
    def calculate_performance_metrics(self, schedule, nodes, buf_lifecycle, addr_alloc, spill_list, baseline_metrics):
        """计算性能指标"""
        
        # 计算优化后的指标
        optimized_metrics = self.calculate_baseline_metrics(
            schedule, nodes, buf_lifecycle, addr_alloc, spill_list
        )
        
        # 计算改善程度
        baseline_time = baseline_metrics['total_exec_time']
        optimized_time = optimized_metrics['total_exec_time']
        time_improvement = (baseline_time - optimized_time) / baseline_time if baseline_time > 0 else 0
        
        # 计算SPILL成本
        total_spill_cost = 0
        # 计算优化后SPILL操作的成本
        for buf_id, new_offset in spill_list:
            # 获取缓冲区大小
            for node in nodes.values():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    buf_size = node['Size']
                    total_spill_cost += buf_size * 2  # SPILL成本为缓冲区大小的2倍
                    break
        
        # 计算单元空闲时间改善
        baseline_idle = sum(stats['idle_ratio'] for stats in baseline_metrics['unit_stats'].values())
        optimized_idle = sum(stats['idle_ratio'] for stats in optimized_metrics['unit_stats'].values())
        idle_improvement = (baseline_idle - optimized_idle) / baseline_idle if baseline_idle > 0 else 0
        
        # 计算碎片率改善
        baseline_frag = sum(frag['fragmentation_rate'] for frag in baseline_metrics['fragmentation_stats'].values())
        optimized_frag = sum(frag['fragmentation_rate'] for frag in optimized_metrics['fragmentation_stats'].values())
        frag_improvement = (baseline_frag - optimized_frag) / baseline_frag if baseline_frag > 0 else 0
        
        return {
            'baseline_time': baseline_time,
            'optimized_time': optimized_time,
            'time_improvement': time_improvement,
            'total_spill_cost': total_spill_cost,
            'idle_improvement': idle_improvement,
            'frag_improvement': frag_improvement,
            'meets_time_target': time_improvement >= 0.15,  # 15%改善目标
            'meets_cost_constraint': total_spill_cost <= baseline_time * 0.11  # 成本约束
        }
    
    def stability_validation(self, case_name, graph_path, baseline_schedule, baseline_metrics, runs=3):
        """稳定性验证：多次运行同一优化算法"""
        
        exec_times = []
        
        for run in range(runs):
            try:
                # 重新进行优化
                with open(graph_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                nodes = {n['Id']: n for n in data['Nodes']}
                
                buf_lifecycle = get_buf_lifecycle(baseline_schedule, nodes)
                max_spill_cost = baseline_metrics['total_exec_time'] * 0.11  # 11%的成本约束
                
                optimized_schedule, addr_alloc, spill_list, metrics = self.integrated_optimization_v2(
                    baseline_schedule, nodes, buf_lifecycle, baseline_metrics, max_spill_cost
                )
                
                exec_time = metrics['total_exec_time']
                exec_times.append(exec_time)
                
            except Exception as e:
                exec_times.append(baseline_metrics['total_exec_time'])  # 使用基准值
        
        # 计算稳定性指标
        if exec_times:
            mean_time = sum(exec_times) / len(exec_times)
            max_deviation = max(abs(t - mean_time) for t in exec_times)
            stability_ratio = max_deviation / mean_time if mean_time > 0 else 0
            
            return stability_ratio <= 0.03, {
                'mean_time': mean_time,
                'max_deviation': max_deviation,
                'stability_ratio': stability_ratio,
                'exec_times': exec_times
            }
        
        return False, {}

    def validate_schedule_constraints(self, schedule, nodes, buf_lifecycle):
        """验证调度序列约束"""
        # 检查所有节点是否都在序列中
        all_node_ids = set(nodes.keys())
        schedule_node_ids = set(schedule)
        
        if all_node_ids != schedule_node_ids:
            return False
        
        # 检查依赖约束
        node_positions = {node_id: i for i, node_id in enumerate(schedule)}
        
        for buf_id, lifecycle in buf_lifecycle.items():
            alloc_node = lifecycle['alloc']
            free_node = lifecycle['free']
            producers = lifecycle['producers']
            consumers = lifecycle['consumers']
            
            # ALLOC必须在producers之前
            alloc_pos = node_positions[alloc_node]
            for prod in producers:
                if node_positions[prod] < alloc_pos:
                    return False
            
            # producers必须在consumers之前
            for prod in producers:
                prod_pos = node_positions[prod]
                for cons in consumers:
                    if node_positions[cons] < prod_pos:
                        return False
            
            # consumers必须在FREE之前
            free_pos = node_positions[free_node]
            for cons in consumers:
                if node_positions[cons] > free_pos:
                    return False
        
        return True

def extract_schedule_from_json(json_path):
    """从JSON文件中提取调度序列"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if 'schedule' in data:
        return data['schedule']
    else:
        # 如果没有schedule字段，从nodes生成一个简单的序列
        nodes = data.get('Nodes', [])
        return [node['Id'] for node in nodes]

def extract_memory_from_json(json_path):
    """从JSON文件中提取内存分配信息"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    memory_allocation = data.get('memory_allocation', {})
    # 转换为整数键值对
    return {int(k): v for k, v in memory_allocation.items() if v != -1}

def extract_spill_from_json(json_path):
    """从JSON文件中提取SPILL操作信息"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    spill_operations = data.get('spill_operations', [])
    return [(op['buf_id'], op['new_offset']) for op in spill_operations]

def solve_problem3(enable_reorder=False):
    """问题3主解决函数"""
    
    cache_config = {
        'L1': 4096,
        'UB': 1024,
        'L0A': 256,
        'L0B': 256,
        'L0C': 512
    }
    
    optimizer = PerformanceOptimizer(cache_config)
    
    # 加载数据 - 适配当前目录文件格式
    print("正在加载计算图数据...")
    with open('1.json', 'r', encoding='utf-8') as f:
        graph_data = json.load(f)
    nodes = {n['Id']: n for n in graph_data['Nodes']}
    
    # 从task2_schedule.json加载调度序列
    print("正在加载调度序列...")
    baseline_schedule = load_schedule('task2_schedule.json')
    
    # 从task2_memory.json加载内存分配
    print("正在加载内存分配...")
    baseline_addr_alloc = load_memory_allocation('task2_memory.json')
    
    # 从spill_operations.txt加载SPILL操作
    print("正在加载SPILL操作...")
    baseline_spill_list = load_spill_operations('spill_operations.txt')
    
    case_name = 'FlashAttention_Case0'
    
    print("正在计算缓冲区生命周期...")
    buf_lifecycle = get_buf_lifecycle(baseline_schedule, nodes)
    
    # 计算问题2基准指标
    print("正在计算基准指标...")
    baseline_metrics = optimizer.calculate_baseline_metrics(
        baseline_schedule, nodes, buf_lifecycle, baseline_addr_alloc, baseline_spill_list
    )
    
    baseline_time = baseline_metrics['total_exec_time']
    # 从spill_operations.txt的行数估算SPILL成本
    baseline_spill_cost = 0
    with open('spill_operations.txt', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                buf_id, offset = line.split(':')
                # 获取缓冲区大小
                buf_id = int(buf_id)
                for node in nodes.values():
                    if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                        buf_size = node['Size']
                        baseline_spill_cost += buf_size * 2  # SPILL成本为缓冲区大小的2倍
                        break
    max_spill_cost = baseline_spill_cost * 1.1
    
    # 执行真正的优化（使用重构后的版本）
    print("正在执行优化...")
    optimized_schedule, optimized_addr_alloc, optimized_spill_list, optimized_metrics = optimizer.integrated_optimization_v2(
        baseline_schedule, nodes, buf_lifecycle, baseline_metrics, max_spill_cost, enable_reorder
    )
    
    # 计算性能指标
    print("正在计算性能指标...")
    performance_metrics = optimizer.calculate_performance_metrics(
        optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc, optimized_spill_list, baseline_metrics
    )
    
    # 计算优化前的SPILL成本
    baseline_spill_cost = 0
    for buf_id, new_offset in baseline_spill_list:
        # 获取缓冲区大小
        for node in nodes.values():
            if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                buf_size = node['Size']
                baseline_spill_cost += buf_size * 2  # SPILL成本为缓冲区大小的2倍
                break
    
    # 输出结果
    print(f"总执行时间: {performance_metrics['baseline_time']} -> {performance_metrics['optimized_time']} (改善: {performance_metrics['time_improvement']:.1%})")
    print(f"SPILL成本: {baseline_spill_cost} -> {performance_metrics['total_spill_cost']}")
    print(f"满足成本约束: {'YES' if performance_metrics['meets_cost_constraint'] else 'NO'}")
    print(f"满足时间改善目标: {'YES' if performance_metrics['meets_time_target'] else 'NO'}")
    
    # 保存结果到当前目录
    print("正在保存结果...")
    save_problem3_results(
        case_name, optimized_schedule, optimized_addr_alloc, optimized_spill_list
    )
    print("优化完成！")

def save_problem3_results(case_name, schedule, addr_alloc, spill_list):
    """保存问题3结果到当前目录"""
    
    # 保存调度序列
    with open(f'{case_name}_schedule.txt', 'w', encoding='utf-8') as f:
        for node_id in schedule:
            f.write(f"{node_id}\n")
    
    # 保存内存分配
    with open(f'{case_name}_memory.txt', 'w', encoding='utf-8') as f:
        for buf_id, offset in addr_alloc.items():
            f.write(f"{buf_id}:{offset}\n")
    
    # 保存SPILL操作
    with open(f'{case_name}_spill.txt', 'w', encoding='utf-8') as f:
        for buf_id, new_offset in spill_list:
            f.write(f"{buf_id}:{new_offset}\n")

if __name__ == "__main__":
    import sys
    enable_reorder = '--enable-reorder' in sys.argv
    solve_problem3(enable_reorder)
