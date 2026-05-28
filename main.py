#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - v8.0（可用性验证版）
流程：数据源获取 -> 去重 -> TCP测试 -> 带宽测试 -> 可达性验证(CF CDN+TLS) -> 地区检测 -> 评分排序 -> 输出
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

stats_lock = threading.Lock()
stats = {
    'tcp_tested': 0, 'tcp_success': 0,
    'bw_tested': 0, 'bw_success': 0,
    'avail_tested': 0, 'avail_success': 0,
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
        print(f"  [FAIL] HTML解析失败: {str(e)[:50]}")
        return []

def fetch_all_nodes():
    all_nodes = set()
    data_sources = config.get("DATA_SOURCES", [])
    enabled_sources = [ds for ds in data_sources if ds.get("enabled", True)]
    if not enabled_sources:
        print("[WARN] 没有启用的数据源")
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
                        print(f"[OK] HTML解析获取 {count} 个节点")
                    else:
                        print("[WARN] HTML中未找到有效IP")
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
                        print(f"[OK] 获取 {count} 个节点")
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
    print(f"[OK] 总计获取 {len(all_nodes)} 个唯一节点\n")
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

# ========== 带宽测试 ==========

def measure_bandwidth(ip, port=443, timeout=10, size_mb=1.0):
    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    bytes_to_download = int(size_mb * 1024 * 1024)
    bandwidth_url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"

    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total} %{http_code}",
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
    except subprocess.TimeoutExpired:
        pass
    except:
        pass
    return 0

# ========== 可达性验证（CF Workers + TLS）==========

WORKERS_DOMAIN = os.environ.get("WORKERS_DOMAIN", "xin21.whdiah23ouo.dpdns.org")

def check_availability(ip, port=443, timeout=8):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start = time.time()
        result = sock.connect_ex((ip, port))
        connect_time = (time.time() - start) * 1000
        if result != 0:
            sock.close()
            return False, {"tcp": False}
        sock.close()
    except:
        return False, {"tcp": False}

    tls_ok = False
    workers_ok = False

    if shutil.which("curl"):
        try:
            null_device = "NUL" if sys.platform == "win32" else "/dev/null"
            curl_cmd = [
                "curl", "-s", "-o", null_device,
                "-w", "%{http_code}",
                "--resolve", f"{WORKERS_DOMAIN}:{port}:{ip}",
                "--connect-timeout", "5",
                "--max-time", str(timeout),
                "--insecure",
                f"https://{WORKERS_DOMAIN}/"
            ]
            result = subprocess.run(
                curl_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5
            )
            if result.returncode == 0 and result.stdout.strip():
                code = int(result.stdout.strip())
                if 200 <= code < 500:
                    workers_ok = True
                    tls_ok = True
        except:
            pass

        if not tls_ok:
            for host in ["speed.cloudflare.com", "cloudflare.com"]:
                try:
                    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
                    curl_cmd = [
                        "curl", "-s", "-o", null_device,
                        "-w", "%{http_code}",
                        "--resolve", f"{host}:{port}:{ip}",
                        "--connect-timeout", "5",
                        "--max-time", str(timeout),
                        "--insecure",
                        f"https://{host}/"
                    ]
                    result = subprocess.run(
                        curl_cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout + 5
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        code = int(result.stdout.strip())
                        if 200 <= code < 500:
                            tls_ok = True
                            break
                except:
                    continue

    if not tls_ok:
        try:
            import ssl
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            conn = context.wrap_socket(sock, server_hostname=WORKERS_DOMAIN)
            conn.connect((ip, port))
            conn.close()
            tls_ok = True
        except:
            pass

    return tls_ok, {"tcp": True, "tls": tls_ok, "workers": workers_ok, "connect_ms": connect_time}

# ========== 地区检测 ==========

CF_IP_RANGES = {
    (173245, 173245): "美国 Cloudflare",
    (10321, 10322): "美国 Cloudflare",
    (103272, 103272): "美国 Cloudflare",
    (131072, 131072): "美国 Cloudflare",
    (141568, 141568): "美国 Cloudflare",
    (162158, 162159): "美国 Cloudflare",
    (17264, 17267): "美国 Cloudflare",
    (10416, 10419): "美国 Cloudflare",
    (10424, 10427): "美国 Cloudflare",
    (108162, 108163): "美国 Cloudflare",
    (19080, 19093): "美国 Cloudflare",
    (188114, 188115): "欧洲 Cloudflare",
    (197564, 197564): "欧洲 Cloudflare",
    (209242, 209242): "中国香港 Cloudflare CDN",
    (206286, 206286): "新加坡 Cloudflare",
}

def get_cf_ip_region(ip):
    try:
        octets = [int(x) for x in ip.split('.')]
        ip_int = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
        first_octet = octets[0]
        second_octet = octets[1]
        if first_octet == 104 and 16 <= second_octet <= 27:
            return "美国 Cloudflare"
        if first_octet == 104 and second_octet == 19:
            return "美国 Cloudflare"
        if first_octet == 172 and 64 <= second_octet <= 71:
            return "美国 Cloudflare"
        if first_octet == 162 and second_octet == 159:
            return "美国 Cloudflare"
        if first_octet == 108 and second_octet == 162:
            return "美国 Cloudflare"
        if first_octet == 188 and second_octet in [114, 115]:
            return "欧洲 Cloudflare"
        if first_octet == 190 and 80 <= second_octet <= 93:
            return "美国 Cloudflare"
        if first_octet == 198 and second_octet == 41:
            return "美国 Cloudflare"
        if first_octet == 197 and second_octet == 234:
            return "欧洲 Cloudflare"
        if first_octet == 209 and second_octet == 242:
            return "中国香港 Cloudflare CDN"
        if first_octet == 206 and second_octet == 286:
            return "新加坡 Cloudflare"
    except:
        pass
    return None

def get_ip_location(ip):
    is_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'
    api_timeout = 5 if is_actions else 8

    cf_region = get_cf_ip_region(ip)
    if cf_region:
        pass

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
            if resp_type == "json":
                data = resp.json()
            else:
                continue

            if name == "ip-api":
                if data.get("status") == "success":
                    country = data.get("country", "") or ""
                    country_code = data.get("countryCode", "") or ""
                    region = data.get("regionName", "") or ""
                    city = data.get("city", "") or ""
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "ipinfo.io":
                if not data.get("bogon"):
                    country_code = data.get("country", "") or ""
                    region = data.get("region", "") or ""
                    city = data.get("city", "") or ""
                    country_names = {
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
                    }
                    country = country_names.get(country_code, country_code)
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "ip.sb":
                country = data.get("country", "") or ""
                country_code = data.get("country_code", "") or ""
                region = data.get("region", "") or ""
                city = data.get("city", "") or ""
                parts = [p for p in [country, region, city] if p]
                location = " ".join(parts) if parts else ""
                if location:
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "ipapi.co":
                country = data.get("country_name", "") or ""
                country_code = data.get("country_code", "") or ""
                region = data.get("region", "") or ""
                city = data.get("city", "") or ""
                parts = [p for p in [country, region, city] if p]
                location = " ".join(parts) if parts else ""
                if location:
                    return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

            elif name == "iping.cc":
                if data.get("code") == 200 and data.get("data"):
                    info = data["data"]
                    country = info.get("country", "") or ""
                    country_code = info.get("country_code", "") or info.get("countryCode", "") or ""
                    region = info.get("region", "") or ""
                    city = info.get("city", "") or ""
                    parts = [p for p in [country, region, city] if p]
                    location = " ".join(parts) if parts else ""
                    if location:
                        return {"success": True, "location": location, "country_code": country_code.upper() if country_code else "XX"}

        except:
            continue

    if cf_region:
        return {"success": True, "location": cf_region, "country_code": "XX", "source": "cf_range"}

    asn_result = infer_location_from_asn(ip)
    if asn_result:
        return asn_result

    return {"success": False}

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
    "AS8075": ("美国", "US", "Microsoft"),
    "AS15169": ("美国", "US", "Google"),
    "AS16509": ("美国", "US", "Amazon"),
    "AS14618": ("美国", "US", "Amazon"),
    "AS20473": ("美国", "US", "Vultr"),
    "AS63949": ("美国", "US", "Linode"),
    "AS14061": ("美国", "US", "DigitalOcean"),
    "AS16276": ("法国", "FR", "OVH"),
    "AS24940": ("德国", "DE", "Hetzner"),
    "AS60781": ("荷兰", "NL", "Leaseweb"),
    "AS62041": ("荷兰", "NL", "Contabo"),
}

COUNTRY_NAMES = {
    "CN": "中国", "HK": "中国香港", "TW": "中国台湾",
    "JP": "日本", "KR": "韩国", "SG": "新加坡",
    "US": "美国", "GB": "英国", "DE": "德国",
    "FR": "法国", "AU": "澳大利亚", "CA": "加拿大",
    "IN": "印度", "BR": "巴西", "NL": "荷兰",
    "RU": "俄罗斯", "IT": "意大利", "ES": "西班牙",
    "SE": "瑞典", "CH": "瑞士", "NO": "挪威", "FI": "芬兰",
    "DK": "丹麦", "AT": "奥地利", "BE": "比利时",
    "IE": "爱尔兰", "PT": "葡萄牙", "PL": "波兰",
    "MY": "马来西亚", "TH": "泰国", "VN": "越南",
    "PH": "菲律宾", "ID": "印度尼西亚", "NZ": "新西兰",
    "MX": "墨西哥", "AR": "阿根廷", "CL": "智利",
    "ZA": "南非", "IL": "以色列", "AE": "阿联酋",
    "TR": "土耳其", "UA": "乌克兰", "CZ": "捷克",
    "RO": "罗马尼亚", "HU": "匈牙利", "BG": "保加利亚",
}

def infer_location_from_asn(ip):
    try:
        result = subprocess.run(
            ["nslookup", "-type=TXT", f"{ip}.origin.asn.cymru.com", "8.8.8.8"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        asn_match = re.search(r'"(\d+)\s+', output)
        if asn_match:
            asn = f"AS{asn_match.group(1)}"
            if asn in ASN_REGION_MAP:
                country, code, provider = ASN_REGION_MAP[asn]
                return {
                    "success": True,
                    "location": f"{country} ({provider})",
                    "country_code": code,
                    "source": "asn_infer"
                }
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(
                    f"https://stat.ripe.net/data/as-overview/data.json?resource={asn}",
                    headers=headers, timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    holder = data.get("data", {}).get("holder", "")
                    country = data.get("data", {}).get("country", "")
                    if country:
                        cn_name = COUNTRY_NAMES.get(country, country)
                        location = f"{cn_name} ({holder})" if holder else cn_name
                        return {
                            "success": True,
                            "location": location,
                            "country_code": country,
                            "source": "asn_ripe"
                        }
            except:
                pass
            return {
                "success": True,
                "location": f"ASN-{asn}",
                "country_code": "XX",
                "source": "asn_raw"
            }
    except:
        pass
    return None

# ========== 主流程 ==========

def main():
    start_time = time.time()

    print("=" * 70)
    print("IP节点检测工具 - v8.0（可用性验证版）")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"流程: 数据源->TCP->带宽->可达性验证->地区->评分->输出\n")

    # ====== 步骤1：获取并去重 ======
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()
    if not nodes:
        print("[FAIL] 无法获取节点列表")
        return

    total_nodes = len(nodes)
    print(f"[OK] 成功获取 {total_nodes} 个唯一节点\n")

    # ====== 步骤2：TCP测试 ======
    print("=" * 70)
    print("[步骤2] TCP连接测试")
    print("=" * 70)

    is_github_actions = os.environ.get('GITHUB_ACTIONS', '') == 'true'
    tcp_timeout = config.get("TIMEOUT", 5 if is_github_actions else 8)
    tcp_workers = min(300 if is_github_actions else 200, max(50, total_nodes // 50))
    tcp_retries = 1 if is_github_actions else 2
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
                print(f"  进度: {done}/{total} ({pct}%) | TCP成功: {len(tcp_results)} | {rate:.1f}/s | {elapsed:.1f}s")

    t1 = time.time() - t0
    print(f"\n[OK] TCP完成! 耗时{t1:.1f}s | 成功: {len(tcp_results)}/{total}\n")

    if not tcp_results:
        print("[FAIL] TCP全部失败")
        return

    # ====== 步骤3：带宽测试 ======
    print("=" * 70)
    print("[步骤3] 带宽测速")
    print("=" * 70)

    bw_results = []

    if not shutil.which("curl"):
        print("[WARN] 无curl，跳过带宽测试")
        tcp_results.sort(key=lambda x: x[1])
        bw_results = [(node, lat, 0) for node, lat in tcp_results]
    else:
        bw_timeout = config.get("BANDWIDTH_TIMEOUT", 8 if is_github_actions else 12)
        bw_size_mb = config.get("BANDWIDTH_SIZE_MB", 1.0)
        bw_workers = min(50 if is_github_actions else 30, max(10, len(tcp_results) // 100))

        print(f"\n待测: {len(tcp_results)} | 并发: {bw_workers} | 超时: {bw_timeout}s | 文件: {bw_size_mb}MB\n")

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
                    print(f"  进度: {done}/{total_bw} ({pct}%) | 有效带宽: {valid_bw} | {rate:.1f}/s | {elapsed:.1f}s")

        t3 = time.time() - t2
        valid_bw = sum(1 for _, _, s in bw_results if s > 0)
        print(f"\n[OK] 带宽完成! 耗时{t3:.1f}s | 有效: {valid_bw}/{len(bw_results)}\n")

    # ====== 步骤4：可达性验证 ======
    print("=" * 70)
    print("[步骤4] 可达性验证 (CF Workers + TLS)")
    print("=" * 70)

    avail_results = []
    avail_workers = min(100 if is_github_actions else 50, max(20, len(bw_results) // 50))
    print(f"\n待验证: {len(bw_results)} | 并发: {avail_workers}\n")

    t4 = time.time()

    with ThreadPoolExecutor(max_workers=avail_workers) as executor:
        futures = {}
        for node, latency, speed in bw_results:
            m = NODE_PATTERN.match(node)
            if m:
                ip = m.group(1)
                port = int(m.group(2))
                futures[executor.submit(check_availability, ip, port, timeout=8)] = (node, latency, speed)

        done = 0
        total_avail = len(futures)
        for future in as_completed(futures):
            node, latency, speed = futures[future]
            try:
                is_avail, detail = future.result()
                if is_avail:
                    avail_results.append((node, latency, speed))
                    with stats_lock:
                        stats['avail_success'] += 1
            except:
                pass
            done += 1
            with stats_lock:
                stats['avail_tested'] = done
            if done % 200 == 0 or done == total_avail:
                pct = done * 100 // total_avail
                rate = done / (time.time() - t4) if (time.time() - t4) > 0 else 0
                elapsed = time.time() - t4
                print(f"  进度: {done}/{total_avail} ({pct}%) | 可用: {len(avail_results)} | {rate:.1f}/s | {elapsed:.1f}s")

    t5 = time.time() - t4
    print(f"\n[OK] 可达性验证完成! 耗时{t5:.1f}s | 可用: {len(avail_results)}/{stats['avail_tested']}\n")

    if not avail_results:
        print("[WARN] 无可达节点，降级使用带宽测试结果（按速度排序）")
        bw_results.sort(key=lambda x: -x[2])
        avail_results = bw_results[:500]

    # ====== 步骤5：地区检测 ======
    print("=" * 70)
    print("[步骤5] 地区检测")
    print("=" * 70)

    loc_workers = min(150 if is_github_actions else 100, max(30, len(avail_results) // 50))
    print(f"\n待检测: {len(avail_results)} | 并发: {loc_workers}\n")

    final_data = []
    t6 = time.time()

    with ThreadPoolExecutor(max_workers=loc_workers) as executor:
        futures = {}
        for node, latency, speed in avail_results:
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
                rate = done / (time.time() - t6) if (time.time() - t6) > 0 else 0
                elapsed = time.time() - t6
                print(f"  进度: {done}/{total_loc} ({pct}%) | 成功: {stats['loc_success']} | {rate:.1f}/s | {elapsed:.1f}s")

    t7 = time.time() - t6
    print(f"\n[OK] 地区检测完成! 耗时{t7:.1f}s | 成功: {stats['loc_success']}/{len(final_data)}\n")

    # ====== 步骤6：评分排序 + 输出 ======
    print("=" * 70)
    print("[步骤6] 评分排序 & 输出")
    print("=" * 70)

    TARGET = 500
    HK_PRIORITY = 50
    MIN_SPEED = 1.0

    for item in final_data:
        lat = item['latency']
        spd = item['speed']
        lat_score = max(0, 100 - lat / 10) if lat > 0 else 0
        spd_score = min(100, spd * 5) if spd > 0 else 0
        item['score'] = lat_score * 0.3 + spd_score * 0.7

    fast_items = [x for x in final_data if x['speed'] >= MIN_SPEED]
    slow_items = [x for x in final_data if x['speed'] < MIN_SPEED and x['speed'] > 0]
    zero_items = [x for x in final_data if x['speed'] == 0]

    fast_items.sort(key=lambda x: -x['score'])
    slow_items.sort(key=lambda x: -x['score'])
    zero_items.sort(key=lambda x: x['latency'])

    sorted_data = fast_items + slow_items + zero_items

    hk_items = [x for x in sorted_data if any(k in x['location'] for k in ['香港', 'HK', 'Hong Kong', 'Kowloon'])]
    other_items = [x for x in sorted_data if not any(k in x['location'] for k in ['香港', 'HK', 'Hong Kong', 'Kowloon'])]

    print(f"\n[HK] 香港节点: {len(hk_items)} | 其他: {len(other_items)} | 高速(>{MIN_SPEED}Mbps): {len(fast_items)}")

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

    output_lines = []
    for item in output:
        m = NODE_PATTERN.match(item['node'])
        if m:
            ip = m.group(1)
            port = m.group(2)
            output_lines.append(f"{ip}:{port}#{item['location']}")

    if len(output_lines) < TARGET:
        shortage = TARGET - len(output_lines)
        print(f"\n[WARN] 不足{TARGET}个（当前: {len(output_lines)}），补充 {shortage} 个")
        existing = set(output_lines)
        for item in sorted_data[len(output):]:
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

    print(f"\n[OK] 已保存 {len(output_lines)} 个节点到 {output_file}")
    print(f"   格式: ip:端口#地区名称")
    print(f"   [HK] 香港优先: {min(HK_PRIORITY, len(hk_items))} 个")

    if output_lines:
        print(f"\n前20个样本:")
        for i, line in enumerate(output_lines[:20], 1):
            print(f"  [{i:2d}] {line}")

    total_time = time.time() - start_time
    print(f"\n{'='*70}")
    print("[STAT] 运行统计")
    print("="*70)
    print(f"  数据源: {total_nodes} 个唯一节点")
    print(f"  TCP: {stats['tcp_success']}/{stats['tcp_tested']} ({stats['tcp_success']/max(stats['tcp_tested'],1)*100:.1f}%)")
    print(f"  带宽: {stats['bw_success']}/{stats['bw_tested']} ({stats['bw_success']/max(stats['bw_tested'],1)*100:.1f}%)")
    print(f"  可达性: {stats['avail_success']}/{stats['avail_tested']} ({stats['avail_success']/max(stats['avail_tested'],1)*100:.1f}%)")
    print(f"  地区: {stats['loc_success']}/{stats['loc_tested']} ({stats['loc_success']/max(stats['loc_tested'],1)*100:.1f}%)")
    print(f"  高速节点(>{MIN_SPEED}Mbps): {len(fast_items)}")
    print(f"  最终输出: {len(output_lines)} 个节点")
    print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    print("="*70)

if __name__ == "__main__":
    main()
