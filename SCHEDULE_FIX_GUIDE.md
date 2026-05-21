# 🚀 GitHub Actions 定时任务不触发 - 完整解决方案

## ❌ 问题诊断

**你的情况：**
- ✅ Push触发工作正常
- ✅ 手动触发工作正常
- ❌ **Schedule定时任务完全不触发**

**根本原因：Fork仓库的GitHub Actions限制**

即使你在Settings中启用了所有Actions选项，**Fork的仓库可能仍然无法使用scheduled triggers**。这是GitHub的安全机制。

---

## 💡 解决方案（按推荐顺序）

### 方案A：外部Cron服务 + GitHub API ⭐⭐⭐（推荐）

#### 原理：
使用外部定时服务（如cron-job.org）每小时调用GitHub API触发workflow

#### 步骤：

**1. 获取GitHub Personal Access Token：**
```
1. 打开 https://github.com/settings/tokens
2. 点击 "Generate new token (classic)"
3. 名称填: "Auto Trigger"
4. 勾选权限: repo (全部)
5. 点击 "Generate token"
6. 复制token（只显示一次！）
```

**2. 配置trigger_workflow.py：**
```python
# 编辑 trigger_workflow.py
GITHUB_TOKEN = "你刚复制的token粘贴到这里"
```

**3. 注册cron-job.org（免费）：**
```
1. 打开 https://cron-job.org/en/create/
2. Title: "CF IP Updater"
3. Execution schedule: Every hour (每小时)
4. URL: 你的执行地址（见下方）
5. 保存并激活
```

**4. 使用方法：**

**手动运行一次测试：**
```bash
python trigger_workflow.py
```

**设置Windows定时任务（自动运行）：**
```bash
# 方法1：双击运行 auto_run.bat（一次性）
auto_run.bat

# 方法2：设置Windows计划任务（推荐）
# 打开"任务计划程序"
# 创建基本任务
# 触发器：每小时
# 操作：启动程序 -> 选择 auto_run.bat
```

**优点：**
- ✅ 100%可靠，不受Fork限制
- ✅ 精确到分钟级
- ✅ 免费且简单

---

### 方案B：使用cron-job.org直接调用 ⭐⭐

如果你不想用Python脚本，可以直接让cron-job.org调用GitHub API：

**URL填写：**
```
https://api.github.com/repos/xiajd-we1/cfnb/actions/workflows/update-ip.yml/dispatches
```

**请求方法：** POST  
**Headers：**
```
Authorization: token YOUR_GITHUB_TOKEN
Content-Type: application/json
Accept: application/vnd.github.v3+json
```

**Body (JSON)：**
```json
{
  "ref": "main"
}
```

---

### 方案C：本地定时任务 + 完整运行 ⭐

如果不想依赖GitHub Actions，直接在本地定时运行main.py：

**创建本地定时任务：**

**Windows任务计划程序：**
```
1. 打开 "任务计划程序"
2. 创建基本任务
3. 名称: "Cloudflare IP Update"
4. 触发器: 每天, 每小时重复
5. 操作: 启动程序
   - 程序: python
   - 参数: d:\工具\cfnb-main\cfnb-main\main.py
   - 起始位置: d:\工具\cfnb-main\cfnb-main\
6. 完成
```

**优点：**
- ✅ 完全本地控制
- ✅ 不依赖任何外部服务
- ❌ 需要电脑保持开机

---

## 🔧 快速开始指南

### 如果你想要最简单的方案（推荐新手）：

**选择方案A + Windows定时任务：**

1. **获取GitHub Token**（5分钟）
   - 访问 https://github.com/settings/tokens
   - 生成新token，勾选repo权限
   - 复制token

2. **配置脚本**（1分钟）
   - 用记事本打开 `trigger_workflow.py`
   - 粘贴你的token
   - 保存

3. **测试运行**（1分钟）
   ```bash
   python trigger_workflow.py
   ```
   - 如果显示 "✅ Workflow triggered successfully!" 说明配置正确

4. **设置自动运行**（2分钟）
   - 双击 `auto_run.bat` 测试
   - 或设置Windows计划任务让它每小时自动运行

5. **完成！** 
   - 现在你的IP列表会每小时自动更新
   - 更新后会自动推送到GitHub
   - 订阅链接会自动更新

---

## 📊 对比表

| 方案 | 可靠性 | 设置难度 | 成本 | 需要开电脑 |
|------|--------|----------|------|-----------|
| A: 外部Cron+API | ⭐⭐⭐⭐⭐ | 简单 | 免费 | ❌ |
| B: cron-job.org | ⭐⭐⭐⭐ | 中等 | 免费 | ❌ |
| C: 本地定时任务 | ⭐⭐⭐⭐⭐ | 最简单 | 免费 | ✅ |

---

## 🆘 故障排除

### trigger_workflow.py报错：

**错误："404 Not Found"**
- 检查REPO_OWNER和REPO_NAME是否正确
- 检查WORKFLOW_ID是否正确（文件名要完全匹配）

**错误："401 Unauthorized"**
- Token无效或过期
- Token没有repo权限
- 重新生成token

**错误："403 Forbidden"**
- 账户被限制
- 检查是否有Actions使用额度

**网络错误：**
- 检查代理设置
- 如果需要代理，修改脚本添加proxies参数

### Windows定时任务不运行：
- 检查任务是否启用
- 检查Python路径是否正确
- 查看任务历史记录中的错误信息

---

## 🎯 最终建议

**对于你的情况，我强烈推荐方案A：**

1. ✅ 不受Fork限制
2. ✅ 100%可靠
3. ✅ 设置简单（10分钟搞定）
4. ✅ 免费使用
5. ✅ 电脑不用一直开着

**按照上面的"快速开始指南"操作即可！**

---

## 📞 需要帮助？

如果遇到问题：
1. 检查token是否正确
2. 手动运行 `python trigger_workflow.py` 测试
3. 查看输出错误信息
4. 根据错误类型参考故障排除部分

祝好运！🚀
