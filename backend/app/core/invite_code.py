"""邀请码格式：生成与注册时的输入规范化"""
import secrets

# 只用大写字母和数字，去掉容易看混的 0 O 1 I L
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUP_SIZE = 4
GROUP_COUNT = 3


def generate_invite_code() -> str:
    """生成 12 位邀请码，每 4 位一组用短横线分隔，如 K7QM-3XPD-9RWT（31^12 ≈ 7.9×10^17 种组合）"""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(GROUP_SIZE * GROUP_COUNT))
    return _group(raw)


def normalize_invite_code(value: str) -> str:
    """
    注册时输入的邀请码规范化：去掉空格与短横线、转大写后，
    若恰好是 12 位且只含邀请码字符，按标准格式分组返回；否则原样（去首尾空格）返回，
    兼容早期生成的 16 位大小写混合邀请码。
    """
    stripped = value.strip()
    compact = "".join(ch for ch in stripped if ch not in " -\t").upper()
    if len(compact) == GROUP_SIZE * GROUP_COUNT and all(ch in ALPHABET for ch in compact):
        return _group(compact)
    return stripped


def _group(raw: str) -> str:
    return "-".join(raw[i:i + GROUP_SIZE] for i in range(0, len(raw), GROUP_SIZE))
