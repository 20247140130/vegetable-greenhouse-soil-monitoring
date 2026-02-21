CREATE DATABASE IF NOT EXISTS greenhouse_soil CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE greenhouse_soil;

CREATE TABLE IF NOT EXISTS soil_data_raw (
  id INT AUTO_INCREMENT PRIMARY KEY,
  node_id VARCHAR(20) NOT NULL,
  temp FLOAT(3,1),
  hum FLOAT(3,1),
  collect_time VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS soil_data (
  id INT AUTO_INCREMENT PRIMARY KEY,
  node_id VARCHAR(20) NOT NULL,
  temp FLOAT(3,1),
  hum FLOAT(3,1),
  collect_time DATETIME
);

CREATE INDEX idx_node_time ON soil_data (node_id, collect_time);