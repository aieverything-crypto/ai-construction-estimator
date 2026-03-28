import re


def _parse_scientific_like(text: str):
    text = text.strip().lower()

    sci = re.search(r"(\d+\.?\d*)\s*e\s*([+-]?\d+)", text)
    if sci:
        return float(sci.group(1)) * (10 ** int(sci.group(2)))

    power = re.search(r"(\d+\.?\d*)\s*(?:x|\*|times)?\s*10\^([+-]?\d+)", text)
    if power:
        return float(power.group(1)) * (10 ** int(power.group(2)))

    return None


def parse_budget(text):
    if not text:
        return 0

    text = str(text).lower().replace(",", "").replace("$", "").strip()

    sci_value = _parse_scientific_like(text)
    if sci_value is not None:
        return sci_value

    multiplier = 1
    if "billion" in text or re.search(r"\bb\b", text):
        multiplier = 1_000_000_000
    elif "million" in text or re.search(r"\bm\b", text):
        multiplier = 1_000_000
    elif "thousand" in text or re.search(r"\bk\b", text):
        multiplier = 1_000

    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0

    return float(nums[0]) * multiplier


def parse_size(text):
    if not text:
        return 2000

    text = str(text).lower().replace(",", "").strip()

    sci_value = _parse_scientific_like(text)
    if sci_value is not None:
        return sci_value

    multiplier = 1
    if "billion" in text:
        multiplier = 1_000_000_000
    elif "million" in text:
        multiplier = 1_000_000
    elif "thousand" in text:
        multiplier = 1_000

    text = re.sub(r"\s*by\s*", "x", text)
    text = re.sub(r"\s*x\s*", "x", text)

    # sqm / m² / m2 → sqft
    if "sqm" in text or "m²" in text or "m2" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * multiplier * 10.7639

    text = text.replace("square feet", "")
    text = text.replace("sqft", "")
    text = text.replace("sq ft", "")
    text = text.replace("ft", "")
    text = text.strip()

    if "x" in text:
        parts = text.split("x")
        if len(parts) == 2:
            try:
                return float(parts[0]) * float(parts[1])
            except Exception:
                pass

    nums = re.findall(r"\d+\.?\d*", text)
    if nums:
        return float(nums[0]) * multiplier

    return 2000


def extract_timeline_months(text):
    if not text:
        return None

    text = str(text).lower().strip()

    months = re.search(r"(\d+\.?\d*)\s*month", text)
    if months:
        return float(months.group(1))

    years = re.search(r"(\d+\.?\d*)\s*year", text)
    if years:
        return float(years.group(1)) * 12

    days = re.search(r"(\d+\.?\d*)\s*day", text)
    if days:
        return float(days.group(1)) / 30

    weeks = re.search(r"(\d+\.?\d*)\s*week", text)
    if weeks:
        return float(weeks.group(1)) / 4.345

    return None
