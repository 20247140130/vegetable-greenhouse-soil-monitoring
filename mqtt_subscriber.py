import paho.mqtt.client as mqtt
import mysql.connector
import json
from datetime import datetime

# 配置
mqtt_server = "iot-06z00e09s0b5m8t.mqtt.iothub.aliyuncs.com"
mqtt_port = 1883
mqtt_topic = "greenhouse/soil/data"

db = mysql.connector.connect(
    host="localhost", user="root", password="123456", 
    database="greenhouse_soil", charset='utf8mb4'
)
cursor = db.cursor()

def on_connect(client, userdata, flags, rc):
    print(f"[{datetime.now()}] MQTT 已连接，代码: {rc}")
    client.subscribe(mqtt_topic)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        sql = """INSERT INTO soil_data_raw 
                 (node_id, temp, hum, collect_time) 
                 VALUES (%s, %s, %s, %s)"""
        val = (data["node_id"], data["temp"], data["hum"], data["time"])
        cursor.execute(sql, val)
        db.commit()
        print(f"[{datetime.now()}] 收到数据并入库: {data['node_id']} {data['temp']}°C {data['hum']}%")
    except Exception as e:
        print(f"[{datetime.now()}] 入库失败: {e}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(mqtt_server, mqtt_port, 60)
client.loop_forever()
