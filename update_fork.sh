#!/bin/bash
# ======================================================
# 一键同步 fork 并安全合并令牌（Linux 最终分发版）
# 前置条件：config.json、git_sync.sh 中已填写真实令牌
# ======================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
cd "$(dirname "$0")"

# 检查 python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误：未检测到 python3，请先安装 Python 3${NC}"
    exit 1
fi

BACKUP_DIR="$HOME/cfnb_token_backup_$(date +%Y%m%d_%H%M%S)"
echo -e "${YELLOW}[1/6] 备份当前令牌文件到 $BACKUP_DIR${NC}"
mkdir -p "$BACKUP_DIR"
cp -f config.json "$BACKUP_DIR/config.json" 2>/dev/null || true
cp -f git_sync.sh "$BACKUP_DIR/git_sync.sh" 2>/dev/null || true
cp -f git_sync.ps1 "$BACKUP_DIR/git_sync.ps1" 2>/dev/null || true
cp -f ip.txt "$BACKUP_DIR/ip.txt" 2>/dev/null || true

# 从备份的 git_sync.sh 中提取 GitHub 信息
if [ ! -f "$BACKUP_DIR/git_sync.sh" ]; then
    echo -e "${RED}错误：未找到 git_sync.sh，请先创建并填写令牌${NC}"
    exit 1
fi

# 使用 Python 精确解析 shell 变量（避免 sed 特殊字符问题）
read -r TOKEN USERNAME REPO BRANCH <<< $(python3 -c "
import re
with open('$BACKUP_DIR/git_sync.sh') as f:
    text = f.read()
token = re.search(r'github_token=\"(.+?)\"', text)
user  = re.search(r'github_username=\"(.+?)\"', text)
repo  = re.search(r'repo_name=\"(.+?)\"', text)
branch= re.search(r'branch=\"(.+?)\"', text)
print(token.group(1) if token else '')
print(user.group(1) if user else '')
print(repo.group(1) if repo else '')
print(branch.group(1) if branch else '')
")

if [ -z "$TOKEN" ] || [ "$TOKEN" = "your_github_personal_access_token_here" ]; then
    echo -e "${RED}错误：git_sync.sh 中的 GitHub Token 仍是占位符，请先填写真实令牌${NC}"
    exit 1
fi

# 如果 branch 是占位符，自动探测远程默认分支
if [ -z "$BRANCH" ] || [ "$BRANCH" = "your_branch" ]; then
    echo -e "${YELLOW}分支名为占位符，尝试自动探测远程默认分支...${NC}"
    git remote set-url origin "https://${TOKEN}@github.com/${USERNAME}/${REPO}.git" 2>/dev/null || true
    BRANCH=$(git remote show origin | grep "HEAD branch" | cut -d " " -f5)
    if [ -z "$BRANCH" ]; then
        echo -e "${RED}无法自动探测分支，请手动在 git_sync.sh 中设置 branch=\"main\"${NC}"
        exit 1
    fi
    echo -e "已探测到默认分支：$BRANCH"
fi

echo -e "${YELLOW}[2/6] 设置免认证远程地址${NC}"
git remote set-url origin "https://${TOKEN}@github.com/${USERNAME}/${REPO}.git"

echo -e "${YELLOW}[3/6] 拉取远程并强制对齐${NC}"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

echo -e "${YELLOW}[4/6] 注入令牌到 config.json${NC}"
python3 << 'PYEOF'
import sys, json
from pathlib import Path

backup_dir = Path.home() / "cfnb_token_backup_"  # 可能不够精确，改用传参方式
sys.exit(1)  # 不采用此方式，改用以下方案
PYEOF

# 使用 Python 精准合并（传入备份目录）
python3 - "$BACKUP_DIR" << 'PYEOF'
import sys, json
from pathlib import Path

backup_dir = Path(sys.argv[1])
config_backup = backup_dir / "config.json"
config_current = Path("config.json")

if config_backup.exists() and config_current.exists():
    with open(config_backup) as f:
        backup = json.load(f)
    with open(config_current) as f:
        current = json.load(f)

    # 只替换这些敏感字段
    token_fields = [
        "WXPUSHER_APP_TOKEN", "WXPUSHER_UIDS",
        "CF_API_TOKEN", "CF_ZONE_ID", "CF_DNS_RECORD_NAME"
    ]
    for key in token_fields:
        if key in backup and key in current:
            current[key] = backup[key]

    with open(config_current, 'w') as f:
        json.dump(current, f, indent=4, ensure_ascii=False)
    print("config.json 令牌注入完成")
else:
    print("config.json 备份或当前文件缺失，跳过注入")
PYEOF

echo -e "${YELLOW}[5/6] 更新 git_sync.sh（含 --allow-unrelated-histories）${NC}"
python3 - "$BACKUP_DIR" "$TOKEN" "$USERNAME" "$REPO" "$BRANCH" << 'PYEOF'
import sys, re
from pathlib import Path

backup_dir = Path(sys.argv[1])
token, username, repo, branch = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]

sync_file = Path("git_sync.sh")
if sync_file.exists():
    content = sync_file.read_text()
    # 替换四个变量
    content = re.sub(r'github_token=".*?"', f'github_token="{token}"', content)
    content = re.sub(r'github_username=".*?"', f'github_username="{username}"', content)
    content = re.sub(r'repo_name=".*?"', f'repo_name="{repo}"', content)
    content = re.sub(r'branch=".*?"', f'branch="{branch}"', content)
    # 添加历史不相关兼容（如果还没加）
    if 'allow-unrelated-histories' not in content:
        content = content.replace(
            'git pull origin "$branch"',
            'git pull origin "$branch" --allow-unrelated-histories'
        )
    sync_file.write_text(content)
    sync_file.chmod(0o755)
    print("git_sync.sh 已更新")
else:
    print("git_sync.sh 不存在，跳过")
PYEOF

echo -e "${YELLOW}[6/6] 恢复 ip.txt${NC}"
if [ -f "$BACKUP_DIR/ip.txt" ]; then
    cp -f "$BACKUP_DIR/ip.txt" ip.txt
    echo "ip.txt 已恢复"
fi

echo -e "${GREEN}========================================"
echo -e " ✅ 一键更新完成！"
echo -e "========================================${NC}"
echo -e "备份保留在：$BACKUP_DIR"
echo -e "可运行 python3 main.py 测试"