import json

def detailed_address_analysis():
    # 加载数据
    with open('3.json', 'r', encoding='utf-8') as f:
        solution_data = json.load(f)
    
    memory_allocation = solution_data['memory_allocation']
    
    print("=== 详细地址分配分析 ===")
    
    # 统计每个地址的分配情况
    address_allocation = {}
    for buf_id, offset in memory_allocation.items():
        if offset in address_allocation:
            address_allocation[offset].append(buf_id)
        else:
            address_allocation[offset] = [buf_id]
    
    print(f"不同地址数量: {len(address_allocation)}")
    
    # 按分配的缓冲区数量排序
    sorted_addresses = sorted(address_allocation.items(), key=lambda x: len(x[1]), reverse=True)
    
    print("\n=== 地址分配统计（按缓冲区数量排序） ===")
    for i, (address, buf_ids) in enumerate(sorted_addresses[:15]):
        print(f"{i+1}. 地址 {address}: {len(buf_ids)} 个缓冲区")
        if len(buf_ids) <= 10:
            print(f"   缓冲区: {', '.join(buf_ids)}")
        else:
            print(f"   缓冲区: {', '.join(buf_ids[:10])} ... (共{len(buf_ids)}个)")
        print()
    
    # 检查地址0的特殊情况
    if 0 in address_allocation:
        print("=== 地址0的详细分析 ===")
        buf_ids_at_zero = address_allocation[0]
        print(f"分配到地址0的缓冲区数量: {len(buf_ids_at_zero)}")
        
        # 从1.json中获取这些缓冲区的详细信息
        with open('1.json', 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        
        # 构建缓冲区信息映射
        buffer_info = {}
        for node in graph_data['Nodes']:
            if node.get('Op') == 'ALLOC':
                buf_id = str(node['BufId'])
                buffer_info[buf_id] = {
                    'size': node['Size'],
                    'type': node['Type']
                }
        
        # 分析地址0的缓冲区信息
        zero_address_buffers = []
        for buf_id in buf_ids_at_zero:
            if buf_id in buffer_info:
                zero_address_buffers.append({
                    'buf_id': buf_id,
                    'size': buffer_info[buf_id]['size'],
                    'type': buffer_info[buf_id]['type']
                })
        
        print(f"地址0缓冲区详细信息:")
        type_count = {}
        size_count = {}
        
        for buf in zero_address_buffers:
            # 统计类型
            buf_type = buf['type']
            if buf_type in type_count:
                type_count[buf_type] += 1
            else:
                type_count[buf_type] = 1
                
            # 统计大小
            buf_size = buf['size']
            if buf_size in size_count:
                size_count[buf_size] += 1
            else:
                size_count[buf_size] = 1
        
        print(f"  类型分布: {type_count}")
        print(f"  大小分布: {size_count}")
        
        # 显示前20个缓冲区
        print(f"  前20个缓冲区:")
        for i, buf in enumerate(zero_address_buffers[:20]):
            print(f"    {i+1}. 缓冲区 {buf['buf_id']}: 类型={buf['type']}, 大小={buf['size']}")

def check_allocation_algorithm():
    """检查分配算法问题"""
    print("\n=== 检查分配算法问题 ===")
    
    # 查看3.json中的cache_utilization信息
    with open('3.json', 'r', encoding='utf-8') as f:
        solution_data = json.load(f)
    
    cache_utilization = solution_data.get('cache_utilization', {})
    print("缓存利用率信息:")
    for cache_type, info in cache_utilization.items():
        print(f"  {cache_type}:")
        print(f"    使用量: {info['used']}")
        print(f"    容量: {info['capacity']}")
        print(f"    利用率: {info['utilization_rate']:.4f}")
        print()

if __name__ == "__main__":
    detailed_address_analysis()
    check_allocation_algorithm()