/* request.js — 统一请求封装
 * 功能：
 *   1. 自动携带登录凭证（same-origin Cookie，兼容现有 HttpOnly token Cookie 方案）
 *   2. JS 对象自动 JSON 序列化 + 设置 Content-Type
 *   3. 统一响应解包：后端统一返回 {code, msg, data}
 *      成功(code===0) → 直接返回 data；失败/非2xx → 抛 Error(msg)
 *   4. FormData 文件上传自动识别（不手动设 Content-Type，浏览器自动带 boundary）
 *
 * 用法（调用方拿到的就是 data，不再需要判断 code/ok）：
 *   const rows = await request('/api/state?month=2026-08');  // GET，rows 即 data
 *   const data = await request.get('/api/state?month=2026-08');
 *   const r = await request.post('/api/rows', {...});        // 成功返回 data
 *   await request.put('/api/rows/1', { volume: 3.14 });
 *   await request.del('/api/rows/1');
 *   const up = await request.upload('/api/import', formData);
 *
 * 错误处理：业务失败(code!==0)或 HTTP 非 2xx 都会抛 Error，
 * 调用方用 try/catch 捕获，err.message 即后端 msg。
 */
(function (window) {
  'use strict';

  async function request(url, options) {
    options = options || {};
    var opts = { credentials: 'same-origin' };
    opts.method = (options.method || 'GET').toUpperCase();
    opts.headers = Object.assign({}, options.headers);

    if (options.body !== undefined && !(options.body instanceof FormData)) {
      // 普通对象/数组 → JSON 序列化
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(options.body);
    } else if (options.body !== undefined) {
      // FormData → 直接作为请求体，不手动设 Content-Type
      opts.body = options.body;
    }

    var resp = await fetch(url, opts);
    var data = null;
    try { data = await resp.json(); } catch (e) { /* 非 JSON 响应（如文件下载） */ }

    if (!resp.ok) {
      // HTTP 错误（401/403/400/500 等），消息取后端 msg
      var msg = (data && (data.msg || data.error)) || ('请求失败（HTTP ' + resp.status + '）');
      throw new Error(msg);
    }
    // 统一解包：标准格式 {code, msg, data}
    if (data && typeof data === 'object' && 'code' in data) {
      if (data.code !== 0) {
        throw new Error(data.msg || '操作失败');
      }
      return data.data;
    }
    // 兼容历史裸数据（后端统一后一般不会走到这里）
    return data;
  }

  request.get = function (url) { return request(url); };
  request.post = function (url, body) { return request(url, { method: 'POST', body: body }); };
  request.put = function (url, body) { return request(url, { method: 'PUT', body: body }); };
  request.del = function (url) { return request(url, { method: 'DELETE' }); };
  request.upload = function (url, formData) { return request(url, { method: 'POST', body: formData }); };

  window.request = request;
})(window);
