window.myChart = null;
let rawAllData = [];
let chartType = "line";
let granularity = "day";
let currentKey = "lithium";
let viewData = [];                       // 当前筛选+聚合后的数据（日期正序），图表用
let sortState = { field: null, asc: true }; // 表格排序状态：null=默认日期正序

const keyNameMap = {
    lithium: "碳酸锂",
    sodiumSulfate: "硫酸钠",
    sodiumCarbonate: "碳酸钠",
    drain: "外排水"
};

// 表格列布局（改版：列数可变 + 支持 diff 伪列 = 差值）
const tableLayoutMap = {
    lithium: [
        { title: "日期", field: "日期" },
        { title: "碳酸锂车间产出", field: "碳酸锂车间产出" },
        { title: "碳酸锂仓库出库", field: "碳酸锂仓库出库" },
        { title: "当日差值", field: "diff", isDiff: true }
    ],
    sodiumSulfate: [
        { title: "日期", field: "日期" },
        { title: "硫酸钠日累计", field: "硫酸钠" },
        { title: "干料", field: "硫酸钠干料" },
        { title: "湿料", field: "硫酸钠湿料" },
        { title: "杂质料", field: "硫酸钠杂质料" },
        { title: "落地料", field: "硫酸钠落地料" },
        { title: "当日差值", field: "diff", isDiff: true }
    ],
    sodiumCarbonate: [
        { title: "日期", field: "日期" },
        { title: "碳酸钠车间消耗", field: "碳酸钠车间消耗" },
        { title: "碳酸钠仓库出库", field: "碳酸钠仓库出库" },
        { title: "当日差值", field: "diff", isDiff: true }
    ],
    drain: [
        { title: "日期", field: "日期" },
        { title: "外排水量", field: "外排水量" }
    ]
};

// 每个key对应的多系列配置
const seriesConfig = {
    lithium: [
        { field: "碳酸锂车间产出", name: "碳酸锂车间产出" },
        { field: "碳酸锂仓库出库", name: "碳酸锂仓库出库" }
    ],
    sodiumSulfate: [
        { field: "硫酸钠干料", name: "硫酸钠干料" },
        { field: "硫酸钠湿料", name: "硫酸钠湿料" },
        { field: "硫酸钠杂质料", name: "硫酸钠杂质料" },
        { field: "硫酸钠落地料", name: "硫酸钠落地料" }
    ],
    sodiumCarbonate: [
        { field: "碳酸钠车间消耗", name: "碳酸钠车间消耗" },
        { field: "碳酸钠仓库出库", name: "碳酸钠仓库出库" },
        { field: "ratio_na_li", name: "碳酸钠/碳酸锂消耗比", isRatio: true }
    ],
    drain: [
        { field: "外排水量", name: "外排水量" }
    ]
};

// 差值计算规则：出库 − 产出/消耗（硫酸钠为 日累计 − 四料和）
const diffRule = {
    lithium: r => Number(r["碳酸锂仓库出库"] || 0) - Number(r["碳酸锂车间产出"] || 0),
    sodiumCarbonate: r => Number(r["碳酸钠仓库出库"] || 0) - Number(r["碳酸钠车间消耗"] || 0),
    sodiumSulfate: r => Number(r["硫酸钠"] || 0) - (Number(r["硫酸钠干料"] || 0) + Number(r["硫酸钠湿料"] || 0) + Number(r["硫酸钠杂质料"] || 0) + Number(r["硫酸钠落地料"] || 0)),
    drain: null
};

// 月度计划对应的指标字段（/api/plan/get 返回 碳酸锂 / 硫酸钠）
const planFieldMap = {
    lithium: { planKey: "碳酸锂", field: "碳酸锂车间产出" },
    sodiumSulfate: { planKey: "硫酸钠", field: "硫酸钠" }
};

function getLastDayOfPrevMonth() {
    // 默认起始日 = 上月最后一天：本月1号往前回退1天（跨年自动正确）
    const d = new Date();
    d.setDate(1);   // 本月1号
    d.setDate(0);   // 上月最后一天
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function getTodayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function loadData() {
    try {
        rawAllData = await request.get("/api/output/all");
        document.getElementById("startDate").value = getLastDayOfPrevMonth();
        document.getElementById("endDate").value = getTodayStr();
        render();
    } catch (err) {
        console.error("加载数据异常", err);
        alert("无法获取后端数据，请确认Flask服务已启动，接口地址正确");
    }
}

function parseDateStr(s) {
    return new Date(s.replace(/\//g, "-"));
}

function filterByDate(list, startStr, endStr) {
    if (!startStr && !endStr) return list;
    return list.filter(item => {
        const d = parseDateStr(item["日期"]);
        let ok = true;
        if (startStr) ok = ok && (d >= new Date(startStr));
        if (endStr) ok = ok && (d <= new Date(endStr));
        return ok;
    })
}

// 按月聚合，字段按月累加
function groupByMonth(list) {
    const map = {};
    list.forEach(row => {
        const y = row["日期"].substring(0, 7);
        if (!map[y]) {
            map[y] = {
                "日期": y,
                "碳酸锂仓库出库": 0,
                "碳酸锂车间产出": 0,
                "硫酸钠": 0,
                "硫酸钠干料": 0,
                "硫酸钠湿料": 0,
                "硫酸钠杂质料": 0,
                "硫酸钠落地料": 0,
                "碳酸钠车间消耗": 0,
                "碳酸钠仓库出库": 0,
                "外排水量": 0
            }
        }
        for (const f of ["碳酸锂仓库出库", "碳酸锂车间产出", "硫酸钠", "硫酸钠干料", "硫酸钠湿料",
            "硫酸钠杂质料", "硫酸钠落地料", "碳酸钠车间消耗", "碳酸钠仓库出库", "外排水量"]) {
            map[y][f] += Number(row[f] || 0);
        }
    })
    return Object.values(map);
}

// ===== KPI 卡片渲染（替代原 renderStatDisplay + calcStat 的 DOM 回填） =====
function renderKpiCards(data) {
    const $ = id => document.getElementById(id);
    const fmt = v => Number(v || 0).toFixed(2);
    // 日期区间显示
    $("kpiRange").innerText = `${$("startDate").value} ~ ${$("endDate").value}`;
    $("curMetricName").innerText = keyNameMap[currentKey];

    // 先全部隐藏，按指标逐个打开
    $("kpiACard").style.display = "none";
    $("kpiBCard").style.display = "none";
    $("kpiSubCard").style.display = "none";
    $("kpiDiffCard").style.display = "none";
    $("kpiPlanCard").style.display = "none";

    const sum = f => data.reduce((s, r) => s + Number(r[f] || 0), 0);

    if (currentKey === "drain") {
        // 外排水：只显示总值
        $("kpiALabel").innerText = "外排水量总值";
        $("kpiAValue").innerHTML = fmt(sum("外排水量")) + "<small>t</small>";
        $("kpiACard").style.display = "block";
        return;
    }

    // 碳酸锂 / 碳酸钠 / 硫酸钠：A/B 双合计 + 差值
    let aField, bField, aLabel, bLabel, diffLabel;
    if (currentKey === "lithium") {
        aField = "碳酸锂车间产出"; bField = "碳酸锂仓库出库";
        aLabel = "车间产出合计"; bLabel = "仓库出库合计"; diffLabel = "差值(出库−产出)";
    } else if (currentKey === "sodiumCarbonate") {
        aField = "碳酸钠车间消耗"; bField = "碳酸钠仓库出库";
        aLabel = "车间消耗合计"; bLabel = "仓库出库合计"; diffLabel = "差值(出库−消耗)";
    } else {
        aField = "硫酸钠"; bField = null;
        aLabel = "硫酸钠日累计合计"; bLabel = "料总合计(干+湿+杂+落地)"; diffLabel = "差值(日累计−料总和)";
    }

    // 硫酸钠不展示「日累计合计」卡片（用户要求卡片数量减一），其余指标正常展示
    if (currentKey !== "sodiumSulfate") {
        $("kpiALabel").innerText = aLabel;
        $("kpiAValue").innerHTML = fmt(sum(aField)) + "<small>t</small>";
        $("kpiACard").style.display = "block";
    }

    let sumB;
    if (currentKey === "sodiumSulfate") {
        sumB = sum("硫酸钠干料") + sum("硫酸钠湿料") + sum("硫酸钠杂质料") + sum("硫酸钠落地料");
        $("kpiBLabel").innerText = bLabel;
        $("kpiBValue").innerHTML = fmt(sumB) + "<small>t</small>";
        $("kpiBCard").style.display = "block";
        // 四料分项卡片
        const dry = sum("硫酸钠干料"), wet = sum("硫酸钠湿料"),
            imp = sum("硫酸钠杂质料"), lan = sum("硫酸钠落地料");
        $("kpiSubValue").innerHTML =
            `干 ${fmt(dry)} / 湿 ${fmt(wet)} / 杂 ${fmt(imp)} / 落地 ${fmt(lan)}`;
        $("kpiSubCard").style.display = "block";
    } else {
        sumB = sum(bField);
        $("kpiBLabel").innerText = bLabel;
        $("kpiBValue").innerHTML = fmt(sumB) + "<small>t</small>";
        $("kpiBCard").style.display = "block";
    }

    const diff = sumB - Number(sum(aField));
    $("kpiDiffLabel").innerText = diffLabel;
    const diffDom = $("kpiDiffValue");
    diffDom.innerHTML = (diff > 0 ? "+" : "") + fmt(diff) + "<small>t</small>";
    diffDom.classList.toggle("diff-neg", diff < 0);
    diffDom.classList.toggle("diff-pos", diff > 0);
    $("kpiDiffCard").style.display = "block";
}

// ===== 月度计划完成率（/api/plan/get，仅碳酸锂 / 硫酸钠） =====
async function renderPlanCard() {
    const $ = id => document.getElementById(id);
    const cfg = planFieldMap[currentKey];
    if (!cfg) { $("kpiPlanCard").style.display = "none"; return; }

    // 计划月份 = 结束日期所在月；实际完成 = 该月全量数据（不受起始日期影响）
    const endVal = $("endDate").value;               // yyyy-mm-dd
    const monthKey = endVal.slice(0, 7);             // yyyy-mm
    const monthSlash = monthKey.replace("-", "/");   // yyyy/mm
    const actual = rawAllData
        .filter(r => (r["日期"] || "").startsWith(monthSlash))
        .reduce((s, r) => s + Number(r[cfg.field] || 0), 0);

    let plan = 0;
    try {
        const d = await request.get(`/api/plan/get?month=${monthKey}`);
        plan = Number(d[cfg.planKey] || 0);
    } catch (e) { /* 接口异常时完成率卡片显示无计划 */ }

    $("kpiPlanLabel").innerText = `${monthKey.replace("-", "年")}月计划完成率`;
    $("kpiPlanCard").style.display = "block";
    if (plan > 0) {
        const pct = Math.min(actual / plan * 100, 100);
        $("planFill").style.width = pct.toFixed(1) + "%";
        $("planPct").innerText = (actual / plan * 100).toFixed(0) + "%";
        $("planFoot").innerText = `计划 ${plan.toFixed(2)} t · 已完成 ${actual.toFixed(2)} t`;
    } else {
        $("planFill").style.width = "0%";
        $("planPct").innerText = "-";
        $("planFoot").innerText = `本月无计划数据 · 已完成 ${actual.toFixed(2)} t`;
    }
}

// ===== 表头渲染（可排序） =====
function renderTableHeader(layout) {
    const headDom = document.getElementById("tableHead");
    // 列数写入表格，CSS 据此自适应首列宽度
    document.getElementById("dataTable").dataset.cols = layout.length;
    let trHtml = "<tr>";
    layout.forEach(item => {
        const sortable = item.field !== "diff";
        trHtml += `<th class="${item.isDiff ? "col-sep" : ""}" data-field="${item.field}" ${sortable ? 'data-sortable="1"' : ""}>${item.title}`;
        if (sortable) trHtml += `<span class="sort">↕</span>`;
        trHtml += `</th>`;
    })
    trHtml += "</tr>";
    headDom.innerHTML = trHtml;

    // 排序点击事件
    headDom.querySelectorAll("th[data-sortable]").forEach(th => {
        th.onclick = () => {
            const field = th.dataset.field;
            if (sortState.field === field) sortState.asc = !sortState.asc;
            else sortState = { field, asc: field === "日期" }; // 数值列默认降序（先看最大值），日期列默认升序
            renderTable();
        };
    });
}

// ===== 表格渲染（含排序、差值列、合计行、空态） =====
function renderTable() {
    const layout = tableLayoutMap[currentKey];
    const tb = document.getElementById("tableBody");
    const tf = document.getElementById("tableFoot");
    const rule = diffRule[currentKey];

    // 排序指示箭头
    document.querySelectorAll("#tableHead th").forEach(th => {
        const s = th.querySelector(".sort");
        if (!s) return;
        s.textContent = th.dataset.field === sortState.field ? (sortState.asc ? "↑" : "↓") : "↕";
    });

    if (viewData.length === 0) {
        tb.innerHTML = `<tr class="table-empty"><td colspan="${layout.length}">该日期范围内暂无数据</td></tr>`;
        tf.innerHTML = "";
        return;
    }

    // 排序副本（不影响图表用的 viewData 顺序）
    let list = [...viewData];
    if (sortState.field) {
        const f = sortState.field;
        list.sort((a, b) => {
            const va = f === "日期" ? a[f] : Number(a[f] || 0);
            const vb = f === "日期" ? b[f] : Number(b[f] || 0);
            const cmp = f === "日期" ? String(va).localeCompare(String(vb)) : va - vb;
            return sortState.asc ? cmp : -cmp;
        });
    }

    tb.innerHTML = "";
    list.forEach(r => {
        const tr = document.createElement("tr");
        layout.forEach(cfg => {
            const td = document.createElement("td");
            if (cfg.isDiff) {
                const v = rule ? rule(r) : 0;
                const cls = Math.abs(v) < 0.0001 ? "zero" : (v < 0 ? "neg" : "pos");
                td.classList.add("col-sep");
                td.innerHTML = `<span class="pill ${cls}">${v > 0 ? "+" : ""}${v.toFixed(2)}</span>`;
            } else if (cfg.field === "日期") {
                td.innerText = r[cfg.field] || "";
            } else {
                td.innerText = Number(r[cfg.field] || 0).toFixed(2);
            }
            tr.appendChild(td);
        })
        tb.appendChild(tr);
    })

    // 合计行（吸底）：各数值列求和，差值列求和
    let footHtml = "<tr>";
    layout.forEach((cfg, idx) => {
        if (idx === 0) { footHtml += `<td>合计</td>`; return; }
        if (cfg.isDiff) {
            const total = rule ? list.reduce((s, r) => s + rule(r), 0) : 0;
            const cls = Math.abs(total) < 0.0001 ? "" : (total < 0 ? "tf-neg" : "tf-pos");
            footHtml += `<td class="col-sep ${cls}">${total > 0 ? "+" : ""}${total.toFixed(2)}</td>`;
        } else {
            const total = list.reduce((s, r) => s + Number(r[cfg.field] || 0), 0);
            footHtml += `<td>${total.toFixed(2)}</td>`;
        }
    });
    footHtml += "</tr>";
    tf.innerHTML = footHtml;
}

function render() {
    // 卡片标题随指标/粒度联动
    const units = { lithium: "t", sodiumSulfate: "t", sodiumCarbonate: "t", drain: "m³" };
    document.getElementById("chartTitle").innerText = keyNameMap[currentKey] + "趋势";
    document.getElementById("chartSub").innerText =
        (granularity === "month" ? "按月" : "按日") + " · 单位 " + (units[currentKey] || "t");

    if (rawAllData.length === 0) {
        viewData = [];
        renderTableHeader(tableLayoutMap[currentKey]);
        renderTable();
        myChart.setOption({ series: [] }, true);
        return;
    }
    const sDate = document.getElementById("startDate").value;
    const eDate = document.getElementById("endDate").value;
    let data = filterByDate(rawAllData, sDate, eDate);

    // 给每行预先计算：碳酸钠车间消耗 / 碳酸锂车间产出
    data = data.map(d => {
        const naConsume = Number(d["碳酸钠车间消耗"] || 0);
        const liOutput = Number(d["碳酸锂车间产出"] || 0);
        let ratio = 0;
        if (liOutput > 0) {
            ratio = naConsume / liOutput;
        }
        return {
            ...d,
            ratio_na_li: parseFloat(ratio.toFixed(2))
        }
    })

    if (granularity === "month") {
        data = groupByMonth(data);
    }

    viewData = data;
    renderKpiCards(data);
    renderPlanCard();   // 异步，不阻塞图表

    //动态表格
    renderTableHeader(tableLayoutMap[currentKey]);
    renderTable();

    // 渲染多系列图表（蓝色调主色 #2b579a，辅色蓝绿/橙/红）
    const CHART_COLORS = ["#2b579a", "#1d9e75", "#e0a030", "#d9534f"];
    const xAxisData = data.map(d => d["日期"]);
    const isStack = chartType === "stack";
    const seriesList = seriesConfig[currentKey].map((cfg, idx) => {
        const ser = {
            name: cfg.name,
            type: isStack ? "bar" : chartType,
            data: data.map(d => Number(d[cfg.field] || 0)),
            itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] }
        }
        if (isStack) {
            ser.stack = "total";
        }
        if (chartType === "line") {
            ser.smooth = true;
            ser.areaStyle = { opacity: 0.15 };
        }
        // 如果是比例曲线，使用右侧Y轴
        if (cfg.isRatio) {
            ser.yAxisIndex = 1;
            if (isStack) { ser.type = "line"; delete ser.stack; } // 比例曲线不参与堆叠
        }
        return ser;
    });

    const option = {
        tooltip: {
            trigger: "axis",
            formatter: (params) => {
                if (!params || !params.length) return "";
                let html = params[0].axisValue + "<br/>";
                params.forEach(p => {
                    html += `${p.marker}${p.seriesName}：${Number(p.value).toFixed(2)}<br/>`;
                });
                // 差值提示（月粒度时为当月差值）
                const rule = diffRule[currentKey];
                if (rule) {
                    const row = viewData[params[0].dataIndex];
                    if (row) {
                        const v = rule(row);
                        const c = v < 0 ? "#e74c3c" : "#2f9e6b";
                        html += `<span style="color:${c};font-weight:600;">差值：${v > 0 ? "+" : ""}${v.toFixed(2)}</span>`;
                    }
                }
                return html;
            }
        },
        legend: { show: true, top: 0 },
        xAxis: { type: "category", data: xAxisData, boundaryGap: chartType !== "line", axisLabel: { fontSize: 11 } },
        yAxis: [
            { type: "value", name: "产量/消耗", splitLine: { lineStyle: { color: "#eef1f5" } } },
            { type: "value", name: "比值", position: "right", splitLine: { show: false } }
        ],
        dataZoom: [
            { type: "slider", show: true, height: 20, bottom: 10, start: 0, end: 100 }
        ],
        series: seriesList,
        grid: { left: 10, right: 20, top: 30, bottom: 60, containLabel: true }
    }
    myChart.setOption(option, true);
}

//页面初始化
window.addEventListener('DOMContentLoaded', () => {
    window.myChart = initChart(document.getElementById("chart"));

    // 卡片高度随 KPI 行/窗口变化，用 ResizeObserver 保证图表跟着缩放
    if (window.ResizeObserver) {
        new ResizeObserver(() => {
            if (window.myChart) window.myChart.resize();
        }).observe(document.querySelector(".p-body"));
    }

    document.getElementById("btnDay").onclick = () => {
        granularity = "day";
        document.getElementById("btnDay").classList.add("active");
        document.getElementById("btnMonth").classList.remove("active");
        render();
    }
    document.getElementById("btnMonth").onclick = () => {
        granularity = "month";
        document.getElementById("btnMonth").classList.add("active");
        document.getElementById("btnDay").classList.remove("active");
        render();
    }
    document.getElementById("btnLine").onclick = () => {
        chartType = "line";
        setActiveChartBtn("btnLine");
        render();
    }
    document.getElementById("btnBar").onclick = () => {
        chartType = "bar";
        setActiveChartBtn("btnBar");
        render();
    }
    document.getElementById("btnStack").onclick = () => {
        chartType = "stack";
        setActiveChartBtn("btnStack");
        render();
    }
    document.querySelectorAll(".metric-group button").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".metric-group button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentKey = btn.getAttribute("data-key");
            sortState = { field: null, asc: true }; // 切指标后恢复默认排序
            render();
        }
    })
    document.getElementById("btnSearch").onclick = () => {
        render();
    }
    // 改版：日期变化自动刷新（数据已在前端，直接重渲染）
    document.getElementById("startDate").addEventListener("change", render);
    document.getElementById("endDate").addEventListener("change", render);

    document.getElementById("btnExport").onclick = () => {
        exportExcel();
    }
    window.addEventListener('resize', () => {
        myChart.resize();
    })
    loadData();
})

function setActiveChartBtn(activeId) {
    ["btnLine", "btnBar", "btnStack"].forEach(id => {
        document.getElementById(id).classList.toggle("active", id === activeId);
    });
}

/* 导出 Excel：按当前指标/日期范围/粒度请求后端生成 xlsx 并下载 */
async function exportExcel() {
    const start = document.getElementById("startDate").value;
    const end = document.getElementById("endDate").value;
    const url = `/api/export/output?key=${currentKey}&start=${start}&end=${end}&granularity=${granularity}`;
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
        a.download = `${keyNameMap[currentKey]}_${start}_至_${end}_${gText}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    } catch (err) {
        alert(err.message || '导出失败');
    }
}
