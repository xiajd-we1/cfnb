#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - 完整版 v5.0
策略：全量解析 → 去重 → 全量TCP测试 → 全量带宽测试 → 前1000优质 → 输出前500
"""

import re
import json
import time
import socket
import subprocess
import shutil
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

    if not line or line.startswith('#') or line.startswith('线路名称') or line.startswith('ipv4.list'):
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

# ========== HTML解析函数（用于网页数据源）==========

def extract_ips_from_html(html_content):
    """从HTML内容中提取IP地址"""
    import re

    ips_found = set()

    # 匹配IPv4地址的正则
    ip_pattern = re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b')

    # 查找所有IP地址
    all_ips = ip_pattern.findall(html_content)

    for ip in all_ips:
        # 排除明显不是Cloudflare IP的地址段
        first_octet = int(ip.split('.')[0])
        if first_octet in [0, 127, 192, 10, 172]:  # 排除本地/私有IP
            continue

        # 默认端口443
        ips_found.add(f"{ip}:443")

    return list(ips_found)

def fetch_html_source(url, name):
    """从HTML网页数据源提取IP"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        resp = requests.get(url, headers=headers, timeout=(5, 15), allow_redirects=True)
        resp.raise_for_status()

        html_content = resp.text
        ips = extract_ips_from_html(html_content)

        return ips

    except Exception as e:
        print(f"  ❌ HTML解析失败: {str(e)[:50]}")
        return []

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

# ========== TCP测试函数 ==========

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

# ========== 带宽测试函数（参考原项目）==========

def measure_bandwidth_curl(ip, port=443, timeout=8, size_mb=0.5):
    """使用curl测量带宽（参考原项目实现）"""
    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    
    bytes_to_download = int(size_mb * 1024 * 1024)
    bandwidth_url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"
    
    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total}",
        "--resolve", f"speed.cloudflare.com:{port}:{ip}",
        "--connect-timeout", str(min(timeout, 5)),
        "--max-time", str(timeout),
        "--insecure",
        bandwidth_url
    ]

    try:
        result = subprocess.run(
            curl_cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout + 2
        )
        
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                size_bytes = float(parts[0])
                time_total = float(parts[1])
                
                if time_total > 0 and size_bytes > 0:
                    # 计算Mbps： (bytes * 8) / (seconds * 1000000)
                    speed_mbps = (size_bytes * 8) / (time_total * 1000 * 1000)
                    return speed_mbps
    except Exception:
        pass
    
    return 0

def test_bandwidth_with_retry(ip, port, max_retries=2, timeout=8):
    """带重试的带宽测试"""
    for attempt in range(max_retries + 1):
        speed = measure_bandwidth_curl(ip, port, timeout)
        if speed > 0:
            return speed
        
        if attempt < max_retries:
            time.sleep(0.3)
    
    return 0

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
        source_type = source.get("type", "text")  # 默认为文本类型

        if not url:
            continue

        print(f"\n[{idx}/{len(enabled_sources)}] {name}")

        max_retries = 3

        for attempt in range(max_retries):
            try:
                print(f"  尝试 {attempt+1}/{max_retries}...", end=" ")

                # 根据数据源类型选择解析方式
                if source_type == "html":
                    # HTML网页数据源
                    ips = fetch_html_source(url, name)
                    count = len(ips)

                    for node in ips:
                        all_nodes.add(node)

                    if count > 0:
                        print(f"✅ HTML解析获取 {count} 个节点")
                    else:
                        print(f"⚠️ HTML中未找到有效IP")
                else:
                    # 默认文本数据源
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
    import sys
    start_time = time.time()

    print("=" * 70)
    print("🚀 IP节点检测工具 - v5.0（完整版）")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"策略: 全量TCP+带宽 → 前1000优质 → 输出前500\n")

    # ====== 步骤1：获取并去重 ======
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()

    if not nodes:
        print("❌ 无法获取节点列表")
        return

    total_nodes = len(nodes)
    print(f"✅ 成功获取 {total_nodes} 个唯一节点\n")

    # ====== 步骤2：全量TCP连接测试 ======
    print("=" * 70)
    print("[步骤2] TCP连接测试（全量检测）")
    print("=" * 70)

    tcp_timeout = config.get("TIMEOUT", 10)

    # 动态调整并发数
    if total_nodes > 10000:
        tcp_workers = 100
    elif total_nodes > 5000:
        tcp_workers = 80
    elif total_nodes > 1000:
        tcp_workers = 60
    else:
        tcp_workers = 50

    print(f"\n总节点: {total_nodes} | 并发: {tcp_workers} | 超时: {tcp_timeout}s\n")

    tcp_results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=tcp_workers) as executor:
        futures = {}
        for node in nodes:
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

            if done % 500 == 0 or done == total:
                pct = done * 100 // total
                rate = done / (time.time() - t0) if (time.time() - t0) > 0 else 0
                elapsed = time.time() - t0
                print(f"  进度: {done}/{total} ({pct}%) | TCP成功: {len(tcp_results)} | {rate:.1f}/s | 耗时:{elapsed:.1f}s")

    t1 = time.time() - t0
    tcp_rate = len(tcp_results) / total * 100 if total > 0 else 0

    print(f"\n✅ TCP测试完成！耗时 {t1:.1f}秒")
    print(f"   成功率: {len(tcp_results)}/{total} ({tcp_rate:.1f}%)\n")

    if not tcp_results:
        print("⚠️ TCP全部失败，程序退出")
        return

    # ====== 步骤3：全量带宽测试 ======
    print("=" * 70)
    print("[步骤3] 带宽测速（全量检测）")
    print("=" * 70)

    # 检查curl是否可用
    if not shutil.which("curl"):
        print("⚠️ 未检测到curl命令，跳过带宽测试")
        print("   提示: Windows可从 https://curl.se/download.html 安装\n")
        # 直接使用TCP结果排序
        tcp_results.sort(key=lambda x: x[1])
        candidates = tcp_results[:1000]
        print(f"✅ 使用TCP延迟排序，选择前 {len(candidates)} 个节点\n")
    else:
        # 对所有TCP成功的节点进行带宽测试
        bw_timeout = config.get("BANDWIDTH_TIMEOUT", 12)
        bw_size_mb = config.get("BANDWIDTH_SIZE_MB", 0.1)
        
        # 优化：限制带宽测试数量（GitHub Actions环境优化）
        MAX_BW_TEST = 3000  # 最多测试3000个IP的带宽
        bw_test_nodes = tcp_results[:MAX_BW_TEST] if len(tcp_results) > MAX_BW_TEST else tcp_results
        
        if len(bw_test_nodes) > 2000:
            bw_workers = 15  # 降低并发数
        elif len(bw_test_nodes) > 1000:
            bw_workers = 12
        else:
            bw_workers = 10

        print(f"\n待测节点: {len(bw_test_nodes)}/{len(tcp_results)} (限制{MAX_BW_TEST}个) | 并发: {bw_workers} | 超时: {bw_timeout}s | 文件大小: {bw_size_mb}MB\n")

        bw_results = []
        t2 = time.time()

        with ThreadPoolExecutor(max_workers=bw_workers) as executor:
            futures = {}
            for node, latency in bw_test_nodes:  # 使用限制后的列表
                m = NODE_PATTERN.match(node)
                if m:
                    ip = m.group(1)
                    port = int(m.group(2))
                    future = executor.submit(test_bandwidth_with_retry, ip, port, max_retries=2, timeout=bw_timeout)
                    futures[future] = (node, latency)

            done = 0
            total_bw = len(futures)

            for future in as_completed(futures):
                original_data = futures[future]
                original_node, latency = original_data
                try:
                    speed = future.result()
                    if speed > 0:
                        bw_results.append((original_node, latency, speed))
                except:
                    # 带宽测试失败但TCP成功，记录为0带宽
                    bw_results.append((original_node, latency, 0))

                done += 1

                if done % 200 == 0 or done == total_bw:
                    pct = done * 100 // total_bw
                    rate = done / (time.time() - t2) if (time.time() - t2) > 0 else 0
                    valid_bw = sum(1 for _, _, s in bw_results if s > 0)
                    elapsed = time.time() - t2
                    print(f"  进度: {done}/{total_bw} ({pct}%) | 有效带宽: {valid_bw} | {rate:.1f}/s | 耗时:{elapsed:.1f}s")

        t3 = time.time() - t2
        bw_valid = sum(1 for _, _, s in bw_results if s > 0)
        bw_valid_rate = bw_valid / total_bw * 100 if total_bw > 0 else 0

        print(f"\n✅ 带宽测试完成！耗时 {t3:.1f}秒")
        print(f"   有效率: {bw_valid}/{total_bw} ({bw_valid_rate:.1f}%)\n")

        # 智能降级：如果带宽测试成功率太低（<10%），使用TCP排序
        if bw_valid_rate < 10:
            print(f"⚠️ 带宽测试成功率过低({bw_valid_rate:.1f}%)，降级使用TCP延迟排序\n")
            tcp_results.sort(key=lambda x: x[1])
            candidates = [(node, lat, 0) for node, lat in tcp_results[:1000]]
            print(f"✅ 使用TCP延迟排序，选择前 {len(candidates)} 个节点\n")
        else:
            # 综合排序：带宽优先，延迟次之
            # 排序规则：带宽降序，带宽相同时延迟升序
            bw_results.sort(key=lambda x: (-x[2], x[1]))

            # 选择前1000个最优质节点
            top_n = 1000
            candidates = bw_results[:top_n]
            print(f"✅ 综合排序完成！选择前 {len(candidates)} 个优质节点进行地区检测\n")

    # ====== 步骤4：地区与纯净度检测（前1000优质节点）======
    print("=" * 70)
    print("[步骤4] 地区与纯净度检测（前1000优质节点）")
    print("=" * 70)

    candidate_nodes = [node for node, _, _ in candidates]

    api_workers = 30
    api_timeout = 15

    print(f"\n并发数: {api_workers} | 超时: {api_timeout}秒 | 检测节点: {len(candidate_nodes)}\n")

    enriched = []
    t4 = time.time()

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
                rate = done / (time.time() - t4) if (time.time() - t4) > 0 else 0
                print(f"  进度: {done}/{total_api} ({pct}%) | 成功: {len(enriched)} | {rate:.1f}/s")

    t5 = time.time() - t4
    api_rate = len(enriched) / total_api * 100 if total_api > 0 else 0

    print(f"\n✅ 地区检测完成！耗时 {t5:.1f}秒")
    print(f"   成功率: {len(enriched)}/{total_api} ({api_rate:.1f}%)\n")

    # ====== 步骤5：输出前500个到订阅文件（自动补满机制）======
    print("=" * 70)
    print("[步骤5] 保存结果到 ip.txt（输出前500个优质节点）")
    print("=" * 70)

    output_file = config.get("OUTPUT_FILE", "ip.txt")

    TARGET_COUNT = 500  # 目标输出数量

    # 获取已成功检测的节点
    final_output = list(enriched[:TARGET_COUNT])

    # 补满机制：如果不足500个，从candidates中用原始格式补充
    if len(final_output) < TARGET_COUNT:
        shortage = TARGET_COUNT - len(final_output)
        print(f"\n⚠️ 检测成功节点不足{TARGET_COUNT}个（当前: {len(final_output)}），自动补充 {shortage} 个")

        # 从candidates中获取还未加入的节点
        enriched_set = set(final_output)
        supplement_count = 0

        for node, latency, speed in candidates:
            if len(final_output) >= TARGET_COUNT:
                break

            # 使用原始格式：ip:port#未知#50
            m = NODE_PATTERN.match(node)
            if m:
                ip = m.group(1)
                port = m.group(2)
                fallback_format = f"{ip}:{port}#未知#50"

                if fallback_format not in enriched_set:
                    final_output.append(fallback_format)
                    enriched_set.add(fallback_format)
                    supplement_count += 1

        print(f"✅ 成功补充 {supplement_count} 个节点，总计: {len(final_output)} 个")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_output) + '\n')

    print(f"\n✅ 已保存 {len(final_output)} 个优质节点到 {output_file}")
    print(f"   格式: ip:端口#地区中文#纯净度")
    print(f"   ✅ 确保输出达到目标数量: {len(final_output)}/{TARGET_COUNT}\n")

    if final_output:
        print("前20个样本:")
        for i, line in enumerate(final_output[:20], 1):
            parts = line.split('#')
            if len(parts) >= 3:
                print(f"  [{i:2d}] {parts[0]:<25s} #{parts[1]} #{parts[2]}")

    # ====== 统计信息 ======
    total_time = time.time() - start_time

    print(f"\n{'='*70}")
    print("📊 运行统计")
    print("="*70)
    print(f"  数据源总数: {total_nodes} 个唯一节点")
    print(f"  TCP测试: {tcp_rate:.1f}% ({len(tcp_results)}/{total})")
    if 'bw_results' in dir() and bw_results:
        print(f"  带宽测试: {bw_valid_rate:.1f}% ({bw_valid}/{total_bw})")
    print(f"  地区检测: {api_rate:.1f}% ({len(enriched)}/{total_api})")
    print(f"  最终输出: {len(final_output)} 个优质节点（目标: 500个）")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print(f"  完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

if __name__ == "__main__":
    main()
