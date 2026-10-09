#!/bin/bash
# ClipSync HTTPS 证书：用 certbot 向 Let's Encrypt 申请、续期证书（webroot 方式）
#
# 验证过程：Let's Encrypt 访问 http://<域名>/.well-known/acme-challenge/...，
# frontend 容器的 Nginx 从 ./acme 目录返回 certbot 写入的验证文件。
# 因此 frontend 必须在运行，域名必须已解析到本服务器，80 端口必须能从公网访问。
#
# 用法（root，在任意目录）：
#   bash /opt/clipsync/cert.sh issue <域名> <邮箱>   首次申请（或更换域名）
#   bash /opt/clipsync/cert.sh renew                 续期：离过期不到 30 天才真正续期，否则什么都不做（cron 每天执行）
# 证书保存在部署目录的 letsencrypt/，证书名固定为 clipsync（nginx-https.conf 按这个名字读取）。
# 申请成功后的切换步骤见 DEPLOYMENT.md「使用 HTTPS」。

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# build-release.ps1 -WithCertbot 按本行把 certbot 镜像打进镜像包
CERTBOT_IMAGE="certbot/certbot:v5.8.0"

log() { echo "[$(date '+%F %T')] $*"; }

certbot() {
    docker run --rm \
        -v "$PWD/letsencrypt:/etc/letsencrypt" \
        -v "$PWD/acme:/var/www/acme" \
        "$CERTBOT_IMAGE" "$@"
}

frontend_running() {
    docker compose ps --status running --services 2>/dev/null | grep -qx frontend
}

case "${1:-}" in
    issue)
        domain="${2:-}"
        email="${3:-}"
        if [ -z "$domain" ] || [ -z "$email" ]; then
            echo "用法：bash cert.sh issue <域名> <邮箱>" >&2
            exit 1
        fi
        if ! [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || [[ "$domain" != *.* ]]; then
            echo "域名格式不对：$domain（只写域名，不带 http:// 和路径）" >&2
            exit 1
        fi
        if [[ "$domain" =~ ^[0-9.]+$ ]]; then
            echo "本脚本只为域名申请证书，不支持 IP 地址：$domain" >&2
            exit 1
        fi
        if ! frontend_running; then
            echo "frontend 容器没有运行：先 docker compose up -d，再申请证书" >&2
            exit 1
        fi
        mkdir -p acme letsencrypt
        log "为 $domain 申请证书"
        certbot certonly --webroot -w /var/www/acme \
            --cert-name clipsync -d "$domain" \
            --email "$email" --agree-tos --no-eff-email --non-interactive
        log "申请成功。下一步：按 DEPLOYMENT.md「使用 HTTPS」修改 .env 并重建容器"
        ;;
    renew)
        if [ ! -d letsencrypt/live/clipsync ]; then
            log "还没有申请过证书，跳过续期"
            exit 0
        fi
        certbot renew --webroot -w /var/www/acme --non-interactive --quiet
        # 让 Nginx 读取可能更新过的证书；没有续期时重新加载也不影响访问
        if frontend_running; then
            docker compose exec -T frontend nginx -s reload
        fi
        log "续期检查完成"
        ;;
    *)
        echo "用法：bash cert.sh issue <域名> <邮箱> | bash cert.sh renew" >&2
        exit 1
        ;;
esac
