"""Question language (BR-11): answer in the language the user asked in.

Vietnamese is recognised by its letters (ă â đ ê ô ơ ư and tone marks) and, for
accent-free typing, by common function words; English by its function words. Mixed
questions go to the language with more evidence; ties default to Vietnamese.
"""
from __future__ import annotations

import re
import unicodedata

from unidecode import unidecode

_VI_LETTERS = set("ăâđêôơưĂÂĐÊÔƠƯ")
_VI_WORDS = {"la", "cua", "bao", "nhieu", "nhung", "khong", "duoc", "cho", "voi", "trong", "cac", "nam", "ty", "dong",
             "gi", "nao", "sao", "co", "ve", "theo", "nay", "mot", "hay", "neu", "thi", "tai", "da", "se", "dang",
             "nhom", "cong", "ty", "hop", "phi", "gia", "von", "tong", "ban", "toi", "minh"}
_EN_WORDS = {"what", "is", "the", "of", "how", "much", "many", "which", "who", "when", "does", "did", "are", "for",
             "to", "and", "was", "were", "total", "net", "revenue", "price", "fee", "share", "shares", "please",
             "tell", "me", "about", "list", "show", "summarize", "summary", "compare", "in", "on", "with", "a", "an",
             "this", "that", "group", "company", "capacity", "contract", "where", "why", "per"}
_WORD = re.compile(r"[a-z]+")

NAMES = {"vi": "Tiếng Việt", "en": "English"}


def detect(text: str) -> str:
    t = unicodedata.normalize("NFC", text)
    marked = sum(1 for ch in t if ch in _VI_LETTERS or (unicodedata.decomposition(ch) and ch.isalpha()
                                                          and unidecode(ch) != ch))
    words = _WORD.findall(unidecode(t).lower())
    vi = 2 * marked + sum(w in _VI_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return "en" if en > vi else "vi"


# Fixed messages of the answer path, in English (BR-11: refusals in the question's language too).
EN = {
    "Không tìm thấy thông tin phù hợp trong các tài liệu bạn được phép truy cập.":
        "No relevant information was found in the documents you are allowed to access.",
    "Hệ thống chưa xác minh được đầy đủ nguồn lúc này, vui lòng thử lại sau ít phút.":
        "The sources could not be fully verified right now. Please try again in a few minutes.",
    "Trợ lý AI tạm ngừng để đảm bảo an toàn phân quyền. Vui lòng thử lại sau.":
        "The AI assistant is paused to keep access control safe. Please try again later.",
    "Tài khoản của bạn chưa được cấp quyền sử dụng trợ lý AI trong Data Room.":
        "Your account has not been granted access to the Data Room AI assistant.",
    ("Câu hỏi có dấu hiệu yêu cầu trợ lý bỏ qua quy tắc, tiết lộ cấu hình hoặc vượt quyền, nên không được xử lý. "
     "Hãy hỏi trực tiếp về nội dung tài liệu."):
        "The question appears to ask the assistant to bypass its rules, reveal its configuration or exceed your "
        "access, so it was not processed. Please ask about the documents' content directly.",
    ("Câu hỏi thuộc nhóm cần Ban IPO xem xét trước khi trả lời. Câu trả lời sẽ hiển thị tại đây sau khi được duyệt."):
        "This question belongs to a topic the IPO team reviews before answering. The answer will appear here "
        "once it has been approved.",
}


def tr(message: str, lang: str) -> str:
    return EN.get(message, message) if lang == "en" else message
