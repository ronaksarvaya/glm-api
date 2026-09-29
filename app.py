import os
from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    render_template,
    url_for
)
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
import pytesseract
import re
import os
from datetime import datetime
import json
from io import BytesIO

from ocr.service import get_ocr_engine, print_debug_info
import traceback
app = Flask(
    __name__,
    template_folder="dashboard",
    static_folder="dashboard"
)

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# ============================================================
# DASHBOARD CONFIG
#
# The review dashboard reads images from the existing local
# test image directory. Nothing is uploaded or sent anywhere.
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_DIR = os.path.join(BASE_DIR, "images", "images")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif")

# In-memory thumbnail cache: filename -> (bytes, mtime)
THUMB_CACHE = {}


# ============================================================
# OCR
# ============================================================

# ============================================================
# OCR IMAGE PREPROCESSING
#
# Tesseract is run over several renderings of the same image and
# the best scoring text wins. The original image is never modified
# and the untouched OCR text stays reachable via run_ocr_detail().
# ============================================================

OCR_TESSERACT_CONFIG = "--oem 3 --psm 3"

OCR_LABEL_PATTERNS = (
    r"GIVEN\s*NAME",
    r"SURNAME",
    r"DATE\s*O?F?\s*BIR",
    r"PL?ACE\s*O?F?\s*BIRT",
    r"PL?ACE\s*O?F?\s*(?:ISSUE|SUE|SVE)",
    r"DATE\s*O?F?\s*(?:ISSUE|EXPI)",
    r"\bSEX\b",
    r"NATIONALITY",
    r"PASSPORT\s*NO",
    r"REPUBLIC\s*OF\s*INDIA",
    r"BEARER",
    r"AUTHORITY",
    r"REGISTERED",
    r"MOTHER",
    r"FATHER",
    r"PLACE\s*O?F?\s*ISS",
)


def _to_gray(image):
    return image if image.mode == "L" else image.convert("L")


def _otsu_value(gray):
    hist = gray.histogram()
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    weight_b = 0
    sum_b = 0
    best = -1.0
    threshold = 128
    for t in range(256):
        weight_b += hist[t]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += t * hist[t]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        between = weight_b * weight_f * (mean_b - mean_f) ** 2
        if between > best:
            best = between
            threshold = t
    return threshold


def _contrast_boost(gray, cutoff=1, boost=1.4):
    stretched = ImageOps.autocontrast(gray, cutoff=cutoff)
    return ImageEnhance.Contrast(stretched).enhance(boost)


def _adaptive_threshold(gray, factor=0.85, radius=18):
    local = gray.filter(ImageFilter.BoxBlur(radius))
    diff = ImageChops.subtract(gray, local.point(lambda v: int(v * factor)))
    return diff.point(lambda v: 255 if v > 0 else 0, mode="L")


OCR_MRZ_NAME_RE = re.compile(r"P<[^A-Z0-9]{0,3}[A-Z]{3}")
MRZ_WEIGHTS = (7, 3, 1)


def _mrz_check_digit(data):
    total = 0
    for i, ch in enumerate(data):
        if ch.isdigit():
            value = int(ch)
        elif "A" <= ch <= "Z":
            value = ord(ch) - 55
        elif ch == "<":
            value = 0
        else:
            return None
        total += value * MRZ_WEIGHTS[i % 3]
    return str(total % 10)


def _mrz_quality(text):
    quality = {"name_line": False, "number_line": False, "checks_ok": 0, "checks_bad": 0, "corrupt": 0}
    for raw in text.splitlines():
        line = re.sub(r"[^A-Z0-9<]+", "?", raw.upper()).replace("?", "\ufffd")
        if len(line) < 30:
            continue
        if not quality["name_line"] and OCR_MRZ_NAME_RE.match(line):
            quality["name_line"] = True
            continue
        digits = sum(1 for c in line if c.isdigit())
        if quality["number_line"] or digits < 18 or len(line) < 36:
            continue
        quality["number_line"] = True
        quality["corrupt"] += line.count("\ufffd")
        for start, length, check_at in ((0, 9, 9), (13, 6, 19), (21, 6, 27)):
            expected = _mrz_check_digit(line[start:start + length])
            check = line[check_at:check_at + 1]
            if expected is None or not check.isdigit() or expected != check:
                quality["checks_bad"] += 1
            else:
                quality["checks_ok"] += 1
    return quality


def build_ocr_candidates(image):
    gray = _to_gray(image)
    stretched = _contrast_boost(gray)
    otsu = _otsu_value(gray)
    return {
        "original": image,
        "grayscale": gray,
        "contrast": stretched,
        "upscale2x": gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS),
        "adaptive": _adaptive_threshold(stretched),
        "otsu": gray.point(lambda v: 255 if v > otsu else 0, mode="L"),
    }


def score_ocr_text(text):
    if not text:
        return -1000.0
    upper = text.upper()
    score = 0.0
    for pattern in OCR_LABEL_PATTERNS:
        if re.search(pattern, upper):
            score += 12.0
    words = re.findall(r"[A-Z]{3,}", upper)
    score += min(len(words), 90) * 0.6
    score += min(len(set(words)), 60) * 0.4
    score += 20.0 * len(re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", upper))
    if OCR_MRZ_NAME_RE.search(upper):
        score += 30.0
    score += 10.0 * len(re.findall(r"\b[A-Z][0-9]{7}[0-9A-Z<]?\b", upper))
    mrz = _mrz_quality(upper)
    if mrz["name_line"]:
        score += 20.0
    if mrz["number_line"]:
        score += 25.0
    score += 30.0 * mrz["checks_ok"]
    score -= 18.0 * mrz["checks_bad"]
    score -= 12.0 * mrz["corrupt"]
    for line in text.splitlines():
        if not line.strip():
            continue
        marks = sum(1 for c in line if not c.isalnum() and not c.isspace())
        if marks > len(line) * 0.35:
            score -= 1.5
    score -= 6.0 * upper.count("\ufffd")
    score -= 4.0 * upper.count("|")
    return score


OCR_PREFER_ORIGINAL_WITH_MRZ = True


def _original_is_authoritative(text):
    upper = text.upper()
    mrz = _mrz_quality(upper)
    if mrz["number_line"] and mrz["checks_ok"] >= 2:
        return True
    if not mrz["name_line"]:
        return False
    return any(
        _mrz_check_digit(match.group(1) + "<") == match.group(2)
        for match in re.finditer(r"([A-Z][0-9]{7})<?([0-9])", upper)
    )


def run_ocr_detail(image):
    candidates = build_ocr_candidates(image)
    results = {}

    def ocr_variant(name):
        try:
            results[name] = pytesseract.image_to_string(
                candidates[name], config=OCR_TESSERACT_CONFIG
            )
        except Exception:
            results[name] = ""

    ocr_variant("original")

    authoritative = bool(
        OCR_PREFER_ORIGINAL_WITH_MRZ
        and _original_is_authoritative(results["original"])
    )
    if authoritative:
        skipped = [name for name in candidates if name != "original"]
    else:
        mrz = _mrz_quality(results["original"].upper())
        # If any MRZ is detected, it's a Passport Front, skip upscale2x
        skip_upscale = mrz["name_line"] or mrz["number_line"]
        
        skipped = []
        for name in candidates:
            if name != "original":
                if name == "upscale2x" and skip_upscale:
                    skipped.append(name)
                    continue
                ocr_variant(name)

    scores = {n: score_ocr_text(t) for n, t in results.items()}
    best_name = "original" if authoritative else max(scores, key=lambda n: scores[n])
    return {
        "variant": best_name,
        "score": scores[best_name],
        "text": results[best_name],
        "original_text": results["original"],
        "skipped": skipped,
        "all": {n: {"score": scores[n], "text": t} for n, t in results.items()},
    }


def run_ocr(image):
    return run_ocr_detail(image)["text"]


# ============================================================
# DOCUMENT DETECTION
# ============================================================

def detect_document(text):
    upper = text.upper()









    # PAN
    if (
        "INCOME TAX DEPARTMENT" in upper
        or "PERMANENT ACCOUNT NUMBER" in upper
        or re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", upper)
    ):
        return "PAN"

    # Passport
    if (
        "PASSPORT" in upper
        or "P<IND" in upper
        or re.search(r"\b[A-Z][0-9]{7}\b", upper)
    ):
        # Back usually contains parent/spouse/address information
        if any(word in upper for word in [
            "FATHER",
            "MOTHER",
            "SPOUSE",
            "ADDRESS"
        ]):
            return "PASSPORT_BACK"

        return "PASSPORT_FRONT"

    return "UNKNOWN"


# ============================================================
# PASSPORT FRONT
# ============================================================

def extract_passport_front(text):
    import re

    raw = text or ""
    lines = raw.splitlines()
    upper = raw.upper()

    # ---------- date primitives ----------

    def valid_date(value):
        if not value or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(value)):
            return None
        try:
            datetime.strptime(value, "%d/%m/%Y")
        except ValueError:
            return None
        return value

    MONTH_REPAIR = {"92": "12"}

    def repair_date(token):
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(token).strip())
        if not m:
            return None
        day, month, year = m.group(1), m.group(2), m.group(3)
        direct = valid_date(f"{day.zfill(2)}/{month}/{year}")
        if direct:
            return direct
        fixed = MONTH_REPAIR.get(month)
        if fixed:
            return valid_date(f"{day.zfill(2)}/{fixed}/{year}")
        return None

    def parse_mrz_date(six, kind):
        if not six or not re.fullmatch(r"\d{6}", six):
            return None
        yy, mm, dd = int(six[0:2]), six[2:4], six[4:6]
        if kind == "dob":
            year = 2000 + yy if yy <= 26 else 1900 + yy
        else:
            year = 2000 + yy
        return valid_date(f"{dd}/{mm}/{year:04d}")

    # ---------- MRZ normalization + parsing ----------

    def compact(line):
        return re.sub(r"\s+", "", line.upper())

    cleaned = [compact(l) for l in lines]
    cleaned = [c for c in cleaned if c]

    def looks_like_mrz2(candidate):
        if len(candidate) < 15 or not re.fullmatch(r"[A-Z0-9<]+", candidate):
            return False
        return bool(re.match(r"^[A-Z][0-9]{7}[0-9A-Z<]", candidate))

    mrz2 = None
    for c in cleaned:
        if looks_like_mrz2(c):
            mrz2 = c
            break
    if mrz2 is None:
        for i in range(len(cleaned) - 1):
            joined = cleaned[i] + cleaned[i + 1]
            if looks_like_mrz2(joined) and len(joined) > len(cleaned[i]):
                mrz2 = joined
                break

    if mrz2 and len(mrz2) < 28:
        best = None
        for c in cleaned:
            if c is mrz2 or not 5 <= len(c) < 28:
                continue
            if not re.fullmatch(r"[A-Z0-9<]+", c) or not re.search(r"\d", c):
                continue
            joined = mrz2 + c
            joined_expiry = parse_mrz_date(joined[21:27], "expiry") if len(joined) >= 27 else None
            joined_sex = joined[20] if len(joined) > 20 else None
            if not joined_expiry and joined_sex not in ("M", "F", "N"):
                continue
            score = (1 if joined_expiry else 0) + (1 if joined_sex in ("M", "F", "N") else 0)
            if best is None or score > best[0]:
                best = (score, joined)
        if best:
            mrz2 = best[1]

    mrz1 = None
    for c in cleaned:
        if c.startswith("P<") and len(c) > 10:
            mrz1 = c
            break

    def mrz_field(start, end):
        if not mrz2 or len(mrz2) < end:
            return None
        chunk = mrz2[start:end]
        return chunk if chunk.strip("<") else None

    mrz_passport = mrz_field(0, 9)
    if mrz_passport:
        mrz_passport = re.sub(r"<+$", "", mrz_passport)
        if not re.fullmatch(r"[A-Z][0-9]{7}(?:[0-9A-Z])?", mrz_passport):
            mrz_passport = None

    mrz_dob = parse_mrz_date(mrz_field(13, 19), "dob")
    mrz_expiry = parse_mrz_date(mrz_field(21, 27), "expiry")

    mrz_sex = mrz_field(20, 21)
    if mrz_sex:
        if mrz_sex == "N":
            mrz_sex = "M"
        elif mrz_sex not in ("M", "F"):
            mrz_sex = None

    def clean_mrz_name(value):
        v = value.replace("<", " ")
        v = re.sub(r"\s+", " ", v).strip()
        v = re.split(r"\s*K{3,}", v, 1)[0].strip()
        return v or None

    mrz_surname = mrz_given = None
    if mrz1:
        body = re.sub(r"^P<[A-Z]{3}", "", mrz1, count=1) if mrz1.startswith("P<") else mrz1
        surname_part = re.split(r"<<", body, 1)[0]
        mrz_surname = clean_mrz_name(surname_part)
        rest = body.split("<<", 1)[1] if "<<" in body else ""
        mrz_given = clean_mrz_name(rest)

    # ---------- label-based visible fields ----------

    LABEL = {
        "given_name": (r"GIVEN\s*NAME",),
        "place_of_birth": (
            r"PL?ACE\s*(?:A|OF)?\s*BIRT",
            r"PLACE\s*[O0]F?\s*BIRT",
        ),
        "place_of_issue": (
            r"PL?ACE\s*(?:A|OF)?\s*(?:ISSUE|SUE|SVE)",
        ),
        "date_of_birth": (
            r"DATE\s*(?:A|OF)?\s*BIRT",
            r"DATE\s*O[F]?\s*BIR",
        ),
        "date_of_issue": (
            r"DATE\s*(?:A|OF)?\s*(?:T?S?S?UE|ISSUE|SVE)",
            r"DATE\s*O[F]?\s*S",
        ),
        "date_of_expiry": (
            r"DATE\s*(?:A|OF)?\s*EX",
            r"DATE\s*O[F]?\s*EY",
        ),
    }
    ALL_LABELS = [p for pats in LABEL.values() for p in pats]

    def is_label_line(line):
        u = line.upper().strip()
        if not u:
            return True
        if " / " in line:
            return True
        if u.startswith("P<") or looks_like_mrz2(compact(u)):
            return True
        if any(re.search(p, u) for p in ALL_LABELS):
            return True
        return len(u.split()) >= 6

    def looks_like_value(line):
        u = line.strip().upper()
        if len(u) < 3 or is_label_line(line):
            return False
        letters = [c for c in u if c.isalpha()]
        if len(letters) < 2:
            return False
        if sum(1 for c in letters if c.isupper()) / len(letters) < 0.6:
            return False
        if re.search(r"\d{4,}", u):
            return False
        first = re.match(r"[A-Z]+", u)
        return bool(first and len(first.group(0)) >= 3)

    def label_line(field):
        pats = LABEL[field]
        for i, line in enumerate(lines):
            if any(re.search(p, line.upper()) for p in pats):
                return i
        return None

    def value_after(idx, span=3):
        if idx is None:
            return None
        for j in range(idx + 1, min(idx + span + 1, len(lines))):
            if looks_like_value(lines[j]):
                return j
        return None

    def text_at(idx):
        return lines[idx].strip() if idx is not None and 0 <= idx < len(lines) else None

    def name_like(value):
        if not value or not re.fullmatch(r"[A-Z][A-Z .'\-]{1,39}", value.strip().upper()):
            return False
        if len(value.split()) > 3:
            return False
        return not re.search(r"\b(?:DATE|BIRT|ISSUE|EXPI|PLACE|GIVEN|SEX|NAME)\b", value.upper())

    def normalize_place(value):
        if not value:
            return None
        v = re.sub(r"\s*,\s*", ", ", str(value).strip())
        if "," in v:
            head, tail = (p.strip() for p in v.split(",", 1))
            if head and tail and (head.startswith(tail) or tail.startswith(head)):
                v = head
            elif head and tail:
                v = f"{head}, {tail}"
            else:
                v = head or tail
        else:
            parts = v.split()
            v = parts[0] if parts else v
        v = re.sub(r"\s+", " ", v).strip(" ,")
        if len(v) < 3:
            return None
        if re.search(r"K{4,}", v) or re.search(r"(?:5K|5K5K|K5K)", v):
            return None
        return v

    # ---------- date pipeline ----------

    DATE_TOKEN = r"\b\d{1,2}/\d{1,2}/\d{4}\b"
    dates = []
    for i, line in enumerate(lines):
        for tok in re.findall(DATE_TOKEN, line):
            dates.append({"line": i, "raw": tok, "value": repair_date(tok)})
    valid_dates = [d for d in dates if d["value"]]

    def dates_near(idx, span=2):
        if idx is None:
            return []
        out = []
        for d in valid_dates:
            if 0 <= d["line"] - idx <= span:
                out.append(d)
        return out

    dob_line = None
    dob = mrz_dob
    if dob:
        for d in valid_dates:
            if d["value"] == dob:
                dob_line = d["line"]
                break
    if not dob:
        birth_label = label_line("date_of_birth")
        candidates = dates_near(birth_label) or dates_near(label_line("place_of_birth"), span=3)
        for d in candidates:
            if dob is None:
                dob = d["value"]
                dob_line = d["line"]
    if not dob:
        for d in valid_dates:
            tail = lines[d["line"]].upper()[len(d["raw"]):]
            if re.search(r"\b[MF]\b", tail):
                dob = d["value"]
                dob_line = d["line"]
                break

    expiry = mrz_expiry
    if not expiry:
        for d in dates_near(label_line("date_of_expiry"), span=2):
            if d["value"] and d["value"] != dob:
                expiry = d["value"]
                break

    issue = None
    issue_label = label_line("date_of_issue")
    rest = [d["value"] for d in valid_dates if d["value"] != dob and d["value"] != expiry]
    for d in dates_near(issue_label, span=2):
        if d["value"] and d["value"] != dob and d["value"] != expiry:
            issue = d["value"]
            break
    if not issue and mrz_expiry and expiry and len(rest) == 1:
        issue = rest[0]

    # ---------- sex ----------

    sex = mrz_sex
    if not sex and dob_line is not None:
        m = re.search(r"\b([MF])\b", lines[dob_line].upper())
        if m:
            sex = m.group(1)

    # ---------- passport number ----------

    passport = mrz_passport
    if not passport:
        m = re.search(r"\b[A-Z][0-9]{7}[0-9A-Z]\b", upper)
        if m:
            passport = m.group(0)

    # ---------- names ----------

    surname = mrz_surname

    given = None
    g_line = value_after(label_line("given_name"))
    g_text = text_at(g_line)
    if g_text and name_like(g_text):
        given = g_text.strip().upper()

    if not given:
        region_end = dob_line
        if region_end is None:
            region_end = valid_dates[0]["line"] if valid_dates else len(lines)
        surname_stem = None
        if surname:
            surname_stem = re.split(r"[\s,]+", surname)[0]
        candidates = []
        for i in range(0, min(region_end, len(lines))):
            candidate = lines[i].strip().upper()
            if not name_like(candidate) or not looks_like_value(lines[i]):
                continue
            if surname_stem and candidate.split(" ")[0] == surname_stem:
                continue
            candidates.append(candidate)
        if candidates:
            given = candidates[-1]

    if not given:
        given = mrz_given

    # ---------- places ----------

    def place_label_row():
        for i, line in enumerate(lines):
            if re.search(r"\bPL?ACE\b\s*(?:OF|A|\d+\b)", line.upper()):
                return i
        return None

    def place_candidates(row, exclude_idx=()):
        if row is None:
            return []
        out = []
        for j in range(max(0, row - 2), min(row + 3, len(lines))):
            if dob_line is not None and abs(j - dob_line) <= 1:
                continue
            if j in exclude_idx or not looks_like_value(lines[j]):
                continue
            out.append(j)
        return out

    pob_line = value_after(label_line("place_of_birth"))
    place_of_birth = normalize_place(text_at(pob_line))

    place_of_issue = None
    poi_line = value_after(label_line("place_of_issue"))
    if poi_line is not None:
        place_of_issue = normalize_place(text_at(poi_line))

    row = place_label_row()
    if not place_of_birth:
        row_pob = place_candidates(row)
        if row_pob:
            pob_line = row_pob[0]
            place_of_birth = normalize_place(text_at(pob_line))
    if not place_of_issue:
        taken = (pob_line,) if pob_line is not None else ()
        for j in place_candidates(row, exclude_idx=taken):
            place_of_issue = normalize_place(text_at(j))
            if place_of_issue:
                break
    if not place_of_issue and pob_line is not None:
        for j in range(pob_line + 1, min(pob_line + 4, len(lines))):
            if looks_like_value(lines[j]):
                place_of_issue = normalize_place(text_at(j))
                if place_of_issue:
                    break

    return {
        "passport_number": passport,
        "surname": surname,
        "given_name": given,
        "date_of_birth": dob,
        "sex": sex,
        "place_of_birth": place_of_birth,
        "place_of_issue": place_of_issue,
        "date_of_issue": issue,
        "date_of_expiry": expiry,
    }


def extract_passport_back(text):

    upper = text.upper()
    lines = [line.strip() for line in upper.splitlines() if line.strip()]

    result = {
        "father_name": None,
        "mother_name": None,
        "spouse_name": None,
        "address": None
    }

    def normalize_label(s):
        s = s.lower()
        s = re.sub(r"[^a-z0-9\s]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    father_label_re = re.compile(r"\b(father|fathcr|guarda|guardian)\b")
    mother_label_re = re.compile(r"\b(mother|mothcr)\b")
    spouse_label_re = re.compile(r"\b(spouse)\b")
    address_label_re = re.compile(r"\b(address|addres|aaeens|acres|adress)\b")

    def find_name_after_label(label_re):
        for i, line in enumerate(lines):
            norm = normalize_label(line)
            if label_re.search(norm):
                for j in range(1, 3):
                    if i + j < len(lines):
                        candidate = lines[i + j]
                        c_norm = normalize_label(candidate)
                        
                        if len(c_norm) < 3:
                            continue
                            
                        if label_re != father_label_re and father_label_re.search(c_norm):
                            break
                        if label_re != mother_label_re and mother_label_re.search(c_norm):
                            break
                        if label_re != spouse_label_re and spouse_label_re.search(c_norm):
                            break
                        if address_label_re.search(c_norm):
                            break
                            
                        if re.search(r"\b(road|distt|pin|sector|house|nagar|colony|marg|street)\b", c_norm):
                            break
                            
                        return candidate
                break
        return None

    result["father_name"] = find_name_after_label(father_label_re)
    result["mother_name"] = find_name_after_label(mother_label_re)
    result["spouse_name"] = find_name_after_label(spouse_label_re)

    address_lines = []
    found_address = False
    for line in lines:
        norm = normalize_label(line)
        if not found_address:
            if address_label_re.search(norm):
                found_address = True
            continue
            
        if re.search(r"\b(old\s*passport|file\s*no|date\s*and\s*place|passport\s*no|file\s*to)\b", norm):
            break
        if re.search(r"\b(petpet|mace|dotan pace|ferfes|cer ei|ater me|aeraie|cert cer)\b", norm):
            break
        if re.fullmatch(r"[a-z0-9\$]{12,16}", norm.replace(" ", "")):
            break
        if re.search(r"\d{2}/\d{2}/\d{4}", line):
            break
            
        address_lines.append(line)
        
    if address_lines:
        result["address"] = " ".join(address_lines).strip()

    return result


# ============================================================
# PAN
# ============================================================

def extract_pan(text):

    upper = text.upper()
    lines = [line.strip() for line in upper.splitlines() if line.strip()]

    result = {
        "pan_number": None,
        "name": None,
        "father_name": None,
        "date_of_birth": None
    }

    # 1. PAN Number
    pan_candidates = re.findall(r"\b[A-Z0-9]{10}\b", upper)
    
    def correct_pan(candidate):
        letters = candidate[:5]
        numbers = candidate[5:9]
        last = candidate[9:]
        
        l_map = {'0': 'O', '1': 'I', '5': 'S', '8': 'B'}
        corrected_l = "".join(l_map.get(c, c) for c in letters)
        
        n_map = {'O': '0', 'I': '1', 'S': '5', 'B': '8'}
        corrected_n = "".join(n_map.get(c, c) for c in numbers)
        
        corrected_last = "".join(l_map.get(c, c) for c in last)
        
        final_pan = corrected_l + corrected_n + corrected_last
        
        if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", final_pan):
            return final_pan
        return None

    for cand in pan_candidates:
        corrected = correct_pan(cand)
        if corrected:
            result["pan_number"] = corrected
            break

    # 2. DOB
    dob_match = re.search(r"\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b", upper)
    if dob_match:
        day, month, year = dob_match.groups()
        dob_str = f"{day}/{month}/{year}"
        try:
            datetime.strptime(dob_str, "%d/%m/%Y")
            result["date_of_birth"] = dob_str
        except ValueError:
            pass

    # 3. Names
    def clean_name(s):
        s = re.sub(r"[^A-Z\s]", "", s).strip()
        s = re.sub(r"\s+", " ", s)
        return s if len(s) >= 3 else None

    def normalize_label(s):
        s = s.lower()
        s = re.sub(r"[^a-z0-9\s]", "", s)
        return re.sub(r"\s+", " ", s).strip()
        
    def is_garbage(s):
        s_norm = normalize_label(s)
        if re.search(r"\b(income\s*tax|govt\s*of\s*india|permanent\s*account|signature|department)\b", s_norm):
            return True
        letters = re.sub(r"[^A-Z]", "", s.upper())
        if len(letters) < 3:
            return True
        return False

    name_found = False
    father_found = False

    father_labels = [r"\bfather", r"\bfathcr", r"\bguarda"]
    name_labels = [r"\bname\b", r"\bnari\b"]

    father_line_idx = -1

    for i, line in enumerate(lines):
        norm = normalize_label(line)
        
        if not father_found and any(re.search(l, norm) for l in father_labels):
            father_line_idx = i
            for j in range(1, 3):
                if i + j < len(lines):
                    cand = lines[i + j]
                    if not is_garbage(cand) and not re.search(r"\d", cand):
                        cleaned = clean_name(cand)
                        if cleaned:
                            result["father_name"] = cleaned
                            father_found = True
                        break
                        
        if not name_found and not any(re.search(l, norm) for l in father_labels):
            if any(re.search(l, norm) for l in name_labels):
                for j in range(1, 3):
                    if i + j < len(lines):
                        cand = lines[i + j]
                        if not is_garbage(cand) and not re.search(r"\d", cand):
                            cleaned = clean_name(cand)
                            if cleaned:
                                result["name"] = cleaned
                                name_found = True
                            break

    # If Name not found by label, look right above the father label
    if not name_found and father_line_idx > 0:
        for j in range(father_line_idx - 1, -1, -1):
            cand = lines[j]
            if not is_garbage(cand) and not re.search(r"\d", cand):
                cleaned = clean_name(cand)
                if cleaned:
                    result["name"] = cleaned
                    name_found = True
                break

    # If still not found, check layout (INCOME TAX DEPARTMENT -> Name -> Father)
    if not name_found or not father_found:
        for i, line in enumerate(lines):
            norm = normalize_label(line)
            if "income tax" in norm or "govt of india" in norm:
                found_names = []
                for j in range(1, 6):
                    if i + j < len(lines):
                        cand = lines[i + j]
                        if not is_garbage(cand) and not re.search(r"\d", cand):
                            cleaned = clean_name(cand)
                            # To be conservative, standard names shouldn't have too many small words
                            if cleaned and len(cleaned.split()) <= 4:
                                found_names.append(cleaned)
                        if len(found_names) == 2:
                            break
                if len(found_names) >= 1 and not name_found:
                    result["name"] = found_names[0]
                if len(found_names) >= 2 and not father_found:
                    result["father_name"] = found_names[1]
                break

    return result


# ============================================================
# API
# ============================================================

@app.get("/health/ocr")
def health_ocr():
    engine = get_ocr_engine()
    status = "healthy"
    ollama_ok = False
    
    if os.environ.get("OCR_ENGINE", "existing").lower() == "glm_ocr":
        if hasattr(engine, "is_available") and engine.is_available():
            ollama_ok = True
        else:
            status = "degraded"
            
    return jsonify({
        "status": status,
        "engine": os.environ.get("OCR_ENGINE", "existing").lower(),
        "model": os.environ.get("GLM_OCR_MODEL", "glm-ocr:latest"),
        "ollama": ollama_ok
    })

@app.post("/ocr/test")
def ocr_test():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "Empty filename"}), 400
    
    try:
        image = Image.open(file.stream)
        
        # Determine engine
        engine = get_ocr_engine()
        
        # Test with generic
        result = engine.process(image, "UNKNOWN", file.filename)
        
        return jsonify({
            "success": True,
            "filename": file.filename,
            "engine": result.get("ocr_engine"),
            "model": result.get("ocr_model"),
            "raw_text": result.get("raw_text"),
            "clean_text": result.get("clean_text"),
            "processing_time": result.get("processing_time")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.get("/")
def home():

    return jsonify({
        "success": True,
        "service": "Local Document OCR API",
        "status": "running"
    })


@app.post("/ocr")
def ocr():

    if "file" not in request.files:

        return jsonify({
            "success": False,
            "error": "No file uploaded"
        }), 400

    file = request.files["file"]

    if not file.filename:

        return jsonify({
            "success": False,
            "error": "Empty filename"
        }), 400

    try:

        image = Image.open(file.stream)

        # Get OCR engine
        engine = get_ocr_engine()
        
        # First, we need to know the document type.
        # But we don't know it yet. We could use existing engine to detect type first,
        # or we could use the new engine and detect from raw text.
        # Wait, if we use GLM-OCR, we want to use specific prompts.
        # Let's run a fast detection using existing Tesseract on a low-res image?
        # Or just use "UNKNOWN" first.
        # Let's run the OCR. The instructions say "if the project determines PAN then use pan.txt".
        # We will use "UNKNOWN" to get a generic read, detect, and if we really wanted to we could re-run.
        # For this implementation, we will just pass "UNKNOWN" to let the adapter decide, or we can use existing app.detect_document.
        # Actually, let's just pass "UNKNOWN" and let detect_document run on the clean_text.
        
        result = engine.process(image, "UNKNOWN", file.filename)
        text = result["clean_text"]

        # Detect document
        document_type = detect_document(text)

        # Extract fields
        if document_type == "PASSPORT_FRONT":
            fields = extract_passport_front(text)
        elif document_type == "PASSPORT_BACK":
            fields = extract_passport_back(text)
        elif document_type == "PAN":
            fields = extract_pan(text)
        else:
            fields = {}
            
        print_debug_info(file.filename, document_type, result, fields)

        return jsonify({
            "success": True,
            "document": {
                "type": document_type
            },
            "fields": fields,
            "raw_text": result["raw_text"],
            "clean_text": text,
            "ocr_metadata": {
                "engine": result["ocr_engine"],
                "model": result["ocr_model"],
                "processing_time": result["processing_time"]
            },
            "filename": file.filename
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# DASHBOARD HELPERS
# ============================================================

def list_image_files():
    """Return sorted image filenames from the local image directory."""

    if not os.path.isdir(IMAGE_DIR):
        return []

    names = [
        name
        for name in os.listdir(IMAGE_DIR)
        if name.lower().endswith(IMAGE_EXTENSIONS)
        and os.path.isfile(os.path.join(IMAGE_DIR, name))
    ]

    return sorted(names)


def extract_fields(text):
    """Dispatch to the existing extraction functions. Read-only."""

    document_type = detect_document(text)

    if document_type == "PASSPORT_FRONT":

        fields = extract_passport_front(text)

    elif document_type == "PASSPORT_BACK":

        fields = extract_passport_back(text)

    elif document_type == "PAN":

        fields = extract_pan(text)

    else:

        fields = {}

    return document_type, fields


# ============================================================
# DASHBOARD API
# ============================================================

@app.get("/api/images")
def api_images():

    images = [
        {
            "filename": name,
            # url_for already percent-encodes the path segment, so spaces
            # in filenames must NOT be quoted again here.
            "url": url_for("serve_image", filename=name),
            "thumbnail_url": url_for("serve_thumbnail", filename=name)
        }
        for name in list_image_files()
    ]

    return jsonify({
        "success": True,
        "count": len(images),
        "images": images
    })


@app.get("/images/<path:filename>")
def serve_image(filename):
    """Serve an image from the configured directory only."""

    return send_from_directory(IMAGE_DIR, filename)


@app.get("/api/thumb/<path:filename>")
def serve_thumbnail(filename):
    """Serve a small in-memory thumbnail. Originals are untouched."""

    if not filename.lower().endswith(IMAGE_EXTENSIONS):

        return jsonify({
            "success": False,
            "error": "Unsupported file type"
        }), 400

    if filename in THUMB_CACHE:

        cached, stamp = THUMB_CACHE[filename]

        if stamp == os.path.getmtime(
            os.path.join(IMAGE_DIR, filename)
        ):

            return cached

    try:

        with Image.open(
            os.path.join(IMAGE_DIR, filename)
        ) as image:

            image = image.convert("RGB")

            image.thumbnail((220, 220))

            buffer = BytesIO()

            image.save(
                buffer,
                format="JPEG",
                quality=80
            )

            payload = buffer.getvalue()

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 404

    THUMB_CACHE[filename] = (
        payload,
        os.path.getmtime(
            os.path.join(IMAGE_DIR, filename)
        )
    )

    return app.response_class(
        payload,
        mimetype="image/jpeg"
    )


@app.post("/api/process")
def api_process():
    """Process every image in the directory in one batch.

    A single failed image never stops the batch.
    """

    payload = request.get_json(silent=True) or {}

    want_stream = bool(payload.get("stream"))
    target_filename = payload.get("filename")

    all_names = list_image_files()
    if target_filename:
        names = [target_filename] if target_filename in all_names else []
    else:
        names = all_names

    if not names:

        if want_stream:

            return app.response_class(
                json.dumps({
                    "type": "end",
                    "total": 0,
                    "processed": 0,
                    "results": []
                }) + "\n",
                mimetype="application/x-ndjson"
            )

        return jsonify({
            "success": True,
            "total": 0,
            "results": []
        })

    def run_batch():

        results = []

        for index, name in enumerate(names, start=1):

            entry = {
                "filename": name,
                "status": "success",
                "document": {"type": "UNKNOWN"},
                "fields": {},
                "raw_text": ""
            }

            try:

                with Image.open(
                    os.path.join(IMAGE_DIR, name)
                ) as image:
                    engine = get_ocr_engine()
                    result = engine.process(image, "UNKNOWN", name)
                    text = result["clean_text"]

                document_type, fields = extract_fields(text)
                
                print_debug_info(name, document_type, result, fields)

                entry["document"] = {
                    "type": document_type
                }

                entry["fields"] = fields
                entry["raw_text"] = result["raw_text"]
                entry["clean_text"] = text
                entry["ocr_metadata"] = {
                    "engine": result["ocr_engine"],
                    "model": result["ocr_model"],
                    "processing_time": result["processing_time"]
                }

            except Exception as e:

                entry["status"] = "error"
                entry["error"] = str(e)

            results.append(entry)

            if want_stream:

                yield json.dumps({
                    "type": "item",
                    "total": len(names),
                    "processed": index,
                    "result": entry
                }) + "\n"

        yield json.dumps({
            "type": "end",
            "total": len(names),
            "processed": len(results),
            "results": results
        }) + "\n"

    if want_stream:

        return app.response_class(
            run_batch(),
            mimetype="application/x-ndjson"
        )

    for line in run_batch():

        pass

    payload = json.loads(line)

    return jsonify({
        "success": True,
        "total": payload["total"],
        "results": payload["results"]
    })


@app.get("/dashboard")
def dashboard():

    return render_template("index.html")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )