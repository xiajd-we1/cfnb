#!/usr/bin/env python3
"""
Cloudflare IP 优选工具 (TCP筛选 + IP可用性二次筛选 + curl带宽测速 + WxPusher通知)
依赖：requests, curl (系统自带)
配置文件：同目录下的 config.json（请根据需要修改参数）
结果保存到 ip.txt，并自动推送到 GitHub，同时批量更新到 Cloudflare DNS
支持 Windows / Linux
优化：国家过滤前置，减少无效 TCP 测试；重试参数可配置；所有网络请求连接超时分离
"""

import requests
import socket
import time
import sys
import re
import os
import subprocess
import shutil
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 预编译正则 ====================
NODE_LINE_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+:\d+#[A-Z]{2}$")
NODE_PATTERN = re.compile(r"^(\d+\.\d+\.\d+\.\d+):(\d+)#(.+)$")
IP_PORT_PATTERN = re.compile(r"^(\d+\.\d+\.\d+\.\d+):(\d+)#")

# ==================== 加载配置文件 ====================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    """加载 config.json 配置文件，缺失必填字段时抛出异常"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] 未找到配置文件 {CONFIG_FILE}")
        print("请在同目录下创建 config.json 文件，内容参考示例。")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] 配置文件格式不正确 - {e}")
        sys.exit(1)

    defaults = {
        "USE_GLOBAL_MODE": True,
        "GLOBAL_TOP_N": 15,
        "PER_COUNTRY_TOP_N": 1,
        "BANDWIDTH_CANDIDATES": 90,
        "TCP_PROBES": 3,
        "MIN_SUCCESS_RATE": 1.0,
        "TIMEOUT": 2.0,
        "SOCKET_DEFAULT_TIMEOUT": 3,
        "PROGRESS_PRINT_INTERVAL": 1,
        "FILTER_COUNTRIES_ENABLED": False,
        "ALLOWED_COUNTRIES": ["US"],
        "ENABLE_WXPUSHER": True,
        "WXPUSHER_APP_TOKEN": "your_app_token_here",
        "WXPUSHER_UIDS": ["your_uid_here"],
        "WXPUSHER_API_URL": "http://wxpusher.zjiecode.com/api/send/message",
        "NOTIFY_TIMEOUT": 3,
        "NOTIFY_CONNECT_TIMEOUT": 3,
        "CF_ENABLED": True,
        "CF_API_TOKEN": "your_CF_API_TOKEN",
        "CF_ZONE_ID": "your_CF_ZONE_ID",
        "CF_DNS_RECORD_NAME": "your_CF_DNS_RECORD_NAME",
        "CF_TTL": 60,
        "CF_PROXIED": False,
        "CF_DNS_CONNECT_TIMEOUT": 3,
        "CF_DNS_READ_TIMEOUT": 3,
        "JSON_URL": "https://zip.cm.edu.kg/all.txt",
        "FETCH_MAX_RETRIES": 3,
        "FETCH_RETRY_DELAY": 3,
        "FETCH_TIMEOUT": 3,
        "FETCH_CONNECT_TIMEOUT": 3,
        "OUTPUT_FILE": "ip.txt",
        "TEST_AVAILABILITY": True,
        "AVAILABILITY_CHECK_API": "https://api.check.proxyip.cmliussss.net/check",
        "AVAILABILITY_TIMEOUT": 3,
        "AVAILABILITY_CONNECT_TIMEOUT": 3,
        "AVAILABILITY_RETRY_MAX": 2,
        "AVAILABILITY_RETRY_DELAY": 3,
        "FILTER_IPV6_AVAILABILITY": True,
        "FILTER_BLOCKED_COUNTRIES_ENABLED": True,
        "BLOCKED_COUNTRIES": [
            "BD", "BI", "BY", "CD", "CF", "CN", "CU", "DE", "ET", "HK",
            "IR", "KP", "LY", "MO", "NG", "NL", "PK", "RU", "SD", "SO",
            "SY", "TH", "TW", "UA", "VE", "VN", "YE", "ZW"
        ],
        "DNS_UPDATE_TARGET_COUNT": 15,
        "BANDWIDTH_SIZE_MB": 0.5,
        "BANDWIDTH_TIMEOUT": 3,
        "BANDWIDTH_RETRY_MAX": 2,
        "BANDWIDTH_RETRY_DELAY": 3,
        "BANDWIDTH_URL_TEMPLATE": "https://speed.cloudflare.com/__down?bytes={bytes}",
        "BANDWIDTH_PROCESS_BUFFER": 2,
        "BANDWIDTH_CONNECT_TIMEOUT": 3,
        "MAX_WORKERS": 200,
        "AVAILABILITY_WORKERS": 10,
        "BANDWIDTH_WORKERS": 10,
        "DNS_UPDATE_MAX_RETRIES": 3,
        "DNS_UPDATE_RETRY_DELAY": 3,
        "GITHUB_SYNC_MAX_RETRIES": 3,
        "GITHUB_SYNC_RETRY_DELAY": 3,
        "GIT_SYNC_PROCESS_TIMEOUT": 180,
        "MIN_BANDWIDTH_MBPS": 1.0,
    }

    for key, value in defaults.items():
        if key not in config:
            config[key] = value
            print(f"[WARN] 配置项 {key} 未设置，使用默认值：{value}")

    return config

cfg = load_config()

USE_GLOBAL_MODE = cfg["USE_GLOBAL_MODE"]
GLOBAL_TOP_N = cfg["GLOBAL_TOP_N"]
PER_COUNTRY_TOP_N = cfg["PER_COUNTRY_TOP_N"]
BANDWIDTH_CANDIDATES = cfg["BANDWIDTH_CANDIDATES"]
TCP_PROBES = cfg["TCP_PROBES"]
MIN_SUCCESS_RATE = cfg["MIN_SUCCESS_RATE"]
TIMEOUT = cfg["TIMEOUT"]
SOCKET_DEFAULT_TIMEOUT = cfg["SOCKET_DEFAULT_TIMEOUT"]
PROGRESS_PRINT_INTERVAL = cfg["PROGRESS_PRINT_INTERVAL"]
FILTER_COUNTRIES_ENABLED = cfg["FILTER_COUNTRIES_ENABLED"]
ALLOWED_COUNTRIES = cfg["ALLOWED_COUNTRIES"]
ENABLE_WXPUSHER = cfg["ENABLE_WXPUSHER"]
WXPUSHER_APP_TOKEN = cfg["WXPUSHER_APP_TOKEN"]
WXPUSHER_UIDS = cfg["WXPUSHER_UIDS"]
WXPUSHER_API_URL = cfg["WXPUSHER_API_URL"]
NOTIFY_TIMEOUT = cfg["NOTIFY_TIMEOUT"]
NOTIFY_CONNECT_TIMEOUT = cfg["NOTIFY_CONNECT_TIMEOUT"]
CF_ENABLED = cfg["CF_ENABLED"]
CF_API_TOKEN = cfg["CF_API_TOKEN"]
CF_ZONE_ID = cfg["CF_ZONE_ID"]
CF_DNS_RECORD_NAME = cfg["CF_DNS_RECORD_NAME"]
CF_TTL = cfg["CF_TTL"]
CF_PROXIED = cfg["CF_PROXIED"]
CF_DNS_CONNECT_TIMEOUT = cfg["CF_DNS_CONNECT_TIMEOUT"]
CF_DNS_READ_TIMEOUT = cfg["CF_DNS_READ_TIMEOUT"]
JSON_URL = cfg["JSON_URL"]
FETCH_MAX_RETRIES = cfg["FETCH_MAX_RETRIES"]
FETCH_RETRY_DELAY = cfg["FETCH_RETRY_DELAY"]
FETCH_TIMEOUT = cfg["FETCH_TIMEOUT"]
FETCH_CONNECT_TIMEOUT = cfg["FETCH_CONNECT_TIMEOUT"]
OUTPUT_FILE = cfg["OUTPUT_FILE"]
TEST_AVAILABILITY = cfg["TEST_AVAILABILITY"]
AVAILABILITY_CHECK_API = cfg["AVAILABILITY_CHECK_API"]
AVAILABILITY_TIMEOUT = cfg["AVAILABILITY_TIMEOUT"]
AVAILABILITY_CONNECT_TIMEOUT = cfg["AVAILABILITY_CONNECT_TIMEOUT"]
AVAILABILITY_RETRY_MAX = cfg["AVAILABILITY_RETRY_MAX"]
AVAILABILITY_RETRY_DELAY = cfg["AVAILABILITY_RETRY_DELAY"]
FILTER_IPV6_AVAILABILITY = cfg["FILTER_IPV6_AVAILABILITY"]
FILTER_BLOCKED_COUNTRIES_ENABLED = cfg["FILTER_BLOCKED_COUNTRIES_ENABLED"]
BLOCKED_COUNTRIES = cfg["BLOCKED_COUNTRIES"]
DNS_UPDATE_TARGET_COUNT = cfg["DNS_UPDATE_TARGET_COUNT"]
BANDWIDTH_SIZE_MB = cfg["BANDWIDTH_SIZE_MB"]
BANDWIDTH_TIMEOUT = cfg["BANDWIDTH_TIMEOUT"]
BANDWIDTH_RETRY_MAX = cfg["BANDWIDTH_RETRY_MAX"]
BANDWIDTH_RETRY_DELAY = cfg["BANDWIDTH_RETRY_DELAY"]
BANDWIDTH_URL_TEMPLATE = cfg["BANDWIDTH_URL_TEMPLATE"]
BANDWIDTH_PROCESS_BUFFER = cfg["BANDWIDTH_PROCESS_BUFFER"]
BANDWIDTH_CONNECT_TIMEOUT = cfg["BANDWIDTH_CONNECT_TIMEOUT"]
MAX_WORKERS = cfg["MAX_WORKERS"]
AVAILABILITY_WORKERS = cfg["AVAILABILITY_WORKERS"]
BANDWIDTH_WORKERS = cfg["BANDWIDTH_WORKERS"]
BANDWIDTH_WORKERS_MIN = cfg.get("BANDWIDTH_WORKERS_MIN", 50)
BANDWIDTH_WORKERS_MAX = cfg.get("BANDWIDTH_WORKERS_MAX", 150)
BANDWIDTH_AUTO_ADJUST = cfg.get("BANDWIDTH_AUTO_ADJUST", True)
DNS_UPDATE_MAX_RETRIES = cfg["DNS_UPDATE_MAX_RETRIES"]
DNS_UPDATE_RETRY_DELAY = cfg["DNS_UPDATE_RETRY_DELAY"]
GITHUB_SYNC_MAX_RETRIES = cfg["GITHUB_SYNC_MAX_RETRIES"]
GITHUB_SYNC_RETRY_DELAY = cfg["GITHUB_SYNC_RETRY_DELAY"]
GIT_SYNC_PROCESS_TIMEOUT = cfg["GIT_SYNC_PROCESS_TIMEOUT"]

socket.setdefaulttimeout(SOCKET_DEFAULT_TIMEOUT)
BANDWIDTH_URL = BANDWIDTH_URL_TEMPLATE.format(bytes=int(BANDWIDTH_SIZE_MB * 1024 * 1024))

# ====================================================

def send_wxpusher_notification(content, summary):
    if not ENABLE_WXPUSHER:
        return
    try:
        payload = {
            "appToken": WXPUSHER_APP_TOKEN,
            "content": content,
            "summary": summary,
            "uids": WXPUSHER_UIDS
        }
        headers = {"Content-Type": "application/json; charset=utf-8"}
        resp = requests.post(
            WXPUSHER_API_URL,
            data=json.dumps(payload),
            headers=headers,
            timeout=(NOTIFY_CONNECT_TIMEOUT, NOTIFY_TIMEOUT)
        )
        if resp.status_code == 200:
            print("[OK] 微信通知已发送")
        else:
            print(f"[WARN] 微信通知发送失败: {resp.status_code}")
    except Exception as e:
        print(f"[WARN] 微信通知异常: {e}")

# ====================================================
# 真实地区检测与风控值评估
# ====================================================

def get_real_location_ping0(ip, timeout=5):
    """使用ping0.cc获取真实地理位置（免费API）"""
    try:
        url = f"https://ping0.cc/geo?ip={ip}"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200 and resp.text.strip():
            parts = resp.text.strip().split(' ', 3)
            if len(parts) >= 4:
                location = parts[1] if len(parts) > 1 else ""
                asn_info = parts[2] if len(parts) > 2 else ""
                org = parts[3] if len(parts) > 3 else ""
                return {
                    "location": location,
                    "asn": asn_info,
                    "org": org,
                    "source": "ping0"
                }
    except Exception as e:
        pass
    return None

def get_real_location_ipsb(ip, timeout=5):
    """使用ip.sb API获取真实地理位置（推荐，返回JSON格式）"""
    try:
        url = f"https://api.ip.sb/geoip/{ip}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ip": data.get("ip", ""),
                "country_code": data.get("country_code", ""),
                "country": data.get("country", ""),
                "region": data.get("region", ""),
                "city": data.get("city", ""),
                "organization": data.get("organization", ""),
                "isp": data.get("isp", ""),
                "asn": data.get("asn", ""),
                "asn_organization": data.get("asn_organization", ""),
                "latitude": data.get("latitude", ""),
                "longitude": data.get("longitude", ""),
                "timezone": data.get("timezone", ""),
                "source": "ipsb"
            }
    except Exception as e:
        pass
    return None

def get_risk_score_iping(ip, timeout=5):
    """使用iping.cc获取IP风控值和纯净度信息"""
    try:
        url = f"https://api.iping.cc/v1/query?ip={ip}&language=zh"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                info = data["data"]
                return {
                    "risk_score": info.get("risk_score", ""),
                    "risk_tag": info.get("risk_tag", ""),
                    "is_proxy": info.get("is_proxy", ""),
                    "usage_type": info.get("usage_type", ""),
                    "type": info.get("type", ""),
                    "continent": info.get("continent", ""),
                    "country_cn": info.get("country", ""),
                    "region": info.get("region", ""),
                    "city": info.get("city", ""),
                    "isp": info.get("isp", ""),
                    "asn": info.get("asn", ""),
                    "as_owner": info.get("as_owner", ""),
                    "as_type": info.get("as_type", ""),
                    "company": info.get("company", ""),
                    "source": "iping"
                }
    except Exception as e:
        pass
    return None

def get_country_code_from_location(location_text):
    """从位置文本中提取国家代码"""
    if not location_text:
        return "UNKNOWN"
    
    country_mapping = {
        "美国": "US", "日本": "JP", "韩国": "KR", "香港": "HK", 
        "台湾": "TW", "新加坡": "SG", "英国": "GB", "德国": "DE",
        "法国": "FR", "加拿大": "CA", "澳大利亚": "AU", "巴西": "BR",
        "印度": "IN", "俄罗斯": "RU", "荷兰": "NL", "芬兰": "FI",
        "瑞典": "SE", "挪威": "NO", "丹麦": "DK", "瑞士": "CH",
        "奥地利": "AT", "比利时": "BE", "西班牙": "ES", "葡萄牙": "PT",
        "意大利": "IT", "波兰": "PL", "捷克": "CZ", "匈牙利": "HU",
        "罗马尼亚": "RO", "保加利亚": "BG", "希腊": "GR", "土耳其": "TR",
        "以色列": "IL", "阿联酋": "AE", "沙特阿拉伯": "SA", "泰国": "TH",
        "越南": "VN", "马来西亚": "MY", "印度尼西亚": "ID", "菲律宾": "PH",
        "阿根廷": "AR", "智利": "CL", "墨西哥": "MX", "南非": "ZA",
        "埃及": "EG", "尼日利亚": "NG", "肯尼亚": "KE", "中国": "CN"
    }
    
    for cn_name, code in country_mapping.items():
        if cn_name in location_text:
            return code
    
    return "UNKNOWN"

def calculate_risk_score(location_info, ip):
    """基于IP信息计算风控值（0-100，越低越好）"""
    risk_score = 0
    risk_factors = []
    
    if not location_info:
        return 50, ["无法获取位置信息"]
    
    org = location_info.get("org", "").lower()
    asn = location_info.get("asn", "").lower()
    location = location_info.get("location", "")
    
    # IDC/数据中心检测
    idc_keywords = ["amazon", "google", "microsoft", "azure", "digitalocean", 
                   "linode", "vultr", "ovh", "cloudflare", "alibaba", "tencent",
                   "huawei", "oracle", "ec2", "data center", "idc", "hosting",
                   "server", "cloud"]
    for keyword in idc_keywords:
        if keyword in org or keyword in asn:
            risk_score += 25
            risk_factors.append(f"数据中心({keyword})")
            break
    
    # 云服务提供商
    cloud_providers = ["aws", "amazon web", "google cloud", "microsoft azure",
                      "alibaba cloud", "tencent cloud", "oracle cloud"]
    for provider in cloud_providers:
        if provider in org:
            risk_score += 15
            risk_factors.append(f"云服务商({provider})")
            break
    
    # VPN/代理特征
    vpn_keywords = ["vpn", "proxy", "tor", "exit node", "anonymous"]
    for keyword in vpn_keywords:
        if keyword in org or keyword in asn:
            risk_score += 30
            risk_factors.append(f"VPN/代理特征({keyword})")
            break
    
    # 已知高风险ASN
    high_risk_asn = ["as13335"]  # Cloudflare
    for ra in high_risk_asn:
        if ra in asn:
            risk_score += 10
            risk_factors.append(f"高风险ASN({ra})")
    
    # 限制最高分为100
    risk_score = min(risk_score, 100)
    
    if not risk_factors:
        risk_factors.append("正常")
    
    return risk_score, risk_factors

def enrich_node_with_real_info(node, timeout=5):
    """为节点添加真实地区和风控值信息（优先使用iping.cc）"""
    m = NODE_PATTERN.match(node)
    if not m:
        return node, {}
    
    ip = m.group(1)
    port = m.group(2)
    
    # 1. 优先使用iping.cc获取风控值和中文位置信息
    iping_info = get_risk_score_iping(ip, timeout)
    
    # 2. 使用ip.sb获取准确的国家代码（备用）
    ipsb_info = get_real_location_ipsb(ip, timeout)
    
    # 3. 如果都失败，使用ping0作为后备
    if not ipsb_info and not ipsb_info:
        ping0_info = get_real_location_ping0(ip, timeout)
        if ping0_info:
            country_code = get_country_code_from_location(ping0_info.get("location", ""))
            ipsb_info = {
                "country_code": country_code,
                "country": ping0_info.get("location", "").split(' ')[0] if ping0_info.get("location") else "",
                "organization": ping0_info.get("org", ""),
                "asn": ping0_info.get("asn", ""),
                "source": "ping0"
            }
    
    if not ipsb_info and not iping_info:
        return node, {"error": "无法获取位置信息"}
    
    # 合并信息 - 优先使用iping.cc的数据
    country_cn = iping_info.get("country_cn", "") if iping_info else ""
    country_code = ipsb_info.get("country_code", "") if ipsb_info else ""
    
    # 优先使用中文国家名，如果没有则用代码
    display_country = country_cn if country_cn else (ipsb_info.get("country", "") if ipsb_info else country_code)
    
    # 获取风控值（主要来自iping.cc）
    risk_score_raw = iping_info.get("risk_score", "") if iping_info else ""
    if isinstance(risk_score_raw, int):
        risk_score = risk_score_raw
    elif isinstance(risk_score_raw, str) and risk_score_raw.isdigit():
        risk_score = int(risk_score_raw)
    else:
        risk_score = -1
    
    # 获取其他详细信息
    organization = iping_info.get("company", "") or iping_info.get("isp", "") or (ipsb_info.get("organization", "") if ipsb_info else "")
    city = iping_info.get("city", "") or (ipsb_info.get("city", "") if ipsb_info else "")
    region = iping_info.get("region", "") or (ipsb_info.get("region", "") if ipsb_info else "")
    is_proxy = iping_info.get("is_proxy", "") if iping_info else "未知"
    usage_type = iping_info.get("usage_type", "") if iping_info else "未知"
    
    # 构建真实位置描述
    real_location_parts = []
    if country_cn:
        real_location_parts.append(country_cn)
    elif country_code:
        real_location_parts.append(country_code)
    if region:
        real_location_parts.append(region)
    if city:
        real_location_parts.append(city)
    real_location = " ".join(real_location_parts) if real_location_parts else (display_country if display_country else "未知")
    
    # 风控等级判断
    if risk_score >= 0:
        if risk_score <= 15:
            risk_level = "纯净"
        elif risk_score <= 30:
            risk_level = "低"
        elif risk_score <= 60:
            risk_level = "中"
        else:
            risk_level = "高"
    else:
        risk_level = "未知"
    
    # 构建详细信息
    enriched_info = {
        "ip": ip,
        "port": port,
        "real_location": real_location,
        "country_code": country_code,
        "country_cn": country_cn,
        "display_country": display_country,
        "city": city,
        "region": region,
        "organization": organization,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "is_proxy": is_proxy,
        "usage_type": usage_type,
        "source_ipsb": ipsb_info.get("source") if ipsb_info else "",
        "source_iping": iping_info.get("source") if iping_info else ""
    }
    
    # 新格式：IP:端口#真实地区编码或中文名#风控值
    output_country = country_code if country_code else country_cn
    new_node = f"{ip}:{port}#{output_country}#{risk_score}"
    
    return new_node, enriched_info

def batch_enrich_nodes(nodes, max_workers=20, timeout=5):
    """批量处理节点，添加真实地区和风控值"""
    enriched_nodes = []
    nodes_info = {}
    
    print(f"\n开始真实地区与风控值检测（共 {len(nodes)} 个节点）...")
    print("=" * 60)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_node = {executor.submit(enrich_node_with_real_info, node, timeout): node 
                        for node in nodes}
        
        completed = 0
        for future in as_completed(future_to_node):
            original_node = future_to_node[future]
            try:
                new_node, info = future.result()
                enriched_nodes.append(new_node)
                if info and "error" not in info:
                    nodes_info[info["ip"]] = info
                completed += 1
                
                if completed % 10 == 0 or completed == len(nodes):
                    print(f"  进度: {completed}/{len(nodes)} ({completed*100//len(nodes)}%)")
                    
            except Exception as e:
                enriched_nodes.append(original_node)
                completed += 1
    
    print("=" * 60)
    print(f"检测完成！成功获取 {len(nodes_info)} 个节点的详细信息\n")
    
    return enriched_nodes, nodes_info

def fetch_from_source(source_info):
    """从单个数据源获取节点，支持多种格式"""
    url = source_info.get("url")
    name = source_info.get("name", url)
    
    if not source_info.get("enabled", True):
        return []
    
    try:
        print(f"  正在获取 [{name}] ...", end=" ")
        resp = requests.get(url, timeout=(FETCH_CONNECT_TIMEOUT, FETCH_TIMEOUT))
        resp.raise_for_status()
        
        lines = [line.strip() for line in resp.text.splitlines() 
                if line.strip() and not line.startswith('#')]
        
        nodes = []
        for line in lines:
            node = None
            
            if NODE_LINE_PATTERN.match(line):
                node = line
            elif re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', line):
                node = f"{line}#US"
            elif re.match(r'^\d+\.\d+\.\d+\.\d+$', line):
                node = f"{line}:443#US"
            elif ',' in line:
                parts = [p.strip() for p in line.split(',')]
                
                if parts[0] == 'IP' or not re.match(r'^\d+\.\d+\.\d+\.\d+', parts[0]):
                    continue
                
                ip = parts[0]
                port = "443"
                country = "US"
                
                if len(parts) >= 3:
                    try:
                        port = str(int(parts[2]))
                    except:
                        pass
                
                if len(parts) >= 5:
                    country_code = parts[4].strip().upper()
                    if re.match(r'^[A-Z]{2}$', country_code):
                        country = country_code
                
                node = f"{ip}:{port}#{country}"
            
            if node and NODE_LINE_PATTERN.match(node):
                nodes.append(node)
        
        print(f"[OK] {len(nodes)} 个节点")
        return nodes
        
    except Exception as e:
        print(f"[FAIL] {str(e)[:50]}")
        return []

def fetch_nodes():
    """从多个数据源获取节点（增强版：多级去重）"""
    all_nodes = set()
    ip_node_map = {}  # IP -> 最佳节点映射
    duplicate_count = 0
    
    data_sources = cfg.get("DATA_SOURCES", [])
    
    if not data_sources:
        data_sources = [{"url": JSON_URL, "enabled": True, "name": "主数据源"}]
    
    print(f"\n开始从 {len(data_sources)} 个数据源获取节点...")
    print("=" * 60)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_from_source, source): source for source in data_sources}
        
        for future in as_completed(futures):
            nodes = future.result()
            for node in nodes:
                m = NODE_PATTERN.match(node)
                if m:
                    ip = m.group(1)
                    if ip in ip_node_map:
                        duplicate_count += 1
                    else:
                        ip_node_map[ip] = node
                all_nodes.add(node)
    
    unique_by_ip = list(ip_node_map.values())
    
    print("=" * 60)
    print(f"原始节点: {len(all_nodes)} 个")
    print(f"IP去重后: {len(unique_by_ip)} 个 (去除 {duplicate_count} 个重复IP)")
    print(f"\n总计获取 {len(unique_by_ip)} 个唯一IP节点\n")
    
    if not unique_by_ip:
        print("[ERROR] 未获取到任何节点，退出程序。")
        send_wxpusher_notification(
            content="从所有数据源均未获取到节点",
            summary="获取节点失败"
        )
        sys.exit(1)
    
    return unique_by_ip

def test_tcp_latency(ip, port, timeout=TIMEOUT, probes=TCP_PROBES):
    min_latency = float("inf")
    success = 0
    for _ in range(probes):
        try:
            start = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((ip, int(port)))
            latency = time.time() - start
            if latency < min_latency:
                min_latency = latency
            success += 1
        except Exception:
            continue
    return min_latency, success

def test_node(node_str):
    m = NODE_PATTERN.match(node_str)
    if not m:
        return None
    ip, port, country = m.groups()
    min_lat, success = test_tcp_latency(ip, port)

    if success == 0 or (success / TCP_PROBES) < MIN_SUCCESS_RATE:
        return None

    return (node_str, min_lat, country, success)

def check_availability(node_str):
    m = IP_PORT_PATTERN.match(node_str)
    if not m:
        return (node_str, False, "unknown", {})
    ip, port = m.group(1), m.group(2)
    proxyip = f"{ip}:{port}"

    best_stack = "unknown"
    best_exit_info = {}
    success = False

    try:
        resp = requests.get(
            AVAILABILITY_CHECK_API,
            params={"proxyip": proxyip},
            timeout=(AVAILABILITY_CONNECT_TIMEOUT, AVAILABILITY_TIMEOUT)
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") is True:
                success = True
                best_stack = data.get("inferred_stack", "unknown")
                probe = data.get("probe_results", {}).get("ipv6") or data.get("probe_results", {}).get("ipv4") or {}
                best_exit_info = probe.get("exit", {})
    except Exception:
        pass

    return (node_str, success, best_stack, best_exit_info)

def availability_filter_candidates(candidates):
    if not TEST_AVAILABILITY or not candidates:
        return candidates, {}, {}

    print(f"\n对 {len(candidates)} 个候选节点进行可用性二次筛选...")
    passed = []
    ip_info = {}
    exit_details = {}
    completed = 0
    total = len(candidates)
    last_print = time.time()

    with ThreadPoolExecutor(max_workers=AVAILABILITY_WORKERS) as executor:
        futures = {executor.submit(check_availability, node): node for node in candidates}
        for future in as_completed(futures):
            completed += 1
            node_str, ok, stack, exit_info = future.result()
            if ok:
                passed.append(node_str)
                ip_info[node_str] = stack
                exit_details[node_str] = exit_info
            now = time.time()
            if now - last_print >= PROGRESS_PRINT_INTERVAL or completed == total:
                print(f"\r[可用性检测] 进度：{completed}/{total} ({(completed/total)*100:.1f}%) 通过数量：{len(passed)}", end="", flush=True)
                last_print = now
    print()
    return passed, ip_info, exit_details

def availability_filter_with_retry(candidates):
    if not TEST_AVAILABILITY or not candidates:
        return candidates, {}, {}

    passed = []
    ip_info = {}
    exit_details = {}
    for attempt in range(1, AVAILABILITY_RETRY_MAX + 1):
        print(f"\n[可用性检测] 第 {attempt} 轮检测...")
        passed, ip_info, exit_details = availability_filter_candidates(candidates)
        if passed:
            print(f"[OK] 可用性检测通过 {len(passed)} 个节点")
            return passed, ip_info, exit_details
        if attempt < AVAILABILITY_RETRY_MAX:
            print(f"[WARN] 本轮可用性检测通过率为 0%，等待 {AVAILABILITY_RETRY_DELAY} 秒后重试...")
            time.sleep(AVAILABILITY_RETRY_DELAY)

    print(f"[ERROR] 可用性检测经 {AVAILABILITY_RETRY_MAX} 轮重试后仍无节点通过。")
    send_wxpusher_notification(
        content=f"IP 可用性检测经 {AVAILABILITY_RETRY_MAX} 轮重试后仍无节点通过，已跳过过滤，使用原候选列表继续。",
        summary="可用性检测全部失败"
    )
    return candidates, {}, {}

def measure_bandwidth_curl(node_str):
    m = IP_PORT_PATTERN.match(node_str)
    if not m:
        return (node_str, 0)
    ip, port = m.group(1), m.group(2)

    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total}",
        "--resolve", f"speed.cloudflare.com:{port}:{ip}",
        "--connect-timeout", str(BANDWIDTH_CONNECT_TIMEOUT),
        "--max-time", str(BANDWIDTH_TIMEOUT),
        "--insecure",
        BANDWIDTH_URL
    ]

    try:
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=BANDWIDTH_TIMEOUT + BANDWIDTH_PROCESS_BUFFER)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                size_bytes = float(parts[0])
                time_total = float(parts[1])
                if time_total > 0 and size_bytes > 0:
                    speed_mbps = (size_bytes * 8) / (time_total * 1000 * 1000)
                    return (node_str, speed_mbps)
    except Exception:
        pass
    return (node_str, 0)

def bandwidth_filter(candidates):
    if not candidates:
        return []

    if not shutil.which("curl"):
        print("[WARN] 未检测到 curl 命令，带宽测速将跳过。")
        return []

    min_bandwidth = cfg.get("MIN_BANDWIDTH_MBPS", 1.0)
    
    current_workers = BANDWIDTH_WORKERS
    if BANDWIDTH_AUTO_ADJUST:
        current_workers = min(BANDWIDTH_WORKERS_MAX, max(BANDWIDTH_WORKERS_MIN, BANDWIDTH_WORKERS))
    
    print(f"\n开始带宽测速（对前 {len(candidates)} 个节点，并发 {current_workers}，超时 {BANDWIDTH_TIMEOUT}s）...")
    print(f"最小带宽要求：{min_bandwidth} Mbps")
    if BANDWIDTH_AUTO_ADJUST:
        print(f"自动调节并发：{BANDWIDTH_WORKERS_MIN} - {BANDWIDTH_WORKERS_MAX}")
    
    results = []
    completed = 0
    total = len(candidates)
    last_print = time.time()
    filtered_count = 0
    success_count = 0
    fail_count = 0
    last_adjust_time = time.time()
    adjust_interval = 5

    with ThreadPoolExecutor(max_workers=current_workers) as executor:
        futures = {executor.submit(measure_bandwidth_curl, node): node for node in candidates}
        for future in as_completed(futures):
            completed += 1
            node, speed = future.result()
            if speed > 0:
                success_count += 1
                if speed >= min_bandwidth:
                    results.append((node, speed))
                else:
                    filtered_count += 1
            else:
                fail_count += 1
            
            now = time.time()
            if now - last_print >= PROGRESS_PRINT_INTERVAL or completed == total:
                print(f"\r[带宽测速] 进度：{completed}/{total} ({(completed/total)*100:.1f}%) 有效：{len(results)} 低速过滤：{filtered_count} 并发：{current_workers}", end="", flush=True)
                last_print = now
            
            if BANDWIDTH_AUTO_ADJUST and (now - last_adjust_time >= adjust_interval) and completed < total:
                total_tested = success_count + fail_count
                if total_tested > 0:
                    success_rate = success_count / total_tested
                    
                    if success_rate > 0.7 and current_workers < BANDWIDTH_WORKERS_MAX:
                        new_workers = min(BANDWIDTH_WORKERS_MAX, current_workers + 10)
                        if new_workers != current_workers:
                            current_workers = new_workers
                            executor._max_workers = current_workers
                    elif success_rate < 0.3 and current_workers > BANDWIDTH_WORKERS_MIN:
                        new_workers = max(BANDWIDTH_WORKERS_MIN, current_workers - 10)
                        if new_workers != current_workers:
                            current_workers = new_workers
                            executor._max_workers = current_workers
                    
                    last_adjust_time = now
                    success_count = 0
                    fail_count = 0

    print()
    
    if filtered_count > 0:
        print(f"已过滤 {filtered_count} 个低带宽节点（< {min_bandwidth} Mbps）")
    
    results.sort(key=lambda x: x[1], reverse=True)
    print(f"带宽测速完成，有效节点 {len(results)} 个")
    
    return results

def batch_update_cloudflare_dns(ip_list, ip_info=None, full_bw_results=None, target_count=None, latency_map=None):
    if not cfg.get("CF_ENABLED", False):
        print("Cloudflare DNS 批量更新未启用。")
        return

    if target_count is None:
        target_count = cfg.get("DNS_UPDATE_TARGET_COUNT", 15)

    dns_ip_list = []
    dns_node_list = []
    filtered_by_port = 0
    filtered_by_ipv6 = 0
    filtered_by_country = 0

    if full_bw_results and ip_info:
        blocked_set = set()
        if cfg.get("FILTER_BLOCKED_COUNTRIES_ENABLED", False):
            blocked_set = {c.upper() for c in cfg.get("BLOCKED_COUNTRIES", [])}

        for node_str, speed in full_bw_results:
            if ':' in node_str:
                port = node_str.split(':')[1].split('#')[0]
                if port != '443':
                    filtered_by_port += 1
                    continue

            if cfg.get("FILTER_IPV6_AVAILABILITY", False):
                stack = ip_info.get(node_str, "unknown")
                if stack == "ipv6_only":
                    filtered_by_ipv6 += 1
                    continue

            if blocked_set and '#' in node_str:
                country = node_str.split('#')[-1].upper()
                if country in blocked_set:
                    filtered_by_country += 1
                    continue

            pure_ip = node_str.split(':')[0]
            dns_ip_list.append(pure_ip)
            dns_node_list.append(node_str)

            if len(dns_ip_list) >= target_count:
                break

        filter_parts = []
        if filtered_by_port > 0:
            filter_parts.append(f"非443端口过滤({filtered_by_port}个)")
        if cfg.get("FILTER_IPV6_AVAILABILITY", False):
            filter_parts.append(f"IPv6落地过滤({filtered_by_ipv6}个)")
        if cfg.get("FILTER_BLOCKED_COUNTRIES_ENABLED", False):
            filter_parts.append(f"屏蔽国家过滤({filtered_by_country}个)")
        filter_str = " + ".join(filter_parts) if filter_parts else "无过滤"
        print(f"从 {len(full_bw_results)} 个测速节点中筛选出 {len(dns_ip_list)} 个节点用于 DNS 更新（{filter_str}）。")

    if not dns_ip_list:
        if ip_list:
            print("[WARN] 未能从完整测速结果构建 DNS 列表，降级使用 ip.txt 中的 IP。")
            dns_ip_list = ip_list
            dns_node_list = ip_list
        else:
            msg = "没有可用的 IP 用于 DNS 更新，跳过。"
            print(msg)
            send_wxpusher_notification(content=msg, summary="DNS 更新跳过")
            return

    seen = set()
    unique_ips = []
    unique_nodes = []
    for ip, node in zip(dns_ip_list, dns_node_list):
        if ip not in seen:
            seen.add(ip)
            unique_ips.append(ip)
            unique_nodes.append(node)
    dns_ip_list = unique_ips
    dns_node_list = unique_nodes

    print(f"\n准备将以下 {len(dns_ip_list)} 个 IP 批量更新到 Cloudflare DNS:")
    speed_map = {}
    if full_bw_results:
        speed_map = {node: speed for node, speed in full_bw_results}
    for i, (ip, node) in enumerate(zip(dns_ip_list, dns_node_list), 1):
        speed = speed_map.get(node, 0)
        lat_ms = float('inf')
        if latency_map and node in latency_map:
            lat_ms = latency_map[node] * 1000
        if lat_ms != float('inf'):
            print(f"{i}. {node} 速度 {speed:.2f} Mbps 延迟 {lat_ms:.2f} ms")
        else:
            print(f"{i}. {ip} 速度 {speed:.2f} Mbps")

    headers = {
        "Authorization": f"Bearer {cfg['CF_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    zone_id = cfg['CF_ZONE_ID']
    record_name = cfg['CF_DNS_RECORD_NAME']
    ttl = cfg.get('CF_TTL', 120)
    proxied = cfg.get('CF_PROXIED', False)

    max_retries = cfg.get('DNS_UPDATE_MAX_RETRIES', 5)
    retry_delay = cfg.get('DNS_UPDATE_RETRY_DELAY', 10)

    for attempt in range(1, max_retries + 1):
        print(f"\n[DNS 更新] 尝试 {attempt}/{max_retries}...")
        try:
            list_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&name={record_name}"
            response = requests.get(list_url, headers=headers, timeout=(CF_DNS_CONNECT_TIMEOUT, CF_DNS_READ_TIMEOUT))
            response.raise_for_status()
            result = response.json()
            if not result.get('success'):
                error_detail = result.get('errors')
                raise Exception(f"查询 DNS 记录失败: {error_detail}")

            existing_records = result.get('result', [])
            deletes = [{"id": rec["id"]} for rec in existing_records]
            posts = [
                {
                    "name": record_name,
                    "type": "A",
                    "content": ip,
                    "ttl": ttl,
                    "proxied": proxied
                }
                for ip in dns_ip_list
            ]

            batch_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/batch"
            payload = {"deletes": deletes, "posts": posts}
            response = requests.post(batch_url, headers=headers, json=payload, timeout=(CF_DNS_CONNECT_TIMEOUT, CF_DNS_READ_TIMEOUT))
            response.raise_for_status()
            result = response.json()
            if not result.get('success'):
                error_detail = result.get('errors')
                raise Exception(f"批量更新失败: {error_detail}")

            success_msg = f"[OK] Cloudflare DNS 批量更新成功！已将 {record_name} 指向 {len(dns_ip_list)} 个 IP。"
            print(success_msg)
            print("   注意：DNS 解析将随机返回这些 IP 中的一个，实现负载均衡。")
            return

        except Exception as e:
            error_msg = f"[尝试 {attempt}/{max_retries}] DNS 更新出错: {e}"
            print(error_msg)
            if attempt < max_retries:
                print(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                final_error = f"[ERROR] Cloudflare DNS 更新失败，已重试 {max_retries} 次，错误：{e}"
                print(final_error)
                send_wxpusher_notification(content=final_error, summary="DNS 更新失败")

def sync_to_github():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "win32":
        script_name = "git_sync.ps1"
        interpreter = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
        creationflags = subprocess.CREATE_NO_WINDOW
    else:
        script_name = "git_sync.sh"
        interpreter = ["bash"]
        creationflags = 0

    script_path = os.path.join(script_dir, script_name)
    if not os.path.exists(script_path):
        print(f"[WARN] 未找到 {script_name}，跳过 GitHub 同步。")
        return

    if sys.platform != "win32":
        try:
            os.chmod(script_path, 0o755)
        except Exception:
            pass

    max_retries = cfg.get('GITHUB_SYNC_MAX_RETRIES', 3)
    retry_delay = cfg.get('GITHUB_SYNC_RETRY_DELAY', 3)
    process_timeout = cfg.get('GIT_SYNC_PROCESS_TIMEOUT', 180)

    for attempt in range(1, max_retries + 1):
        print(f"\n正在同步到 GitHub (尝试 {attempt}/{max_retries})...")
        try:
            cmd = interpreter + [script_path]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags
            )

            try:
                stdout, stderr = process.communicate(timeout=process_timeout)
                if process.returncode == 0:
                    print("[OK] 已自动推送到 GitHub。")
                    return
                else:
                    print(f"[ERROR] 推送失败 (退出码 {process.returncode})")
                    if stderr:
                        print(f"错误信息: {stderr.strip()}")
            except subprocess.TimeoutExpired:
                process.kill()
                print(f"[ERROR] 推送超时（超过 {process_timeout} 秒）")
        except Exception as e:
            print(f"[ERROR] 推送过程异常: {e}")

        if attempt < max_retries:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)

    send_wxpusher_notification(
        content=f"GitHub 推送失败，已重试 {max_retries} 次，请检查网络或仓库状态。",
        summary="GitHub 推送失败"
    )
    print(f"[WARN] 已尝试 {max_retries} 次推送，均失败。")
    print(f"[INFO] 请手动执行以下命令进行推送：")
    print(f"       python push_to_github.py {OUTPUT_FILE}")
    print(f"       或者：")
    print(f"       git add {OUTPUT_FILE}")
    print(f"       git commit -m \"Update IP list\"")
    print(f"       git push origin HEAD")

def main():
    mode_str = f"全局最优{GLOBAL_TOP_N}个" if USE_GLOBAL_MODE else f"每个国家最优{PER_COUNTRY_TOP_N}个"
    print(f"当前模式：{mode_str}，每个节点测试 {TCP_PROBES} 次 TCP 连接")
    print(f"最低成功率要求：{MIN_SUCCESS_RATE*100:.0f}%")
    print(f"IP 可用性二次筛选：{'启用' if TEST_AVAILABILITY else '禁用'}（仅对候选节点）")
    print(f"IPv6 客户端 IP 过滤（仅作用于DNS更新环节）：{'启用' if FILTER_IPV6_AVAILABILITY else '禁用'}")
    print(f"屏蔽国家过滤（仅作用于DNS更新环节）：{'启用' if FILTER_BLOCKED_COUNTRIES_ENABLED else '禁用'}，屏蔽国家：{', '.join(BLOCKED_COUNTRIES)}")
    print(f"带宽测速候选数：{BANDWIDTH_CANDIDATES}，测速文件大小：{BANDWIDTH_SIZE_MB} MB，超时：{BANDWIDTH_TIMEOUT}s")
    if FILTER_COUNTRIES_ENABLED:
        print(f"国家过滤：启用，允许国家：{', '.join(ALLOWED_COUNTRIES)}")

    nodes = fetch_nodes()
    if not nodes:
        print("没有获取到任何有效节点，退出。")
        sys.exit(1)

    if FILTER_COUNTRIES_ENABLED and ALLOWED_COUNTRIES:
        before = len(nodes)
        allowed_set = {c.upper() for c in ALLOWED_COUNTRIES}
        filtered_nodes = []
        for node in nodes:
            parts = node.split('#')
            if len(parts) == 2 and parts[1].upper() in allowed_set:
                filtered_nodes.append(node)
        nodes = filtered_nodes
        after = len(nodes)
        print(f"\n国家过滤（测试前）：{before} -> {after} 个节点（允许国家：{', '.join(allowed_set)}）")
        if not nodes:
            print("[WARN] 过滤后无任何节点，退出程序。")
            sys.exit(0)

    total = len(nodes)
    print(f"开始 TCP 连接测试（超时 {TIMEOUT}s，并发 {MAX_WORKERS}）...")

    results = []
    completed = 0
    last_print = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_node, node): node for node in nodes}
        for future in as_completed(futures):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            now = time.time()
            if now - last_print >= PROGRESS_PRINT_INTERVAL or completed == total:
                print(f"\r进度：{completed}/{total} ({(completed/total)*100:.1f}%)", end="", flush=True)
                last_print = now

    print("\nTCP 测试完成！")
    if not results:
        print("没有通过成功率筛选的节点，请检查网络或降低 MIN_SUCCESS_RATE。")
        sys.exit(0)

    results.sort(key=lambda x: (-x[3], x[1]))
    latency_map = {node: lat for node, lat, _, _ in results}

    if USE_GLOBAL_MODE:
        candidates = [node for node, _, _, _ in results[:BANDWIDTH_CANDIDATES]]
        print(f"\nTCP 最优前 {len(candidates)} 个节点进入候选池。")
    else:
        country_nodes = defaultdict(list)
        for node_str, lat, country, succ in results:
            country_nodes[country].append((node_str, lat, succ))

        total_countries = len(country_nodes)
        base_limit = max(1, BANDWIDTH_CANDIDATES // total_countries)
        candidates = []
        for country, nodes in country_nodes.items():
            nodes_sorted = sorted(nodes, key=lambda x: (-x[2], x[1]))
            limit = min(len(nodes_sorted), base_limit)
            for node_str, lat, succ in nodes_sorted[:limit]:
                candidates.append(node_str)
        print(f"\n各国家候选池分配：共 {total_countries} 个国家，每国最多 {base_limit} 个候选，总计 {len(candidates)} 个节点进入候选池。")

    if not candidates:
        print("没有候选节点，退出。")
        sys.exit(0)

    candidates_after_availability, avail_ip_info, avail_exit_details = availability_filter_with_retry(candidates)

    bw_results = []
    for attempt in range(1, BANDWIDTH_RETRY_MAX + 1):
        print(f"\n[带宽测速] 第 {attempt} 轮测试...")
        bw_results = bandwidth_filter(candidates_after_availability)
        if bw_results:
            break
        if attempt < BANDWIDTH_RETRY_MAX:
            print(f"[WARN] 本轮测速无有效结果，等待 {BANDWIDTH_RETRY_DELAY} 秒后重试...")
            time.sleep(BANDWIDTH_RETRY_DELAY)

    if not bw_results:
        print("\n[WARN] 带宽测速多次重试仍无有效结果，将使用 TCP 筛选结果作为最终节点。")
        send_wxpusher_notification(
            content=f"带宽测速经 {BANDWIDTH_RETRY_MAX} 轮尝试后仍无有效结果，已降级使用 TCP 排序节点。",
            summary="带宽测速全部失败"
        )
        if USE_GLOBAL_MODE:
            final_selected = [node for node, _, _, _ in results[:GLOBAL_TOP_N]]
        else:
            final_selected = []
            for country, nodes in country_nodes.items():
                nodes_sorted = sorted(nodes, key=lambda x: (-x[2], x[1]))
                for node_str, _, _ in nodes_sorted[:PER_COUNTRY_TOP_N]:
                    final_selected.append(node_str)
    else:
        if USE_GLOBAL_MODE:
            final_selected = [node for node, _ in bw_results[:GLOBAL_TOP_N]]
        else:
            country_speed_nodes = defaultdict(list)
            for node, speed in bw_results:
                country = node.split('#')[-1] if '#' in node else ''
                if country:
                    country_speed_nodes[country].append((node, speed))
            final_selected = []
            for country, nodes in country_speed_nodes.items():
                for node, speed in nodes[:PER_COUNTRY_TOP_N]:
                    final_selected.append(node)
            speed_map = {node: speed for node, speed in bw_results}
            final_selected.sort(key=lambda x: speed_map.get(x, 0), reverse=True)

        print("\n================ 最终优选节点 ================")
        speed_map = {node: speed for node, speed in bw_results}
        
        final_unique = []
        seen_ips = set()
        dup_removed = 0
        
        for node in final_selected:
            ip = node.split(':')[0] if ':' in node else node
            if ip not in seen_ips:
                seen_ips.add(ip)
                final_unique.append(node)
            else:
                dup_removed += 1
        
        if dup_removed > 0:
            print(f"[INFO] 最终输出去除 {dup_removed} 个重复IP")
        
        final_selected = final_unique
        
        # 真实地区检测与风控值评估
        print("\n[INFO] 开始真实地区与风控值检测...")
        final_selected, nodes_real_info = batch_enrich_nodes(
            final_selected, 
            max_workers=min(20, len(final_selected)),
            timeout=5
        )
        
        print("\n================ 最终优选节点（含真实信息）=")
        speed_map = {node: speed for node, speed in bw_results}
        
        for i, node in enumerate(final_selected, 1):
            speed = speed_map.get(node.split('#')[0] + '#' + node.split('#')[1] if '#' in node else node, 0)
            lat_sec = latency_map.get(node, float('inf'))
            
            # 解析新格式：IP:端口#国家#风控值
            parts = node.split('#') if '#' in node else [node]
            ip_port = parts[0] if parts else node
            country = parts[1] if len(parts) > 1 else "??"
            risk_score = parts[2] if len(parts) > 2 else "??"
            
            # 获取详细信息
            ip = ip_port.split(':')[0] if ':' in ip_port else ip_port
            info = nodes_real_info.get(ip, {})
            real_location = info.get("real_location", "未知")
            risk_level = info.get("risk_level", "未知")
            
            if lat_sec != float('inf'):
                print(f"{i}. {ip_port} #{country} 风控:{risk_score}({risk_level}) 速度 {speed:.2f} Mbps 延迟 {lat_sec*1000:.2f} ms [{real_location}]")
            else:
                print(f"{i}. {ip_port} #{country} 风控:{risk_score}({risk_level}) 速度 {speed:.2f} Mbps [{real_location}]")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for node_str in final_selected:
            f.write(node_str + "\n")
    print(f"\n[OK] 结果已保存到 {OUTPUT_FILE}（共 {len(final_selected)} 个节点，含真实地区和风控值）")
    print(f"   格式：IP:端口#国家代码#风控值（0-100，越低越纯净）")

    ip_list = []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            ip_list = [line.split(':')[0].strip() for line in f if line.strip()]
    except Exception as e:
        print(f"读取 {OUTPUT_FILE} 时发生错误: {e}")

    target_dns_count = GLOBAL_TOP_N if USE_GLOBAL_MODE else PER_COUNTRY_TOP_N
    batch_update_cloudflare_dns(
        ip_list,
        ip_info=avail_ip_info,
        full_bw_results=bw_results,
        target_count=target_dns_count,
        latency_map=latency_map
    )

    if os.environ.get('GITHUB_ACTIONS') != 'true':
        sync_to_github()
    else:
        print("\n[INFO] 运行在 GitHub Actions 环境中，跳过自动推送（由工作流处理）")

if __name__ == "__main__":
    main()