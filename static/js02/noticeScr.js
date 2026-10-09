// 信息公示页面JS
let currentMonth = "";

$(function(){
    // 默认当月
    const now = new Date();
    const defaultMonth = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
    $("#monthSelect").val(defaultMonth);
    currentMonth = defaultMonth;

    // 页面初始化自动加载一次数据
    const defaultBanzu = $("#banzuSelect").val();
    loadNoticeData(currentMonth, defaultBanzu);

    // 搜索按钮点击
    $("#noticeSearchBtn").on("click",function(){
        currentMonth = $("#monthSelect").val();
        const banzu = $("#banzuSelect").val();
        loadNoticeData(currentMonth,banzu);
    });
})

async function loadNoticeData(month,banzu){
    // 1、读取月度计划
    const planRes = await request.get(`/api/plan/get?month=${month}`);
    // 2、各班当月汇总产量
    const sumRes = await request.get(`/api/notice/sum?month=${month}`);
    //3、明细表格
    const listRes = await request.get(`/api/notice/list?month=${month}&banzu=${banzu}`);

    // 更新顶部标题
    $("#planTitle").html(`${month.replace("-","年")}月计划:`);
    $("#planLi").text(planRes.碳酸锂.toFixed(1));
    $("#planNa").text(planRes.硫酸钠.toFixed(1));

    // 每班均分计划 = 总计划 / 3
    const liPlanSingle = planRes.碳酸锂 / 3;
    const naPlanSingle = planRes.硫酸钠 / 3;

    // 甲班
    $("#jiaLi").text(sumRes.甲.sum_li.toFixed(1));
    $("#jiaNa").text(sumRes.甲.sum_na.toFixed(1));
    const jiaLiRate = liPlanSingle>0 ? (sumRes.甲.sum_li / liPlanSingle *100).toFixed(1) :0;
    const jiaNaRate = naPlanSingle>0 ? (sumRes.甲.sum_na / naPlanSingle *100).toFixed(1) :0;
    $("#jiaLiRate").text(jiaLiRate+"%");
    $("#jiaNaRate").text(jiaNaRate+"%");

    // 乙班
    $("#yiLi").text(sumRes.乙.sum_li.toFixed(1));
    $("#yiNa").text(sumRes.乙.sum_na.toFixed(1));
    const yiLiRate = liPlanSingle>0 ? (sumRes.乙.sum_li / liPlanSingle *100).toFixed(1) :0;
    const yiNaRate = naPlanSingle>0 ? (sumRes.乙.sum_na / naPlanSingle *100).toFixed(1) :0;
    $("#yiLiRate").text(yiLiRate+"%");
    $("#yiNaRate").text(yiNaRate+"%");

    //丙班
    $("#bingLi").text(sumRes.丙.sum_li.toFixed(1));
    $("#bingNa").text(sumRes.丙.sum_na.toFixed(1));
    const bingLiRate = liPlanSingle>0 ? (sumRes.丙.sum_li / liPlanSingle *100).toFixed(1) :0;
    const bingNaRate = naPlanSingle>0 ? (sumRes.丙.sum_na / naPlanSingle *100).toFixed(1) :0;
    $("#bingLiRate").text(bingLiRate+"%");
    $("#bingNaRate").text(bingNaRate+"%");

    // ========== 新增：计算总产量 + 超产/欠产 ==========
    // 总产量 = 甲+乙+丙
    const totalLi = sumRes.甲.sum_li + sumRes.乙.sum_li + sumRes.丙.sum_li;
    const totalNa = sumRes.甲.sum_na + sumRes.乙.sum_na + sumRes.丙.sum_na;

    // 差值 = 总产量 - 计划量
    const diffLi = totalLi - planRes.碳酸锂;
    const diffNa = totalNa - planRes.硫酸钠;

    // 填充总产量
    $("#totalLi").text(totalLi.toFixed(1));
    $("#totalNa").text(totalNa.toFixed(1));

    // 判断超产欠产，拼接文字
    let liShow = "";
    if(diffLi >= 0){
        liShow = `<span style="color:#e53935;font-weight:bold;">超产 ${diffLi.toFixed(1)}</span>`;
    }else{
        liShow = `<span style="color:#1e88e5;font-weight:bold;">欠产 ${Math.abs(diffLi).toFixed(1)}</span>`;
    }
    $("#liDiffText").html(liShow);

    let naShow = "";
    if(diffNa >= 0){
        naShow = `<span style="color:#e53935;font-weight:bold;">超产 ${diffNa.toFixed(1)}</span>`;
    }else{
        naShow = `<span style="color:#1e88e5;font-weight:bold;">欠产 ${Math.abs(diffNa).toFixed(1)}</span>`;
    }
    $("#naDiffText").html(naShow);

    //渲染表格明细
    let html = "";
    listRes.forEach(row=>{
        html += `<tr>
            <td>${row.日期||""}</td>
            <td>${row.班组||""}</td>
            <td>${Number(row.碳酸锂车间产出||0).toFixed(2)}</td>
            <td>${Number(row.硫酸钠||0).toFixed(2)}</td>
            <td>${Number(row.去蒸发前液处理量||0).toFixed(2)}</td>
            <td>${Number(row.合成前液处理量||0).toFixed(2)}</td>
            <td>${Number(row.压滤机卸渣量||0).toFixed(2)}</td>
            <td>${Number(row.蒸发冷凝水||0).toFixed(2)}</td>
            <td>${Number(row.碳酸钠车间消耗||0).toFixed(2)}</td>
            <td>${Number(row["投活性炭、除氟剂量"]||0).toFixed(2)}</td>
            <td>${Number(row.产出锂渣||0).toFixed(2)}</td>
            <td>${Number(row.回投锂渣||0).toFixed(2)}</td>
            <td>${Number(row.镍渣||0).toFixed(2)}</td>
            <td>${Number(row["104返镁液"]||0).toFixed(2)}</td>
            <td>${Number(row["104废液"]||0).toFixed(2)}</td>
            <td>${Number(row.外排水量||0).toFixed(2)}</td>
            <td>${Number(row.钴渣量||0).toFixed(2)}</td>
            <td>${Number(row.清合成釜||0).toFixed(2)}</td>
            <td>${Number(row.更换滤布||0).toFixed(2)}</td> 
        </tr>`;
    })
    // 表格底部合计行：按当前筛选结果逐列累计
    const sumFieldList = [
        "碳酸锂车间产出","硫酸钠","去蒸发前液处理量","合成前液处理量",
        "压滤机卸渣量","蒸发冷凝水","碳酸钠车间消耗","投活性炭、除氟剂量",
        "产出锂渣","回投锂渣","镍渣","104返镁液","104废液",
        "外排水量","钴渣量","清合成釜","更换滤布"
    ];
    const sums = {};
    sumFieldList.forEach(f=> sums[f] = 0);
    listRes.forEach(row=>{
        sumFieldList.forEach(f=>{
            sums[f] += Number(row[f]||0);
        });
    });
    html += `<tr style="font-weight:bold;background:#f8f9fa;border-top:2px solid #dee2e6;">
        <td colspan="2">合计</td>`;
    sumFieldList.forEach(f=>{
        html += `<td>${sums[f].toFixed(2)}</td>`;
    });
    html += `</tr>`;

        $("#noticeTableBody").html(html);
}