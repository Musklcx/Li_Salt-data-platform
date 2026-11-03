/* ============================================================
   辅料包材单耗页面脚本
   ------------------------------------------------------------
   数据由 /api/unitcost/all 按月返回（后端已汇总）：
     aux  = 辅料月消耗（data_103 日数据 3 班组累计 → 月）
     mat  = 辅材月消耗（month_plan 月度数，直接取）
     li / na = 月度碳酸锂 / 硫酸钠产量；liPlan / naPlan = 计划
   本脚本只做展示层派生：
     1) 硫酸 ×1.84、液碱 ×1.35 折算为吨（qtyOf）
     2) 早于「首次有值月份」的 0 视为未录入（null），不参与计算
     3) 单耗 = 月消耗 ÷ 月产量；环比 = 与上月比；
        年均单耗 = 本年累计消耗 ÷ 本年累计产量（加权，仅两项都有值的月）
     4) 状态 = 较年均 +25% 超耗 / +10% 偏高 / −10% 节约（库中暂无目标表）
   ============================================================ */
let DATA = [];          // [{m,li,na,na4,liPlan,naPlan,aux:{},mat:{},days,rows}]
let ITEMS = [];         // [{key,grp,unit,base,factor,baseName,prec}]
const FIRST = {};       // key -> 首次有值索引（-1 = 从未有值）
const UNITS = {};       // key -> [null | 单耗]
const BASE_NAME = { li: "碳酸锂产量", na: "硫酸钠产量" };
const COLORS = ["#2b579a", "#1d9e75", "#e0a030", "#d9534f", "#7e57c2", "#00838f", "#c2185b", "#6d4c41", "#455a64"];
const MAX_MONTHS = 12;  // 趋势图最多显示近 12 个月

const state = { view: "aux", idx: 0, chartType: "line", sortKey: null, sortAsc: false };
const charts = { trend: null, dev: null };

const $ = id => document.getElementById(id);
const viewItems = () => ITEMS.filter(it => it.grp === state.view);
const now = () => DATA[state.idx] || { m: "", li: 0, na: 0, na4: 0, liPlan: 0, naPlan: 0, aux: {}, mat: {} };

/* ===== 格式化 ===== */
const fx = (v, n = 3) => (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(n);
const fnum = v => (v === null || v === undefined || isNaN(v))
    ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 1 });

/* ============================================================
   消耗量 / 单耗
   ============================================================ */
function rawQty(item, row) {
    const v = item.grp === "aux" ? row.aux[item.key] : row.mat[item.key];
    return (v === null || v === undefined) ? null : Number(v);
}
/* 折算到吨：硫酸 ×1.84、液碱 ×1.35，其余系数 1 */
function qtyOf(item, row) {
    const q = rawQty(item, row);
    return q === null ? null : q * (item.factor || 1);
}

function buildDerived() {
    ITEMS.forEach(it => {
        FIRST[it.key] = DATA.findIndex(r => {
            const v = rawQty(it, r);
            return v !== null && v > 0;
        });
    });
    ITEMS.forEach(it => {
        const first = FIRST[it.key];
        UNITS[it.key] = DATA.map((r, i) => {
            if (first < 0 || i < first) return null;
            const q = qtyOf(it, r);
            if (q === null) return null;
            const base = Number(r[it.base] || 0);
            if (!base) return null;
            return q / base;
        });
    });
}

const baseOf = (it, i) => Number((DATA[i] || {})[it.base] || 0);

function momOf(it, i) {
    const cur = UNITS[it.key][i], prev = UNITS[it.key][i - 1];
    if (cur === null || prev === null || prev === undefined || !prev) return null;
    return (cur - prev) / prev;
}

/* 年均单耗：同年内累计消耗 ÷ 累计产量 */
function avgOf(it, i) {
    let qSum = 0, bSum = 0, n = 0;
    const y = (DATA[i] || {}).m ? DATA[i].m.slice(0, 4) : "";
    for (let k = 0; k <= i && k < DATA.length; k++) {
        if (DATA[k].m.slice(0, 4) !== y) continue;
        if (FIRST[it.key] < 0 || k < FIRST[it.key]) continue;
        const q = qtyOf(it, DATA[k]);
        const b = baseOf(it, k);
        if (q === null || !b) continue;
        qSum += q; bSum += b; n++;
    }
    return { val: bSum > 0 ? qSum / bSum : null, n };
}

/* 状态：以年均单耗为基准 */
function statusOf(ratio) {
    if (ratio === null || ratio === undefined || isNaN(ratio)) return { cls: "tag-flat", txt: "—" };
    if (ratio > 1.25) return { cls: "tag-bad", txt: "超耗" };
    if (ratio > 1.10) return { cls: "tag-warn", txt: "偏高" };
    if (ratio < 0.90) return { cls: "tag-ok", txt: "节约" };
    return { cls: "tag-flat", txt: "正常" };
}

/* 环比 / 较年均 药丸：单耗升高=不利（红），下降=有利（绿） */
function pctPill(p) {
    if (p === null || p === undefined || isNaN(p)) return '<span class="pill na">—</span>';
    const v = p * 100;
    let cls = "flat";
    if (v > 0.05) cls = "bad";
    else if (v < -0.05) cls = "good";
    const arrow = v > 0.05 ? "↑" : (v < -0.05 ? "↓" : "");
    return '<span class="pill ' + cls + '">' + arrow + Math.abs(v).toFixed(1) + "%</span>";
}

/* 迷你走势（近 6 个月） */
function spark(key, i) {
    const from = Math.max(0, i - 5);
    const vals = UNITS[key].slice(from, i + 1);
    const pts = vals.map((v, k) => ({ i: k, v })).filter(p => p.v !== null);
    if (pts.length < 2) return '<span style="color:#c8ced8">—</span>';
    const W = 62, H = 20, pad = 2.5;
    const mn = Math.min(...pts.map(p => p.v)), mx = Math.max(...pts.map(p => p.v));
    const span = (mx - mn) || 1;
    const X = k => pad + k * (W - pad * 2) / Math.max(1, vals.length - 1);
    const Y = v => H - pad - (v - mn) / span * (H - pad * 2);
    const d = pts.map((p, k) => (k ? "L" : "M") + X(p.i).toFixed(1) + "," + Y(p.v).toFixed(1)).join(" ");
    const last = pts[pts.length - 1], first = pts[0];
    const c = last.v > first.v ? "#d9483d" : "#27905f";
    return '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' +
        '<path d="' + d + '" fill="none" stroke="' + c + '" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>' +
        '<circle cx="' + X(last.i).toFixed(1) + '" cy="' + Y(last.v).toFixed(1) + '" r="1.9" fill="' + c + '"/></svg>';
}

/* ============================================================
   事实层：供「数据解读」使用的小统计
   —— 全部基于 UNITS / momOf / avgOf，保证与表格同一套数字
   ============================================================ */
/* 近 span 个月的有效单耗点（跳过未录入的 null） */
function seriesOf(it, i, span) {
    const from = Math.max(0, i - (span || 6) + 1);
    const out = [];
    for (let k = from; k <= i; k++) {
        const v = UNITS[it.key][k];
        if (v !== null && v !== undefined) out.push({ i: k, v: v, m: DATA[k].m });
    }
    return out;
}
/* 连续同向月数：dir = ±1 为方向，n = 连续变化次数（2 表示连升两个月） */
function streakOf(it, i) {
    const cur = UNITS[it.key][i];
    if (cur === null || cur === undefined) return { n: 0, dir: 0 };
    let dir = 0, n = 0;
    for (let k = i; k > 0; k--) {
        const a = UNITS[it.key][k], b = UNITS[it.key][k - 1];
        if (a === null || a === undefined || b === null || b === undefined || !b) break;
        const d = a > b ? 1 : (a < b ? -1 : 0);
        if (!d) break;
        if (!dir) dir = d;
        else if (d !== dir) break;
        n++;
    }
    return { n: n, dir: dir };
}
const pctStr = v => (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "%";

/* ============================================================
   渲染：表格
   ============================================================ */
function renderTable() {
    const items = viewItems();
    const tb = $("tbody");
    const i = state.idx;
    const row = now();

    // 排序（单耗 / 环比 / 较年均）
    let list = items.slice();
    if (state.sortKey) {
        const val = it => {
            if (state.sortKey === "now") return UNITS[it.key][i];
            if (state.sortKey === "mom") return momOf(it, i);
            const a = avgOf(it, i).val, u = UNITS[it.key][i];
            return (a && u !== null) ? (u / a - 1) : null;
        };
        list.sort((a, b) => {
            const va = val(a), vb = val(b);
            const aa = (va === null || va === undefined || isNaN(va)) ? -Infinity : va;
            const bb = (vb === null || vb === undefined || isNaN(vb)) ? -Infinity : vb;
            return state.sortAsc ? aa - bb : bb - aa;
        });
    }

    const grpLabel = {
        aux: { t: "辅料 · 按碳酸锂产量折算", h: "日数据 3 班组累计 → 月消耗 ÷ 月碳酸锂产量，单位 t/t" },
        mat: { t: "辅材 · 按对应产量折算", h: "月度直接取数（month_plan）÷ 对应产量" }
    };

    let html = "", curGrp = null;
    list.forEach(it => {
        if (it.grp !== curGrp) {
            curGrp = it.grp;
            const g = grpLabel[curGrp] || { t: curGrp, h: "" };
            html += '<tr class="grp"><td colspan="9">' + g.t + '<span class="hint">' + g.h + "</span></td></tr>";
        }
        const u = UNITS[it.key][i];
        const p = momOf(it, i);
        const a = avgOf(it, i);
        const ratio = (a.val && u !== null) ? u / a.val : null;
        const st = statusOf(ratio);
        const qty = (FIRST[it.key] < 0 || i < FIRST[it.key]) ? null : qtyOf(it, row);
        html += '<tr>' +
            '<td><span class="mat-name">' + it.key + "</span><span class=\"mat-base\">÷ " +
                it.baseName + (it.factor && it.factor !== 1 ? " · ×" + it.factor + " 折算" : "") + "</span></td>" +
            '<td class="v-qty">' + (qty === null ? "—" : fnum(qty) + '<span class="un">' + it.unit + "</span>") + "</td>" +
            '<td class="v-now">' + fx(u, 3) + "</td>" +
            "<td>" + fx(UNITS[it.key][i - 1], 3) + "</td>" +
            "<td>" + pctPill(p) + "</td>" +
            "<td>" + (a.val === null ? "—" : fx(a.val, 3) +
                '<span style="color:#c3c9d2;font-size:10.5px;margin-left:3px;">' + a.n + "月</span>") + "</td>" +
            "<td>" + pctPill(ratio === null ? null : ratio - 1) + "</td>" +
            '<td style="text-align:center">' + spark(it.key, i) + "</td>" +
            '<td style="text-align:center"><span class="tag ' + st.cls + '">' + st.txt + "</span></td>" +
            "</tr>";
    });

    if (!list.length) html = '<tr><td colspan="9" class="empty">该月份暂无数据</td></tr>';
    tb.innerHTML = html;

    // 表头 / 表底说明
    $("tblSub").textContent = row.m
        ? row.m.replace("-", " 年 ") + " 月 · 碳酸锂 " + fnum(row.li) + " t / 硫酸钠 " + fnum(row.na) + " t"
        : "—";

    const notes = [];
    notes.push("折算基准：碳酸锂 <b>" + fnum(row.li) + " t</b> / 硫酸钠 <b>" + fnum(row.na) + " t</b>");
    notes.push("硫酸 ×1.84、液碱 ×1.35 折算为吨");
    const firstH2SO4 = DATA[FIRST["硫酸"]] ? DATA[FIRST["硫酸"]].m : null;
    if (firstH2SO4 && DATA[0] && firstH2SO4 !== DATA[0].m) {
        notes.push("硫酸 / 液碱自 " + firstH2SO4 + " 起有数据，此前按未录入不计入");
    }
    if (!row.na) notes.push("本月硫酸钠产量为 0，按硫酸钠折算的项无单耗");
    if (row.na4 > 0 && row.na > 0 && Math.abs(row.na - row.na4) / row.na4 > 0.01) {
        notes.push("⚠ 硫酸钠产量与「干+湿+杂质+落地」合计不一致（" + fnum(row.na) + " vs " + fnum(row.na4) + " t），请核对");
    }
    if (row.days && row.days < 28) notes.push("本月仅 " + row.days + " 天有记录，数据可能不完整");
    $("tblNote").innerHTML = notes.join('<span class="dot"></span>');
}

/* ============================================================
   渲染：KPI
   ============================================================ */
function renderKpi() {
    const i = state.idx, row = now();
    const prev = i > 0 ? DATA[i - 1] : null;

    const liPct = row.liPlan ? row.li / row.liPlan : null;
    $("kpiLiFoot").textContent =
        fnum(row.li) + " t / 计划 " + fnum(row.liPlan) + " t" +
        (prev && prev.li ? " · 环比 " + ((row.li - prev.li) / prev.li * 100).toFixed(1) + "%" : "");
    $("kpiLiFill").style.width = Math.min(100, (liPct || 0) * 100).toFixed(1) + "%";
    $("kpiLiPct").textContent = liPct === null ? "—" : (liPct * 100).toFixed(1) + "%";

    const naPct = row.naPlan ? row.na / row.naPlan : null;
    $("kpiNaFoot").textContent =
        fnum(row.na) + " t / 计划 " + fnum(row.naPlan) + " t" +
        (prev && prev.na ? " · 环比 " + ((row.na - prev.na) / prev.na * 100).toFixed(1) + "%" : "");
    $("kpiNaFill").style.width = Math.min(100, (naPct || 0) * 100).toFixed(1) + "%";
    $("kpiNaPct").textContent = naPct === null ? "—" : (naPct * 100).toFixed(1) + "%";

    // 辅料 / 辅材 超标项（较年均 +25% 记超耗，+10%~25% 记偏高）
    const judge = grp => {
        const items = ITEMS.filter(it => it.grp === grp);
        const over = [], warn = [];
        items.forEach(it => {
            const u = UNITS[it.key][i], a = avgOf(it, i).val;
            if (u === null || !a) return;
            const r = u / a;
            if (r > 1.25) over.push({ n: it.key, r });
            else if (r > 1.10) warn.push({ n: it.key, r });
        });
        return { over, warn, total: items.length };
    };
    [["aux", "kpiAux"], ["mat", "kpiMat"]].forEach(([grp, pre]) => {
        const { over, warn, total } = judge(grp);
        const el = $(pre + "Over");
        el.textContent = String(over.length);
        el.style.color = over.length ? "#d9483d" : "#27905f";
        $(pre + "OverSmall").textContent = "/ " + total + " 项";
        const parts = over.map(o => o.n + " +" + ((o.r - 1) * 100).toFixed(0) + "%")
            .concat(warn.map(o => o.n + " +" + ((o.r - 1) * 100).toFixed(0) + "%"));
        $(pre + "OverFoot").textContent = parts.length ? parts.join(" · ") : "全部在年均 ±10% 以内";
    });
}

/* ============================================================
   渲染：图表
   ============================================================ */
function initCharts() {
    if (!window.echarts) return;
    charts.trend = echarts.init($("chartTrend"));
    charts.dev = echarts.init($("chartDev"));
}

function renderCharts() {
    if (!window.echarts || !charts.trend) return;
    const items = viewItems();
    const i = state.idx;
    const start = Math.max(0, DATA.length - MAX_MONTHS);

    $("trendTitle").textContent = "单耗趋势（近 " + (DATA.length - start) + " 个月）";
    $("trendSub").textContent = "单位 / 折算基准见右侧表格";

    const months = DATA.slice(start).map(r => r.m.slice(5) + "月");
    const series = items.map(it => {
        const color = COLORS[ITEMS.indexOf(it) % COLORS.length];
        const data = UNITS[it.key].slice(start).map(v => v === null ? null : +v.toFixed(4));
        return {
            name: it.key, type: state.chartType, data,
            itemStyle: { color }, smooth: true, connectNulls: false,
            areaStyle: state.chartType === "line" ? { opacity: 0.08 } : undefined,
            symbolSize: 5, barMaxWidth: 14
        };
    });

    charts.trend.setOption({
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "line", lineStyle: { color: "#cfd6e0" } },
            backgroundColor: "#fff", borderColor: "#e6eaf0", textStyle: { color: "#2f353d", fontSize: 12 },
            formatter: ps => {
                if (!ps || !ps.length) return "";
                let s = '<div style="font-weight:600;margin-bottom:4px;">' + ps[0].axisValue + "</div>";
                ps.forEach(p => {
                    const it = ITEMS.find(x => x.key === p.seriesName);
                    if (!it) return;
                    const idx = start + p.dataIndex;
                    const qty = qtyOf(it, DATA[idx]);
                    const v = p.value;
                    s += '<div style="line-height:1.7;">' + p.marker + p.seriesName + "：<b>" +
                        (v === null || v === undefined ? "—" : Number(v).toFixed(3)) + "</b>";
                    if (qty !== null) s += '<span style="color:#9aa3b0;">（' + fnum(qty) + it.unit + "）</span>";
                    s += "</div>";
                });
                return s;
            }
        },
        legend: { top: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: "#6b7280", fontSize: 11.5 }, icon: "roundRect" },
        grid: { left: 6, right: 14, top: 34, bottom: 6, containLabel: true },
        xAxis: {
            type: "category", data: months, boundaryGap: state.chartType !== "line",
            axisLine: { lineStyle: { color: "#e6eaf0" } }, axisTick: { show: false },
            axisLabel: { color: "#9aa3b0", fontSize: 11 }
        },
        yAxis: {
            type: "value", name: "单耗", nameTextStyle: { color: "#b6bcc6", fontSize: 11 },
            splitLine: { lineStyle: { color: "#f2f4f8" } },
            axisLabel: { color: "#9aa3b0", fontSize: 11 }
        },
        series
    }, true);

    /* 偏离图：横向条形，正值红 / 负值绿 */
    const dev = items.map(it => {
        const u = UNITS[it.key][i], a = avgOf(it, i).val;
        return { name: it.key, v: (u !== null && a) ? (u / a - 1) * 100 : null };
    }).filter(d => d.v !== null).sort((a, b) => b.v - a.v);

    charts.dev.setOption({
        tooltip: {
            trigger: "axis", axisPointer: { type: "shadow" },
            backgroundColor: "#fff", borderColor: "#e6eaf0", textStyle: { color: "#2f353d", fontSize: 12 },
            formatter: ps => {
                const p = ps[0], v = p.value;
                const it = ITEMS.find(x => x.key === p.name);
                if (!it) return p.name;
                const u = UNITS[it.key][i], a = avgOf(it, i).val;
                return '<div style="font-weight:600;margin-bottom:3px;">' + p.name + "</div>" +
                    "本月 " + fx(u, 3) + " " + it.unit + "/t　年均 " + fx(a, 3) + "<br/>" +
                    '偏离 <b style="color:' + (v > 0 ? "#d9483d" : "#27905f") + '">' +
                    (v > 0 ? "+" : "") + v.toFixed(1) + "%</b>";
            }
        },
        grid: { left: 6, right: 34, top: 8, bottom: 6, containLabel: true },
        xAxis: {
            type: "value", name: "%", nameTextStyle: { color: "#b6bcc6", fontSize: 11 },
            splitLine: { lineStyle: { color: "#f2f4f8" } }, axisLabel: { color: "#9aa3b0", fontSize: 11 }
        },
        yAxis: {
            type: "category", data: dev.map(d => d.name).reverse(),
            axisLine: { show: false }, axisTick: { show: false },
            axisLabel: { color: "#4a5361", fontSize: 11.5 }
        },
        series: [{
            type: "bar", barWidth: 12,
            data: dev.map(d => ({
                value: +d.v.toFixed(1),
                itemStyle: { color: d.v > 0 ? "#d9534f" : "#1d9e75", borderRadius: 3 }
            })).reverse(),
            label: {
                show: true, position: "right", fontSize: 11, color: "#6b7280",
                formatter: p => (p.value > 0 ? "+" : "") + p.value + "%"
            }
        }]
    }, true);

    if (!dev.length) {
        charts.dev.setOption({
            title: {
                text: "本月暂无可比数据", left: "center", top: "middle",
                textStyle: { color: "#aab0ba", fontSize: 13, fontWeight: "normal" }
            },
            series: [{ type: "bar", data: [] }]
        }, true);
    }
}

/* ============================================================
   渲染：数据解读（表达层）
   ------------------------------------------------------------
   三层结构：
     事实层 —— 上面的 UNITS / momOf / avgOf / streakOf 算出事实
     选择层 —— 按「超耗 > 环比 > 趋势 > 节约 > 提醒 > 产量」挑 5 条
     表达层 —— 固定句式填数字，句式随事实分支变化
   所有数字与表格同源，不做二次计算，避免两套口径。
   ============================================================ */
function renderNarrative() {
    const body = $("narBody");
    if (!body) return;

    const i = state.idx, row = now();
    const items = viewItems();
    const grpName = state.view === "mat" ? "辅材" : "辅料";
    $("narSub").textContent = row.m
        ? row.m.replace("-", " 年 ") + " 月 · " + grpName + " " + items.length + " 项"
        : "—";

    const facts = items.map(it => {
        const u = UNITS[it.key][i];
        const a = avgOf(it, i);
        return {
            it: it, u: u, avg: a.val, n: a.n,
            mom: momOf(it, i),
            ratio: (u !== null && u !== undefined && a.val) ? u / a.val : null,
            st: streakOf(it, i),
            hist: seriesOf(it, i, 6)
        };
    });
    /* 本月消耗量为 0 的项：人工录数常见，视为未录入，不参与「最优 / 趋势」判断 */
    const zeroKeys = items
        .filter(it => FIRST[it.key] >= 0 && i >= FIRST[it.key] && qtyOf(it, row) === 0)
        .map(it => it.key);
    const valid = facts.filter(f =>
        f.u !== null && f.u !== undefined && f.u > 0 && f.ratio !== null);

    if (!valid.length) {
        body.innerHTML = '<div class="nar-empty">本月' + grpName + '暂无可比数据：' +
            ((row.li || row.na) ? "消耗量未录入或为 0，无法计算单耗。" : "本月产量尚未录入。") +
            "</div>";
        return;
    }

    const over = valid.filter(f => f.ratio > 1.25).sort((a, b) => b.ratio - a.ratio);
    const warn = valid.filter(f => f.ratio > 1.10 && f.ratio <= 1.25).sort((a, b) => b.ratio - a.ratio);
    const good = valid.filter(f => f.ratio < 0.90).sort((a, b) => a.ratio - b.ratio);

    /* ---------- 总览一句 ---------- */
    const partial = !!(row.days && row.days < 20);        // 月度未录满，单耗系统性偏低
    const firstOnly = valid.every(f => f.n <= 1);         // 只有当月一个月，无基准可比
    const allWithin = valid.every(f => f.ratio >= 0.90 && f.ratio <= 1.10);
    let sum;
    if (firstOnly) {
        sum = "本月" + grpName + " " + valid.length + " 项为首次有数据，暂无可比基准（环比与较年均留空）。";
    } else if (over.length) {
        sum = "本月" + grpName + " " + valid.length + " 项中 <b>" + over.length +
            " 项超耗</b>（高于年均 25% 以上）" +
            (warn.length ? "，另 " + warn.length + " 项偏高" : "") +
            "；最突出的是 <b>" + over[0].it.key + "</b>（" + pctStr(over[0].ratio - 1) + "）。";
    } else if (warn.length) {
        sum = "本月" + grpName + " " + valid.length + " 项单耗均在年均 ±25% 内，<b>" + warn.length +
            " 项偏高</b>，<b>" + warn[0].it.key + "</b> 居首（" + pctStr(warn[0].ratio - 1) + "）。";
    } else if (!allWithin) {
        sum = "本月" + grpName + " " + valid.length + " 项均未超耗，其中 " + good.length +
            " 项低于年均值 10% 以上，单耗整体偏优。";
    } else {
        sum = "本月" + grpName + " " + valid.length + " 项单耗全部落在年均 ±10% 内，消耗水平平稳。";
    }
    /* 数据不完整时，先把前提说清楚，避免"平稳"被误读 */
    if (partial && !firstOnly) {
        sum = '<span class="hl-warn">本月仅 ' + row.days + " 天有记录，以下对比参考意义有限。</span>" + sum;
    }

    const out = [];

    /* 1) 最突出的超耗项 —— 带连续性判断 */
    if (over.length) {
        const f = over[0];
        let t = "<b>" + f.it.key + "</b> " + fx(f.u, 3) + " " + f.it.unit + "/t，较年均 " + fx(f.avg, 3) +
            " 高 <span class=\"hl-bad\">" + pctStr(f.ratio - 1) + "</span>";
        if (f.st.n >= 2 && f.st.dir > 0) t += "，且已连续 " + f.st.n + " 个月上升";
        else if (f.mom !== null && f.mom > 0) t += "，环比继续上升 " + pctStr(f.mom);
        out.push({ tone: "bad", html: t + "。" });
    }

    /* 2) 环比涨幅最大项（与第 1 条重复时跳过） */
    const byMom = valid.filter(f => f.mom !== null && f.mom !== undefined && isFinite(f.mom))
        .sort((a, b) => b.mom - a.mom);
    if (!partial && byMom.length && byMom[0].mom > 0.02 &&
        !(over.length && byMom[0].it.key === over[0].it.key)) {
        const f = byMom[0];
        out.push({
            tone: "bad",
            html: "<b>" + f.it.key + "</b>环比 <span class=\"hl-bad\">" + pctStr(f.mom) + "</span>（" +
                fx(UNITS[f.it.key][i - 1], 3) + " → " + fx(f.u, 3) + "），为当月涨幅最大项。"
        });
    }

    /* 3) 近 6 个月趋势 —— 取变化幅度最大的一项，变化小于 3% 视为平稳不提 */
    const tr = valid.filter(f => f.hist.length >= 3 && f.hist[0].v > 0).map(f => {
        const first = f.hist[0].v, last = f.hist[f.hist.length - 1].v;
        return { f: f, chg: (last - first) / first, span: f.hist.length, first: first, last: last };
    }).sort((a, b) => Math.abs(b.chg) - Math.abs(a.chg));

    if (tr.length && Math.abs(tr[0].chg) > 0.03) {
        const t0 = tr[0];
        const st = t0.f.st;
        const word = (st.n >= 3 && st.dir !== 0)
            ? "已连续 " + st.n + " 个月" + (st.dir > 0 ? "上行" : "下行")
            : "整体" + (t0.chg > 0 ? "上行" : "下行");
        out.push({
            tone: t0.chg > 0 ? "warn" : "good",
            html: "<b>" + t0.f.it.key + "</b>近 " + t0.span + " 个月" + word + "，" +
                fx(t0.first, 3) + " → " + fx(t0.last, 3) +
                "（<span class=\"" + (t0.chg > 0 ? "hl-bad" : "hl-good") + "\">" + pctStr(t0.chg) + "</span>）。"
        });
    }

    /* 4) 最节约项 */
    if (good.length && !partial) {
        const f = good[0];
        out.push({
            tone: "good",
            html: "<b>" + f.it.key + "</b>较年均低 <span class=\"hl-good\">" +
                Math.abs((f.ratio - 1) * 100).toFixed(1) + "%</span>，为当月最优项。"
        });
    }

    /* 5) 数据提醒 —— 只留最要紧的一条，避免噪音 */
    const tips = [];
    if (zeroKeys.length) tips.push(zeroKeys.join("、") + " 本月消耗为 0（疑未录入），未纳入对比");
    if (row.days && row.days < 28 && row.days >= 20) tips.push("本月仅 " + row.days + " 天有记录，单耗可能有偏差");
    const newKeys = items.filter(it => FIRST[it.key] === i).map(it => it.key);
    if (newKeys.length) tips.push(newKeys.join("、") + " 自本月起才有数据，环比无参考");
    if (row.na4 > 0 && row.na > 0 && Math.abs(row.na - row.na4) / row.na4 > 0.01) {
        tips.push("硫酸钠产量与四料合计不一致（" + fnum(row.na) + " vs " + fnum(row.na4) + " t），需核对");
    }
    if (tips.length) out.push({ tone: "warn", html: "数据提醒：" + tips[0] + "。" });

    /* 6) 产量完成情况（放在最后，通常被 5 条上限截掉，KPI 卡已有） */
    const liPct = row.liPlan ? row.li / row.liPlan : null;
    const naPct = row.naPlan ? row.na / row.naPlan : null;
    if (row.li || row.na) {
        let t = "碳酸锂产量 <b>" + fnum(row.li) + " t</b>" +
            (liPct !== null ? "，完成计划 " + (liPct * 100).toFixed(1) + "%" : "");
        if (row.na) t += "；硫酸钠 <b>" + fnum(row.na) + " t</b>" +
            (naPct !== null ? "，完成计划 " + (naPct * 100).toFixed(1) + "%" : "");
        out.push({ tone: "flat", html: t + "。" });
    }

    body.innerHTML = '<div class="nar-sum">' + sum + "</div>" +
        out.slice(0, 5).map(o =>
            '<div class="nar-item ' + o.tone + '"><span class="bar"></span><span class="tx">' + o.html + "</span></div>"
        ).join("");
}

/* ============================================================
   渲染入口
   ============================================================ */
function render() {
    if (!DATA.length) return;
    renderKpi();
    renderTable();
    renderCharts();
    renderNarrative();
    document.querySelectorAll("#dt thead th.sortable").forEach(th => {
        const s = th.querySelector(".sort");
        if (!s) return;
        s.textContent = th.dataset.sort === state.sortKey ? (state.sortAsc ? "↑" : "↓") : "↕";
    });
}

/* ============================================================
   交互
   ============================================================ */
function bindEvents() {
    document.querySelectorAll(".metric-group button").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".metric-group button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            state.view = btn.dataset.view;
            state.sortKey = null;
            render();
        };
    });

    const mp = $("monthPick");
    if (mp) {
        mp.onchange = e => {
            const i = DATA.findIndex(r => r.m === e.target.value);
            if (i >= 0) { state.idx = i; render(); }
            else e.target.value = now().m;
        };
    }

    $("btnLine").onclick = () => {
        state.chartType = "line";
        $("btnLine").classList.add("active");
        $("btnBar").classList.remove("active");
        renderCharts();
    };
    $("btnBar").onclick = () => {
        state.chartType = "bar";
        $("btnBar").classList.add("active");
        $("btnLine").classList.remove("active");
        renderCharts();
    };

    $("btnExport").onclick = () => {
        window.location.href = "/api/export/unitcost?view=" + state.view;
    };

    document.querySelectorAll("#dt thead th.sortable").forEach(th => {
        th.onclick = () => {
            const k = th.dataset.sort;
            if (state.sortKey === k) state.sortAsc = !state.sortAsc;
            else { state.sortKey = k; state.sortAsc = false; }
            renderTable();
            document.querySelectorAll("#dt thead th.sortable").forEach(t => {
                const s = t.querySelector(".sort");
                if (!s) return;
                s.textContent = t.dataset.sort === state.sortKey ? (state.sortAsc ? "↑" : "↓") : "↕";
            });
        };
    });

    window.addEventListener("resize", () => {
        if (charts.trend) charts.trend.resize();
        if (charts.dev) charts.dev.resize();
    });
}

/* ============================================================
   初始化
   ============================================================ */
function showEmpty(msg) {
    $("tbody").innerHTML = '<tr><td colspan="9" class="empty">' + msg + "</td></tr>";
    $("tblSub").textContent = "—";
}

async function init() {
    let payload = null;
    try {
        payload = await request.get("/api/unitcost/all");
    } catch (e) {
        showEmpty("数据加载失败：" + e.message);
        return;
    }
    DATA = (payload && payload.rows) || [];
    ITEMS = ((payload && payload.items) || []).map(it => Object.assign({}, it, {
        baseName: BASE_NAME[it.base] || "产量",
        prec: 3
    }));

    if (!DATA.length || !ITEMS.length) {
        showEmpty("暂无月度数据（请先在数据对比 / 月度计划中录入）");
        return;
    }

    state.idx = DATA.length - 1;
    const mp = $("monthPick");
    mp.min = DATA[0].m;
    mp.max = DATA[DATA.length - 1].m;
    mp.value = now().m;

    buildDerived();
    initCharts();
    bindEvents();
    render();
}

document.addEventListener("DOMContentLoaded", init);
