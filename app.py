import os
from flask import Flask, request, jsonify, render_template
import mysql.connector
import redis
import json

app = Flask(__name__)

# 数据库连接
mysql_db = mysql.connector.connect(
    host="localhost",
    user="root",
    password=os.environ.get('DB_PASSWORD', '123456'),
    database="greenhouse_soil",
    charset='utf8mb4'
)
redis_db = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# ====================== 前端页面路由 ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/threshold')
def threshold():
    return render_template('threshold.html')

# ====================== API接口（与论文完全一致） ======================
@app.route('/api/realtime', methods=['GET'])
def get_realtime_data():
    try:
        realtime_data = {}
        node_keys = redis_db.keys("soil_data:*")
        for key in node_keys:
            node_id = key.split(":")[1]
            data = redis_db.hgetall(key)
            realtime_data[node_id] = data
        return jsonify({"code": 200, "msg": "success", "data": realtime_data})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"error: {str(e)}", "data": None})

@app.route('/api/history', methods=['GET'])
def get_history_data():
    try:
        node_id = request.args.get("node_id")
        start_time = request.args.get("start_time")
        end_time = request.args.get("end_time")
        if not all([node_id, start_time, end_time]):
            return jsonify({"code": 400, "msg": "missing parameters", "data": None})
        cursor = mysql_db.cursor(dictionary=True)
        sql = "SELECT temp, hum, collect_time FROM soil_data WHERE node_id=%s AND collect_time BETWEEN %s AND %s ORDER BY collect_time"
        cursor.execute(sql, (node_id, start_time, end_time))
        data = cursor.fetchall()
        return jsonify({"code": 200, "msg": "success", "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"error: {str(e)}", "data": None})

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
            return jsonify({"code": 400, "msg": "missing parameters", "data": None})
        threshold_key = f"threshold:{node_id}"
        redis_db.hset(threshold_key, mapping={
            "temp_min": temp_min, "temp_max": temp_max,
            "hum_min": hum_min, "hum_max": hum_max
        })
        return jsonify({"code": 200, "msg": "threshold set successfully"})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"error: {str(e)}"})

@app.route('/api/alert', methods=['GET'])
def get_alert_status():
    try:
        alert_status = {}
        node_keys = redis_db.keys("soil_data:*")
        for key in node_keys:
            node_id = key.split(":")[1]
            current_data = redis_db.hgetall(key)
            threshold = redis_db.hgetall(f"threshold:{node_id}")
            if not threshold:
                alert_status[node_id] = {"status": "normal", "msg": "未设置阈值"}
                continue
            try:
                temp = float(current_data.get("temp", 0))
                hum = float(current_data.get("hum", 0))
                t_min = float(threshold["temp_min"])
                t_max = float(threshold["temp_max"])
                h_min = float(threshold["hum_min"])
                h_max = float(threshold["hum_max"])
                if temp < t_min or temp > t_max or hum < h_min or hum > h_max:
                    alert_status[node_id] = {"status": "alert", "msg": "墒情异常，请及时处理"}
                else:
                    alert_status[node_id] = {"status": "normal", "msg": "墒情正常"}
            except:
                alert_status[node_id] = {"status": "error", "msg": "数据格式错误"}
        return jsonify({"code": 200, "msg": "success", "data": alert_status})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"error: {str(e)}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)