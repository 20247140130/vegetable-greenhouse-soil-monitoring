// ==================== 全局工具 ====================
function showAlert(node, msg) {
    const alertBox = document.createElement('div');
    alertBox.style.cssText = `
        position:fixed; bottom:20px; right:20px; background:#ff4444; color:white; 
        padding:20px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.3);
        z-index:9999; font-size:16px; max-width:300px;
    `;
    alertBox.innerHTML = `<strong>⚠️ ${node} 异常！</strong><br>${msg}`;
    document.body.appendChild(alertBox);
    
    setTimeout(() => alertBox.remove(), 30000);  // 30秒自动关闭
}

// ==================== 实时监控页面逻辑 ====================
function loadRealtime() {
    fetch('/api/realtime')
        .then(r => r.json())
        .then(res => {
            if (res.code !== 200) return;

            // 动态生成卡片
            let cardsHTML = '';
            Object.keys(res.data).forEach(node => {
                const d = res.data[node];
                const temp = parseFloat(d.temp);
                const hum = parseFloat(d.hum);
                const isAlert = (temp < 15 || temp > 30 || hum < 50 || hum > 80);
                
                cardsHTML += `
                    <div class="card ${isAlert ? 'alert' : ''}">
                        <h3>${node}</h3>
                        <p>🌡️ 温度: ${d.temp}℃</p>
                        <p>💧 湿度: ${d.hum}%RH</p>
                        <p>🕒 时间: ${d.collect_time}</p>
                    </div>
                `;

                // 预警弹窗
                if (isAlert) {
                    showAlert(node, `温度 ${d.temp}℃ / 湿度 ${d.hum}%RH 已超出阈值！`);
                }
            });
            document.getElementById('cards').innerHTML = cardsHTML;

            // 更新ECharts实时曲线（以Node1为例，支持多节点切换）
            const now = new Date().getTime();
            const chartOption = myChart.getOption();
            chartOption.series[0].data.push([now, parseFloat(res.data.Node1.temp)]);
            chartOption.series[1].data.push([now, parseFloat(res.data.Node1.hum)]);
            
            if (chartOption.series[0].data.length > 60) {
                chartOption.series[0].data.shift();
                chartOption.series[1].data.shift();
            }
            myChart.setOption(chartOption);
        })
        .catch(err => console.error('实时数据加载失败', err));
}

// 初始化ECharts
let myChart;
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('realtime-chart')) {
        myChart = echarts.init(document.getElementById('realtime-chart'));
        const option = {
            title: { text: '土壤墒情实时变化趋势', left: 'center' },
            tooltip: { trigger: 'axis' },
            legend: { data: ['温度(℃)', '湿度(%RH)'], top: 30 },
            xAxis: { type: 'time', boundaryGap: false },
            yAxis: [
                { name: '温度(℃)', type: 'value', min: 0, max: 50 },
                { name: '湿度(%RH)', type: 'value', min: 0, max: 100, offset: 60 }
            ],
            series: [
                { name: '温度(℃)', type: 'line', yAxisIndex: 0, data: [], smooth: true },
                { name: '湿度(%RH)', type: 'line', yAxisIndex: 1, data: [], smooth: true }
            ]
        };
        myChart.setOption(option);

        // 每3秒刷新（论文描述）
        setInterval(loadRealtime, 3000);
        loadRealtime();  // 首次加载
    }
});

// ==================== 历史数据页面逻辑 ====================
function queryHistory() {
    const node = document.getElementById('node').value || 'Node1';
    const start = document.getElementById('start').value;
    const end = document.getElementById('end').value;
    
    if (!start || !end) {
        alert('请选择时间范围');
        return;
    }

    fetch(`/api/history?node_id=${node}&start_time=${start}&end_time=${end}`)
        .then(r => r.json())
        .then(res => {
            if (res.code === 200) {
                const tempData = res.data.map(d => [d.collect_time, d.temp]);
                const humData = res.data.map(d => [d.collect_time, d.hum]);
                
                const historyChart = echarts.init(document.getElementById('history-chart'));
                historyChart.setOption({
                    title: { text: `${node} 历史墒情曲线` },
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'time' },
                    yAxis: [
                        { name: '温度(℃)', type: 'value', min: 0, max: 50 },
                        { name: '湿度(%RH)', type: 'value', min: 0, max: 100, offset: 60 }
                    ],
                    series: [
                        { name: '温度(℃)', type: 'line', data: tempData, smooth: true },
                        { name: '湿度(%RH)', type: 'line', data: humData, smooth: true }
                    ]
                });
            }
        });
}

// ==================== 阈值设置页面逻辑 ====================
function saveThreshold() {
    const node = document.getElementById('node').value;
    const data = {
        node_id: node,
        temp_min: document.getElementById('tmin').value,
        temp_max: document.getElementById('tmax').value,
        hum_min: document.getElementById('hmin').value,
        hum_max: document.getElementById('hmax').value
    };

    fetch('/api/set_threshold', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(res => {
        alert(res.msg || '阈值保存成功！');
    });
}