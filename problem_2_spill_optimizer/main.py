import json
import time
import random
from collections import defaultdict, deque
import math

# 简单的进度条函数
def simple_progress(iterable, desc="Processing"):
    total = len(iterable) if hasattr(iterable, '__len__') else None
    if total:
        print(f"{desc}: {total} items...")
    else:
        print(f"{desc}...")
    
    for i, item in enumerate(iterable):
        if total and (i + 1) % max(1, total // 10) == 0:
            print(f"  Progress: {i+1}/{total}")
        yield item

class MemoryPreAllocator:
    """内存预分配器，用于提前规划内存布局"""

    def __init__(self, cache_capacity):
        self.cache_capacity = cache_capacity

    def analyze_buffer_patterns(self, buffer_info, buffer_lifetime):
        """分析缓冲区模式，识别优化机会"""
        patterns = {
            'overlapping_buffers': [],  # 重叠的缓冲区
            'sequential_buffers': [],   # 顺序访问的缓冲区
            'isolated_buffers': []      # 孤立的缓冲区
        }

        # 按缓存类型分析
        for cache_type in self.cache_capacity:
            cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items()
                         if info['type'] == cache_type and buf_id in buffer_lifetime]

            if not cache_bufs:
                continue

            # 按生命周期排序
            sorted_bufs = sorted(cache_bufs, key=lambda x: buffer_lifetime[x[0]][0])

            # 识别重叠缓冲区
            for i, (buf1_id, buf1_info) in enumerate(sorted_bufs):
                for j, (buf2_id, buf2_info) in enumerate(sorted_bufs[i+1:], i+1):
                    start1, end1 = buffer_lifetime[buf1_id]
                    start2, end2 = buffer_lifetime[buf2_id]

                    if not (end1 < start2 or end2 < start1):  # 有重叠
                        patterns['overlapping_buffers'].append((buf1_id, buf2_id, cache_type))

            # 识别顺序缓冲区（生命周期连续）
            for i in range(len(sorted_bufs) - 1):
                buf1_id, _ = sorted_bufs[i]
                buf2_id, _ = sorted_bufs[i+1]
                start1, end1 = buffer_lifetime[buf1_id]
                start2, end2 = buffer_lifetime[buf2_id]

                if end1 == start2:  # 生命周期连续
                    patterns['sequential_buffers'].append((buf1_id, buf2_id, cache_type))

        return patterns

    def calculate_optimal_placement(self, buffer_info, buffer_lifetime, cache_type):
        """计算最优的缓冲区放置策略"""
        cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items()
                     if info['type'] == cache_type and buf_id in buffer_lifetime]

        if not cache_bufs:
            return {}

        # 按生命周期排序，优先分配长生命周期的缓冲区
        cache_bufs.sort(key=lambda x: buffer_lifetime[x[0]][1] - buffer_lifetime[x[0]][0], reverse=True)

        placement = {}
        current_offset = 0
        max_offset = self.cache_capacity[cache_type]

        for buf_id, buf_info in cache_bufs:
            size = buf_info['size']
            if current_offset + size <= max_offset:
                placement[buf_id] = current_offset
                current_offset += size
            else:
                # 无法预分配，标记为-1
                placement[buf_id] = -1

        return placement

class L1UBOptimizedSolver:
    def __init__(self):
        # 调整缓存容量以匹配问题描述
        self.base_cache_capacity = {'L1': 4096, 'UB': 1024, 'L0A': 256, 'L0B': 256, 'L0C': 512}
        self.cache_capacity = self.base_cache_capacity.copy()
        self.pre_allocator = MemoryPreAllocator(self.cache_capacity)

    def _build_dependency_graph(self, nodes, edges):
        """构建节点依赖图"""
        # 创建节点ID到节点对象的映射
        node_dict = {node['Id']: node for node in nodes}
        
        # 构建前驱和后继关系
        predecessors = defaultdict(set)
        successors = defaultdict(set)
        
        for src_id, dst_id in edges:
            successors[src_id].add(dst_id)
            predecessors[dst_id].add(src_id)
        
        return node_dict, predecessors, successors

    def _find_swappable_pairs(self, schedule, predecessors, successors, node_dict):
        """识别可交换的节点对"""
        swappable_pairs = []
        
        # 统计FREE和COPY_IN节点数量
        free_nodes = []
        copy_in_nodes = []
        for i, node_id in enumerate(schedule):
            node = node_dict.get(node_id)
            if node:
                if node.get('Op') == 'FREE':
                    free_nodes.append((i, node_id))
                elif node.get('Op') == 'COPY_IN':
                    copy_in_nodes.append((i, node_id))
        
        print(f"找到 {len(free_nodes)} 个FREE节点，{len(copy_in_nodes)} 个COPY_IN节点")
        
        # 查找可以交换的节点对：FREE节点和非FREE节点之间没有依赖关系
        # 不简化，完全实现所有可能的交换对，但添加超时机制避免无限循环
        max_pairs = 10000  # 限制最大交换对数量
        pair_count = 0
        
        for i in range(len(schedule)):
            for j in range(i + 1, len(schedule)):
                # 添加超时检查
                pair_count += 1
                if pair_count > max_pairs:
                    print(f"达到最大交换对数量限制 ({max_pairs})，停止搜索")
                    break
                    
                node_a_id = schedule[i]
                node_b_id = schedule[j]
                
                node_a = node_dict.get(node_a_id)
                node_b = node_dict.get(node_b_id)
                
                if not node_a or not node_b:
                    continue
                    
                # 检查是否满足交换条件：
                # 1. 一个是FREE操作，另一个不是FREE操作
                # 2. 两个节点无直接或间接依赖关系
                if ((node_a.get('Op') == 'FREE' and node_b.get('Op') != 'FREE') or
                    (node_a.get('Op') != 'FREE' and node_b.get('Op') == 'FREE')):
                    
                    # 检查是否有直接依赖关系
                    has_direct_dependency = (node_b_id in successors[node_a_id] or 
                                           node_a_id in successors[node_b_id])
                    
                    # 检查是否有间接依赖关系（通过传递闭包）
                    if not has_direct_dependency:
                        # 使用BFS检查间接依赖，限制搜索深度
                        visited = set()
                        queue = deque([node_a_id])
                        has_indirect_dependency = False
                        depth_limit = 100  # 限制搜索深度
                        current_depth = 0
                        
                        while queue and not has_indirect_dependency and current_depth < depth_limit:
                            current = queue.popleft()
                            if current in visited:
                                continue
                            visited.add(current)
                            
                            # 检查当前节点是否是node_b的前驱
                            if current == node_b_id:
                                has_indirect_dependency = True
                                break
                                
                            # 添加后继节点到队列
                            for succ in successors.get(current, []):
                                if succ not in visited:
                                    queue.append(succ)
                            current_depth += 1
                        
                        # 如果也没有间接依赖，则可以交换
                        if not has_indirect_dependency and current_depth < depth_limit:
                            # 再次检查node_b是否是node_a的前驱
                            visited = set()
                            queue = deque([node_b_id])
                            is_node_b_predecessor = False
                            current_depth = 0
                            
                            while queue and not is_node_b_predecessor and current_depth < depth_limit:
                                current = queue.popleft()
                                if current in visited:
                                    continue
                                visited.add(current)
                                
                                # 检查当前节点是否是node_a
                                if current == node_a_id:
                                    is_node_b_predecessor = True
                                    break
                                    
                                # 添加后继节点到队列
                                for succ in successors.get(current, []):
                                    if succ not in visited:
                                        queue.append(succ)
                                current_depth += 1
                            
                            if not is_node_b_predecessor and current_depth < depth_limit:
                                swappable_pairs.append((i, j))
                                if len(swappable_pairs) <= 5:  # 只打印前5个找到的可交换对
                                    print(f"找到可交换对: 位置{i}({node_a.get('Op', 'Unknown')}) <-> 位置{j}({node_b.get('Op', 'Unknown')})")
            
            # 每处理100个节点打印一次进度
            if i % 100 == 0:
                print(f"进度: 已处理 {i}/{len(schedule)} 个节点")
                
            # 如果已达到最大交换对数量，提前退出外层循环
            if pair_count > max_pairs:
                break
                
        print(f"总共找到 {len(swappable_pairs)} 个可交换节点对")
        return swappable_pairs

    def _optimize_schedule_with_free_promotion(self, schedule, nodes, edges):
        """基于关键路径依赖保留的调度优化，优先将FREE节点提前"""
        print("正在进行调度序列优化...")
        
        # 构建依赖图
        node_dict, predecessors, successors = self._build_dependency_graph(nodes, edges)
        
        # 识别可交换节点对
        swappable_pairs = self._find_swappable_pairs(schedule, predecessors, successors, node_dict)
        
        # 执行交换优化
        optimized_schedule = schedule.copy()
        swap_count = 0
        
        # 执行交换
        for i, j in swappable_pairs:
            # 执行交换
            optimized_schedule[i], optimized_schedule[j] = optimized_schedule[j], optimized_schedule[i]
            swap_count += 1
            
        print(f"完成调度优化，共执行 {swap_count} 次节点交换")
        return optimized_schedule

    def _merge_free_blocks(self, free_blocks):
        """合并连续的空闲块，并按块大小降序排序"""
        if not free_blocks:
            return []

        # 按起始地址排序
        free_blocks.sort(key=lambda x: x[0])

        merged = [free_blocks[0]]
        for current in free_blocks[1:]:
            last = merged[-1]
            # 如果当前块与前一块连续
            if last[0] + last[1] == current[0]:
                # 合并两个块
                merged[-1] = (last[0], last[1] + current[1])
            else:
                merged.append(current)

        # 按块大小降序排序（便于快速查找最佳适配块）
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged

    def _find_best_fit(self, free_blocks, size):
        """寻找最佳适配的空闲块 - 从空闲块中选择"最小且能容纳当前缓冲区"的块"""
        best_idx = -1
        best_waste = float('inf')
        best_start = -1

        # 遍历空闲块列表，找到"大小≥size且最小"的块
        for i, (start, length) in enumerate(free_blocks):
            if length >= size:
                waste = length - size
                if waste < best_waste:
                    best_waste = waste
                    best_idx = i
                    best_start = start

        return best_idx, best_start

    def _allocate_buffer(self, free_blocks, size, start_addr):
        """分配缓冲区并更新空闲块列表"""
        # 查找匹配的空闲块
        best_idx = -1
        for i, (start, length) in enumerate(free_blocks):
            if start == start_addr and length >= size:
                best_idx = i
                break

        if best_idx >= 0:
            start, length = free_blocks[best_idx]
            if length > size:
                # 剩余空间作为新块
                free_blocks[best_idx] = (start + size, length - size)
            else:
                # 完全使用，移除该块
                free_blocks.pop(best_idx)
        else:
            # 如果找不到匹配的空闲块，查找任何足够大的空闲块
            for i, (start, length) in enumerate(free_blocks):
                if length >= size:
                    # 使用这个空闲块
                    if length > size:
                        # 剩余空间作为新块
                        free_blocks[i] = (start + size, length - size)
                    else:
                        # 完全使用，移除该块
                        free_blocks.pop(i)
                    break
        
        # 重新合并空闲块以确保没有重叠
        free_blocks = self._merge_free_blocks(free_blocks)

        return free_blocks

    def _select_spill_candidate(self, active_buffers, buffer_lifetime, buffer_info, cache_type, current_pos, node_references=None):
        """选择最优的spill候选者 - 基于动态优先级排序+成本评估+数据复用率"""
        candidates = []

        for active_buf, (offset, buf_size) in active_buffers.items():
            active_info = buffer_info[active_buf]
            lifetime_start, lifetime_end = buffer_lifetime[active_buf]
            lifetime = lifetime_end - lifetime_start
            remaining_lifetime = lifetime_end - current_pos  # 生命周期剩余长度

            # 计算spill优先级（根据您提供的规则）
            # 优先级1: 被COPY_IN节点使用（额外搬运量=Size，比未使用的少50%）
            has_copy_in = active_info['has_copy_in']
            
            # 优先级2: Size最小
            size = buf_size
            
            # 优先级3: 生命周期剩余长度最长
            remaining = remaining_lifetime
            
            # 新增优先级: 数据复用率（后续被复用的次数）
            reuse_count = 0
            if node_references and active_buf in node_references:
                reuse_count = node_references[active_buf]
            
            # 优先级4: 所在缓存的空闲块合并潜力大（简化处理，用剩余生命周期表示）
            
            # 综合评分（高分优先）
            # COPY_IN的缓冲区优先级最高（成本低），Size小的优先，剩余生命周期长的优先
            # 低复用率的缓冲区优先（避免重复搬运）
            score = 0
            if has_copy_in:
                score += 1000  # 最高优先级
            score += 100 - (size // 10)  # Size越小分数越高
            score += remaining // 10  # 剩余生命周期越长分数越高
            score += 300 - (reuse_count * 100)  # 复用率越低分数越高（复用次数越少越好）
            
            candidates.append((score, active_buf, offset, buf_size, has_copy_in, size, remaining, reuse_count))

        # 按综合评分降序排序（分数高优先）
        candidates.sort(reverse=True)
        return candidates

    def predict_optimal_allocation(self, buffer_info, buffer_lifetime, cache_type):
        """基于传统策略的最优分配策略"""
        cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items()
                      if info['type'] == cache_type and buf_id in buffer_lifetime]

        if not cache_bufs:
            return {}

        # 计算基于生命周期的优先级
        scored_bufs = []
        for buf_id, buf_info in cache_bufs:
            # 基础优先级（基于生命周期）
            lifetime_start, lifetime_end = buffer_lifetime[buf_id]
            base_priority = lifetime_end - lifetime_start

            # 只基于实际生命周期
            score = 1 / (base_priority + 1)  # 生命周期越长，优先级越高

            scored_bufs.append((score, buf_id, buf_info))

        # 按综合评分排序
        scored_bufs.sort(reverse=True, key=lambda x: x[0])

        return scored_bufs

    def solve(self):
        with open('1.json', 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        with open('2.json', 'r', encoding='utf-8') as f:
            # 修改：2.json现在是纯调度顺序列表
            schedule_data = f.read().strip().split('\n')
            original_schedule = [int(x) for x in schedule_data if x.strip()]

        nodes = graph_data['Nodes']
        edges = graph_data['Edges']
        node_dict = {node['Id']: node for node in nodes}

        # 应用调度优化
        optimized_schedule = self._optimize_schedule_with_free_promotion(original_schedule, nodes, edges)
        schedule = original_schedule  # 使用原始调度序列，不使用优化后的序列

        buffer_info = {}
        copy_in_bufs = set()

        # 收集COPY_IN缓冲区信息
        for node in nodes:
            if node.get('Op') == 'COPY_IN' and 'Bufs' in node:
                copy_in_bufs.update(node['Bufs'])

        # 收集缓冲区信息
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                buf_id = node['BufId']
                buffer_info[buf_id] = {
                    'size': node['Size'],
                    'type': node['Type'],
                    'has_copy_in': buf_id in copy_in_bufs
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

        # 计算缓冲区引用次数（复用率）
        buffer_references = defaultdict(int)
        for node in nodes:
            if 'In' in node:  # 输入缓冲区
                for buf_id in node['In']:
                    buffer_references[buf_id] += 1
            if 'Bufs' in node:  # COPY_IN缓冲区
                for buf_id in node['Bufs']:
                    buffer_references[buf_id] += 1

        memory_allocation = {}
        spill_operations = []
        total_spill_cost = 0

        # 初始化未分配缓冲区
        for buf_id in buffer_info:
            if buf_id not in buffer_lifetime:
                memory_allocation[buf_id] = -1
            # 对于L0缓存的缓冲区，直接分配成功，但需要为每种类型单独分配地址
            elif buffer_info[buf_id]['type'] in ['L0A', 'L0B', 'L0C']:
                # L0缓存的缓冲区应该根据类型和生命周期来分配，而不是全部分配到地址0
                # 这里我们暂时标记为未分配，让后续的处理逻辑来分配
                memory_allocation[buf_id] = -1

        # 使用预分配策略
        print("正在进行内存预分配分析...")
        pre_allocation = {}
        for cache_type in ['L1', 'UB']:  # 只对L1和UB进行预分配分析
            print(f"  {cache_type}: 使用传统分配策略")
            pre_allocation[cache_type] = self.pre_allocator.calculate_optimal_placement(
                buffer_info, buffer_lifetime, cache_type)

        # 按缓存类型处理
        for cache_type in ['L1', 'UB']:  # 只处理L1和UB缓存，不处理L0缓存
            cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items()
                         if info['type'] == cache_type and buf_id in buffer_lifetime]

            if not cache_bufs:
                continue

            # 按生命周期起始位置排序
            cache_bufs.sort(key=lambda x: buffer_lifetime[x[0]][0])

            capacity = self.cache_capacity[cache_type]
            active_buffers = {}  # 活跃缓冲区: {buf_id: (offset, size)}
            # 为L1和UB缓存分配不同的基地址以避免重叠
            base_address = 0 if cache_type == 'L1' else 4096  # L1从0开始，UB从4096开始
            # 初始化空闲块列表，使用相对于基地址的地址
            free_blocks = [(0, capacity)]  # 空闲块: [(start, length)]，相对于基地址
            successful = 0

            # 添加进度条
            print(f"处理 {cache_type} 缓存 ({len(cache_bufs)} 个缓冲区)...")
            for buf_id, buf_info in simple_progress(cache_bufs, desc=f"  {cache_type}"):
                size = buf_info['size']
                start_pos = buffer_lifetime[buf_id][0]

                # 清理过期缓冲区
                expired = []
                for active_buf, (offset, buf_size) in list(active_buffers.items()):
                    if active_buf in buffer_lifetime:
                        _, end_pos = buffer_lifetime[active_buf]
                        if end_pos <= start_pos:
                            expired.append(active_buf)
                            # 将释放的缓冲区地址转换为相对于基地址的值
                            adjusted_offset = offset - base_address
                            free_blocks.append((adjusted_offset, buf_size))

                for buf in expired:
                    del active_buffers[buf]

                # 合并空闲块：检查新块与相邻空闲块是否连续，若连续则合并
                free_blocks = self._merge_free_blocks(free_blocks)

                # 尝试分配：寻找最佳适配
                best_idx, best_start = self._find_best_fit(free_blocks, size)
                final_offset = best_start if best_idx >= 0 else -1

                if final_offset >= 0:
                    # 分配成功：从空闲块中选择"最小且能容纳当前缓冲区"的块分配
                    # 实际分配的地址需要加上基地址偏移
                    actual_offset = final_offset + base_address
                    memory_allocation[buf_id] = actual_offset
                    active_buffers[buf_id] = (actual_offset, size)
                    # 在更新空闲块时，使用相对于基地址的地址
                    free_blocks = self._allocate_buffer(free_blocks, size, final_offset)
                    successful += 1
                else:
                    # 需要spill
                    spilled = False
                    candidates = self._select_spill_candidate(active_buffers, buffer_lifetime, buffer_info, cache_type, start_pos, buffer_references)

                    for score, spill_buf, spill_offset, spill_size, has_copy_in, buf_size, remaining, reuse_count in candidates:
                        # 计算spill后的可用空间
                        # 将spill缓冲区的地址转换为相对于基地址的值
                        adjusted_spill_offset = spill_offset - base_address
                        temp_free_blocks = free_blocks + [(adjusted_spill_offset, spill_size)]
                        temp_free_blocks = self._merge_free_blocks(temp_free_blocks)

                        if self._find_best_fit(temp_free_blocks, size)[0] >= 0:
                            # 执行spill
                            spill_info = buffer_info[spill_buf]
                            # 根据是否被COPY_IN使用来计算成本
                            cost = spill_info['size'] if spill_info['has_copy_in'] else 2 * spill_info['size']

                            spill_operations.append({
                                'buf_id': spill_buf,
                                'new_offset': spill_offset
                            })
                            total_spill_cost += cost

                            # 更新状态
                            del active_buffers[spill_buf]
                            free_blocks = temp_free_blocks

                            # 重新分配当前缓冲区
                            best_idx, best_start = self._find_best_fit(free_blocks, size)
                            if best_idx >= 0:
                                # 实际分配的地址需要加上基地址偏移
                                actual_offset = best_start + base_address
                                memory_allocation[buf_id] = actual_offset
                                active_buffers[buf_id] = (actual_offset, size)
                                # 在更新空闲块时，使用相对于基地址的地址
                                free_blocks = self._allocate_buffer(free_blocks, size, best_start)
                                successful += 1
                                spilled = True
                                break

                    if not spilled:
                        # 无法分配
                        memory_allocation[buf_id] = -1

            print(f"{cache_type}: {successful}/{len(cache_bufs)} (容量: {self.cache_capacity[cache_type]})")

        # 单独处理L0缓存
        l0_base_offsets = {'L0A': 0, 'L0B': 256, 'L0C': 512}
        l0_capacities = {'L0A': 256, 'L0B': 256, 'L0C': 512}
        
        for cache_type in ['L0A', 'L0B', 'L0C']:
            cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items()
                         if info['type'] == cache_type and buf_id in buffer_lifetime]
            
            if not cache_bufs:
                continue
                
            # 按生命周期起始位置排序
            cache_bufs.sort(key=lambda x: buffer_lifetime[x[0]][0])
            
            # 为每种L0缓存类型单独维护偏移量
            l0_offset = l0_base_offsets[cache_type]
            
            for buf_id, buf_info in cache_bufs:
                # L0缓存的缓冲区按顺序分配地址
                memory_allocation[buf_id] = l0_offset
                l0_offset += buf_info['size']
                
                # 检查是否超出L0缓存容量
                if l0_offset > l0_base_offsets[cache_type] + l0_capacities[cache_type]:
                    print(f"警告: {cache_type}缓存容量不足")

        # 计算缓存利用率（使用动态调整后的容量）
        cache_utilization = {}
        for cache_type in self.cache_capacity:
            cache_bufs = [buf_id for buf_id, info in buffer_info.items()
                         if info['type'] == cache_type]
            used_size = 0
            max_end = 0

            # 正确计算缓存利用率：计算所有已分配缓冲区的总大小
            total_used = 0
            max_address = 0
            for buf_id in cache_bufs:
                if str(buf_id) in memory_allocation:
                    offset = memory_allocation[str(buf_id)]
                    if offset >= 0:  # 计算所有已分配的缓冲区
                        size = buffer_info[buf_id]['size']
                        total_used += size
                        # 计算实际使用的地址范围
                        end_address = offset + size
                        if end_address > max_address:
                            max_address = end_address

            cache_utilization[cache_type] = {
                "used": total_used,  # 使用所有已分配缓冲区的总大小
                "capacity": self.cache_capacity[cache_type],
                "utilization_rate": total_used / self.cache_capacity[cache_type] if self.cache_capacity[cache_type] > 0 else 0,
                "base_capacity": self.base_cache_capacity[cache_type],
                "adjustment_ratio": 1.0  # 固定为1.0
            }

        successful_allocations = len([x for x in memory_allocation.values() if x >= 0])

        # 重新计算spill成本，确保正确性
        recalculated_spill_cost = 0
        for op in spill_operations:
            buf_id = op['buf_id']
            buf_info = buffer_info.get(str(buf_id))  # 确保buf_id是字符串类型
            if buf_info:
                # 如果被COPY_IN使用，搬运成本为Size，否则为2*Size
                if buf_info.get('has_copy_in', False):
                    recalculated_spill_cost += buf_info['size']
                else:
                    recalculated_spill_cost += 2 * buf_info['size']
            else:
                # 如果找不到缓冲区信息，尝试通过节点查找
                for node in nodes:
                    if node.get('Op') == 'ALLOC' and str(node.get('BufId')) == str(buf_id):
                        size = node['Size']
                        has_copy_in = str(buf_id) in copy_in_bufs
                        if has_copy_in:
                            recalculated_spill_cost += size
                        else:
                            recalculated_spill_cost += 2 * size
                        break

        # 使用重新计算的spill成本
        total_spill_cost = recalculated_spill_cost

        # 在调度序列中插入SPILL节点
        schedule_with_spill = self._insert_spill_nodes(schedule, spill_operations, node_dict, len(nodes))
        
        problem3_result = {
            "algorithm": "基于传统策略的L1UB优化算法",
            "total_spill_cost": total_spill_cost,
            "spill_operations_count": len(spill_operations),
            "allocated_buffers_count": len(memory_allocation),
            "memory_allocation": memory_allocation,
            "spill_operations": spill_operations,
            "cache_utilization": cache_utilization,
            "dynamic_capacity_adjustment": {
                "enabled": False,  # 禁用动态容量调整
                "adjustment_interval": 0,
                "total_allocations_processed": 0,
                "capacity_changes": {}
            },
            "machine_learning_features": {
                "access_pattern_prediction": "disabled",
                "load_trend_analysis": "disabled",  # 禁用负载趋势分析
                "buffer_lifetime_prediction": "disabled"
            },
            "performance_metrics": {
                "memory_efficiency": 1.0 - (total_spill_cost / sum(info['size'] for info in buffer_info.values())) if sum(info['size'] for info in buffer_info.values()) > 0 else 0,
                "allocation_success_rate": successful_allocations / len(buffer_info),
                "average_capacity_adjustment": 1.0  # 固定为1.0
            }
        }

        with open('3.json', 'w', encoding='utf-8') as f:
            json.dump(problem3_result, f, indent=2, ensure_ascii=False)

        # 生成符合题目要求的输出文件
        # 生成 task2_schedule.json (使用json后缀代替txt)
        with open('task2_schedule.json', 'w') as f:
            for node_id in schedule_with_spill:
                f.write(f"{node_id}\n")

        # 生成 task2_memory.json (使用json后缀代替txt)
        with open('task2_memory.json', 'w') as f:
            for buf_id, offset in sorted(memory_allocation.items()):
                f.write(f"{buf_id}:{offset}\n")

        # 生成 task2_spill.json (使用json后缀代替txt)
        with open('task2_spill.json', 'w') as f:
            for op in spill_operations:
                f.write(f"{op['buf_id']}:{op['new_offset']}\n")

        # 保留原有的txt格式文件以供兼容
        with open('memory_allocation.txt', 'w') as f:
            for buf_id, offset in sorted(memory_allocation.items()):
                f.write(f"{buf_id}:{offset}\n")

        with open('spill_operations.txt', 'w') as f:
            for op in spill_operations:
                f.write(f"{op['buf_id']}:{op['new_offset']}\n")

        with open('schedule.txt', 'w') as f:
            for node_id in schedule_with_spill:
                f.write(f"{node_id}\n")

        return {
            'total_spill_cost': total_spill_cost,
            'spill_count': len(spill_operations),
            'allocated_buffers': len(memory_allocation),
            'successful_allocations': successful_allocations,
            'performance_metrics': {
                "memory_efficiency": 1.0 - (total_spill_cost / sum(info['size'] for info in buffer_info.values())) if sum(info['size'] for info in buffer_info.values()) > 0 else 0,
                "allocation_success_rate": successful_allocations / len(buffer_info),
                "average_capacity_adjustment": 1.0  # 固定为1.0
            }
        }
        
    def _insert_spill_nodes(self, schedule, spill_operations, node_dict, node_count):
        """在调度序列中插入SPILL节点"""
        # 创建一个包含所有节点的列表，包括SPILL节点
        extended_schedule = list(schedule)
        
        # 为每个spill操作创建SPILL_OUT和SPILL_IN节点
        spill_node_id = node_count
        spill_mapping = {}  # 映射原始spill操作到新节点ID
        
        # 首先创建所有SPILL节点
        for op in spill_operations:
            buf_id = op['buf_id']
            # 创建SPILL_OUT节点
            spill_out_id = spill_node_id
            spill_node_id += 1
            # 创建SPILL_IN节点
            spill_in_id = spill_node_id
            spill_node_id += 1
            
            # 保存映射关系
            spill_mapping[buf_id] = (spill_out_id, spill_in_id)
            
        # 在调度序列中插入SPILL节点
        # 首先找到对应的ALLOC和FREE节点位置
        alloc_positions = {}
        free_positions = {}
        for i, node_id in enumerate(extended_schedule):
            node = node_dict.get(node_id)
            if node and node.get('Op') == 'ALLOC':
                alloc_positions[node['BufId']] = i
            elif node and node.get('Op') == 'FREE':
                free_positions[node['BufId']] = i
                
        # 对于每个spill操作，在ALLOC之后插入SPILL_OUT，在FREE之前插入SPILL_IN
        # 我们需要从后往前插入，以避免位置变化影响
        for op in reversed(spill_operations):
            buf_id = op['buf_id']
            if buf_id in alloc_positions and buf_id in free_positions:
                spill_out_id, spill_in_id = spill_mapping[buf_id]
                alloc_pos = alloc_positions[buf_id]
                free_pos = free_positions[buf_id]
                
                # 在ALLOC之后插入SPILL_OUT
                extended_schedule.insert(alloc_pos + 1, spill_out_id)
                # 更新FREE位置（因为插入了SPILL_OUT）
                free_positions[buf_id] += 1
                free_pos += 1
                # 在FREE之前插入SPILL_IN
                extended_schedule.insert(free_pos, spill_in_id)
                
        return extended_schedule

if __name__ == "__main__":
    start_time = time.time()
    solver = L1UBOptimizedSolver()
    result = solver.solve()
    end_time = time.time()

    print(f"总额外搬运量: {result['total_spill_cost']}")
    print(f"SPILL操作数: {result['spill_count']}")
    print(f"分配成功率: {result['successful_allocations']/result['allocated_buffers']:.2%}")
    print(f"执行时间: {end_time - start_time:.2f}秒")
