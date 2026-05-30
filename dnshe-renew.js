const https = require('https');
const http = require('http');

if (process.stdout.isTTY) {
  process.stdout.setDefaultEncoding('utf-8');
}

const CONFIG = {
  API_BASE: 'https://api005.dnshe.com/index.php?m=domain_hub',
  API_KEY: process.env.DNSHE_API_KEY || 'cfsd_8a019a6291a9a882aed40f0142a2bf74',
  API_SECRET: process.env.DNSHE_API_SECRET || 'fd702e1f7a1a9144250cc927722edb5956457f609f444204273583259714fcc8',
  RENEW_THRESHOLD_DAYS: 180,
  MAX_RETRIES: 3,
  RETRY_DELAY: 1000,
};

function log(level, message, data = null) {
  const timestamp = new Date().toISOString();
  const prefix = `[${timestamp}] [${level.toUpperCase()}]`;
  console.log(`${prefix} ${message}`);
  if (data) {
    console.log(JSON.stringify(data, null, 2));
  }
}

function makeRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const headers = {
      'X-API-Key': CONFIG.API_KEY,
      'X-API-Secret': CONFIG.API_SECRET,
      'Content-Type': 'application/json',
      ...options.headers,
    };

    const requestOptions = {
      hostname: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
      path: urlObj.pathname + urlObj.search,
      method: options.method || 'GET',
      headers: headers,
    };

    const reqModule = urlObj.protocol === 'https:' ? https : http;
    const req = reqModule.request(requestOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const jsonData = JSON.parse(data);
          resolve({ status: res.statusCode, data: jsonData });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });

    req.on('error', (error) => {
      reject(error);
    });

    if (options.body) {
      req.write(options.body);
    }

    req.end();
  });
}

async function fetchAllSubdomains() {
  log('info', '正在获取所有子域名列表...');
  
  let allDomains = [];
  let page = 1;
  const perPage = 200;
  let hasMore = true;

  while (hasMore) {
    const url = `${CONFIG.API_BASE}&endpoint=subdomains&action=list&page=${page}&per_page=${perPage}&fields=id,subdomain,rootdomain,full_domain,status,expires_at,never_expires&sort_by=expires_at&sort_dir=asc`;
    
    try {
      log('info', `获取第 ${page} 页数据...`);
      const response = await makeRequest(url);
      
      if (response.status !== 200) {
        throw new Error(`API请求失败，状态码: ${response.status}`);
      }

      const result = response.data;
      
      if (!result.success) {
        throw new Error(`API返回错误: ${result.message || '未知错误'}`);
      }

      if (result.subdomains && result.subdomains.length > 0) {
        allDomains = allDomains.concat(result.subdomains);
        log('info', `第 ${page} 页获取到 ${result.subdomains.length} 个域名`);
      }

      if (result.pagination && result.pagination.has_more) {
        page++;
        hasMore = true;
        // 避免请求过快
        await new Promise(resolve => setTimeout(resolve, 500));
      } else {
        hasMore = false;
      }

    } catch (error) {
      log('error', `获取第 ${page} 页失败:`, error.message);
      throw error;
    }
  }

  log('info', `总共获取到 ${allDomains.length} 个子域名`);
  return allDomains;
}

function calculateDaysUntilExpiry(expiresAt) {
  if (!expiresAt) return Infinity;
  
  const expiryDate = new Date(expiresAt.replace(' ', 'T'));
  const now = new Date();
  const diffTime = expiryDate - now;
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  
  return diffDays;
}

async function renewDomain(subdomainId, domainName) {
  const url = `${CONFIG.API_BASE}&endpoint=subdomains&action=renew`;
  const body = JSON.stringify({ subdomain_id: subdomainId });

  for (let attempt = 1; attempt <= CONFIG.MAX_RETRIES; attempt++) {
    try {
      log('info', `[${attempt}/${CONFIG.MAX_RETRIES}] 正在续期域名: ${domainName} (ID: ${subdomainId})`);
      
      const response = await makeRequest(url, {
        method: 'POST',
        body: body,
      });

      if (response.status === 200 && response.data.success) {
        const result = response.data;
        log('success', `✅ 续期成功: ${domainName}`, {
          域名: result.full_domain || domainName,
          之前过期时间: result.previous_expires_at,
          新的过期时间: result.new_expires_at,
          剩余天数: result.remaining_days,
          扣费金额: result.charged_amount || 0,
          续期时间: result.renewed_at,
        });
        return true;
      } else {
        const errorMsg = response.data?.message || response.data?.error || '未知错误';
        
        if (response.status === 422) {
          log('warning', `⏳ 域名 ${domainName} 尚未进入续期窗口`);
          return false;
        } else if (response.status === 403) {
          log('error', `❌ 域名 ${domainName} 续期失败: ${errorMsg}`);
          return false;
        } else {
          throw new Error(`续期失败 (${response.status}): ${errorMsg}`);
        }
      }
    } catch (error) {
      log('warning', `第 ${attempt} 次尝试失败: ${error.message}`);
      
      if (attempt < CONFIG.MAX_RETRIES) {
        await new Promise(resolve => setTimeout(resolve, CONFIG.RETRY_DELAY * attempt));
      } else {
        log('error', `❌ 域名 ${domainName} 续期失败（已重试${CONFIG.MAX_RETRIES}次）:`, error.message);
        return false;
      }
    }
  }
  
  return false;
}

async function checkAndRenewDomains() {
  const startTime = Date.now();
  
  log('info', '=' .repeat(80));
  log('info', 'DNSHE 域名自动续期脚本启动');
  log('info', '=' .repeat(80));
  log('info', `配置信息:`, {
    续期阈值: `${CONFIG.RENEWAL_THRESHOLD_DAYS} 天`,
    最大重试次数: CONFIG.MAX_RETRIES,
    时间: new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }),
  });

  try {
    const domains = await fetchAllSubdomains();

    if (domains.length === 0) {
      log('warning', '没有找到任何子域名');
      return;
    }

    log('info', '-' .repeat(80));
    log('info', '开始检查域名过期状态...');
    log('info', '-'.repeat(80));

    const needRenewal = [];
    const noExpiryInfo = [];
    const neverExpires = [];
    const safeDomains = [];

    for (const domain of domains) {
      const daysLeft = calculateDaysUntilExpiry(domain.expires_at);
      
      if (domain.never_expires === 1 || daysLeft === Infinity) {
        neverExpires.push({
          domain: domain.full_domain,
          id: domain.id,
          status: domain.status,
        });
      } else if (!domain.expires_at) {
        noExpiryInfo.push({
          domain: domain.full_domain,
          id: domain.id,
          status: domain.status,
        });
      } else if (daysLeft <= CONFIG.RENEWAL_THRESHOLD_DAYS) {
        needRenewal.push({
          ...domain,
          days_left: daysLeft,
          expires_at: domain.expires_at,
        });
      } else {
        safeDomains.push({
          domain: domain.full_domain,
          days_left: daysLeft,
          expires_at: domain.expires_at,
        });
      }
    }

    log('info', '\n📊 域名统计汇总:');
    log('info', `   总计域名数: ${domains.length}`);
    log('info', `   ✅ 安全（>${CONFIG.RENEWAL_THRESHOLD_DAYS}天）: ${safeDomains.length}`);
    log('info', `   ⚠️  需要续期（≤${CONFIG.RENEWAL_THRESHOLD_DAYS}天）: ${needRenewal.length}`);
    log('info', `   ♾️  永不过期: ${neverExpires.length}`);
    log('info', `   ❓ 无过期信息: ${noExpiryInfo.length}`);

    if (safeDomains.length > 0) {
      log('info', `\n✅ 安全域名列表（距离过期 > ${CONFIG.RENEWAL_THRESHOLD_DAYS} 天）:`);
      safeDomains.sort((a, b) => a.days_left - b.days_left).forEach((d, i) => {
        log('info', `   ${i + 1}. ${d.domain} - 剩余 ${d.days_left} 天 (过期: ${d.expires_at})`);
      });
    }

    if (needRenewal.length > 0) {
      log('info', `\n⚠️  需要续期的域名列表（距离过期 ≤ ${CONFIG.RENEWAL_THRESHOLD_DAYS} 天）:`);
      needRenewal.sort((a, b) => a.days_left - b.days_left).forEach((d, i) => {
        const urgency = d.days_left <= 30 ? '🔴 紧急' : d.days_left <= 90 ? '🟠 警告' : '🟡 注意';
        log('info', `   ${i + 1}. ${urgency} ${d.full_domain} - 仅剩 ${d.days_left} 天 (过期: ${d.expires_at})`);
      });

      log('info', `\n🔄 开始执行续期操作...`);
      log('info', '-'.repeat(80));

      let successCount = 0;
      let failCount = 0;
      let skipCount = 0;

      for (const domain of needRenewal) {
        const renewed = await renewDomain(domain.id, domain.full_domain);
        if (renewed) {
          successCount++;
        } else {
          failCount++;
        }
        
        // 避免请求过快
        await new Promise(resolve => setTimeout(resolve, 1000));
      }

      log('info', '\n' + '='.repeat(80));
      log('info', '📈 续期操作统计:');
      log('info', `   ✅ 成功: ${successCount}`);
      log('info', `   ❌ 失败/跳过: ${failCount}`);
      log('info', `   📊 成功率: ${((successCount / needRenewal.length) * 100).toFixed(1)}%`);
    } else {
      log('info', '\n🎉 所有域名都在安全期内，无需续期！');
    }

    if (neverExpires.length > 0) {
      log('info', `\n♾️  永不过期的域名:`);
      neverExpires.forEach(d => {
        log('info', `   • ${d.domain}`);
      });
    }

    if (noExpiryInfo.length > 0) {
      log('info', `\n❓ 无过期信息的域名:`);
      noExpiryInfo.forEach(d => {
        log('info', `   • ${d.domain} (ID: ${d.id})`);
      });
    }

  } catch (error) {
    log('error', '❌ 脚本执行出错:', error.message);
    process.exit(1);
  }

  const endTime = Date.now();
  const duration = ((endTime - startTime) / 1000).toFixed(2);

  log('info', '\n' + '='.repeat(80));
  log('info', `✨ 脚本执行完成！总耗时: ${duration} 秒`);
  log('info', `⏰ 执行时间: ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
  log('info', '='.repeat(80));
}

if (require.main === module) {
  checkAndRenewDomains().catch(error => {
    log('error', '未捕获的错误:', error);
    process.exit(1);
  });
}

module.exports = { checkAndRenewDomains, fetchAllSubdomains, renewDomain };
