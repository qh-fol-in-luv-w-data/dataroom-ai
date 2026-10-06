"""Upload-time file safety checks (master plan §4.2, L3).

Production uses Magika + ClamAV + YARA-X + oletools inside gVisor. The demo keeps the
same decision points with lightweight checks: true-type vs extension, a test malware
signature, encryption detection by bytes, and archive-bomb limits.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

MALWARE_SIGNATURES = (b"DATAROOM-DEMO-MALWARE-SIGNATURE",)
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
OOXML = {"docx", "xlsx", "pptx"}
MAX_UNZIPPED = 200 * 1024 * 1024
MAX_RATIO = 100


@dataclass
class SafetyResult:
    ok: bool
    reason: str | None = None
    encrypted: bool = False
    malware: bool = False


def sniff_type(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(OLE_MAGIC):
        return "ole"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return "text"


def inspect(data: bytes, ext: str) -> SafetyResult:
    ext = ext.lower().lstrip(".")
    if any(sig in data for sig in MALWARE_SIGNATURES):
        return SafetyResult(False, "Phát hiện chữ ký mã độc (quét on-prem)", malware=True)
    kind = sniff_type(data)
    if ext == "pdf":
        if kind != "pdf":
            return SafetyResult(False, "Loại file thật không khớp đuôi .pdf")
        try:
            from pypdf import PdfReader
            if PdfReader(io.BytesIO(data)).is_encrypted:
                return SafetyResult(False, "File PDF bị mã hóa/có mật khẩu", encrypted=True)
        except Exception as e:  # unreadable PDF is not "clean"
            return SafetyResult(False, f"PDF hỏng: {e.__class__.__name__}")
    elif ext in OOXML:
        if kind == "ole":
            return SafetyResult(False, "File Office được mã hóa (container OLE)", encrypted=True)
        if kind != "zip":
            return SafetyResult(False, f"Loại file thật không khớp đuôi .{ext}")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                total = sum(i.file_size for i in z.infolist())
                if total > MAX_UNZIPPED or total > MAX_RATIO * max(len(data), 1):
                    return SafetyResult(False, "Vượt giới hạn giải nén (nghi zip bomb)")
                if "EncryptedPackage" in z.namelist():
                    return SafetyResult(False, "File Office được mã hóa", encrypted=True)
        except zipfile.BadZipFile:
            return SafetyResult(False, "File Office hỏng")
    elif ext in ("png", "jpg", "jpeg"):
        if kind not in ("png", "jpg"):
            return SafetyResult(False, "Loại ảnh không khớp đuôi")
    elif ext in ("txt", "md", "csv", "html", "htm", "eml"):
        if kind in ("pdf", "ole", "zip"):
            return SafetyResult(False, f"File nhị phân mang đuôi .{ext}")
    return SafetyResult(True)
