#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions curl诊断脚本 - 直接在Actions环境中测试
"""

import subprocess
import shutil
import time
import sys

def run_cmd(cmd, timeout=15):
    """执行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip()
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def main():
    print("=" * 70)
    print("🔬 GitHub Actions Curl环境诊断")
    print("=" * 70)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"系统: {sys.platform}\n")

    # ====== 1. 检查curl是否存在 ======
    print("[1/5] 检查curl...")
    curl_path = shutil.which('curl')
    if curl_path:
        print(f"✅ curl已安装: {curl_path}")

        # 获取版本
        ver_result = run_cmd("curl --version")
        if ver_result['success']:
            version_line = ver_result['stdout'].split('\n')[0]
            print(f"   版本: {version_line}")
    else:
        print("❌ curl未安装！")
        return

    # ====== 2. 基础连接测试（不使用--resolve）======
    print("\n[2/5] 基础连接测试（直接连接Cloudflare）...")

    test_urls = [
        "https://speed.cloudflare.com/__down?bytes=1024",  # 1KB文件
    ]

    for url in test_urls:
        print(f"\n   测试URL: {url[:50]}...")
        result = run_cmd(
            f'curl -s -o /dev/null -w "%{{http_code}} %{{time_total}} %{{size_download}}" --connect-timeout 5 --max-time 10 "{url}"',
            timeout=12
        )
        
        if result['success'] and result['stdout']:
            parts = result['stdout'].split()
            if len(parts) >= 3:
                http_code, time_total, size = parts[0], parts[1], parts[2]
                print(f"   ✅ HTTP {http_code} | 耗时:{time_total}s | 大小:{size}B")
            else:
                print(f"   ⚠️ 输出异常: {result['stdout']}")
        else:
            error_msg = result.get('error', '') or result.get('stderr', '')[:100]
            print(f"   ❌ 失败: {error_msg}")

    # ====== 3. 使用--resolve的连接测试（关键！）======
    print("\n[3/5] --resolve连接测试（这是main.py使用的方式）...")

    test_ips = [
        ("104.17.210.72", 443),
        ("162.159.44.181", 443),
    ]

    for ip, port in test_ips:
        print(f"\n   测试IP: {ip}:{port}...")

        # 测试1KB文件
        cmd = f'''curl -v -o /dev/null -w "\\n---STATS---\\nhttp:%{{http_code}}\\ntime:%{{time_total}}\\nsize:%{{size_download}}" \\
            --resolve "speed.cloudflare.com:{port}:{ip}" \\
            --connect-timeout 5 --max-time 10 \\
            --insecure \\
            "https://speed.cloudflare.com/__down?bytes=1024"'''

        result = run_cmd(cmd, timeout=12)

        # 输出详细信息
        if result['stderr']:
            stderr_lines = result['stderr'].split('\\n')
            key_info = [l for l in stderr_lines if any(k in l.lower() for k in 
                        ['connect', 'resolve', 'ssl', 'error', 'failed', 'try', '*'])]
            if key_info:
                print(f"   📋 连接详情:")
                for line in key_info[-10:]:
                    print(f"      {line.strip()}")

        if result['success']:
            if "---STATS---" in result['stdout']:
                stats = result['stdout'].split("---STATS---")[1]
                print(f"   ✅ 成功! {stats.replace(chr(10), ' | ')}")
            else:
                print(f"   ⚠️ 无统计信息")
        else:
            error = result.get('stderr', '') or result.get('error', '')
            print(f"   ❌ 失败 (code={result.get('returncode','?')})")
            print(f"      错误: {error[:150]}")

    # ====== 4. DNS解析测试 ======
    print("\n[4/5] DNS解析测试...")
    
    dns_test_ips = ["speed.cloudflare.com", "api.iping.cc", "cloudflare.com"]
    
    for domain in dns_test_ips:
        result = run_cmd(f'nslookup {domain}', timeout=5)
        if result['success'] and result['stdout']:
            lines = [l for l in result['stdout'].split('\n') if 'Address:' in l]
            if lines:
                ips_found = [l.split(':')[1].strip() for l in lines[1:] if ':' in l]
                if ips_found:
                    print(f"   ✅ {domain} → {ips_found[0]}")
                    continue
        print(f"   ⚠️ {domain} 解析失败")

    # ====== 5. 网络出口IP测试 ======
    print("\n[5/5] 网络环境检测...")
    
    # 获取公网IP
    ip_result = run_cmd('curl -s --max-time 5 https://ifconfig.me', timeout=7)
    if ip_result['success'] and ip_result['stdout']:
        print(f"   公网IP: {ip_result['stdout']}")

    # 测试到Cloudflare的连通性
    ping_result = run_cmd('ping -c 2 -W 3 speed.cloudflare.com', timeout=8)
    if ping_result['success']:
        for line in ping_result['stdout'].split('\n'):
            if 'time=' in line.lower() or 'packet loss' in line.lower():
                print(f"   Ping: {line.strip()}")

    # ====== 总结 ======
    print("\n" + "=" * 70)
    print("📊 诊断总结")
    print("=" * 70)
    print("""
如果以上测试显示：
├─ 步骤2成功，步骤3失败 → --resolve参数在GitHub Actions受限
├─ DNS解析正常 → 网络本身没问题
├─ 所有都失败 → GitHub Actions网络策略限制出站HTTPS
└─ 部分成功 → IP白名单或地域限制

建议方案：
1. 如果--resolve不可用 → 改用Python requests库下载测速
2. 如果完全无法访问Cloudflare → 禁用带宽测试，仅用TCP延迟排序
3. 如果部分可用 → 减少并发和超时时间
""")

if __name__ == "__main__":
    main()
