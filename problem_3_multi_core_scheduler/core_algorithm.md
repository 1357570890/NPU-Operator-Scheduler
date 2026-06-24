```python
class PerformanceOptimizer:
    def __init__(self, cache_config):
        self.cache_config = cache_config
        
    def integrated_optimization_v2(self, schedule, nodes, buf_lifecycle, baseline_metrics, max_spill_cost, enable_reorder=False):
        """三位一体集成优化框架"""
        
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
        max_iterations = 2
        
        while iterations < max_iterations:
            # 阶段1：调度序列重构（策略1）
            optimized_schedule = self.advanced_schedule_optimization(
                best_schedule, nodes, buf_lifecycle, best_metrics, enable_reorder
            )
            
            # 阶段2：缓存分配优化（策略2）
            optimized_addr_alloc = self.optimize_cache_allocation_v2(
                optimized_schedule, nodes, buf_lifecycle, best_addr_alloc
            )
            
            # 阶段3：SPILL节点优化（策略3）
            spill_list, total_spill_cost = self.simulate_spill_handling(
                optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc
            )
            
            # 调整SPILL时序
            optimized_schedule, spill_list = self.optimize_spill_timing_v2(
                optimized_schedule, nodes, optimized_addr_alloc, spill_list, best_metrics
            )
            
            # 计算新的执行时间
            new_metrics = self.calculate_baseline_metrics(
                optimized_schedule, nodes, buf_lifecycle, optimized_addr_alloc, spill_list
            )
            
            new_total_time = new_metrics['total_exec_time']
            time_improvement = (best_total_time - new_total_time) / best_total_time if best_total_time > 0 else 0
            
            # 计算多目标得分
            new_score = self.calculate_multi_objective_score(time_improvement, total_spill_cost, baseline_spill_cost)
            
            # 检查是否为最佳解
            if new_score > best_score and total_spill_cost <= max_spill_cost * 1.05:
                best_schedule = optimized_schedule
                best_metrics = new_metrics
                best_addr_alloc = optimized_addr_alloc
                best_spill_list = spill_list
                best_total_time = new_total_time
                best_spill_cost = total_spill_cost
                best_score = new_score
            elif time_improvement > 0.01:
                best_schedule = optimized_schedule
                best_metrics = new_metrics
                best_addr_alloc = optimized_addr_alloc
                best_spill_list = spill_list
                best_total_time = new_total_time
                best_spill_cost = total_spill_cost
            
            iterations += 1
        
        return best_schedule, best_addr_alloc, best_spill_list, best_metrics

    def optimize_cache_allocation_v2(self, schedule, nodes, buf_lifecycle, addr_alloc):
        """策略2：基于数据复用率的地址复用优化"""
        
        # 1. 计算缓冲区复用率
        buffer_reuse_rate = self.calculate_buffer_reuse_rate(schedule, nodes, buf_lifecycle)
        
        # 2. 分离高复用率和低复用率缓冲区
        high_reuse_buffers = {buf_id: rate for buf_id, rate in buffer_reuse_rate.items() if rate >= 2}
        low_reuse_buffers = {buf_id: rate for buf_id, rate in buffer_reuse_rate.items() if rate < 2}
        
        # 3. 重新分配地址
        new_addr_alloc = {}
        
        # 按缓存类型跟踪已分配的地址区域
        cache_allocated_regions = defaultdict(list)
        cache_type_offsets = defaultdict(int)

        # 为高复用率缓冲区分配固定地址区域
        for buf_id in sorted(high_reuse_buffers.keys()):
            if buf_id in buf_lifecycle:
                alloc_node_id = buf_lifecycle[buf_id]['alloc']
                alloc_node = nodes[alloc_node_id]
                cache_type = alloc_node['Type']
                size = alloc_node['Size']
                
                if cache_type in ['L0A', 'L0B', 'L0C']:
                    # L0缓存特殊处理
                    capacity = self.cache_config[cache_type]
                    if cache_type_offsets[cache_type] + size <= capacity:
                        start_addr = cache_type_offsets[cache_type]
                        new_addr_alloc[buf_id] = start_addr
                        cache_allocated_regions[cache_type].append((start_addr, start_addr + size - 1))
                        cache_type_offsets[cache_type] += size
                else:
                    # 非L0缓存处理
                    capacity = int(self.cache_config[cache_type] * 0.85)
                    if cache_type_offsets[cache_type] + size <= capacity:
                        start_addr = cache_type_offsets[cache_type]
                        end_addr = start_addr + size - 1
                        
                        if not self._check_address_conflict(cache_type, start_addr, end_addr, cache_allocated_regions):
                            new_addr_alloc[buf_id] = start_addr
                            cache_allocated_regions[cache_type].append((start_addr, end_addr))
                            cache_type_offsets[cache_type] += size
        
        # 为低复用率缓冲区使用最佳适配算法
        cache_free_blocks = defaultdict(list)
        for cache_type, capacity in self.cache_config.items():
            if cache_type not in ['L0A', 'L0B', 'L0C']:
                start_addr = int(capacity * 0.7)
                remaining_capacity = int(capacity * 0.3)
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
            if cache_type in ['L0A', 'L0B', 'L0C']:
                continue
            
            # 查找最佳适配块
            best_block = None
            best_fit_size = float('inf')
            
            for i, (start, block_size) in enumerate(cache_free_blocks[cache_type]):
                if block_size >= size and block_size < best_fit_size:
                    end_addr = start + size - 1
                    if not self._check_address_conflict(cache_type, start, end_addr, cache_allocated_regions):
                        best_block = i
                        best_fit_size = block_size
            
            # 如果找到合适的块
            if best_block is not None:
                start, block_size = cache_free_blocks[cache_type][best_block]
                new_addr_alloc[buf_id] = start
                
                end_addr = start + size - 1
                cache_allocated_regions[cache_type].append((start, end_addr))
                
                # 更新空闲块列表
                del cache_free_blocks[cache_type][best_block]
                if block_size > size:
                    cache_free_blocks[cache_type].append((start + size, block_size - size))
                cache_free_blocks[cache_type].sort(key=lambda x: x[0])
        
        return new_addr_alloc

    def optimize_spill_timing_v2(self, schedule, nodes, addr_alloc, spill_list, baseline_metrics):
        """策略3：基于负载预测的SPILL节点优化"""
        
        if not spill_list:
            return schedule, spill_list
        
        # 1. MTE单元负载预测（时间窗口法）
        unit_times = baseline_metrics.get('unit_times', {})
        mte_load = defaultdict(lambda: defaultdict(int))
        window_size = 20
        
        for pipe, time_slots in unit_times.items():
            if pipe in ['MTE2', 'MTE3']:
                for slot in time_slots:
                    start = slot.get('start', 0)
                    end = slot.get('end', 0)
                    cycles = slot.get('cycles', 0)
                    
                    start_window = start // window_size
                    end_window = end // window_size
                    
                    remaining_cycles = cycles
                    current_time = start
                    
                    for window in range(start_window, end_window + 1):
                        window_start = window * window_size
                        window_end = (window + 1) * window_size
                        
                        slot_start_in_window = max(current_time, window_start)
                        slot_end_in_window = min(end, window_end)
                        window_cycles = max(0, slot_end_in_window - slot_start_in_window)
                        
                        if window_cycles > 0:
                            mte_load[pipe][window] += window_cycles
                            remaining_cycles -= window_cycles
                            current_time += window_cycles
    
        # 2. 优化SPILL节点插入位置
        spill_info = []
        for buf_id, new_offset in spill_list:
            buf_size = None
            for node_id, node in nodes.items():
                if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
                    buf_size = node['Size']
                    break
            if buf_size is not None:
                spill_info.append((buf_id, new_offset, buf_size))
    
        spill_info.sort(key=lambda x: x[2], reverse=True)
    
        # 3. 合并同类SPILL操作
        spill_groups = defaultdict(list)
        buf_lifecycle_local = get_buf_lifecycle(schedule, nodes)
    
        for buf_id, new_offset, buf_size in spill_info:
            if buf_id in buf_lifecycle_local:
                lifecycle = buf_lifecycle_local[buf_id]
                alloc_node_id = lifecycle['alloc']
                if alloc_node_id in nodes:
                    alloc_node = nodes[alloc_node_id]
                    cache_type = alloc_node['Type']
                    spill_groups[cache_type].append((buf_id, new_offset, buf_size))
    
        merged_spill_list = []
        for cache_type, group in spill_groups.items():
            if len(group) > 1:
                group.sort(key=lambda x: x[2], reverse=True)
                representative_buf_id = group[0][0]
                representative_offset = group[0][1]
                merged_spill_list.append((representative_buf_id, representative_offset))
            else:
                for buf_id, new_offset, buf_size in group:
                    merged_spill_list.append((buf_id, new_offset))
    
        return schedule, merged_spill_list

    def advanced_schedule_optimization(self, schedule, nodes, buf_lifecycle, baseline_metrics, enable_reorder=False):
        """高级调度优化：基于关键路径和资源负载平衡"""
        if not enable_reorder:
            return schedule
            
        # 1. 计算关键路径
        cpm_result = self.calculate_critical_path(schedule, nodes, buf_lifecycle)
        critical_nodes = cpm_result['critical_nodes']
        es_times = cpm_result['es_times']
        
        # 2. 构建依赖图
        dependencies = defaultdict(set)
        reverse_dependencies = defaultdict(set)
        buf_producers = defaultdict(list)
        buf_consumers = defaultdict(list)
        
        # 构建缓冲区生产者和消费者映射
        for node_id, node in nodes.items():
            if 'Bufs' in node:
                op = node.get('Op', '')
                bufs = node['Bufs']
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
            
            for prod in producers:
                dependencies[prod].add(alloc_node)
                reverse_dependencies[alloc_node].add(prod)
            
            for prod in producers:
                for cons in consumers:
                    dependencies[cons].add(prod)
                    reverse_dependencies[prod].add(cons)
            
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
        critical_schedulable = []
        for node_id in critical_nodes:
            if node_id not in processed_nodes and all(dep in new_schedule for dep in dependencies.get(node_id, set())):
                critical_schedulable.append((node_id, es_times.get(node_id, 0)))
        
        critical_schedulable.sort(key=lambda x: x[1])
        for node_id, _ in critical_schedulable:
            new_schedule.append(node_id)
            processed_nodes.add(node_id)
        
        # 按负载差异排序Pipe
        pipe_load_diff = {pipe: abs(load - target_load) for pipe, load in pipe_load.items()}
        sorted_pipes = sorted(pipe_load_diff.keys(), key=lambda x: pipe_load_diff[x], reverse=True)
        
        # 轮流从不同Pipe调度节点以平衡负载
        round_robin_index = 0
        max_rounds = len(schedule)
        
        while len(processed_nodes) < len(schedule) and max_rounds > 0:
            node_scheduled = False
            
            for pipe in sorted_pipes:
                if pipe in pipe_nodes:
                    schedulable_nodes = []
                    for node_info in pipe_nodes[pipe]:
                        node_id, cycles, es = node_info
                        if node_id not in processed_nodes:
                            node_deps = dependencies.get(node_id, set())
                            if all(dep in new_schedule for dep in node_deps):
                                if self._validate_dependencies(node_id, new_schedule, dependencies, reverse_dependencies, nodes):
                                    schedulable_nodes.append((node_id, es))
                    
                    if schedulable_nodes:
                        schedulable_nodes.sort(key=lambda x: x[1])
                        selected_node = schedulable_nodes[0][0]
                        new_schedule.append(selected_node)
                        processed_nodes.add(selected_node)
                        node_scheduled = True
                        break
            
            if not node_scheduled:
                for node_id in schedule:
                    if node_id not in processed_nodes:
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
```