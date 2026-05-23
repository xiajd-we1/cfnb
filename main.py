#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - v7.0 全量测试版
流程：数据源获取 → 去重 → 全量TCP测试 → 全量带宽测试 → 全量地区检测 → 评分排序 → 前500输出(50香港)
格式：ip:端口#地区名称
"""

import re
import json
import time
import socket
import subprocess
import shutil
import requests
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading

CONFIG_FILE = "config.json"

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 配置文件加载失败: {e}")
        return {}

config = load_config()

NODE_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+):(\d+)')
IP_ONLY_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
CSV_IP_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+),(\d+)')

stats_lock = threading.Lock()
stats = {
    'tcp_tested': 0, 'tcp_success': 0,
    'bw_tested': 0, 'bw_success': 0,
    'loc_tested': 0, 'loc_success': 0,
}

def parse_node_from_line(line):
    line = line.strip()
    if not line or line.startswith('#') or line.startswith('线路名称') or line.startswith('ipv4.list'):
        return None
    if '.' in line and not re.match(r'^\d+\.\d+\.\d+\.\d+', line):
        if not any(c in line for c in ':#,') and not re.search(r'\d', line):
            return None
    match = NODE_PATTERN.match(line)
    if match:
        return (match.group(1), int(match.group(2)))
    if ':' in line and '#' in line:
        parts = line.split('#')
        ip_port = parts[0].strip()
        match = NODE_PATTERN.match(ip_port)
        if match:
            return (match.group(1), int(match.group(2)))
    match = CSV_IP_PATTERN.match(line)
    if match:
        try:
            port = int(match.group(2))
            if 1 <= port <= 65535:
                return (match.group(1), port)
        except:
            pass
    parts = line.split('#')
    ip_part = parts[0].strip()
    ip_match = IP_ONLY_PATTERN.match(ip_part)
    if ip_match:
        return (ip_match.group(1), 443)
    csv_parts = line.split(',')
    if len(csv_parts) >= 2:
        for col in csv_parts[1:3]:
            potential_ip = col.strip()
            ip_match = IP_ONLY_PATTERN.match(potential_ip)
            if ip_match:
                return (ip_match.group(1), 443)
    return None

def extract_ips_from_html(html_content):
    ips_found = set()
    ip_pattern = re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b')
    all_ips = ip_pattern.findall(html_content)
    for ip in all_ips:
        first_octet = int(ip.split('.')[0])
        if first_octet in [0, 127, 192, 10, 172]:
            continue
        ips_found.add(f"{ip}:443")
    return list(ips_found)

def fetch_html_source(url, name):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=(5, 15), allow_redirects=True)
        resp.raise_for_status()
        return extract_ips_from_html(resp.text)
    except Exception as e:
        print(f"  ❌ HTML解析失败: {str(e)[:50]}")
        return []

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
        source_type = source.get("type", "text")
        if not url:
            continue
        print(f"\n[{idx}/{len(enabled_sources)}] {name}")
        for attempt in range(3):
            try:
                print(f"  尝试 {attempt+1}/3...", end=" ")
                if source_type == "html":
                    ips = fetch_html_source(url, name)
                    count = len(ips)
                    for node in ips:
                        all_nodes.add(node)
                    if count > 0:
                        print(f"✅ HTML解析获取 {count} 个节点")
                    else:
                        print(f"⚠️ HTML中未找到有效IP")
                else:
                    resp = requests.get(url, timeout=(5, 15), allow_redirects=True)
                    resp.raise_for_status()
                    lines = resp.text.strip().split('\n')
                    count = 0
                    for line in lines:
                        result = parse_node_from_line(line)
                        if result:
                            ip, port = result
                            all_nodes.add(f"{ip}:{port}")
                            count += 1
                    if count > 0:
                        print(f"✅ 获取 {count} 个节点")
                    else:
                        print(f"⚠️ 无有效IP")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"❌ 失败，重试...")
                    time.sleep(2)
                else:
                    print(f"❌ 最终失败: {str(e)[:40]}")

    print("\n" + "=" * 70)
    print(f"✅ 总计获取 {len(all_nodes)} 个唯一节点\n")
    return list(all_nodes)

# ========== TCP测试 ==========

def test_tcp_connection(ip, port, timeout=8):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start_time = time.time()
        result = sock.connect_ex((ip, port))
        elapsed = time.time() - start_time
        sock.close()
        if result == 0:
            return True, elapsed * 1000
        return False, None
    except:
        return False, None

def test_tcp_with_retry(ip, port, max_retries=2, timeout=8):
    for attempt in range(max_retries + 1):
        success, latency = test_tcp_connection(ip, port, timeout)
        if success:
            return True, latency
        if attempt < max_retries:
            time.sleep(0.1)
    return False, None

# ========== 带宽测试（参考原项目列表形式）==========

def measure_bandwidth(ip, port=443, timeout=10, size_mb=0.5):
    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    bytes_to_download = int(size_mb * 1024 * 1024)
    bandwidth_url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"

    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total}",
        "--resolve", f"speed.cloudflare.com:{port}:{ip}",
        "--connect-timeout", "5",
        "--max-time", str(timeout),
        "--insecure",
        bandwidth_url
    ]

    try:
        result = subprocess.run(
            curl_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                size_bytes = float(parts[0])
                time_total = float(parts[1])
                if time_total > 0 and size_bytes > 0:
                    speed_mbps = (size_bytes * 8) / (time_total * 1000 * 1000)
                    return speed_mbps

        if not hasattr(measure_bandwidth, '_debug_logged'):
            measure_bandwidth._debug_logged = True
            print(f"\n   [DEBUG带宽] IP:{ip}:{port} rc={result.returncode} stdout='{result.stdout[:80] if result.stdout else 'empty'}' stderr='{result.stderr[:150] if result.stderr else 'empty'}'")

    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        if not hasattr(measure_bandwidth, '_exc_logged'):
            measure_bandwidth._exc_logged = True
            print(f"\n   [DEBUG带宽异常] {str(e)[:80]}")
    return 0

# ========== 地区检测 ==========

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_ip_location(ip):
    is_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'

    if is_actions:
        apis = [
            ("ip-api", f"http://ip-api.com/json/{ip}?lang=zh-CN"),
            ("ip.sb", f"https://api.ip.sb/geoip/{ip}"),
            ("iping.cc", f"https://api.iping.cc/v1/query?ip={ip}&language=zh"),
        ]
        api_timeout = 5
    else:
        apis = [
            ("iping.cc", f"https://api.iping.cc/v1/query?ip={ip}&language=zh"),
            ("ip-api", f"http://ip-api.com/json/{ip}?lang=zh-CN"),
            ("ip.sb", f"https://api.ip.sb/geoip/{ip}"),
        ]
        api_timeout = 10

    for name, url in apis:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            if name == "iping.cc":
                resp = requests.get(url, headers=headers, timeout=api_timeout, verify=False)
            else:
                resp = requests.get(url, headers=headers, timeout=api_timeout)
            if resp.status_code != 200:
                continue
            data = resp.json()

            if name == "iping.cc":
                if data.get("code") == 200 and data.get("data"):
                    info = data["data"]
                    country = info.get("country", "") or ""
                    country_code = info.get("country_code", "") or info.get("countryCode", "") or ""
                    region = info.get("region", "") or ""
                    city = info.get("city", "") or ""
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else "未知"
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "ip-api":
                if data.get("status") == "success":
                    country = data.get("country", "") or ""
                    country_code = data.get("countryCode", "") or ""
                    region = data.get("regionName", "") or ""
                    city = data.get("city", "") or ""
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else "未知"
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "ip.sb":
                country = data.get("country_name", "") or ""
                country_code = data.get("country_code", "") or ""
                region = data.get("region", "") or ""
                city = data.get("city", "") or ""
                parts = [p for p in [country, region, city] if p]
                location = " ".join(parts) if parts else "未知"
                return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

        except:
            continue
    return {"success": False}

# ========== 主流程 ==========

def main():
    start_time = time.time()

    print("=" * 70)
    print("🚀 IP节点检测工具 - v7.0（全量测试版）")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"流程: 数据源→去重→全量TCP→全量带宽→全量地区→评分排序→前500输出\n")

    # ====== 步骤1：获取并去重 ======
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()
    if not nodes:
        print("❌ 无法获取节点列表")
        return

    total_nodes = len(nodes)
    print(f"✅ 成功获取 {total_nodes} 个唯一节点\n")

    # ====== 步骤2：全量TCP测试 ======
    print("=" * 70)
    print("[步骤2] 全量TCP连接测试")
    print("=" * 70)

    is_github_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'

    tcp_timeout = config.get("TIMEOUT", 5 if is_github_actions else 8)
    tcp_workers = min(300 if is_github_actions else 200, max(50, total_nodes // 50))
    tcp_retries = 1 if is_github_actions else 2
    print(f"\n总节点: {total_nodes} | 并发: {tcp_workers} | 超时: {tcp_timeout}s | 重试: {tcp_retries} | 环境: {'GitHub Actions' if is_github_actions else '本地'}\n")

    tcp_results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=tcp_workers) as executor:
        futures = {}
        for node in nodes:
            m = NODE_PATTERN.match(node)
            if m:
                ip = m.group(1)
                port = int(m.group(2))
                futures[executor.submit(test_tcp_with_retry, ip, port, max_retries=tcp_retries, timeout=tcp_timeout)] = node

        done = 0
        total = len(futures)
        for future in as_completed(futures):
            original_node = futures[future]
            try:
                success, latency = future.result()
                if success and latency is not None:
                    tcp_results.append((original_node, latency))
                    with stats_lock:
                        stats['tcp_success'] += 1
            except:
                pass
            done += 1
            with stats_lock:
                stats['tcp_tested'] = done
            if done % 500 == 0 or done == total:
                pct = done * 100 // total
                rate = done / (time.time() - t0) if (time.time() - t0) > 0 else 0
                elapsed = time.time() - t0
                print(f"  进度: {done}/{total} ({pct}%) | TCP成功: {len(tcp_results)} | {rate:.1f}/s | 耗时:{elapsed:.1f}s")

    t1 = time.time() - t0
    tcp_rate = len(tcp_results) / total * 100 if total > 0 else 0
    print(f"\n✅ TCP测试完成！耗时 {t1:.1f}秒 | 成功率: {len(tcp_results)}/{total} ({tcp_rate:.1f}%)\n")

    if not tcp_results:
        print("❌ TCP全部失败，程序退出")
        return

    # ====== 步骤3：全量带宽测试 ======
    print("=" * 70)
    print("[步骤3] 全量带宽测速")
    print("=" * 70)

    bw_results = []

    if not shutil.which("curl"):
        print("⚠️ 未检测到curl，跳过带宽测试，使用TCP延迟排序")
        tcp_results.sort(key=lambda x: x[1])
        bw_results = [(node, lat, 0) for node, lat in tcp_results]
    else:
        bw_timeout = config.get("BANDWIDTH_TIMEOUT", 8 if is_github_actions else 10)
        bw_size_mb = config.get("BANDWIDTH_SIZE_MB", 0.5)
        bw_workers = min(50 if is_github_actions else 30, max(10, len(tcp_results) // 100))

        print(f"\n待测节点: {len(tcp_results)} | 并发: {bw_workers} | 超时: {bw_timeout}s | 文件大小: {bw_size_mb}MB\n")

        t2 = time.time()

        with ThreadPoolExecutor(max_workers=bw_workers) as executor:
            futures = {}
            for node, latency in tcp_results:
                m = NODE_PATTERN.match(node)
                if m:
                    ip = m.group(1)
                    port = int(m.group(2))
                    futures[executor.submit(measure_bandwidth, ip, port, timeout=bw_timeout, size_mb=bw_size_mb)] = (node, latency)

            done = 0
            total_bw = len(futures)
            for future in as_completed(futures):
                original_node, latency = futures[future]
                try:
                    speed = future.result()
                    bw_results.append((original_node, latency, speed))
                    if speed > 0:
                        with stats_lock:
                            stats['bw_success'] += 1
                except:
                    bw_results.append((original_node, latency, 0))
                done += 1
                with stats_lock:
                    stats['bw_tested'] = done
                if done % 200 == 0 or done == total_bw:
                    pct = done * 100 // total_bw
                    rate = done / (time.time() - t2) if (time.time() - t2) > 0 else 0
                    valid_bw = sum(1 for _, _, s in bw_results if s > 0)
                    elapsed = time.time() - t2
                    print(f"  进度: {done}/{total_bw} ({pct}%) | 有效带宽: {valid_bw} | {rate:.1f}/s | 耗时:{elapsed:.1f}s")

        t3 = time.time() - t2
        valid_bw = sum(1 for _, _, s in bw_results if s > 0)
        print(f"\n✅ 带宽测试完成！耗时 {t3:.1f}秒 | 有效: {valid_bw}/{len(bw_results)}\n")

    # ====== 步骤4：全量地区检测 ======
    print("=" * 70)
    print("[步骤4] 全量地区检测")
    print("=" * 70)

    loc_workers = min(150 if is_github_actions else 100, max(30, len(bw_results) // 50))
    print(f"\n待测节点: {len(bw_results)} | 并发: {loc_workers}\n")

    final_data = []
    t4 = time.time()

    with ThreadPoolExecutor(max_workers=loc_workers) as executor:
        futures = {}
        for node, latency, speed in bw_results:
            m = NODE_PATTERN.match(node)
            if m:
                ip = m.group(1)
                futures[executor.submit(get_ip_location, ip)] = (node, latency, speed)

        done = 0
        total_loc = len(futures)
        for future in as_completed(futures):
            node, latency, speed = futures[future]
            try:
                loc_result = future.result()
                location = "未知"
                country_code = "XX"
                if loc_result.get("success"):
                    location = loc_result.get("location", "未知")
                    country_code = loc_result.get("country_code", "XX")
                    with stats_lock:
                        stats['loc_success'] += 1
                final_data.append({
                    'node': node,
                    'latency': latency,
                    'speed': speed,
                    'location': location,
                    'country_code': country_code,
                })
            except:
                final_data.append({
                    'node': node,
                    'latency': latency,
                    'speed': speed,
                    'location': '未知',
                    'country_code': 'XX',
                })
            done += 1
            with stats_lock:
                stats['loc_tested'] = done
            if done % 200 == 0 or done == total_loc:
                pct = done * 100 // total_loc
                rate = done / (time.time() - t4) if (time.time() - t4) > 0 else 0
                elapsed = time.time() - t4
                print(f"  进度: {done}/{total_loc} ({pct}%) | 成功: {stats['loc_success']} | {rate:.1f}/s | 耗时:{elapsed:.1f}s")

    t5 = time.time() - t4
    print(f"\n✅ 地区检测完成！耗时 {t5:.1f}秒 | 成功: {stats['loc_success']}/{len(final_data)}\n")

    # ====== 步骤5：评分排序 + 输出前500 ======
    print("=" * 70)
    print("[步骤5] 评分排序 & 输出前500个优质IP")
    print("=" * 70)

    TARGET = 500
    HK_PRIORITY = 50

    for item in final_data:
        lat = item['latency']
        spd = item['speed']
        lat_score = max(0, 100 - lat / 10) if lat > 0 else 0
        spd_score = min(100, spd * 2) if spd > 0 else 0
        item['score'] = lat_score * 0.4 + spd_score * 0.6

    final_data.sort(key=lambda x: -x['score'])

    hk_items = [x for x in final_data if any(k in x['location'] for k in ['香港', 'HK', 'Hong Kong'])]
    other_items = [x for x in final_data if not any(k in x['location'] for k in ['香港', 'HK', 'Hong Kong'])]

    print(f"\n🇭🇰 香港节点: {len(hk_items)} | 其他地区: {len(other_items)}")

    output = []
    output.extend(hk_items[:HK_PRIORITY])
    for item in other_items:
        if len(output) >= TARGET:
            break
        if item['node'] not in [x['node'] for x in output]:
            output.append(item)
    for item in hk_items[HK_PRIORITY:]:
        if len(output) >= TARGET:
            break
        if item['node'] not in [x['node'] for x in output]:
            output.append(item)

    # 格式化输出
    output_lines = []
    for item in output:
        m = NODE_PATTERN.match(item['node'])
        if m:
            ip = m.group(1)
            port = m.group(2)
            output_lines.append(f"{ip}:{port}#{item['location']}")

    # 补满机制
    if len(output_lines) < TARGET:
        shortage = TARGET - len(output_lines)
        print(f"\n⚠️ 不足{TARGET}个（当前: {len(output_lines)}），补充 {shortage} 个")
        existing = set(output_lines)
        for item in final_data[len(output):]:
            if len(output_lines) >= TARGET:
                break
            m = NODE_PATTERN.match(item['node'])
            if m:
                line = f"{m.group(1)}:{m.group(2)}#{item['location']}"
                if line not in existing:
                    output_lines.append(line)
                    existing.add(line)

    output_file = config.get("OUTPUT_FILE", "ip.txt")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines) + '\n')

    print(f"\n✅ 已保存 {len(output_lines)} 个节点到 {output_file}")
    print(f"   格式: ip:端口#地区名称")
    print(f"   🇭🇰 香港优先: {min(HK_PRIORITY, len(hk_items))} 个")

    if output_lines:
        print(f"\n前20个样本:")
        for i, line in enumerate(output_lines[:20], 1):
            print(f"  [{i:2d}] {line}")

    total_time = time.time() - start_time
    print(f"\n{'='*70}")
    print("📊 运行统计")
    print("="*70)
    print(f"  数据源: {total_nodes} 个唯一节点")
    print(f"  TCP: {stats['tcp_success']}/{stats['tcp_tested']} ({stats['tcp_success']/max(stats['tcp_tested'],1)*100:.1f}%)")
    print(f"  带宽: {stats['bw_success']}/{stats['bw_tested']} ({stats['bw_success']/max(stats['bw_tested'],1)*100:.1f}%)")
    print(f"  地区: {stats['loc_success']}/{stats['loc_tested']} ({stats['loc_success']/max(stats['loc_tested'],1)*100:.1f}%)")
    print(f"  最终输出: {len(output_lines)} 个节点")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print("="*70)

if __name__ == "__main__":
    main()
