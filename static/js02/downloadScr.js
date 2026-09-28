//downloadScr.js
$(function(){
    // ========= 数据源，4个分类 （增减new）=========
    const dataSource = {
        report: [
            {title:"2026年8月103车间生产日报表",file:"/static/file/report/2026年8月103车间生产日报表.xlsx",date:"2026-08-31",isNew:true},
            {title:"2026年7月103车间生产日报表",file:"/static/file/report/2026年7月103车间生产日报表.xlsx",date:"2026-07-31"},
            {title:"2026年6月103车间生产日报表",file:"/static/file/report/2026年6月103车间生产日报表.xlsx",date:"2026-06-30"},
            {title:"2026年5月103车间生产日报表",file:"/static/file/report/2026年5月103车间生产日报表.xlsx",date:"2026-05-30"},
            {title:"2026年4月103车间生产日报表",file:"/static/file/report/2026年4月103车间生产日报表.xlsx",date:"2026-04-30"},
            {title:"2026年3月103车间生产日报表",file:"/static/file/report/2026年3月103车间生产日报表.xlsx",date:"2026-03-30"},
            {title:"2026年2月103车间生产日报表",file:"/static/file/report/2026年2月103车间生产日报表.xlsx",date:"2026-02-30"},
            {title:"2026年1月103车间生产日报表",file:"/static/file/report/2026年1月103车间生产日报表.xlsx",date:"2026-01-30"},
        ],
        kpi: [
            {title:"2026年8月103车间绩效考核表",file:"/static/file/kpi/2026年8月103车间绩效考核表.xlsx",date:"2026-08-25",isNew:true},
            {title:"103车间岗位员工绩效汇总表",file:"/static/file/kpi/103车间岗位员工绩效汇总表.xlsx",date:"2026-07-20"},
            {title:"103车间岗位班长绩效汇总表",file:"/static/file/kpi/103车间岗位班长绩效汇总表.xlsx",date:"2026-07-19"},
        ],
        staff: [
            {title:"103车间人员信息表",file:"/static/file/staff/103车间人员信息表.xlsx",date:"2026-09-10"},
            {title:"103车间合成釜汇总表",file:"/static/file/staff/103车间合成釜汇总表.xlsx",date:"2026-09-05"},
            {title:"103车间档案文件收集清单",file:"/static/file/staff/103车间档案文件收集清单.xlsx",date:"2026-09-03"},
            {title:"交接班纪律安全责任书",file:"/static/file/staff/交接班纪律安全责任书.docx",date:"2026-09-01"},
            {title:"班组工具数量统计",file:"/static/file/staff/交班组工具数量统计.xlsx",date:"2026-06-01"},
            {title:"岗位培训签到表",file:"/static/file/staff/岗位培训签到表.xlsx",date:"2026-06-01"},
        ],
        safe: [
            {title:"103车间劳保信息表",file:"/static/file/safe/103车间劳保信息表.xlsx",date:"2026-08-20",isNew:true},
            {title:"103车间劳保配置表",file:"/static/file/safe/103车间劳保配置表.xlsx",date:"2026-08-20"},
            {title:"隐患报告审批表",file:"/static/file/safe/隐患报告审批表.xlsx",date:"2026-06-12"},
            {title:"车间环保设施检查记录表",file:"/static/file/safe/车间环保设施检查记录表.xlsx",date:"2026-04-11"},
            {title:"废水在线监测检查记录表",file:"/static/file/safe/废水在线监测检查记录表.xlsx",date:"2026-03-25"},
        ]
    };

    const pageConfig = {
        report: {current:1,pageSize:6},
        kpi: {current:1,pageSize:6},
        staff: {current:1,pageSize:6},
        safe: {current:1,pageSize:6}
    }

    function sortDesc(list){
        return list.sort((a,b)=>new Date(b.date) - new Date(a.date));
    }

    function renderBlock(type,listDomId,pageDomId){
        const rawList = dataSource[type];
        const sortedList = sortDesc(rawList);
        const cfg = pageConfig[type];
        const total = sortedList.length;
        const totalPage = Math.ceil(total / cfg.pageSize);
        if(cfg.current > totalPage && totalPage>0) cfg.current = totalPage;
        if(cfg.current <1) cfg.current =1;

        const start = (cfg.current -1)*cfg.pageSize;
        const pageData = sortedList.slice(start, start + cfg.pageSize);

        let listHtml = "";
        pageData.forEach(item=>{
            const newTag = item.isNew ? ' <span style="color:#e74c3c;">.New</span>' : '';  // 文字后面加new
            listHtml += '<div class="download-item">' +
                '<a href="' + item.file + '" download>' + item.title + newTag + '</a>' +
                '<span class="download-date">' + item.date + '</span>' +
            '</div>';
        })
        $("#" + listDomId).html(listHtml);

        let pageHtml = '每页 ' + cfg.pageSize + ' 条，共 ' + total + ' 条' +
        '<button class="page-prev" data-type="' + type + '" ' + (cfg.current<=1?"disabled":"") + '>上一页</button>' +
        '<button class="page-next" data-type="' + type + '" ' + (cfg.current>=totalPage?"disabled":"") + '>下一页</button>' +
        ' 页码：<input type="number" min="1" max="' + totalPage + '" value="' + cfg.current + '" class="page-jump" data-type="' + type + '">' +
        '<button class="page-jump-btn" data-type="' + type + '">跳转</button>';
        $("#" + pageDomId).html(pageHtml);
    }

    function renderAllDownload(){
        renderBlock("report","reportList","reportPage");
        renderBlock("kpi","kpiList","kpiPage");
        renderBlock("staff","staffList","staffPage");
        renderBlock("safe","safeList","safePage");
    }

    $(document).on("click",".page-prev",function(){
        const t = $(this).data("type");
        pageConfig[t].current -=1;
        renderAllDownload();
    })
    $(document).on("click",".page-next",function(){
        const t = $(this).data("type");
        pageConfig[t].current +=1;
        renderAllDownload();
    })
    $(document).on("click",".page-jump-btn",function(){
        const t = $(this).data("type");
        const val = $(".page-jump[data-type=" + t + "]").val();
        pageConfig[t].current = parseInt(val);
        renderAllDownload();
    })

    renderAllDownload();
})
