/* ============================================================
   echarts-theme.js — 全局统一 ECharts 图表主题
   用法：
     1) 确保本文件在 echarts.min.js 之后加载
     2) 页面初始化图表时把 echarts.init(el) 换成 initChart(el)
        （已注册主题 'workweb'，业务 option 完全不用改）
   统一风格：红主色 / 深蓝辅色、深蓝 tooltip、浅灰坐标轴分割线
   ============================================================ */
(function (window) {
  'use strict';

  if (typeof echarts === 'undefined') {
    // echarts 未加载时不注册，避免报错
    return;
  }

  var theme = {
    // 系列主色（红主色 + 深蓝辅色 + 辅助色板）
    color: ['#e74c3c', '#205493', '#f4a259', '#4a9e8f', '#9bbbf4', '#a2ddaa', '#c9a7e8', '#e4d48f'],

    backgroundColor: 'transparent',

    textStyle: {
      color: '#333333',
      fontFamily: 'Microsoft YaHei, "PingFang SC", sans-serif'
    },

    title: {
      textStyle: { color: '#1a1b1c', fontSize: 15, fontWeight: 600 },
      subtextStyle: { color: '#6b7280', fontSize: 12 }
    },

    legend: {
      textStyle: { color: '#555555', fontSize: 12 },
      itemWidth: 14,
      itemHeight: 10,
      icon: 'roundRect',
      top: 8
    },

    tooltip: {
      backgroundColor: 'rgba(32, 84, 147, 0.92)',   // 深蓝底
      borderColor: '#205493',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: '#ffffff', fontSize: 12 },
      axisPointer: {
        lineStyle: { color: '#205493' },
        crossStyle: { color: '#205493' }
      }
    },

    categoryAxis: {
      axisLine: { lineStyle: { color: '#999999' } },
      axisTick: { lineStyle: { color: '#999999' } },
      axisLabel: { color: '#555555', fontSize: 12 },
      splitLine: { show: false }
    },

    valueAxis: {
      axisLine: { show: true, lineStyle: { color: '#999999' } },
      axisLabel: { color: '#555555', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e9edf3', type: 'dashed' } }
    },

    grid: {
      borderColor: '#e4e3dd'
    },

    series: {
      line: {
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 }
      },
      bar: {
        barMaxWidth: 40,
        itemStyle: { borderRadius: [4, 4, 0, 0] }
      },
      pie: {
        itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
        label: { fontSize: 12, color: '#555555' }
      }
    }
  };

  echarts.registerTheme('workweb', theme);

  // 统一初始化帮助函数：init(el) 或 init(el, option)
  window.initChart = function (el, option) {
    var chart = echarts.init(el, 'workweb');
    if (option) chart.setOption(option);
    return chart;
  };
})(window);
