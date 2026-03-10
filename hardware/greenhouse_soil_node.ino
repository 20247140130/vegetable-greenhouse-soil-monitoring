// ==================== 蔬菜大棚土壤墒情监测节点（太阳能低功耗版） ================
// 作者：王健（2026优化版）
// 功能：土壤温湿度采集 + MQTT阿里云 + Deep Sleep低功耗（适合太阳能）
// 硬件：ESP32 + 电容土壤湿度v1.2 + DS18B20 + 太阳能供电

// ==================== 蔬菜大棚土壤墒情監測節點 (ESP32-S3 + LCD 1602 I2C + 可配置 Node ID) ====================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>
#include <WiFiManager.h>
#include <Preferences.h> // 用於保存數據到 Flash

// ====================== LCD 1602 I2C 顯示屏庫 ======================
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);  // 地址 0x27，16×2 螢幕

// ====================== 全局配置變量 ======================
const char* mqtt_server = "vf67a773.ala.cn-hangzhou.emqxsl.cn";
const int mqtt_port   = 8883;
const char* mqtt_user   = "greenhouse";
const char* mqtt_pass   = "ZPnzinSibMDx9XT";

// Node ID 默認值 (如果 Flash 中沒有數據則使用此值)
char node_id[20] = "Node1"; 
Preferences preferences; // Flash 存儲對象

#define USE_DEEP_SLEEP 1
const long interval = 30000;   // 30秒

// ====================== 引腳定義 ======================
#define ONE_WIRE_BUS 17
#define SOIL_MOISTURE_PIN 4

// LCD I2C 引腳
#define LCD_SDA 8
#define LCD_SCL 9

// 濕度校準值 (根據實際傳感器調整)
const int DRY_VALUE = 4095;
const int WET_VALUE = 900;

// ====================== 對象初始化 ======================
WiFiClientSecure espClient;
PubSubClient client(espClient);
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 28800, 3600000);
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
WiFiManager wifiManager;

unsigned long bootTime = 0;
float g_temp = 0;
float g_hum  = 0;

// ====================== MQTT 重連 ======================
void reconnect() {
  int retries = 0;
  while (!client.connected()) {
    if (retries >= 5) {
      Serial.println("MQTT connection failed multiple times, restarting...");
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("MQTT Fail");
      lcd.setCursor(0, 1);
      lcd.print("Rebooting...");
      delay(2000);
      ESP.restart();
    }
    Serial.print("Connecting to MQTT...");
    
    String clientId = String(node_id) + "-" + String(random(0xffff), HEX);
    if (client.connect(clientId.c_str(), mqtt_user, mqtt_pass)) {
      Serial.println("connected");
      lcd.setCursor(12, 1); // 在第二行末尾顯示連接狀態
      lcd.print("MQTT:OK");
    } else {
      Serial.printf("failed, rc=%d, retry in 5s\n", client.state());
      lcd.setCursor(12, 1);
      lcd.print("MQTT:Err");
      retries++;
      delay(5000);
    }
  }
}

// ====================== 獲取時間 ======================
String getFormattedTime() {
  if (timeClient.update()) {
    time_t rawtime = timeClient.getEpochTime();
    struct tm *ti = localtime(&rawtime);
    char buf[20];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", ti);
    return String(buf);
  }
  return "Time sync failed";
}

// ====================== 讀取土壤濕度 ======================
float readSoilMoisture() {
  const int samples = 10;
  long sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(SOIL_MOISTURE_PIN);
    delay(30);
  }
  int raw = sum / samples;

  // Serial.printf("Soil ADC raw: %d\n", raw); // 調試用，生產環境可註銷以減少日誌

  if (raw < 200 || raw > 4095) {
    // Serial.println("Warning: Soil value abnormal");
    return -1;
  }

  float hum = (DRY_VALUE - raw) * 100.0 / (DRY_VALUE - WET_VALUE);
  hum = constrain(hum, 0.0f, 100.0f);

  return hum;
}

// ====================== 更新 LCD 顯示 ======================
void updateLCD() {
  // 第一行：溫度 + 濕度
  lcd.setCursor(0, 0);
  lcd.print("T:");
  if (g_temp <= -100 || isnan(g_temp)) { // -127 或更極端視為錯誤
    lcd.print("Err ");
  } else {
    lcd.print(g_temp, 1);
    lcd.print("C  ");
  }

  lcd.print("H:");
  if (g_hum < 0 || g_hum > 100) {
    lcd.print("Err ");
  } else {
    lcd.print(g_hum, 1);
    lcd.print("%  ");
  }

  // 第二行：節點 ID + WiFi 狀態
  lcd.setCursor(0, 1);
  lcd.print(node_id);
  
  // 清空剩餘字符以防長短不一導致殘影
  int len = strlen(node_id);
  for(int i=0; i<(6-len); i++) lcd.print(" "); 
  
  lcd.setCursor(6, 1); 
  if (WiFi.status() == WL_CONNECTED) {
    lcd.print("WiFi:OK ");
  } else {
    lcd.print("NoWiFi  ");
  }
}

// ====================== 保存配置到 Flash ======================
void saveConfigToFlash() {
  preferences.begin("gh_config", false);
  preferences.putString("node_id", node_id);
  preferences.end();
  Serial.printf("✅ Config saved: NodeID=%s\n", node_id);
}

// ====================== 從 Flash 加載配置 ======================
void loadConfigFromFlash() {
  preferences.begin("gh_config", false);
  String savedId = preferences.getString("node_id", "Node1");
  strncpy(node_id, savedId.c_str(), sizeof(node_id) - 1);
  node_id[sizeof(node_id) - 1] = '\0'; // 確保字符串結束
  preferences.end();
  Serial.printf("✅ Loaded from Flash: NodeID=%s\n", node_id);
}

// ====================== setup ======================
void setup() {
  Serial.begin(115200);
  delay(500); // 等待串口穩定
  Serial.println("\n========== System Start ==========");

  // 1. LCD 初始化
  Wire.begin(LCD_SDA, LCD_SCL);
  lcd.init();
  lcd.backlight();
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("Booting...");
  lcd.setCursor(0, 1);
  lcd.print("Greenhouse Node");
  delay(1000);

  // 2. 加載保存的 Node ID
  loadConfigFromFlash();
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ID: ");
  lcd.print(node_id);
  lcd.setCursor(0, 1);
  lcd.print("Configuring WiFi");
  delay(1000);

  // 3. ADC 設定
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  // 4. DS18B20 初始化
  sensors.begin();
  if (sensors.getDeviceCount() == 0) {
    Serial.println("⚠️ No DS18B20 detected!");
    lcd.setCursor(0, 1);
    lcd.print("No Temp Sensor!");
  }

  // 5. WiFiManager 配置 (核心修改部分)
  Serial.println("Starting WiFi Manager...");
  
  // 創建自定義參數輸入框
  // 參數: id, placeholder(提示文字), defaultValue(默認值), length
  WiFiManagerParameter custom_node_id("node_id", "Device Node ID (e.g. Node1)", node_id, 20);
  
  wifiManager.addParameter(&custom_node_id);
  wifiManager.setConfigPortalTimeout(180); // 3分鐘無操作自動退出
  wifiManager.setBreakAfterConfig(true);   // 配置成功後斷開連接以便重啟或繼續
  
  // AP 名稱和密码
  const char* ap_ssid = "GreenHouse_Config";
  const char* ap_pass = "12345678";

  // 嘗試自動連接已保存的 WiFi
  // 如果失敗，將啟動配置門戶 (Captivate Portal)
  if (!wifiManager.autoConnect(ap_ssid, ap_pass)) {
    Serial.println("Failed to connect or Config Portal Timeout");
    // 如果超時仍未配置，重啟再試
    ESP.restart();
  }

  // --- 如果代碼運行到這裡，說明要么已經連上了，要么剛剛在網頁配置成功了 ---
  
  // 檢查是否是用戶剛剛在網頁提交了新配置
  if (custom_node_id.getValue() != NULL && strlen(custom_node_id.getValue()) > 0) {
    String newId = String(custom_node_id.getValue());
    // 只有當新輸入的 ID 與當前內存中的不同時才保存
    if (strcmp(node_id, newId.c_str()) != 0) {
      strncpy(node_id, newId.c_str(), sizeof(node_id) - 1);
      node_id[sizeof(node_id) - 1] = '\0';
      saveConfigToFlash();
      
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Saved New ID:");
      lcd.setCursor(0, 1);
      lcd.print(node_id);
      delay(2000);
    }
  }

  // 顯示連接成功
  Serial.print("✅ WiFi Connected! IP: ");
  Serial.println(WiFi.localIP());
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("IP: ");
  lcd.print(WiFi.localIP());
  lcd.setCursor(0, 1);
  lcd.print("Node: ");
  lcd.print(node_id);
  delay(2000);

  // 6. TLS 和 NTP 時間同步
  espClient.setInsecure(); // 跳過證書驗證 (適合測試)
  espClient.setTimeout(15);

  timeClient.begin();
  Serial.print("Syncing Time...");
  int retry = 0;
  while (!timeClient.update() && retry < 10) {
    timeClient.forceUpdate();
    delay(500);
    retry++;
  }
  if (retry < 10) Serial.println("Success");
  else Serial.println("Failed");

  // 7. MQTT 設置
  client.setServer(mqtt_server, mqtt_port);

  // 8. 第一次傳感器讀取
  sensors.requestTemperatures();
  g_temp = sensors.getTempCByIndex(0);
  if (g_temp == -127.0 || isnan(g_temp)) g_temp = 0;
  
  g_hum = readSoilMoisture();
  if (g_hum < 0) g_hum = 0;

  updateLCD();

  bootTime = millis();
  Serial.println("========== System Ready ==========");
}

// ====================== loop ======================
void loop() {

  // ================= 串口命令處理 =================
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    
    if (cmd == "r" || cmd == "R") {
      Serial.println("[CMD] Resetting WiFi Credentials only...");
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Reset WiFi...");
      lcd.setCursor(0, 1);
      lcd.print("Rebooting");
      
      wifiManager.resetSettings(); // 只清空 WiFi
      // 保留 Node ID
      
      delay(2000);
      ESP.restart();
    } 
    else if (cmd == "factory" || cmd == "FACTORY") {
      Serial.println("[CMD] Factory Reset (WiFi + Node ID)...");
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Factory Reset");
      lcd.setCursor(0, 1);
      lcd.print("Rebooting");
      
      wifiManager.resetSettings();
      preferences.begin("gh_config", false);
      preferences.clear(); // 清空所有保存的配置
      preferences.end();
      
      delay(2000);
      ESP.restart();
    }
    else if (cmd.startsWith("SETID:")) {
      String newId = cmd.substring(6);
      if (newId.length() > 0 && newId.length() < 20) {
        strncpy(node_id, newId.c_str(), sizeof(node_id) - 1);
        node_id[sizeof(node_id) - 1] = '\0';
        saveConfigToFlash();
        Serial.printf("✅ Node ID set to: %s\n", node_id);
        lcd.clear();
        lcd.print("ID Set: ");
        lcd.print(node_id);
        delay(2000);
        ESP.restart();
      } else {
        Serial.println("❌ Invalid ID length (1-19 chars)");
      }
    }
    else {
      Serial.println("Unknown command. Try: 'r' (reset wifi), 'factory' (full reset), 'SETID:Node2'");
    }
  }
  // ===========================================

  // MQTT 維護
  if (!client.connected()) reconnect();
  client.loop();

  // 采集數據
  g_hum = readSoilMoisture();

  sensors.requestTemperatures();
  g_temp = sensors.getTempCByIndex(0);
  if (g_temp == -127.0 || isnan(g_temp)) g_temp = 0;

  // 刷新 LCD
  updateLCD();

  // 上傳數據
  Serial.println("---------- Upload Data ----------");
  Serial.printf("Node: %s | Temp: %.2f C | Hum: %.2f %%\n", node_id, g_temp, g_hum);

  if (g_temp != 0 || g_hum > 0) {
    String currentTime = getFormattedTime();

    StaticJsonDocument<256> doc;
    doc["node_id"] = node_id;
    doc["temp"] = round(g_temp * 10) / 10.0;
    doc["hum"]  = round(g_hum  * 10) / 10.0;
    doc["time"] = currentTime;

    char jsonBuffer[256];
    serializeJson(doc, jsonBuffer);

    if (client.publish("greenhouse/soil/data", jsonBuffer)) {
      Serial.println("MQTT publish OK");
      // 短暫閃爍 LCD 表示發送成功 (可選)
    } else {
      Serial.println("MQTT publish failed");
    }
  }

  // 低功耗休眠
  if (USE_DEEP_SLEEP) {
    unsigned long workTime = millis() - bootTime;
    uint64_t sleepTime = (interval > workTime) ? (interval - workTime) * 1000ULL : 1000000ULL;
    
    Serial.printf("Deep sleep in %.1f sec\n\n", sleepTime / 1000000.0);
    Serial.flush();
    
    // 關閉 LCD 背光省電 (可選，需硬件支持或簡單延遲後休眠)
    lcd.noBacklight(); 
    delay(200);
    
    esp_sleep_enable_timer_wakeup(sleepTime);
    esp_deep_sleep_start();
  } else {
    delay(interval);
  }
}
