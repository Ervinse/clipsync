"""HTTP 辅助：安全的下载响应头"""
import re
from urllib.parse import quote

# 控制字符（含 CR/LF）与路径分隔符
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f/\\]')


def sanitize_filename(name: str) -> str:
    """清洗用户提供的文件名：去控制字符与路径分隔符，空则给默认名"""
    cleaned = _UNSAFE_CHARS.sub("_", name or "").strip().strip(".")
    return cleaned[:255] or "file"


def content_disposition(filename: str) -> str:
    """
    按 RFC 6266 / 5987 生成 Content-Disposition。

    安全红线：文件名来自用户，ASCII 兜底名去掉引号与非 ASCII 字符，
    真实文件名走 filename* 百分号编码，杜绝头注入与引号截断。
    """
    safe = sanitize_filename(filename)
    ascii_fallback = re.sub(r'[^A-Za-z0-9._\- ]', "_", safe) or "file"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"
