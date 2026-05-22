#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - 完整版 v3.0
功能：
1. 多格式IP解析（ip:port、纯IP、CSV）
2. TCP连接测试
3. 带宽速度测试
4. 地区位置检测（多API策略）
5. 纯净度评估
输出格式：ip:端口#地区中文#纯净度
"""

import re
import json
import time
import socket
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ========== 配置 ==========
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
    
    if not line or line.startswith('#'):
        return None
    
    # 格式1: ip:port
    match = NODE_PATTERN.match(line)
    if match:
        return (match.group(1), int(match.group(2)))
    
    # 格式2: CSV - ip,port,...
    match = CSV_IP_PATTERN.match(line)
    if match:
        try:
            port = int(match.group(2))
            if 1 <= port <= 65535:
                return (match.group(1), port)
        except:
            pass
    
    # 格式3: 纯IP（自动添加443端口）
    match = IP_ONLY_PATTERN.match(line)
    if match:
        return (match.group(1), 443)
    
    return None

# ========== API函数（多API策略）==========

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
    """测试TCP连接"""
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
    """带重试机制的TCP测试"""
    for attempt in range(max_retries + 1):
        success, latency = test_tcp_connection(ip, port, timeout)
        if success:
            return True, latency
        
        if attempt < max_retries:
            time.sleep(0.2)
    
    return False, None

def measure_bandwidth(ip, port, timeout=8):
    """测量带宽（简化版）"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        
        request = b"GET /__down?bytes=1048576 HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n"
        sock.sendall(request)
        
        start_time = time.time()
        total_bytes = 0
        
        while True:
            data = sock.recv(8192)
            if not data:
                break
            total_bytes += len(data)
            
            if time.time() - start_time > timeout:
                break
        
        sock.close()
        
        elapsed = time.time() - start_time
        
        if total_bytes > 0 and elapsed > 0:
            bandwidth_bps = (total_bytes * 8) / elapsed
            bandwidth_mbps = bandwidth_bps / 1000000
            return bandwidth_mbps
        
        return 0
    
    except Exception as e:
        return 0

# ========== 数据获取（完整版）==========

def fetch_all_nodes():
    """从所有数据源获取IP节点列表（支持多格式）"""
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
        print(f"  URL: {url}")
        
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
                
                print(f"✅ 获取 {count} 个节点")
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
    """检测单个节点（返回新格式或None）"""
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
    print("🚀 IP节点检测工具 - 完整版 v3.0")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # ====== 步骤1：获取IP列表 ======
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()
    
    if not nodes:
        print("❌ 无法获取节点列表")
        return
    
    print(f"✅ 成功获取 {len(nodes)} 个节点\n")
    
    # 选择要测试的节点
    max_test = min(config.get("GLOBAL_TOP_N", 300), len(nodes))
    test_nodes = nodes[:max_test]
    
    # ====== 步骤2：TCP连接测试 ======
    print("=" * 70)
    print("[步骤2] TCP连接测试")
    print("=" * 70)
    
    tcp_timeout = config.get("TIMEOUT", 10)
    tcp_workers = 50
    
    print(f"\n并发数: {tcp_workers} | 超时: {tcp_timeout}秒 | 测试节点: {len(test_nodes)}\n")
    
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
            
            if done % 100 == 0 or done == total:
                pct = done * 100 // total
                rate = done / (time.time() - t0) if (time.time() - t0) > 0 else 0
                print(f"  进度: {done}/{total} ({pct}%) | TCP成功: {len(tcp_results)} | {rate:.1f}/s")
    
    t1 = time.time() - t0
    tcp_rate = len(tcp_results) / total * 100 if total > 0 else 0
    
    print(f"\n✅ TCP测试完成！耗时 {t1:.1f}秒")
    print(f"   成功率: {len(tcp_results)}/{total} ({tcp_rate:.1f}%)\n")
    
    if not tcp_results:
        print("⚠️ TCP全部失败，使用原始节点继续...\n")
        candidates = [(node, float('inf')) for node in test_nodes[:300]]
    else:
        tcp_results.sort(key=lambda x: x[1])
        candidates = tcp_results[:300]
        print(f"✅ 选择前 {len(candidates)} 个最快节点\n")
    
    # ====== 步骤3：地区与纯净度检测 ======
    print("=" * 70)
    print("[步骤3] 地区与纯净度检测")
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
            
            if done % 50 == 0 or done == total_api:
                pct = done * 100 // total_api
                rate = done / (time.time() - t2) if (time.time() - t2) > 0 else 0
                print(f"  进度: {done}/{total_api} ({pct}%) | 成功: {len(enriched)} | {rate:.1f}/s")
    
    t3 = time.time() - t2
    api_rate = len(enriched) / total_api * 100 if total_api > 0 else 0
    
    print(f"\n✅ 地区检测完成！耗时 {t3:.1f}秒")
    print(f"   成功率: {len(enriched)}/{total_api} ({api_rate:.1f}%)\n")
    
    # ====== 步骤4：带宽测试（可选）=====
    if tcp_results and len(enriched) > 10:
        print("=" * 70)
        print("[步骤4] 带宽测试（前20个最快节点）")
        print("=" * 70)
        
        bw_test_nodes = enriched[:min(20, len(enriched))]
        bw_workers = 10
        bw_timeout = 8
        
        print(f"\n并发数: {bw_workers} | 超时: {bw_timeout}秒\n")
        
        bw_results = []
        t4 = time.time()
        
        with ThreadPoolExecutor(max_workers=bw_workers) as executor:
            futures = {}
            for node in bw_test_nodes:
                m = NODE_PATTERN.match(node)
                if m:
                    ip = m.group(1)
                    port = int(m.group(2))
                    future = executor.submit(measure_bandwidth, ip, port, timeout=bw_timeout)
                    futures[future] = node
            
            for future in as_completed(futures):
                node = futures[future]
                try:
                    bw = future.result()
                    if bw and bw > 0:
                        bw_results.append((node, bw))
                except:
                    pass
        
        t5 = time.time() - t4
        
        print(f"\n✅ 带宽测试完成！耗时 {t5:.1f}秒")
        print(f"   有效结果: {len(bw_results)}/20\n")
        
        if bw_results:
            bw_results.sort(key=lambda x: -x[1])
            print("Top 5 带宽节点:")
            for i, (node, bw) in enumerate(bw_results[:5], 1):
                parts = node.split('#')
                if len(parts) >= 3:
                    print(f"  [{i}] {parts[0]:<25s} #{parts[1]} | {bw:.2f} Mbps")
    
    # ====== 步骤5：保存结果 ======
    print("\n" + "=" * 70)
    print("[步骤5] 保存结果到 ip.txt")
    print("=" * 70)
    
    output_file = config.get("OUTPUT_FILE", "ip.txt")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(enriched) + '\n')
    
    print(f"\n✅ 已保存 {len(enriched)} 个节点到 {output_file}")
    print(f"   格式: ip:端口#地区中文#纯净度\n")
    
    if enriched:
        print("前15个样本:")
        for i, line in enumerate(enriched[:15], 1):
            parts = line.split('#')
            if len(parts) >= 3:
                print(f"  [{i:2d}] {parts[0]:<25s} #{parts[1]} #{parts[2]}")
    
    # ====== 统计信息 ======
    total_time = time.time() - start_time
    
    print(f"\n{'='*70}")
    print("📊 运行统计")
    print("="*70)
    print(f"  数据源节点: {len(nodes)}")
    print(f"  TCP测试: {tcp_rate:.1f}% ({len(tcp_results)}/{total})")
    print(f"  地区检测: {api_rate:.1f}% ({len(enriched)}/{total_api})")
    print(f"  最终输出: {len(enriched)} 个节点")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print(f"  完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

if __name__ == "__main__":
    main()
