# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库
mysql -u root -p < init_db.sql

# 3. 启动Redis（后台）
redis-server --daemonize yes

# 4. 启动后端
python app.py

# 5. 浏览器访问
http://你的IP:5000