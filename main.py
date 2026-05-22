#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare IP优选工具 - 增强版
功能：自动获取IP列表、测试可用性、测速、筛选最优IP、更新DNS
新增：真实地区检测（IPinfo.io + iping.cc）+ 风控值评估 + 异步并发框架
"""

import requests
import socket
import json
import time
import re
import random
import subprocess
import sys
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 配置文件路径
CONFIG_FILE = "config.json"

def load_config():
    """加载配置文件"""
    default_config = {
        "USE_GLOBAL_MODE": True,
        "GLOBAL_TOP_N": 300,
        "PER_COUNTRY_TOP_N": 10,
        "BANDWIDTH_CANDIDATES": 1000,
        "TCP_PROBES": 3,
        "MIN_SUCCESS_RATE": 0.9,
        "TIMEOUT": 2.5,
        "SOCKET_DEFAULT_TIMEOUT": 3,
        "PROGRESS_PRINT_INTERVAL": 1,
        "FILTER_COUNTRIES_ENABLED": False,
        "ALLOWED_COUNTRIES": ["US"],
        "ENABLE_WXPUSHER": False,
        "WXPUSHER_APP_TOKEN": "your_app_token_here",
        "WXPUSHER_UIDS": ["your_uid_here"],
        "WXPUSHER_API_URL": "http://wxpusher.zjiecode.com/api/send/message",
        "NOTIFY_TIMEOUT": 3,
        "NOTIFY_CONNECT_TIMEOUT": 3,
        "CF_ENABLED": False,
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
        "FETCH_TIMEOUT": 10,
        "FETCH_CONNECT_TIMEOUT": 5,
        "OUTPUT_FILE": "ip.txt",
        "TEST_AVAILABILITY": False,
        "AVAILABILITY_CHECK_API": "https://api.check.proxyip.cmliussss.net/check",
        "AVAILABILITY_TIMEOUT": 3,
        "AVAILABILITY_CONNECT_TIMEOUT": 3,
        "AVAILABILITY_RETRY_MAX": 2,
        "AVAILABILITY_RETRY_DELAY": 3,
        "FILTER_IPV6_AVAILABILITY": False,
        "FILTER_BLOCKED_COUNTRIES_ENABLED": False,
        "BLOCKED_COUNTRIES": [],
        "DNS_UPDATE_TARGET_COUNT": 15,
        "BANDWIDTH_SIZE_MB": 2.0,
        "BANDWIDTH_TIMEOUT": 8,
        "BANDWIDTH_RETRY_MAX": 2,
        "BANDWIDTH_RETRY_DELAY": 3,
        "BANDWIDTH_URL_TEMPLATE": "https://speed.cloudflare.com/__down?bytes={bytes}",
        "BANDWIDTH_PROCESS_BUFFER": 2,
        "BANDWIDTH_CONNECT_TIMEOUT": 5,
        "MAX_WORKERS": 300,
        "AVAILABILITY_WORKERS": 20,
        "BANDWIDTH_WORKERS": 100,
        "BANDWIDTH_WORKERS_MIN": 50,
        "BANDWIDTH_WORKERS_MAX": 150,
        "BANDWIDTH_AUTO_ADJUST": True,
        "DNS_UPDATE_MAX_RETRIES": 3,
        "DNS_UPDATE_RETRY_DELAY": 3,
        "GITHUB_SYNC_MAX_RETRIES": 3,
        "GITHUB_SYNC_RETRY_DELAY": 3,
        "GIT_SYNC_PROCESS_TIMEOUT": 180,
        "MIN_BANDWIDTH_MBPS": 2.0,
        "DATA_SOURCES": [
            {"url": "https://zip.cm.edu.kg/all.txt", "enabled": True, "name": "主数据源"},
            {"url": "https://raw.githubusercontent.com/xxzh72/yxym/main/best-domain.txt", "enabled": True, "name": "xxzh72-best-domain"},
            {"url": "https://raw.githubusercontent.com/xxzh72/yxym/main/ip.txt", "enabled": True, "name": "xxzh72-ip"},
            {"url": "https://raw.githubusercontent.com/xxzh72/yxym/main/proxyip.txt", "enabled": True, "name": "xxzh72-proxyip"},
            {"url": "https://raw.githubusercontent.com/AiLee77/proxyip.cczz.eu.cc/main/ip.txt", "enabled": True, "name": "AiLee77-ip"},
            {"url": "https://raw.githubusercontent.com/KafeMars/best-ips-domains/main/CF-BestIPs-A", "enabled": True, "name": "KafeMars-CF-A"},
            {"url": "https://raw.githubusercontent.com/KafeMars/best-ips-domains/main/CF-BestIPs-B", "enabled": True, "name": "KafeMars-CF-B"},
            {"url": "https://raw.githubusercontent.com/KafeMars/best-ips-domains/main/cf-bestips.txt", "enabled": True, "name": "KafeMars-cf-bestips"},
            {"url": "https://raw.githubusercontent.com/KafeMars/best-ips-domains/main/HK_IP4", "enabled": True, "name": "KafeMars-HK_IP4"},
            {"url": "https://raw.githubusercontent.com/chris202010/yxym/main/ip.txt", "enabled": True, "name": "chris202010-ip"},
            {"url": "https://raw.githubusercontent.com/chris202010/yxym/main/proxyip.txt", "enabled": True, "name": "chris202010-proxyip"},
            {"url": "https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv", "enabled": True, "name": "xgonce-result-csv"},
            {"url": "https://raw.githubusercontent.com/Wwuyi123/CF-Proxyip/main/proxyip.txt", "enabled": True, "name": "Wwuyi123-proxyip"},
            {"url": "https://raw.githubusercontent.com/Wwuyi123/CF-Proxyip/main/proxyip_with_country.txt", "enabled": True, "name": "Wwuyi123-proxyip-country"},
            {"url": "https://raw.githubusercontent.com/hofccyf/myip/main/sg.txt", "enabled": True, "name": "hofccyf-sg"}
        ],
        "ENABLE_REAL_LOCATION_DETECT": True,
        "REAL_LOCATION_TIMEOUT": 5,
        "REAL_LOCATION_WORKERS": 150,
        "ENABLE_RISK_SCORE": True,
        "MAX_RISK_SCORE": 70,
        "IPINFO_TOKEN": "",
        "ASYNC_CONCURRENCY_MIN": 50,
        "ASYNC_CONCURRENCY_MAX": 150,
        "ASYNC_CONCURRENCY_INITIAL": 100
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
                print(f"✓ 已加载配置文件: {CONFIG_FILE}")
        except Exception as e:
            print(f"⚠ 配置文件加载失败，使用默认配置: {e}")
    else:
        print(f"⚠ 配置文件不存在，使用默认配置")
    
    return default_config

config = load_config()

NODE_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+):(\d+)')
IP_ONLY_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+)$')
IP_COUNTRY_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+)#(\w+)$')
CSV_IP_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+),(\d+),')

def parse_node_from_line(line):
    """
    从一行文本中解析IP节点，支持多种格式：
    1. ip:port（标准格式）
    2. 纯IP（自动添加默认端口443）
    3. ip#country_code（自动添加默认端口443）
    4. CSV格式：ip,port,...（提取IP和端口）
    
    返回: (ip, port) 或 None
    """
    line = line.strip()
    
    if not line or line.startswith('#'):
        return None
    
    # 格式1: ip:port
    match = NODE_PATTERN.match(line)
    if match:
        return (match.group(1), int(match.group(2)))
    
    # 格式2: 纯IP
    match = IP_ONLY_PATTERN.match(line)
    if match:
        return (match.group(1), 443)  # 默认HTTPS端口
    
    # 格式3: ip#country
    match = IP_COUNTRY_PATTERN.match(line)
    if match:
        return (match.group(1), 443)  # 默认HTTPS端口
    
    # 格式4: CSV - ip,port,...
    match = CSV_IP_PATTERN.match(line)
    if match:
        try:
            port = int(match.group(2))
            if 1 <= port <= 65535:
                return (match.group(1), port)
        except:
            pass
    
    return None

class AsyncConcurrencyManager:
    """高性能异步并发管理器 - 支持自动调节并发数"""
    
    def __init__(self, min_workers=50, max_workers=150, initial_workers=100,
                 success_threshold_high=0.7, success_threshold_low=0.3,
                 adjust_step=10, name="Worker"):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.current_workers = initial_workers
        self.success_threshold_high = success_threshold_high
        self.success_threshold_low = success_threshold_low
        self.adjust_step = adjust_step
        self.name = name
        self.lock = threading.Lock()
        self.stats = {"total": 0, "success": 0, "failed": 0}
    
    def record_success(self):
        with self.lock:
            self.stats["total"] += 1
            self.stats["success"] += 1
    
    def record_failed(self):
        with self.lock:
            self.stats["total"] += 1
            self.stats["failed"] += 1
    
    def auto_adjust(self):
        """根据成功率自动调节并发数"""
        with self.lock:
            if self.stats["total"] >= 20:
                success_rate = self.stats["success"] / self.stats["total"]
                
                if success_rate > self.success_threshold_high and self.current_workers < self.max_workers:
                    new_workers = min(self.max_workers, self.current_workers + self.adjust_step)
                    if new_workers != self.current_workers:
                        print(f"  [{self.name}] 并发提升: {self.current_workers} -> {new_workers} (成功率: {success_rate:.1%})")
                        self.current_workers = new_workers
                        
                elif success_rate < self.success_threshold_low and self.current_workers > self.min_workers:
                    new_workers = max(self.min_workers, self.current_workers - self.adjust_step)
                    if new_workers != self.current_workers:
                        print(f"  [{self.name}] 并发降低: {self.current_workers} -> {new_workers} (成功率: {success_rate:.1%})")
                        self.current_workers = new_workers
                
                self.stats = {"total": 0, "success": 0, "failed": 0}
    
    def execute_batch(self, items, worker_func, timeout=None, 
                      show_progress=True, progress_interval=10,
                      description="处理"):
        """批量执行任务（自动并发+进度显示）"""
        results = []
        total = len(items)
        
        if total == 0:
            return results
        
        print(f"\n[{self.name}] 开始{description}（共 {total} 个任务，初始并发: {self.current_workers}）...")
        print("=" * 60)
        
        batch_num = 0
        batch_size = min(200, total)
        
        for i in range(0, total, batch_size):
            batch = items[i:i + batch_size]
            batch_num += 1
            
            with ThreadPoolExecutor(max_workers=self.current_workers) as executor:
                future_to_item = {
                    executor.submit(worker_func, item): item 
                    for item in batch
                }
                
                completed_in_batch = 0
                for future in as_completed(future_to_item):
                    original_item = future_to_item[future]
                    
                    try:
                        result = future.result(timeout=timeout)
                        results.append((original_item, result))
                        self.record_success()
                    except Exception as e:
                        results.append((original_item, None))
                        self.record_failed()
                    
                    completed_in_batch += 1
                    total_completed = len(results)
                    
                    if show_progress and (total_completed % progress_interval == 0 or total_completed == total):
                        pct = total_completed * 100 // total
                        print(f"  进度: {total_completed}/{total} ({pct}%) [并发: {self.current_workers}]")
                
                self.auto_adjust()
        
        success_count = sum(1 for _, r in results if r is not None)
        print("=" * 60)
        print(f"[{self.name}] {description}完成！成功: {success_count}/{total}")
        
        return results

def get_real_location_ipinfo(ip, timeout=5):
    """使用IPinfo.io获取真实地理位置（免费API，无需Token也可用）"""
    try:
        token = config.get("IPINFO_TOKEN", "")
        if token:
            url = f"https://ipinfo.io/{ip}?token={token}"
        else:
            url = f"https://ipinfo.io/{ip}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ip": data.get("ip", ""),
                "country_code": data.get("country", ""),
                "country": data.get("country_name") or data.get("country", ""),
                "region": data.get("region", ""),
                "city": data.get("city", ""),
                "org": data.get("org", ""),
                "asn": data.get("org", "").split()[0] if data.get("org") else "",
                "as_name": " ".join(data.get("org", "").split()[1:]) if data.get("org") and len(data.get("org", "").split()) > 1 else "",
                "location": data.get("loc", ""),
                "source": "ipinfo"
            }
    except Exception as e:
        pass
    return None

def get_risk_score_iping(ip, timeout=5, max_retries=3):
    """使用iping.cc获取IP风控值和纯净度信息（带重试机制）- 主数据源"""
    for attempt in range(max_retries):
        try:
            url = f"https://api.iping.cc/v1/query?ip={ip}&language=zh"
            
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            })
            
            resp = session.get(url, timeout=timeout, verify=True)
            
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
                    
        except requests.exceptions.SSLError as e:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                continue
        except Exception as e:
            break
    
    return None

def get_real_location_ipsb(ip, timeout=5):
    """使用ip.sb获取地理位置（备用）"""
    try:
        url = f"https://api.ip.sb/geoip/{ip}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ip": data.get("ip", ""),
                "country_code": data.get("country_code", ""),
                "country": data.get("country_name") or data.get("country", ""),
                "region": data.get("region", "") or data.get("province", ""),
                "city": data.get("city", ""),
                "organization": data.get("organization", "") or data.get("asn", {}).get("name", ""),
                "asn": data.get("asn", {}).get("as_number", "") if isinstance(data.get("asn"), dict) else "",
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "source": "ipsb"
            }
    except Exception as e:
        pass
    return None

def get_real_location_ping0(ip, timeout=5):
    """使用ping0.cn获取位置信息（备用）"""
    try:
        url = f"https://ping0.cc/api/ip?ip={ip}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data"):
                info = data["data"]
                return {
                    "ip": info.get("ip", ""),
                    "location": info.get("location", ""),
                    "asn": info.get("asnumber", ""),
                    "org": info.get("asorganization", ""),
                    "source": "ping0"
                }
    except Exception as e:
        pass
    return None

def get_country_code_from_location(location_str):
    """从位置字符串中提取国家代码（备用方法）"""
    country_mapping = {
        "美国": "US", "United States": "US",
        "加拿大": "CA", "Canada": "CA",
        "英国": "GB", "United Kingdom": "GB",
        "德国": "DE", "Germany": "DE",
        "法国": "FR", "France": "FR",
        "日本": "JP", "Japan": "JP",
        "韩国": "KR", "South Korea": "KR",
        "新加坡": "SG", "Singapore": "SG",
        "澳大利亚": "AU", "Australia": "AU",
        "巴西": "BR", "Brazil": "BR",
        "印度": "IN", "India": "IN",
        "荷兰": "NL", "Netherlands": "NL",
        "香港": "HK", "Hong Kong": "HK",
        "台湾": "TW", "Taiwan": "TW",
        "俄罗斯": "RU", "Russia": "RU"
    }
    
    for cn_name, code in country_mapping.items():
        if cn_name.lower() in location_str.lower():
            return code
    
    return ""

def calculate_composite_risk_score(ip_info):
    """计算综合风控值（基于多个维度）"""
    risk_score = 0
    risk_factors = []
    
    org = ip_info.get("organization", "").lower() or ip_info.get("as_name", "").lower()
    
    high_risk_keywords = ['proxy', 'vpn', 'cloud', 'hosting', 'data center', 'server']
    medium_risk_keywords = ['digitalocean', 'linode', 'vultr', 'aws', 'google cloud', 'azure', 'oracle', 'alibaba', 'tencent', 'ovh', 'hetzner']
    
    for keyword in high_risk_keywords:
        if keyword in org:
            risk_score += 15
            risk_factors.append(f"高风险组织({keyword})")
    
    for keyword in medium_risk_keywords:
        if keyword in org:
            risk_score += 8
            risk_factors.append(f"云服务商({keyword})")
    
    ra_list = ['AS13335', 'AS209242', 'AS141289', 'AS141642', 'AS141163']
    asn = ip_info.get('asn', '')
    for ra in ra_list:
        if ra == asn:
            risk_score += 25
            risk_factors.append(f"高风险ASN({ra})")
    
    risk_score = min(risk_score, 100)
    
    if not risk_factors:
        risk_factors.append("正常")
    
    return risk_score, risk_factors

def enrich_node_with_real_info(node, timeout=5):
    """为节点添加真实地区和风控值信息（以iping.cc为主数据源）"""
    m = NODE_PATTERN.match(node)
    if not m:
        return node, {}
    
    ip = m.group(1)
    port = m.group(2)
    
    # ========== 核心策略：iping.cc作为主要数据源 ==========
    # 1. 优先使用iping.cc API获取完整信息（位置+风控）
    iping_info = get_risk_score_iping(ip, timeout=timeout+2, max_retries=3)
    
    # 2. 使用IPinfo.io作为备用国家代码验证
    ipinfo_data = get_real_location_ipinfo(ip, timeout)
    
    # 3. 如果iping.cc失败，尝试其他备用API
    if not iping_info:
        ipsb_info = get_real_location_ipsb(ip, timeout)
        ping0_info = get_real_location_ping0(ip, timeout)
        
        if ipsb_info:
            country_code = ipsb_info.get("country_code", "")
            iping_info = {
                "ip": ip,
                "country": ipsb_info.get("country", ""),
                "country_cn": "",
                "region": ipsb_info.get("region", ""),
                "city": ipsb_info.get("city", ""),
                "isp": "",
                "is_proxy": "未知",
                "type": "未知",
                "usage_type": "未知",
                "risk_score": -1,
                "risk_tag": "API失败",
                "asn": "",
                "as_owner": ipsb_info.get("organization", ""),
                "as_type": "",
                "company": ipsb_info.get("organization", ""),
                "source": "ipsb_backup"
            }
        elif ping0_info:
            location = ping0_info.get("location", "")
            country_code = get_country_code_from_location(location)
            iping_info = {
                "ip": ip,
                "country": location.split(' ')[0] if location else "",
                "country_cn": "",
                "region": "",
                "city": "",
                "isp": "",
                "is_proxy": "未知",
                "type": "未知",
                "usage_type": "未知",
                "risk_score": -1,
                "risk_tag": "API失败",
                "asn": ping0_info.get("asn", ""),
                "as_owner": ping0_info.get("org", ""),
                "as_type": "",
                "company": ping0_info.get("org", ""),
                "source": "ping0_backup"
            }
    
    if not iping_info:
        return node, {"error": "无法获取位置信息"}
    
    # ========== 提取信息（优先使用iping.cc的中文数据） ==========
    
    # 地区信息 - 优先中文
    country_cn = iping_info.get("country_cn", "") or iping_info.get("country", "")
    region = iping_info.get("region", "")
    city = iping_info.get("city", "")
    
    # 国家代码（用于备用显示，但最终输出用中文）
    country_code = ipinfo_data.get("country_code", "") if ipinfo_data else ""
    country_en = iping_info.get("country", "") or (ipinfo_data.get("country", "") if ipinfo_data else "")
    
    # 组织信息
    as_name = iping_info.get("as_owner", "") or (ipinfo_data.get("as_name", "") if ipinfo_data else "")
    organization = iping_info.get("company", "") or iping_info.get("isp", "") or as_name
    
    # 风控信息
    risk_score_raw = iping_info.get("risk_score", -1)
    is_proxy = iping_info.get("is_proxy", "未知")
    usage_type = iping_info.get("usage_type", "未知")
    risk_tag = iping_info.get("risk_tag", "")
    
    # 解析风控值
    if isinstance(risk_score_raw, int):
        risk_score = risk_score_raw
    elif isinstance(risk_score_raw, str) and risk_score_raw.isdigit():
        risk_score = int(risk_score_raw)
    else:
        risk_score = -1
    
    # 构建中文地区描述（最终输出格式）
    location_parts = []
    if country_cn:
        location_parts.append(country_cn)
    if region:
        location_parts.append(region)
    if city:
        location_parts.append(city)
    
    location_chinese = " ".join(location_parts) if location_parts else (country_cn or country_en or "未知")
    
    # ========== 综合风控评估（参考iping.cc网站标准） ==========
    base_risk = risk_score if risk_score >= 0 else 50
    
    # 加权调整
    if is_proxy == "是":
        base_risk += 20
    elif is_proxy == "错误的":
        base_risk += 0
        
    if usage_type == "数据中心" or usage_type == "IDC":
        base_risk += 10
        
    if risk_tag and any(keyword in risk_tag for keyword in ["翻墙", "代理", "VPN"]):
        base_risk += 25
    
    adjusted_risk = min(100, max(0, base_risk))
    
    # 纯净度等级判断（与iping.cc网站一致）
    if adjusted_risk <= 20:
        purity_level = "纯净"
    elif adjusted_risk <= 40:
        purity_level = "低风险"
    elif adjusted_risk <= 70:
        purity_level = "中风险"
    else:
        purity_level = "高风险"
    
    # 最终使用的风控值
    final_risk = adjusted_risk if (is_proxy == "是" or usage_type in ["数据中心", "IDC"]) else risk_score
    if final_risk < 0:
        final_risk = adjusted_risk
    
    # 构建详细信息字典
    enriched_info = {
        "ip": ip,
        "port": port,
        "real_location": location_chinese,
        "country_code": country_code,
        "country_en": country_en,
        "country_cn": country_cn,
        "display_country": location_chinese,
        "city": city,
        "region": region,
        "organization": organization,
        "as_name": as_name,
        "risk_score": final_risk,
        "risk_level": purity_level,
        "is_proxy": is_proxy,
        "usage_type": usage_type,
        "source_ipinfo": ipinfo_data.get("source") if ipinfo_data else "",
        "source_ipsb": "",
        "source_iping": iping_info.get("source", "iping_main")
    }
    
    # 新格式：IP:端口#地区中文#纯净度
    new_node = f"{ip}:{port}#{location_chinese}#{final_risk}"
    
    return new_node, enriched_info

def batch_enrich_nodes(nodes, max_workers=150, timeout=5):
    """批量处理节点 - 使用高性能异步并发框架（自动调节50-150并发）"""
    
    manager = AsyncConcurrencyManager(
        min_workers=50,
        max_workers=150,
        initial_workers=min(max_workers, 100),
        success_threshold_high=0.7,
        success_threshold_low=0.3,
        adjust_step=10,
        name="IP检测"
    )
    
    def enrich_worker(node):
        """工作线程：处理单个节点"""
        return enrich_node_with_real_info(node, timeout)
    
    results = manager.execute_batch(
        items=nodes,
        worker_func=enrich_worker,
        timeout=timeout + 2,
        show_progress=True,
        progress_interval=10,
        description="真实地区与风控值检测"
    )
    
    enriched_nodes = []
    nodes_info = {}
    
    for original_node, result in results:
        if result is not None:
            new_node, info = result
            enriched_nodes.append(new_node)
            if info and "error" not in info:
                nodes_info[info["ip"]] = info
        else:
            enriched_nodes.append(original_node)
    
    print(f"成功获取 {len(nodes_info)} 个节点的详细信息\n")
    
    return enriched_nodes, nodes_info

def fetch_ip_list():
    """从配置的数据源获取IP列表"""
    all_nodes = set()
    data_sources = config.get("DATA_SOURCES", [])
    
    enabled_sources = [ds for ds in data_sources if ds.get("enabled", True)]
    
    if not enabled_sources:
        print("⚠ 没有启用的数据源")
        return list(all_nodes)
    
    print(f"\n开始获取IP列表（共 {len(enabled_sources)} 个数据源）...")
    print("=" * 60)
    
    for idx, source in enumerate(enabled_sources, 1):
        url = source.get("url", "")
        name = source.get("name", f"数据源{idx}")
        
        if not url:
            continue
        
        print(f"\n[{idx}/{len(enabled_sources)}] 获取: {name}")
        print(f"  URL: {url}")
        
        max_retries = config.get("FETCH_MAX_RETRIES", 3)
        retry_delay = config.get("FETCH_RETRY_DELAY", 3)
        fetch_timeout = config.get("FETCH_TIMEOUT", 10)
        connect_timeout = config.get("FETCH_CONNECT_TIMEOUT", 5)
        
        nodes_from_source = []
        
        for attempt in range(max_retries):
            try:
                print(f"  尝试 {attempt + 1}/{max_retries}...", end=" ")
                
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })
                
                resp = session.get(url, timeout=(connect_timeout, fetch_timeout), allow_redirects=True)
                resp.raise_for_status()
                
                content = resp.text.strip()
                
                lines = content.split('\n')
                valid_count = 0
                
                for line in lines:
                    result = parse_node_from_line(line)
                    if result:
                        ip, port = result
                        node = f"{ip}:{port}"
                        nodes_from_source.append(node)
                        valid_count += 1
                
                print(f"✓ 成功！获取 {valid_count} 个有效节点")
                break
                
            except requests.exceptions.Timeout:
                print(f"✗ 超时")
                if attempt < max_retries - 1:
                    print(f"  等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
            except requests.exceptions.ConnectionError as e:
                print(f"✗ 连接失败: {str(e)[:50]}")
                if attempt < max_retries - 1:
                    print(f"  等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
            except Exception as e:
                print(f"✗ 错误: {str(e)[:50]}")
                break
        
        if nodes_from_source:
            before_count = len(all_nodes)
            all_nodes.update(nodes_from_source)
            new_count = len(all_nodes) - before_count
            print(f"  新增 {new_count} 个唯一节点（总计: {len(all_nodes)}）")
    
    print("\n" + "=" * 60)
    print(f"✓ IP列表获取完成！共 {len(all_nodes)} 个唯一节点\n")
    
    return list(all_nodes)

def test_tcp_connection(ip, port, timeout=None):
    """测试TCP连接并返回延迟"""
    if timeout is None:
        timeout = config.get("TIMEOUT", 2.5)
    
    socket_timeout = config.get("SOCKET_DEFAULT_TIMEOUT", 3)
    
    start_time = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        result = sock.connect_ex((ip, port))
        
        if result == 0:
            latency_ms = (time.time() - start_time) * 1000
            sock.close()
            return True, latency_ms
        else:
            sock.close()
            return False, None
    except socket.timeout:
        return False, None
    except Exception as e:
        return False, None

def test_tcp_connection_with_retry(ip, port, max_retries=2, timeout=None):
    """带重试机制的TCP连接测试"""
    for attempt in range(max_retries + 1):
        success, latency = test_tcp_connection(ip, port, timeout)
        
        if success:
            return True, latency
        
        # 如果不是最后一次，等待后重试
        if attempt < max_retries:
            time.sleep(0.1)  # 短暂等待100ms
    
    return False, None

def test_availability(ip, port):
    """通过外部API测试IP可用性"""
    api_url = config.get("AVAILABILITY_CHECK_API", "")
    if not api_url:
        return True
    
    try:
        full_url = f"{api_url}?ip={ip}&port={port}"
        resp = requests.get(full_url, 
                          timeout=config.get("AVAILABILITY_TIMEOUT", 3),
                          connect_timeout=config.get("AVAILABILITY_CONNECT_TIMEOUT", 3))
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("available", True)
    except:
        pass
    
    return True

def filter_by_country(nodes):
    """按国家过滤节点"""
    if not config.get("FILTER_COUNTRIES_ENABLED", False):
        return nodes
    
    allowed_countries = config.get("ALLOWED_COUNTRIES", [])
    blocked_countries = config.get("BLOCKED_COUNTRIES", [])
    
    if not allowed_countries and not blocked_countries:
        return nodes
    
    filtered = []
    for node in nodes:
        match = NODE_PATTERN.match(node)
        if match:
            country = match.group(3) if len(match.groups()) > 2 else ""
            
            if allowed_countries and country in allowed_countries:
                filtered.append(node)
            elif blocked_countries and country not in blocked_countries:
                filtered.append(node)
            elif not allowed_countries and country not in blocked_countries:
                filtered.append(node)
    
    return filtered if filtered else nodes

def filter_ipv6_unavailable(nodes):
    """过滤IPv6不可用的节点"""
    if not config.get("FILTER_IPV6_AVAILABILITY", False):
        return nodes
    
    filtered = []
    for node in nodes:
        match = NODE_PATTERN.match(node)
        if match:
            ip = match.group(1)
            if ':' in ip:
                available = test_availability(match.group(1), match.group(2))
                if available:
                    filtered.append(node)
            else:
                filtered.append(node)
    
    return filtered

def probe_tcp_multiple_times(ip, port, probes=None):
    """多次探测TCP连接取最佳延迟"""
    if probes is None:
        probes = config.get("TCP_PROBES", 3)
    
    latencies = []
    
    for _ in range(probes):
        success, latency = test_tcp_connection(ip, port)
        if success and latency is not None:
            latencies.append(latency)
    
    if latencies:
        return min(latencies)
    
    return None

def measure_bandwidth(ip, port, size_mb=None, timeout=None):
    """测量下载带宽"""
    if size_mb is None:
        size_mb = config.get("BANDWIDTH_SIZE_MB", 2.0)
    if timeout is None:
        timeout = config.get("BANDWIDTH_TIMEOUT", 8)
    
    bytes_count = int(size_mb * 1024 * 1024)
    url_template = config.get("BANDWIDTH_URL_TEMPLATE", "https://speed.cloudflare.com/__down?bytes={bytes}")
    url = url_template.format(bytes=bytes_count)
    
    headers = {"Host": "speed.cloudflare.com"}
    
    start_time = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(config.get("BANDWIDTH_CONNECT_TIMEOUT", 5))
        sock.connect((ip, port))
        
        request = f"GET {url} HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode())
        
        total_received = 0
        buffer_size = config.get("BANDWIDTH_PROCESS_BUFFER", 2) * 1024 * 1024
        
        while True:
            chunk = sock.recv(buffer_size)
            if not chunk:
                break
            total_received += len(chunk)
            
            elapsed = time.time() - start_time
            if elapsed > timeout:
                break
        
        sock.close()
        
        elapsed_time = time.time() - start_time
        
        if total_received > 0 and elapsed_time > 0:
            bandwidth_bps = (total_received * 8) / elapsed_time
            bandwidth_mbps = bandwidth_bps / 1000000
            return bandwidth_mbps
        
        return None
        
    except socket.timeout:
        return None
    except Exception as e:
        return None

def select_best_nodes(nodes):
    """选择最优节点（支持全球模式和分国家模式）"""
    use_global_mode = config.get("USE_GLOBAL_MODE", True)
    global_top_n = config.get("GLOBAL_TOP_N", 300)
    per_country_top_n = config.get("PER_COUNTRY_TOP_N", 10)
    min_bandwidth_mbps = config.get("MIN_BANDWIDTH_MBPS", 2.0)
    
    if use_global_mode:
        valid_nodes = [(n, b, l) for n, b, l in nodes if b >= min_bandwidth_mbps]
        valid_nodes.sort(key=lambda x: (-x[1], x[2]))
        return valid_nodes[:global_top_n]
    else:
        from collections import defaultdict
        country_groups = defaultdict(list)
        
        for node, bandwidth, latency in nodes:
            if bandwidth >= min_bandwidth_mbps:
                match = NODE_PATTERN.match(node)
                country = match.group(3) if match and len(match.groups()) > 2 else "Unknown"
                country_groups[country].append((node, bandwidth, latency))
        
        best_nodes = []
        for country in sorted(country_groups.keys()):
            country_nodes = country_groups[country]
            country_nodes.sort(key=lambda x: (-x[1], x[2]))
            best_nodes.extend(country_nodes[:per_country_top_n])
        
        return best_nodes

def format_output_line(node, bandwidth, latency, real_location=""):
    """格式化输出行"""
    match = NODE_PATTERN.match(node)
    if match:
        ip = match.group(1)
        port = match.group(2)
        country = match.group(3) if len(match.groups()) > 2 else ""
        
        if real_location:
            return f"{ip}:{port}:{port} #{country} 风控:{real_location.split('#')[-1] if '#' in real_location else '?'}({real_location.split('#')[0] if '#' in real_location else ''}) 速度 {bandwidth:.2f} Mbps  延迟 {latency:.2f} ms [{real_location}]"
        else:
            return f"{ip}:{port}:{port} #{country} 速度 {bandwidth:.2f} Mbps  延迟 {latency:.2f} ms"
    
    return f"{node} 速度 {bandwidth:.2f} Mbps  延迟 {latency:.2f} ms"

def send_wxpusher_notification(content):
    """发送微信推送通知"""
    if not config.get("ENABLE_WXPUSHER", False):
        return
    
    app_token = config.get("WXPUSHER_APP_TOKEN", "")
    uids = config.get("WXPUSHER_UIDS", [])
    api_url = config.get("WXPUSHER_API_URL", "")
    
    if not app_token or not uids or not api_url:
        return
    
    try:
        payload = {
            "appToken": app_token,
            "content": content,
            "contentType": 1,
            "uids": uids
        }
        
        resp = requests.post(
            api_url,
            json=payload,
            timeout=(
                config.get("NOTIFY_CONNECT_TIMEOUT", 3),
                config.get("NOTIFY_TIMEOUT", 3)
            )
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 1000:
                print("✓ 微信推送通知发送成功")
            else:
                print(f"⚠ 微信推送失败: {data.get('msg')}")
        else:
            print(f"⚠ 微信推送HTTP错误: {resp.status_code}")
            
    except Exception as e:
        print(f"⚠ 微信推送异常: {e}")

def update_cloudflare_dns(best_nodes):
    """更新Cloudflare DNS记录"""
    if not config.get("CF_ENABLED", False):
        return
    
    cf_api_token = config.get("CF_API_TOKEN", "")
    cf_zone_id = config.get("CF_ZONE_ID", "")
    cf_dns_record_name = config.get("CF_DNS_RECORD_NAME", "")
    
    if not all([cf_api_token, cf_zone_id, cf_dns_record_name]):
        print("⚠ Cloudflare配置不完整，跳过DNS更新")
        return
    
    target_count = config.get("DNS_UPDATE_TARGET_COUNT", 15)
    update_nodes = best_nodes[:target_count]
    
    if not update_nodes:
        print("⚠ 没有可用的节点用于更新DNS")
        return
    
    print(f"\n准备更新Cloudflare DNS记录:")
    print(f"  记录名: {cf_dns_record_name}")
    print(f"  目标数量: {target_count}")
    
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json"
    }
    
    existing_records = []
    try:
        list_url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records?name={cf_dns_record_name}&type=A"
        resp = requests.get(list_url, headers=headers, 
                          timeout=(config.get("CF_DNS_CONNECT_TIMEOUT", 3), 
                                  config.get("CF_DNS_READ_TIMEOUT", 3)))
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                existing_records = data.get("result", [])
    except Exception as e:
        print(f"⚠ 获取现有DNS记录失败: {e}")
    
    for idx, (node, bandwidth, latency) in enumerate(update_nodes[:5], 1):
        match = NODE_PATTERN.match(node)
        if not match:
            continue
        
        ip = match.group(1)
        
        record_name_full = f"{cf_dns_record_name}" if idx == 1 else f"{idx}-{cf_dns_record_name}"
        
        print(f"\n[{idx}] 更新DNS: {record_name_full} -> {ip}")
        print(f"    速度: {bandwidth:.2f} Mbps | 延迟: {latency:.2f} ms")
        
        max_retries = config.get("DNS_UPDATE_MAX_RETRIES", 3)
        retry_delay = config.get("DNS_UPDATE_RETRY_DELAY", 3)
        
        for attempt in range(max_retries):
            try:
                existing_record = None
                for record in existing_records:
                    if record.get("name") == record_name_full:
                        existing_record = record
                        break
                
                body = {
                    "type": "A",
                    "name": record_name_full,
                    "content": ip,
                    "ttl": config.get("CF_TTL", 60),
                    "proxied": config.get("CF_PROXIED", False)
                }
                
                if existing_record:
                    update_url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records/{existing_record['id']}"
                    resp = requests.put(update_url, headers=headers, json=body,
                                      timeout=(config.get("CF_DNS_CONNECT_TIMEOUT", 3),
                                              config.get("CF_DNS_READ_TIMEOUT", 3)))
                else:
                    create_url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records"
                    resp = requests.post(create_url, headers=headers, json=body,
                                       timeout=(config.get("CF_DNS_CONNECT_TIMEOUT", 3),
                                               config.get("CF_DNS_READ_TIMEOUT", 3)))
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        print(f"    ✓ DNS更新成功")
                        break
                    else:
                        errors = data.get("errors", [])
                        error_msg = errors[0].get("message", "未知错误") if errors else "未知错误"
                        print(f"    ✗ API错误: {error_msg}")
                else:
                    print(f"    ✗ HTTP错误: {resp.status_code}")
                    
            except Exception as e:
                print(f"    ✗ 异常: {e}")
            
            if attempt < max_retries - 1:
                print(f"    等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)

def sync_to_github(output_file="ip.txt"):
    """同步结果到GitHub仓库"""
    if not os.path.exists(".git"):
        return
    
    max_retries = config.get("GITHUB_SYNC_MAX_RETRIES", 3)
    retry_delay = config.get("GITHUB_SYNC_RETRY_DELAY", 3)
    process_timeout = config.get("GIT_SYNC_PROCESS_TIMEOUT", 180)
    
    for attempt in range(max_retries):
        try:
            print(f"\n同步到GitHub (尝试 {attempt + 1}/{max_retries})...")
            
            result = subprocess.run(
                ["git", "add", output_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            commit_result = subprocess.run(
                ["git", "commit", "-m", f"update: 更新优选IP列表 ({timestamp})"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if commit_result.returncode != 0 and "nothing to commit" in commit_result.stdout:
                print("✓ 无需更新（内容未变化）")
                return
            
            push_result = subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True,
                text=True,
                timeout=process_timeout
            )
            
            if push_result.returncode == 0:
                print("✓ GitHub同步成功")
                return
            else:
                print(f"✗ 推送失败: {push_result.stderr[-200:] if push_result.stderr else '未知错误'}")
                
        except subprocess.TimeoutExpired:
            print(f"✗ Git操作超时 ({process_timeout}秒)")
        except Exception as e:
            print(f"✗ 同步异常: {e}")
        
        if attempt < max_retries - 1:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)

def main():
    """主函数"""
    print("=" * 70)
    print("🌍 Cloudflare IP优选工具 - 增强版")
    print("   支持真实地区检测 | 风控值评估 | 异步并发框架")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    start_time = time.time()
    
    nodes = fetch_ip_list()
    
    if not nodes:
        print("✗ 未获取到任何IP节点，程序退出")
        return
    
    nodes = filter_by_country(nodes)
    nodes = filter_ipv6_unavailable(nodes)
    
    print(f"过滤后剩余 {len(nodes)} 个节点\n")
    
    if not nodes:
        print("✗ 过滤后无可用节点，程序退出")
        return
    
    print("=" * 70)
    print("阶段1: TCP连接测试（初步筛选）")
    print("=" * 70)
    
    tcp_test_results = []
    total_nodes = len(nodes)
    tested = 0
    
    # 优化：降低并发数，增加成功率
    tcp_workers = min(config.get("MAX_WORKERS", 300), 100)  # 最大100并发
    
    print(f"\n开始TCP连接测试（共 {total_nodes} 个节点，并发数: {tcp_workers}）...")
    print("-" * 60)
    
    batch_size = 500
    for i in range(0, total_nodes, batch_size):
        batch = nodes[i:i + batch_size]
        
        with ThreadPoolExecutor(max_workers=tcp_workers) as executor:
            future_to_node = {executor.submit(test_tcp_connection_with_retry, 
                                           NODE_PATTERN.match(n).group(1), 
                                           NODE_PATTERN.match(n).group(2)): n 
                            for n in batch}
            
            for future in as_completed(future_to_node):
                node = future_to_node[future]
                try:
                    success, latency = future.result()
                    if success and latency is not None:
                        tcp_test_results.append((node, latency))
                    
                    tested += 1
                    
                    if tested % config.get("PROGRESS_PRINT_INTERVAL", 1) * 100 == 0 or tested == total_nodes:
                        pct = tested * 100 // total_nodes
                        print(f"  进度: {tested}/{total_nodes} ({pct}%)")
                        
                except Exception as e:
                    tested += 1
    
    print("-" * 60)
    print(f"TCP测试完成！可用节点: {len(tcp_test_results)}/{total_nodes}\n")
    
    # 检测是否为受限环境（GitHub Actions等）
    restricted_environment = False
    if not tcp_test_results:
        success_rate = len(tcp_test_results) / total_nodes if total_nodes > 0 else 0
        
        if success_rate < 0.01:
            print("⚠ TCP连接测试全部失败")
            print(f"  原因可能是：网络限制、端口不通、或超时时间过短\n")
            print("⚙️ 自动切换到【受限环境模式】：")
            print("   ✅ 跳过带宽测试（无法建立TCP连接）")
            print("   ✅ 仅执行地区与纯净度检测（API调用）")
            print("   ✅ 直接输出格式化结果\n")
            
            restricted_environment = True
            
            # 直接使用原始节点，跳过TCP排序和带宽测试
            candidates = [(node, float('inf')) for node in nodes[:config.get("BANDWIDTH_CANDIDATES", 1000)]]
        else:
            print("✗ 所有节点均不可达，程序退出")
            return
    else:
        tcp_test_results.sort(key=lambda x: x[1])
        
        candidates_count = config.get("BANDWIDTH_CANDIDATES", 1000)
        candidates = tcp_test_results[:candidates_count]
        
        print(f"选择前 {len(candidates)} 个节点进行后续处理\n")
    
    if config.get("ENABLE_REAL_LOCATION_DETECT", True) and config.get("ENABLE_RISK_SCORE", True):
        print("=" * 70)
        print("阶段2: 真实地区与风控值检测（异步并发框架）")
        print("=" * 70)
        
        candidate_nodes = [node for node, _ in candidates]
        
        enriched_nodes, nodes_info = batch_enrich_nodes(
            candidate_nodes,
            max_workers=config.get("REAL_LOCATION_WORKERS", 150),
            timeout=config.get("REAL_LOCATION_TIMEOUT", 5)
        )
        
        enriched_dict = {}
        for new_node in enriched_nodes:
            match = NODE_PATTERN.match(new_node)
            if match:
                ip = match.group(1)
                enriched_dict[ip] = new_node
        
        updated_candidates = []
        for node, latency in candidates:
            match = NODE_PATTERN.match(node)
            if match:
                ip = match.group(1)
                if ip in enriched_dict:
                    updated_candidates.append((enriched_dict[ip], latency))
                else:
                    updated_candidates.append((node, latency))
        
        candidates = updated_candidates
        
        print(f"已更新 {len(enriched_dict)} 个节点的真实地区和风控值\n")
    
    # 受限环境模式：跳过带宽测试，直接输出结果
    if restricted_environment:
        print("=" * 70)
        print("📋 受限环境模式 - 直接输出检测结果（跳过带宽测试）")
        print("=" * 70)
        
        best_nodes = candidates[:config.get("GLOBAL_TOP_N", 300)]
        
        output_lines = []
        for idx, (node, _) in enumerate(best_nodes, 1):
            output_lines.append(node)
        
        output_file = config.get("OUTPUT_FILE", "ip.txt")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines) + '\n')
        
        print(f"\n✅ 已完成！共输出 {len(output_lines)} 个节点")
        print(f"   输出文件: {output_file}")
        print(f"   格式: ip:端口#真实地区#纯净度\n")
        
        if output_lines:
            print(f'前10个样本:')
            for i, line in enumerate(output_lines[:10], 1):
                print(f'  [{i}] {line}')
        
        elapsed_time = time.time() - start_time
        print(f"\n⏱️ 总耗时: {elapsed_time:.1f}秒")
        print('=' * 70)
        return
    
    print("=" * 70)
    print("阶段3: 带宽测试（异步并发 + 自动调节）")
    print("=" * 70)
    
    bandwidth_manager = AsyncConcurrencyManager(
        min_workers=config.get("BANDWIDTH_WORKERS_MIN", 50),
        max_workers=config.get("BANDWIDTH_WORKERS_MAX", 150),
        initial_workers=config.get("BANDWIDTH_WORKERS", 100),
        success_threshold_high=0.85,
        success_threshold_low=0.4,
        adjust_step=15,
        name="带宽测试"
    )
    
    def bandwidth_worker(item):
        """带宽测试工作函数"""
        node, latency = item
        match = NODE_PATTERN.match(node)
        if match:
            ip = match.group(1)
            port = match.group(2)
            
            retry_max = config.get("BANDWIDTH_RETRY_MAX", 2)
            retry_delay = config.get("BANDWIDTH_RETRY_DELAY", 3)
            
            for attempt in range(retry_max + 1):
                bandwidth = measure_bandwidth(ip, port)
                
                if bandwidth is not None:
                    return (node, bandwidth, latency)
                
                if attempt < retry_max:
                    time.sleep(retry_delay)
            
            return (node, 0, latency)
        
        return (node, 0, 0)
    
    bw_results = bandwidth_manager.execute_batch(
        items=candidates,
        worker_func=bandwidth_worker,
        timeout=config.get("BANDWIDTH_TIMEOUT", 8) + 2,
        show_progress=True,
        progress_interval=5,
        description="带宽测速"
    )
    
    valid_bw_results = [(n, b, l) for n, r in bw_results if r is not None for n, b, l in [r] if b > 0]
    
    print(f"\n带宽测试完成！有效结果: {len(valid_bw_results)}/{len(candidates)}\n")
    
    if not valid_bw_results:
        print("✗ 所有节点带宽测试失败")
        return
    
    best_nodes = select_best_nodes(valid_bw_results)
    
    print("=" * 70)
    print("最终优选节点（含真实信息）")
    print("=" * 70)
    
    output_lines = []
    for idx, (node, bandwidth, latency) in enumerate(best_nodes, 1):
        match = NODE_PATTERN.match(node)
        real_location = ""
        
        if match:
            ip = match.group(1)
            if ip in nodes_info:
                info = nodes_info[ip]
                real_location = info.get("real_location", "")
        
        line = format_output_line(node, bandwidth, latency, real_location)
        output_lines.append(line)
        print(f"{idx}. {line}")
    
    output_file = config.get("OUTPUT_FILE", "ip.txt")
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in output_lines:
                f.write(line + '\n')
        
        print(f"\n✓ 结果已保存到: {output_file}")
    except Exception as e:
        print(f"\n✗ 保存文件失败: {e}")
    
    notification_content = f"""🌍 Cloudflare IP优选完成
⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📊 测试节点: {total_nodes}
✅ 可用节点: {len(tcp_test_results)}
🏆 优选节点: {len(best_nodes)}
⚡ 最高带宽: {best_nodes[0][1]:.2f} Mbps (如果存在)
📍 最低延迟: {min([l for _, _, l in best_nodes]):.2f} ms (如果存在)"""
    
    send_wxpusher_notification(notification_content)
    
    update_cloudflare_dns(best_nodes)
    
    sync_to_github(output_file)
    
    elapsed_time = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"✓ 全部完成！总耗时: {elapsed_time:.1f}秒")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
