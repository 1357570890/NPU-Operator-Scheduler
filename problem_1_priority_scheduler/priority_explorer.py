#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import copy
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import itertools
import random

# 从interactive_scheduler_gui.py导入所需的类和函数
from interactive_scheduler_gui import (
    NodeType, CacheType, Node, L0CacheManager, 
    load_graph_from_json, InteractiveScheduler
)

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
        
        # 生成所有可能的排列组合数量太大，我们采用随机采样
        patterns = []
        # 生成50个随机排列
        for _ in range(50):
            pattern = list(categories)
            random.shuffle(pattern)
            patterns.append(tuple(pattern))
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
    
    def explore_top_patterns(self, top_n=10):
        """探索前N个最优的优先级模式"""
        results = []
        
        # 评估所有模式
        for i, pattern in enumerate(self.priority_patterns):
            print(f"正在评估第 {i+1} 个优先级模式...")
            result = self.evaluate_pattern(pattern)
            results.append(result)
        
        # 按最大内存使用量排序
        results.sort(key=lambda x: x['max_memory'])
        
        return results

def main():
    """主函数"""
    # 加载图数据
    nodes, edges = load_graph_from_json('1.json')
    
    # 创建优先级组合探索器
    explorer = PriorityCombinationExplorer(nodes, edges)
    
    print(f"总共有 {len(explorer.priority_patterns)} 种优先级组合")
    print("开始探索最优的优先级模式...")
    
    # 探索最优的优先级模式
    results = explorer.explore_top_patterns(50)
    
    # 只输出最优解
    best_result = results[0]
    print(f"\n最优解:")
    print(f"最大内存使用量: {best_result['max_memory']}")
    print(f"调度长度: {best_result['schedule_length']}")
    print(f"优先级模式: {best_result['pattern']}")
    
    # 保存最优解到result.json
    with open('result.json', 'w', encoding='utf-8') as f:
        for node_id in best_result['schedule']:
            f.write(f"{node_id}\n")
    print(f"最优解已保存到 result.json")

if __name__ == "__main__":
    main()