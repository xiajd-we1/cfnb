# Cloudflare IP 优选工具 - 配置说明

## 📁 config.json 配置指南

### 🎯 DATA_SOURCES 数据源配置

**位置**: `config.json` → `DATA_SOURCES` 数组

#### ✅ 标准格式（每个数据源对象）

```json
{
    "url": "数据源的完整URL",
    "enabled": true,
    "name": "数据源显示名称"
}
```

#### 📝 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | ✅ | 数据源的完整URL地址 |
| `enabled` | boolean | ❌ | 是否启用（默认true） |
| `name` | string | ❌ | 日志中显示的名称 |

---

### 🔧 如何添加新数据源

#### 步骤1: 打开配置文件

```bash
notepad config.json
```

#### 步骤2: 找到 DATA_SOURCES 数组

搜索关键字：`"DATA_SOURCES": [`

#### 步骤3: 在数组末尾添加新数据源

**格式示例**:

```json
{
    "USE_GLOBAL_MODE": true,
    "GLOBAL_TOP_N": 300,
    
    "DATA_SOURCES": [
        {
            "url": "https://example.com/source1.txt",
            "enabled": true,
            "name": "数据源1"
        },
        
        {
            "url": "https://example.com/source2.csv",
            "enabled": true,
            "name": "数据源2"
        },
        
        {
            "url": "https://raw.githubusercontent.com/用户名/仓库名/main/文件.txt",
            "enabled": true,
            "name": "github-source"
        }
    ]
}
```

#### ⚠️ 注意事项

1. **逗号分隔**: 每个数据源对象之间用 `,` 分隔
2. **最后一个元素**: 数组最后一个元素后面**不要加逗号**
3. **URL有效性**: 确保URL可以直接访问，返回文本内容
4. **启用控制**: 设置 `"enabled": false` 可临时禁用某数据源

---

### 📊 支持的数据源格式

程序自动识别以下 **5种格式**：

#### 格式1: 完整标准格式（推荐）
```
104.16.132.229:443#US
```
- 包含IP、端口、国家代码

#### 格式2: IP+端口
```
104.16.132.229:443
```
- 自动补充默认国家代码 `#US`

#### 格式3: 纯IP地址
```
104.16.132.229
```
- 自动补充默认端口 `:443` 和国家 `#US`

#### 格式4: CSV格式（逗号分隔）
```csv
IP,cf-meta-ip,端口,速度(Mbps),CF归属国,机房,...
40.233.68.138,40.233.68.138,443,165.68,CA,YYZ,30.16,40.88
```
- 自动跳过表头行
- 提取第1列(IP)、第3列(端口)、第5列(国家)

#### 格式5: 注释和空行
```
# 这是注释行，会被自动跳过

104.16.132.229:443#US

# 另一个注释
```

---

### 💡 实际案例

#### 案例1: 添加GitHub上的CSV文件

```json
{
    "url": "https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv",
    "enabled": true,
    "name": "xgonce-cloudflare-csv"
}
```

#### 案例2: 添加普通TXT文件

```json
{
    "url": "https://your-domain.com/cloudflare-ips.txt",
    "enabled": true,
    "name": "custom-ip-list"
}
```

#### 案例3: 临时禁用某个数据源

```json
{
    "url": "https://example.com/slow-source.txt",
    "enabled": false,
    "name": "slow-source"
}
```

---

### 🔍 验证添加成功

运行程序后查看日志：

```bash
python main.py
```

**预期输出**:
```
开始从 N 个数据源获取节点...
==================================================
  正在获取 [主数据源] ... [OK] XXX 个节点
  正在获取 [你新增的名称] ... [OK] XXX 个节点  ← 新增的数据源
==================================================
总计获取 XXXX 个唯一节点  ← 总数应该增加
```

---

### 🎨 当前已配置的数据源列表

| 序号 | 名称 | URL类型 | 状态 |
|------|------|--------|------|
| 1 | 主数据源 | TXT | ✅ 启用 |
| 2 | xxzh72-best-domain | TXT | ✅ 启用 |
| 3 | xxzh72-ip | TXT | ✅ 启用 |
| 4 | xxzh72-proxyip | TXT | ✅ 启用 |
| 5 | AiLee77-ip | TXT | ✅ 启用 |
| 6 | KafeMars-CF-A | TXT | ✅ 启用 |
| 7 | KafeMars-CF-B | TXT | ✅ 启用 |
| 8 | KafeMars-cf-bestips | TXT | ✅ 启用 |
| 9 | KafeMars-HK_IP4 | TXT | ✅ 启用 |
| 10 | chris202010-ip | TXT | ✅ 启用 |
| 11 | chris202010-proxyip | TXT | ✅ 启用 |
| 12 | xgonce-result-csv | **CSV** | ✅ 启用 |
| 13 | Wwuyi123-proxyip | TXT | ✅ 启用 |
| 14 | Wwuyi123-proxyip-country | TXT | ✅ 启用 |
| 15 | hofccyf-sg | TXT | ✅ 启用 |

---

### ⚡ 性能优化建议

1. **数据源数量**: 建议控制在 10-20 个以内
2. **禁用无效源**: 定期检查并禁用失效的数据源
3. **优先级**: 将高质量数据源放在数组前面
4. **监控质量**: 观察每个数据源提供的有效节点数量

---

### 🛠️ 故障排查

#### 问题: 某个数据源获取失败

**检查项**:
- [ ] URL是否正确且可访问
- [ ] 网络连接是否正常
- [ ] 是否被防火墙拦截
- [ ] URL是否需要认证

**解决方案**:
1. 在浏览器中测试URL是否可访问
2. 临时设置 `"enabled": false` 排查问题
3. 检查URL是否使用HTTPS

---

## 📞 技术支持

如遇问题，请检查：
1. JSON格式是否正确（可用在线JSON验证器）
2. 所有字段拼写是否正确
3. 逗号和括号是否匹配完整

---

**最后更新**: 2026-05-21
**版本**: v2.0 (优化版)
