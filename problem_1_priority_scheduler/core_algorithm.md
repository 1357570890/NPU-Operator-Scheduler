```python
class InteractiveScheduler:
    """交互式调度器"""
    
    def select_node_by_priority(self):
        """按优先级顺序选择节点"""
        # 获取新入度为0的节点
        new_zero_indegree_nodes = self._get_new_zero_indegree_nodes()
        
        # 获取所有就绪节点
        grouped_ready_nodes = self.get_grouped_ready_nodes()
        
        # 优先级顺序：
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
```