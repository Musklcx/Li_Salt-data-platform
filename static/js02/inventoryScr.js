/* 锂金属平衡看板 — Vue3 + Element Plus */
window.onerror = function(msg, src, line, col, err) {
  var d = document.createElement('div');
  d.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#d9534f;color:#fff;padding:10px;z-index:9999;font-size:13px;white-space:pre-wrap';
  d.textContent = 'JS错误: ' + msg + ' (行' + line + ')';
  document.body.appendChild(d);
};
const { createApp, ref, reactive, computed, onMounted, nextTick, watch } = Vue;

const TYPE_COLOR = { '输入体积': '#5b8ff9', '输入高度': '#2f8f6e', '输入质量': '#e0a030', 'SQLite': '#8a94a6' };
const TYPE_TEXT = { '输入体积': '#1a5fd0', '输入高度': '#1a7a4e', '输入质量': '#b07a10', 'SQLite': '#5a6478' };

createApp({
  setup() {
    const month = ref('2026-08');
    const months = ref([]);
    const rows = ref([]);
    const summary = reactive({});
    const dbBalance = reactive({});
    const fileInput = ref(null);
    const unlocked = ref(false);
    const showNewPeriod = ref(false);
    const newPeriod = reactive({ month: '', start_date: '', end_date: '' });

    let cSankey, cDonut, cWater, cTop, cSource;

    const fmt = v => (v == null ? '–' : Number(v).toFixed(3));
    const pct = v => (v == null ? '–' : (v * 100).toFixed(3) + '%');

    const input = computed(() => dbBalance.input_metal || 0);
    const sale = computed(() => dbBalance.sale_metal || 0);
    const ending = computed(() => summary.ending || 0);
    const sold2 = computed(() => (summary.sold_li2co3 || 0) + (summary.sold_na2so4 || 0));
    const yield_ = computed(() => summary.yield || 0);

    const balanceHtml = computed(() => {
      const s = summary;
      if (!s.opening && s.opening !== 0) return '';
      const closed = Math.abs(s.balance_diff) < 0.1;
      const cls = 'balance ' + (closed ? 'ok' : '');
      return `<span class="${cls}">平衡校验：期初 ${fmt(s.opening)} + 投入 ${fmt(s.input)} − 期末 ${fmt(s.ending)} − 外售 ${fmt(s.total_sold)} − 损失 ${fmt(s.loss)} =
        <b>${fmt(s.balance_diff)} t</b> <span class="tag">${closed?'✓ 闭合':'✗ 不平衡'}</span>
        ｜ 直收率 = ${pct(s.yield)}</span>`;
    });

    // ---- 公式联动 ----
    function recalcMetal(row) {
      // 金属量 = 体积 × 含量 / 1000
      const v = row.volume || 0;
      const c = row.concentration || 0;
      row.metal = Math.round(v * c / 1000 * 1000) / 1000;
    }

    function onHeightChange(row) {
      // 输入高度类型：体积 = 3.14 × 半径² × 高度
      if (row.data_type === '输入高度' && row.radius && row.height != null) {
        row.volume = Math.round(3.14 * row.radius * row.radius * row.height * 1000) / 1000;
        recalcMetal(row);
      }
      saveRow(row);
    }

    function onRadiusChange(row) {
      // 改半径也重算体积
      if (row.data_type === '输入高度' && row.radius && row.height != null) {
        row.volume = Math.round(3.14 * row.radius * row.radius * row.height * 1000) / 1000;
        recalcMetal(row);
      }
      saveRow(row);
    }

    function onVolumeChange(row) {
      recalcMetal(row);
      saveRow(row);
    }

    function onConcentrationChange(row) {
      recalcMetal(row);
      saveRow(row);
    }

    // ---- API ----
    async function load() {
      const q = month.value ? '?month=' + month.value : '';
      const st = await request.get('/api/state' + q);
      months.value = st.months || [];
      rows.value = st.inventory || [];
      Object.assign(summary, st.summary || {});
      Object.assign(dbBalance, st.db_balance || {});
      await nextTick();
      renderCharts();
    }

    async function saveRow(row) {
      await request.put('/api/rows/' + row.id, {
        equip_no: row.equip_no, equip_name: row.equip_name, data_type: row.data_type,
        radius: row.radius, height: row.height, volume: row.volume,
        concentration: row.concentration, metal: row.metal, in_ending: row.in_ending
      });
      // 保存后重新拉取汇总（KPI/图表/平衡条），不重渲染表格避免失焦
      await refreshSummary();
    }

    async function refreshSummary() {
      const q = month.value ? '?month=' + month.value : '';
      const st = await request.get('/api/state' + q);
      Object.assign(summary, st.summary || {});
      Object.assign(dbBalance, st.db_balance || {});
      // 同步 in_ending 和 metal 到本地行（避免后端重算覆盖前端值）
      const map = {};
      (st.inventory || []).forEach(r => map[r.id] = r);
      rows.value.forEach(r => {
        const s = map[r.id];
        if (s) { r.metal = s.metal; r.in_ending = s.in_ending; }
      });
      renderCharts();
    }

    async function addRow() {
      await request.post('/api/rows', { equip_no: '', equip_name: '新设备', data_type: '输入高度', radius: 2, height: 0, concentration: 0, period: month.value });
      await load();
      // 滚到表格底部，让新行可见
      await nextTick();
      const el = document.querySelector('.detail-table .el-scrollbar__wrap');
      if (el) el.scrollTop = el.scrollHeight;
    }

    async function delRow(row) {
      if (!confirm('删除该行？')) return;
      await request.del('/api/rows/' + row.id);
      load();
    }

    function triggerImport() { fileInput.value.click(); }

    async function addPeriod() {
      const r = await request.post('/api/periods', newPeriod);
      if (r.ok) {
        months.value = r.months;
        month.value = newPeriod.month;
        showNewPeriod.value = false;
        newPeriod.month = newPeriod.start_date = newPeriod.end_date = '';
        ElementPlus.ElMessage.success('已新增，可切换并导入盘点表');
        load(month.value);
      } else {
        ElementPlus.ElMessage.error(r.error || '创建失败');
      }
    }

    async function toggleLock() {
      if (unlocked.value) {
        unlocked.value = false;
        ElementPlus.ElMessage.info('已锁定，数据只读');
        return;
      }
      const { value } = await ElementPlus.ElMessageBox.prompt('请输入编辑密码', '解锁编辑', {
        confirmButtonText: '确定', cancelButtonText: '取消', inputType: 'password',
      });
      const r = await request.post('/api/unlock', { password: value });
      if (r.ok) {
        unlocked.value = true;
        ElementPlus.ElMessage.success('已解锁，可以编辑数据');
      } else {
        ElementPlus.ElMessage.error('密码错误');
      }
    }
    async function onImport(e) {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append('file', f); fd.append('period', month.value);
      const r = await request.upload('/api/import', fd);
      ElementPlus.ElMessage.success('导入完成，共 ' + r.imported + ' 行');
      load();
    }

    // ---- 图表 ----
    function renderCharts() {
      const s = summary;
      if (!s.opening && s.opening !== 0) return;

      // 桑基：投入 → 三种外售 / 在制 / 损失
      const li2co3 = s.sold_li2co3 || 0;
      const na2so4 = s.sold_na2so4 || 0;
      const li2so4 = dbBalance.sale_metal || 0;
      cSankey.setOption({
        tooltip: { trigger: 'item' },
        series: [{
          type: 'sankey', left: 10, right: 110, top: 10, bottom: 10, nodeWidth: 18, nodeGap: 10,
          label: { fontSize: 12 }, lineStyle: { color: 'gradient', opacity: 0.4 },
          data: [
            { name: '投入 ' + fmt(s.input) + ' t', itemStyle: { color: '#7fb08a' } },
            { name: '碳酸锂 ' + fmt(li2co3) + ' t', itemStyle: { color: '#3a9d6b' } },
            { name: '硫酸钠 ' + fmt(na2so4) + ' t', itemStyle: { color: '#5bb8a0' } },
            { name: '硫酸锂 ' + fmt(li2so4) + ' t', itemStyle: { color: '#7fd0b8' } },
            { name: '在制 ' + fmt(s.ending) + ' t', itemStyle: { color: '#2f6fb2' } },
            { name: '损失 ' + fmt(s.loss) + ' t', itemStyle: { color: '#d9534f' } },
          ],
          links: [
            { source: '投入 ' + fmt(s.input) + ' t', target: '碳酸锂 ' + fmt(li2co3) + ' t', value: li2co3 },
            { source: '投入 ' + fmt(s.input) + ' t', target: '硫酸钠 ' + fmt(na2so4) + ' t', value: na2so4 },
            { source: '投入 ' + fmt(s.input) + ' t', target: '硫酸锂 ' + fmt(li2so4) + ' t', value: li2so4 },
            { source: '投入 ' + fmt(s.input) + ' t', target: '在制 ' + fmt(s.ending) + ' t', value: s.ending },
            { source: '投入 ' + fmt(s.input) + ' t', target: '损失 ' + fmt(s.loss) + ' t', value: s.loss },
          ],
        }]
      });

      // 环形：期末构成
      const byType = {};
      rows.value.filter(r => r.in_ending)
        .forEach(r => { byType[r.data_type] = (byType[r.data_type] || 0) + (r.metal || 0); });
      cDonut.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} t ({d}%)' },
        legend: { bottom: 0 },
        series: [{
          type: 'pie', radius: ['50%', '72%'], center: ['50%', '44%'],
          label: { position: 'center', formatter: fmt(s.ending) + ' t', fontSize: 20, fontWeight: 'bold' },
          data: Object.entries(byType).map(([k, v]) => ({ name: k, value: +v.toFixed(3), itemStyle: { color: TYPE_COLOR[k] } })),
        }]
      });

      // 瀑布
      const steps = [
        { name: '期初', v: s.opening, start: 0, color: '#9db8d6' },
        { name: '投入', v: s.input, start: s.opening, color: '#7fb08a', add: true },
        { name: '期末', v: s.ending, start: s.opening + s.input - s.ending, color: '#d9534f', sub: true },
        { name: '损失', v: s.loss, start: s.opening + s.input - s.ending - s.loss, color: '#e0a030', sub: true },
        { name: '外售', v: s.total_sold, start: 0, color: '#3a9d6b' },
      ];
      cWater.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 40, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: steps.map(x => x.name) },
        yAxis: { type: 'value', name: 't' },
        series: [
          { type: 'bar', stack: 'x', itemStyle: { color: 'transparent' }, data: steps.map(x => +x.start.toFixed(3)) },
          { type: 'bar', stack: 'x', barWidth: 36,
            label: { show: true, position: 'top', formatter: p => { const st = steps[p.dataIndex]; return (st.add ? '+' : st.sub ? '−' : '') + fmt(st.v); } },
            data: steps.map(x => ({ value: +x.v.toFixed(3), itemStyle: { color: x.color } })) },
        ]
      });

      // Top 8
      const top = rows.value.filter(r => r.in_ending && r.metal > 0)
        .sort((a, b) => (b.metal || 0) - (a.metal || 0)).slice(0, 8);
      cTop.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 8, right: 50, top: 10, bottom: 10, containLabel: true },
        xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f5' } } },
        yAxis: { type: 'category', inverse: true, data: top.map(t => t.equip_name), axisLabel: { fontSize: 11 } },
        series: [{ type: 'bar', barWidth: 14,
          label: { show: true, position: 'right', formatter: p => fmt(p.value) + ' t', fontSize: 11 },
          data: top.map(t => ({ value: +t.metal.toFixed(3), itemStyle: { color: TYPE_COLOR[t.data_type] || '#5b8ff9' } })) }]
      });

      // 每日折线图：每日投入金属量 vs 每日外售合计（硫酸锂+碳酸锂+硫酸钠）
      const daily = dbBalance.daily || [];
      cSource.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['每日投入', '每日外售合计'], bottom: 0 },
        grid: { left: 10, right: 20, top: 20, bottom: 40, containLabel: true },
        xAxis: { type: 'category', data: daily.map(d => d.date), axisLabel: { fontSize: 10, rotate: 45 } },
        yAxis: { type: 'value', name: 't', splitLine: { lineStyle: { color: '#eef1f5' } } },
        series: [
          { name: '每日投入', type: 'line', smooth: true, data: daily.map(d => d.input), itemStyle: { color: '#7fb08a' }, areaStyle: { opacity: 0.15 } },
          { name: '每日外售合计', type: 'line', smooth: true, data: daily.map(d => d.sale), itemStyle: { color: '#e0a030' }, areaStyle: { opacity: 0.15 } },
        ]
      });
    }

    onMounted(() => {
      cSankey = echarts.init(document.getElementById('ch-sankey'));
      cDonut = echarts.init(document.getElementById('ch-donut'));
      cWater = echarts.init(document.getElementById('ch-waterfall'));
      cTop = echarts.init(document.getElementById('ch-top'));
      cSource = echarts.init(document.getElementById('ch-source'));
      window.addEventListener('resize', () => [cSankey, cDonut, cWater, cTop, cSource].forEach(c => c.resize()));
      load();
    });

    return {
      month, months, rows, fileInput, summary, db: dbBalance, unlocked,
      showNewPeriod, newPeriod,
      input, sale, ending, sold2, yield_, balanceHtml,
      fmt, pct, TYPE_COLOR, TYPE_TEXT,
      load, saveRow, addRow, delRow, triggerImport, onImport, toggleLock, addPeriod,
      onHeightChange, onRadiusChange, onVolumeChange, onConcentrationChange,
    };
  }
}).use(ElementPlus).mount('#app');
