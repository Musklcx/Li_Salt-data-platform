const menuItems = document.querySelectorAll('.sidebar-menu-item');
const allPages = document.querySelectorAll('.content-page');
const leftSidebar = document.getElementById('leftSidebar');
const toggleBtn = document.getElementById('sidebarToggleBtn');

// 标记：portfolio只初始化1次
let portfolioInstance = null;
window._portfolioInited = false;

// 侧边栏折叠
let isCollapsed = false;
toggleBtn.addEventListener('click', () => {
    isCollapsed = !isCollapsed;
    if (isCollapsed) {
        leftSidebar.classList.add('collapsed');
        toggleBtn.innerText = " >> ";
    } else {
        leftSidebar.classList.remove('collapsed');
        toggleBtn.innerText = " << ";
    }
});

menuItems.forEach(menu => {
    menu.addEventListener('click', function () {
        menuItems.forEach(m => m.classList.remove('active'));
        this.classList.add('active');
        const targetPageId = this.getAttribute('data-page');

        allPages.forEach(p => p.classList.remove('active'));
        document.getElementById(targetPageId).classList.add('active');

        // =========切换到人员概况tab，初始化isotope=========
        if (targetPageId === "page_staff") {
            setTimeout(() => {
                const $ = jQuery;
                if (!window._portfolioInited) {
                    // 第一次初始化
                    portfolioInstance = $('.portfolio-container').isotope({
                        itemSelector: '.portfolio-item',
                        layoutMode: 'fitRows'
                    });

                    // 筛选按钮点击事件
                    $('#portfolio-flters li').on('click', function () {
                        $('#portfolio-flters li').removeClass('filter-active');
                        $(this).addClass('filter-active');
                        portfolioInstance.isotope({ filter: $(this).data('filter') });
                    });

                    // venobox图片弹窗
                    $('.venobox').venobox();
                    window._portfolioInited = true;
                } else {
                    // 再次切回这个tab，强制重新计算布局！关键！
                    portfolioInstance.isotope('layout');
                }
            }, 200);
        }

        // =========切换到【信息公示】页面，自动加载当月数据=========
        if (targetPageId === "page_notice") {
            setTimeout(() => {
                const $ = jQuery;
                const now = new Date();
                const defaultMonth = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
                $("#monthSelect").val(defaultMonth);
                // 调用noticeScr里面的全局变量与加载函数
                currentMonth = defaultMonth;
                const defaultBanzu = $("#banzuSelect").val();
                loadNoticeData(currentMonth, defaultBanzu);
            }, 100);
        }

        // =========切换到【隐患记录】页面，强制VXE表格重算尺寸，消除双滚动条和右侧空白列=========
        if (targetPageId === "page_hazard") {
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 200);
        }

        // =========切换到【生产数据】页面，直接调用ECharts实例resize，多次切换也不会压缩=========
        if (targetPageId === "page_data") {
            setTimeout(() => {
                if(window.myChart){
                    window.myChart.resize();
                }
                // 多次延迟重算，覆盖快速切换时序问题
                setTimeout(()=>{
                    if(window.myChart) window.myChart.resize();
                }, 300);
                setTimeout(()=>{
                    if(window.myChart) window.myChart.resize();
                }, 500);
            }, 100);
        }

        // ===== 下载专区 page_download 不需要额外逻辑，只靠上面的active切换，不用加代码
    });
});
