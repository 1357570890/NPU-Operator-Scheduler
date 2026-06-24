import json
from collections import defaultdict, deque
from typing import List, Dict, Tuple, Set, Optional

def load_graph(filename: str) -> Tuple[List[Dict], List[List[int]]]:
    """加载计算图数据"""
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['Nodes'], data['Edges']

def load_schedule_result(filename: str) -> Dict:
    """加载调度结果数据"""
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        
        # 尝试解析为JSON对象
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                # 如果是数组格式，包装成对象
                return {
                    'schedule': data,
                    'algorithm': 'Unknown (Array Format)',
                    'schedule_length': len(data)
                }
        except json.JSONDecodeError:
            # 如果不是有效JSON，尝试作为纯数组解析
            # 移除可能的注释和格式字符
            lines = content.split('\n')
            numbers = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('//'):
                    # 移除尾随逗号
                    line = line.rstrip(',')
                    if line:
                        try:
                            numbers.append(int(line))
                        except ValueError:
                            continue
            return {
                'schedule': numbers,
                'algorithm': 'Unknown (Plain Array)',
                'schedule_length': len(numbers)
            }

def build_adjacency_lists(nodes: List[Dict], edges: List[List[int]]) -> Tuple[Dict[int, List[int]], Dict[int, List[int]]]:
    """构建邻接表"""
    predecessors = defaultdict(list)
    successors = defaultdict(list)
    
    for edge in edges:
        from_node, to_node = edge
        predecessors[to_node].append(from_node)
        successors[from_node].append(to_node)
    
    return predecessors, successors

def validate_schedule_completeness(nodes: List[Dict], schedule: List[int]) -> Tuple[bool, List[str]]:
    """验证调度序列的完整性 - 增强版"""
    errors = []
    
    # 检查基本数据有效性
    if not isinstance(schedule, list):
        errors.append("调度序列不是列表类型")
        return False, errors
    
    if not isinstance(nodes, list):
        errors.append("节点数据不是列表类型")
        return False, errors
    
    # 检查节点数量
    if len(schedule) != len(nodes):
        errors.append(f"调度序列长度{len(schedule)}与节点总数{len(nodes)}不匹配")
    
    # 检查节点ID的有效性
    valid_node_ids = set(range(len(nodes)))
    
    for i, node_id in enumerate(schedule):
        if not isinstance(node_id, int):
            errors.append(f"步骤{i+1}: 节点ID {node_id} 不是整数类型")
        elif node_id < 0:
            errors.append(f"步骤{i+1}: 节点ID {node_id} 为负数")
        elif node_id >= len(nodes):
            errors.append(f"步骤{i+1}: 节点ID {node_id} 超出范围[0, {len(nodes)-1}]")
    
    # 检查是否包含所有节点
    schedule_set = set(schedule)
    
    missing_nodes = valid_node_ids - schedule_set
    if missing_nodes:
        errors.append(f"缺失节点: {sorted(missing_nodes)}")
    
    extra_nodes = schedule_set - valid_node_ids
    if extra_nodes:
        errors.append(f"多余节点: {sorted(extra_nodes)}")
    
    # 增强的重复检测
    duplicates = []
    seen = set()
    duplicate_positions = {}
    
    for i, node_id in enumerate(schedule):
        if node_id in seen:
            duplicates.append(node_id)
            if node_id not in duplicate_positions:
                duplicate_positions[node_id] = []
            duplicate_positions[node_id].append(i + 1)
        seen.add(node_id)
    
    if duplicates:
        for node_id in sorted(set(duplicates)):
            positions = duplicate_positions[node_id]
            errors.append(f"节点{node_id}重复出现在步骤: {positions}")
    
    # 检查节点数据完整性
    for i, node_id in enumerate(schedule):
        if 0 <= node_id < len(nodes):
            node = nodes[node_id]
            if not isinstance(node, dict):
                errors.append(f"步骤{i+1}: 节点{node_id}的数据不是字典类型")
            elif 'Op' not in node:
                errors.append(f"步骤{i+1}: 节点{node_id}缺少Op字段")
    
    return len(errors) == 0, errors

def validate_dependency_constraints(nodes: List[Dict], edges: List[List[int]], schedule: List[int]) -> Tuple[bool, List[str]]:
    """验证依赖约束是否满足"""
    errors = []
    predecessors, _ = build_adjacency_lists(nodes, edges)
    
    # 建立节点在调度序列中的位置映射
    position = {node_id: i for i, node_id in enumerate(schedule)}
    
    # 检查每条边的依赖关系
    for from_node, to_node in edges:
        if from_node not in position or to_node not in position:
            continue
            
        if position[from_node] >= position[to_node]:
            errors.append(f"依赖违反: 节点{from_node}必须在节点{to_node}之前执行")
    
    # 检查每个节点的所有前驱是否都已执行
    for i, node_id in enumerate(schedule):
        for pred in predecessors[node_id]:
            if pred not in position:
                continue
            if position[pred] >= i:
                errors.append(f"前驱违反: 节点{pred}必须在节点{node_id}之前执行")
    
    return len(errors) == 0, errors

class BufferLifecycleTracker:
    """Buffer生命周期跟踪器"""
    
    def __init__(self):
        self.buffers = {}  # buf_id -> BufferInfo
        self.step_states = []  # 每步的buffer状态快照
    
    def add_buffer_info(self, buf_id: int, step: int, op: str, size: int, node_id: int):
        """添加buffer操作信息"""
        if buf_id not in self.buffers:
            self.buffers[buf_id] = {
                'alloc_step': None,
                'free_step': None,
                'alloc_size': 0,
                'free_size': 0,
                'alloc_node': None,
                'free_node': None,
                'usage_steps': [],
                'state': 'unallocated'
            }
        
        if op == 'ALLOC':
            self.buffers[buf_id]['alloc_step'] = step
            self.buffers[buf_id]['alloc_size'] = size
            self.buffers[buf_id]['alloc_node'] = node_id
            self.buffers[buf_id]['state'] = 'allocated'
        elif op == 'FREE':
            self.buffers[buf_id]['free_step'] = step
            self.buffers[buf_id]['free_size'] = size
            self.buffers[buf_id]['free_node'] = node_id
            self.buffers[buf_id]['state'] = 'freed'
        elif op == 'USE':
            self.buffers[buf_id]['usage_steps'].append((step, node_id))
    
    def get_buffer_state_at_step(self, buf_id: int, step: int) -> str:
        """获取指定步骤时buffer的状态"""
        if buf_id not in self.buffers:
            return 'unallocated'
        
        buf_info = self.buffers[buf_id]
        alloc_step = buf_info['alloc_step']
        free_step = buf_info['free_step']
        
        if alloc_step is None:
            return 'unallocated'
        elif alloc_step > step:
            return 'unallocated'
        elif free_step is None:
            return 'allocated'
        elif free_step > step:
            return 'allocated'
        else:
            return 'freed'
    
    def validate_buffer_lifecycle(self) -> Tuple[bool, List[str]]:
        """验证buffer生命周期的完整性"""
        errors = []
        
        for buf_id, info in self.buffers.items():
            # 检查ALLOC/FREE配对
            if info['alloc_step'] is not None and info['free_step'] is None:
                errors.append(f"Buffer {buf_id} 已分配但未释放")
            
            if info['alloc_step'] is None and info['free_step'] is not None:
                errors.append(f"Buffer {buf_id} 未分配就释放")
            
            # 检查大小一致性
            if (info['alloc_step'] is not None and info['free_step'] is not None and 
                info['alloc_size'] != info['free_size']):
                errors.append(f"Buffer {buf_id} 分配大小({info['alloc_size']})与释放大小({info['free_size']})不匹配")
            
            # 检查使用时序
            for use_step, use_node in info['usage_steps']:
                state = self.get_buffer_state_at_step(buf_id, use_step)
                if state != 'allocated':
                    errors.append(f"节点 {use_node} 在步骤 {use_step} 使用了未分配的buffer {buf_id}")
        
        return len(errors) == 0, errors

def validate_buffer_operations(nodes: List[Dict], schedule: List[int]) -> Tuple[bool, List[str]]:
    """验证缓冲区操作的正确性 - 增强版"""
    errors = []
    tracker = BufferLifecycleTracker()
    
    # 第一遍：收集所有buffer操作信息
    for i, node_id in enumerate(schedule):
        if node_id >= len(nodes):
            errors.append(f"步骤{i+1}: 无效的节点ID {node_id}")
            continue
            
        node = nodes[node_id]
        op = node.get('Op', '')
        step = i + 1
        
        # 验证必要字段
        if not op:
            errors.append(f"步骤{step}: 节点{node_id}缺少Op字段")
            continue
        
        if op == 'ALLOC':
            buf_id = node.get('BufId')
            size = node.get('Size', 0)
            
            if buf_id is None:
                errors.append(f"步骤{step}: ALLOC节点{node_id}缺少BufId字段")
                continue
            
            if size <= 0:
                errors.append(f"步骤{step}: ALLOC节点{node_id}的Size({size})无效")
            
            tracker.add_buffer_info(buf_id, step, 'ALLOC', size, node_id)
            
        elif op == 'FREE':
            buf_id = node.get('BufId')
            size = node.get('Size', 0)
            
            if buf_id is None:
                errors.append(f"步骤{step}: FREE节点{node_id}缺少BufId字段")
                continue
            
            if size <= 0:
                errors.append(f"步骤{step}: FREE节点{node_id}的Size({size})无效")
            
            tracker.add_buffer_info(buf_id, step, 'FREE', size, node_id)
        
        # 检查计算操作使用的buffer
        if 'Bufs' in node and isinstance(node['Bufs'], list):
            for buf_id in node['Bufs']:
                if isinstance(buf_id, int):
                    tracker.add_buffer_info(buf_id, step, 'USE', 0, node_id)
    
    # 第二遍：验证buffer状态转换的合法性
    buffer_states = {}  # buf_id -> current_state
    
    for i, node_id in enumerate(schedule):
        if node_id >= len(nodes):
            continue
            
        node = nodes[node_id]
        op = node.get('Op', '')
        step = i + 1
        
        if op == 'ALLOC':
            buf_id = node.get('BufId')
            if buf_id is None:
                continue
                
            current_state = buffer_states.get(buf_id, 'unallocated')
            
            if current_state == 'allocated':
                errors.append(f"步骤{step}: Buffer {buf_id} 重复分配")
            elif current_state == 'freed':
                # 允许重新分配已释放的buffer，但需要检查是否是同一个逻辑buffer
                pass
            
            buffer_states[buf_id] = 'allocated'
            
        elif op == 'FREE':
            buf_id = node.get('BufId')
            if buf_id is None:
                continue
                
            current_state = buffer_states.get(buf_id, 'unallocated')
            
            if current_state != 'allocated':
                errors.append(f"步骤{step}: Buffer {buf_id} 未分配就释放(当前状态: {current_state})")
            
            buffer_states[buf_id] = 'freed'
        
        # 验证计算操作的buffer使用
        if 'Bufs' in node and isinstance(node['Bufs'], list):
            for buf_id in node['Bufs']:
                if isinstance(buf_id, int):
                    current_state = buffer_states.get(buf_id, 'unallocated')
                    if current_state != 'allocated':
                        errors.append(f"步骤{step}: 节点{node_id}使用了未分配的buffer {buf_id}(状态: {current_state})")
    
    # 使用tracker进行生命周期验证
    lifecycle_valid, lifecycle_errors = tracker.validate_buffer_lifecycle()
    errors.extend(lifecycle_errors)
    
    # 检查最终状态
    unreleased = [buf_id for buf_id, state in buffer_states.items() if state == 'allocated']
    if unreleased:
        errors.append(f"未释放的缓冲区: {sorted(unreleased)}")
    
    return len(errors) == 0, errors

def calculate_memory_usage(nodes: List[Dict], schedule: List[int]) -> Tuple[int, List[Tuple[int, int]]]:
    """计算内存使用情况"""
    current_memory = 0
    max_memory = 0
    memory_trace = []
    
    for i, node_id in enumerate(schedule):
        node = nodes[node_id]
        
        if node['Op'] == 'ALLOC':
            current_memory += node['Size']
        elif node['Op'] == 'FREE':
            current_memory -= node['Size']
        
        max_memory = max(max_memory, current_memory)
        memory_trace.append((i + 1, current_memory))
    
    return max_memory, memory_trace

def validate_memory_consistency(nodes: List[Dict], schedule: List[int], schedule_result: Dict, calculated_max_memory: int) -> Tuple[bool, List[str]]:
    """验证内存计算的一致性 - 完整实现"""
    errors = []
    
    # 验证报告的最大内存使用
    reported_max = schedule_result.get('max_memory_usage', 0)
    if abs(reported_max - calculated_max_memory) > 0:
        errors.append(f"内存计算不一致: 报告值{reported_max}, 实际计算值{calculated_max_memory}")
    
    # 详细验证内存轨迹
    if 'memory_trace' in schedule_result:
        trace = schedule_result['memory_trace']
        
        # 重新计算每一步的内存使用
        current_memory = 0
        memory_changes = []
        
        for i, node_id in enumerate(schedule):
            if node_id < len(nodes):
                node = nodes[node_id]
                op = node.get('Op', '')
                size = node.get('Size', 0)
                
                if op == 'ALLOC':
                    current_memory += size
                elif op == 'FREE':
                    current_memory -= size
                
                memory_changes.append({
                    'step': i + 1,
                    'node_id': node_id,
                    'operation': op,
                    'size': size,
                    'current_memory': current_memory
                })
        
        # 与报告的轨迹对比
        if len(trace) != len(memory_changes):
            errors.append(f"内存轨迹长度不匹配: 报告{len(trace)}, 计算{len(memory_changes)}")
        else:
            for i, (reported, calculated) in enumerate(zip(trace, memory_changes)):
                step = i + 1
                
                # 检查步骤编号
                reported_step = reported.get('step', step)
                if reported_step != step:
                    errors.append(f"步骤{step}: 步骤编号不匹配(报告{reported_step})")
                
                # 检查当前内存
                reported_memory = reported.get('current_memory', 0)
                calculated_memory = calculated['current_memory']
                if reported_memory != calculated_memory:
                    errors.append(f"步骤{step}: 内存值不匹配(报告{reported_memory}, 计算{calculated_memory})")
                
                # 检查内存变化
                reported_change = reported.get('memory_change', 0)
                calculated_change = calculated['size'] if calculated['operation'] == 'ALLOC' else (-calculated['size'] if calculated['operation'] == 'FREE' else 0)
                if reported_change != calculated_change:
                    errors.append(f"步骤{step}: 内存变化不匹配(报告{reported_change}, 计算{calculated_change})")
                
                # 检查操作类型
                reported_op = reported.get('operation', '')
                calculated_op = calculated['operation']
                if reported_op != calculated_op:
                    errors.append(f"步骤{step}: 操作类型不匹配(报告{reported_op}, 计算{calculated_op})")
    
    # 检查负内存情况
    current_memory = 0
    for i, node_id in enumerate(schedule):
        if node_id < len(nodes):
            node = nodes[node_id]
            op = node.get('Op', '')
            size = node.get('Size', 0)
            
            if op == 'ALLOC':
                current_memory += size
            elif op == 'FREE':
                current_memory -= size
            
            if current_memory < 0:
                errors.append(f"步骤{i+1}: 内存使用为负数({current_memory})")
    
    return len(errors) == 0, errors

def validate_l0_duplicate_detection(nodes: List[Dict], schedule: List[int]) -> Tuple[bool, List[str]]:
    """L0级别的重复检测 - 核心验证函数
    只检测L0A/L0B/L0C三类缓存，每个缓存类型在同一时刻最多只能有一个缓冲区驻留
    """
    errors = []
    
    # 跟踪每个buffer的详细状态
    buffer_detailed_states = {}  # buf_id -> {'operations': [(step, op, node_id, size)], 'current_state': str}
    
    # 跟踪节点执行状态
    executed_nodes = set()
    
    # 跟踪同时活跃的buffer
    active_buffers = set()
    
    # 跟踪L0缓存级别的使用状态 - 只关心L0A/L0B/L0C
    l0_cache_states = {}  # cache_type -> {'allocated_buffer': buf_id, 'step': int, 'node_id': int}
    
    for i, node_id in enumerate(schedule):
        step = i + 1
        
        # 检查节点重复执行
        if node_id in executed_nodes:
            errors.append(f"L0错误 - 步骤{step}: 节点{node_id}重复执行")
        executed_nodes.add(node_id)
        
        if node_id >= len(nodes):
            continue
            
        node = nodes[node_id]
        op = node.get('Op', '')
        
        if op == 'ALLOC':
            buf_id = node.get('BufId')
            size = node.get('Size', 0)
            cache_type = node.get('Type', '')
            
            if buf_id is not None:
                # 初始化buffer状态跟踪
                if buf_id not in buffer_detailed_states:
                    buffer_detailed_states[buf_id] = {
                        'operations': [],
                        'current_state': 'unallocated',
                        'allocated_size': 0,
                        'allocation_count': 0,
                        'free_count': 0,
                        'cache_type': cache_type
                    }
                
                buf_state = buffer_detailed_states[buf_id]
                
                # 检查重复分配
                if buf_state['current_state'] == 'allocated':
                    errors.append(f"L0错误 - 步骤{step}: Buffer {buf_id} 重复分配")
                
                # 检查分配大小一致性
                if buf_state['allocation_count'] > 0 and buf_state['allocated_size'] != size:
                    errors.append(f"L0错误 - 步骤{step}: Buffer {buf_id} 分配大小不一致(之前{buf_state['allocated_size']}, 现在{size})")
                
                # 检查L0缓存级别冲突 - 只检测L0A/L0B/L0C
                if cache_type and cache_type in ['L0A', 'L0B', 'L0C']:
                    if cache_type in l0_cache_states:
                        existing_info = l0_cache_states[cache_type]
                        existing_buf = existing_info['allocated_buffer']
                        existing_step = existing_info['step']
                        existing_node = existing_info['node_id']
                        
                        # 检查该L0缓存级别是否已被其他buffer占用
                        if existing_buf != buf_id and existing_buf in active_buffers:
                            errors.append(f"L0错误 - 步骤{step}: 缓存级别'{cache_type}'冲突 - "
                                        f"Buffer {buf_id}(节点{node_id})尝试分配到已被Buffer {existing_buf}(节点{existing_node}, 步骤{existing_step})占用的缓存级别")
                    
                    # 更新L0缓存级别状态
                    l0_cache_states[cache_type] = {
                        'allocated_buffer': buf_id,
                        'step': step,
                        'node_id': node_id
                    }
                
                # 更新buffer状态
                buf_state['operations'].append((step, 'ALLOC', node_id, size))
                buf_state['current_state'] = 'allocated'
                buf_state['allocated_size'] = size
                buf_state['allocation_count'] += 1
                buf_state['cache_type'] = cache_type
                active_buffers.add(buf_id)
        
        elif op == 'FREE':
            buf_id = node.get('BufId')
            size = node.get('Size', 0)
            cache_type = node.get('Type', '')
            
            if buf_id is not None:
                if buf_id not in buffer_detailed_states:
                    errors.append(f"L0错误 - 步骤{step}: 尝试释放未知buffer {buf_id}")
                    continue
                
                buf_state = buffer_detailed_states[buf_id]
                
                # 检查释放未分配的buffer
                if buf_state['current_state'] != 'allocated':
                    errors.append(f"L0错误 - 步骤{step}: 尝试释放未分配的buffer {buf_id}(状态: {buf_state['current_state']})")
                
                # 检查释放大小一致性
                if buf_state['allocated_size'] != size:
                    errors.append(f"L0错误 - 步骤{step}: Buffer {buf_id} 释放大小({size})与分配大小({buf_state['allocated_size']})不匹配")
                
                # 释放L0缓存级别 - 只处理L0A/L0B/L0C
                if cache_type and cache_type in ['L0A', 'L0B', 'L0C']:
                    if cache_type in l0_cache_states:
                        current_buf = l0_cache_states[cache_type]['allocated_buffer']
                        if current_buf == buf_id:
                            # 释放该L0缓存级别
                            del l0_cache_states[cache_type]
                        else:
                            errors.append(f"L0错误 - 步骤{step}: 缓存级别'{cache_type}'状态不一致 - "
                                        f"尝试通过Buffer {buf_id}释放，但当前占用者是Buffer {current_buf}")
                
                # 更新buffer状态
                buf_state['operations'].append((step, 'FREE', node_id, size))
                buf_state['current_state'] = 'freed'
                buf_state['free_count'] += 1
                active_buffers.discard(buf_id)
        
        # 检查计算操作的buffer使用
        elif 'Bufs' in node and isinstance(node['Bufs'], list):
            for buf_id in node['Bufs']:
                if isinstance(buf_id, int):
                    if buf_id not in buffer_detailed_states:
                        errors.append(f"L0错误 - 步骤{step}: 节点{node_id}使用未知buffer {buf_id}")
                    elif buffer_detailed_states[buf_id]['current_state'] != 'allocated':
                        errors.append(f"L0错误 - 步骤{step}: 节点{node_id}使用未分配buffer {buf_id}")
                    else:
                        # 记录使用操作
                        buffer_detailed_states[buf_id]['operations'].append((step, 'USE', node_id, 0))
    
    # 最终状态检查
    for buf_id, buf_state in buffer_detailed_states.items():
        # 检查分配/释放配对
        if buf_state['allocation_count'] != buf_state['free_count']:
            if buf_state['allocation_count'] > buf_state['free_count']:
                errors.append(f"L0错误: Buffer {buf_id} 分配{buf_state['allocation_count']}次但只释放{buf_state['free_count']}次")
            else:
                errors.append(f"L0错误: Buffer {buf_id} 释放{buf_state['free_count']}次但只分配{buf_state['allocation_count']}次")
        
        # 检查最终状态
        if buf_state['current_state'] == 'allocated':
            errors.append(f"L0错误: Buffer {buf_id} 最终状态为已分配但未释放")
    
    return len(errors) == 0, errors

def validate_topological_order(nodes: List[Dict], edges: List[List[int]], schedule: List[int]) -> Tuple[bool, List[str]]:
    """验证是否为有效的拓扑排序"""
    errors = []
    predecessors, _ = build_adjacency_lists(nodes, edges)
    
    # 使用Kahn算法验证
    in_degree = [len(predecessors[i]) for i in range(len(nodes))]
    remaining = set(range(len(nodes)))
    
    for node_id in schedule:
        if node_id not in remaining:
            errors.append(f"节点{node_id}不在剩余节点集合中")
            continue
            
        if in_degree[node_id] > 0:
            errors.append(f"节点{node_id}的前驱未完全满足(入度{in_degree[node_id]})")
        
        remaining.remove(node_id)
        
        # 更新后继节点的入度
        for i in range(len(nodes)):
            if i in remaining and node_id in predecessors[i]:
                in_degree[i] -= 1
    
    return len(errors) == 0, errors

def comprehensive_validation(graph_file: str, schedule_result_file: str) -> Dict:
    """综合验证调度结果 - 增强版"""
    # 加载数据
    try:
        nodes, edges = load_graph(graph_file)
        schedule_result = load_schedule_result(schedule_result_file)
        schedule = schedule_result.get('schedule', [])
    except Exception as e:
        return {
            'error': f"数据加载失败: {str(e)}",
            'overall_valid': False
        }
    
    validation_report = {
        'graph_file': graph_file,
        'schedule_file': schedule_result_file,
        'total_nodes': len(nodes),
        'total_edges': len(edges),
        'schedule_length': len(schedule),
        'algorithm_type': detect_schedule_algorithm_type(schedule_result),
        'algorithm_name': schedule_result.get('algorithm', 'Unknown'),
        'validations': {},
        'overall_valid': True,
        'summary': {
            'passed': 0,
            'failed': 0,
            'total_errors': 0,
            'critical_errors': 0,
            'warnings': 0
        }
    }
    
    # 执行各项验证 - 按重要性排序
    validations = [
        ('completeness', '完整性验证', validate_schedule_completeness, (nodes, schedule), 'critical'),
        ('l0_duplicate', 'L0重复检测', validate_l0_duplicate_detection, (nodes, schedule), 'critical'),
        ('dependencies', '依赖约束验证', validate_dependency_constraints, (nodes, edges, schedule), 'critical'),
        ('buffer_ops', '缓冲区操作验证', validate_buffer_operations, (nodes, schedule), 'critical'),
        ('topological', '拓扑排序验证', validate_topological_order, (nodes, edges, schedule), 'important'),
    ]
    
    for test_id, test_name, test_func, test_args, severity in validations:
        try:
            is_valid, errors = test_func(*test_args)
            
            # 分类错误严重程度
            critical_errors = []
            warnings = []
            
            for error in errors:
                if 'L0错误' in error or '重复' in error or '未分配' in error:
                    critical_errors.append(error)
                else:
                    warnings.append(error)
            
            validation_report['validations'][test_id] = {
                'name': test_name,
                'passed': is_valid,
                'errors': errors,
                'critical_errors': critical_errors,
                'warnings': warnings,
                'error_count': len(errors),
                'critical_count': len(critical_errors),
                'warning_count': len(warnings),
                'severity': severity
            }
            
            if is_valid:
                validation_report['summary']['passed'] += 1
            else:
                validation_report['summary']['failed'] += 1
                if severity == 'critical' or critical_errors:
                    validation_report['overall_valid'] = False
            
            validation_report['summary']['total_errors'] += len(errors)
            validation_report['summary']['critical_errors'] += len(critical_errors)
            validation_report['summary']['warnings'] += len(warnings)
            
        except Exception as e:
            validation_report['validations'][test_id] = {
                'name': test_name,
                'passed': False,
                'errors': [f"验证过程出错: {str(e)}"],
                'critical_errors': [f"验证过程出错: {str(e)}"],
                'warnings': [],
                'error_count': 1,
                'critical_count': 1,
                'warning_count': 0,
                'severity': 'critical'
            }
            validation_report['summary']['failed'] += 1
            validation_report['summary']['total_errors'] += 1
            validation_report['summary']['critical_errors'] += 1
            validation_report['overall_valid'] = False
    
    # 内存验证 - 只有在基础验证通过时才执行
    if validation_report['summary']['critical_errors'] == 0:
        try:
            calculated_max, memory_trace = calculate_memory_usage(nodes, schedule)
            is_consistent, mem_errors = validate_memory_consistency(nodes, schedule, schedule_result, calculated_max)
            
            validation_report['validations']['memory'] = {
                'name': '内存计算验证',
                'passed': is_consistent,
                'errors': mem_errors,
                'critical_errors': [e for e in mem_errors if '负数' in e or '不匹配' in e],
                'warnings': [e for e in mem_errors if '负数' not in e and '不匹配' not in e],
                'error_count': len(mem_errors),
                'critical_count': len([e for e in mem_errors if '负数' in e or '不匹配' in e]),
                'warning_count': len([e for e in mem_errors if '负数' not in e and '不匹配' not in e]),
                'severity': 'important'
            }
            
            if not is_consistent:
                validation_report['summary']['failed'] += 1
                if any('负数' in e or '不匹配' in e for e in mem_errors):
                    validation_report['overall_valid'] = False
            else:
                validation_report['summary']['passed'] += 1
            
            validation_report['summary']['total_errors'] += len(mem_errors)
            validation_report['summary']['critical_errors'] += len([e for e in mem_errors if '负数' in e or '不匹配' in e])
            validation_report['summary']['warnings'] += len([e for e in mem_errors if '负数' not in e and '不匹配' not in e])
            
        except Exception as e:
            validation_report['validations']['memory'] = {
                'name': '内存计算验证',
                'passed': False,
                'errors': [f"内存验证出错: {str(e)}"],
                'critical_errors': [f"内存验证出错: {str(e)}"],
                'warnings': [],
                'error_count': 1,
                'critical_count': 1,
                'warning_count': 0,
                'severity': 'important'
            }
            validation_report['summary']['failed'] += 1
            validation_report['summary']['total_errors'] += 1
            validation_report['summary']['critical_errors'] += 1
    
    return validation_report

def print_validation_report(report: Dict):
    """打印验证报告 - 增强版"""
    if 'error' in report:
        print("=" * 60)
        print("验证失败")
        print("=" * 60)
        print(f"错误: {report['error']}")
        return
    
    print("=" * 80)
    print("调度路线验证报告 - L0级别严格检测")
    print("=" * 80)
    print(f"图文件: {report['graph_file']}")
    print(f"调度文件: {report['schedule_file']}")
    print(f"节点总数: {report['total_nodes']}")
    print(f"边总数: {report['total_edges']}")
    print(f"调度长度: {report['schedule_length']}")
    print(f"调度算法: {report.get('algorithm_name', 'Unknown')}")
    print(f"算法类型: {'新添加的算法' if report.get('algorithm_type') == 'new' else '现有的算法'}")
    print()
    
    summary = report['summary']
    print(f"验证摘要:")
    print(f"  ✓ 通过测试: {summary['passed']}")
    print(f"  ✗ 失败测试: {summary['failed']}")
    print(f"  🔴 严重错误: {summary['critical_errors']}")
    print(f"  🟡 警告信息: {summary['warnings']}")
    print(f"  📊 总错误数: {summary['total_errors']}")
    
    # 根据严重程度显示整体结果
    if report['overall_valid']:
        print(f"  🎉 整体结果: 通过")
    else:
        print(f"  ❌ 整体结果: 失败")
    print()
    
    # 按严重程度分组显示结果
    critical_tests = []
    important_tests = []
    other_tests = []
    
    for test_id, test_result in report['validations'].items():
        severity = test_result.get('severity', 'other')
        if severity == 'critical':
            critical_tests.append((test_id, test_result))
        elif severity == 'important':
            important_tests.append((test_id, test_result))
        else:
            other_tests.append((test_id, test_result))
    
    # 显示关键测试结果
    if critical_tests:
        print("🔴 关键验证结果:")
        for test_id, test_result in critical_tests:
            status = "✓" if test_result['passed'] else "✗"
            critical_count = test_result.get('critical_count', 0)
            warning_count = test_result.get('warning_count', 0)
            
            print(f"  {status} {test_result['name']}: {'通过' if test_result['passed'] else '失败'}")
            if critical_count > 0:
                print(f"    🔴 严重错误: {critical_count}")
            if warning_count > 0:
                print(f"    🟡 警告: {warning_count}")
            
            # 显示关键错误
            critical_errors = test_result.get('critical_errors', [])
            if critical_errors:
                print("    关键错误详情:")
                for error in critical_errors[:3]:  # 只显示前3个关键错误
                    print(f"      - {error}")
                if len(critical_errors) > 3:
                    print(f"      ... 还有{len(critical_errors) - 3}个关键错误")
            print()
    
    # 显示重要测试结果
    if important_tests:
        print("🟠 重要验证结果:")
        for test_id, test_result in important_tests:
            status = "✓" if test_result['passed'] else "✗"
            print(f"  {status} {test_result['name']}: {'通过' if test_result['passed'] else '失败'}")
            
            if test_result['errors']:
                for error in test_result['errors'][:3]:  # 只显示前3个错误
                    print(f"    - {error}")
                if len(test_result['errors']) > 3:
                    print(f"    ... 还有{len(test_result['errors']) - 3}个错误")
            print()
    
    # 显示其他测试结果
    if other_tests:
        print("ℹ️  其他验证结果:")
        for test_id, test_result in other_tests:
            status = "✓" if test_result['passed'] else "✗"
            print(f"  {status} {test_result['name']}: {'通过' if test_result['passed'] else '失败'}")
            
            if test_result['errors'] and len(test_result['errors']) <= 2:
                for error in test_result['errors']:
                    print(f"    - {error}")
            elif test_result['errors']:
                print(f"    {len(test_result['errors'])} 个错误 (详情略)")
            print()
    
    # 显示内存验证特殊信息
    if 'memory' in report['validations']:
        mem_result = report['validations']['memory']
        if 'calculated_max_memory' in mem_result:
            print("📊 内存使用分析:")
            print(f"  计算得出的最大内存: {mem_result['calculated_max_memory']}")
            print(f"  报告的最大内存: {mem_result['reported_max_memory']}")
            print()
    
    # 总结建议
    print("💡 建议:")
    if summary['critical_errors'] > 0:
        print("  - 发现严重错误，必须修复后才能使用此调度")
    elif summary['warnings'] > 0:
        print("  - 存在警告信息，建议检查并优化")
    else:
        print("  - 调度验证通过，可以安全使用")
    print()

def detect_schedule_algorithm_type(schedule_result: Dict) -> str:
    """检测调度算法类型
    
    Args:
        schedule_result: 调度结果字典
        
    Returns:
        str: 算法类型描述 ('existing' 或 'new')
    """
    algorithm = schedule_result.get('algorithm', '').lower()
    
    # 如果algorithm包含标识，则基于此判断
    if algorithm and algorithm != 'unknown':
        # 检查算法名称中是否包含L0约束相关关键词
        l0_keywords = ['l0约束', 'l0-aware', 'l0 constraint', '双步预判', 'two-step', '复用贪心', 'reuse greedy']
        
        for keyword in l0_keywords:
            if keyword in algorithm:
                return 'new'  # 新添加的算法
        
        # 检查其他特征来识别现有算法
        if '贪心' in algorithm or 'greedy' in algorithm:
            return 'existing'  # 现有的贪心调度
        
        if '拓扑' in algorithm or 'topological' in algorithm:
            return 'existing'  # 现有的拓扑排序
    
    # 如果algorithm未知，基于数据格式判断
    # 如果是数组格式（没有algorithm字段），认为是新添加的算法
    if 'algorithm' not in schedule_result or algorithm.startswith('Unknown'):
        return 'new'  # 新添加的算法（数组格式）
    
    # 默认情况下，认为是现有的
    return 'existing'

def main():
    """主函数"""
    import sys
    
    # 检查命令行参数
    if len(sys.argv) == 3:
        graph_file = sys.argv[1]
        schedule_file = sys.argv[2]
    else:
        # 默认文件路径
        graph_file = "1.json"
        schedule_file = "2.json"
    
    print("调度路线验证工具")
    print("-" * 40)
    print(f"图文件: {graph_file}")
    print(f"调度文件: {schedule_file}")
    print()
    
    try:
        # 执行验证
        report = comprehensive_validation(graph_file, schedule_file)
        
        # 打印报告
        print_validation_report(report)
        
        
        return report
        
    except FileNotFoundError as e:
        print(f"文件未找到: {e}")
        return None
    except Exception as e:
        print(f"验证过程出错: {e}")
        return None

if __name__ == "__main__":
    main()