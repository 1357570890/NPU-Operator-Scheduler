#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import copy
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum

class NodeType(Enum):
    ALLOC = "ALLOC"
    FREE = "FREE"
    COMPUTE = "COMPUTE"
    COPY_IN = "COPY_IN"
    COPY_OUT = "COPY_OUT"

class CacheType(Enum):
    L0A = "L0A"
    L0B = "L0B"
    L0C = "L0C"
    L1 = "L1"
    UB = "UB"
    OTHER = "OTHER"

@dataclass
class Node:
    id: int
    op: NodeType
    size: int = 0
    type: CacheType = CacheType.OTHER
    buf_id: int = -1
    bufs: List[int] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)

class L0CacheManager:
    """L0缓存管理器"""
    def __init__(self):
        self.l0_locks: Dict[str, Optional[int]] = {"L0A": None, "L0B": None, "L0C": None}
    
    def can_allocate_l0(self, l0_type: str, buf_id: int) -> bool:
        """检查是否可以分配L0缓存"""
        return self.l0_locks[l0_type] is None
    
    def allocate_l0(self, l0_type: str, buf_id: int):
        """分配L0缓存"""
        self.l0_locks[l0_type] = buf_id
    
    def free_l0(self, l0_type: str, buf_id: int):
        """释放L0缓存"""
        if self.l0_locks[l0_type] == buf_id:
            self.l0_locks[l0_type] = None

class PriorityCombinationExplorer:
    """优先级组合探索器"""
    
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges
        self.priority_patterns = self._generate_priority_patterns()
    
    def _generate_priority_patterns(self):
        """生成所有优先级组合模式"""
        # 定义优先级类别
        categories = [
            'new_l0_free',
            'old_l0_free', 
            'new_l1_ub_free',
            'old_l1_ub_free',
            'new_other',
            'old_other',
            'new_l0_alloc',
            'old_l0_alloc',
            'new_l1_ub_alloc', 
            'old_l1_ub_alloc'
        ]
        
        # 生成所有可能的排列组合
        import itertools
        patterns = list(itertools.permutations(categories))
        return patterns
    
    def evaluate_pattern(self, pattern):
        """评估特定优先级模式的效果"""
        # 创建调度器实例
        scheduler = InteractiveScheduler(self.nodes, self.edges)
        
        # 设置特定的优先级模式
        scheduler.set_priority_pattern(pattern)
        
        # 执行调度直到完成
        while scheduler.remaining_nodes:
            node_id = scheduler.select_node_by_priority()
            if node_id is None:
                # 无法继续调度，可能有循环依赖
                break
            scheduler.execute_node(node_id)
        
        # 返回评估结果
        max_memory = max([trace['memory'] for trace in scheduler.get_memory_trace()]) if scheduler.get_memory_trace() else 0
        return {
            'pattern': pattern,
            'max_memory': max_memory,
            'schedule_length': len(scheduler.current_schedule),
            'schedule': scheduler.current_schedule
        }

class InteractiveScheduler:
    """交互式调度器"""
    
    def __init__(self, nodes: List[Node], edges: List[Tuple[int, int]]):
        self.original_nodes = nodes
        self.original_edges = edges
        self.priority_pattern = None  # 当前优先级模式
        self.nodes = []
        self.edges = []
        self.schedule_history = []
        self.current_schedule = []
        self.remaining_nodes = set()
        self.l0_manager = L0CacheManager()
        self.current_memory = 0
        self.l1_memory = 0
        self.ub_memory = 0
        self.memory_trace = []
        self.in_degree = []
        self.reset()
    
    def reset(self):
        """重置调度器状态"""
        self.nodes = copy.deepcopy(self.original_nodes)
        self.edges = copy.deepcopy(self.original_edges)
        self.schedule_history = []  # 调度历史记录
        self.current_schedule = []  # 当前调度序列
        self.remaining_nodes = set(range(len(self.nodes)))  # 剩余未调度节点
        self.l0_manager = L0CacheManager()
        self.current_memory = 0  # 当前内存使用量
        self.l1_memory = 0  # L1内存使用量
        self.ub_memory = 0  # UB内存使用量
        self.memory_trace = []  # 内存使用轨迹
        self.in_degree = [0] * len(self.nodes)  # 入度
        
        # 计算入度
        for src, dst in self.edges:
            self.in_degree[dst] += 1
            
        # 构建邻接表
        for node in self.nodes:
            node.successors = []
            node.predecessors = []
            
        for src, dst in self.edges:
            self.nodes[src].successors.append(dst)
            self.nodes[dst].predecessors.append(src)
    
    def get_memory_trace(self):
        """获取内存轨迹"""
        return self.memory_trace
    
    def get_ready_nodes(self) -> List[int]:
        """获取当前可调度的节点（入度为0且满足L0约束）"""
        ready = []
        for node_id in self.remaining_nodes:
            if self.in_degree[node_id] == 0:
                node = self.nodes[node_id]
                # 检查L0约束
                if node.op == NodeType.ALLOC and node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
                    if not self.l0_manager.can_allocate_l0(node.type.value, node.buf_id):
                        continue
                ready.append(node_id)
        return ready
    
    def set_priority_pattern(self, pattern):
        """设置优先级模式"""
        self.priority_pattern = pattern
    
    def get_grouped_ready_nodes(self):
        """获取按操作类型分组的就绪节点"""
        ready_nodes = self.get_ready_nodes()
        
        # 按操作类型分组
        l0_nodes = []
        l1_ub_nodes = []
        other_nodes = []
        
        for node_id in ready_nodes:
            node = self.nodes[node_id]
            if node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
                l0_nodes.append(node_id)
            elif node.type in [CacheType.L1, CacheType.UB]:
                l1_ub_nodes.append(node_id)
            else:
                other_nodes.append(node_id)
                
        return {
            'l0': l0_nodes,
            'l1_ub': l1_ub_nodes,
            'other': other_nodes
        }
    
    def _get_new_zero_indegree_nodes(self):
        """获取新入度为0的节点（内部方法）"""
        new_zero_indegree_nodes = {
            'l0': [],
            'l1_ub': [],
            'other': []
        }
        
        # 如果有调度历史，获取最新一步操作后新入度为0的节点
        if self.schedule_history:
            last_state = self.schedule_history[-1]
            current_in_degree = self.in_degree
            last_in_degree = last_state['in_degree']
            
            for node_id in self.remaining_nodes:
                # 如果当前入度为0，但上一步不为0，则是新入度为0的节点
                if current_in_degree[node_id] == 0 and last_in_degree[node_id] != 0:
                    node = self.nodes[node_id]
                    if node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
                        new_zero_indegree_nodes['l0'].append(node_id)
                    elif node.type in [CacheType.L1, CacheType.UB]:
                        new_zero_indegree_nodes['l1_ub'].append(node_id)
                    else:
                        new_zero_indegree_nodes['other'].append(node_id)
                        
        return new_zero_indegree_nodes
    
    def select_node_by_priority(self):
        """按优先级顺序选择节点"""
        # 如果没有设置特定模式，使用默认模式
        if self.priority_pattern is None:
            return self._default_priority_selection()
        
        # 根据设置的模式选择节点
        return self._pattern_based_selection()
    
    def _default_priority_selection(self):
        """默认优先级选择"""
        # 获取新入度为0的节点
        new_zero_indegree_nodes = self._get_new_zero_indegree_nodes()
        
        # 获取所有就绪节点
        grouped_ready_nodes = self.get_grouped_ready_nodes()
        
        # 默认优先级顺序：
        # 1. 新入度为0的L0中的FREE
        new_l0_free = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                      if self.nodes[node_id].op == NodeType.FREE]
        if new_l0_free:
            return new_l0_free[0]
            
        # 2. 旧入度为0的L0中的FREE
        l0_free = [node_id for node_id in grouped_ready_nodes['l0'] 
                  if self.nodes[node_id].op == NodeType.FREE]
        if l0_free:
            return l0_free[0]
            
        # 3. 新入度为0的L1+UB中的FREE
        new_l1_ub_free = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                         if self.nodes[node_id].op == NodeType.FREE]
        if new_l1_ub_free:
            return new_l1_ub_free[0]
            
        # 4. 旧入度为0的L1+UB中的FREE
        l1_ub_free = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                     if self.nodes[node_id].op == NodeType.FREE]
        if l1_ub_free:
            return l1_ub_free[0]
            
        # 5. 新入度为0的其他操作 - 按bufs数量排序，数量多的优先
        new_other = [node_id for node_id in new_zero_indegree_nodes['other']]
        if new_other:
            new_other.sort(key=lambda x: len(self.nodes[x].bufs), reverse=True)
            return new_other[0]
            
        # 6. 旧入度为0的其他操作 - 按bufs数量排序，数量多的优先
        other = [node_id for node_id in grouped_ready_nodes['other']]
        if other:
            other.sort(key=lambda x: len(self.nodes[x].bufs), reverse=True)
            return other[0]
            
        # 7. 新入度为0的L0中的ALLOC
        new_l0_alloc = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                       if self.nodes[node_id].op == NodeType.ALLOC]
        if new_l0_alloc:
            return new_l0_alloc[0]
            
        # 8. 旧入度为0的L0中的ALLOC
        l0_alloc = [node_id for node_id in grouped_ready_nodes['l0'] 
                   if self.nodes[node_id].op == NodeType.ALLOC]
        if l0_alloc:
            return l0_alloc[0]
            
        # 9. 新入度为0的L1+UB中的ALLOC
        new_l1_ub_alloc = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                          if self.nodes[node_id].op == NodeType.ALLOC]
        if new_l1_ub_alloc:
            return new_l1_ub_alloc[0]
            
        # 10. 旧入度为0的L1+UB中的ALLOC
        l1_ub_alloc = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                      if self.nodes[node_id].op == NodeType.ALLOC]
        if l1_ub_alloc:
            return l1_ub_alloc[0]
            
        # 没有可执行的节点
        return None
    
    def _pattern_based_selection(self):
        """基于模式的优先级选择"""
        # 获取新入度为0的节点
        new_zero_indegree_nodes = self._get_new_zero_indegree_nodes()
        
        # 获取所有就绪节点
        grouped_ready_nodes = self.get_grouped_ready_nodes()
        
        # 按照设置的模式顺序检查
        if self.priority_pattern:
            for category in self.priority_pattern:
                if category == 'new_l0_free':
                    new_l0_free = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                                  if self.nodes[node_id].op == NodeType.FREE]
                    if new_l0_free:
                        return new_l0_free[0]
                        
                elif category == 'old_l0_free':
                    l0_free = [node_id for node_id in grouped_ready_nodes['l0'] 
                              if self.nodes[node_id].op == NodeType.FREE]
                    if l0_free:
                        return l0_free[0]
                        
                elif category == 'new_l1_ub_free':
                    new_l1_ub_free = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                                     if self.nodes[node_id].op == NodeType.FREE]
                    if new_l1_ub_free:
                        return new_l1_ub_free[0]
                        
                elif category == 'old_l1_ub_free':
                    l1_ub_free = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                                 if self.nodes[node_id].op == NodeType.FREE]
                    if l1_ub_free:
                        return l1_ub_free[0]
                        
                elif category == 'new_other':
                    new_other = [node_id for node_id in new_zero_indegree_nodes['other']]
                    if new_other:
                        # 按bufs数量排序，数量多的优先
                        new_other.sort(key=lambda x: len(self.nodes[x].bufs), reverse=True)
                        return new_other[0]
                        
                elif category == 'old_other':
                    other = [node_id for node_id in grouped_ready_nodes['other']]
                    if other:
                        # 按bufs数量排序，数量多的优先
                        other.sort(key=lambda x: len(self.nodes[x].bufs), reverse=True)
                        return other[0]
                        
                elif category == 'new_l0_alloc':
                    new_l0_alloc = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                                   if self.nodes[node_id].op == NodeType.ALLOC]
                    if new_l0_alloc:
                        return new_l0_alloc[0]
                        
                elif category == 'old_l0_alloc':
                    l0_alloc = [node_id for node_id in grouped_ready_nodes['l0'] 
                               if self.nodes[node_id].op == NodeType.ALLOC]
                    if l0_alloc:
                        return l0_alloc[0]
                        
                elif category == 'new_l1_ub_alloc':
                    new_l1_ub_alloc = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                                      if self.nodes[node_id].op == NodeType.ALLOC]
                    if new_l1_ub_alloc:
                        return new_l1_ub_alloc[0]
                        
                elif category == 'old_l1_ub_alloc':
                    l1_ub_alloc = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                                  if self.nodes[node_id].op == NodeType.ALLOC]
                    if l1_ub_alloc:
                        return l1_ub_alloc[0]
        
        # 没有可执行的节点
        return None

    def can_execute_node(self, node_id: int) -> bool:
        """检查是否可以执行指定节点"""
        if node_id not in self.remaining_nodes or self.in_degree[node_id] != 0:
            return False
            
        # 检查L0约束
        node = self.nodes[node_id]
        if node.op == NodeType.ALLOC and node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
            if not self.l0_manager.can_allocate_l0(node.type.value, node.buf_id):
                return False
                
        # 检查内存约束（这里可以添加更复杂的内存检查逻辑）
        # 例如，检查是否有足够的内存来执行节点
        # 这里简化处理，假设所有节点都可以执行
        return True
    
    def execute_node(self, node_id: int) -> bool:
        """执行指定节点"""
        # 检查是否可以执行节点
        if not self.can_execute_node(node_id):
            return False
        
        # 记录操作前状态用于回退
        state = {
            'node_id': node_id,
            'in_degree': self.in_degree.copy(),
            'l0_locks': self.l0_manager.l0_locks.copy(),
            'current_memory': self.current_memory,
            'l1_memory': self.l1_memory,
            'ub_memory': self.ub_memory,
            'remaining_nodes': self.remaining_nodes.copy(),
            'current_schedule': self.current_schedule.copy()
        }
        self.schedule_history.append(state)
        
        # 执行节点
        self.current_schedule.append(node_id)
        self.remaining_nodes.remove(node_id)
        
        # 更新内存使用量
        memory_change = 0
        node = self.nodes[node_id]
        if node.op == NodeType.ALLOC:
            memory_change = node.size
            if node.type == CacheType.L1:
                self.l1_memory += node.size
            elif node.type == CacheType.UB:
                self.ub_memory += node.size
        elif node.op == NodeType.FREE:
            memory_change = -node.size
            if node.type == CacheType.L1:
                self.l1_memory -= node.size
            elif node.type == CacheType.UB:
                self.ub_memory -= node.size
                
        self.current_memory += memory_change
        self.memory_trace.append({
            'step': len(self.current_schedule),
            'node_id': node_id,
            'memory': self.current_memory,
            'l1_memory': self.l1_memory,
            'ub_memory': self.ub_memory
        })
        
        # 更新L0状态
        if node.op == NodeType.ALLOC and node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
            self.l0_manager.allocate_l0(node.type.value, node.buf_id)
        elif node.op == NodeType.FREE and node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
            self.l0_manager.free_l0(node.type.value, node.buf_id)
        
        # 更新后继节点入度
        for succ_id in self.nodes[node_id].successors:
            self.in_degree[succ_id] -= 1
            
        return True
    
    def rollback(self) -> bool:
        """回退上一步操作"""
        if not self.schedule_history:
            return False
            
        # 恢复到上一步状态
        state = self.schedule_history.pop()
        self.in_degree = state['in_degree']
        self.l0_manager.l0_locks = state['l0_locks']
        self.current_memory = state['current_memory']
        self.l1_memory = state['l1_memory']
        self.ub_memory = state['ub_memory']
        self.remaining_nodes = state['remaining_nodes']
        self.current_schedule = state['current_schedule']
        
        # 更新内存轨迹
        if self.memory_trace:
            self.memory_trace.pop()
            
        return True
    
    def get_l0_status(self) -> Dict[str, Optional[int]]:
        """获取L0占用情况"""
        return self.l0_manager.l0_locks
    
    def get_memory_status(self) -> Dict[str, int]:
        """获取内存使用情况"""
        return {
            'total': self.current_memory,
            'l1': self.l1_memory,
            'ub': self.ub_memory,
            'l1_plus_ub': self.l1_memory + self.ub_memory
        }

def load_graph_from_json(file_path: str) -> Tuple[List[Node], List[Tuple[int, int]]]:
    """从JSON文件加载图数据"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    nodes = []
    for i, node_data in enumerate(data['Nodes']):
        node_type = node_data.get('Type', '')
        cache_type = CacheType.OTHER
        if node_type in ['L0A', 'L0B', 'L0C', 'L1', 'UB']:
            cache_type = CacheType(node_type)
            
        # 处理不同的操作类型
        op_str = node_data['Op']
        try:
            op = NodeType(op_str)
        except ValueError:
            # 对于不支持的操作类型，统一归类为COMPUTE
            op = NodeType.COMPUTE
            
        node = Node(
            id=i,
            op=op,
            size=node_data.get('Size', 0),
            type=cache_type,
            buf_id=node_data.get('BufId', -1),
            bufs=node_data.get('Bufs', [])
        )
        nodes.append(node)
    
    edges = [(edge[0], edge[1]) for edge in data['Edges']]
    return nodes, edges

class InteractiveSchedulerGUI:
    """交互式调度器GUI"""
    def __init__(self, root, scheduler: InteractiveScheduler):
        self.root = root
        self.scheduler = scheduler
        self.auto_scheduler = copy.deepcopy(scheduler)  # 用于自动操作的调度器副本
        self.auto_running = False  # 自动运行标志
        self.trace_auto_refresh = True  # 内存使用轨迹自动刷新标志
        self.auto_run_delay = 500  # 自动运行延迟时间（毫秒）
        self.max_l1_ub_memory = 0  # 最大L1+UB内存占用
        self.fast_simulate_update_gui = True  # 高速推算模式是否更新GUI
        self.comparison_mode = False  # 对比模式标志
        self.setup_ui()
        self.update_display()
    
    def setup_ui(self):
        """设置UI界面"""
        self.root.title("交互式调度器")
        self.root.geometry("1200x800")
        
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="交互式调度器", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))
        
        # 控制按钮框架
        control_frame = ttk.LabelFrame(main_frame, text="控制面板", padding="10")
        control_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        # 控制按钮
        self.rollback_btn = ttk.Button(control_frame, text="回退 (Ctrl+Z)", command=self.rollback)
        self.rollback_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.reset_btn = ttk.Button(control_frame, text="重置", command=self.reset)
        self.reset_btn.grid(row=0, column=1, padx=(0, 10))
        
        # 自动运行按钮
        self.auto_run_btn = ttk.Button(control_frame, text="开始自动运行", command=self.toggle_auto_run)
        self.auto_run_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 自动运行时间设置
        ttk.Label(control_frame, text="自动运行间隔(ms):").grid(row=0, column=3, padx=(0, 5))
        self.auto_run_delay_var = tk.StringVar(value=str(self.auto_run_delay))
        self.auto_run_delay_entry = ttk.Entry(control_frame, textvariable=self.auto_run_delay_var, width=10)
        self.auto_run_delay_entry.grid(row=0, column=4, padx=(0, 10))
        self.auto_run_delay_entry.bind('<Return>', self.update_auto_run_delay)
        
        # 内存轨迹自动刷新切换按钮
        self.trace_refresh_btn = ttk.Button(control_frame, text="停止轨迹刷新", command=self.toggle_trace_refresh)
        self.trace_refresh_btn.grid(row=0, column=5, padx=(0, 10))
        
        # 高速推算按钮
        self.fast_simulate_btn = ttk.Button(control_frame, text="高速推算", command=self.fast_simulate)
        self.fast_simulate_btn.grid(row=0, column=6, padx=(0, 10))
        
        # 高速推算模式GUI更新切换按钮
        self.fast_sim_update_gui_btn = ttk.Button(control_frame, text="高速推算不更新GUI", command=self.toggle_fast_sim_update_gui)
        self.fast_sim_update_gui_btn.grid(row=0, column=7, padx=(0, 10))
        
        # 对比模式切换按钮
        self.comparison_mode_btn = ttk.Button(control_frame, text="开启对比模式", command=self.toggle_comparison_mode)
        self.comparison_mode_btn.grid(row=0, column=8, padx=(0, 10))
        
        # 统计信息框架
        stats_frame = ttk.LabelFrame(main_frame, text="统计信息", padding="10")
        stats_frame.grid(row=2, column=0, sticky="ns", padx=(0, 10))
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.rowconfigure(4, weight=1)
        stats_frame.rowconfigure(7, weight=1)  # 为新增的入度为0节点区域留出空间
        stats_frame.rowconfigure(12, weight=1)  # 为新入度为0节点区域留出空间
        stats_frame.rowconfigure(14, weight=1)  # 为新入度为0节点区域留出空间
        stats_frame.rowconfigure(16, weight=1)  # 为新入度为0节点区域留出空间
        
        # L0状态
        self.l0_status_label = ttk.Label(stats_frame, text="L0占用情况:", font=("Arial", 10, "bold"))
        self.l0_status_label.grid(row=0, column=0, sticky="w")
        
        self.l0_status_text = scrolledtext.ScrolledText(stats_frame, width=25, height=5, state="disabled")
        self.l0_status_text.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        
        # 内存状态
        self.memory_status_label = ttk.Label(stats_frame, text="内存使用情况:", font=("Arial", 10, "bold"))
        self.memory_status_label.grid(row=2, column=0, sticky="w")
        
        self.memory_status_text = scrolledtext.ScrolledText(stats_frame, width=25, height=6, state="disabled")
        self.memory_status_text.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        
        # 最大L1+UB内存显示
        self.max_l1_ub_label = ttk.Label(stats_frame, text="最大L1+UB内存:", font=("Arial", 10, "bold"))
        self.max_l1_ub_label.grid(row=4, column=0, sticky="w")
        
        self.max_l1_ub_text = ttk.Label(stats_frame, text="0", font=("Arial", 12, "bold"), foreground="blue")
        self.max_l1_ub_text.grid(row=5, column=0, sticky="w", padx=(10, 0), pady=(0, 10))
        
        # 候选集 - 按操作类型分组显示
        self.candidates_label = ttk.Label(stats_frame, text="候选集 (入度为0):", font=("Arial", 10, "bold"))
        self.candidates_label.grid(row=6, column=0, sticky="w")
        
        # L0操作候选集
        self.l0_candidates_label = ttk.Label(stats_frame, text="L0操作:", font=("Arial", 9, "bold"))
        self.l0_candidates_label.grid(row=7, column=0, sticky="w", padx=(10, 0))
        
        self.l0_candidates_listbox = tk.Listbox(stats_frame, width=25, height=4)
        self.l0_candidates_listbox.grid(row=8, column=0, sticky="ew", pady=(0, 5), padx=(10, 0))
        self.l0_candidates_listbox.bind('<Double-Button-1>', self.on_node_selected)
        
        # L1+UB操作候选集
        self.l1_ub_candidates_label = ttk.Label(stats_frame, text="L1+UB操作:", font=("Arial", 9, "bold"))
        self.l1_ub_candidates_label.grid(row=9, column=0, sticky="w", padx=(10, 0))
        
        self.l1_ub_candidates_listbox = tk.Listbox(stats_frame, width=25, height=4)
        self.l1_ub_candidates_listbox.grid(row=10, column=0, sticky="ew", pady=(0, 5), padx=(10, 0))
        self.l1_ub_candidates_listbox.bind('<Double-Button-1>', self.on_node_selected)
        
        # 其他操作候选集
        self.other_candidates_label = ttk.Label(stats_frame, text="其他操作:", font=("Arial", 9, "bold"))
        self.other_candidates_label.grid(row=11, column=0, sticky="w", padx=(10, 0))
        
        self.other_candidates_listbox = tk.Listbox(stats_frame, width=25, height=4)
        self.other_candidates_listbox.grid(row=12, column=0, sticky="ew", pady=(0, 10), padx=(10, 0))
        self.other_candidates_listbox.bind('<Double-Button-1>', self.on_node_selected)
        
        # 新入度为0的节点
        self.new_zero_indegree_label = ttk.Label(stats_frame, text="新入度为0节点:", font=("Arial", 10, "bold"))
        self.new_zero_indegree_label.grid(row=13, column=0, sticky="w", pady=(10, 0))
        
        # 新入度为0的节点 - 按操作类型分组显示
        # L0操作新入度为0节点
        self.new_l0_zero_indegree_label = ttk.Label(stats_frame, text="L0操作:", font=("Arial", 9, "bold"))
        self.new_l0_zero_indegree_label.grid(row=14, column=0, sticky="w", padx=(10, 0))
        
        self.new_l0_zero_indegree_listbox = tk.Listbox(stats_frame, width=25, height=3)
        self.new_l0_zero_indegree_listbox.grid(row=15, column=0, sticky="ew", pady=(0, 5), padx=(10, 0))
        self.new_l0_zero_indegree_listbox.bind('<Double-Button-1>', self.on_new_node_selected)
        
        # L1+UB操作新入度为0节点
        self.new_l1_ub_zero_indegree_label = ttk.Label(stats_frame, text="L1+UB操作:", font=("Arial", 9, "bold"))
        self.new_l1_ub_zero_indegree_label.grid(row=16, column=0, sticky="w", padx=(10, 0))
        
        self.new_l1_ub_zero_indegree_listbox = tk.Listbox(stats_frame, width=25, height=3)
        self.new_l1_ub_zero_indegree_listbox.grid(row=17, column=0, sticky="ew", pady=(0, 5), padx=(10, 0))
        self.new_l1_ub_zero_indegree_listbox.bind('<Double-Button-1>', self.on_new_node_selected)
        
        # 其他操作新入度为0节点
        self.new_other_zero_indegree_label = ttk.Label(stats_frame, text="其他操作:", font=("Arial", 9, "bold"))
        self.new_other_zero_indegree_label.grid(row=18, column=0, sticky="w", padx=(10, 0))
        
        self.new_other_zero_indegree_listbox = tk.Listbox(stats_frame, width=25, height=3)
        self.new_other_zero_indegree_listbox.grid(row=19, column=0, sticky="ew", pady=(0, 10), padx=(10, 0))
        self.new_other_zero_indegree_listbox.bind('<Double-Button-1>', self.on_new_node_selected)
        
        # 详细信息框架
        details_frame = ttk.LabelFrame(main_frame, text="详细信息", padding="10")
        details_frame.grid(row=2, column=1, columnspan=2, sticky="nsew")
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(1, weight=1)
        details_frame.rowconfigure(3, weight=1)
        details_frame.rowconfigure(5, weight=1)
        
        # 当前调度序列
        self.schedule_label = ttk.Label(details_frame, text="当前调度序列:", font=("Arial", 10, "bold"))
        self.schedule_label.grid(row=0, column=0, sticky="w")
        
        self.schedule_text = scrolledtext.ScrolledText(details_frame, height=10, state="disabled")
        self.schedule_text.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        
        # 内存使用轨迹
        self.trace_label = ttk.Label(details_frame, text="内存使用轨迹:", font=("Arial", 10, "bold"))
        self.trace_label.grid(row=2, column=0, sticky="w")
        
        self.trace_text = scrolledtext.ScrolledText(details_frame, height=10, state="disabled")
        self.trace_text.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        
        # 新入度为0节点详情
        self.new_zero_indegree_detail_label = ttk.Label(details_frame, text="新入度为0节点详情:", font=("Arial", 10, "bold"))
        self.new_zero_indegree_detail_label.grid(row=4, column=0, sticky="w")
        
        self.new_zero_indegree_detail_text = scrolledtext.ScrolledText(details_frame, height=8, state="disabled")
        self.new_zero_indegree_detail_text.grid(row=5, column=0, columnspan=2, sticky="nsew")
        
        # 绑定快捷键
        self.root.bind('<Control-z>', lambda e: self.rollback())
    
    def on_node_selected(self, event):
        """当选中节点时执行"""
        # 确定是哪个列表框被选中
        widget = event.widget
        selection = widget.curselection()
        if not selection:
            return
            
        # 获取选中的节点ID
        ready_nodes = self.get_grouped_ready_nodes()
        
        # 根据不同的列表框确定节点列表
        if widget == self.l0_candidates_listbox:
            nodes_list = ready_nodes['l0']
        elif widget == self.l1_ub_candidates_listbox:
            nodes_list = ready_nodes['l1_ub']
        elif widget == self.other_candidates_listbox:
            nodes_list = ready_nodes['other']
        else:
            return
            
        if selection[0] < len(nodes_list):
            node_id = nodes_list[selection[0]]
            # 尝试执行节点
            if self.scheduler.execute_node(node_id):
                # 如果在对比模式下，也执行自动调度器的相同操作
                if self.comparison_mode:
                    self.auto_scheduler.execute_node(node_id)
                self.update_display()
            else:
                # 执行失败，显示错误信息并回退
                messagebox.showerror("错误", f"无法执行节点{node_id}，可能不满足运行要求")
                # 回退操作
                self.scheduler.rollback()
                if self.comparison_mode:
                    self.auto_scheduler.rollback()
                self.update_display()
    
    def on_new_node_selected(self, event):
        """当选中新的入度为0节点时执行"""
        # 确定是哪个列表框被选中
        widget = event.widget
        selection = widget.curselection()
        if not selection:
            return
            
        # 获取新入度为0的节点
        new_zero_indegree_nodes = self.get_new_zero_indegree_nodes()
        
        # 根据不同的列表框确定节点列表
        if widget == self.new_l0_zero_indegree_listbox:
            nodes_list = new_zero_indegree_nodes['l0']
        elif widget == self.new_l1_ub_zero_indegree_listbox:
            nodes_list = new_zero_indegree_nodes['l1_ub']
        elif widget == self.new_other_zero_indegree_listbox:
            nodes_list = new_zero_indegree_nodes['other']
        else:
            return
            
        if selection[0] < len(nodes_list):
            node_id = nodes_list[selection[0]]
            # 尝试执行节点
            if self.scheduler.execute_node(node_id):
                # 如果在对比模式下，也执行自动调度器的相同操作
                if self.comparison_mode:
                    self.auto_scheduler.execute_node(node_id)
                self.update_display()
            else:
                # 执行失败，显示错误信息并回退
                messagebox.showerror("错误", f"无法执行节点{node_id}，可能不满足运行要求")
                # 回退操作
                self.scheduler.rollback()
                if self.comparison_mode:
                    self.auto_scheduler.rollback()
                self.update_display()
    
    def get_grouped_ready_nodes(self):
        """获取按操作类型分组的就绪节点"""
        ready_nodes = self.scheduler.get_ready_nodes()
        
        # 按操作类型分组
        l0_nodes = []
        l1_ub_nodes = []
        other_nodes = []
        
        for node_id in ready_nodes:
            node = self.scheduler.nodes[node_id]
            if node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
                l0_nodes.append(node_id)
            elif node.type in [CacheType.L1, CacheType.UB]:
                l1_ub_nodes.append(node_id)
            else:
                other_nodes.append(node_id)
                
        return {
            'l0': l0_nodes,
            'l1_ub': l1_ub_nodes,
            'other': other_nodes
        }
    
    def get_new_zero_indegree_nodes(self):
        """获取新入度为0的节点"""
        new_zero_indegree_nodes = {
            'l0': [],
            'l1_ub': [],
            'other': []
        }
        
        # 如果有调度历史，获取最新一步操作后新入度为0的节点
        if self.scheduler.schedule_history:
            last_state = self.scheduler.schedule_history[-1]
            current_in_degree = self.scheduler.in_degree
            last_in_degree = last_state['in_degree']
            
            for node_id in self.scheduler.remaining_nodes:
                # 如果当前入度为0，但上一步不为0，则是新入度为0的节点
                if current_in_degree[node_id] == 0 and last_in_degree[node_id] != 0:
                    node = self.scheduler.nodes[node_id]
                    if node.type in [CacheType.L0A, CacheType.L0B, CacheType.L0C]:
                        new_zero_indegree_nodes['l0'].append(node_id)
                    elif node.type in [CacheType.L1, CacheType.UB]:
                        new_zero_indegree_nodes['l1_ub'].append(node_id)
                    else:
                        new_zero_indegree_nodes['other'].append(node_id)
                        
        return new_zero_indegree_nodes
    
    def update_auto_run_delay(self, event=None):
        """更新自动运行延迟时间"""
        try:
            delay = int(self.auto_run_delay_var.get())
            if delay > 0:
                self.auto_run_delay = delay
        except ValueError:
            # 如果输入无效，恢复原来的值
            self.auto_run_delay_var.set(str(self.auto_run_delay))
    
    def fast_simulate(self):
        """高速推算模式"""
        # 创建一个新窗口显示推算结果
        fast_sim_window = tk.Toplevel(self.root)
        fast_sim_window.title("高速推算结果")
        fast_sim_window.geometry("400x300")
        
        # 创建文本框显示结果
        result_text = scrolledtext.ScrolledText(fast_sim_window, state="normal")
        result_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 进行高速推算
        result_text.insert(tk.END, "开始高速推算...\n")
        self.root.update()
        
        # 保存当前状态
        original_scheduler = copy.deepcopy(self.scheduler)
        
        # 进行推算直到没有节点可执行
        max_l1_ub = 0
        steps = 0
        schedule_sequence = []  # 记录调度顺序
        
        while True:
            # 按优先级选择节点
            node_id = self.select_node_by_priority()
            if node_id is None:
                break
                
            # 执行节点
            if not self.scheduler.execute_node(node_id):
                break
                
            # 记录调度顺序
            schedule_sequence.append(node_id)
                
            # 更新最大L1+UB内存
            memory_status = self.scheduler.get_memory_status()
            max_l1_ub = max(max_l1_ub, memory_status['l1_plus_ub'])
            
            # 如果需要更新GUI，则更新显示
            if self.fast_simulate_update_gui:
                self.update_display()
            
            steps += 1
            if steps % 1000 == 0:
                result_text.insert(tk.END, f"已处理 {steps} 步，当前最大L1+UB: {max_l1_ub:,}\n")
                self.root.update()
        
        # 显示最终结果
        result_text.insert(tk.END, f"\n高速推算完成！\n")
        result_text.insert(tk.END, f"总步数: {steps}\n")
        result_text.insert(tk.END, f"最大L1+UB内存占用: {max_l1_ub:,}\n")
        result_text.insert(tk.END, f"\n调度顺序:\n")
        
        # 按1行1个节点的方式输出调度顺序
        for i, node_id in enumerate(schedule_sequence):
            result_text.insert(tk.END, f"{node_id}\n")
        
        # 保存调度顺序到result.json文件
        try:
            with open('result.json', 'w', encoding='utf-8') as f:
                for node_id in schedule_sequence:
                    f.write(f"{node_id}\n")
            result_text.insert(tk.END, f"\n调度顺序已保存到result.json文件\n")
        except Exception as e:
            result_text.insert(tk.END, f"\n保存调度顺序到result.json文件失败: {e}\n")
        
        # 恢复原始状态
        self.scheduler = original_scheduler
        if self.fast_simulate_update_gui:
            self.update_display()
        
        result_text.config(state="disabled")
    
    def update_display(self):
        """更新显示内容"""
        # 更新L0状态
        self.l0_status_text.config(state="normal")
        self.l0_status_text.delete(1.0, tk.END)
        l0_status = self.scheduler.get_l0_status()
        for l0_type, buf_id in l0_status.items():
            if buf_id is not None:
                self.l0_status_text.insert(tk.END, f"{l0_type}: 节点{buf_id}\n")
            else:
                self.l0_status_text.insert(tk.END, f"{l0_type}: 空闲\n")
        self.l0_status_text.config(state="disabled")
        
        # 更新内存状态
        self.memory_status_text.config(state="normal")
        self.memory_status_text.delete(1.0, tk.END)
        memory_status = self.scheduler.get_memory_status()
        self.memory_status_text.insert(tk.END, f"总内存: {memory_status['total']:,}\n")
        self.memory_status_text.insert(tk.END, f"L1内存: {memory_status['l1']:,}\n")
        self.memory_status_text.insert(tk.END, f"UB内存: {memory_status['ub']:,}\n")
        self.memory_status_text.insert(tk.END, f"L1+UB: {memory_status['l1_plus_ub']:,}\n")
        
        # 如果在对比模式下，显示自动调度器的状态
        if self.comparison_mode:
            self.memory_status_text.insert(tk.END, "\n--- 自动调度器状态 ---\n")
            auto_memory_status = self.auto_scheduler.get_memory_status()
            self.memory_status_text.insert(tk.END, f"总内存: {auto_memory_status['total']:,}\n")
            self.memory_status_text.insert(tk.END, f"L1内存: {auto_memory_status['l1']:,}\n")
            self.memory_status_text.insert(tk.END, f"UB内存: {auto_memory_status['ub']:,}\n")
            self.memory_status_text.insert(tk.END, f"L1+UB: {auto_memory_status['l1_plus_ub']:,}\n")
            
        self.memory_status_text.config(state="disabled")
        
        # 更新最大L1+UB内存显示
        self.max_l1_ub_text.config(text=f"{self.max_l1_ub_memory:,}")
        
        # 更新候选集 - 按操作类型分组显示
        grouped_ready_nodes = self.get_grouped_ready_nodes()
        
        # 更新L0操作候选集
        self.l0_candidates_listbox.delete(0, tk.END)
        for node_id in grouped_ready_nodes['l0']:
            node = self.scheduler.nodes[node_id]
            self.l0_candidates_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新L1+UB操作候选集
        self.l1_ub_candidates_listbox.delete(0, tk.END)
        for node_id in grouped_ready_nodes['l1_ub']:
            node = self.scheduler.nodes[node_id]
            self.l1_ub_candidates_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新其他操作候选集
        self.other_candidates_listbox.delete(0, tk.END)
        for node_id in grouped_ready_nodes['other']:
            node = self.scheduler.nodes[node_id]
            self.other_candidates_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新新入度为0的节点 - 按操作类型分组显示
        new_zero_indegree_nodes = self.get_new_zero_indegree_nodes()
        
        # 更新L0操作新入度为0节点
        self.new_l0_zero_indegree_listbox.delete(0, tk.END)
        for node_id in new_zero_indegree_nodes['l0']:
            node = self.scheduler.nodes[node_id]
            self.new_l0_zero_indegree_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新L1+UB操作新入度为0节点
        self.new_l1_ub_zero_indegree_listbox.delete(0, tk.END)
        for node_id in new_zero_indegree_nodes['l1_ub']:
            node = self.scheduler.nodes[node_id]
            self.new_l1_ub_zero_indegree_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新其他操作新入度为0节点
        self.new_other_zero_indegree_listbox.delete(0, tk.END)
        for node_id in new_zero_indegree_nodes['other']:
            node = self.scheduler.nodes[node_id]
            self.new_other_zero_indegree_listbox.insert(tk.END, f"节点{node_id}: {node.op.value} {node.type.value} {node.size}")
        
        # 更新新入度为0节点详情
        self.new_zero_indegree_detail_text.config(state="normal")
        self.new_zero_indegree_detail_text.delete(1.0, tk.END)
        
        # 显示所有新入度为0节点的详情
        all_new_nodes = (new_zero_indegree_nodes['l0'] + 
                        new_zero_indegree_nodes['l1_ub'] + 
                        new_zero_indegree_nodes['other'])
        
        for node_id in all_new_nodes:
            node = self.scheduler.nodes[node_id]
            self.new_zero_indegree_detail_text.insert(tk.END, f"节点{node_id}:\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  操作类型: {node.op.value}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  缓存类型: {node.type.value}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  大小: {node.size}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  缓冲区ID: {node.buf_id}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  前驱节点: {node.predecessors}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, f"  后继节点: {node.successors}\n")
            self.new_zero_indegree_detail_text.insert(tk.END, "\n")
        
        self.new_zero_indegree_detail_text.config(state="disabled")
        
        # 更新调度序列
        self.schedule_text.config(state="normal")
        self.schedule_text.delete(1.0, tk.END)
        for i, node_id in enumerate(self.scheduler.current_schedule):
            node = self.scheduler.nodes[node_id]
            self.schedule_text.insert(tk.END, f"{i+1}. 节点{node_id}: {node.op.value} {node.type.value} {node.size}\n")
            
        # 如果在对比模式下，显示自动调度器的调度序列
        if self.comparison_mode:
            self.schedule_text.insert(tk.END, "\n--- 自动调度器调度序列 ---\n")
            for i, node_id in enumerate(self.auto_scheduler.current_schedule):
                node = self.auto_scheduler.nodes[node_id]
                self.schedule_text.insert(tk.END, f"{i+1}. 节点{node_id}: {node.op.value} {node.type.value} {node.size}\n")
                
        self.schedule_text.config(state="disabled")
        
        # 更新内存轨迹显示
        self.update_trace_display()
        
        # 更新最大L1+UB内存
        self.max_l1_ub_memory = max(self.max_l1_ub_memory, memory_status['l1_plus_ub'])
        
        # 更新按钮状态
        self.rollback_btn.config(state="normal" if self.scheduler.schedule_history else "disabled")
    
    def toggle_trace_refresh(self):
        """切换内存使用轨迹自动刷新"""
        self.trace_auto_refresh = not self.trace_auto_refresh
        if self.trace_auto_refresh:
            self.trace_refresh_btn.config(text="停止轨迹刷新")
        else:
            self.trace_refresh_btn.config(text="开始轨迹刷新")
    
    def update_trace_display(self):
        """更新内存使用轨迹显示"""
        # 保存当前滚动位置
        old_scroll_pos = self.trace_text.yview()
        
        # 更新内存轨迹
        self.trace_text.config(state="normal")
        self.trace_text.delete(1.0, tk.END)
        for trace in self.scheduler.memory_trace:
            node = self.scheduler.nodes[trace['node_id']]
            self.trace_text.insert(tk.END, f"步骤{trace['step']}: 节点{trace['node_id']} - "
                                  f"操作:{node.op.value} 类型:{node.type.value} 大小:{node.size} "
                                  f"总内存: {trace['memory']:,}, "
                                  f"L1: {trace['l1_memory']:,}, "
                                  f"UB: {trace['ub_memory']:,}\n")
        self.trace_text.config(state="disabled")
        
        # 恢复滚动位置
        if not self.trace_auto_refresh:
            self.trace_text.yview_moveto(old_scroll_pos[0])
    
    def toggle_auto_run(self):
        """切换自动运行状态"""
        self.auto_running = not self.auto_running
        if self.auto_running:
            self.auto_run_btn.config(text="停止自动运行")
            self.auto_run_step()  # 开始自动运行
        else:
            self.auto_run_btn.config(text="开始自动运行")
    
    def auto_run_step(self):
        """自动运行一步"""
        if not self.auto_running:
            return
            
        # 按优先级顺序选择节点
        node_id = self.select_node_by_priority()
        
        if node_id is not None:
            # 尝试执行节点
            if self.scheduler.execute_node(node_id):
                # 如果在对比模式下，也执行自动调度器的相同操作
                if self.comparison_mode:
                    self.auto_scheduler.execute_node(node_id)
                self.update_display()
            else:
                # 执行失败，回退并停止自动运行
                self.scheduler.rollback()
                if self.comparison_mode:
                    self.auto_scheduler.rollback()
                self.update_display()
                self.auto_running = False
                self.auto_run_btn.config(text="开始自动运行")
                messagebox.showerror("错误", f"无法执行节点{node_id}，自动运行已停止")
                return
        else:
            # 没有可执行的节点，停止自动运行
            self.auto_running = False
            self.auto_run_btn.config(text="开始自动运行")
            messagebox.showinfo("提示", "没有可执行的节点，自动运行已停止")
            return
            
        # 0.5秒后继续自动运行
        self.root.after(500, self.auto_run_step)
    
    def select_node_by_priority(self):
        """按优先级顺序选择节点"""
        # 获取新入度为0的节点
        new_zero_indegree_nodes = self.get_new_zero_indegree_nodes()
        
        # 获取所有就绪节点
        grouped_ready_nodes = self.get_grouped_ready_nodes()
        
        # 优先级顺序：
        # 1. 新入度为0的L0中的FREE
        new_l0_free = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                      if self.scheduler.nodes[node_id].op == NodeType.FREE]
        if new_l0_free:
            return new_l0_free[0]
            
        # 2. 旧入度为0的L0中的FREE
        l0_free = [node_id for node_id in grouped_ready_nodes['l0'] 
                  if self.scheduler.nodes[node_id].op == NodeType.FREE]
        if l0_free:
            return l0_free[0]
            
        # 3. 新入度为0的L1+UB中的FREE
        new_l1_ub_free = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                         if self.scheduler.nodes[node_id].op == NodeType.FREE]
        if new_l1_ub_free:
            return new_l1_ub_free[0]
            
        # 4. 旧入度为0的L1+UB中的FREE
        l1_ub_free = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                     if self.scheduler.nodes[node_id].op == NodeType.FREE]
        if l1_ub_free:
            return l1_ub_free[0]
            
        # 5. 新入度为0的其他操作
        new_other = [node_id for node_id in new_zero_indegree_nodes['other']]
        if new_other:
            return new_other[0]
            
        # 6. 旧入度为0的其他操作
        other = [node_id for node_id in grouped_ready_nodes['other']]
        if other:
            return other[0]
            
        # 7. 新入度为0的L0中的ALLOC
        new_l0_alloc = [node_id for node_id in new_zero_indegree_nodes['l0'] 
                       if self.scheduler.nodes[node_id].op == NodeType.ALLOC]
        if new_l0_alloc:
            return new_l0_alloc[0]
            
        # 8. 旧入度为0的L0中的ALLOC
        l0_alloc = [node_id for node_id in grouped_ready_nodes['l0'] 
                   if self.scheduler.nodes[node_id].op == NodeType.ALLOC]
        if l0_alloc:
            return l0_alloc[0]
            
        # 9. 新入度为0的L1+UB中的ALLOC
        new_l1_ub_alloc = [node_id for node_id in new_zero_indegree_nodes['l1_ub'] 
                          if self.scheduler.nodes[node_id].op == NodeType.ALLOC]
        if new_l1_ub_alloc:
            return new_l1_ub_alloc[0]
            
        # 10. 旧入度为0的L1+UB中的ALLOC
        l1_ub_alloc = [node_id for node_id in grouped_ready_nodes['l1_ub'] 
                      if self.scheduler.nodes[node_id].op == NodeType.ALLOC]
        if l1_ub_alloc:
            return l1_ub_alloc[0]
            
        # 没有可执行的节点
        return None
    
    def toggle_fast_sim_update_gui(self):
        """切换高速推算模式是否更新GUI"""
        self.fast_simulate_update_gui = not self.fast_simulate_update_gui
        if self.fast_simulate_update_gui:
            self.fast_sim_update_gui_btn.config(text="高速推算不更新GUI")
        else:
            self.fast_sim_update_gui_btn.config(text="高速推算更新GUI")
    
    def toggle_comparison_mode(self):
        """切换对比模式"""
        self.comparison_mode = not self.comparison_mode
        if self.comparison_mode:
            self.comparison_mode_btn.config(text="关闭对比模式")
            # 初始化自动调度器副本
            self.auto_scheduler = copy.deepcopy(self.scheduler)
        else:
            self.comparison_mode_btn.config(text="开启对比模式")
    
    def rollback(self):
        """回退操作"""
        if self.scheduler.rollback():
            # 如果在对比模式下，也回退自动调度器
            if self.comparison_mode:
                self.auto_scheduler.rollback()
            self.update_display()
        else:
            messagebox.showinfo("提示", "没有可回退的操作")
    
    def reset(self):
        """重置调度器"""
        self.scheduler.reset()
        # 如果在对比模式下，也重置自动调度器
        if self.comparison_mode:
            self.auto_scheduler.reset()
        self.update_display()

def main():
    """主函数"""
    # 创建示例数据文件（如果不存在）
    try:
        nodes, edges = load_graph_from_json('1.json')
    except FileNotFoundError:
        # 创建示例数据
        nodes = [
            Node(0, NodeType.ALLOC, 100, CacheType.L1, 0),
            Node(1, NodeType.COMPUTE, 0, CacheType.OTHER, -1),
            Node(2, NodeType.FREE, 100, CacheType.L1, 0),
            Node(3, NodeType.ALLOC, 200, CacheType.UB, 1),
            Node(4, NodeType.COMPUTE, 0, CacheType.OTHER, -1),
            Node(5, NodeType.FREE, 200, CacheType.UB, 1)
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
        
        # 保存示例数据
        data = {
            "Nodes": [
                {"Op": "ALLOC", "Size": 100, "Type": "L1", "BufId": 0},
                {"Op": "COMPUTE", "Size": 0},
                {"Op": "FREE", "Size": 100, "Type": "L1", "BufId": 0},
                {"Op": "ALLOC", "Size": 200, "Type": "UB", "BufId": 1},
                {"Op": "COMPUTE", "Size": 0},
                {"Op": "FREE", "Size": 200, "Type": "UB", "BufId": 1}
            ],
            "Edges": edges
        }
        
        with open('1.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 创建调度器
    scheduler = InteractiveScheduler(nodes, edges)
    
    # 创建GUI应用
    root = tk.Tk()
    app = InteractiveSchedulerGUI(root, scheduler)
    root.mainloop()

if __name__ == "__main__":
    main()