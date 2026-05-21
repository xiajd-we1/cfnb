#!/usr/bin/env python3
"""
GitHub 推送工具
专门用于将结果文件推送到 GitHub
支持系统代理配置
"""

import os
import sys
import subprocess
import time
from datetime import datetime

def set_git_proxy(proxy_host="127.0.0.1", proxy_port="10100"):
    """设置 Git 代理"""
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    
    print(f"[INFO] 正在配置 Git 代理: {proxy_url}")
    
    subprocess.run(
        ["git", "config", "--global", "http.proxy", proxy_url],
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "--global", "https.proxy", proxy_url],
        capture_output=True
    )
    
    print(f"[OK] Git 代理配置完成")

def unset_git_proxy():
    """取消 Git 代理设置"""
    print("[INFO] 正在取消 Git 代理设置...")
    
    subprocess.run(
        ["git", "config", "--global", "--unset", "http.proxy"],
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "--global", "--unset", "https.proxy"],
        capture_output=True
    )
    
    print("[OK] Git 代理已取消")

def run_git_command(cmd, check=True):
    """执行 git 命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        if check and result.returncode != 0:
            return False, result.stderr or result.stdout
        
        return True, result.stdout
    except Exception as e:
        return False, str(e)

def push_to_github(file_path="ip.txt", commit_msg=None, max_retries=3, retry_delay=5, use_proxy=True, proxy_host="127.0.0.1", proxy_port="10100"):
    """推送文件到 GitHub"""
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    if not os.path.exists(file_path):
        print(f"[ERROR] 文件 {file_path} 不存在")
        return False
    
    if commit_msg is None:
        commit_msg = f"Update IP list - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    print("=" * 60)
    print("GitHub 推送工具")
    print("=" * 60)
    print(f"文件: {file_path}")
    print(f"提交信息: {commit_msg}")
    print(f"最大重试次数: {max_retries}")
    print(f"使用代理: {'是' if use_proxy else '否'}")
    if use_proxy:
        print(f"代理地址: {proxy_host}:{proxy_port}")
    print()
    
    if use_proxy:
        set_git_proxy(proxy_host, proxy_port)
        print()
    
    try:
        for attempt in range(1, max_retries + 1):
            print(f"[尝试 {attempt}/{max_retries}]")
            
            success, output = run_git_command(["git", "status", "--porcelain", file_path], check=False)
            if not success:
                print(f"[ERROR] Git 状态检查失败: {output}")
                time.sleep(retry_delay)
                continue
            
            if not output.strip():
                print(f"[OK] 文件 {file_path} 没有更改，无需推送")
                return True
            
            print("  [1/4] 检查文件更改... 有更改")
            
            success, output = run_git_command(["git", "add", file_path], check=False)
            if not success:
                print(f"[ERROR] Git add 失败: {output}")
                time.sleep(retry_delay)
                continue
            print("  [2/4] 添加文件到暂存区... 完成")
            
            success, output = run_git_command(
                ["git", "commit", "-m", commit_msg],
                check=False
            )
            if not success:
                if "nothing to commit" in output or "nothing to commit" in output.lower():
                    print(f"[OK] 没有需要提交的内容")
                    return True
                print(f"[ERROR] Git commit 失败: {output}")
                time.sleep(retry_delay)
                continue
            print("  [3/4] 提交更改... 完成")
            
            success, output = run_git_command(["git", "push", "origin", "HEAD"], check=False)
            if success:
                print("  [4/4] 推送到 GitHub... 完成")
                print()
                print("=" * 60)
                print("[SUCCESS] 推送成功！")
                print("=" * 60)
                return True
            else:
                if "Everything up-to-date" in output:
                    print("  [4/4] 推送到 GitHub... 已是最新")
                    print()
                    print("=" * 60)
                    print("[OK] 仓库已是最新状态")
                    print("=" * 60)
                    return True
                
                print(f"[ERROR] Git push 失败: {output}")
                
                if attempt < max_retries:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
        
        print()
        print("=" * 60)
        print("[FAILED] 推送失败")
        print("=" * 60)
        print()
        print("请手动执行以下命令进行推送：")
        print()
        print(f"  python push_to_github.py {file_path}")
        print()
        print("或者手动执行 Git 命令：")
        print()
        print(f"  git add {file_path}")
        print(f'  git commit -m "{commit_msg}"')
        print("  git push origin HEAD")
        print()
        
        return False
    finally:
        if use_proxy:
            print()
            unset_git_proxy()

def main():
    file_path = "ip.txt"
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    commit_msg = None
    if len(sys.argv) > 2:
        commit_msg = sys.argv[2]
    
    max_retries = 3
    if len(sys.argv) > 3:
        try:
            max_retries = int(sys.argv[3])
        except:
            pass
    
    use_proxy = True
    proxy_host = "127.0.0.1"
    proxy_port = "10100"
    
    if len(sys.argv) > 4:
        use_proxy = sys.argv[4].lower() in ['true', '1', 'yes', 'y']
    
    if len(sys.argv) > 5:
        proxy_host = sys.argv[5]
    
    if len(sys.argv) > 6:
        proxy_port = sys.argv[6]
    
    success = push_to_github(
        file_path=file_path,
        commit_msg=commit_msg,
        max_retries=max_retries,
        use_proxy=use_proxy,
        proxy_host=proxy_host,
        proxy_port=proxy_port
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
