/* ============================================================
   水电汽消耗页面脚本
   ------------------------------------------------------------
   数据口径：14 列均为累计表底读数（底数），0 = 未抄表。
   - 库里存原始底数；插值只在展示层做：
     两个有效底数之间的 0 按线性插值补齐
     → 日用量 = （当日有效底数 − 前日有效底数）× 电表倍率
   - 「表底读数」口径显示的是表上原始读数（未乘倍率），
     与人工抄表看到的数字一致；「当日用量」才是真正的 kWh。
   - 插值不影响合计（合计只取决于首尾真实底数）
   - 插值补录的单元格标黄加 *（td-est）
   ============================================================ */
let charts = { c1: null, c2: null };     // 两张趋势图实例

/* 用电分两组显示（曲线太密拆开），表格不拆分 */
const ELEC_GROUP_1 = ["60t高压电表1", "60t高压电表2", "30t高压电表", "车间总电表"];
const ELEC_GROUP_2 = ["沸腾床电表", "60t低压电表", "30t低压电表", "104总电表"];

/* 合计电量 = 车间总电表 + 60t高压1 + 60t高压2 + 30t高压 */
const ELEC_TOTAL_COLS = ["车间总电表", "60t高压电表1", "60t高压电表2", "30t高压电表"];

/* 合计汽量 = 车间总蒸汽 + 60t总蒸汽 + 30t总蒸汽 */
const STEAM_TOTAL_COLS = ["车间总蒸汽", "60t总蒸汽", "30t总蒸汽"];

/* 吨锂X耗卡片标签（电/汽/水同一算法：区间合计用量 ÷ 区间碳酸锂金属量） */
const UNIT_NAMES = { elec: "吨锂电耗", steam: "吨锂汽耗", water: "吨锂水耗" };

const METRICS = {
    elec:  {
        name: "用电", unit: "kWh",
        cols: ["车间总电表", "60t高压电表1", "60t高压电表2", "30t高压电表", "沸腾床电表", "60t低压电表", "30t低压电表", "104总电表"],
        groups: [
            { title: "趋势 · 车间总表与高压", cols: ELEC_GROUP_1 },
            { title: "趋势 · 低压与沸腾床", cols: ELEC_GROUP_2 }
        ]
    },
    steam: {
        name: "蒸汽", unit: "t",
        cols: ["车间总蒸汽", "60t总蒸汽", "30t总蒸汽", "沸腾床蒸汽"],
        groups: [{ title: "蒸汽趋势", cols: ["车间总蒸汽", "60t总蒸汽", "30t总蒸汽", "沸腾床蒸汽"] }]
    },
    water: {
        name: "用水", unit: "m³",
        cols: ["自来水", "工业水"],
        groups: [{ title: "用水趋势", cols: ["自来水", "工业水"] }]
    }
};

/* 电表倍率：表上读数 × 倍率 = 实际电量（与后端 COL_RATIO 保持一致） */
const RATIO = {
    "车间总电表": 4000, "60t高压电表1": 4000, "60t高压电表2": 4000,
    "30t高压电表": 40,
    "沸腾床电表": 1, "60t低压电表": 1, "30t低压电表": 1, "104总电表": 1
};

/* 表格/图例里的短名（右侧表格栏较窄，长列名会挤爆）
   注：车间总蒸汽展示为「碳酸锂汽」= 车间总蒸汽 − 沸腾床蒸汽（派生列，见 cellVal） */
const LABELS = {
    "车间总电表": "车间总表", "60t高压电表1": "60t高压1", "60t高压电表2": "60t高压2",
    "30t高压电表": "30t高压", "沸腾床电表": "沸腾床", "60t低压电表": "60t低压",
    "30t低压电表": "30t低压", "104总电表": "104总表",
    "车间总蒸汽": "碳酸锂汽", "60t总蒸汽": "60t总汽", "30t总蒸汽": "30t总汽",
    "沸腾床蒸汽": "沸腾床", "自来水": "自来水", "工业水": "工业水"
};
/* 派生列的表头悬停说明 */
const DERIVED_TIP = {
    "__total": "合计电量 = 车间总电表 + 60t高压1 + 60t高压2 + 30t高压",
    "车间总蒸汽": "碳酸锂汽 = 车间总蒸汽 − 沸腾床蒸汽"
};
const labelOf = c => LABELS[c] || c;
const ratioOf = c => RATIO[c] || 1;

let rawAllData = [];
let EFF = {}, USAGE = {}, EST = {};      // 全量序列（按原始索引），插值/用量预计算
let currentKey = "elec";
let granularity = "day";
let mode = "usage";                       // usage=当日用量 | reading=表底读数
let chartType = "line";
let viewRows = [];                        // 当前视图行：日=[{日期,_idx}]；月=[{日期,_lastIdx,usage:{col:sum}}]
let sortState = { field: null, asc: false };

const CHART_COLORS = ["#2b579a", "#1d9e75", "#e0a030", "#d9534f", "#7e57c2", "#00838f", "#c2185b", "#6d4c41"];

function getLastDayOfPrevMonth() {
    const d = new Date();
    d.setDate(1);
    d.setDate(0);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function getTodayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/* ===== 底数插值 + 日用量预计算（全量序列上做，保证跨筛选边界的缺口也能补齐） ===== */
function computeDerived() {
    EFF = {}; USAGE = {}; EST = {};
    for (const k of Object.keys(METRICS)) {
        METRICS[k].cols.forEach(col => {
            const raw = rawAllData.map(r => Number(r[col] || 0));
            const eff = raw.slice(), est = raw.map(() => false);
            const first = raw.findIndex(v => v > 0);
            if (first >= 0) {
                let last = first;
                for (let i = first + 1; i < raw.length; i++) {
                    if (raw[i] > 0) {
                        if (i - last > 1) {
                            const step = (raw[i] - raw[last]) / (i - last);
                            for (let j = last + 1; j < i; j++) { eff[j] = raw[last] + step * (j - last); est[j] = true; }
                        }
                        last = i;
                    }
                }
            }
            const ratio = ratioOf(col);
            const usage = eff.map((v, i) => {
                if (v === 0) return 0;               // 未启用段：用量 0
                if (i === 0 || eff[i - 1] === 0) return null;  // 首个有效底数日：无前值
                return (v - eff[i - 1]) * ratio;     // 读数差 × 倍率 = 实际用量
            });
            EFF[col] = eff; EST[col] = est; USAGE[col] = usage;
        });
    }
}

/* ===== 数据加载 ===== */
async function loadData() {
    try {
        rawAllData = await request.get("/api/utilities/all");
        computeDerived();
        document.getElementById("startDate").value = getLastDayOfPrevMonth();
        document.getElementById("endDate").value = getTodayStr();
        render();
    } catch (err) {
        console.error("加载数据异常", err);
        alert("无法获取后端数据，请确认Flask服务已启动，接口地址正确");
    }
}

function parseDateStr(s) { return new Date(String(s).replace(/\//g, "-")); }

function filterByDate(list, startStr, endStr) {
    if (!startStr && !endStr) return list.map((r, i) => [r, i]);
    const out = [];
    list.forEach((r, i) => {
        const d = parseDateStr(r["日期"]);
        let ok = true;
        if (startStr) ok = ok && (d >= new Date(startStr));
        if (endStr) ok = ok && (d <= new Date(endStr));
        if (ok) out.push([r, i]);
    });
    return out;
}

/* ===== 视图构建：日 / 月 ===== */
function buildView() {
    const sDate = document.getElementById("startDate").value;
    const eDate = document.getElementById("endDate").value;
    const pairs = filterByDate(rawAllData, sDate, eDate);

    if (granularity === "day") {
        viewRows = pairs.map(([r, i]) => ({ 日期: r["日期"], _idx: i }));
        return;
    }
    // 月聚合：用量按月累加；底数取当月最后一个有效底数
    const cols = METRICS[currentKey].cols;
    const agg = [];
    const map = {};
    pairs.forEach(([r, i]) => {
        const m = r["日期"].substring(0, 7);
        if (!map[m]) { map[m] = { 日期: m, _lastIdx: i, usage: {} }; agg.push(map[m]); }
        const g = map[m];
        if (i > g._lastIdx) g._lastIdx = i;
        cols.forEach(c => {
            const v = USAGE[c][i];
            if (v !== null) g.usage[c] = (g.usage[c] || 0) + v;
        });
    });
    viewRows = agg;
}

/* ===== 单元格取值 ===== */
function cellValRaw(col, row) {
    if (granularity === "month") {
        return mode === "usage" ? (row.usage[col] !== undefined ? row.usage[col] : null) : EFF[col][row._lastIdx];
    }
    return mode === "usage" ? USAGE[col][row._idx] : EFF[col][row._idx];
}
/* 碳酸锂汽（派生）：车间总蒸汽 − 沸腾床蒸汽（读数口径相减、用量口径相减，二者等价） */
function cellVal(col, row) {
    const v = cellValRaw(col, row);
    if (col === "车间总蒸汽") {
        if (v === null) return null;
        const fb = cellValRaw("沸腾床蒸汽", row);
        return fb === null ? null : v - fb;
    }
    return v;
}
function cellEst(col, row) {
    // 插值补录日：读数口径（该日读数是补的）与用量口径（用量是分摊的）都要标
    if (granularity === "month") return false;
    if (col === "车间总蒸汽") return EST[col][row._idx] || EST["沸腾床蒸汽"][row._idx];
    return EST[col][row._idx];
}

/* ===== KPI 卡片 ===== */
function renderKpiCards() {
    const $ = id => document.getElementById(id);
    const m = METRICS[currentKey];
    const fmt = v => Number(v || 0).toFixed(2);
    const isElec = currentKey === "elec";
    const isSteam = currentKey === "steam";
    // 用电=合计电量口径；蒸汽=合计汽量口径；用水逐表相加
    const totalCols = isElec ? ELEC_TOTAL_COLS : (isSteam ? STEAM_TOTAL_COLS : m.cols);
    $("kpiRange").innerText = `${$("startDate").value} ~ ${$("endDate").value}`;
    $("curMetricName").innerText = m.name;
    $("kpiSumUnit").innerText = m.unit;
    $("kpiLastUnit").innerText = m.unit;

    const isUsage = mode === "usage";
    $("kpiSumLabel").innerText = isUsage ? (isElec ? "合计电量" : (isSteam ? "合计汽量" : "各表合计用量")) : "最新读数合计（仅参考）";
    $("kpiSumLabel").title = isElec
        ? "合计电量 = 车间总电表 + 60t高压1 + 60t高压2 + 30t高压"
        : (isSteam
            ? "合计汽量 = 车间总蒸汽 + 60t总蒸汽 + 30t总蒸汽"
            : "逐表相加");

    if (viewRows.length === 0) {
        $("kpiSumValue").innerText = "0.00";
        $("kpiLastValue").innerText = "-";
        $("kpiUnitCard").style.display = "block";
        $("kpiUnitLabel").innerText = UNIT_NAMES[currentKey];
        $("kpiUnitValue").innerText = "-";
        return;
    }

    // 合计（用量口径：区间内逐日累加；底数口径：最后一行的读数合计）
    // 注意用 cellValRaw（原始表值）：合计汽量中的"车间总蒸汽"是原表，不扣沸腾床
    let total = 0;
    if (isUsage) {
        viewRows.forEach(row => totalCols.forEach(c => { const v = cellValRaw(c, row); if (v !== null) total += v; }));
    } else {
        const last = viewRows[viewRows.length - 1];
        totalCols.forEach(c => { const v = cellVal(c, last); if (v !== null) total += v; });
    }
    $("kpiSumValue").innerText = fmt(total);

    // 最近一日 / 最后一条
    const lastRow = viewRows[viewRows.length - 1];
    let lastTotal = 0;
    totalCols.forEach(c => { const v = cellValRaw(c, lastRow); if (v !== null) lastTotal += v; });
    $("kpiLastLabel").innerText = isUsage
        ? (granularity === "day" ? `最近一日（${lastRow.日期}）` : `${lastRow.日期} 用量`)
        : (granularity === "day" ? `最近一日（${lastRow.日期}）` : `${lastRow.日期} 底数`);
    $("kpiLastValue").innerText = fmt(lastTotal);

    // 吨锂X耗（电/汽/水同算法）：区间合计用量 ÷ 区间碳酸锂金属量
    // 分子与 KPI 合计同口径：用电=合计电量、汽=合计汽量（原表总汽，含沸腾床）、水=两路水相加
    $("kpiUnitCard").style.display = "block";
    $("kpiUnitLabel").innerText = UNIT_NAMES[currentKey];
    $("kpiUnitSmall").innerText = m.unit + "/t";
    $("kpiUnitCard").title = `区间${$("kpiSumLabel").innerText} ÷ 区间碳酸锂金属量`;
    {
        const sDate = $("startDate").value, eDate = $("endDate").value;
        let utilSum = 0, metalSum = 0;
        filterByDate(rawAllData, sDate, eDate).forEach(([r, i]) => {
            totalCols.forEach(c => {
                const v = USAGE[c][i];
                if (v !== null) utilSum += v;
            });
            metalSum += Number(r["碳酸锂金属量"] || 0);
        });
        $("kpiUnitValue").innerText = metalSum > 0 ? fmt(utilSum / metalSum) : "-";
    }
}

/* ===== 图表（用电拆两组，蒸汽/水一张图） ===== */
function renderChart() {
    const m = METRICS[currentKey];
    const xData = viewRows.map(r => r["日期"]);
    const modeText = mode === "usage" ? "当日用量" : "表底读数";

    document.getElementById("chartCol").classList.toggle("single", m.groups.length < 2);

    m.groups.forEach((g, gi) => {
        const idx = gi + 1;
        const chart = charts["c" + idx];
        const panel = document.getElementById("chartPanel" + idx);
        const shown = !!g;
        panel.style.display = shown ? "" : "none";
        if (!shown || !chart) return;

        // 短名 → 全名（tooltip 里显示完整表名）
        const FULL = {};
        g.cols.forEach(c => FULL[labelOf(c)] = c);

        const ratioCols = g.cols.filter(c => ratioOf(c) !== 1);
        const ratioText = ratioCols.length ? "（已乘倍率：" + ratioCols.map(c => labelOf(c) + "×" + ratioOf(c)).join("、") + "）" : "";

        const seriesList = g.cols.map(col => {
            const colorIdx = m.cols.indexOf(col);   // 全局配色：同一块表在任何图里颜色一致
            const ser = {
                name: labelOf(col),
                type: chartType === "stack" ? "bar" : chartType,
                data: viewRows.map(r => { const v = cellVal(col, r); return v === null ? null : Math.round(v * 100) / 100; }),
                itemStyle: { color: CHART_COLORS[colorIdx % CHART_COLORS.length] }
            };
            if (chartType === "stack") ser.stack = "total";
            if (chartType === "line") { ser.smooth = true; ser.connectNulls = false; ser.areaStyle = { opacity: 0.12 }; }
            return ser;
        });

        document.getElementById("chartTitle" + idx).innerText = g.title;
        document.getElementById("chartSub" + idx).innerText =
            (granularity === "month" ? "按月" : "按日") + " · " + modeText +
            (mode === "usage" ? " · 单位 " + m.unit : " · 表上读数（未乘倍率）") + ratioText;

        const option = {
            tooltip: {
                trigger: "axis",
                formatter: (params) => {
                    if (!params || !params.length) return "";
                    let html = params[0].axisValue + "<br/>";
                    params.forEach(p => {
                        const v = p.value;
                        const unitTxt = mode === "usage" ? " " + m.unit : "";
                        const txt = (v === null || v === undefined) ? "—" : Number(v).toFixed(2) + unitTxt;
                        html += `${p.marker}${FULL[p.seriesName] || p.seriesName}：${txt}<br/>`;
                    });
                    if (mode === "usage") {
                        html += `<span style="color:#9aa3b0;font-size:12px;">0 = 未抄表，已按前后底数插值均摊（标*处）</span>`;
                    }
                    return html;
                }
            },
            legend: { show: true, top: 0, type: "scroll" },
            xAxis: { type: "category", data: xData, boundaryGap: chartType !== "line", axisLabel: { fontSize: 11 } },
            yAxis: { type: "value", name: mode === "usage" ? m.unit : "表读数", splitLine: { lineStyle: { color: "#eef1f5" } } },
            dataZoom: [{ type: "slider", show: true, height: 16, bottom: 6, start: 0, end: 100 }],
            series: seriesList,
            grid: { left: 10, right: 20, top: 28, bottom: 42, containLabel: true }
        };
        chart.setOption(option, true);
    });

    resizeCharts();
}

/* 统一 resize（隐藏的面板跳过，避免 echarts 警告） */
function resizeCharts() {
    [["c1", "chartPanel1"], ["c2", "chartPanel2"]].forEach(([key, pid]) => {
        const p = document.getElementById(pid);
        if (charts[key] && p && p.style.display !== "none") charts[key].resize();
    });
}

/* ===== 合计电量（派生列，仅用电 + 用量口径）：= 车间总电表 + 60t高压1 + 60t高压2 + 30t高压 ===== */
const TOTAL_FIELD = "__total";
function hasTotalCol() { return currentKey === "elec" && mode === "usage"; }
function totalVal(row) {
    let s = 0, any = false;
    ELEC_TOTAL_COLS.forEach(c => {
        const v = cellVal(c, row);
        if (v !== null) { s += v; any = true; }
    });
    return any ? s : null;
}
function cellValEx(field, row) { return field === TOTAL_FIELD ? totalVal(row) : cellVal(field, row); }

/* ===== 表格 ===== */
function renderTableHeader() {
    const cols = METRICS[currentKey].cols;
    const headDom = document.getElementById("tableHead");
    document.getElementById("dataTable").dataset.cols = cols.length + 1 + (hasTotalCol() ? 1 : 0);
    let html = `<tr><th data-field="日期" data-sortable="1">日期<span class="sort">↕</span></th>`;
    cols.forEach(c => {
        const tip = DERIVED_TIP[c] || (ratioOf(c) === 1 ? c : `${c} · 倍率 ×${ratioOf(c)}`);
        html += `<th data-field="${c}" data-sortable="1" title="${tip}">${labelOf(c)}<span class="sort">↕</span></th>`;
    });
    if (hasTotalCol()) {
        html += `<th data-field="${TOTAL_FIELD}" data-sortable="1" title="合计电量 = 车间总电表 + 60t高压1 + 60t高压2 + 30t高压">合计电量<span class="sort">↕</span></th>`;
    }
    html += "</tr>";
    headDom.innerHTML = html;

    headDom.querySelectorAll("th[data-sortable]").forEach(th => {
        th.onclick = () => {
            const field = th.dataset.field;
            if (sortState.field === field) sortState.asc = !sortState.asc;
            else sortState = { field, asc: field === "日期" };
            renderTable();
        };
    });
}

function renderTable() {
    const cols = METRICS[currentKey].cols;
    const tb = document.getElementById("tableBody");
    const tf = document.getElementById("tableFoot");

    // 排序箭头
    document.querySelectorAll("#tableHead th").forEach(th => {
        const s = th.querySelector(".sort");
        if (!s) return;
        s.textContent = th.dataset.field === sortState.field ? (sortState.asc ? "↑" : "↓") : "↕";
    });

    if (viewRows.length === 0) {
        tb.innerHTML = `<tr class="table-empty"><td colspan="${cols.length + 1 + (hasTotalCol() ? 1 : 0)}">该日期范围内暂无数据</td></tr>`;
        tf.innerHTML = "";
        return;
    }

    // 排序副本
    let list = [...viewRows];
    if (sortState.field) {
        const f = sortState.field;
        list.sort((a, b) => {
            let cmp;
            if (f === "日期") cmp = String(a["日期"]).localeCompare(String(b["日期"]));
            else {
                const va = cellValEx(f, a), vb = cellValEx(f, b);
                cmp = (va === null ? -Infinity : va) - (vb === null ? -Infinity : vb);
            }
            return sortState.asc ? cmp : -cmp;
        });
    }

    const fmtV = v => v === null ? "—" : Number(v).toFixed(2);
    const withTotal = hasTotalCol();
    let body = "";
    list.forEach(row => {
        body += `<tr><td>${row["日期"]}</td>`;
        cols.forEach(c => {
            const v = cellVal(c, row);
            const cls = cellEst(c, row) ? "td-est" : (v === 0 ? "td-zero" : "");
            body += `<td class="${cls}">${fmtV(v)}${cls === "td-est" ? "<sup>*</sup>" : ""}</td>`;
        });
        if (withTotal) body += `<td class="td-total">${fmtV(totalVal(row))}</td>`;
        body += "</tr>";
    });
    tb.innerHTML = body;

    // 合计行（吸底）：用量口径逐列求和；底数口径不合计
    let foot = "<tr>";
    if (mode === "usage") {
        foot += `<td>合计</td>`;
        cols.forEach(c => {
            let s = 0;
            viewRows.forEach(row => { const v = cellVal(c, row); if (v !== null) s += v; });
            foot += `<td>${s.toFixed(2)}</td>`;
        });
        if (withTotal) {
            let s = 0;
            viewRows.forEach(row => { const v = totalVal(row); if (v !== null) s += v; });
            foot += `<td class="td-total">${s.toFixed(2)}</td>`;
        }
    } else {
        foot += `<td>—</td>` + cols.map(() => `<td>—</td>`).join("");
    }
    foot += "</tr>";
    tf.innerHTML = foot;
}

/* ===== 总渲染 ===== */
function render() {
    buildView();
    renderKpiCards();
    renderTableHeader();
    renderTable();
    renderChart();
}

/* ===== 初始化 ===== */
window.addEventListener('DOMContentLoaded', () => {
    charts.c1 = initChart(document.getElementById("chart1"));
    charts.c2 = initChart(document.getElementById("chart2"));

    if (window.ResizeObserver) {
        const ro = new ResizeObserver(resizeCharts);
        ro.observe(document.querySelector("#chartPanel1 .p-body"));
        ro.observe(document.querySelector("#chartPanel2 .p-body"));
    }

    document.getElementById("btnDay").onclick = () => {
        granularity = "day";
        document.getElementById("btnDay").classList.add("active");
        document.getElementById("btnMonth").classList.remove("active");
        render();
    };
    document.getElementById("btnMonth").onclick = () => {
        granularity = "month";
        document.getElementById("btnMonth").classList.add("active");
        document.getElementById("btnDay").classList.remove("active");
        render();
    };
    document.getElementById("btnUsage").onclick = () => {
        mode = "usage";
        document.getElementById("btnUsage").classList.add("active");
        document.getElementById("btnReading").classList.remove("active");
        render();
    };
    document.getElementById("btnReading").onclick = () => {
        mode = "reading";
        document.getElementById("btnReading").classList.add("active");
        document.getElementById("btnUsage").classList.remove("active");
        render();
    };
    document.getElementById("btnLine").onclick = () => { chartType = "line"; setActiveChartBtn("btnLine"); render(); };
    document.getElementById("btnBar").onclick = () => { chartType = "bar"; setActiveChartBtn("btnBar"); render(); };
    document.getElementById("btnStack").onclick = () => { chartType = "stack"; setActiveChartBtn("btnStack"); render(); };

    document.querySelectorAll(".metric-group button").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".metric-group button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentKey = btn.getAttribute("data-key");
            sortState = { field: null, asc: false };
            render();
        };
    });

    document.getElementById("btnSearch").onclick = render;
    document.getElementById("btnLayout").onclick = () => {
        const main = document.querySelector(".page-main");
        const stacked = main.classList.toggle("stack");
        document.getElementById("btnLayout").innerText = stacked ? "上下布局" : "左右布局";
        document.getElementById("btnLayout").classList.toggle("active", stacked);
        requestAnimationFrame(resizeCharts);
    };
    document.getElementById("startDate").addEventListener("change", render);
    document.getElementById("endDate").addEventListener("change", render);
    document.getElementById("btnExport").onclick = exportExcel;

    window.addEventListener('resize', resizeCharts);
    loadData();
});

function setActiveChartBtn(activeId) {
    ["btnLine", "btnBar", "btnStack"].forEach(id => {
        document.getElementById(id).classList.toggle("active", id === activeId);
    });
}

/* 导出 Excel（后端生成，口径/粒度与页面一致） */
async function exportExcel() {
    const start = document.getElementById("startDate").value;
    const end = document.getElementById("endDate").value;
    const url = `/api/export/utilities?key=${currentKey}&start=${start}&end=${end}&granularity=${granularity}&mode=${mode}`;
    try {
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) {
            let j = null;
            try { j = await resp.json(); } catch (e) {}
            throw new Error((j && (j.msg || j.error)) || `导出失败（HTTP ${resp.status}）`);
        }
        const blob = await resp.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        const gText = granularity === "month" ? "按月" : "按日";
        const mText = mode === "usage" ? "日用量" : "底数";
        a.download = `水电汽_${METRICS[currentKey].name}_${start}_至_${end}_${gText}_${mText}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    } catch (err) {
        alert(err.message || '导出失败');
    }
}
