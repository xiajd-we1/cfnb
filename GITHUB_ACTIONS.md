# GitHub Actions 自动更新使用说明

## 功能介绍

本项目已配置 GitHub Actions 自动化工作流，可以实现：

- ✅ **定时自动运行**：每6小时自动更新一次IP列表
- ✅ **手动触发**：随时可以在GitHub页面手动触发更新
- ✅ **自动推送**：更新完成后自动提交并推送到GitHub
- ✅ **无需本地运行**：完全在GitHub云端运行，本地只需更新订阅

## 使用方法

### 1. 启用 GitHub Actions

1. 打开你的 GitHub 仓库页面
2. 点击 **Actions** 标签
3. 如果看到提示，点击 **I understand my workflows, go ahead and enable them**
4. 确认工作流已启用

### 2. 配置必要的环境变量（可选）

如果你的项目需要特殊配置，可以在仓库设置中添加 Secrets：

1. 进入仓库 **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**
3. 添加需要的密钥（如 Cloudflare API Token 等）

### 3. 手动触发更新

1. 进入 **Actions** 标签
2. 选择 **Update Cloudflare IP** 工作流
3. 点击 **Run workflow** 按钮
4. 选择分支（默认 master）
5. 点击绿色的 **Run workflow** 按钮

### 4. 查看运行结果

1. 在 **Actions** 标签下可以看到所有运行记录
2. 点击具体的运行记录查看详细日志
3. 运行成功后，ip.txt 文件会自动更新

## 工作流配置说明

### 定时任务

当前配置为每6小时运行一次：

```yaml
schedule:
  - cron: '0 */6 * * *'
```

你可以修改 `.github/workflows/update-ip.yml` 文件来调整运行频率：

- `0 */6 * * *` - 每6小时运行一次
- `0 */4 * * *` - 每4小时运行一次
- `0 */12 * * *` - 每12小时运行一次
- `0 0 * * *` - 每天凌晨运行一次

### 触发条件

工作流会在以下情况下运行：

1. **定时触发**：按照 cron 表达式定时运行
2. **手动触发**：通过 GitHub Actions 页面手动运行
3. **代码推送**：当推送代码到 master 分支时（排除 ip.txt 和文档文件）

### 运行环境

- 操作系统：Ubuntu Latest
- Python 版本：3.11
- 必要依赖：requests、curl

## 本地使用

### 方式1：使用 GitHub Actions（推荐）

1. Fork 本项目到你的 GitHub
2. 启用 GitHub Actions
3. 等待自动运行或手动触发
4. 更新你的订阅地址为：`https://raw.githubusercontent.com/你的用户名/cfnb/master/ip.txt`

### 方式2：本地运行

```bash
# 克隆项目
git clone https://github.com/你的用户名/cfnb.git
cd cfnb

# 安装依赖
pip install requests

# 运行脚本
python main.py

# 手动推送（如果自动推送失败）
python push_to_github.py
```

## 注意事项

### 1. GitHub Actions 权限

确保你的仓库设置中 Actions 有写入权限：

1. 进入 **Settings** → **Actions** → **General**
2. 在 **Workflow permissions** 中选择 **Read and write permissions**
3. 保存设置

### 2. 文件更改检测

工作流会自动检测 ip.txt 是否有更改：

- 有更改：自动提交并推送
- 无更改：跳过提交步骤

### 3. 运行时间

每次运行大约需要 10-30 分钟，具体时间取决于：

- 数据源响应速度
- 网络状况
- 候选节点数量

### 4. 失败处理

如果工作流运行失败：

1. 查看 Actions 日志了解失败原因
2. 检查配置是否正确
3. 可以手动触发重新运行
4. 或者本地运行 `python main.py` 并使用 `python push_to_github.py` 推送

## 高级配置

### 自定义运行参数

你可以修改 `.github/workflows/update-ip.yml` 文件来自定义运行参数：

```yaml
- name: Run IP update script
  run: |
    python main.py
  env:
    PYTHONIOENCODING: utf-8
    # 添加自定义环境变量
    # CUSTOM_VAR: "custom_value"
```

### 添加通知功能

可以在工作流中添加通知步骤，例如发送到 Telegram、钉钉等：

```yaml
- name: Send notification
  if: always()
  run: |
    # 添加你的通知脚本
    curl -X POST "你的通知webhook地址" \
      -d "text=IP更新完成"
```

## 常见问题

### Q: 为什么工作流没有运行？

A: 检查以下几点：
1. GitHub Actions 是否已启用
2. 仓库是否有写入权限
3. 工作流文件是否正确

### Q: 如何修改运行频率？

A: 编辑 `.github/workflows/update-ip.yml` 文件中的 cron 表达式。

### Q: 如何查看运行日志？

A: 进入 Actions 标签，点击具体的运行记录即可查看详细日志。

### Q: 本地运行和 GitHub Actions 有什么区别？

A: 
- **本地运行**：需要手动执行，适合调试和测试
- **GitHub Actions**：自动定时运行，适合生产环境使用

## 技术支持

如有问题，请：

1. 查看 Actions 运行日志
2. 检查配置文件
3. 提交 Issue 寻求帮助
