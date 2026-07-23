#!/bin/bash
# teaching-cultivator 云部署脚本 (Ubuntu 24.04)

set -e

echo "=== 1. 安装依赖 ==="
apt update
apt install -y python3 python3-pip git

echo "=== 2. 克隆项目 ==="
git clone https://github.com/longee142857/teaching-cultivator.git /opt/teaching-cultivator
cd /opt/teaching-cultivator

echo "=== 3. 安装 Python 包 ==="
pip3 install dingtalk-stream requests -q

echo "=== 4. 写入配置 === (手动)"
echo "请手动创建 .env 文件:"
echo "  cat > .env << EOF"
echo "  DINGTALK_CLIENT_ID=your_client_id"
echo "  DINGTALK_CLIENT_SECRET=your_client_secret"
echo "  DEEPSEEK_API_KEY=your_deepseek_key"
echo "  EOF"

echo "=== 5. 配置 systemd 服务 ==="
cat > /etc/systemd/system/teaching.service << 'SERVICEEOF'
[Unit]
Description=teaching-cultivator DingTalk Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/teaching-cultivator
ExecStart=/usr/bin/python3 /opt/teaching-cultivator/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable teaching
systemctl start teaching

echo "=== 6. 状态 ==="
sleep 10
systemctl status teaching --no-pager -l | head -20
echo ""
echo "部署完成！日志查看: journalctl -u teaching -f"
