window.myChart = null;
let rawAllData = [];
let chartType = "line";
let granularity = "day";
let currentKey = "lithium";

const keyNameMap = {
    lithium: "碳酸锂",
    sodiumSulfate: "硫酸钠",
    sodiumCarbonate: "碳酸钠",
    drain: "外排水"
};

//表格列布局配置：总固定6列，index从0~5
const tableLayoutMap = {
    lithium: [
        {title:"日期",field:"日期"},
        null,null,null,
        {title:"碳酸锂车间产出",field:"碳酸锂车间产出"},
        {title:"碳酸锂仓库出库",field:"碳酸锂仓库出库"}
    ],
    sodiumSulfate: [
        {title:"日期",field:"日期"},
        {title:"硫酸钠日累计",field:"硫酸钠"},
        {title:"干料",field:"硫酸钠干料"},
        {title:"湿料",field:"硫酸钠湿料"},
        {title:"杂质料",field:"硫酸钠杂质料"},
        {title:"落地料",field:"硫酸钠落地料"}
    ],
    sodiumCarbonate: [
        {title:"日期",field:"日期"},
        null,null,null,
        {title:"碳酸钠车间消耗",field:"碳酸钠车间消耗"},
        {title:"碳酸钠仓库出库",field:"碳酸钠仓库出库"}
    ],
    drain: [
        {title:"日期",field:"日期"},
        null,null,null,null,
        {title:"外排水量",field:"外排水量"}
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
        // 新增曲线：当日碳酸钠车间消耗 / 当日碳酸锂车间产出
        { field: "ratio_na_li", name: "碳酸钠/碳酸锂消耗比", isRatio:true }
    ],
    drain: [
        { field: "外排水量", name: "外排水量" }
    ]
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
        const resp = await fetch("/api/output/all");
        if (!resp.ok) {
            console.error("接口返回错误", resp.status);
            alert("接口访问失败，检查后端路由地址");
            return;
        }
        rawAllData = await resp.json();
        console.log("拿到后端数据：", rawAllData);
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
                "碳酸锂仓库出库":0,
                "碳酸锂车间产出":0,
                "硫酸钠":0,
                "硫酸钠干料":0,
                "硫酸钠湿料":0,
                "硫酸钠杂质料":0,
                "硫酸钠落地料":0,
                "碳酸钠车间消耗":0,
                "碳酸钠仓库出库":0,
                "外排水量":0
            }
        }
        map[y]["碳酸锂仓库出库"] += Number(row["碳酸锂仓库出库"] || 0);
        map[y]["碳酸锂车间产出"] += Number(row["碳酸锂车间产出"] || 0);
        map[y]["硫酸钠"] += Number(row["硫酸钠"] || 0);
        map[y]["硫酸钠干料"] += Number(row["硫酸钠干料"] || 0);
        map[y]["硫酸钠湿料"] += Number(row["硫酸钠湿料"] || 0);
        map[y]["硫酸钠杂质料"] += Number(row["硫酸钠杂质料"] || 0);
        map[y]["硫酸钠落地料"] += Number(row["硫酸钠落地料"] || 0);
        map[y]["碳酸钠车间消耗"] += Number(row["碳酸钠车间消耗"] || 0);
        map[y]["碳酸钠仓库出库"] += Number(row["碳酸钠仓库出库"] || 0);
        map[y]["外排水量"] += Number(row["外排水量"] || 0);
    })
    return Object.values(map);
}

function renderStatDisplay(currentKey){
    const statLiOutput = document.getElementById("statLithiumOutput");
    const statLiOut = document.getElementById("statLithiumOut");
    const statLiDiff = document.getElementById("statLithiumDiff");
    const statNormalSum = document.getElementById("statNormalSum");
    const statAvgRatio = document.getElementById("statAvgRatio");
    // 硫酸钠：干、湿、杂、落地四项各自合计（默认隐藏，仅硫酸钠页显示）
    const statSulfateDry = document.getElementById("statSulfateDry");
    const statSulfateWet = document.getElementById("statSulfateWet");
    const statSulfateImpurity = document.getElementById("statSulfateImpurity");
    const statSulfateLanded = document.getElementById("statSulfateLanded");
    statSulfateDry.style.display = "none";
    statSulfateWet.style.display = "none";
    statSulfateImpurity.style.display = "none";
    statSulfateLanded.style.display = "none";

    // 碳酸锂、碳酸钠、硫酸钠：dual双栏+差值；外排水走normal总值
    if(currentKey === "lithium" || currentKey === "sodiumCarbonate" || currentKey === "sodiumSulfate"){
        statLiOutput.style.display = "block";
        statLiOut.style.display = "block";
        statLiDiff.style.display = "block";
        statNormalSum.style.display = "none";
        statAvgRatio.style.display = "none";
        if(currentKey === "lithium"){
            statLiOutput.firstChild.textContent = "车间产出合计：";
            statLiOut.firstChild.textContent = "仓库出库合计：";
            statLiDiff.firstChild.textContent = "差值(出库‑产出)：";
        }else if(currentKey === "sodiumCarbonate"){
            statLiOutput.firstChild.textContent = "车间消耗合计：";
            statLiOut.firstChild.textContent = "仓库出库合计：";
            statLiDiff.firstChild.textContent = "差值(出库‑消耗)：";
            // 碳酸钠页面，展示消耗平均值
            statAvgRatio.style.display = "block";
        }else if(currentKey === "sodiumSulfate"){
            statLiOutput.firstChild.textContent = "硫酸钠日累计合计：";
            statLiOut.firstChild.textContent = "料总合计(干+湿+杂+落地)：";
            statLiDiff.firstChild.textContent = "差值(日累计‑料总和)：";
            statSulfateDry.style.display = "block";
            statSulfateWet.style.display = "block";
            statSulfateImpurity.style.display = "block";
            statSulfateLanded.style.display = "block";
        }
    }else{
        statLiOutput.style.display = "none";
        statLiOut.style.display = "none";
        statLiDiff.style.display = "none";
        statAvgRatio.style.display = "none";
        statNormalSum.style.display = "block";
    }
}

function calcStat(list, key) {
    const fields = seriesConfig[key].map(i=>i.field);
    if(key === "lithium"){
        let sumOutput = 0, sumOut =0;
        list.forEach(r=>{
            sumOutput += Number(r["碳酸锂车间产出"]||0);
            sumOut += Number(r["碳酸锂仓库出库"]||0);
        })
        const diff = sumOut - sumOutput;
        return {
            type:"dual",
            sumOutput:sumOutput.toFixed(2),
            sumOut:sumOut.toFixed(2),
            diff: diff.toFixed(2),
            avgRatio: null
        }
    }else if(key === "sodiumCarbonate"){
        let sumOutput = 0, sumOut =0, sumLiTotal=0;
        list.forEach(r=>{
            sumOutput += Number(r["碳酸钠车间消耗"]||0);
            sumOut += Number(r["碳酸钠仓库出库"]||0);
            sumLiTotal += Number(r["碳酸锂车间产出"]||0);
        })
        const diff = sumOut - sumOutput;
        // 平均值计算，防止除0
        let avgRatio = 0;
        if(sumLiTotal > 0){
            avgRatio = sumOutput / sumLiTotal;
        }
        return {
            type:"dual",
            sumOutput:sumOutput.toFixed(2),
            sumOut:sumOut.toFixed(2),
            diff: diff.toFixed(2),
            avgRatio: avgRatio.toFixed(2)
        }
    }else if(key === "sodiumSulfate"){
        // 硫酸钠：sumOutput=硫酸钠(日累计总合计)；sumOut=干+湿+杂+落地料总和
        let sumOutput = 0;
        let sumDry = 0;
        let sumWet = 0;
        let sumImpurity = 0;
        let sumLanded = 0;
        list.forEach(r=>{
            sumOutput += Number(r["硫酸钠"]||0);
            sumDry += Number(r["硫酸钠干料"]||0);
            sumWet += Number(r["硫酸钠湿料"]||0);
            sumImpurity += Number(r["硫酸钠杂质料"]||0);
            sumLanded += Number(r["硫酸钠落地料"]||0);
        })
        const sumOut = sumDry + sumWet + sumImpurity + sumLanded;
        const diff = sumOutput - sumOut;
        return {
            type:"dual",
            sumOutput:sumOutput.toFixed(2),
            sumOut:sumOut.toFixed(2),
            sumDry:sumDry.toFixed(2),
            sumWet:sumWet.toFixed(2),
            sumImpurity:sumImpurity.toFixed(2),
            sumLanded:sumLanded.toFixed(2),
            diff: diff.toFixed(2),
            avgRatio: null
        }
    }else{
        let sum =0;
        list.forEach(r=>{
            fields.forEach(f=> sum += Number(r[f]||0));
        })
        return {
            type:"normal",
            sum:sum.toFixed(2),
            avgRatio:null
        }
    }
}

//动态渲染表头【修改：th增加居中样式】
function renderTableHeader(layout){
    const headDom = document.getElementById("tableHead");
    let trHtml = "<tr>";
    layout.forEach(item=>{
        if(item){
            trHtml += `<th style="text-align:center;">${item.title}</th>`;
        }else{
            trHtml += `<th style="text-align:center;"></th>`;
        }
    })
    trHtml += "</tr>";
    headDom.innerHTML = trHtml;
}

//动态渲染表格行【修改：创建td强制设置居中】
function renderTableBody(dataList,layout){
    const tb = document.getElementById("tableBody");
    tb.innerHTML = "";
    if(dataList.length === 0){
        let trHtml="<tr>";
        for(let i=0;i<6;i++) trHtml += "<td style='text-align:center;'></td>";
        trHtml += "</tr>";
        tb.innerHTML = trHtml;
        return;
    }
    dataList.forEach(r=>{
        const tr = document.createElement("tr");
        layout.forEach(cfg=>{
            const td = document.createElement("td");
            td.style.textAlign = "center";
            if(cfg){
                const val = r[cfg.field];
                if(cfg.field === "日期"){
                    td.innerText = val||"";
                }else{
                    td.innerText = Number(val||0).toFixed(2);
                }
            }else{
                td.innerText = "";
            }
            tr.appendChild(td);
        })
        tb.appendChild(tr);
    })
}

function render() {
    console.log("执行render，原始数据长度", rawAllData.length);
    if (rawAllData.length === 0) {
        const layout = tableLayoutMap[currentKey];
        renderTableHeader(layout);
        renderTableBody([],layout);
        myChart.setOption({ series: [] }, true);
        return;
    }
    const sDate = document.getElementById("startDate").value;
    const eDate = document.getElementById("endDate").value;
    let data = filterByDate(rawAllData, sDate, eDate);

    // 给每行预先计算：碳酸钠车间消耗 / 碳酸锂车间产出
    data = data.map(d=>{
        const naConsume = Number(d["碳酸钠车间消耗"] ||0);
        const liOutput = Number(d["碳酸锂车间产出"] ||0);
        let ratio = 0;
        if(liOutput > 0){
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
    document.getElementById("curMetricName").innerText = keyNameMap[currentKey];
    renderStatDisplay(currentKey);
    const stat = calcStat(data, currentKey);
    if(stat.type === "dual"){
        document.getElementById("lithiumOutputSum").innerText = stat.sumOutput;
        document.getElementById("lithiumOutSum").innerText = stat.sumOut;
        document.getElementById("lithiumDiffVal").innerText = stat.diff;
        // 硫酸钠：回填干、湿、杂、落地四项各自合计
        if(currentKey === "sodiumSulfate"){
            document.getElementById("sulfateDrySum").innerText = stat.sumDry;
            document.getElementById("sulfateWetSum").innerText = stat.sumWet;
            document.getElementById("sulfateImpuritySum").innerText = stat.sumImpurity;
            document.getElementById("sulfateLandedSum").innerText = stat.sumLanded;
        }
        // 回填消耗平均值
        if(stat.avgRatio !== null){
            document.getElementById("avgRatioVal").innerText = stat.avgRatio;
        }
    }else{
        document.getElementById("sumVal").innerText = stat.sum;
    }

    //动态表格
    const layout = tableLayoutMap[currentKey];
    renderTableHeader(layout);
    renderTableBody(data,layout);

    // 渲染多系列图表（风格对齐 inventory 盘点页：平滑曲线 + 浅面积 + 指定配色）
    const CHART_COLORS = ["#5b8ff9", "#2f8f6e", "#e0a030", "#d9534f"];
    const xAxisData = data.map(d => d["日期"]);
    const seriesList = seriesConfig[currentKey].map((cfg, idx)=>{
        const ser = {
            name: cfg.name,
            type: chartType,
            data: data.map(d=>Number(d[cfg.field]||0)),
            itemStyle: { color: CHART_COLORS[idx % CHART_COLORS.length] }
        }
        if (chartType === "line") {
            ser.smooth = true;
            ser.areaStyle = { opacity: 0.15 };
        }
        // 如果是比例曲线，使用右侧Y轴
        if(cfg.isRatio){
            ser.yAxisIndex = 1;
        }
        return ser;
    });

    const option = {
        tooltip: { trigger: "axis" },
        legend: { show: true, top: 0 },
        xAxis: { type: "category", data: xAxisData, boundaryGap: false, axisLabel: { fontSize: 11 } },
        yAxis: [
            { type: "value", name:"产量/消耗", splitLine: { lineStyle: { color: "#eef1f5" } } },
            { type: "value", name:"比值", position:"right", splitLine: { show: false } }
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
window.addEventListener('DOMContentLoaded', ()=>{
    window.myChart = echarts.init(document.getElementById("chart"));

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
        document.getElementById("btnLine").classList.add("active");
        document.getElementById("btnBar").classList.remove("active");
        render();
    }
    document.getElementById("btnBar").onclick = () => {
        chartType = "bar";
        document.getElementById("btnBar").classList.add("active");
        document.getElementById("btnLine").classList.remove("active");
        render();
    }
    document.querySelectorAll(".metric-group button").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".metric-group button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentKey = btn.getAttribute("data-key");
            render();
        }
    })
    document.getElementById("btnSearch").onclick = () => {
        render();
    }
    window.addEventListener('resize', () => {
        myChart.resize();
    })
    loadData();
})


