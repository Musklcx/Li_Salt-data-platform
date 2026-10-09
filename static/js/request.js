/* request.js — 统一请求封装
 * 功能：
 *   1. 自动携带登录凭证（same-origin Cookie，兼容现有 HttpOnly token Cookie 方案）
 *   2. JS 对象自动 JSON 序列化 + 设置 Content-Type
 *   3. 统一错误处理：非 2xx 抛 Error（消息取自后端 msg / error 字段）
 *   4. FormData 文件上传自动识别（不手动设 Content-Type，浏览器自动带 boundary）
 *
 * 用法：
 *   const data = await request('/api/state?month=2026-08');   // GET
 *   const data = await request.get('/api/state?month=2026-08');
 *   await request.post('/api/rows', { equip_no: 'A01' });     // POST JSON
 *   await request.put('/api/rows/1', { volume: 3.14 });       // PUT JSON
 *   await request.del('/api/rows/1');                          // DELETE
 *   await request.upload('/api/import', formData);             // POST 文件上传
 *
 * 返回：解析后的 JSON 对象（原样返回后端 data 内容）
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
      var msg = (data && (data.msg || data.error)) || ('请求失败（HTTP ' + resp.status + '）');
      throw new Error(msg);
    }
    return data;
  }

  request.get = function (url) { return request(url); };
  request.post = function (url, body) { return request(url, { method: 'POST', body: body }); };
  request.put = function (url, body) { return request(url, { method: 'PUT', body: body }); };
  request.del = function (url) { return request(url, { method: 'DELETE' }); };
  request.upload = function (url, formData) { return request(url, { method: 'POST', body: formData }); };

  window.request = request;
})(window);
