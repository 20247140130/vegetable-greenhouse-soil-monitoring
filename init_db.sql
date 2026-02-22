-- ================================================
-- greenhouse_soil 数据库初始化脚本（最终稳定版）
-- 作者：王健   更新日期：2026.2.22
-- 特点：支持增量清洗、防重复插入、时间高效查询
-- ================================================

CREATE DATABASE IF NOT EXISTS greenhouse_soil 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_general_ci;

USE greenhouse_soil;

-- ==================== 原始数据表（日志缓存层） ====================
-- 允许重复，快速插入，作为清洗前的缓冲
CREATE TABLE IF NOT EXISTS soil_data_raw (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    node_id       VARCHAR(20) NOT NULL,
    temp          DECIMAL(4,1) NOT NULL COMMENT '土壤温度(℃)',
    hum           DECIMAL(4,1) NOT NULL COMMENT '土壤湿度(%RH)',
    collect_time  DATETIME NOT NULL,
    INDEX idx_raw_time (collect_time)              -- 加速按时间范围清洗
) ENGINE=InnoDB COMMENT='原始MQTT接收数据（允许重复）';

-- ==================== 正式数据表（清洗后数据） ====================
-- 必须保证同一节点同一时间只有一条记录
CREATE TABLE IF NOT EXISTS soil_data (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    node_id       VARCHAR(20) NOT NULL,
    temp          DECIMAL(4,1) NOT NULL COMMENT '土壤温度(℃)',
    hum           DECIMAL(4,1) NOT NULL COMMENT '土壤湿度(%RH)',
    collect_time  DATETIME NOT NULL,
    UNIQUE KEY unique_node_time (node_id, collect_time)  -- 核心防重 + 自动索引
) ENGINE=InnoDB COMMENT='清洗后的正式土壤墒情数据';

-- ==================== 可选额外索引（提升历史查询速度） ====================
-- UNIQUE KEY 已包含复合索引，此处再加一个纯时间索引（可选）
CREATE INDEX idx_soil_time ON soil_data (collect_time);

-- 初始化完成提示
SELECT '✅ greenhouse_soil 数据库初始化成功！' AS `初始化状态`;
