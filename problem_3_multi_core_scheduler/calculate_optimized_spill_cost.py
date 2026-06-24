import json
from problem3_optimization import load_spill_operations

# 加载计算图数据
with open('1.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
nodes = {n['Id']: n for n in data['Nodes']}

# 从FlashAttention_Case0_spill.txt加载SPILL操作
spill_list = load_spill_operations('FlashAttention_Case0_spill.txt')

# 计算SPILL成本
total_spill_cost = 0
for buf_id, new_offset in spill_list:
    # 获取缓冲区大小
    for node in nodes.values():
        if node.get('Op') == 'ALLOC' and node.get('BufId') == buf_id:
            buf_size = node['Size']
            spill_cost = buf_size * 2  # SPILL成本为缓冲区大小的2倍
            total_spill_cost += spill_cost
            print(f"Buffer {buf_id}: size={buf_size}, cost={spill_cost}")
            break

print(f"Optimized SPILL cost: {total_spill_cost}")