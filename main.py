#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - v10.0（三阶段极速版）
核心优化：
1. 阶段1：asyncio极速初筛延迟（2000并发，1秒超时，3次100%成功）
2. 阶段2：仅对通过阶段1的IP进行测速+地区检测
3. 阶段3：保存所有通过测试的IP（不限制数量）
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
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_FILE = "config.json"

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 配置文件加载失败: {e}")
        return {}

config = load_config()

NODE_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+):(\d+)')
IP_ONLY_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
CSV_IP_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+),(\d+)')

stats = {
    'stage1_tested': 0, 'stage1_passed': 0,
    'stage2_bw_tested': 0, 'stage2_bw_passed': 0,
    'stage2_loc_tested': 0, 'stage2_loc_success': 0,
}

# ==================== 数据源获取 ====================

def parse_node_from_line(line):
    """解析IP行，同时提取地区标注（#后的内容）"""
    line = line.strip()
    if not line or line.startswith('#') or line.startswith('线路名称') or line.startswith('ipv4.list'):
        return None
    if '.' in line and not re.match(r'^\d+\.\d+\.\d+\.\d+', line):
        if not any(c in line for c in ':#,') and not re.search(r'\d', line):
            return None
    
    # 提取地区标注（#后的内容）
    region_tag = None
    if '#' in line:
        tag_part = line.split('#', 1)[1].strip()
        if tag_part and len(tag_part) <= 30:
            region_tag = tag_part
    
    match = NODE_PATTERN.match(line)
    if match:
        return (match.group(1), int(match.group(2)), region_tag)
    if ':' in line and '#' in line:
        parts = line.split('#')
        ip_port = parts[0].strip()
        match = NODE_PATTERN.match(ip_port)
        if match:
            return (match.group(1), int(match.group(2)), region_tag)
    match = CSV_IP_PATTERN.match(line)
    if match:
        try:
            port = int(match.group(2))
            if 1 <= port <= 65535:
                return (match.group(1), port, region_tag)
        except:
            pass
    parts = line.split('#')
    ip_part = parts[0].strip()
    ip_match = IP_ONLY_PATTERN.match(ip_part)
    if ip_match:
        return (ip_match.group(1), 443, region_tag)
    csv_parts = line.split(',')
    if len(csv_parts) >= 2:
        for col in csv_parts[1:3]:
            potential_ip = col.strip()
            ip_match = IP_ONLY_PATTERN.match(potential_ip)
            if ip_match:
                return (ip_match.group(1), 443, region_tag)
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
        print(f"  [FAIL] HTML解析失败: {str(e)[:50]}")
        return []

def fetch_all_nodes():
    all_nodes = set()
    ip_region_tags = {}  # ip -> 地区标注（来自数据源的#标注）
    total_raw = 0  # 去重前的总数
    data_sources = config.get("DATA_SOURCES", [])
    enabled_sources = [ds for ds in data_sources if ds.get("enabled", True)]
    if not enabled_sources:
        print("[WARN] 没有启用的数据源")
        return [], {}

    print(f"\n从 {len(enabled_sources)} 个数据源获取IP...")
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
                        total_raw += 1
                    if count > 0:
                        print(f"[OK] HTML解析获取 {count} 个节点")
                    else:
                        print("[WARN] HTML中未找到有效IP")
                else:
                    resp = requests.get(url, timeout=(5, 15), allow_redirects=True)
                    resp.raise_for_status()
                    lines = resp.text.strip().split('\n')
                    count = 0
                    tagged_count = 0
                    for line in lines:
                        result = parse_node_from_line(line)
                        if result:
                            ip, port = result[0], result[1]
                            region_tag = result[2] if len(result) > 2 else None
                            all_nodes.add(f"{ip}:{port}")
                            # 保存地区标注
                            if region_tag:
                                ip_region_tags[ip] = region_tag
                                tagged_count += 1
                            count += 1
                            total_raw += 1
                    tag_info = f" (含{tagged_count}个带地区标注)" if tagged_count > 0 else ""
                    if count > 0:
                        print(f"[OK] 获取 {count} 个节点{tag_info}")
                    else:
                        print("[WARN] 无有效IP")
                break
            except Exception as e:
                if attempt < 2:
                    print("[FAIL] 失败，重试...")
                    time.sleep(2)
                else:
                    print(f"[FAIL] 最终失败: {str(e)[:40]}")

    print("\n" + "=" * 70)
    print(f"[OK] 数据源获取完成: 原始 {total_raw} 个 → 去重后 {len(all_nodes)} 个唯一节点 (去除 {total_raw - len(all_nodes)} 个重复)")
    print(f"     其中 {len(ip_region_tags)} 个IP已有地区标注（无需API查询）\n")
    return list(all_nodes), ip_region_tags


# ==================== 阶段1：极速初筛延迟 ====================

async def tcp_probe_once(ip, port, timeout=2.0):
    """异步TCP握手，返回(成功, 延迟ms)"""
    try:
        start = time.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        elapsed_ms = (time.time() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return True, elapsed_ms
    except:
        return False, None

async def probe_ip_serial(ip, port, sem, probe_count=3, timeout=2.0, max_latency=300, total_timeout=6.0):
    """对单个IP串行探测3次，带信号量控制总并发，总超时6秒"""
    async with sem:
        start_time = time.time()
        latencies = []
        for i in range(probe_count):
            # 检查总超时
            if time.time() - start_time > total_timeout:
                break
            success, latency = await tcp_probe_once(ip, port, timeout)
            if success and latency is not None and latency <= max_latency:
                latencies.append(latency)
        return ip, port, latencies

async def stage1_batch_probe(ip_port_list, concurrency=500, timeout=2.0, max_latency=300, probe_count=3):
    """阶段1：每个IP串行3次探测，不同IP之间并发执行"""
    sem = asyncio.Semaphore(concurrency)
    
    # 为每个IP创建一个串行探测任务
    tasks = []
    ip_port_map = {}  # ip -> port
    for node in ip_port_list:
        m = NODE_PATTERN.match(node)
        if m:
            ip = m.group(1)
            port = int(m.group(2))
            ip_port_map[ip] = port
            tasks.append(probe_ip_serial(ip, port, sem, probe_count, timeout, max_latency, total_timeout=6.0))
    
    total_ips = len(ip_port_map)
    total_tasks = len(tasks)
    
    print(f"  总IP: {total_ips} | 并发: {concurrency} | 每IP串行{probe_count}次 | 单次超时: {timeout}s | 总超时: 6s")
    print(f"  策略: 不同IP并发执行，同一IP串行3次探测（避免互相干扰）\n")
    
    # 执行所有探测
    ip_results = {}  # ip -> [latency1, latency2, latency3, ...]
    done_count = 0
    t0 = time.time()
    
    for coro in asyncio.as_completed(tasks):
        try:
            ip, port, latencies = await coro
            if latencies:
                ip_results[ip] = latencies
        except:
            pass
        
        done_count += 1
        if done_count % 2000 == 0 or done_count == total_tasks:
            elapsed = time.time() - t0
            pct = done_count * 100 // total_tasks
            rate = done_count / elapsed if elapsed > 0 else 0
            detected = len(ip_results)
            print(f"  探测进度: {done_count}/{total_tasks} ({pct}%) | 可达: {detected} | {rate:.0f}/s | {elapsed:.1f}s")
    
    elapsed = time.time() - t0
    
    # 按成功次数分类
    passed_3 = {}    # 3次全成功
    passed_2 = {}    # 2次成功
    count_1 = 0      # 1次成功
    count_0 = 0      # 0次成功
    
    for ip, latencies in ip_results.items():
        port = ip_port_map[ip]
        success_count = len(latencies)
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        
        if success_count >= 3:
            passed_3[ip] = {'port': port, 'latency': avg_latency, 'probes': success_count}
        elif success_count >= 2:
            passed_2[ip] = {'port': port, 'latency': avg_latency, 'probes': success_count}
        elif success_count >= 1:
            count_1 += 1
    
    # 统计0次成功的（从未出现在ip_results中的IP）
    count_0 = total_ips - len(ip_results)
    
    # 输出丢包分布统计
    print(f"\n  ─── 阶段1丢包分布统计 ───")
    print(f"  3次全成功: {len(passed_3):>6} 个 ({len(passed_3)/max(total_ips,1)*100:.1f}%)")
    print(f"  2次成功:   {len(passed_2):>6} 个 ({len(passed_2)/max(total_ips,1)*100:.1f}%)")
    print(f"  1次成功:   {count_1:>6} 个 ({count_1/max(total_ips,1)*100:.1f}%)")
    print(f"  0次成功:   {count_0:>6} 个 ({count_0/max(total_ips,1)*100:.1f}%)")
    
    # 合并：2次以上成功算通过
    final_results = {}
    final_results.update(passed_3)
    final_results.update(passed_2)
    
    total_passed = len(final_results)
    print(f"\n  通过条件: 2次以上成功 + 延迟<{max_latency}ms")
    print(f"  最终通过: {total_passed} 个 ({total_passed/max(total_ips,1)*100:.1f}%)")
    print(f"  耗时: {elapsed:.1f}s")
    
    return final_results

def run_stage1(nodes):
    """阶段1入口：极速初筛延迟"""
    print("=" * 70)
    print("[阶段1] 极速初筛延迟（3次TCP探测，统计丢包分布）")
    print("=" * 70)

    total = len(nodes)
    print(f"\n总IP数: {total} | 并发: 500 | 超时: 2.0s | 最大延迟: 300ms | 每IP串行3次 | 总超时: 6s")
    print(f"通过条件: 2次以上成功 + 延迟<300ms\n")

    t0 = time.time()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                results = pool.submit(lambda: asyncio.run(stage1_batch_probe(nodes))).result()
        else:
            results = loop.run_until_complete(stage1_batch_probe(nodes))
    except RuntimeError:
        results = asyncio.run(stage1_batch_probe(nodes))

    elapsed = time.time() - t0

    stats['stage1_tested'] = total
    stats['stage1_passed'] = len(results)

    print(f"\n[OK] 阶段1完成! 耗时{elapsed:.1f}s | 通过: {len(results)}/{total} ({len(results)/max(total,1)*100:.1f}%)\n")
    return results


# ==================== 阶段2：测速 + 地区检测 ====================

def measure_bandwidth(ip, port=443, timeout=8, size_kb=100):
    """下载小文件测速（默认100KB）"""
    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    bytes_to_download = int(size_kb * 1024)
    bandwidth_url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"

    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total} %{http_code}",
        "--resolve", f"speed.cloudflare.com:{port}:{ip}",
        "--connect-timeout", "3",
        "--max-time", str(timeout),
        "--insecure",
        bandwidth_url
    ]

    try:
        result = subprocess.run(
            curl_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 3
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                size_bytes = float(parts[0])
                time_total = float(parts[1])
                if time_total > 0 and size_bytes > 0:
                    speed_mbps = (size_bytes * 8) / (time_total * 1000 * 1000)
                    return speed_mbps
    except subprocess.TimeoutExpired:
        pass
    except:
        pass
    return 0


# CF IP段快速推断
CF_IP_REGIONS = {
    (104, 16, 31): "美国 Cloudflare",
    (104, 24, 27): "美国 Cloudflare",
    (172, 64, 71): "美国 Cloudflare",
    (162, 158, 159): "美国 Cloudflare",
    (108, 162, 163): "美国 Cloudflare",
    (188, 114, 115): "欧洲 Cloudflare",
    (190, 80, 93): "美国 Cloudflare",
    (198, 41, 41): "美国 Cloudflare",
    (197, 234, 234): "欧洲 Cloudflare",
    (209, 242, 242): "中国香港 Cloudflare",
    (206, 286, 286): "新加坡 Cloudflare",
}

def get_cf_region_fast(ip):
    """CF IP段快速推断地区（0ms，不调API）"""
    try:
        octets = [int(x) for x in ip.split('.')]
        first = octets[0]
        second = octets[1]

        if first == 104 and 16 <= second <= 31:
            return "美国 Cloudflare", "US"
        if first == 104 and 24 <= second <= 27:
            return "美国 Cloudflare", "US"
        if first == 172 and 64 <= second <= 71:
            return "美国 Cloudflare", "US"
        if first == 162 and second in [158, 159]:
            return "美国 Cloudflare", "US"
        if first == 108 and second == 162:
            return "美国 Cloudflare", "US"
        if first == 188 and second in [114, 115]:
            return "欧洲 Cloudflare", "EU"
        if first == 190 and 80 <= second <= 93:
            return "美国 Cloudflare", "US"
        if first == 198 and second == 41:
            return "美国 Cloudflare", "US"
        if first == 197 and second == 234:
            return "欧洲 Cloudflare", "EU"
        if first == 209 and second == 242:
            return "中国香港 Cloudflare", "HK"
        if first == 206 and second == 286:
            return "新加坡 Cloudflare", "SG"
        if first == 141 and second == 101:
            return "欧洲 Cloudflare", "EU"
        if first == 103 and 21 <= second <= 22:
            return "美国 Cloudflare", "US"
        if first == 103 and second == 272:
            return "美国 Cloudflare", "US"
        if first == 131 and second == 0:
            return "美国 Cloudflare", "US"
        if first == 173 and second == 245:
            return "美国 Cloudflare", "US"
    except:
        pass
    return None, None

COUNTRY_CODE_MAP = {
    "US": "美国", "HK": "中国香港", "TW": "中国台湾",
    "JP": "日本", "KR": "韩国", "SG": "新加坡",
    "GB": "英国", "DE": "德国", "FR": "法国",
    "CA": "加拿大", "AU": "澳大利亚", "IN": "印度",
    "NL": "荷兰", "RU": "俄罗斯", "BR": "巴西",
    "IT": "意大利", "ES": "西班牙", "SE": "瑞典",
    "CH": "瑞士", "NO": "挪威", "FI": "芬兰",
    "DK": "丹麦", "AT": "奥地利", "BE": "比利时",
    "IE": "爱尔兰", "PT": "葡萄牙", "PL": "波兰",
    "CZ": "捷克", "RO": "罗马尼亚", "HU": "匈牙利",
    "MY": "马来西亚", "TH": "泰国", "VN": "越南",
    "PH": "菲律宾", "ID": "印度尼西亚", "NZ": "新西兰",
    "MX": "墨西哥", "AR": "阿根廷", "CL": "智利",
    "CO": "哥伦比亚", "ZA": "南非", "IL": "以色列",
    "AE": "阿联酋", "SA": "沙特阿拉伯", "TR": "土耳其",
    "CN": "中国",
}

ASN_REGION_MAP = {
    "AS13335": ("美国", "US", "Cloudflare"),
    "AS209242": ("中国香港", "HK", "Cloudflare CDN"),
    "AS206286": ("新加坡", "SG", "Cloudflare"),
    "AS397916": ("日本", "JP", "Cloudflare"),
    "AS14558": ("韩国", "KR", "Cloudflare"),
    "AS4808": ("中国", "CN", "China Telecom"),
    "AS4837": ("中国", "CN", "China Unicom"),
    "AS4134": ("中国", "CN", "ChinaNet"),
    "AS9808": ("中国", "CN", "China Mobile"),
    "AS45090": ("中国香港", "HK", "HGC Global"),
    "AS4760": ("中国香港", "HK", "HKIX"),
    "AS18001": ("中国台湾", "TW", "Chunghwa Telecom"),
    "AS3462": ("中国台湾", "TW", "Data Communication Business Group"),
    "AS17676": ("日本", "JP", "SoftBank"),
    "AS2516": ("日本", "JP", "KDDI"),
    "AS4713": ("韩国", "KR", "Korea Telecom"),
    "AS7552": ("越南", "VN", "Viettel"),
    "AS45899": ("越南", "VN", "VNPT"),
    "AS174": ("美国", "US", "Cogent"),
    "AS3257": ("欧洲", "EU", "GTT"),
    "AS3356": ("美国", "US", "Level 3"),
    "AS6453": ("加拿大", "CA", "Tata Communications"),
    "AS2914": ("日本/美国", "JP/US", "NTT"),
    "AS3491": ("印度", "IN", "PCCW"),
    "AS5511": ("法国", "FR", "Orange"),
    "AS6830": ("德国", "DE", "Liberty Global"),
    "AS3320": ("德国", "DE", "Deutsche Telekom"),
    "AS12389": ("俄罗斯", "RU", "Rostelecom"),
}

# 地区标注解析映射（数据源中的#标注 -> 国家代码）
TAG_COUNTRY_MAP = {
    "HK": ("中国香港", "HK"), "SG": ("新加坡", "SG"), "JP": ("日本", "JP"),
    "KR": ("韩国", "KR"), "US": ("美国", "US"), "TW": ("中国台湾", "TW"),
    "DE": ("德国", "DE"), "GB": ("英国", "GB"), "FR": ("法国", "FR"),
    "NL": ("荷兰", "NL"), "AU": ("澳大利亚", "AU"), "CA": ("加拿大", "CA"),
    "IN": ("印度", "IN"), "RU": ("俄罗斯", "RU"), "BR": ("巴西", "BR"),
    "IT": ("意大利", "IT"), "ES": ("西班牙", "ES"), "SE": ("瑞典", "SE"),
    "CH": ("瑞士", "CH"), "NO": ("挪威", "NO"), "FI": ("芬兰", "FI"),
    "DK": ("丹麦", "DK"), "AT": ("奥地利", "AT"), "BE": ("比利时", "BE"),
    "IE": ("爱尔兰", "IE"), "PT": ("葡萄牙", "PT"), "PL": ("波兰", "PL"),
    "CZ": ("捷克", "CZ"), "RO": ("罗马尼亚", "RO"), "HU": ("匈牙利", "HU"),
    "MY": ("马来西亚", "MY"), "TH": ("泰国", "TH"), "VN": ("越南", "VN"),
    "PH": ("菲律宾", "PH"), "ID": ("印度尼西亚", "ID"), "NZ": ("新西兰", "NZ"),
    "MX": ("墨西哥", "MX"), "AR": ("阿根廷", "AR"), "CL": ("智利", "CL"),
    "CO": ("哥伦比亚", "CO"), "ZA": ("南非", "ZA"), "IL": ("以色列", "IL"),
    "AE": ("阿联酋", "AE"), "SA": ("沙特阿拉伯", "SA"), "TR": ("土耳其", "TR"),
    "CN": ("中国", "CN"),
    # 中文名映射
    "香港": ("中国香港", "HK"), "新加坡": ("新加坡", "SG"), "日本": ("日本", "JP"),
    "韩国": ("韩国", "KR"), "美国": ("美国", "US"), "台湾": ("中国台湾", "TW"),
    "德国": ("德国", "DE"), "英国": ("英国", "GB"), "法国": ("法国", "FR"),
}

def parse_region_tag(tag):
    """解析数据源中的地区标注，返回(地区名, 国家代码)"""
    if not tag:
        return None, None
    tag = tag.strip()
    # 直接匹配国家代码
    upper_tag = tag.upper()
    if upper_tag in TAG_COUNTRY_MAP:
        return TAG_COUNTRY_MAP[upper_tag]
    # 尝试中文名匹配
    if tag in TAG_COUNTRY_MAP:
        return TAG_COUNTRY_MAP[tag]
    # 标注本身是2-3个大写字母，可能是国家代码
    if len(tag) <= 3 and tag.isalpha():
        upper_tag = tag.upper()
        if upper_tag in TAG_COUNTRY_MAP:
            return TAG_COUNTRY_MAP[upper_tag]
        # 未在映射表中但看起来像国家代码，直接用
        return tag, upper_tag
    return None, None

def batch_query_ip_api(ips, batch_size=100):
    """ip-api.com批量查询，每批最多100个IP"""
    results = {}
    is_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'
    timeout = 5 if is_actions else 8
    
    for i in range(0, len(ips), batch_size):
        batch = ips[i:i+batch_size]
        try:
            url = "http://ip-api.com/batch?fields=status,country,countryCode,regionName,city,query&lang=zh-CN"
            payload = [{"query": ip} for ip in batch]
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    if item.get("status") == "success":
                        ip = item.get("query", "")
                        country = item.get("country", "")
                        country_code = item.get("countryCode", "")
                        region = item.get("regionName", "")
                        city = item.get("city", "")
                        parts = [p for p in [country, region, city] if p]
                        location = " ".join(parts) if parts else ""
                        if location:
                            results[ip] = {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX", "source": "ip-api-batch"}
        except:
            pass
    return results

def get_ip_location(ip):
    """地区检测：CF段优先 -> ip-api -> ipinfo -> ip.sb -> ipapi -> iping -> ASN推断"""
    # 优先CF段推断（0ms）
    cf_loc, cf_cc = get_cf_region_fast(ip)
    if cf_loc:
        return {"success": True, "location": cf_loc, "country_code": cf_cc, "source": "cf_range"}

    is_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'
    api_timeout = 5 if is_actions else 8

    apis = [
        ("ip-api", f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,country,countryCode,regionName,city,isp,org,as", "json"),
        ("ipinfo.io", f"https://ipinfo.io/{ip}/json", "json"),
        ("ip.sb", f"https://api.ip.sb/geoip/{ip}", "json"),
        ("ipapi.co", f"https://ipapi.co/{ip}/json/", "json"),
        ("iping.cc", f"https://api.iping.cc/v1/query?ip={ip}&language=zh", "json"),
    ]

    for name, url, resp_type in apis:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            if name == "iping.cc":
                resp = requests.get(url, headers=headers, timeout=api_timeout, verify=False)
            elif name == "ipinfo.io":
                token = config.get("IPINFO_TOKEN", "")
                params = {"token": token} if token else {}
                resp = requests.get(url, headers=headers, timeout=api_timeout, params=params)
            else:
                resp = requests.get(url, headers=headers, timeout=api_timeout)

            if resp.status_code != 200:
                continue

            data = resp.json()

            if name == "ip-api":
                if data.get("status") == "success":
                    country = data.get("country", "") or ""
                    country_code = data.get("countryCode", "") or ""
                    region = data.get("regionName", "") or ""
                    city = data.get("city", "") or ""
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX", "source": name}

            elif name == "ipinfo.io":
                if not data.get("bogon"):
                    country_code = data.get("country", "") or ""
                    region = data.get("region", "") or ""
                    city = data.get("city", "") or ""
                    country = COUNTRY_CODE_MAP.get(country_code, country_code)
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX", "source": name}

            elif name == "ip.sb":
                country = data.get("country", "") or ""
                country_code = data.get("country_code", "") or ""
                region = data.get("region", "") or ""
                city = data.get("city", "") or ""
                parts = [p for p in [country, region, city] if p]
                location = " ".join(parts) if parts else ""
                if location:
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX", "source": name}

            elif name == "ipapi.co":
                country = data.get("country_name", "") or ""
                country_code = data.get("country_code", "") or ""
                region = data.get("region", "") or ""
                city = data.get("city", "") or ""
                parts = [p for p in [country, region, city] if p]
                location = " ".join(parts) if parts else ""
                if location:
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX", "source": name}

            elif name == "iping.cc":
                if data.get("code") == 200 and data.get("data"):
                    info = data["data"]
                    country = info.get("country", "") or ""
                    raw_country_code = info.get("country_code", "") or info.get("countryCode", "") or ""
                    region = info.get("region", "") or ""
                    city = info.get("city", "") or ""

                    country_code = raw_country_code.upper()
                    if country_code and len(country_code) == 2:
                        mapped_country = COUNTRY_CODE_MAP.get(country_code)
                        if mapped_country and not any(c in country for c in ['中国', '美国', '日本']):
                            country = mapped_country

                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code if country_code else "XX", "source": name}

        except:
            continue

    # ASN推断
    try:
        url = f"http://ip-api.com/json/{ip}?fields=as"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            asn_str = data.get("as", "")
            if asn_str and asn_str.startswith("AS"):
                asn_num = asn_str.split()[0]
                if asn_num in ASN_REGION_MAP:
                    country, code, org = ASN_REGION_MAP[asn_num]
                    return {"success": True, "location": f"{country} {org}", "country_code": code, "source": "asn"}
    except:
        pass

    return {"success": False}


def run_stage2(stage1_results, ip_region_tags=None):
    """阶段2：对通过阶段1的IP进行测速+地区检测"""
    if ip_region_tags is None:
        ip_region_tags = {}
    print("=" * 70)
    print("[阶段2] 精选测速 + 地区检测")
    print("=" * 70)

    passed_ips = list(stage1_results.items())
    total = len(passed_ips)
    print(f"\n通过阶段1的IP: {total} 个")

    # --- 2a: 带宽测速 ---
    has_curl = shutil.which("curl")
    bw_results = {}

    if not has_curl:
        print("[WARN] 无curl，跳过带宽测试，仅按延迟排序")
        for ip, data in passed_ips:
            bw_results[ip] = {**data, 'speed': 0}
    else:
        bw_concurrency = min(30, max(5, total // 20))
        bw_timeout = 8
        size_kb = 100  # 100KB小文件

        print(f"\n--- 带宽测速 ---")
        print(f"待测: {total} | 并发: {bw_concurrency} | 超时: {bw_timeout}s | 文件: {size_kb}KB\n")

        t0 = time.time()
        lock = threading.Lock()
        done_count = 0

        with ThreadPoolExecutor(max_workers=bw_concurrency) as executor:
            futures = {}
            for ip, data in passed_ips:
                futures[executor.submit(measure_bandwidth, ip, data['port'], timeout=bw_timeout, size_kb=size_kb)] = (ip, data)

            for future in as_completed(futures):
                ip, data = futures[future]
                try:
                    speed = future.result()
                    bw_results[ip] = {**data, 'speed': speed}
                    if speed > 0:
                        with lock:
                            stats['stage2_bw_passed'] += 1
                except:
                    bw_results[ip] = {**data, 'speed': 0}
                with lock:
                    done_count += 1
                    stats['stage2_bw_tested'] = done_count
                if done_count % 50 == 0 or done_count == total:
                    elapsed = time.time() - t0
                    pct = done_count * 100 // total
                    rate = done_count / elapsed if elapsed > 0 else 0
                    valid = stats['stage2_bw_passed']
                    print(f"  进度: {done_count}/{total} ({pct}%) | 有效带宽: {valid} | {rate:.1f}/s | {elapsed:.1f}s")

        elapsed = time.time() - t0
        print(f"\n[OK] 带宽测速完成! 耗时{elapsed:.1f}s | 有效: {stats['stage2_bw_passed']}/{total}\n")

    # --- 2b: 地区检测（优化版：标注优先+批量查询+高并发） ---
    print(f"--- 地区检测 ---")
    
    # 第一步：利用数据源标注和CF段推断（0ms）
    pre_detected = {}   # ip -> {location, country_code, source}
    need_api_query = []  # 需要API查询的IP列表
    
    cf_detected = 0
    tag_detected = 0
    
    for ip, data in bw_results.items():
        # 优先1：数据源标注
        if ip in ip_region_tags:
            loc_name, cc = parse_region_tag(ip_region_tags[ip])
            if loc_name:
                pre_detected[ip] = {"location": loc_name, "country_code": cc, "source": "source_tag"}
                tag_detected += 1
                continue
        
        # 优先2：CF段推断
        cf_loc, cf_cc = get_cf_region_fast(ip)
        if cf_loc:
            pre_detected[ip] = {"location": cf_loc, "country_code": cf_cc, "source": "cf_range"}
            cf_detected += 1
            continue
        
        # 需要API查询
        need_api_query.append(ip)
    
    print(f"数据源标注直接识别: {tag_detected} 个 | CF段推断: {cf_detected} 个 | 需API查询: {len(need_api_query)} 个\n")
    
    # 第二步：批量API查询（ip-api.com batch，100个/批）
    batch_results = {}
    if need_api_query:
        print(f"  批量API查询: {len(need_api_query)} 个IP...")
        t_batch = time.time()
        batch_results = batch_query_ip_api(need_api_query, batch_size=100)
        batch_elapsed = time.time() - t_batch
        batch_hit = len(batch_results)
        print(f"  批量查询完成: {batch_hit}/{len(need_api_query)} 命中 | 耗时{batch_elapsed:.1f}s")
    
    # 第三步：对批量查询未命中的IP，用高并发逐个查询
    still_need = [ip for ip in need_api_query if ip not in batch_results]
    individual_results = {}
    
    if still_need:
        loc_concurrency = 50  # 从20提高到50
        print(f"\n  逐个API查询: {len(still_need)} 个IP | 并发: {loc_concurrency}")
        
        t0 = time.time()
        lock = threading.Lock()
        done_count = 0
        
        with ThreadPoolExecutor(max_workers=loc_concurrency) as executor:
            futures = {}
            for ip in still_need:
                futures[executor.submit(get_ip_location, ip)] = ip
            
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    loc_result = future.result()
                    if loc_result.get("success"):
                        individual_results[ip] = {
                            "location": loc_result.get("location", "未知"),
                            "country_code": loc_result.get("country_code", "XX"),
                            "source": loc_result.get("source", ""),
                        }
                except:
                    pass
                with lock:
                    done_count += 1
                    if done_count % 50 == 0 or done_count == len(still_need):
                        elapsed = time.time() - t0
                        pct = done_count * 100 // len(still_need)
                        rate = done_count / elapsed if elapsed > 0 else 0
                        print(f"  逐个查询进度: {done_count}/{len(still_need)} ({pct}%) | {rate:.1f}/s | {elapsed:.1f}s")
        
        individual_elapsed = time.time() - t0
        print(f"  逐个查询完成: {len(individual_results)}/{len(still_need)} 命中 | 耗时{individual_elapsed:.1f}s")
    
    # 合并所有地区结果
    t0 = time.time()
    final_data = []
    loc_success = 0
    
    for ip, data in bw_results.items():
        location = "未知"
        country_code = "XX"
        loc_source = ""
        
        if ip in pre_detected:
            info = pre_detected[ip]
            location = info["location"]
            country_code = info["country_code"]
            loc_source = info["source"]
            loc_success += 1
        elif ip in batch_results:
            info = batch_results[ip]
            location = info["location"]
            country_code = info["country_code"]
            loc_source = info["source"]
            loc_success += 1
        elif ip in individual_results:
            info = individual_results[ip]
            location = info["location"]
            country_code = info["country_code"]
            loc_source = info["source"]
            loc_success += 1
        
        final_data.append({
            'ip': ip,
            'port': data['port'],
            'latency': data['latency'],
            'speed': data['speed'],
            'location': location,
            'country_code': country_code,
            'loc_source': loc_source,
        })
    
    elapsed = time.time() - t0
    stats['stage2_loc_success'] = loc_success
    stats['stage2_loc_tested'] = total
    print(f"\n[OK] 地区检测完成! 成功: {loc_success}/{total} | 总耗时{elapsed:.1f}s\n")

    return final_data


# ==================== 阶段3：保存结果 ====================

def run_stage3(final_data):
    """阶段3：评分排序+保存所有通过测试的IP"""
    print("=" * 70)
    print("[阶段3] 评分排序 & 保存结果")
    print("=" * 70)

    total = len(final_data)
    if total == 0:
        print("[FAIL] 无可用节点")
        return

    # 评分
    for item in final_data:
        lat = item['latency']
        spd = item['speed']

        lat_score = max(0, 100 - lat / 10) if lat > 0 else 0
        spd_score = min(100, spd * 5) if spd > 0 else 0

        item['score'] = lat_score * 0.3 + spd_score * 0.7

    # 严格过滤：丢弃带宽为0（未通过测速）和带宽过低的IP
    MIN_BANDWIDTH = 0.5  # 最低带宽0.5Mbps
    valid_data = [x for x in final_data if x['speed'] > 0]
    filtered_low = [x for x in final_data if x['speed'] == 0]
    filtered_slow = [x for x in valid_data if x['speed'] < MIN_BANDWIDTH]
    qualified_data = [x for x in valid_data if x['speed'] >= MIN_BANDWIDTH]

    print(f"\n总计: {len(final_data)} 个通过延迟测试的节点")
    print(f"  丢弃(带宽=0，未通过测速): {len(filtered_low)} 个")
    print(f"  丢弃(带宽<{MIN_BANDWIDTH}Mbps，过慢): {len(filtered_slow)} 个")
    print(f"  优质节点(带宽>={MIN_BANDWIDTH}Mbps): {len(qualified_data)} 个")

    if not qualified_data:
        print("[WARN] 无带宽达标的节点，放宽条件保留所有有带宽数据的IP")
        qualified_data = valid_data
        if not qualified_data:
            print("[FAIL] 无可用节点")
            return

    final_data = qualified_data

    # 按评分排序（高分在前）
    final_data.sort(key=lambda x: -x['score'])

    # 取前1000个最优节点
    MAX_OUTPUT = 1000
    if len(final_data) > MAX_OUTPUT:
        print(f"  截取前 {MAX_OUTPUT} 个最优节点（共 {len(final_data)} 个达标）")
        final_data = final_data[:MAX_OUTPUT]

    # 统计
    fast_items = [x for x in final_data if x['speed'] >= 2.0]
    slow_items = [x for x in final_data if x['speed'] < 2.0]
    hk_items = [x for x in final_data if any(k in x['location'] for k in ['香港', 'Hong Kong', 'Kowloon'])]

    print(f"\n总计: {len(final_data)} 个优质节点")
    print(f"  香港节点: {len(hk_items)}")
    print(f"  高速(>=2Mbps): {len(fast_items)}")
    print(f"  中速(0.5-2Mbps): {len(slow_items)}")

    # 保存
    output_lines = []
    seen = set()

    for item in final_data:
        line = f"{item['ip']}:443#{item['location']}"
        if line not in seen:
            output_lines.append(line)
            seen.add(line)

    output_file = config.get("OUTPUT_FILE", "ip.txt")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines) + '\n')

    print(f"\n[OK] 已保存 {len(output_lines)} 个节点到 {output_file}")
    print(f"   格式: ip:443#地区名称（统一端口）")


# ==================== 主流程 ====================

def main():
    start_time = time.time()
    is_github_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'

    print("=" * 70)
    print("IP节点检测工具 v10.0（三阶段极速版）")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"环境: {'GitHub Actions' if is_github_actions else '本地运行'}")
    print("=" * 70)

    # 获取数据源
    nodes, ip_region_tags = fetch_all_nodes()
    total_nodes = len(nodes)

    if not nodes:
        print("[FAIL] 无可用节点")
        return

    # 阶段1：极速初筛延迟
    stage1_results = run_stage1(nodes)

    if not stage1_results:
        print("[FAIL] 阶段1全部失败，无可用IP")
        return

    # 阶段2：测速+地区检测
    final_data = run_stage2(stage1_results, ip_region_tags)

    # 阶段3：保存结果
    run_stage3(final_data)

    # 统计
    total_time = time.time() - start_time
    print(f"\n{'='*70}")
    print("[STAT] 运行统计")
    print("="*70)
    print(f"  数据源获取: {total_nodes} 个唯一节点")
    print(f"  阶段1-TCP初筛: {stats['stage1_passed']}/{stats['stage1_tested']} ({stats['stage1_passed']/max(stats['stage1_tested'],1)*100:.1f}%)")
    print(f"  阶段2-带宽测速: {stats['stage2_bw_passed']}/{stats['stage2_bw_tested']} ({stats['stage2_bw_passed']/max(stats['stage2_bw_tested'],1)*100:.1f}%)")
    print(f"  阶段2-地区检测: {stats['stage2_loc_success']}/{stats['stage2_loc_tested']} ({stats['stage2_loc_success']/max(stats['stage2_loc_tested'],1)*100:.1f}%)")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print("="*70)

if __name__ == "__main__":
    main()
