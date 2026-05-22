#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - 完整版 v4.0
策略优化：全量解析 → 去重 → TCP全测 → 前300 → 地区检测 → 输出
"""

import re
import json
import time
import socket
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

CONFIG_FILE = "config.json"

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 配置文件加载失败: {e}")
        return {}

config = load_config()

# 正则表达式（支持多种格式）
NODE_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+):(\d+)')
IP_ONLY_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
CSV_IP_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+),(\d+)')

def parse_node_from_line(line):
    """从一行文本中解析IP节点，支持多种格式"""
    line = line.strip()

    if not line or line.startswith('#') or line.startswith('线路名称'):
        return None

    # 跳过纯域名行（没有数字、没有冒号、没有井号、没有逗号）
    if '.' in line and not re.match(r'^\d+\.\d+\.\d+\.\d+', line):
        if not any(c in line for c in ':#,') and not re.search(r'\d', line):
            return None

    # 格式1: ip:port（可能带#注释）
    match = NODE_PATTERN.match(line)
    if match:
        return (match.group(1), int(match.group(2)))

    # 格式2: ip:port#xxx（如 43.168.16.112:443#HK [高速]）
    if ':' in line and '#' in line:
        parts = line.split('#')
        ip_port = parts[0].strip()
        match = NODE_PATTERN.match(ip_port)
        if match:
            return (match.group(1), int(match.group(2)))

    # 格式3: CSV - ip,port,...
    match = CSV_IP_PATTERN.match(line)
    if match:
        try:
            port = int(match.group(2))
            if 1 <= port <= 65535:
                return (match.group(1), port)
        except:
            pass

    # 格式4: 纯IP 或 ip#xxx（提取IP部分）
    parts = line.split('#')
    ip_part = parts[0].strip()

    # 检查是否是有效IP
    ip_match = IP_ONLY_PATTERN.match(ip_part)
    if ip_match:
        return (ip_match.group(1), 443)  # 默认端口443

    # 格式5: CSV格式（跳过表头，第2列可能是IP）
    csv_parts = line.split(',')
    if len(csv_parts) >= 2:
        for col in csv_parts[1:3]:  # 检查第2、3列
            potential_ip = col.strip()
            ip_match = IP_ONLY_PATTERN.match(potential_ip)
            if ip_match:
                return (ip_match.group(1), 443)

    return None

# ========== API函数 ==========

def get_ip_location(ip):
    """获取IP的地理位置信息（多API自动切换）"""
    apis = [
        ("iping.cc", f"https://api.iping.cc/v1/query?ip={ip}&language=zh"),
        ("ip.sb", f"https://api.ip.sb/geoip/{ip}"),
        ("ip-api", f"http://ip-api.com/json/{ip}?lang=zh-CN"),
    ]
    
    for name, url in apis:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            if name == "iping.cc":
                import urllib3
                urllib3.disable_warnings()
                resp = requests.get(url, headers=headers, timeout=15, verify=False)
            else:
                resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                
                if name == "iping.cc":
                    if data.get("code") == 200 and data.get("data"):
                        info = data["data"]
                        country = info.get("country", "") or ""
                        region = info.get("region", "") or ""
                        city = info.get("city", "") or ""
                        location_parts = [p for p in [country, region, city] if p]
                        location = " ".join(location_parts) if location_parts else "未知"
                        risk = info.get("risk_score", 50)
                        
                        return {"success": True, "location": location, 
                               "risk": int(risk) if str(risk).isdigit() else 50, "source": name}
                
                elif name == "ip.sb":
                    country = data.get("country_name", "") or ""
                    region = data.get("region", "") or ""
                    city = data.get("city", "")
                    location_parts = [p for p in [country, region, city] if p]
                    location = " ".join(location_parts) if location_parts else "未知"
                    
                    return {"success": True, "location": location, "risk": 50, "source": name}
                
                elif name == "ip-api":
                    if data.get("status") == "success":
                        country = data.get("country", "") or ""
                        region = data.get("regionName", "") or ""
                        city = data.get("city", "")
                        location_parts = [p for p in [country, region, city] if p]
                        location = " ".join(location_parts) if location_parts else "未知"
                        
                        return {"success": True, "location": location, "risk": 50, "source": name}
        
        except Exception as e:
            continue
    
    return {"success": False}

# ========== 测试函数 ==========

def test_tcp_connection(ip, port, timeout=10):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        start_time = time.time()
        result = sock.connect_ex((ip, port))
        elapsed = time.time() - start_time
        
        sock.close()
        
        if result == 0:
            latency_ms = elapsed * 1000
            return True, latency_ms
        else:
            return False, None
            
    except socket.timeout:
        return False, None
    except Exception as e:
        return False, None

def test_tcp_with_retry(ip, port, max_retries=3, timeout=10):
    for attempt in range(max_retries + 1):
        success, latency = test_tcp_connection(ip, port, timeout)
        if success:
            return True, latency
        
        if attempt < max_retries:
            time.sleep(0.2)
    
    return False, None

# ========== 数据获取 ==========

def fetch_all_nodes():
    all_nodes = set()
    data_sources = config.get("DATA_SOURCES", [])
    
    enabled_sources = [ds for ds in data_sources if ds.get("enabled", True)]
    
    if not enabled_sources:
        print("⚠️ 没有启用的数据源")
        return []
    
    print(f"\n开始从 {len(enabled_sources)} 个数据源获取IP...")
    print("=" * 70)
    
    for idx, source in enumerate(enabled_sources, 1):
        url = source.get("url", "")
        name = source.get("name", f"数据源{idx}")
        
        if not url:
            continue
        
        print(f"\n[{idx}/{len(enabled_sources)}] {name}")
        
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                print(f"  尝试 {attempt+1}/{max_retries}...", end=" ")
                
                resp = requests.get(url, timeout=(5, 15), allow_redirects=True)
                resp.raise_for_status()
                
                lines = resp.text.strip().split('\n')
                count = 0
                
                for line in lines:
                    result = parse_node_from_line(line)
                    if result:
                        ip, port = result
                        node = f"{ip}:{port}"
                        all_nodes.add(node)
                        count += 1
                
                if count > 0:
                    print(f"✅ 获取 {count} 个节点")
                else:
                    print(f"⚠️ 无有效IP（可能为域名列表或其他格式）")
                break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"❌ 失败，重试...")
                    time.sleep(2)
                else:
                    print(f"❌ 最终失败: {str(e)[:40]}")
    
    print("\n" + "=" * 70)
    print(f"✅ 总计获取 {len(all_nodes)} 个唯一节点\n")
    
    return list(all_nodes)

# ========== 核心检测函数 ==========

def detect_single_node(node):
    match = NODE_PATTERN.match(node)
    if not match:
        return None
    
    ip = match.group(1)
    port = match.group(2)
    
    result = get_ip_location(ip)
    
    if result["success"]:
        new_format = f"{ip}:{port}#{result['location']}#{result['risk']}"
        return new_format
    
    return None

# ========== 主流程 ==========

def main():
    start_time = time.time()
    
    print("=" * 70)
    print("🚀 IP节点检测工具 - v4.0（策略优化版）")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # ====== 步骤1：获取并去重 ======
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()
    
    if not nodes:
        print("❌ 无法获取节点列表")
        return
    
    print(f"✅ 成功获取 {len(nodes)} 个唯一节点\n")
    
    # ====== 步骤2：全量TCP测试 ======
    print("=" * 70)
    print("[步骤2] TCP连接测试（全量检测）")
    print("=" * 70)
    
    tcp_timeout = config.get("TIMEOUT", 10)
    
    # 根据节点数量动态调整并发数和测试数量
    total_nodes = len(nodes)
    
    if total_nodes > 5000:
        test_count = 3000  # 最多测试3000个
        tcp_workers = 80
    elif total_nodes > 1000:
        test_count = min(2000, total_nodes)
        tcp_workers = 60
    else:
        test_count = total_nodes
        tcp_workers = 50
    
    test_nodes = nodes[:test_count]
    
    print(f"\n总节点: {total_nodes} | 测试节点: {test_count} | 并发: {tcp_workers} | 超时: {tcp_timeout}s\n")
    
    tcp_results = []
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=tcp_workers) as executor:
        futures = {}
        for node in test_nodes:
            m = NODE_PATTERN.match(node)
            if m:
                ip = m.group(1)
                port = int(m.group(2))
                future = executor.submit(test_tcp_with_retry, ip, port, max_retries=3, timeout=tcp_timeout)
                futures[future] = node
        
        done = 0
        total = len(futures)
        
        for future in as_completed(futures):
            original_node = futures[future]
            try:
                success, latency = future.result()
                if success and latency is not None:
                    tcp_results.append((original_node, latency))
            except:
                pass
            
            done += 1
            
            if done % 200 == 0 or done == total:
                pct = done * 100 // total
                rate = done / (time.time() - t0) if (time.time() - t0) > 0 else 0
                print(f"  进度: {done}/{total} ({pct}%) | TCP成功: {len(tcp_results)} | {rate:.1f}/s")
    
    t1 = time.time() - t0
    tcp_rate = len(tcp_results) / total * 100 if total > 0 else 0
    
    print(f"\n✅ TCP测试完成！耗时 {t1:.1f}秒")
    print(f"   成功率: {len(tcp_results)}/{total} ({tcp_rate:.1f}%)\n")
    
    if not tcp_results:
        print("⚠️ TCP全部失败，使用原始节点继续...\n")
        candidates = [(node, float('inf')) for node in nodes[:300]]
    else:
        # 按延迟排序，选择前300个最快节点
        tcp_results.sort(key=lambda x: x[1])
        top_n = 300
        candidates = tcp_results[:top_n]
        print(f"✅ 选择前 {len(candidates)} 个最快节点进行地区检测\n")
    
    # ====== 步骤3：地区与纯净度检测 ======
    print("=" * 70)
    print("[步骤3] 地区与纯净度检测（前300优质节点）")
    print("=" * 70)
    
    candidate_nodes = [node for node, _ in candidates]
    
    api_workers = 30
    api_timeout = 15
    
    print(f"\n并发数: {api_workers} | 超时: {api_timeout}秒 | 检测节点: {len(candidate_nodes)}\n")
    
    enriched = []
    t2 = time.time()
    
    with ThreadPoolExecutor(max_workers=api_workers) as executor:
        futures = {executor.submit(detect_single_node, node): node for node in candidate_nodes}
        
        done = 0
        total_api = len(futures)
        
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    enriched.append(result)
            except:
                pass
            
            done += 1
            
            if done % 30 == 0 or done == total_api:
                pct = done * 100 // total_api
                rate = done / (time.time() - t2) if (time.time() - t2) > 0 else 0
                print(f"  进度: {done}/{total_api} ({pct}%) | 成功: {len(enriched)} | {rate:.1f}/s")
    
    t3 = time.time() - t2
    api_rate = len(enriched) / total_api * 100 if total_api > 0 else 0
    
    print(f"\n✅ 地区检测完成！耗时 {t3:.1f}秒")
    print(f"   成功率: {len(enriched)}/{total_api} ({api_rate:.1f}%)\n")
    
    # ====== 步骤4：保存结果到订阅链接 ======
    print("=" * 70)
    print("[步骤4] 保存结果到 ip.txt（订阅文件）")
    print("=" * 70)
    
    output_file = config.get("OUTPUT_FILE", "ip.txt")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(enriched) + '\n')
    
    print(f"\n✅ 已保存 {len(enriched)} 个优质节点到 {output_file}")
    print(f"   格式: ip:端口#地区中文#纯净度\n")
    
    if enriched:
        print("前20个样本:")
        for i, line in enumerate(enriched[:20], 1):
            parts = line.split('#')
            if len(parts) >= 3:
                print(f"  [{i:2d}] {parts[0]:<25s} #{parts[1]} #{parts[2]}")
    
    # ====== 统计信息 ======
    total_time = time.time() - start_time
    
    print(f"\n{'='*70}")
    print("📊 运行统计")
    print("="*70)
    print(f"  数据源总数: {len(nodes)} 个唯一节点")
    print(f"  TCP测试: {tcp_rate:.1f}% ({len(tcp_results)}/{total})")
    print(f"  地区检测: {api_rate:.1f}% ({len(enriched)}/{total_api})")
    print(f"  最终输出: {len(enriched)} 个优质节点")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print(f"  完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

if __name__ == "__main__":
    main()
