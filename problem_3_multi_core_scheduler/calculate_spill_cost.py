import json

# 加载计算图数据
with open('1.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
nodes = {n['Id']: n for n in data['Nodes']}

# 从spill_operations.txt加载SPILL操作
spill_list = []
with open('spill_operations.txt', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if ':' in line:
            buf_id, offset = line.split(':')
            spill_list.append((int(buf_id), int(offset)))

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

print(f"Total SPILL cost: {total_spill_cost}")