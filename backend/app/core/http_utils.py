"""HTTP 辅助：安全的下载响应头"""
import re
import unicodedata
from urllib.parse import quote

# 控制字符（含 CR/LF 与 U+0085）、行 / 段分隔符与路径分隔符
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f\x85  /\\]')
# Unicode「格式字符」（类别 Cf）不可见，其中的方向控制符（U+202E 等）能把 `invoice‮fdp.exe` 显示成
# `invoiceexe.pdf` 来伪装扩展名，零宽字符能让两个文件名看起来一样，一律删除；
# 零宽连接符 / 非连接符是 emoji 组合序列与波斯语、印度语系文字的正常组成部分，保留
_KEPT_FORMAT_CHARS = frozenset("‌‍")


def sanitize_filename(name: str) -> str:
    """清洗用户提供的文件名：去控制字符、路径分隔符与不可见的格式字符，空则给默认名"""
    visible = "".join(
        ch for ch in (name or "")
        if unicodedata.category(ch) != "Cf" or ch in _KEPT_FORMAT_CHARS
    )
    cleaned = _UNSAFE_CHARS.sub("_", visible).strip().strip(".")
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
