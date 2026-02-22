// ==================== 蔬菜大棚土壤墒情监测节点（太阳能低功耗版） ====================
// 作者：王健（2026优化版）
// 功能：土壤温湿度采集 + MQTT阿里云 + Deep Sleep低功耗（适合太阳能）
// 硬件：ESP32 + 电容土壤湿度v1.2 + DS18B20 + 太阳能供电

#include <WiFi.h>
#include <PubSubClient.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>          // ← 新增：Deep Sleep 支持

// ====================== 用户配置区（必须修改） ======================
const char* ssid = "Greenhouse_WiFi";           // ← 改成你的大棚WiFi
const char* password = "12345678";              // ← WiFi密码

const char* mqtt_server = "iot-06z00e09s0b5m8t.mqtt.iothub.aliyuncs.com";
const int mqtt_port = 1883;
const char* node_id = "Node1";                  // Node1 / Node2 / Node3

#define USE_DEEP_SLEEP 1        // ← 1=开启太阳能低功耗模式（推荐）  0=关闭（调试用）
const long interval = 30000;    // 采集间隔 30秒

// ====================== 引脚定义 ======================
#define ONE_WIRE_BUS 4
#define SOIL_MOISTURE_PIN 34

// ====================== 对象初始化 ======================
WiFiClient espClient;
PubSubClient client(espClient);
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 28800); // UTC+8
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// ====================== 全局变量 ======================
unsigned long bootTime = 0;

// ====================== MQTT重连 ======================
void reconnect() {
  while (!client.connected()) {
    if (client.connect(node_id)) {
      Serial.println("MQTT连接成功");
    } else {
      delay(5000);
    }
  }
}

// ====================== 获取时间 ======================
String getFormattedTime() {
  timeClient.update();
  time_t rawtime = timeClient.getEpochTime();
  struct tm *ti = localtime(&rawtime);
  char buf[20];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", ti);
  return String(buf);
}

// ====================== setup ======================
void setup() {
  Serial.begin(115200);
  sensors.begin();
  timeClient.begin();

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi已连接 IP: " + WiFi.localIP().toString());

  client.setServer(mqtt_server, mqtt_port);
  bootTime = millis();
  Serial.println("系统启动完成！低功耗模式：" + String(USE_DEEP_SLEEP ? "已开启" : "已关闭"));
}

// ====================== loop ======================
void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  // 采集数据
  sensors.requestTemperatures();
  float temp = sensors.getTempCByIndex(0);
  int rawHum = analogRead(SOIL_MOISTURE_PIN);
  float hum = map(rawHum, 4095, 0, 0, 100);

  if (isnan(temp) || hum < 0 || hum > 100) {
    Serial.println("传感器读取失败");
  } else {
    String currentTime = getFormattedTime();
    Serial.printf("采集成功 → %.1f°C  %.1f%%  %s\n", temp, hum, currentTime.c_str());

    StaticJsonDocument<200> doc;
    doc["node_id"] = node_id;
    doc["temp"] = round(temp * 10) / 10.0;
    doc["hum"] = round(hum * 10) / 10.0;
    doc["time"] = currentTime;

    char jsonBuffer[256];
    serializeJson(doc, jsonBuffer);

    if (client.publish("greenhouse/soil/data", jsonBuffer)) {
      Serial.println("✅ 已成功上传阿里云");
    }
  }

  // ====================== 太阳能低功耗休眠 ======================
  if (USE_DEEP_SLEEP) {
    unsigned long workTime = millis() - bootTime;
    uint64_t sleepTime = (interval > workTime) ? (interval - workTime) * 1000 : 1000000; // 至少睡1秒

    Serial.printf("即将休眠 %.1f 秒（节能模式）\n", sleepTime / 1000000.0);
    delay(100); // 给串口输出时间

    esp_sleep_enable_timer_wakeup(sleepTime);
    esp_deep_sleep_start();   // ← 进入深度睡眠
  } else {
    delay(interval);   // 调试模式正常延时
  }
}