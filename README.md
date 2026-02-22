# 基于物联网的蔬菜大棚土壤墒情监测平台

**毕业设计完整源码**  
作者：王健（大连东软信息学院 数据科学与大数据技术 20247140130）  
指导教师：肖凤纬  
完成时间：2026年3月

### 项目亮点
- 单节点硬件成本 **115-200元**（含太阳能供电）
- 30天真实大棚测试（瓦房店黄瓜大棚）：在线率97%、传输准确率98%、节水41.5%、增产16%
- **太阳能低功耗Deep Sleep**，超长续航，真正适合中小农户
- 即插即用，无需专业人员部署

**硬件**：ESP32 DevKitC + 电容式土壤湿度v1.2 + DS18B20 + 太阳能供电（低功耗Deep Sleep）  
**通信**：MQTT + 阿里云IoT平台  
**后端**：Flask + MySQL + Redis + pandas清洗  
**前端**：ECharts + 原生JavaScript（fetch）  
**部署**：Linux + Nginx
  
### 仓库结构
vegetable-greenhouse-soil-monitoring/
├── hardware/                  
│   └── greenhouse_soil_node.ino
├── static/
├── templates/
├── app.py
├── cleaning.py
├── mqtt_subscriber.py
├── requirements.txt
├── init_db.sql
├── README.md
└── LICENSE

### 快速启动（软件平台）

# 1. 克隆仓库
git clone https://github.com/20247140130/vegetable-greenhouse-soil-monitoring.git

# 2. 安装依赖
pip install -r requirements.txt

# 3. 创建数据库（执行init_db.sql）

# 4. 启动Redis + Flask
redis-server --daemonize yes
python app.py
访问地址：http://你的服务器IP:5000
硬件部署（超详细）

打开 hardware/greenhouse_soil_node.ino
修改 WiFi 和节点编号
Arduino IDE 上传到 ESP32
太阳能版：保持 USE_DEEP_SLEEP 1，传感器插入土壤10-15cm，太阳能板朝南
串口监视器（115200）可实时查看采集日志

低功耗模式说明

开启后平均功耗极低，适合太阳能+锂电池户外长期运行
关闭后方便调试（串口持续输出）

