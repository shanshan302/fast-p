import re

from .collection import CollectionError
from .models import InputRow, ItemResult, PLATFORM_NAMES


BRAND_ALIASES = {
    "walsin": "Walsin/华新科技", "华新科技": "Walsin/华新科技",
    "jxnd": "JXND/嘉兴南电", "嘉兴南电": "JXND/嘉兴南电", "深圳嘉兴南电": "JXND/嘉兴南电",
    "jksemi": "JKSEMI/金开盛", "金开盛": "JKSEMI/金开盛", "深圳金开盛电子": "JKSEMI/金开盛",
    "yfw": "YFW/广东佑风微电子", "佑风微": "YFW/广东佑风微电子", "广东佑风微电子": "YFW/广东佑风微电子",
}

GENERIC_BRAND_PARTS = {
    "广东", "深圳", "江苏", "上海", "北京", "浙江", "苏州", "东莞", "厦门", "香港", "天津", "四川",
    "电子", "股份", "有限", "公司", "微电子", "科技", "集团", "实业", "半导体", "光电", "技术",
    "产业", "能源", "商贸", "贸易", "进出口", "供应", "控股", "企业", "发展", "国际", "制造",
}


def norm(value) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def number(value):
    try:
        return float(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def model_matches(expected: str, actual: str) -> bool:
    left, right = norm(expected), norm(actual)
    return bool(left and right and (left in right or right in left))


def brand_variants(expected: str) -> tuple[str, ...]:
    values = [expected, *str(expected or "").split("/")]
    expected_norm = norm(expected)
    for alias, standard in BRAND_ALIASES.items():
        if norm(standard) == expected_norm or norm(alias) == expected_norm:
            values.extend([alias, standard, *standard.split("/")])
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def brand_matches(actual: str, expected: str) -> bool:
    if not actual or not expected:
        return False
    actual_norm, expected_norm = norm(actual), norm(expected)
    candidates = {norm(value) for value in brand_variants(expected)}
    if any(candidate and candidate in actual_norm for candidate in candidates):
        return True
    return any(
        part not in GENERIC_BRAND_PARTS and part in expected_norm
        for part in re.findall(r"[a-z0-9]{2,}|[一-鿿]{2,}", actual_norm)
    )


def qualifying_tiers(tiers, moq, supply_price):
    if moq is None or supply_price is None:
        return []
    found = []
    for tier in tiers or []:
        quantity = number(tier.get("quantity"))
        price = number(tier.get("unit_price"))
        if quantity is not None and price is not None and quantity >= moq and price > supply_price:
            found.append((quantity, price))
    return found


def platform_candidates(payload, platform):
    result = payload.get("result") if isinstance(payload, dict) else None
    platforms = result.get("platforms", []) if isinstance(result, dict) else []
    return [entry for entry in platforms if entry.get("platformId") == platform]


def find_match(row: InputRow, platforms: list[str], collector, progress=None):
    model_hit = brand_hit = collected = False
    errors, all_tiers = [], []
    for platform in platforms:
        if progress:
            progress({"phase": "collect", "model": row.model, "platform": platform})
        try:
            payload = collector(row.model, platform)
        except CollectionError as exc:
            errors.append(str(exc))
            continue

        matches = []
        results = platform_candidates(payload, platform)
        for platform_result in results:
            if platform_result.get("noData") or platform_result.get("success"):
                collected = True
            elif platform_result.get("error"):
                errors.append(f"{platform}: {platform_result['error']}")
            if not platform_result.get("success") or platform_result.get("noData"):
                continue
            for candidate in platform_result.get("data", []):
                actual_model = candidate.get("part_number", "")
                actual_brand = candidate.get("manufacturer", "")
                if not model_matches(row.model, actual_model):
                    continue
                model_hit = True
                if not brand_matches(actual_brand, row.brand):
                    continue
                brand_hit = True
                tiers = candidate.get("price_tiers", [])
                all_tiers.extend(tiers)
                qualified = qualifying_tiers(tiers, row.moq, row.supply_price)
                if qualified and candidate.get("product_url"):
                    quantity, price = min(qualified, key=lambda value: value[1])
                    matches.append((price, candidate, quantity))
        if matches:
            _, candidate, quantity = min(matches, key=lambda value: value[0])
            price = min(
                qualifying_tiers(candidate.get("price_tiers", []), row.moq, row.supply_price),
                key=lambda value: value[1],
            )[1]
            return ItemResult(
                row_number=row.row_number,
                sku=row.sku,
                model=row.model,
                status="OK",
                reason=f"数量{quantity:g}≥起订{row.moq}，价格{price:g}>供货价{row.supply_price:g}",
                platform=platform,
                platform_name=platform_result.get("platformName") or PLATFORM_NAMES.get(platform, platform),
                url=candidate.get("product_url", ""),
                matched_model=candidate.get("part_number", ""),
                matched_brand=candidate.get("manufacturer", ""),
                quantity=quantity,
                price=price,
            )

    if not collected:
        status, reason = "ERROR", "；".join(errors) or "采集 Worker 没有返回结果"
    elif not model_hit:
        status, reason = "NO_MODEL", "所选平台均未找到该型号"
    elif not brand_hit:
        status, reason = "NO_BRAND", f"找到型号，但未找到厂牌「{row.brand}」"
    elif not all_tiers:
        status, reason = "BRAND_NO_OK", "型号和厂牌匹配，但平台未提供价格梯度"
    else:
        status, reason = "BRAND_NO_OK", "型号和厂牌匹配，但没有数量≥MOQ且价格>供货价的档位"
    return ItemResult(row.row_number, row.sku, row.model, status, reason)
