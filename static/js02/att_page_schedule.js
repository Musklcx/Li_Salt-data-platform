/* 记录表组件: 请假 / 加班 / 放假 三张表共用同一套表格与分页逻辑 */
Vue.component('record-table', {
  delimiters: ['[[', ']]'],
  template: '#tpl-record-table',
  props: {
    rows: { type: Array, default: function () { return []; } },
    columns: { type: Array, default: function () { return []; } },
    tone: { type: String, default: 'leave' },
    empty: { type: String, default: '暂无记录' },
    locked: { type: Boolean, default: false }
  },
  data: function () { return { keyword: '', page: 1, size: 10 }; },
  computed: {
    filtered: function () {
      var kw = this.keyword.trim();
      if (!kw) return this.rows;
      return this.rows.filter(function (r) {
        return r.name.indexOf(kw) >= 0 || (r.note || '').indexOf(kw) >= 0 ||
          (r.type || '').indexOf(kw) >= 0;
      });
    },
    pageRows: function () {
      var start = (this.page - 1) * this.size;
      return this.filtered.slice(start, start + this.size);
    }
  },
  watch: {
    rows: function () { this.page = 1; },
    keyword: function () { this.page = 1; }
  },
  methods: {
    indexOf: function (i) { return (this.page - 1) * this.size + i + 1; }
  }
});

new Vue({
  el: '#app',
  delimiters: ['[[', ']]'],
  mixins: [window.AppMixin],
  data: function () {
    var p = window.PAGE;
    var paid = p.leaveTypes.filter(function (t) { return t.indexOf('带薪假-') === 0; });
    var comp = p.leaveTypes.filter(function (t) { return t === '调休'; });
    var unpaid = p.leaveTypes.filter(function (t) {
      return t.indexOf('带薪假-') !== 0 && t !== '调休';
    });
    return {
      y: p.y, m: p.m, today: p.today, groups: p.groups,
      grid: p.grid, summary: p.summary, records: p.records,
      swaps: p.swaps, holidayPlans: p.holidayPlans,
      lock: p.lock, locked: p.lock.locked,
      holidayDates: p.holidayDates,
      otTypes: p.otTypes, holidayTypes: p.holidayTypes,
      leaveTypeGroups: [
        { label: '不带薪', options: unpaid.map(function (t) { return { value: t, label: t }; }) },
        { label: '带薪假', options: paid.map(function (t) { return { value: t, label: t.replace('带薪假-', '') }; }) },
        { label: '不扣薪', options: comp.map(function (t) { return { value: t, label: t }; }) }
      ],
      month: p.y + '-' + AppUtil.pad(p.m),
      tab: tabFromHash(window.location.hash) || sessionStorage.getItem('sched-tab') || 'leave',
      generating: false,
      /* 日历表高度(JS 按容器实测, Element 2.6 不支持 calc)与空行填充数 */
      calH: 0,
      filler: 0,
      leaveForm: { staff_ids: [], exc_type: '事假', date_mode: 'single', exc_date: '', range: [],
                   actual_hours: 0, note: '' },
      pv: null,            /* 连续登记的预览结果 */
      pvLoading: false,
      pvTimer: null,
      otForm: { staff_ids: [], exc_type: p.otTypes[0], exc_date: '', actual_hours: 0, note: '' },
      holForm: { staff_ids: [], holiday_type: '日常', exc_date: '', actual_hours: 0, note: '' },
      swapForm: { staff_a: '', staff_b: '', swap_date: '', note: '' },
      planForm: { scope: 'all', group: p.groups[0], staff_ids: [], start_date: '', end_date: '', note: '' },
      /* 班制设置 */
      cfgDialog: false,
      cfgSaving: false,
      cfgShifts: (p.shiftConfig ? p.shiftConfig.shifts : []),
      cfgRules: (p.shiftConfig ? p.shiftConfig.rules : []).map(function (r) {
        r.cycleArr = (r.cycle || '').split(',');
        return r;
      }),
      ruleForm: { group: p.groups[0], cycle: '休,休,白,白,夜,夜', offset: 0, anchor: '', valid_from: '' },
      leaveColumns: [
        { prop: 'name', label: '员工', type: 'name', width: 110 },
        { prop: 'group', label: '班组', type: 'group', width: 96 },
        { prop: 'date', label: '日期', width: 110, sortable: true },
        { prop: 'type', label: '假别', type: 'pill', width: 110 },
        { prop: 'hours', label: '扣减(h)', type: 'minus', width: 90, sortable: true },
        { prop: 'note', label: '备注', type: 'note', align: 'left' }
      ],
      otColumns: [
        { prop: 'name', label: '员工', type: 'name', width: 110 },
        { prop: 'group', label: '班组', type: 'group', width: 96 },
        { prop: 'date', label: '日期', width: 110, sortable: true },
        { prop: 'type', label: '类型', type: 'pill', width: 96 },
        { prop: 'hours', label: '时长(h)', type: 'plus', width: 90, sortable: true },
        { prop: 'multiplier', label: '倍率', width: 70 },
        { prop: 'note', label: '备注', type: 'note', align: 'left' }
      ],
      holColumns: [
        { prop: 'name', label: '员工', type: 'name', width: 110 },
        { prop: 'group', label: '班组', type: 'group', width: 96 },
        { prop: 'date', label: '日期', width: 110, sortable: true },
        { prop: 'type', label: '类型', type: 'pill', width: 96 },
        { prop: 'multiplier', label: '倍率', width: 70 },
        { prop: 'planned', label: '计划(h)', width: 84 },
        { prop: 'hours', label: '实际(h)', type: 'plus', width: 90, sortable: true },
        { prop: 'note', label: '备注', type: 'note', align: 'left' }
      ]
    };
  },
  computed: {
    gridRows: function () {
      /* 月份天数不足可视高度时, 用空行补满, 保证日历卡片底部始终齐平 */
      var rows = this.grid.slice();
      for (var i = 0; i < this.filler; i++) rows.push({ filler: true });
      return rows;
    },
    staffGroups: function () {
      var buckets = {}, order = [];
      (window.PAGE.staff || []).forEach(function (s) {
        if (!buckets[s.group]) { buckets[s.group] = []; order.push(s.group); }
        buckets[s.group].push(s);
      });
      return order.map(function (g) { return { label: g, list: buckets[g] }; });
    },
    /* 换班只在倒班班组之间发生: 白班制的管理岗不出现在换班下拉里 */
    swapGroups: function () {
      var buckets = {}, order = [];
      (window.PAGE.staffSwap || []).forEach(function (s) {
        if (!buckets[s.group]) { buckets[s.group] = []; order.push(s.group); }
        buckets[s.group].push(s);
      });
      return order.map(function (g) { return { label: g, list: buckets[g] }; });
    },
    holPicker: function () {
      var allowed = this.holidayDates;
      return {
        disabledDate: function (d) {
          return allowed.indexOf(formatDate(d)) < 0;
        }
      };
    }
  },
  mounted: function () {
    var self = this;
    if (window.location.hash) {
      this.$nextTick(function () {
        var el = document.querySelector(window.location.hash);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
    this.$watch('tab', function (v) { sessionStorage.setItem('sched-tab', v); });
    /* 连续登记的日期/人员/假别一改就重新核对(防抖), 让人提交前看到将写哪几天 */
    this.$watch('leaveForm', function () {
      /* 切到连续模式时清掉手填的扣减数: 区间按每天班次自动扣, 不吃单日残留值 */
      var f = self.leaveForm;
      if (f.date_mode === 'range' && Number(f.actual_hours) > 0) f.actual_hours = 0;
      self.queuePreview();
    }, { deep: true });
    window.addEventListener('hashchange', function () {
      var t = tabFromHash(window.location.hash);
      if (t) self.tab = t;
    });
    /* 日历表高度 + 空行数量: 挂载后与窗口缩放时重新测量 */
    this._onResize = function () { self.measureCal(); };
    window.addEventListener('resize', this._onResize);
    this.$nextTick(function () { self.measureCal(); });
  },
  beforeDestroy: function () {
    window.removeEventListener('resize', this._onResize);
  },
  methods: {
    goMonth: function (v) {
      if (!v) return;
      var p = v.split('-');
      window.location.href = AppUtil.monthUrl(p[0], parseInt(p[1], 10));
    },
    syncHash: function (t) {
      var anchor = {
        leave: '#leave-sec', ot: '#ot-sec', hol: '#hol-sec',
        swap: '#swap-sec', holplan: '#holplan-sec'
      }[t.name];
      if (anchor && window.history.replaceState) {
        window.history.replaceState(null, '', anchor);
      }
    },
    groupColor: function (g) {
      return { '甲班': '#205493', '乙班': '#4C7A9E', '丙班': '#9A7B4F' }[g] || '#909399';
    },
    /** 实测日历容器高度 → 表格高度 + 需要补的空行数 */
    measureCal: function () {
      var self = this;
      var wrap = this.$refs.calWrap;
      if (!wrap) return;
      this.calH = wrap.clientHeight;
      this.$nextTick(function () {
        var bw = wrap.querySelector('.el-table__body-wrapper');
        if (!bw) return;
        var tr = bw.querySelector('tbody tr');
        var rowH = (tr && tr.offsetHeight) || 28;
        var rows = Math.max(1, Math.floor((bw.clientHeight - 2) / rowH));
        self.filler = Math.max(0, rows - self.grid.length);
      });
    },
    rowClass: function (o) {
      if (o.row.filler) return 'is-filler';
      return o.row.weekend ? 'weekend-row' : '';
    },
    multOf: function (t) { return { '日常': 1, '公休': 2, '法定': 3 }[t] || 1; },
    toggleHoliday: function (row) {
      if (row.filler) return;
      var self = this;
      AppUtil.post('/att/schedule/toggle-holiday', { date: row.iso }).catch(function (e) {
        self.$message.error(e.message || '操作失败');
      });
    },
    /** 点某班组的班次 → 只切换该班组放假 */
    toggleGroupHoliday: function (row, group) {
      if (row.filler || this.locked) return;
      var self = this;
      AppUtil.post('/att/schedule/toggle-holiday', { date: row.iso, group: group })
        .catch(function (e) { self.$message.error(e.message || '操作失败'); });
    },
    addSwap: function () {
      var f = this.swapForm;
      if (!f.staff_a || !f.staff_b) return this.$message.warning('请选择两位员工');
      if (f.staff_a === f.staff_b) return this.$message.warning('请选择两位不同的员工');
      if (!f.swap_date) return this.$message.warning('请选择换班日期');
      this.submitPost('/att/schedule/swap', {
        action: 'add', staff_a: f.staff_a, staff_b: f.staff_b,
        swap_date: f.swap_date, note: f.note || ''
      });
    },
    removeSwap: function (row) {
      this.confirmPost('/att/schedule/swap', { action: 'delete', id: row.id },
        '确认删除「' + row.date + ' ' + row.a + ' ↔ ' + row.b + '」这条换班记录？删除后当天工时按原班次重算。',
        '删除换班记录');
    },
    addHolidayPlan: function () {
      var f = this.planForm;
      if (!f.start_date) return this.$message.warning('请选择放假日期');
      if (f.scope === 'person' && !f.staff_ids.length) return this.$message.warning('请选择放假人员');
      this.submitPost('/att/schedule/holiday', {
        action: 'add', scope: f.scope, group: f.group, staff_ids: f.staff_ids,
        start_date: f.start_date, end_date: f.end_date || '', note: f.note || ''
      });
    },
    removeHolidayPlan: function (row) {
      var text = row.kind === 'person'
        ? '确认取消「' + row.date + ' ' + row.scope + '」的个人放假？'
        : '确认取消「' + row.date + ' ' + row.scope + '」的放假？取消后当天恢复计划出勤。';
      this.confirmPost('/att/schedule/holiday', {
        action: 'remove', kind: row.kind, id: row.id, date: row.date, groups: row.groups
      }, text, '取消放假');
    },
    generate: function () {
      var self = this;
      this.generating = true;
      AppUtil.post('/att/schedule/generate', { year: this.y, month: this.m }).catch(function (e) {
        self.generating = false;
        self.$message.error(e.message || '生成失败');
      });
    },
    /* ---- 班制设置 ---- */
    saveShifts: function () {
      var self = this, payload = {};
      this.cfgShifts.forEach(function (s) { payload['hours_' + s.code] = s.hours; });
      this.cfgSaving = true;
      AppUtil.post('/att/schedule/shiftdef', payload).catch(function (e) {
        self.cfgSaving = false;
        self.$message.error(e.message || '保存失败');
      });
    },
    addRule: function () {
      var f = this.ruleForm;
      if (!f.cycle.trim()) return this.$message.warning('请填写周期');
      if (!f.anchor) return this.$message.warning('请选择锚点日期');
      if (!f.valid_from) return this.$message.warning('请选择生效日期');
      this.submitPost('/att/schedule/rotation', {
        action: 'add', group: f.group, cycle: f.cycle, offset: f.offset || 0,
        anchor: f.anchor, valid_from: f.valid_from
      });
    },
    endRule: function (row) {
      var self = this;
      this.$prompt('填写结止日期（含当天），该规则到这天为止不再生效。', '结止「' + row.group + '」的规则', {
        inputValue: row.validFrom, inputPattern: /^\d{4}-\d{2}-\d{2}$/,
        inputErrorMessage: '日期格式应为 yyyy-mm-dd'
      }).then(function (res) {
        self.submitPost('/att/schedule/rotation', { action: 'end', id: row.id, valid_to: res.value });
      }).catch(function () {});
    },
    /* 加班时长: 周末上班通常按一整天算, 选到周六/周日自动填 8h, 仍可手改(工作日不预填) */
    onOtDate: function (v) {
      if (!v || this.otForm.actual_hours) return;
      var wd = new Date(v + 'T00:00:00').getDay();
      if (wd === 0 || wd === 6) this.otForm.actual_hours = 8;
    },
    /** 表单 POST, 但要拿到 JSON 结果(连续登记要回显"写了几条/跳过哪几天") */
    postJson: function (url, data) {
      var fd = new FormData();
      Object.keys(data).forEach(function (k) {
        var v = data[k];
        if (v === undefined || v === null || v === '') return;
        if (Array.isArray(v)) v.forEach(function (x) { fd.append(k, x); });
        else fd.append(k, v);
      });
      return fetch(url, {
        method: 'POST', body: fd, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch' }
      }).then(function (res) {
        return res.json().catch(function () { return { ok: res.ok }; }).then(function (j) {
          if (!res.ok || j.ok === false) throw new Error(j.error || ('提交失败 (HTTP ' + res.status + ')'));
          return j;
        });
      });
    },
    /** 请假区间预览(防抖 350ms): 只有选了人 + 有了起止日期才发请求 */
    queuePreview: function () {
      var self = this, f = this.leaveForm;
      if (this.pvTimer) clearTimeout(this.pvTimer);
      if (f.date_mode !== 'range') { this.pv = null; this.pvLoading = false; return; }
      var start = f.range && f.range[0];
      var end = f.range && f.range[1];
      if (!f.staff_ids.length || !start || !end) {
        this.pv = null; this.pvLoading = false; return;
      }
      this.pvLoading = true;
      this.pvTimer = setTimeout(function () {
        self.postJson('/att/exception/preview', {
          category: '请假', exc_type: f.exc_type,
          start_date: start, end_date: end,
          actual_hours: f.actual_hours || 0, staff_ids: f.staff_ids
        }).then(function (j) {
          self.pv = j; self.pvLoading = false;
        }).catch(function (e) {
          self.pv = { lines: [e.message], days: [], added: 0 };
          self.pvLoading = false;
        });
      }, 350);
    },
    addRecord: function (category, form) {
      var self = this;
      if (!form.staff_ids.length) return this.$message.warning('请先选择员工');
      var isLeave = category === '请假';
      var rangeMode = isLeave && form.date_mode === 'range';
      var start = rangeMode ? (form.range && form.range[0]) : form.exc_date;
      var end = rangeMode ? (form.range && form.range[1]) : form.exc_date;
      if (!start || !end) return this.$message.warning(rangeMode ? '请选择请假的起止日期' : '请选择日期');
      if (!isLeave && !(Number(form.actual_hours) > 0)) {
        return this.$message.warning(category === '放假'
          ? '请填写实际上班时长：放假日出勤按当天真正来了几小时算，不按班次标准工时'
          : '请填写加班工时（大于 0）');
      }
      if (rangeMode && this.pv && this.pv.added === 0) {
        return this.$message.warning('这几天没有可登记的上班日：' + (this.pv.lines[0] || ''));
      }
      var payload = {
        action: 'add', category: category,
        date_mode: rangeMode ? 'range' : 'single',
        actual_hours: form.actual_hours || 0, note: form.note || '',
        staff_ids: form.staff_ids
      };
      if (rangeMode) {
        payload.start_date = start; payload.end_date = end;
      } else {
        payload.exc_date = start;
      }
      if (category === '放假') payload.holiday_type = form.holiday_type;
      else payload.exc_type = form.exc_type;

      if (!isLeave) return this.submitPost('/att/exception', payload);

      /* 请假走 JSON: 拿到"登记 N 天/跳过哪几天"的结论, 区间登记用弹窗确保看得见 */
      payload._json = '1';
      this.postJson('/att/exception', payload).then(function (j) {
        if (rangeMode) {
          self.$alert(j.message, '已登记', { confirmButtonText: '知道了' })
            .then(function () { window.location.reload(); })
            .catch(function () { window.location.reload(); });
        } else {
          self.$message({ type: 'success', message: j.message, duration: 1500 });
          setTimeout(function () { window.location.reload(); }, 800);
        }
      }).catch(function (e) {
        self.$message.error(e.message || '提交失败');
      });
    },
    removeRecord: function (row) {
      this.confirmPost('/att/exception', { action: 'delete', id: row.id },
        '确认删除「' + row.name + ' · ' + row.date + ' · ' + row.type + '」这条记录？删除后统计会同步变化。',
        '删除异动记录');
    }
  }
});

/* ---------- 小工具 ---------- */
function tabFromHash(h) {
  return {
    '#leave-sec': 'leave', '#ot-sec': 'ot', '#hol-sec': 'hol',
    '#swap-sec': 'swap', '#holplan-sec': 'holplan'
  }[h] || '';
}

function formatDate(d) {
  return d.getFullYear() + '-' + AppUtil.pad(d.getMonth() + 1) + '-' + AppUtil.pad(d.getDate());
}
