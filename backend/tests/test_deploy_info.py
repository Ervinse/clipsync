"""系统信息：BUILD_INFO 解析、启动时登记部署记录、/api/admin/deploy-info 与部署备注的权限"""
from datetime import datetime

import pytest
from sqlalchemy import select, func

from app.core import deploy_info
from app.core.deploy_info import BuildInfo, read_build_file, parse_built_at, load_build_info, record_deployment
from app.models import Deployment, UserRole

BUILD_A = BuildInfo(app_version="1.0.0", commit_sha="aaaaaaaaaaaa", branch="master",
                    built_at=datetime(2026, 11, 1, 8, 0, 0))
BUILD_B = BuildInfo(app_version="1.1.0", commit_sha="bbbbbbbbbbbb", branch="master",
                    built_at=datetime(2026, 11, 10, 8, 0, 0))


def _record(db, build):
    async def _run(s):
        return (await record_deployment(s, build)).id
    return db(_run)


def _count(db):
    async def _run(s):
        return (await s.execute(select(func.count(Deployment.id)))).scalar()
    return db(_run)


@pytest.fixture
def running(monkeypatch):
    """把「正在运行的版本」换成指定的构建信息"""
    def _set(build):
        monkeypatch.setattr(deploy_info, "CURRENT_BUILD", build)
    return _set


# ---------- BUILD_INFO 解析 ----------

def test_read_build_file(tmp_path):
    path = tmp_path / "BUILD_INFO"
    path.write_text("commit=abc123\nbranch=feature/x\nbuilt=2026-11-12T08:30:00Z\n不是键值的行\n", encoding="utf-8")
    assert read_build_file(path) == {"commit": "abc123", "branch": "feature/x", "built": "2026-11-12T08:30:00Z"}


def test_missing_build_file_gives_empty_values(tmp_path):
    info = load_build_info(tmp_path / "BUILD_INFO")
    assert (info.commit_sha, info.branch, info.built_at) == ("", "", None)


@pytest.mark.parametrize("value,expected", [
    ("2026-11-12T08:30:00Z", datetime(2026, 11, 12, 8, 30, 0)),
    ("", None),
    ("2026-11-12 08:30:00", None),
    ("not a time", None),
])
def test_parse_built_at(value, expected):
    assert parse_built_at(value) == expected


# ---------- 登记部署记录 ----------

def test_same_build_restart_does_not_add_record(db):
    first = _record(db, BUILD_A)
    assert _record(db, BUILD_A) == first
    assert _count(db) == 1


def test_new_build_and_rollback_each_add_record(db):
    a = _record(db, BUILD_A)
    b = _record(db, BUILD_B)
    rollback = _record(db, BUILD_A)
    assert a < b < rollback
    assert _count(db) == 3


def test_same_commit_different_version_tag_adds_record(db):
    # 测试构建按提交号部署、晋级后改成版本号部署：同一份镜像，版本号不同，记为新部署
    _record(db, BuildInfo(app_version="aaaaaaaaaaaa", commit_sha="aaaaaaaaaaaa", branch="master", built_at=None))
    _record(db, BuildInfo(app_version="1.0.0", commit_sha="aaaaaaaaaaaa", branch="master", built_at=None))
    assert _count(db) == 2


# ---------- GET /api/admin/deploy-info ----------

def test_admin_reads_deploy_info(client, make_user, db, running):
    running(BUILD_B)
    _record(db, BUILD_A)
    current_id = _record(db, BUILD_B)
    admin = make_user(UserRole.ADMIN)
    resp = client.get("/api/admin/deploy-info", headers=admin.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_version"] == "1.1.0"
    assert body["commit_sha"] == "bbbbbbbbbbbb"
    assert body["branch"] == "master"
    assert body["built_at"] == "2026-11-10T08:00:00"
    assert body["uptime_seconds"] >= 0
    assert body["current"]["id"] == current_id
    assert [item["id"] for item in body["history"]] == [current_id, current_id - 1]
    assert body["total"] == 2


def test_deploy_info_without_matching_record(client, make_user, db, running):
    # 正在运行的版本没登记上（例如登记失败）：current 为空，历史照常返回
    running(BUILD_B)
    _record(db, BUILD_A)
    admin = make_user(UserRole.ADMIN)
    body = client.get("/api/admin/deploy-info", headers=admin.headers).json()
    assert body["current"] is None
    assert body["total"] == 1


def test_plain_user_cannot_read_deploy_info(client, make_user):
    user = make_user()
    assert client.get("/api/admin/deploy-info", headers=user.headers).status_code == 403


def test_deploy_info_requires_login(client):
    assert client.get("/api/admin/deploy-info").status_code == 401


# ---------- PATCH /api/admin/deployments/{id} ----------

def test_superadmin_edits_note(client, make_user, db):
    record_id = _record(db, BUILD_A)
    superadmin = make_user(UserRole.SUPERADMIN)
    resp = client.patch(f"/api/admin/deployments/{record_id}", json={"note": "  修复上传失败  "},
                        headers=superadmin.headers)
    assert resp.status_code == 200
    assert resp.json()["note"] == "修复上传失败"

    resp = client.patch(f"/api/admin/deployments/{record_id}", json={"note": ""}, headers=superadmin.headers)
    assert resp.json()["note"] == ""


def test_note_length_limit(client, make_user, db):
    record_id = _record(db, BUILD_A)
    superadmin = make_user(UserRole.SUPERADMIN)
    ok = client.patch(f"/api/admin/deployments/{record_id}", json={"note": "字" * 200}, headers=superadmin.headers)
    assert ok.status_code == 200
    too_long = client.patch(f"/api/admin/deployments/{record_id}", json={"note": "字" * 201},
                            headers=superadmin.headers)
    assert too_long.status_code == 422


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.USER])
def test_non_superadmin_cannot_edit_note(client, make_user, db, role):
    record_id = _record(db, BUILD_A)
    caller = make_user(role)
    resp = client.patch(f"/api/admin/deployments/{record_id}", json={"note": "x"}, headers=caller.headers)
    assert resp.status_code == 403

    async def _note(s):
        return (await s.get(Deployment, record_id)).note
    assert db(_note) == ""


def test_edit_note_unknown_record(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    resp = client.patch("/api/admin/deployments/999999", json={"note": "x"}, headers=superadmin.headers)
    assert resp.status_code == 404
