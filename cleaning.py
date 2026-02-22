import pandas as pd
import mysql.connector
import redis
from datetime import datetime

# =============================
# 数据库连接（增加超时与异常处理）
# =============================
try:
    mysql_db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="123456",
        database="greenhouse_soil",
        charset='utf8mb4',
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30
    )
    mysql_cursor = mysql_db.cursor(dictionary=True)   # 字典模式，更安全
    redis_db = redis.Redis(host="localhost", port=6379, db=0, 
                           decode_responses=True, socket_timeout=10)
except Exception as e:
    print(f"[{datetime.now()}] 数据库连接失败: {e}")
    exit(1)

# =============================
# 数据清洗函数
# =============================
def clean_soil_data(df):
    df = df.dropna(subset=["node_id", "temp", "hum", "collect_time"])
    df = df[(df["temp"] >= 0) & (df["temp"] <= 50)]
    df = df[(df["hum"] >= 0) & (df["hum"] <= 100)]
    df["temp"] = df["temp"].round(1)
    df["hum"] = df["hum"].round(1)
    return df

# =============================
# 核心：增量清洗
# =============================
try:
    # 获取已清洗的最大id（使用显式列名）
    mysql_cursor.execute("SELECT MAX(id) as max_id FROM soil_data")
    result = mysql_cursor.fetchone()
    last_id = result['max_id'] if result and result['max_id'] is not None else 0

    # 显式指定列，防止表结构变化
    sql = """
        SELECT id, node_id, temp, hum, collect_time 
        FROM soil_data_raw 
        WHERE id > %s 
        ORDER BY id ASC
    """
    mysql_cursor.execute(sql, (last_id,))
    result = mysql_cursor.fetchall()

    if not result:
        print(f"[{datetime.now()}] 无新数据需要清洗")
        # 优雅退出
    else:
        df = pd.DataFrame(result)   # dictionary=True 后自动用列名
        cleaned_df = clean_soil_data(df)

        # 批量插入（性能更好 + 去掉无用的 ON DUPLICATE）
        insert_sql = """
            INSERT INTO soil_data (node_id, temp, hum, collect_time)
            VALUES (%(node_id)s, %(temp)s, %(hum)s, %(collect_time)s)
        """
        data_list = []
        for _, row in cleaned_df.iterrows():
            collect_time = pd.to_datetime(row["collect_time"], errors='coerce')
            if pd.isna(collect_time):
                continue  # 跳过非法时间
            data_list.append({
                "node_id": row["node_id"],
                "temp": row["temp"],
                "hum": row["hum"],
                "collect_time": collect_time
            })

        if data_list:
            mysql_cursor.executemany(insert_sql, data_list)
            mysql_db.commit()

            # 更新 Redis（只存每个节点的最新一条）
            for node in cleaned_df["node_id"].unique():
                node_df = cleaned_df[cleaned_df["node_id"] == node]
                if not node_df.empty:
                    latest = node_df.iloc[-1]
                    redis_data = {
                        "temp": float(latest["temp"]),
                        "hum": float(latest["hum"]),
                        "collect_time": str(pd.to_datetime(latest["collect_time"]))
                    }
                    redis_db.hset(f"soil_data:{node}", mapping=redis_data)

            print(f"[{datetime.now()}] 清洗完成！本次有效数据 {len(data_list)} 条")
        else:
            print(f"[{datetime.now()}] 清洗完成！无有效数据")

except Exception as e:
    print(f"[{datetime.now()}] 清洗异常: {e}")
    mysql_db.rollback()
finally:
    # 确保资源释放
    mysql_cursor.close()
    mysql_db.close()
    redis_db.close()
