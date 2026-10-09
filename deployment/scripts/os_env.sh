#!/bin/bash

# ClipSync 部署脚本共用：识别发行版，给出各发行版不同的部署参数
# 由 deploy.sh 用 source 引入，单独执行没有效果；测试见同目录 test_os_env.sh
#
# 支持两类发行版：
#   debian：Debian 12、Ubuntu 22.04 / 24.04 等（os-release 的 ID 或 ID_LIKE 含 debian）
#   rhel：  Rocky Linux / AlmaLinux / RHEL / CentOS Stream 9 及以上（ID 或 ID_LIKE 含 rhel）
#
# detect_os 设置的变量：
#   OS_FAMILY        debian | rhel
#   OS_PRETTY_NAME   发行版名称（用于提示）
#   APP_USER         运行后端、持有项目文件的用户，与 Nginx 的运行用户一致
#   NGINX_SITE_CONF  站点配置的安装位置
#   NGINX_SITE_LINK  需要创建的启用软链；rhel 为空（conf.d 下的文件直接生效）
#   MYSQL_SERVICE    MySQL 的 systemd 服务名

# 两个路径可由环境变量覆盖，便于测试
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
NGINX_DIR="${NGINX_DIR:-/etc/nginx}"

detect_os() {
    if [ ! -f "$OS_RELEASE_FILE" ]; then
        echo "错误: 未找到 $OS_RELEASE_FILE，无法识别发行版" >&2
        return 1
    fi

    local info id id_like version_id pretty major
    # 在子 shell 里读取，os-release 中的变量不会泄漏到调用方
    info=$( . "$OS_RELEASE_FILE"; echo "${ID:-}|${ID_LIKE:-}|${VERSION_ID:-}|${PRETTY_NAME:-${ID:-unknown}}" )
    IFS='|' read -r id id_like version_id pretty <<< "$info"
    OS_PRETTY_NAME="$pretty"

    case " $id $id_like " in
        *" debian "*)
            OS_FAMILY="debian"
            APP_USER="www-data"
            NGINX_SITE_CONF="$NGINX_DIR/sites-available/clipsync"
            NGINX_SITE_LINK="$NGINX_DIR/sites-enabled/clipsync"
            MYSQL_SERVICE="mysql"
            ;;
        *" rhel "*)
            # 按主版本号数值比较（"10.0" 也算 9 以上）
            major="${version_id%%.*}"
            case "$major" in
                ''|*[!0-9]*) major=0 ;;
            esac
            if [ "$major" -lt 9 ]; then
                echo "错误: $pretty 不受支持。RHEL 系只支持 9 及以上（Rocky Linux / AlmaLinux / RHEL / CentOS Stream 9）" >&2
                echo "      CentOS 7 / 8 等旧版本装不上后端需要的 Python 3.12 与 Node.js 20+，请改用 Docker 部署（deployment/docker/README.md）" >&2
                return 1
            fi
            OS_FAMILY="rhel"
            APP_USER="nginx"
            NGINX_SITE_CONF="$NGINX_DIR/conf.d/clipsync.conf"
            NGINX_SITE_LINK=""
            MYSQL_SERVICE="mysqld"
            ;;
        *)
            echo "错误: 不支持的发行版 $pretty。直接部署支持 Debian / Ubuntu 与 Rocky Linux / AlmaLinux / RHEL 9+，其他系统请用 Docker 部署" >&2
            return 1
            ;;
    esac
}

# 解释器是否为 Python 3.12+（后端用到 shutil.rmtree(onexc=...) 等 3.12 才有的接口）
python_ok() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

# 输出第一个可用的 Python 3.12+ 解释器名；Rocky 9 的 python3 是 3.9，需要用 python3.12
find_python() {
    local cand
    for cand in python3 python3.12 python3.13 python3.14; do
        if command -v "$cand" >/dev/null 2>&1 && python_ok "$cand"; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}

# 按当前发行版渲染 systemd 服务文件：项目路径、运行用户、MySQL 服务名
# 用法: render_service_unit <模板> <目标文件>；依赖 PROJECT_ROOT、APP_USER、MYSQL_SERVICE
render_service_unit() {
    sed -e 's/\r$//' \
        -e "s|/var/www/clipsync|$PROJECT_ROOT|g" \
        -e "s|^User=.*|User=$APP_USER|" \
        -e "s|^Group=.*|Group=$APP_USER|" \
        -e "s|mysql\.service|$MYSQL_SERVICE.service|g" \
        "$1" > "$2"
}

# SELinux 是否处于开启状态（enforcing 或 permissive）；未安装 SELinux 工具视为未开启
selinux_enabled() {
    command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled
}

# SELinux 开启时（RHEL 系默认 enforcing）：
#   - 放行 Nginx 主动连接网络端口，否则反代到 127.0.0.1:8000 被拦，页面返回 502
#   - 把 backend/venv/bin 标为 bin_t：/var/www 下默认是 httpd_sys_content_t，
#     systemd 不能执行这种标签的文件，clipsync 服务会以 203/EXEC 启动失败
#   - 把项目文件恢复为上述安全上下文，否则从家目录 mv 过来的文件保留原标签，Nginx 读静态文件返回 403
# 未开启 SELinux 时什么都不做；semanage 由 policycoreutils-python-utils 提供，deploy.sh 第 2 步已检查
# 依赖 PROJECT_ROOT
configure_selinux() {
    selinux_enabled || return 0
    local venv_bin="$PROJECT_ROOT/backend/venv/bin(/.*)?"
    setsebool -P httpd_can_network_connect 1
    # 规则已存在（重复部署）时 -a 会失败，改用 -m 修改
    semanage fcontext -a -t bin_t "$venv_bin" 2>/dev/null || semanage fcontext -m -t bin_t "$venv_bin"
    restorecon -R "$PROJECT_ROOT"
    echo "SELinux: 已开启 httpd_can_network_connect，backend/venv/bin 标为 bin_t，并恢复 $PROJECT_ROOT 的安全上下文"
}

# 发行版自带的 Nginx 默认站点同样监听 80 端口，会抢走请求；
# 检测到时输出提示，不自动修改系统文件
nginx_default_site_warning() {
    case "$OS_FAMILY" in
        debian)
            if [ -e "$NGINX_DIR/sites-enabled/default" ]; then
                echo "检测到 Nginx 默认站点 $NGINX_DIR/sites-enabled/default（同样监听 80 端口）。不需要的话请删除: rm $NGINX_DIR/sites-enabled/default"
            fi
            ;;
        rhel)
            # 只匹配未注释的 server 块
            if grep -Eq '^[[:space:]]*server[[:space:]]*\{' "$NGINX_DIR/nginx.conf" 2>/dev/null; then
                echo "检测到 $NGINX_DIR/nginx.conf 自带的默认 server 块（同样监听 80 端口）。请把这个 server { ... } 块整段注释掉，再执行 nginx -t && systemctl reload nginx"
            fi
            ;;
    esac
    return 0
}
