import pandas as pd
import mysql.connector
import redis
from datetime import datetime, timedelta
import time   # 新增：用于实现循环等待

# ================== MySQL 配置（你提供的最新配置） ==================
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

# ================== Redis 配置 ==================
REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "db": 0,
    "decode_responses": True
}

# ================== 数据清洗函数 ==================
def clean_soil_data(df):
    print(f"[{datetime.now()}] 开始清洗数据，原始条数: {len(df)}")

    # 1. 去空值
    df = df.dropna(subset=["node_id", "temp", "hum", "collect_time"])

    # 2. 类型转换
    df["temp"] = pd.to_numeric(df["temp"], errors="coerce")
    df["hum"] = pd.to_numeric(df["hum"], errors="coerce")

    # 3. 再次去空（转换失败的行）
    df = df.dropna(subset=["temp", "hum"])

    # 4. 过滤异常值
    df = df[(df["temp"].between(-10, 60))]
    df = df[(df["hum"].between(0, 100))]

    # 5. 时间转换
    df["collect_time"] = pd.to_datetime(df["collect_time"], errors="coerce")
    df = df.dropna(subset=["collect_time"])

    # 6. 排序 + 去重
    df = df.sort_values(by=["node_id", "collect_time"])
    df = df.drop_duplicates(subset=["node_id", "collect_time"], keep="last")

    # 7. 精度控制
    df["temp"] = df["temp"].round(1)
    df["hum"] = df["hum"].round(1)

    print(f"[{datetime.now()}] 清洗完成，有效数据: {len(df)} 条")
    return df


# ================== 主程序 ==================
def main():
    print(f"[{datetime.now()}] === 土壤数据清洗任务开始 ===")

    # 连接 MySQL
    try:
        mysql_db = mysql.connector.connect(**MYSQL_CONFIG)
        mysql_cursor = mysql_db.cursor(dictionary=True)
        print(f"[{datetime.now()}] MySQL 连接成功")
    except Exception as e:
        print(f"[{datetime.now()}] MySQL 连接失败: {e}")
        return

    # 连接 Redis
    try:
        redis_db = redis.Redis(**REDIS_CONFIG)
        print(f"[{datetime.now()}] Redis 连接成功")
    except Exception as e:
        print(f"[{datetime.now()}] Redis 连接失败: {e}")
        if 'mysql_db' in locals():
            mysql_db.close()
        return

    try:
        # 获取最近24小时的原始数据（方便调试）
        one_day_ago = datetime.now() - timedelta(hours=24)
        sql = """
            SELECT id, node_id, temp, hum, collect_time
            FROM soil_data_raw
            WHERE collect_time >= %s
            ORDER BY collect_time
        """
        mysql_cursor.execute(sql, (one_day_ago,))
        result = mysql_cursor.fetchall()

        if not result:
            print(f"[{datetime.now()}] soil_data_raw 表中最近24小时没有新数据")
            print("   → 请先确认 ESP32 已成功上传数据到 soil_data_raw 表")
            return

        df = pd.DataFrame(result, columns=["id", "node_id", "temp", "hum", "collect_time"])

        # 清洗数据
        cleaned_df = clean_soil_data(df)

        if cleaned_df.empty:
            print(f"[{datetime.now()}] 清洗后无有效数据")
            return

        # ================== 写入 cleaned 表 ==================
        insert_sql = """
            INSERT IGNORE INTO soil_data (node_id, temp, hum, collect_time)
            VALUES (%s, %s, %s, %s)
        """
        values = list(
            cleaned_df[["node_id", "temp", "hum", "collect_time"]]
            .itertuples(index=False, name=None)
        )
        mysql_cursor.executemany(insert_sql, values)
        mysql_db.commit()

        # ================== 更新 Redis 最新数据 ==================
        latest_df = cleaned_df.groupby("node_id").tail(1)
        pipe = redis_db.pipeline()
        for _, row in latest_df.iterrows():
            pipe.hset(
                f"soil_data:{row['node_id']}",
                mapping={
                    "temp": str(row["temp"]),
                    "hum": str(row["hum"]),
                    "collect_time": str(row["collect_time"])
                }
            )
        pipe.execute()

        print(f"[{datetime.now()}] 清洗完成！原始 {len(df)} 条 → 有效 {len(cleaned_df)} 条，已更新 Redis")

    except mysql.connector.Error as db_err:
        print(f"[{datetime.now()}] MySQL 操作异常: {db_err}")
        if 'mysql_db' in locals():
            mysql_db.rollback()
    except Exception as e:
        print(f"[{datetime.now()}] 未知异常: {e}")
        if 'mysql_db' in locals():
            mysql_db.rollback()
    finally:
        if 'mysql_cursor' in locals():
            mysql_cursor.close()
        if 'mysql_db' in locals():
            mysql_db.close()


# ================== 5分钟循环执行 ==================
if __name__ == "__main__":
    print("=" * 70)
    print("土壤数据自动清洗服务已启动")
    print("每 5 分钟自动执行一次清洗任务")
    print("按 Ctrl + C 可停止服务")
    print("=" * 70)

    try:
        while True:
            main()                    # 执行一次清洗
            print(f"[{datetime.now()}] 下一次清洗将在 5 分钟后自动执行...\n")
            time.sleep(300)           # 300秒 = 5分钟

    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] 用户手动停止了清洗服务")
    except Exception as e:
        print(f"[{datetime.now()}] 服务异常退出: {e}")
