#!/bin/bash

# os_env.sh 的自测：用伪造的 os-release、Nginx 目录与 python 桩命令，验证各发行版的识别结果
# 不需要 root，不修改系统文件，可在任意装有 bash 的机器上运行：
#   bash deployment/scripts/test_os_env.sh
# 全部通过时退出码为 0

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

export OS_RELEASE_FILE="$WORK/os-release"
export NGINX_DIR="$WORK/nginx"
# shellcheck source=os_env.sh
source "$SCRIPT_DIR/os_env.sh"

PASS=0
FAIL=0

check() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "✗ $name：期望 [$expected]，实际 [$actual]"
    fi
}

write_os_release() {
    printf '%s\n' "$@" > "$OS_RELEASE_FILE"
}

reset_vars() {
    OS_FAMILY=""; APP_USER=""; NGINX_SITE_CONF=""; NGINX_SITE_LINK=""; MYSQL_SERVICE=""
}

# ---------- detect_os：支持的发行版 ----------
expect_debian() {
    local name="$1"; shift
    reset_vars
    write_os_release "$@"
    detect_os >/dev/null 2>&1
    check "$name 识别成功" 0 $?
    check "$name OS_FAMILY" debian "$OS_FAMILY"
    check "$name APP_USER" www-data "$APP_USER"
    check "$name NGINX_SITE_CONF" "$NGINX_DIR/sites-available/clipsync" "$NGINX_SITE_CONF"
    check "$name NGINX_SITE_LINK" "$NGINX_DIR/sites-enabled/clipsync" "$NGINX_SITE_LINK"
    check "$name MYSQL_SERVICE" mysql "$MYSQL_SERVICE"
}

expect_rhel() {
    local name="$1"; shift
    reset_vars
    write_os_release "$@"
    detect_os >/dev/null 2>&1
    check "$name 识别成功" 0 $?
    check "$name OS_FAMILY" rhel "$OS_FAMILY"
    check "$name APP_USER" nginx "$APP_USER"
    check "$name NGINX_SITE_CONF" "$NGINX_DIR/conf.d/clipsync.conf" "$NGINX_SITE_CONF"
    check "$name NGINX_SITE_LINK" "" "$NGINX_SITE_LINK"
    check "$name MYSQL_SERVICE" mysqld "$MYSQL_SERVICE"
}

expect_unsupported() {
    local name="$1"; shift
    reset_vars
    write_os_release "$@"
    detect_os >/dev/null 2>&1
    check "$name 被拒绝" 1 $?
}

# 以下字段取自各发行版 /etc/os-release 的实际写法
expect_debian "Ubuntu 24.04" 'NAME="Ubuntu"' 'ID=ubuntu' 'ID_LIKE=debian' 'VERSION_ID="24.04"' 'PRETTY_NAME="Ubuntu 24.04 LTS"'
expect_debian "Ubuntu 22.04" 'ID=ubuntu' 'ID_LIKE=debian' 'VERSION_ID="22.04"'
expect_debian "Debian 12" 'ID=debian' 'VERSION_ID="12"' 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"'
expect_rhel "Rocky Linux 9" 'NAME="Rocky Linux"' 'ID="rocky"' 'ID_LIKE="rhel centos fedora"' 'VERSION_ID="9.4"' 'PRETTY_NAME="Rocky Linux 9.4 (Blue Onyx)"'
expect_rhel "AlmaLinux 9" 'ID="almalinux"' 'ID_LIKE="rhel centos fedora"' 'VERSION_ID="9.4"'
expect_rhel "RHEL 9" 'ID="rhel"' 'ID_LIKE="fedora"' 'VERSION_ID="9.4"'
expect_rhel "CentOS Stream 9" 'ID="centos"' 'ID_LIKE="rhel fedora"' 'VERSION_ID="9"'
expect_rhel "Rocky Linux 10" 'ID="rocky"' 'ID_LIKE="rhel centos fedora"' 'VERSION_ID="10.0"'

# ---------- detect_os：不支持的发行版 ----------
expect_unsupported "CentOS 7" 'ID="centos"' 'ID_LIKE="rhel fedora"' 'VERSION_ID="7"' 'PRETTY_NAME="CentOS Linux 7 (Core)"'
expect_unsupported "Rocky Linux 8" 'ID="rocky"' 'ID_LIKE="rhel centos fedora"' 'VERSION_ID="8.10"'
expect_unsupported "Fedora" 'ID=fedora' 'VERSION_ID=40'
expect_unsupported "Alpine" 'ID=alpine' 'VERSION_ID=3.20.0'
expect_unsupported "无 VERSION_ID 的 RHEL 系" 'ID="rocky"' 'ID_LIKE="rhel centos fedora"'

reset_vars
rm -f "$OS_RELEASE_FILE"
detect_os >/dev/null 2>&1
check "缺少 os-release 被拒绝" 1 $?

# CentOS 7 的提示要指向 Docker
write_os_release 'ID="centos"' 'ID_LIKE="rhel fedora"' 'VERSION_ID="7"' 'PRETTY_NAME="CentOS Linux 7 (Core)"'
MSG=$(detect_os 2>&1)
case "$MSG" in *Docker*) R=yes ;; *) R=no ;; esac
check "CentOS 7 提示改用 Docker" yes "$R"

# os-release 中的变量不泄漏到调用方
unset ID VERSION_ID
write_os_release 'ID="rocky"' 'ID_LIKE="rhel centos fedora"' 'VERSION_ID="9.4"'
detect_os >/dev/null 2>&1
check "ID 不泄漏" "" "${ID:-}"
check "VERSION_ID 不泄漏" "" "${VERSION_ID:-}"

# ---------- render_service_unit ----------
TEMPLATE="$SCRIPT_DIR/../systemd/clipsync.service"
OUT="$WORK/clipsync.service"

PROJECT_ROOT="/opt/clipsync"; APP_USER="nginx"; MYSQL_SERVICE="mysqld"
render_service_unit "$TEMPLATE" "$OUT"
check "rhel: User" "User=nginx" "$(grep '^User=' "$OUT")"
check "rhel: Group" "Group=nginx" "$(grep '^Group=' "$OUT")"
check "rhel: After" "After=network.target mysqld.service" "$(grep '^After=' "$OUT")"
check "rhel: Wants" "Wants=mysqld.service" "$(grep '^Wants=' "$OUT")"
check "rhel: WorkingDirectory" "WorkingDirectory=/opt/clipsync/backend" "$(grep '^WorkingDirectory=' "$OUT")"
check "rhel: EnvironmentFile" "EnvironmentFile=/opt/clipsync/backend/.env" "$(grep '^EnvironmentFile=' "$OUT")"
check "rhel: ExecStart 路径" 1 "$(grep -c '^ExecStart=/opt/clipsync/backend/venv/bin/uvicorn' "$OUT")"
check "rhel: 不残留默认路径" 0 "$(grep -c '/var/www/clipsync' "$OUT")"
check "rhel: 不残留 www-data" 0 "$(grep -c 'www-data' "$OUT")"
check "rhel: 不残留 mysql.service" 0 "$(grep -c 'mysql\.service' "$OUT")"
# 用 tr 统计 CR：部分平台的 grep 不能可靠匹配 $'\r'
check "rhel: 无 CR 字符" 0 "$(tr -cd '\r' < "$OUT" | wc -c | tr -d ' ')"
check "rhel: 仍为单 worker" 1 "$(grep -c -- '--workers 1' "$OUT")"

PROJECT_ROOT="/var/www/clipsync"; APP_USER="www-data"; MYSQL_SERVICE="mysql"
render_service_unit "$TEMPLATE" "$OUT"
check "debian: User" "User=www-data" "$(grep '^User=' "$OUT")"
check "debian: After" "After=network.target mysql.service" "$(grep '^After=' "$OUT")"
check "debian: WorkingDirectory" "WorkingDirectory=/var/www/clipsync/backend" "$(grep '^WorkingDirectory=' "$OUT")"

# ---------- find_python / python_ok（用桩命令模拟不同版本） ----------
STUB="$WORK/bin"
mkdir -p "$STUB"
make_python_stub() {
    # $1 命令名，$2 是否满足 3.12+（0 满足，1 不满足）
    printf '#!/bin/bash\nexit %s\n' "$2" > "$STUB/$1"
    chmod +x "$STUB/$1"
}

run_find_python() {
    # 只用桩目录与基础命令目录，排除宿主机上真实的 python
    PATH="$STUB:/usr/bin:/bin" find_python 2>/dev/null
}

rm -f "$STUB"/*
make_python_stub python3 0
check "python3 满足时选 python3" python3 "$(run_find_python)"

rm -f "$STUB"/*
make_python_stub python3 1
make_python_stub python3.12 0
check "Rocky 9（python3 为 3.9）选 python3.12" python3.12 "$(run_find_python)"

rm -f "$STUB"/*
make_python_stub python3 1
if [ -z "$(command -v -p python3.12 2>/dev/null)" ] && ! PATH="/usr/bin:/bin" command -v python3.12 >/dev/null 2>&1 \
    && ! PATH="/usr/bin:/bin" command -v python3.13 >/dev/null 2>&1 && ! PATH="/usr/bin:/bin" command -v python3.14 >/dev/null 2>&1; then
    run_find_python >/dev/null
    check "没有 3.12+ 时 find_python 失败" 1 $?
else
    echo "（跳过「没有 3.12+」用例：本机 /usr/bin 下有 python3.12+）"
fi

# ---------- nginx_default_site_warning ----------
mkdir -p "$NGINX_DIR/sites-enabled"

OS_FAMILY="debian"
rm -f "$NGINX_DIR/sites-enabled/default"
check "debian: 无默认站点时不提示" "" "$(nginx_default_site_warning)"
touch "$NGINX_DIR/sites-enabled/default"
case "$(nginx_default_site_warning)" in *sites-enabled/default*) R=yes ;; *) R=no ;; esac
check "debian: 有默认站点时提示" yes "$R"

OS_FAMILY="rhel"
# Rocky 9 自带 nginx.conf 的写法：http 块内有一个未注释的 server 块
cat > "$NGINX_DIR/nginx.conf" <<'EOF'
http {
    include /etc/nginx/conf.d/*.conf;

    server {
        listen       80;
        server_name  _;
    }
}
EOF
case "$(nginx_default_site_warning)" in *server*) R=yes ;; *) R=no ;; esac
check "rhel: nginx.conf 有默认 server 块时提示" yes "$R"

cat > "$NGINX_DIR/nginx.conf" <<'EOF'
http {
    include /etc/nginx/conf.d/*.conf;

#    server {
#        listen       80;
#    }
}
EOF
check "rhel: server 块已注释时不提示" "" "$(nginx_default_site_warning)"

# ---------- configure_selinux：未开启时什么都不做 ----------
rm -f "$STUB"/*
printf '#!/bin/bash\nexit 1\n' > "$STUB/selinuxenabled"; chmod +x "$STUB/selinuxenabled"
printf '#!/bin/bash\necho called >> "%s/setsebool.log"\n' "$WORK" > "$STUB/setsebool"; chmod +x "$STUB/setsebool"
PROJECT_ROOT="$WORK/project"
PATH="$STUB:$PATH" configure_selinux
check "SELinux 未开启: 返回 0" 0 $?
check "SELinux 未开启: 不调用 setsebool" no "$([ -f "$WORK/setsebool.log" ] && echo yes || echo no)"

# ---------- configure_selinux：开启时依次调用 setsebool / semanage / restorecon ----------
rm -f "$STUB"/*
LOG="$WORK/selinux.log"
: > "$LOG"
printf '#!/bin/bash\nexit 0\n' > "$STUB/selinuxenabled"
for cmd in setsebool restorecon; do
    printf '#!/bin/bash\necho "%s $*" >> "%s"\n' "$cmd" "$LOG" > "$STUB/$cmd"
done
# 模拟规则已存在：-a 失败，-m 成功
printf '#!/bin/bash\necho "semanage $*" >> "%s"\n[ "$2" = "-a" ] && exit 1\nexit 0\n' "$LOG" > "$STUB/semanage"
chmod +x "$STUB"/*
PATH="$STUB:$PATH" configure_selinux >/dev/null
check "SELinux 开启: 返回 0" 0 $?
check "SELinux 开启: setsebool" 1 "$(grep -c '^setsebool -P httpd_can_network_connect 1$' "$LOG")"
check "SELinux 开启: semanage -a 后回落 -m" 2 "$(grep -c "^semanage fcontext -[am] -t bin_t $PROJECT_ROOT/backend/venv/bin(/\.\*)?$" "$LOG")"
check "SELinux 开启: restorecon" 1 "$(grep -c "^restorecon -R $PROJECT_ROOT$" "$LOG")"

echo
echo "通过 $PASS 项，失败 $FAIL 项"
[ "$FAIL" -eq 0 ]
