import pandas as pd
import mysql.connector
import redis
from datetime import datetime, timedelta

# 配置（建议改成环境变量）
mysql_db = mysql.connector.connect(
    host="localhost", user="root", password="123456", 
    database="greenhouse_soil", charset='utf8mb4'
)
mysql_cursor = mysql_db.cursor()
redis_db = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def clean_soil_data(df):
    df = df.dropna(subset=["node_id", "temp", "hum", "collect_time"])
    df = df[(df["temp"] >= 0) & (df["temp"] <= 50)]
    df = df[(df["hum"] >= 0) & (df["hum"] <= 100)]
    df["temp"] = df["temp"].round(1)
    df["hum"] = df["hum"].round(1)
    return df

# 只清洗最近1小时数据（防止重复）
one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
sql = f"SELECT * FROM soil_data_raw WHERE collect_time >= '{one_hour_ago}'"
mysql_cursor.execute(sql)
result = mysql_cursor.fetchall()

if not result:
    print(f"[{datetime.now()}] 无新数据需要清洗")
    exit()

df = pd.DataFrame(result, columns=["id", "node_id", "temp", "hum", "collect_time"])
cleaned_df = clean_soil_data(df)

try:
    for index, row in cleaned_df.iterrows():
        collect_time = pd.to_datetime(row["collect_time"])
        sql = """INSERT IGNORE INTO soil_data 
                 (node_id, temp, hum, collect_time) 
                 VALUES (%s, %s, %s, %s)"""
        val = (row["node_id"], row["temp"], row["hum"], collect_time)
        mysql_cursor.execute(sql, val)
    mysql_db.commit()

    # 更新 Redis 最新数据
    for node in cleaned_df["node_id"].unique():
        latest = cleaned_df[cleaned_df["node_id"] == node].iloc[-1]
        redis_data = {
            "temp": latest["temp"],
            "hum": latest["hum"],
            "collect_time": str(latest["collect_time"])
        }
        redis_db.hset(f"soil_data:{node}", mapping=redis_data)

    print(f"[{datetime.now()}] 清洗完成！有效数据 {len(cleaned_df)} 条")
except Exception as e:
    print(f"[{datetime.now()}] 清洗异常: {e}")
    mysql_db.rollback()
