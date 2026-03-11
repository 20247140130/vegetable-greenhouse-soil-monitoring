# ==================== 蔬菜大棚土壤墒情监测节点（太阳能低功耗版） ================
# 作者：王健
# 功能：蔬菜大棚土壤墒情監測系統的后端核心,基於 Flask 框架構建，充當了物聯網網關（Gateway）和Web 服務器的雙重角色。
# 硬件：ESP32 + 电容土壤湿度v1.2 + DS18B20 + 太阳能供电

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
import mysql.connector
from mysql.connector import pooling, Error as MySQLError
import redis
from paho.mqtt import client as mqtt
import logging
import traceback
import time
import threading
import sys

app = Flask(__name__)
app.secret_key = 'your_secret_key_here_change_this_in_production'  # 生產環境請改為安全的隨機字符串

# ====================== 日誌設置（詳細級別） ======================
logging.basicConfig(
    level=logging.DEBUG,  # 開發時用 DEBUG，上線可改 INFO
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        # logging.FileHandler('app.log', encoding='utf-8')  # 如需記錄到文件可取消註解
    ]
)
logger = logging.getLogger(__name__)

logger.info("========== 應用程式啟動 ==========")
logger.info(f"Python 版本: {sys.version}")
logger.info(f"當前工作目錄: {os.getcwd()}")

# ====================== MySQL 連接池配置 ======================
MYSQL_CONFIG = {
    "host": "47.112.123.236",
    "port": 3306,
    "user": "flask_user",
    "password": "X7p#kL9mR2vN$qT8",
    "database": "greenhouse_soil",
    "charset": 'utf8mb4',
    "connection_timeout": 10,
    "use_pure": True,
    "autocommit": False,
    "raise_on_warnings": False,
    "get_warnings": False
}

mysql_pool = None
try:
    mysql_pool = pooling.MySQLConnectionPool(
        pool_name='greenhouse_pool',
        pool_size=10,           # 可根據實際並發調整
        pool_reset_session=True,
        **MYSQL_CONFIG
    )
    actual_size = mysql_pool.pool_size
    logger.info(f"✅ MySQL 連接池初始化成功 (Size={actual_size})")
except MySQLError as e:
    logger.error(f"❌ MySQL 連接池初始化失敗: {e}")
    mysql_pool = None

def get_mysql_connection(max_retries=3, retry_delay=1):
    """
    從連接池獲取連接，並自動 ping 檢查有效性
    """
    if not mysql_pool:
        logger.error("❌ MySQL 連接池未初始化")
        return None

    last_error = None
    for attempt in range(max_retries):
        conn = None
        try:
            conn = mysql_pool.get_connection()
            # 關鍵：使用 ping 檢查連接是否有效（自動重連）
            if not conn.is_connected():
                logger.warning(f"⚠️ 從連接池取得的連接已斷開，嘗試重連 (嘗試 {attempt + 1})")
                conn.reconnect(attempts=1, delay=0)

            if conn.is_connected():
                if attempt > 0:
                    logger.info(f"✅ 重試後連接成功 (嘗試 {attempt + 1}/{max_retries})")
                return conn
            else:
                raise MySQLError("連接狀態異常，ping 失敗")
        except Exception as e:
            last_error = e
            if conn:
                try:
                    conn.close()
                except:
                    pass

            logger.warning(f"連接獲取失敗 (嘗試 {attempt + 1}/{max_retries}): {type(e).__name__} - {e}")

            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logger.info(f"等待 {wait_time} 秒後重試...")
                time.sleep(wait_time)

    logger.error(f"❌ 無法獲取數據庫連接 (已重試 {max_retries} 次): {last_error}")
    return None

# ====================== Redis 連接 ======================
redis_db = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
logger.info("✅ Redis 連接初始化完成")

# ====================== MQTT 配置 ======================
MQTT_BROKER = "vf67a773.ala.cn-hangzhou.emqxsl.cn"
MQTT_PORT = 8883
MQTT_USERNAME = "greenhouse"
MQTT_PASSWORD = "ZPnzinSibMDx9XT"
MQTT_TOPIC_DATA = "greenhouse/soil/data"
MQTT_TOPIC_CONFIG = "config/update/"

mqtt_client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="flask-backend-" + str(os.getpid()),
    clean_session=True
)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("✅ MQTT 連接成功")
        client.subscribe(MQTT_TOPIC_DATA)
        logger.info(f"已訂閱 topic: {MQTT_TOPIC_DATA}")
    else:
        logger.error(f"❌ MQTT 連接失敗，rc = {rc}")

def on_message(client, userdata, msg):
    mysql_conn = None
    cursor = None
    try:
        payload_str = msg.payload.decode('utf-8')
        payload = json.loads(payload_str)
        logger.info(f"收到消息: {msg.topic} → {payload}")

        node_id = payload.get('node_id')
        if not node_id:
            logger.warning("缺少 node_id，忽略此消息")
            return

        temp = 0.0
        try:
            temp = float(payload.get('temp', 0.0))
        except (ValueError, TypeError) as e:
            logger.warning(f"temp 轉換失敗，使用 0.0: {payload.get('temp')} → {e}")

        hum = 0.0
        try:
            hum = float(payload.get('hum', 0.0))
        except (ValueError, TypeError) as e:
            logger.warning(f"hum 轉換失敗，使用 0.0: {payload.get('hum')} → {e}")

        collect_time = payload.get('time')
        use_server_time = False
        if not collect_time or collect_time.strip() == '' or collect_time == 'Time sync failed':
            collect_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            use_server_time = True
            logger.info(f"【時間同步失敗，使用伺服器時間】: {collect_time}")

        # 存 Redis（兼容 Redis 3.0，逐個 hset）
        redis_key = f"soil_data:{node_id}"
        try:
            redis_db.hset(redis_key, "temp", str(temp))
            redis_db.hset(redis_key, "hum", str(hum))
            redis_db.hset(redis_key, "collect_time", collect_time)
            redis_db.hset(redis_key, "status", "online")
            redis_db.hset(redis_key, "time_source", "server" if use_server_time else "device")
            redis_db.expire(redis_key, 86400 * 7)
            logger.info(f"✅ Redis 更新成功: {redis_key}")
        except redis.RedisError as re:
            logger.error(f"❌ Redis 寫入失敗: {re}")

        # 存 MySQL（關鍵修復：先判斷 mysql_conn 是否為 None）
        mysql_conn = get_mysql_connection(max_retries=2)
        if mysql_conn is not None and mysql_conn.is_connected():
            try:
                cursor = mysql_conn.cursor()
                sql = """
                    INSERT INTO soil_data (node_id, temp, hum, collect_time)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(sql, (node_id, temp, hum, collect_time))
                mysql_conn.commit()
                logger.info(f"✅ 【MySQL 寫入成功】 Node {node_id} | temp={temp} | hum={hum} | time={collect_time}")
            except MySQLError as db_err:
                logger.error(f"❌ MySQL 寫入失敗: {db_err}", exc_info=True)
                try:
                    mysql_conn.rollback()
                except Exception as rollback_err:
                    logger.warning(f"Rollback 失敗: {rollback_err}")
            finally:
                if cursor:
                    try:
                        cursor.close()
                    except Exception as e:
                        logger.warning(f"關閉 cursor 失敗: {e}")
        else:
            logger.warning("⚠️ MySQL 未連接或連接無效，跳過寫入（Redis 已保存）")

    except json.JSONDecodeError as je:
        logger.error(f"❌ JSON 解析失敗: {msg.payload} | 錯誤: {je}")
    except Exception as e:
        logger.error(f"❌ 處理 MQTT 消息異常: {type(e).__name__} - {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        if mysql_conn is not None and mysql_conn.is_connected():
            try:
                mysql_conn.close()
            except Exception as e:
                logger.warning(f"關閉連接失敗: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def init_mqtt():
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.tls_set()
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        logger.info("✅ MQTT 已初始化並啟動")
    except Exception as e:
        logger.error(f"❌ MQTT 連接初始化失敗: {e}")

# ====================== 健康檢查線程 ======================
def health_check_thread():
    while True:
        try:
            time.sleep(60)
            conn = get_mysql_connection(max_retries=1, retry_delay=0.5)
            if conn:
                cursor = None
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    if result and result[0] == 1:
                        logger.debug(f"✅ 數據庫健康檢查通過 ({datetime.now().strftime('%H:%M:%S')})")
                    else:
                        logger.warning("⚠️ 數據庫健康檢查返回異常")
                except Exception as e:
                    logger.warning(f"⚠️ 數據庫健康檢查執行失敗: {e}")
                finally:
                    if cursor:
                        try:
                            cursor.close()
                        except:
                            pass
                    if conn.is_connected():
                        try:
                            conn.close()
                        except:
                            pass
            else:
                logger.warning(f"⚠️ 數據庫健康檢查失敗：無法獲取連接")
        except Exception as e:
            logger.warning(f"⚠️ 健康檢查線程異常: {e}")
            time.sleep(5)

# ====================== 前端路由與 API ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/threshold')
def threshold():
    return render_template('threshold.html')

@app.route('/diagnostic')
def diagnostic():
    return render_template('time_diagnostic.html')

@app.route('/api-test')
def api_test():
    return render_template('api_diagnostic.html')

@app.route('/time-verify')
def time_verify():
    return render_template('time_verification.html')

@app.route('/api-raw-check')
def api_raw_check():
    return render_template('api_raw_check.html')

@app.route('/api/realtime', methods=['GET'])
def get_realtime_data():
    try:
        realtime_data = {}
        node_keys = redis_db.keys("soil_data:*")
        for key in node_keys:
            node_id = key.split(":", 1)[1]
            data = redis_db.hgetall(key)
            realtime_data[node_id] = data
        logger.debug(f"realtime API 返回 {len(realtime_data)} 個節點")
        return jsonify({"code": 200, "msg": "success", "data": realtime_data})
    except Exception as e:
        logger.error(f"❌ realtime API 錯誤: {e}")
        return jsonify({"code": 500, "msg": str(e), "data": None}), 500

@app.route('/api/history', methods=['GET'])
def get_history_data():
    mysql_conn = None
    cursor = None
    try:
        node_id = request.args.get("node_id")
        start_time = request.args.get("start_time")
        end_time = request.args.get("end_time")

        logger.debug(f"收到 /api/history 請求: node_id={node_id}, start={start_time}, end={end_time}")

        if not all([node_id, start_time, end_time]):
            logger.warning("缺少必要參數")
            return jsonify({"code": 400, "msg": "缺少參數: node_id, start_time, end_time", "data": None}), 400

        mysql_conn = get_mysql_connection(max_retries=3)
        if mysql_conn is None:
            logger.error("無法獲取 MySQL 連接")
            return jsonify({"code": 503, "msg": "資料庫連接失敗，請稍後重試", "data": None}), 503

        cursor = mysql_conn.cursor(dictionary=True)
        sql = """
            SELECT temp, hum, collect_time
            FROM soil_data
            WHERE node_id = %s
            AND collect_time BETWEEN %s AND %s
            ORDER BY collect_time
        """
        logger.debug(f"執行 SQL: {sql} with params {node_id, start_time, end_time}")
        cursor.execute(sql, (node_id, start_time, end_time))
        data = cursor.fetchall()
        logger.info(f"查詢成功: {len(data)} 筆記錄")

        return jsonify({"code": 200, "msg": "success", "data": data}), 200

    except MySQLError as e:
        logger.error(f"❌ 數據庫查詢失敗: {e}", exc_info=True)
        return jsonify({"code": 500, "msg": f"數據庫查詢失敗: {str(e)}", "data": None}), 500
    except Exception as e:
        logger.error(f"❌ history API 異常: {e}", exc_info=True)
        return jsonify({"code": 500, "msg": str(e), "data": None}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception as e:
                logger.warning(f"關閉 cursor 失敗: {e}")
        if mysql_conn is not None and mysql_conn.is_connected():
            try:
                mysql_conn.close()
            except Exception as e:
                logger.warning(f"歸還連接失敗: {e}")

@app.route('/api/set_threshold', methods=['POST'])
def set_threshold():
    try:
        data = request.get_json()
        node_id = data.get("node_id")
        temp_min = data.get("temp_min")
        temp_max = data.get("temp_max")
        hum_min = data.get("hum_min")
        hum_max = data.get("hum_max")
        if not all([node_id, temp_min, temp_max, hum_min, hum_max]):
            return jsonify({"code": 400, "msg": "缺少參數", "data": None})
        threshold_key = f"threshold:{node_id}"

        redis_db.hset(threshold_key, "temp_min", str(temp_min))
        redis_db.hset(threshold_key, "temp_max", str(temp_max))
        redis_db.hset(threshold_key, "hum_min", str(hum_min))
        redis_db.hset(threshold_key, "hum_max", str(hum_max))
        redis_db.expire(threshold_key, 86400 * 365)

        logger.info(f"✅ 閾值設定成功: {node_id}")
        return jsonify({"code": 200, "msg": f"{node_id} 閾值設定成功"})
    except Exception as e:
        logger.error(f"❌ set_threshold 錯誤: {e}")
        return jsonify({"code": 500, "msg": str(e)})

@app.route('/api/alert', methods=['GET'])
def get_alert_status():
    try:
        alert_status = {}
        node_keys = redis_db.keys("soil_data:*")
        logger.debug(f"發現 {len(node_keys)} 個節點")
        for key in node_keys:
            node_id = key.split(":", 1)[1]
            current = redis_db.hgetall(key)
            thresh_key = f"threshold:{node_id}"
            threshold = redis_db.hgetall(thresh_key)
            if not threshold:
                alert_status[node_id] = {"status": "normal", "msg": "未設定閾值"}
                continue
            try:
                temp = float(current.get("temp", 0))
                hum = float(current.get("hum", 0))
                t_min = float(threshold.get("temp_min", -999))
                t_max = float(threshold.get("temp_max", 999))
                h_min = float(threshold.get("hum_min", -999))
                h_max = float(threshold.get("hum_max", 999))
                if temp < t_min or temp > t_max or hum < h_min or hum > h_max:
                    alert_status[node_id] = {"status": "alert", "msg": "墒情異常，請檢查"}
                else:
                    alert_status[node_id] = {"status": "normal", "msg": "正常"}
            except ValueError:
                alert_status[node_id] = {"status": "error", "msg": "資料格式錯誤"}
        return jsonify({"code": 200, "msg": "success", "data": alert_status})
    except Exception as e:
        logger.error(f"❌ alert API 錯誤: {e}")
        return jsonify({"code": 500, "msg": str(e)})

# ====================== 配置頁面 ======================
@app.route('/config', methods=['GET', 'POST'])
def config():
    node_keys = redis_db.keys("soil_data:*")
    nodes = sorted(set(key.split(":", 1)[1] for key in node_keys))
    suggested_new = "Node1"
    if nodes:
        nums = [int(n.replace('Node', '')) for n in nodes if n.startswith('Node') and n[4:].isdigit()]
        if nums:
            suggested_new = f"Node{max(nums) + 1}"

    if request.method == 'POST':
        try:
            node_id = request.form.get('node_id')
            ssid = request.form.get('ssid')
            password = request.form.get('password')
            mqtt_server = request.form.get('mqtt_server')
            mqtt_port = request.form.get('mqtt_port')
            mqtt_user = request.form.get('mqtt_user')
            mqtt_pass = request.form.get('mqtt_pass')
            mqtt_topic = request.form.get('mqtt_topic')

            if not node_id:
                flash("請選擇或輸入節點 ID", "danger")
                return redirect(url_for('config'))
            if not node_id.startswith('Node') or not node_id[4:].isdigit():
                flash("節點 ID 格式錯誤，應為 Node1、Node2 等", "danger")
                return redirect(url_for('config'))

            node_key = f"soil_data:{node_id}"
            if not redis_db.exists(node_key):
                flash(f"節點 {node_id} 不存在，正在自動初始化...", "info")
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                redis_db.hset(node_key, "temp", "0.0")
                redis_db.hset(node_key, "hum", "0.0")
                redis_db.hset(node_key, "collect_time", current_time)
                redis_db.hset(node_key, "status", "online")
                redis_db.expire(node_key, 86400 * 7)

                mysql_conn = get_mysql_connection(max_retries=2)
                if mysql_conn:
                    cursor = None
                    try:
                        cursor = mysql_conn.cursor()
                        sql = "INSERT INTO soil_data (node_id, temp, hum, collect_time) VALUES (%s, %s, %s, %s)"
                        cursor.execute(sql, (node_id, 0.0, 0.0, current_time))
                        mysql_conn.commit()
                        logger.info(f"✅ MySQL 節點初始化: {node_id}")
                    except MySQLError as e:
                        logger.warning(f"⚠️ MySQL 初始化失敗: {e}")
                        mysql_conn.rollback()
                    finally:
                        if cursor:
                            try:
                                cursor.close()
                            except:
                                pass
                        if mysql_conn.is_connected():
                            try:
                                mysql_conn.close()
                            except:
                                pass
                else:
                    flash("MySQL 未連接，跳過資料庫初始化", "warning")
                flash(f"節點 {node_id} 初始化完成", "success")
            else:
                flash(f"更新節點 {node_id} 配置", "info")

            config_data = {
                "ssid": ssid,
                "password": password,
                "mqtt_server": mqtt_server,
                "mqtt_port": int(mqtt_port) if mqtt_port else 8883,
                "mqtt_user": mqtt_user,
                "mqtt_pass": mqtt_pass,
                "mqtt_topic": mqtt_topic
            }
            topic = f"{MQTT_TOPIC_CONFIG}{node_id}"
            result = mqtt_client.publish(topic, json.dumps(config_data), qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                flash(f"配置已發送到 {node_id}", "success")
            else:
                flash(f"配置發送失敗 (rc={result.rc})", "danger")
            return redirect(url_for('config'))
        except Exception as e:
            flash(f"操作失敗: {str(e)}", "danger")
            return redirect(url_for('config'))

    return render_template('config.html', nodes=nodes, suggested_new=suggested_new)

@app.route('/delete_node', methods=['POST'])
def delete_node():
    try:
        node_id = request.form.get('node_id_to_delete')
        if not node_id:
            flash("請選擇要刪除的節點", "danger")
            return redirect(url_for('config'))
        redis_db.delete(f"soil_data:{node_id}")
        redis_db.delete(f"threshold:{node_id}")

        mysql_conn = get_mysql_connection(max_retries=2)
        if mysql_conn:
            cursor = None
            try:
                cursor = mysql_conn.cursor()
                cursor.execute("DELETE FROM soil_data WHERE node_id = %s", (node_id,))
                mysql_conn.commit()
                logger.info(f"✅ MySQL 節點刪除: {node_id}")
            except MySQLError as e:
                logger.warning(f"⚠️ MySQL 刪除失敗: {e}")
                mysql_conn.rollback()
            finally:
                if cursor:
                    try:
                        cursor.close()
                    except:
                        pass
                if mysql_conn.is_connected():
                    try:
                        mysql_conn.close()
                    except:
                        pass

        flash(f"節點 {node_id} 已刪除", "success")
        return redirect(url_for('config'))
    except Exception as e:
        flash(f"刪除失敗: {str(e)}", "danger")
        return redirect(url_for('config'))

# ====================== 健康檢查線程 ======================
def health_check_thread():
    while True:
        try:
            time.sleep(60)
            conn = get_mysql_connection(max_retries=1, retry_delay=0.5)
            if conn:
                cursor = None
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    if result and result[0] == 1:
                        logger.debug(f"✅ 數據庫健康檢查通過 ({datetime.now().strftime('%H:%M:%S')})")
                    else:
                        logger.warning("⚠️ 數據庫健康檢查返回異常")
                except Exception as e:
                    logger.warning(f"⚠️ 數據庫健康檢查執行失敗: {e}")
                finally:
                    if cursor:
                        try:
                            cursor.close()
                        except:
                            pass
                    if conn.is_connected():
                        try:
                            conn.close()
                        except:
                            pass
            else:
                logger.warning(f"⚠️ 數據庫健康檢查失敗：無法獲取連接")
        except Exception as e:
            logger.warning(f"⚠️ 健康檢查線程異常: {e}")
            time.sleep(5)

# ====================== 啟動 ======================
if __name__ == '__main__':
    health_thread = threading.Thread(target=health_check_thread, daemon=True)
    health_thread.start()
    logger.info("✅ 健康檢查線程已啟動")

    init_mqtt()

    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("正在關閉服務...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("✅ 服務正常關閉")
