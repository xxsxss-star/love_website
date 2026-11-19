# Our Love 情侣网站

一个可以自行部署的双人恋爱记录网站，包含情侣首页、纪念日、文字留言、愿望清单和每日心情。后端使用 FastAPI，数据保存在 SQLite 中，支持 Docker 一键部署。

## 功能

- 情侣首页：姓名、恋爱开始日期、相恋天数、下一纪念日倒计时
- 纪念日：名称、日期、是否每年重复
- 文字留言：留言内容、发送人和发送时间
- 愿望清单：添加愿望以及切换未完成/已完成状态
- 每日心情：选择 Emoji，并附加一句简短说明
- 移动端和桌面端自适应

## 服务器部署

以下步骤适用于 Ubuntu 22.04/24.04 或其他已安装 Docker 的 Linux 服务器。建议服务器至少具有 1 核 CPU、1 GB 内存和 10 GB 磁盘空间。

### 1. 登录服务器

```bash
ssh root@你的服务器公网IP
```

如果使用普通用户登录，请在需要管理员权限的命令前添加 `sudo`。

### 2. 安装 Git 和 Docker

```bash
apt update
apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version
docker compose version
```

如果服务器已经安装 Git、Docker 和 Docker Compose，可以跳过本步骤。

### 3. 从 GitHub 克隆项目

```bash
cd /opt
git clone https://github.com/xxsxss-star/love_website.git
cd love_website
```

### 4. 构建并启动

```bash
docker compose up -d --build
```

查看容器状态：

```bash
docker compose ps
```

查看运行日志：

```bash
docker compose logs -f --tail=100
```

日志中没有报错后，按 `Ctrl+C` 退出日志查看，不会停止网站。

### 5. 开放服务器端口

项目默认监听服务器的 `8000` 端口。如果服务器启用了 UFW：

```bash
ufw allow 8000/tcp
ufw status
```

云服务器还需要在厂商控制台的安全组中放行 TCP 端口 `8000`。

浏览器访问：

```text
http://你的服务器公网IP:8000
```

首次进入网站时，页面会要求设置两个人的名字和恋爱开始日期。

## 使用域名和 HTTPS（推荐）

先将域名的 A 记录解析到服务器公网 IP，再安装 Nginx：

```bash
apt install -y nginx certbot python3-certbot-nginx
```

创建配置文件：

```bash
nano /etc/nginx/sites-available/love-website
```

填入以下内容，将 `love.example.com` 替换为自己的域名：

```nginx
server {
    listen 80;
    server_name love.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用配置并申请 HTTPS 证书：

```bash
ln -s /etc/nginx/sites-available/love-website /etc/nginx/sites-enabled/love-website
nginx -t
systemctl reload nginx
certbot --nginx -d love.example.com
```

配置完成后通过 `https://love.example.com` 访问。此时可以在云安全组中关闭公网 `8000` 端口，仅保留 `80` 和 `443`；容器仍由本机 Nginx 访问。

## 更新网站

进入服务器项目目录，拉取最新代码并重新构建：

```bash
cd /opt/love_website
git pull
docker compose up -d --build
docker image prune -f
```

## 数据存储与备份

SQLite 数据保存在 Docker 命名卷 `love-data` 中。删除或重新构建容器不会丢失数据，但执行 `docker compose down -v` 会删除数据卷，请勿随意使用 `-v` 参数。

备份数据库：

```bash
cd /opt/love_website
docker compose exec -T love sh -c 'cat /app/data/love.db' > love-$(date +%F).db
```

将备份文件下载到本地电脑：

```bash
scp root@你的服务器公网IP:/opt/love_website/love-日期.db ./
```

## 停止与重启

```bash
cd /opt/love_website

# 停止
docker compose stop

# 启动
docker compose start

# 重启
docker compose restart

# 删除容器但保留数据
docker compose down
```

## 本地开发

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```

Linux/macOS：

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

本地网站地址为 `http://localhost:8000`，API 文档地址为 `http://localhost:8000/docs`。

## 技术栈

- 后端：FastAPI
- 数据库：SQLite
- 前端：HTML、CSS、原生 JavaScript
- 部署：Docker、Docker Compose
