/* 导航角色守卫：非管理员访问「期末金属量」时置灰菜单并弹窗提示，不跳转 */
(function () {
  var links = document.querySelectorAll('a[href="/inventory"]');
  if (!links.length) return;

  request.get('/api/me')
    .then(function (j) {
      // 管理员正常访问；接口异常时保守拦截（后端还会兜底 403）
      // request.js 已解包：成功时 j 即 data（{role:...}）
      if (j && j.role === 'admin') return;
      links.forEach(function (a) {
        a.style.opacity = '0.45';
        a.style.cursor = 'not-allowed';
        a.title = '操作员权限无法访问';
        a.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          showNoPermTip();
        });
      });
    })
    .catch(function () { /* 网络异常不做前端拦截，由后端 403 兜底 */ });

  function showNoPermTip() {
    var mask = document.createElement('div');
    mask.id = 'noPermMask';
    mask.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:99999;display:flex;align-items:center;justify-content:center;';
    mask.innerHTML =
      '<div style="background:#fff;border-radius:12px;padding:26px 30px;width:330px;max-width:86vw;box-shadow:0 8px 30px rgba(0,0,0,.18);text-align:center;">' +
      '<div style="font-size:34px;margin-bottom:8px;">🔒</div>' +
      '<div style="font-size:16px;font-weight:600;color:#1A1B1C;">无权访问</div>' +
      '<div style="font-size:13px;color:#6B7280;margin:10px 0 20px;line-height:1.7;">当前账号为操作员权限。<br>如需访问请联系管理员调整权限。</div>' +
      '<button style="background:#EA6668;color:#fff;border:none;border-radius:8px;padding:9px 30px;font-size:14px;cursor:pointer;">我知道了</button>' +
      '</div>';
    mask.querySelector('button').addEventListener('click', function () { mask.remove(); });
    mask.addEventListener('click', function (e) { if (e.target === mask) mask.remove(); });
    document.body.appendChild(mask);
  }
})();
