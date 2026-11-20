/* 人员信息: 班组切换 + 增删改查 + 入职离职 + 调组/对调/履历(照片走 FormData, 后端接口保持不变) */
function blankForm(group, today) {
  return {
    id: null, badge_id: '', name: '', gender: '', position: '',
    group: group, shift_type: '倒班制', report_to: '',
    cloth_size: '', shoe_size: '', helmet_size: '', age: '',
    hire: today, leave: ''
  };
}

new Vue({
  el: '#app',
  delimiters: ['[[', ']]'],
  mixins: [window.AppMixin],
  data: function () {
    var p = window.PAGE;
    return {
      groups: p.groups,
      members: p.members,
      reporters: p.reporters,
      today: p.today,
      activeGroup: '全部',
      keyword: '',
      saving: false,
      unlocked: false,
      dialog: { visible: false, edit: false },
      photoFile: null,
      photoPreview: '',
      form: blankForm(p.groups[0], p.today),
      rules: { name: [{ required: true, message: '请输入姓名', trigger: 'blur' }] },
      /* 调组 / 对调 / 履历 / 离职 四个弹窗 */
      groupDialog: { visible: false, id: null, name: '', from: '' },
      groupForm: { group: '', eff_date: p.today, note: '' },
      swapDialog: { visible: false, id: null, name: '', from: '' },
      swapForm: { other_id: '', eff_date: p.today, note: '' },
      histDialog: { visible: false, name: '', rows: [] },
      leaveDialog: { visible: false, id: null, name: '', date: p.today }
    };
  },
  computed: {
    /** 页签数据: "全部" 在最前, 便于跨班组查找; 行对象与各班组共享引用 */
    memberTabs: function () {
      var all = [];
      this.members.forEach(function (m) { all = all.concat(m.list); });
      return [{ group: '全部', all: true, list: all }].concat(this.members);
    },
    total: function () {
      var on = 0, left = 0;
      this.members.forEach(function (m) {
        m.list.forEach(function (s) { s.status === '在职' ? on++ : left++; });
      });
      return { onDuty: on, left: left };
    },
    /** 对调候选: 排除本人、同班组、管理岗 */
    swapCandidates: function () {
      var self = this;
      var out = [];
      this.members.forEach(function (m) {
        if (m.group === '管理' || m.group === self.swapDialog.from) return;
        m.list.forEach(function (s) {
          if (s.id !== self.swapDialog.id && s.status === '在职' && s.group !== '管理') out.push(s);
        });
      });
      return out;
    }
  },
  methods: {
    /** 写操作统一门槛: 未解锁一律拦截（与 30吨蒸发问题汇总页同款机制） */
    ensureEdit: function () {
      if (!this.unlocked) {
        this.$message.warning('请先点击右上角「解锁编辑」再操作');
        return false;
      }
      return true;
    },
    toggleLock: async function () {
      if (this.unlocked) {
        this.unlocked = false;
        this.$message.info('已锁定，人员信息只读');
        return;
      }
      try {
        var self = this;
        var res = await ELEMENT.MessageBox.prompt('请输入编辑密码', '解锁编辑', {
          confirmButtonText: '确定', cancelButtonText: '取消', inputType: 'password'
        });
        var r = await request.post('/att/staff/unlock', { password: res.value });
        if (r && r.ok) {
          self.unlocked = true;
          self.$message.success('已解锁，可以编辑人员信息');
        } else {
          self.$message.error((r && r.msg) || '密码错误');
        }
      } catch (err) {
        if (err && err !== 'cancel' && err !== 'close') {
          this.$message.error((err && err.message) || '密码错误');
        }
      }
    },
    groupColor: function (g) {
      return { '全部': '#205493', '甲班': '#205493', '乙班': '#4C7A9E', '丙班': '#9A7B4F', '管理': '#909399' }[g] || '#909399';
    },
    photoUrl: function (name) { return window.STATIC + 'att/photos/' + name; },
    filterRows: function (list) {
      var kw = this.keyword.trim();
      if (!kw) return list;
      return list.filter(function (s) {
        return (s.name + s.badge + s.position).indexOf(kw) >= 0;
      });
    },
    openAdd: function () {
      this.dialog = { visible: true, edit: false };
      /* "全部"页签下新增: 默认归入第一个班组, 弹窗内仍可改选 */
      var g = this.activeGroup === '全部' ? this.groups[0] : this.activeGroup;
      this.form = blankForm(g, this.today);
      this.photoFile = null;
      this.photoPreview = '';
    },
    openEdit: function (row) {
      this.dialog = { visible: true, edit: true };
      this.form = {
        id: row.id, badge_id: row.badge, name: row.name, gender: row.gender,
        position: row.position, group: row.group, shift_type: row.shift,
        report_to: row.reportTo || '', cloth_size: row.cloth, shoe_size: row.shoe,
        helmet_size: row.helmet, hire: row.hireDate || '', leave: row.leaveDate || '',
        age: row.age == null ? '' : row.age
      };
      this.photoFile = null;
      this.photoPreview = row.photo ? this.photoUrl(row.photo) : '';
    },
    onPhotoChange: function (file) {
      var raw = file.raw || file;
      if (!/^image\//.test(raw.type)) {
        this.$message.warning('只能上传图片文件');
        return;
      }
      if (raw.size > 2 * 1024 * 1024) {
        this.$message.warning('图片不能超过 2MB，请压缩后再上传');
        return;
      }
      this.photoFile = raw;
      this.photoPreview = URL.createObjectURL(raw);
    },
    save: function () {
      var self = this;
      if (!this.ensureEdit()) return;
      this.$refs.form.validate(function (ok) {
        if (!ok) return;
        var f = self.form;
        var data = {
          action: self.dialog.edit ? 'edit' : 'add',
          name: f.name.trim(), gender: f.gender, position: f.position,
          group: f.group, shift_type: f.shift_type,
          hire_date: f.hire || '', leave_date: f.leave || '',
          age: f.age === '' ? '' : Number(f.age),
          badge_id: f.badge_id,
          report_to: f.report_to === '' ? '' : f.report_to,
          cloth_size: f.cloth_size, shoe_size: f.shoe_size, helmet_size: f.helmet_size
        };
        if (self.dialog.edit) {
          data.id = f.id;
          if (self.photoFile) data.photo = self.photoFile;
        }
        self.saving = true;
        AppUtil.post('/att/staff', data).catch(function (e) {
          self.saving = false;
          self.$message.error(e.message || '保存失败');
        });
      });
    },
    /* ---------- 下拉菜单 ---------- */
    onCmd: function (cmd, row) {
      if (cmd === 'swap') return this.openSwap(row);
      if (cmd === 'hist') return this.openHist(row);
      if (cmd === 'leave') return this.openLeave(row);
      if (cmd === 'rejoin') return this.rejoin(row);
      if (cmd === 'remove') return this.remove(row);
    },
    /* ---------- 调组 ---------- */
    openGroupChange: function (row) {
      this.groupDialog = { visible: true, id: row.id, name: row.name, from: row.group };
      this.groupForm = { group: '', eff_date: this.today, note: '' };
    },
    submitGroupChange: function () {
      if (!this.ensureEdit()) return;
      var f = this.groupForm;
      if (!f.group) return this.$message.warning('请选择目标班组');
      if (!f.eff_date) return this.$message.warning('请选择生效日期');
      this.submitPost('/att/staff/group', {
        action: 'change', staff_id: this.groupDialog.id, group: f.group,
        eff_date: f.eff_date, note: f.note || ''
      });
    },
    /* ---------- 两人对调 ---------- */
    openSwap: function (row) {
      this.swapDialog = { visible: true, id: row.id, name: row.name, from: row.group };
      this.swapForm = { other_id: '', eff_date: this.today, note: '' };
    },
    submitGroupSwap: function () {
      if (!this.ensureEdit()) return;
      var f = this.swapForm;
      if (!f.other_id) return this.$message.warning('请选择对调对象');
      if (!f.eff_date) return this.$message.warning('请选择生效日期');
      this.submitPost('/att/staff/group', {
        action: 'swap', staff_id: this.swapDialog.id, other_id: f.other_id,
        eff_date: f.eff_date, note: f.note || ''
      });
    },
    /* ---------- 履历 ---------- */
    openHist: function (row) {
      this.histDialog = { visible: true, name: row.name, rows: row.history || [] };
    },
    /* ---------- 离职 / 复职 ---------- */
    openLeave: function (row) {
      this.leaveDialog = { visible: true, id: row.id, name: row.name, date: this.today };
    },
    submitLeave: function () {
      if (!this.ensureEdit()) return;
      if (!this.leaveDialog.date) return this.$message.warning('请选择离职日期');
      this.submitPost('/att/staff', {
        action: 'leave', id: this.leaveDialog.id, leave_date: this.leaveDialog.date
      });
    },
    rejoin: function (row) {
      if (!this.ensureEdit()) return;
      this.confirmPost('/att/staff', { action: 'rejoin', id: row.id },
        '确认让「' + row.name + '」复职？复职后按原班组继续排班，离职日期会清空。',
        '办理复职');
    },
    remove: function (row) {
      if (!this.ensureEdit()) return;
      this.confirmPost('/att/staff', { action: 'delete', id: row.id },
        '将永久移除「' + row.name + '」，其历史请假/加班记录会失去关联。如只是离岗，建议改用"办理离职"。',
        '移除员工');
    },
    onDialogClosed: function () {
      this.photoFile = null;
      this.photoPreview = '';
      if (this.$refs.form) this.$refs.form.resetFields();
    }
  }
});
