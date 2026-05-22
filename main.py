#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP节点检测工具 - 基于原项目架构重构版
核心改进：添加地区和纯净度检测功能
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

# 正则表达式（与原项目一致）
NODE_PATTERN = re.compile(r'^(\d+\.\d+\.\d+\.\d+):(\d+)')

# ========== API函数（简化版）==========

def get_ip_location(ip):
    """获取IP的地理位置信息"""
    # 尝试多个API
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

# ========== 数据获取（支持多数据源）==========

def fetch_all_nodes():
    """从所有数据源获取IP节点列表"""
    all_nodes = set()
    data_sources = config.get("DATA_SOURCES", [])
    
    enabled_sources = [ds for ds in data_sources if ds.get("enabled", True)]
    
    if not enabled_sources:
        print("⚠️ 没有启用的数据源")
        return []
    
    print(f"\n开始从 {len(enabled_sources)} 个数据源获取IP...")
    print("=" * 60)
    
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
                
                resp = requests.get(url, timeout=(5, 10), allow_redirects=True)
                resp.raise_for_status()
                
                lines = resp.text.strip().split('\n')
                count = 0
                
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    match = NODE_PATTERN.match(line)
                    if match:
                        node = f"{match.group(1)}:{match.group(2)}"
                        all_nodes.add(node)
                        count += 1
                
                print(f"✅ 获取 {count} 个节点")
                break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"❌ 失败，重试...")
                    time.sleep(2)
                else:
                    print(f"❌ 最终失败")
    
    print("\n" + "=" * 60)
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
    print("🚀 IP节点检测工具 - 稳定版 v2.0")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 步骤1：获取IP列表
    print("[步骤1] 获取IP节点列表...")
    nodes = fetch_all_nodes()
    
    if not nodes:
        print("❌ 无法获取节点列表")
        return
    
    print(f"✅ 成功获取 {len(nodes)} 个节点\n")
    
    # 步骤2：地区检测
    max_detect = min(config.get("GLOBAL_TOP_N", 300), len(nodes))
    detect_nodes = nodes[:max_detect]
    
    print(f"[步骤2] 检测前 {max_detect} 个节点的地区信息...")
    print("=" * 70)
    print(f"并发数: 30 | 超时: 15秒\n")
    
    enriched = []
    success = 0
    fail = 0
    
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(detect_single_node, node): node for node in detect_nodes}
        
        done = 0
        total = len(futures)
        
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    enriched.append(result)
                    success += 1
                else:
                    fail += 1
            except:
                fail += 1
            
            done += 1
            
            if done % 50 == 0 or done == total:
                pct = done * 100 // total
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                print(f"  进度: {done}/{total} ({pct}%) | 成功: {success} | 失败: {fail} | {rate:.1f}/s")
    
    t1 = time.time() - t0
    rate = success / total * 100 if total > 0 else 0
    
    print(f"\n{'='*70}")
    print(f"✅ 检测完成！耗时 {t1:.1f}秒")
    print(f"   成功率: {success}/{total} ({rate:.1f}%)")
    
    # 步骤3：保存结果
    print(f"\n[步骤3] 保存结果到 ip.txt...")
    
    output_file = config.get("OUTPUT_FILE", "ip.txt")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(enriched) + '\n')
    
    print(f"✅ 已保存 {len(enriched)} 个节点\n")
    
    # 显示样本
    if enriched:
        print("前10个样本:")
        for i, line in enumerate(enriched[:10], 1):
            parts = line.split('#')
            if len(parts) >= 3:
                print(f"  [{i}] {parts[0]:<25s} #{parts[1]} #{parts[2]}")
    
    # 统计
    total_time = time.time() - start_time
    
    print(f"\n{'='*70}")
    print("📊 运行统计")
    print("="*70)
    print(f"  数据源节点: {len(nodes)}")
    print(f"  检测节点数: {max_detect}")
    print(f"  成功检测: {success} ({rate:.1f}%)")
    print(f"  最终输出: {len(enriched)} 个节点")
    print(f"  总耗时: {total_time:.1f}秒")
    print(f"  完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

if __name__ == "__main__":
    main()
