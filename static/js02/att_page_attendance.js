/* 月度考勤表: 渲染 + 前端筛选; 月结锁定 / 调整单 / 导出 */
new Vue({
  el: '#app',
  delimiters: ['[[', ']]'],
  mixins: [window.AppMixin],
  data: function () {
    var p = window.PAGE;
    return {
      y: p.y, m: p.m, today: p.today,
      days: p.days, groups: p.groups, rows: p.rows, totals: p.totals,
      byType: p.byType || {},
      lock: p.lock, adjustments: p.adjustments, archive: p.archive,
      archiving: false,
      staffOptions: p.staffOptions, adjCategories: p.adjCategories,
      leaveTypes: p.leaveTypes, otTypes: p.otTypes,
      keyword: '', group: '',
      month: p.y + '-' + AppUtil.pad(p.m),
      adjDialog: false,
      adjForm: {
        staff_id: '', adj_date: '', category: '出勤', exc_type: '',
        hours: 0, reason: ''
      },
      /* 表格可视高度 = 窗口高 - 页头/KPI/卡片头占用, 随窗口缩放 */
      tableH: Math.max(320, window.innerHeight - 316)
    };
  },
  mounted: function () {
    var self = this;
    this._onResize = function () {
      self.tableH = Math.max(320, window.innerHeight - 316);
    };
    window.addEventListener('resize', this._onResize);
  },
  beforeDestroy: function () {
    window.removeEventListener('resize', this._onResize);
  },
  computed: {
    filteredRows: function () {
      var kw = this.keyword.trim(), gp = this.group;
      return this.rows.filter(function (r) {
        if (gp && (r.groups || [r.group]).indexOf(gp) < 0) return false;
        return !kw || r.name.indexOf(kw) >= 0;
      });
    },
    /* 调整单日期只能选本月 */
    monthPicker: function () {
      var y = this.y, m = this.m;
      return {
        disabledDate: function (d) {
          return d.getFullYear() !== y || d.getMonth() + 1 !== m;
        }
      };
    },
    /* 班制分组: 白班 8h/天 与 倒班 11h/天 口径不同, 分开看才不会被平均数误导 */
    typeRows: function () {
      var order = ['倒班制', '白班制'];
      var bt = this.byType || {};
      var keys = order.filter(function (k) { return bt[k]; });
      Object.keys(bt).forEach(function (k) {
        if (order.indexOf(k) < 0) keys.push(k);
      });
      return keys.map(function (k) {
        var v = bt[k];
        return {
          name: k, staff: v.staff, work: v.work, night: v.night,
          nightH: v.nightH, total: v.total,
          ot: v.ot, leave: v.leave, compOff: v.compOff, _src: v
        };
      });
    }
  },
  methods: {
    goMonth: function (v) {
      if (!v) return;
      var p = v.split('-');
      window.location.href = AppUtil.monthUrl(p[0], parseInt(p[1], 10));
    },
    reload: function () { window.location.reload(); },
    exportExcel: function () {
      window.location.href = '/att/attendance/export?year=' + this.y + '&month=' + this.m;
    },
    toggleLock: function () {
      var self = this;
      var locked = this.lock.locked;
      var text = locked
        ? '解锁后本月排班与异动会重新可编辑，调整单也将暂停使用。确认解锁 ' + this.y + ' 年 ' + this.m + ' 月？'
        : '锁定后本月的排班、异动都不能再修改，更正只能走「调整单」并永久留痕。确认锁定 ' + this.y + ' 年 ' + this.m + ' 月？';
      this.$confirm(text, locked ? '解锁月度' : '月结锁定', {
        type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消'
      }).then(function () {
        return AppUtil.post('/att/month/lock', {
          year: self.y, month: self.m, action: locked ? 'unlock' : 'lock'
        });
      }).catch(function (e) {
        if (e === 'cancel' || e === 'close') return;
        self.$message.error(e.message || '操作失败');
      });
    },
    /* ---- 结算归档 ---- */
    doArchive: function () {
      var self = this;
      if (!this.lock.locked) return this.$message.warning('请先执行月结锁定');
      var text = this.archive.archived
        ? '本月已归档 v' + this.archive.ver + '，重新归档会生成新版本（旧版本保留）。确认？'
        : '归档会把本月的明细、汇总、调整单和当时的班制配置写成本地文件（结算表 xlsx + 数据快照 json + 说明 txt），用于审计与纠纷回溯。确认归档 ' + this.y + ' 年 ' + this.m + ' 月？';
      this.$confirm(text, '结算归档', {
        type: 'info', confirmButtonText: '归档', cancelButtonText: '取消'
      }).then(function () {
        self.archiving = true;
        return AppUtil.post('/att/attendance/archive', { year: self.y, month: self.m });
      }).catch(function (e) {
        self.archiving = false;
        if (e === 'cancel' || e === 'close') return;
        self.$message.error(e.message || '归档失败');
      });
    },
    downloadArchive: function (kind) {
      window.location.href = '/att/attendance/archive/download?year=' + this.y +
        '&month=' + this.m + '&kind=' + kind;
    },
    openAdjust: function () {      if (!this.lock.locked) return this.$message.warning('请先执行月结锁定');
      this.adjDialog = true;
    },
    onAdjCategory: function () {
      this.adjForm.exc_type = this.adjForm.category === '请假'
        ? (this.leaveTypes[0] || '')
        : this.adjForm.category === '加班' ? (this.otTypes[0] || '') : '';
    },
    addAdjust: function () {
      var f = this.adjForm;
      if (!f.staff_id) return this.$message.warning('请选择员工');
      if (!f.hours) return this.$message.warning('调整工时不能为 0');
      if (!f.reason.trim()) return this.$message.warning('请填写调整原因');
      var payload = {
        action: 'add', staff_id: f.staff_id, adj_date: f.adj_date || '',
        category: f.category, exc_type: f.category === '出勤' ? '' : f.exc_type,
        hours: f.hours, reason: f.reason, year: this.y, month: this.m
      };
      this.submitPost('/att/adjustment', payload);
    },
    groupColor: function (g) {
      return { '甲班': '#205493', '乙班': '#4C7A9E', '丙班': '#9A7B4F', '管理': '#8A6D3B' }[g] || '#909399';
    },
    /** 给周末/今日的日期格加底色 */
    cellClass: function (o) {
      var prop = o.column.property || '';
      if (prop.charAt(0) !== 'c') return '';
      var d = this.days[parseInt(prop.slice(1), 10)];
      if (!d) return '';
      var cls = [];
      if (d.weekend) cls.push('wk');
      if (d.iso === this.today) cls.push('wk-today');
      if (d.future) cls.push('fut');
      return cls.join(' ');
    },
    headClass: function (o) {
      var prop = o.column.property || '';
      if (prop.charAt(0) !== 'c') return '';
      var d = this.days[parseInt(prop.slice(1), 10)];
      if (!d) return '';
      // 周末优先于未来：保证所有周末表头统一走 wk-head 深蓝底
      return d.weekend ? 'wk-head' : (d.future ? 'fut-head' : '');
    }
  }
});
