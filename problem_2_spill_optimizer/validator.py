import json
import time
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, deque

class ConstraintValidator:
    def __init__(self):
        self.cache_capacity = {'L1': 4096, 'UB': 1024, 'L0A': 256, 'L0B': 256, 'L0C': 512}
        self.execution_units = {
            'MTE1': 'L1L0数据搬运单元',
            'MTE2': 'DDRL1数据搬运单元', 
            'MTE3': 'UB数据搬运单元',
            'FIXP': '数据搬运单元',
            'CUBE': '矩阵乘法计算单元',  # 统一大小写
            'Cube': '矩阵乘法计算单元',
            'Vector': '向量计算单元',
            'VECTOR': '向量计算单元'
        }
        
        # 允许的操作类型
        self.valid_operations = {
            'ALLOC', 'FREE', 'COPY_IN', 'COPY_OUT', 'MOVE', 'MMAD', 'ADD', 'MUL', 
            'EXP', 'CONV', 'SPILL_IN', 'SPILL_OUT', 'CONV_ADD', 'D2S', 'S2D',
            'SOFTMAX', 'ATTENTION', 'MATMUL', 'RELU', 'SIGMOID', 'TANH',
            'COPY', 'ROWMAX', 'COMPACT', 'SUB', 'ROWSUM', 'MAX', 'REC'  # 新增的操作类型
        }
        
    def validate_solution(self) -> Dict:
        """验证问题3解的约束和结论"""
        print("开始验证解的约束条件...")
        
        # 读取JSON文件
        with open('1.json', 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        with open('2.json', 'r', encoding='utf-8') as f:
            # 修改：2.json现在是纯调度顺序列表
            schedule_data = f.read().strip().split('\n')
            schedule_data = [int(x) for x in schedule_data if x.strip()]
        with open('3.json', 'r', encoding='utf-8') as f:
            solution_data = json.load(f)
        
        # 读取TXT文件
        txt_data = self._load_txt_files()
        
        nodes = graph_data['Nodes']
        # 修改：schedule现在直接是节点ID列表
        schedule = schedule_data
        memory_allocation = solution_data['memory_allocation']
        spill_operations = solution_data['spill_operations']
        
        # 构建节点映射
        node_dict = {node['Id']: node for node in nodes}
        
        # 验证结果
        validation_results = {
            'constraint_violations': [],
            'warnings': [],
            'statistics': {},
            'overall_valid': True
        }
        
        # 验证跨文件数据一致性
        print("验证跨文件数据一致性...")
        consistency_violations = self._check_cross_file_consistency(graph_data, schedule_data, solution_data, txt_data)
        if consistency_violations:
            validation_results['constraint_violations'].extend(consistency_violations)
            validation_results['overall_valid'] = False
        
        # 验证调度序列拓扑序合规性
        print("验证调度序列拓扑序合规性...")
        topology_violations = self._check_topological_order(graph_data, schedule_data)
        if topology_violations:
            validation_results['constraint_violations'].extend(topology_violations)
            validation_results['overall_valid'] = False
        
        # 验证SIMD架构约束
        print("验证SIMD架构约束...")
        simd_violations = self._check_simd_constraints(nodes)
        if simd_violations:
            validation_results['constraint_violations'].extend(simd_violations)
            validation_results['overall_valid'] = False
        
        # 验证缓存类型约束
        print("验证缓存类型约束...")
        cache_type_violations = self._check_cache_type_constraints(nodes)
        if cache_type_violations:
            validation_results['constraint_violations'].extend(cache_type_violations)
            validation_results['overall_valid'] = False
        
        # 验证缓冲区生命周期规则
        print("验证缓冲区生命周期规则...")
        lifetime_violations = self._check_buffer_lifetime_rules(nodes, schedule)
        if lifetime_violations:
            validation_results['constraint_violations'].extend(lifetime_violations)
            validation_results['overall_valid'] = False
        
        # 验证最小缓存驻留指标(max(V_stay))
        print("计算最小缓存驻留指标...")
        vstay_result = self._calculate_max_vstay(nodes, schedule)
        validation_results['max_vstay_analysis'] = vstay_result
        
        # 验证TXT文件格式和内容
        print("验证TXT文件格式和内容...")
        txt_violations = self._validate_txt_files(txt_data, solution_data, nodes)
        if txt_violations:
            validation_results['constraint_violations'].extend(txt_violations)
            validation_results['overall_valid'] = False
        
        # 约束1: 地址不重叠验证
        print("验证地址不重叠约束...")
        overlap_violations = self._check_address_overlap(nodes, schedule, memory_allocation, node_dict)
        if overlap_violations:
            validation_results['constraint_violations'].extend(overlap_violations)
            validation_results['overall_valid'] = False
        
        # 约束2: 缓存容量限制验证
        print("验证缓存容量限制...")
        capacity_violations = self._check_capacity_limits(nodes, memory_allocation)
        if capacity_violations:
            validation_results['constraint_violations'].extend(capacity_violations)
            validation_results['overall_valid'] = False
        
        # 约束3: SPILL操作合规性
        print("验证SPILL操作合规性...")
        spill_violations = self._check_spill_validity(spill_operations, nodes)
        if spill_violations:
            validation_results['constraint_violations'].extend(spill_violations)
            validation_results['overall_valid'] = False
        
        # 约束4: 调度序列完整性
        print("验证调度序列完整性...")
        schedule_violations = self._check_schedule_completeness(nodes, schedule)
        if schedule_violations:
            validation_results['constraint_violations'].extend(schedule_violations)
            validation_results['overall_valid'] = False
        
        # 约束5: SPILL节点属性验证
        print("验证SPILL节点属性...")
        spill_attr_violations = self._check_spill_attributes(spill_operations)
        if spill_attr_violations:
            validation_results['constraint_violations'].extend(spill_attr_violations)
            validation_results['overall_valid'] = False
        
        # 性能指标验证
        print("计算性能指标...")
        validation_results['statistics'] = self._calculate_performance_metrics(
            solution_data, nodes, memory_allocation, spill_operations)
        
        # 额外性能分析
        performance_analysis = self._analyze_performance_issues(solution_data, validation_results['statistics'], nodes, memory_allocation)
        validation_results['performance_analysis'] = performance_analysis
        
        if performance_analysis['critical_issues']:
            validation_results['warnings'].extend(performance_analysis['critical_issues'])
        
        return validation_results
    
    def _analyze_performance_issues(self, solution_data: Dict, stats: Dict, nodes: List, memory_allocation: Dict) -> Dict:
        """分析性能问题"""
        issues = []
        recommendations = []
        
        # 分配成功率分析
        if stats['allocation_success_rate'] < 0.5:
            issues.append(f"分配成功率过低({stats['allocation_success_rate']:.1%})，需要优化SPILL策略")
            recommendations.append("建议优先选择有COPY_IN关联的缓冲区进行SPILL")
        
        # 缓存利用率分析
        if stats['average_utilization'] < 0.3:
            issues.append(f"平均缓存利用率过低({stats['average_utilization']:.1%})，存在空间浪费")
            recommendations.append("建议优化缓存分配算法，减少碎片化")
        
        # SPILL成本分析
        # 使用更合理的指标进行比较
        total_allocated_size = sum(node['Size'] for node in nodes if node.get('Op') == 'ALLOC' and str(node['BufId']) in memory_allocation and memory_allocation[str(node['BufId'])] >= 0)
        if stats['total_spill_cost'] > total_allocated_size:
            issues.append(f"SPILL成本过高({stats['total_spill_cost']})，影响性能")
            recommendations.append("建议优化调度序列，减少缓冲区生命周期重叠")
        
        return {
            'critical_issues': issues,
            'recommendations': recommendations,
            'performance_score': min(100, int(stats['allocation_success_rate'] * 50 + stats['average_utilization'] * 50))
        }
    
    def _check_address_overlap(self, nodes: List, schedule: List, 
                              memory_allocation: Dict, node_dict: Dict) -> List[str]:
        """检查地址重叠"""
        violations = []
        
        # 计算缓冲区生命周期
        buffer_lifetime = {}
        buffer_info = {}
        
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                buf_id = node['BufId']
                buffer_info[buf_id] = {'size': node['Size'], 'type': node['Type']}
        
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
        
        # 按缓存类型检查重叠
        for cache_type in self.cache_capacity:
            # L0A/L0B/L0C缓存特殊处理：同一时刻仅1个缓冲区驻留
            if cache_type in ['L0A', 'L0B', 'L0C']:
                cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items() 
                             if info['type'] == cache_type and buf_id in memory_allocation and memory_allocation[buf_id] >= 0]
                
                # 检查同一时刻是否有多个缓冲区驻留
                # 构建时间线事件
                events = []
                for buf_id, info in cache_bufs:
                    if buf_id in buffer_lifetime:
                        start, end = buffer_lifetime[buf_id]
                        events.append((start, 1, buf_id))  # 1表示分配
                        events.append((end, -1, buf_id))   # -1表示释放
                
                # 按时间排序
                events.sort()
                
                # 检查任意时刻的驻留缓冲区数量
                current_count = 0
                for time, event_type, buf_id in events:
                    current_count += event_type
                    if current_count > 1:
                        violations.append(f"{cache_type}缓存违反约束：同一时刻最多仅1个缓冲区驻留，但在时间点{time}有{current_count}个缓冲区驻留")
                        break
            else:
                # 其他缓存类型检查地址重叠
                cache_bufs = [(buf_id, info) for buf_id, info in buffer_info.items() 
                             if info['type'] == cache_type and buf_id in memory_allocation]
                
                for i, (buf1_id, buf1_info) in enumerate(cache_bufs):
                    for j, (buf2_id, buf2_info) in enumerate(cache_bufs[i+1:], i+1):
                        if self._lifetimes_overlap(buffer_lifetime.get(buf1_id), 
                                                 buffer_lifetime.get(buf2_id)):
                            addr1 = memory_allocation[buf1_id]
                            addr2 = memory_allocation[buf2_id]
                            size1 = buf1_info['size']
                            size2 = buf2_info['size']
                            
                            if self._addresses_overlap(addr1, size1, addr2, size2):
                                violations.append(
                                    f"{cache_type}缓存中BufId {buf1_id}[{addr1}:{addr1+size1}]与"
                                    f"BufId {buf2_id}[{addr2}:{addr2+size2}]地址重叠"
                                )
        
        return violations
    
    def _lifetimes_overlap(self, lifetime1: Optional[Tuple], lifetime2: Optional[Tuple]) -> bool:
        """检查生命周期是否重叠"""
        if not lifetime1 or not lifetime2:
            return False
        start1, end1 = lifetime1
        start2, end2 = lifetime2
        return not (end1 < start2 or end2 < start1)
    
    def _addresses_overlap(self, addr1: int, size1: int, addr2: int, size2: int) -> bool:
        """检查地址是否重叠"""
        return not (addr1 + size1 <= addr2 or addr2 + size2 <= addr1)
    
    def _check_capacity_limits(self, nodes: List, memory_allocation: Dict) -> List[str]:
        """检查缓存容量限制"""
        violations = []
        
        # 统计各缓存使用量
        cache_usage = {cache: 0 for cache in self.cache_capacity}
        
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                buf_id = node['BufId']
                cache_type = node['Type']
                size = node['Size']
                
                if buf_id in memory_allocation and memory_allocation[buf_id] > 0:
                    offset = memory_allocation[buf_id]
                    if offset + size > self.cache_capacity[cache_type]:
                        violations.append(
                            f"BufId {buf_id}在{cache_type}缓存中超出容量限制: "
                            f"需要{offset + size}, 容量{self.cache_capacity[cache_type]}"
                        )
        
        return violations
    
    def _check_spill_validity(self, spill_operations: List, nodes: List) -> List[str]:
        """检查SPILL操作合规性"""
        violations = []
        
        if not spill_operations:
            return violations
        
        # 检查SPILL的缓冲区是否存在
        buffer_ids = set()
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                buffer_ids.add(node['BufId'])
        
        for spill_op in spill_operations:
            buf_id = spill_op['buf_id']
            if buf_id not in buffer_ids:
                violations.append(f"SPILL操作中的BufId {buf_id}不存在于原计算图中")
        
        return violations
    
    def _check_schedule_completeness(self, nodes: List, schedule: List) -> List[str]:
        """检查调度序列完整性"""
        violations = []
        
        # 检查所有原始节点是否在调度序列中
        original_node_ids = {node['Id'] for node in nodes}
        schedule_node_ids = set(schedule)
        
        missing_nodes = original_node_ids - schedule_node_ids
        if missing_nodes:
            violations.append(f"调度序列缺少节点: {missing_nodes}")
        
        # 检查是否有多余节点
        extra_nodes = schedule_node_ids - original_node_ids
        if extra_nodes:
            violations.append(f"调度序列包含未知节点(可能为SPILL节点): {extra_nodes}")
        
        return violations
    
    def _check_spill_attributes(self, spill_operations: List) -> List[str]:
        """检查SPILL操作属性"""
        violations = []
        
        for i, spill_op in enumerate(spill_operations):
            # 检查必要字段
            if 'buf_id' not in spill_op:
                violations.append(f"SPILL操作{i}缺少buf_id字段")
            if 'new_offset' not in spill_op:
                violations.append(f"SPILL操作{i}缺少new_offset字段")
            
            # 检查new_offset合理性
            if 'new_offset' in spill_op and spill_op['new_offset'] < 0:
                violations.append(f"SPILL操作{i}的new_offset不能为负数")
        
        return violations
    
    def _load_txt_files(self) -> Dict:
        """加载所有TXT文件"""
        txt_data = {}
        
        # 读取memory_allocation.txt (兼容旧格式)
        try:
            with open('memory_allocation.txt', 'r') as f:
                memory_alloc = {}
                for line in f:
                    line = line.strip()
                    if ':' in line:
                        buf_id, offset = line.split(':');
                        memory_alloc[buf_id] = int(offset)
                txt_data['memory_allocation'] = memory_alloc
        except FileNotFoundError:
            # 尝试读取新的task2_memory.json文件
            try:
                with open('task2_memory.json', 'r') as f:
                    memory_alloc = {}
                    for line in f:
                        line = line.strip()
                        if ':' in line:
                            buf_id, offset = line.split(':');
                            memory_alloc[buf_id] = int(offset)
                    txt_data['memory_allocation'] = memory_alloc
            except FileNotFoundError:
                print("警告: memory_allocation.txt 和 task2_memory.json 文件均未找到")
                txt_data['memory_allocation'] = {}
        
        # 读取spill_operations.txt (兼容旧格式)
        try:
            with open('spill_operations.txt', 'r') as f:
                spill_ops = []
                for line in f:
                    line = line.strip()
                    if ':' in line:
                        buf_id, offset = line.split(':')
                        spill_ops.append({'buf_id': buf_id, 'new_offset': int(offset)})
                txt_data['spill_operations'] = spill_ops
        except FileNotFoundError:
            # 尝试读取新的task2_spill.json文件
            try:
                with open('task2_spill.json', 'r') as f:
                    spill_ops = []
                    for line in f:
                        line = line.strip()
                        if ':' in line:
                            buf_id, offset = line.split(':')
                            spill_ops.append({'buf_id': buf_id, 'new_offset': int(offset)})
                    txt_data['spill_operations'] = spill_ops
            except FileNotFoundError:
                print("警告: spill_operations.txt 和 task2_spill.json 文件均未找到")
                txt_data['spill_operations'] = []
        
        # 读取schedule.txt (兼容旧格式)
        try:
            with open('schedule.txt', 'r') as f:
                schedule = []
                for line in f:
                    line = line.strip()
                    if line:
                        schedule.append(int(line))
                txt_data['schedule'] = schedule
        except FileNotFoundError:
            # 尝试读取新的task2_schedule.json文件
            try:
                with open('task2_schedule.json', 'r') as f:
                    schedule = []
                    for line in f:
                        line = line.strip()
                        if line:
                            schedule.append(int(line))
                    txt_data['schedule'] = schedule
            except FileNotFoundError:
                print("警告: schedule.txt 和 task2_schedule.json 文件均未找到")
                txt_data['schedule'] = []
        
        return txt_data
    
    def _validate_txt_files(self, txt_data: Dict, solution_data: Dict, nodes: List) -> List[str]:
        """验证TXT文件格式和内容正确性"""
        violations = []
        
        # 验证memory_allocation.txt格式
        memory_alloc_txt = txt_data.get('memory_allocation', {})
        if not memory_alloc_txt:
            violations.append("memory_allocation.txt文件为空或格式错误")
        else:
            # 检查格式
            for buf_id, offset in memory_alloc_txt.items():
                if not buf_id.isdigit():
                    violations.append(f"memory_allocation.txt中缓冲区ID '{buf_id}' 格式错误")
                if not isinstance(offset, int):
                    violations.append(f"memory_allocation.txt中偏移量 '{offset}' 不是整数")
        
        # 验证spill_operations.txt格式
        spill_ops_txt = txt_data.get('spill_operations', [])
        for i, op in enumerate(spill_ops_txt):
            if 'buf_id' not in op or 'new_offset' not in op:
                violations.append(f"spill_operations.txt第{i+1}行格式错误")
            elif not op['buf_id'].isdigit():
                violations.append(f"spill_operations.txt第{i+1}行缓冲区ID格式错误")
        
        # 验证schedule.txt格式
        schedule_txt = txt_data.get('schedule', [])
        if not schedule_txt:
            violations.append("schedule.txt文件为空或格式错误")
        else:
            for i, node_id in enumerate(schedule_txt):
                if not isinstance(node_id, int):
                    violations.append(f"schedule.txt第{i+1}行节点ID不是整数")
        
        return violations
    
    def _check_cross_file_consistency(self, graph_data: Dict, schedule_data: List, 
                                    solution_data: Dict, txt_data: Dict) -> List[str]:
        """检查跨文件数据一致性"""
        violations = []
        
        nodes = graph_data['Nodes']
        schedule_json = schedule_data
        memory_allocation_json = solution_data['memory_allocation']
        
        # TXT文件数据
        memory_allocation_txt = txt_data.get('memory_allocation', {})
        spill_operations_txt = txt_data.get('spill_operations', [])
        schedule_txt = txt_data.get('schedule', [])
        
        # 1. 检查JSON与TXT的调度序列一致性
        if schedule_txt and schedule_json != schedule_txt:
            violations.append("2.json与schedule.txt/task2_schedule.json中的调度序列不一致")
        
        # 2. 检查JSON与TXT的内存分配一致性
        for buf_id_str, offset_json in memory_allocation_json.items():
            if buf_id_str in memory_allocation_txt:
                offset_txt = memory_allocation_txt[buf_id_str]
                if offset_json != offset_txt:
                    violations.append(f"BufId {buf_id_str}: 3.json中地址{offset_json}与memory_allocation.txt/task2_memory.json中地址{offset_txt}不一致")
            else:
                violations.append(f"BufId {buf_id_str}在3.json中有分配记录但在memory_allocation.txt/task2_memory.json中缺失")
        
        # 检查TXT文件中是否有JSON中没有的记录
        for buf_id_str in memory_allocation_txt:
            if buf_id_str not in memory_allocation_json:
                violations.append(f"BufId {buf_id_str}在memory_allocation.txt/task2_memory.json中有记录但在3.json中缺失")
        
        # 3. 检查JSON与TXT的溢出操作一致性
        spill_ops_json = solution_data.get('spill_operations', [])
        if len(spill_ops_json) != len(spill_operations_txt):
            violations.append(f"溢出操作数量不一致: 3.json中{len(spill_ops_json)}个，spill_operations.txt/task2_spill.json中{len(spill_operations_txt)}个")
        
        # 检查具体溢出操作内容
        spill_dict_json = {str(op['buf_id']): op['new_offset'] for op in spill_ops_json}
        spill_dict_txt = {op['buf_id']: op['new_offset'] for op in spill_operations_txt}
        
        for buf_id, offset_json in spill_dict_json.items():
            if buf_id in spill_dict_txt:
                offset_txt = spill_dict_txt[buf_id]
                if offset_json != offset_txt:
                    violations.append(f"溢出操作BufId {buf_id}: 3.json中地址{offset_json}与spill_operations.txt/task2_spill.json中地址{offset_txt}不一致")
            else:
                violations.append(f"溢出操作BufId {buf_id}在3.json中存在但在spill_operations.txt/task2_spill.json中缺失")
        
        # 4. 原有的基础一致性检查
        original_node_ids = {str(node['Id']) for node in nodes}
        for node_id in schedule_json:
            if str(node_id) not in original_node_ids:
                violations.append(f"调度序列中节点{node_id}不在原始计算图中")
        
        buffer_ids_in_graph = {node['BufId'] for node in nodes if node.get('Op') == 'ALLOC'}
        for buf_id_str in memory_allocation_json:
            buf_id = int(buf_id_str)
            if buf_id not in buffer_ids_in_graph:
                violations.append(f"内存分配中BufId {buf_id}不在原始计算图中")
        
        for buf_id in buffer_ids_in_graph:
            if str(buf_id) not in memory_allocation_json:
                violations.append(f"BufId {buf_id}在原始计算图中但未在内存分配中")
        
        return violations
    
    def _calculate_performance_metrics(self, solution_data: Dict, nodes: List,
                                     memory_allocation: Dict, spill_operations: List) -> Dict:
        """计算性能指标"""
        # 基础统计
        total_buffers = len([n for n in nodes if n.get('Op') == 'ALLOC'])
        allocated_buffers = len([addr for addr in memory_allocation.values() if addr >= 0])  # 修改：包括0地址
        spill_count = len(spill_operations)
        
        # 缓存利用率统计
        cache_stats = {}
        
        for cache_type in self.cache_capacity:
            cache_bufs = [n for n in nodes if n.get('Op') == 'ALLOC' and n['Type'] == cache_type]
            
            # 计算实际使用的最大地址
            max_address = 0
            for node in cache_bufs:
                buf_id = node['BufId']
                if str(buf_id) in memory_allocation:
                    offset = memory_allocation[str(buf_id)]
                    if offset >= 0:  # 包括0地址
                        size = node['Size']
                        end_address = offset + size
                        if end_address > max_address:
                            max_address = end_address
            
            cache_stats[cache_type] = {
                'used': max_address,
                'capacity': self.cache_capacity[cache_type],
                'utilization': max_address / self.cache_capacity[cache_type] if self.cache_capacity[cache_type] > 0 else 0
            }
        
        # 计算不包含L0A, L0B, L0C的平均利用率
        main_cache_types = {k: v for k, v in self.cache_capacity.items() if k not in ['L0A', 'L0B', 'L0C']}
        main_cache_utilization = sum(cache_stats[cache_type]['utilization'] for cache_type in main_cache_types) / len(main_cache_types) if main_cache_types else 0
        
        return {
            'total_buffers': total_buffers,
            'allocated_buffers': allocated_buffers,
            'spill_operations': spill_count,
            'allocation_success_rate': allocated_buffers / total_buffers if total_buffers > 0 else 0,
            'total_spill_cost': solution_data['total_spill_cost'],
            'cache_utilization': cache_stats,
            'average_utilization': main_cache_utilization
        }
    
    def generate_report(self, validation_results: Dict):
        """生成验证报告"""
        print("\n" + "="*50)
        print("约束验证报告")
        print("="*50)
        
        if validation_results['overall_valid']:
            print("✓ 解满足所有约束条件")
            print("✓ 所有输出TXT文件格式正确且与JSON一致")
        else:
            print("✗ 解存在约束违反或文件不一致")
            print("\n约束违反和文件错误:")
            for violation in validation_results['constraint_violations']:
                print(f"  - {violation}")
        
        if validation_results['warnings']:
            print("\n警告:")
            for warning in validation_results['warnings']:
                print(f"  - {warning}")
        
        stats = validation_results['statistics']
        print(f"\n性能统计:")
        print(f"  总缓冲区数: {stats['total_buffers']}")
        print(f"  成功分配数: {stats['allocated_buffers']}")
        print(f"  SPILL操作数: {stats['spill_operations']}")
        print(f"  分配成功率: {stats['allocation_success_rate']:.2%}")
        print(f"  总额外搬运量: {stats['total_spill_cost']}")
        print(f"  平均缓存利用率: {stats['average_utilization']:.2%}")
        
        print("\n各缓存利用率:")
        for cache, util in stats['cache_utilization'].items():
            # 不显示L0A, L0B, L0C的利用率
            if cache not in ['L0A', 'L0B', 'L0C']:
                print(f"  {cache}: {util['utilization']:.2%} ({util['used']}/{util['capacity']})")
            else:
                # L0A, L0B, L0C的利用率设为0
                util['utilization'] = 0
        
        # 性能分析
        if 'performance_analysis' in validation_results:
            analysis = validation_results['performance_analysis']
            print(f"\n性能分析:")
            print(f"  性能评分: {analysis['performance_score']}/100")
            
            if analysis['critical_issues']:
                print("  关键问题:")
                for issue in analysis['critical_issues']:
                    print(f"    - {issue}")
            
            if analysis['recommendations']:
                print("  优化建议:")
                for rec in analysis['recommendations']:
                    print(f"    - {rec}")
        
        # 保存报告
        validation_results['validation_summary'] = {
            'files_validated': [
                '1.json - 原始计算图数据',
                '2.json - 调度序列数据', 
                '3.json - 算法求解结果',
                'memory_allocation.txt/task2_memory.json - 内存分配结果',
                'spill_operations.txt/task2_spill.json - 溢出操作记录',
                'schedule.txt/task2_schedule.json - 执行调度序列'
            ],
            'validation_passed': validation_results['overall_valid'],
            'total_violations': len(validation_results['constraint_violations']),
            'total_warnings': len(validation_results['warnings'])
        }
        with open('validation_report.json', 'w', encoding='utf-8') as f:
            json.dump(validation_results, f, indent=2, ensure_ascii=False)
        
        print(f"\n详细报告已保存至: validation_report.json")
    
    def _check_topological_order(self, graph_data: Dict, schedule_data: List) -> List[str]:
        """验证调度序列是否满足拓扑序"""
        violations = []
        nodes = graph_data['Nodes']
        edges = graph_data['Edges']
        schedule = schedule_data
        
        # 构建节点位置映射
        node_positions = {node_id: pos for pos, node_id in enumerate(schedule)}
        
        # 检查每条边是否满足拓扑序
        for edge in edges:
            src_id, dst_id = edge
            if src_id in node_positions and dst_id in node_positions:
                if node_positions[src_id] >= node_positions[dst_id]:
                    violations.append(f"拓扑序违反: 节点{src_id}应在节点{dst_id}之前执行")
        
        return violations
    
    def _check_simd_constraints(self, nodes: List) -> List[str]:
        """验证SIMD架构约束"""
        violations = []
        
        for node in nodes:
            # 检查执行单元是否有效
            if 'Pipe' in node and node['Pipe']:
                pipe = node['Pipe']
                if pipe not in self.execution_units:
                    violations.append(f"节点{node['Id']}使用了无效的执行单元: {pipe}")
            
            # 检查操作类型是否合理
            op = node.get('Op', '')
            if op and op not in self.valid_operations:
                violations.append(f"节点{node['Id']}使用了未知操作类型: {op}")
        
        return violations
    
    def _check_cache_type_constraints(self, nodes: List) -> List[str]:
        """验证缓存类型约束"""
        violations = []
        
        for node in nodes:
            if node.get('Op') in ['ALLOC', 'FREE'] and 'Type' in node:
                cache_type = node['Type']
                if cache_type not in self.cache_capacity:
                    violations.append(f"节点{node['Id']}使用了无效的缓存类型: {cache_type}")
        
        return violations
    
    def _check_buffer_lifetime_rules(self, nodes: List, schedule: List) -> List[str]:
        """验证缓冲区生命周期规则"""
        violations = []
        
        # 收集ALLOC和FREE节点
        alloc_nodes = {}
        free_nodes = {}
        
        for node in nodes:
            if node.get('Op') == 'ALLOC':
                buf_id = node.get('BufId')
                if buf_id is not None:
                    alloc_nodes[buf_id] = node['Id']
            elif node.get('Op') == 'FREE':
                buf_id = node.get('BufId')
                if buf_id is not None:
                    free_nodes[buf_id] = node['Id']
        
        # 检查每个缓冲区是否都有对应的ALLOC和FREE
        for buf_id in alloc_nodes:
            if buf_id not in free_nodes:
                violations.append(f"缓冲区{buf_id}有ALLOC但缺少对应的FREE")
        
        for buf_id in free_nodes:
            if buf_id not in alloc_nodes:
                violations.append(f"缓冲区{buf_id}有FREE但缺少对应的ALLOC")
        
        # 检查ALLOC在FREE之前
        node_positions = {node_id: pos for pos, node_id in enumerate(schedule)}
        for buf_id in alloc_nodes:
            if buf_id in free_nodes:
                alloc_pos = node_positions.get(alloc_nodes[buf_id])
                free_pos = node_positions.get(free_nodes[buf_id])
                if alloc_pos is not None and free_pos is not None:
                    if alloc_pos >= free_pos:
                        violations.append(f"缓冲区{buf_id}的ALLOC节点应在FREE节点之前")
        
        return violations
    
    def _calculate_max_vstay(self, nodes: List, schedule: List) -> Dict:
        """计算最小缓存驻留指标 max(V_stay)"""
        v_stay = 0
        max_v_stay = 0
        v_stay_history = []
        
        # 构建节点映射
        node_dict = {node['Id']: node for node in nodes}
        
        for node_id in schedule:
            if node_id in node_dict:
                node = node_dict[node_id]
                op = node.get('Op')
                
                if op == 'ALLOC':
                    size = node.get('Size', 0)
                    v_stay += size
                elif op == 'FREE':
                    size = node.get('Size', 0)
                    v_stay -= size
                
                v_stay_history.append((node_id, v_stay))
                max_v_stay = max(max_v_stay, v_stay)
        
        return {
            'max_vstay': max_v_stay,
            'final_vstay': v_stay,
            'vstay_history': v_stay_history,
            'is_balanced': v_stay == 0  # 最终应该为0
        }

def main():
    validator = ConstraintValidator()
    results = validator.validate_solution()
    validator.generate_report(results)
    
    return results['overall_valid']

if __name__ == "__main__":
    is_valid = main()
    if is_valid:
        print("\n解验证通过!")
    else:
        print("\n解验证失败!")