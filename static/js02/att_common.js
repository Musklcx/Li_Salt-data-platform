/* =========================================================
   公共脚本: 与后端 form 接口对接的提交工具
   后端仍是传统 form POST + redirect, 这里只是把 Vue 里的数据
   打包成同样的 application/x-www-form-urlencoded / multipart 请求,
   提交后跟随服务端 redirect, 确保原有业务逻辑一行都不用改。
   ========================================================= */
(function (global) {
  'use strict';

  function buildFormData(data) {
    var fd = new FormData();
    Object.keys(data).forEach(function (k) {
      var v = data[k];
      if (v === undefined || v === null) return;
      if (Array.isArray(v)) {
        v.forEach(function (item) { if (item !== undefined && item !== null) fd.append(k, item); });
      } else if (v instanceof File || v instanceof Blob) {
        fd.append(k, v);
      } else {
        fd.append(k, v);
      }
    });
    return fd;
  }

  var AppUtil = {
    /** POST 后跟随服务端重定向(保留后端 redirect 逻辑与锚点) */
    post: function (url, data) {
      return fetch(url, {
        method: 'POST',
        body: buildFormData(data || {}),
        credentials: 'same-origin'
      }).then(function (res) {
        if (!res.ok) {
          /* 后端用 409 返回中文原因(如月结锁定), 直接透出给用户 */
          return res.text().then(function (t) {
            throw new Error((t || '').trim().slice(0, 200) || ('提交失败 (HTTP ' + res.status + ')'));
          });
        }
        window.location.href = res.url || window.location.href;
        return res;
      });
    },

    /** 保留当前路径, 只改 year/month 参数 */
    monthUrl: function (y, m) {
      var p = new URLSearchParams(window.location.search);
      p.set('year', y);
      p.set('month', m);
      return window.location.pathname + '?' + p.toString();
    },

    pad: function (n) { return n < 10 ? '0' + n : '' + n; }
  };

  /** 所有页面 Vue 实例共用的方法 */
  var AppMixin = {
    methods: {
      submitPost: function (url, data) {
        var self = this;
        return AppUtil.post(url, data).catch(function (e) {
          self.$message.error(e.message || '提交失败');
        });
      },
      confirmPost: function (url, data, text, title) {
        var self = this;
        return this.$confirm(text, title || '请确认', {
          type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消'
        }).then(function () {
          return AppUtil.post(url, data);
        }).catch(function (e) {
          if (e === 'cancel' || e === 'close') return;
          self.$message.error(e.message || '操作失败');
        });
      }
    }
  };

  global.AppUtil = AppUtil;
  global.AppMixin = AppMixin;
})(window);
