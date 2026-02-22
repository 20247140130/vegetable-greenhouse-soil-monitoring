// ================================================
// greenhouse_soil_node.ino  【最终优化稳定版】
// 作者：王健  优化日期：2026.2.22
// ================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>        // Deep Sleep 必须

// ====================== 用户配置区 ======================
const char* ssid = "Greenhouse_WiFi";           // ← 改成你的大棚WiFi
const char* password = "12345678";

const char* mqtt_server = "iot-06z00e09s0b5m8t.mqtt.iothub.aliyuncs.com";
const int mqtt_port = 1883;
const char* node_id = "Node1";                  // Node1/Node2/Node3

// 阿里云一机一密认证（必须填写！在阿里云控制台复制）
const char* mqtt_username = "你的DeviceName";   // ← 改成阿里云生成的 DeviceName
const char* mqtt_password = "你的DeviceSecret"; // ← 改成阿里云生成的 DeviceSecret（完整字符串）

#define USE_DEEP_SLEEP 1        // 1=开启低功耗（推荐太阳能） 0=关闭（调试用）
const unsigned long interval = 30000;  // 30秒采集一次

// ====================== 引脚 & 对象 ======================
#define ONE_WIRE_BUS 4
#define SOIL_MOISTURE_PIN 34

WiFiClient espClient;
PubSubClient client(espClient);
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 28800); // 东八区
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// ====================== 全局变量 ======================
unsigned long previousMillis = 0;

// ====================== MQTT重连（带认证） ======================
void reconnect() {
  while (!client.connected()) {
    Serial.print("尝试连接MQTT...");
    if (client.connect(node_id, mqtt_username, mqtt_password)) {
      Serial.println("MQTT连接成功！");
    } else {
      Serial.print("失败 rc=");
      Serial.println(client.state());
      delay(5000);
    }
  }
}

// ====================== 获取标准时间 ======================
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
  Serial.println("系统启动完成！低功耗模式：" + String(USE_DEEP_SLEEP ? "已开启" : "已关闭"));
}

// ====================== loop ======================
void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // 采集数据
    sensors.requestTemperatures();
    float temp = sensors.getTempCByIndex(0);
    int rawHum = analogRead(SOIL_MOISTURE_PIN);
    float hum = map(rawHum, 4095, 0, 0, 100);   // 两点标定（论文已说明）

    if (isnan(temp) || hum < 0 || hum > 100) {
      Serial.println("传感器读取失败，跳过本次");
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
        Serial.println("数据已成功上传阿里云");
      } else {
        Serial.println("上传失败，将在下次重试");
      }
    }
  }

  // ====================== 低功耗休眠 ======================
  if (USE_DEEP_SLEEP) {
    uint64_t sleepTime = interval * 1000ULL;   // 转换为微秒
    Serial.printf("即将进入深度睡眠 %.1f 秒（节能模式）\n", sleepTime / 1000000.0);
    delay(100);  // 给串口输出时间

    esp_sleep_enable_timer_wakeup(sleepTime);
    esp_deep_sleep_start();   // 进入深度睡眠，唤醒后从setup重新开始
  } else {
    delay(1000);   // 调试模式每秒检查一次
  }
}

