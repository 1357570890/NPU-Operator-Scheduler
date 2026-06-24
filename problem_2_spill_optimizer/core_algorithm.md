# 核心算法代码

## 最佳适配算法

```python
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
```

## 空闲块合并

```python
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
```

## 缓冲区分配

```python
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
```

## Spill候选者选择

```python
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
```