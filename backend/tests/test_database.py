"""数据库环境：MySQL 版本、字符集、会话时区、迁移版本

部署使用 MySQL 8.4 LTS（docker-compose.yml 固定版本号），测试库应与之一致。
"""
import re
from pathlib import Path

from sqlalchemy import text

from tests.conftest import TEST_DB_NAME, TEST_PASSWORD

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _scalar(db, sql, **params):
    async def _query(session):
        return (await session.execute(text(sql), params)).scalar()
    return db(_query)


def test_mysql_version_is_8_4_or_newer(db):
    version = _scalar(db, "SELECT VERSION()")
    major, minor = (int(part) for part in re.match(r"(\d+)\.(\d+)", version).groups())
    assert (major, minor) >= (8, 4), f"测试库是 MySQL {version}，部署环境为 8.4，请用 8.4 运行测试"


def test_session_time_zone_is_utc(db):
    # database.py 的 init_command 把会话时区固定为 UTC，server_default=now() 与 utcnow() 口径一致
    assert _scalar(db, "SELECT @@session.time_zone") == "+00:00"


def test_all_tables_use_utf8mb4(db):
    collations = db(lambda s: _table_collations(s))
    assert collations, "测试库里没有表"
    bad = {name: c for name, c in collations.items() if not c.startswith("utf8mb4")}
    assert not bad, f"这些表不是 utf8mb4，无法保存 emoji 等 4 字节字符：{bad}"


async def _table_collations(session):
    rows = await session.execute(
        text(
            "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME <> 'alembic_version'"
        ),
        {"schema": TEST_DB_NAME},
    )
    return {name: collation for name, collation in rows.all()}


def test_alembic_version_is_latest_revision(db):
    # conftest 用 alembic upgrade head 建表：库里的版本号应是没有被其他迁移引用的那个（head）
    revisions, parents = set(), set()
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        revisions.add(re.search(r"^revision\b[^=]*=\s*['\"]([^'\"]+)", source, re.M).group(1))
        down = re.search(r"^down_revision\b[^=]*=\s*['\"]([^'\"]+)", source, re.M)
        if down:
            parents.add(down.group(1))
    heads = revisions - parents
    assert len(heads) == 1, f"迁移有多个 head：{heads}"
    assert _scalar(db, "SELECT version_num FROM alembic_version") == heads.pop()


async def _username_collation(session):
    result = await session.execute(
        text(
            "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'users' AND COLUMN_NAME = 'username'"
        ),
        {"schema": TEST_DB_NAME},
    )
    return result.scalar()


def test_collation_matches_docker_deployment(db):
    # docker compose 由 MYSQL_DATABASE 自动建库，用 MySQL 8.4 的服务器默认规则 utf8mb4_0900_ai_ci（行尾空格有意义）；
    # 测试库必须同一规则，否则测不到部署环境的真实匹配行为（如 utf8mb4_unicode_ci 会忽略行尾空格）
    assert db(_username_collation) == "utf8mb4_0900_ai_ci"


def test_login_username_with_trailing_space_does_not_match(client, make_user):
    make_user(username="spacey")
    ok = client.post("/api/auth/login", json={"username": "spacey", "password": TEST_PASSWORD})
    assert ok.status_code == 200
    padded = client.post("/api/auth/login", json={"username": "spacey ", "password": TEST_PASSWORD})
    assert padded.status_code == 401


def test_four_byte_characters_round_trip(client, make_user):
    user = make_user()
    content = "emoji 😀🎉 生僻字 𠮷 中文"
    assert client.put("/api/clipboard", json={"content": content}, headers=user.headers).status_code == 200
    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == content
    # 归档进历史后同样完整
    client.put("/api/clipboard", json={"content": "next"}, headers=user.headers)
    history = client.get("/api/clipboard/history", headers=user.headers).json()["items"]
    assert history[0]["content"] == content
