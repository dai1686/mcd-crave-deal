"""
麦麦心愿单 · mcd-crave-deal
===========================

你说想吃什么，它找出"能把你心愿全包住的最便宜吃法"。

核心思路：
  麦当劳的「套餐」本质上是一组可选槽位（rounds）：主食 / 小食 / 饮料……
  每个槽位有多个可选子项（choices），很多替换是 +¥0。
  所以"想吃 A + B"不一定非得单点两次——
  只要某个套餐的槽位里能选到 A 和 B，走套餐往往更便宜。

  本脚本做的事：
    1. 拉门店实时菜单
    2. 把你的心愿关键词模糊匹配到具体商品
    3. 扫描所有套餐，算出每个套餐能"覆盖"几个心愿（含槽位替换）
    4. 生成若干候选方案（全单点 / 套餐 + 补齐单点），逐个用官方 calculate-price 真实算价
    5. 输出最省方案、省了多少、为什么省

用法:
    export MCD_MCP_TOKEN=xxx
    python crave.py --city 唐山市 --keyword 华北理工大学 --want "吉士蛋麦满分,咖啡"
    python crave.py --store 1980439 --want "麦满分,咖啡" --json

只做只读查询 + 算价，不会下单、不会领券。
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import call_tool  # noqa: E402

# 名称里出现这些词的，视为"套餐/组合"（即内部含多个槽位）
COMBO_HINTS = ("套餐", "组合", "三件套", "双人餐", "多人餐", "全家桶", "超值", "分享", "派对", "桶")


def yuan(cent) -> float:
    """接口价格单位为分，转元。"""
    try:
        return round(int(cent) / 100, 2)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 菜单与套餐

def load_menu(store_code: str, order_type: int, be_type: int) -> dict:
    res = call_tool("query-meals", {
        "storeCode": store_code,
        "orderType": order_type,
        "beType": be_type,
    })
    data = (res.get("structuredContent") or {}).get("data") or {}
    return data.get("meals", {})


def combo_slots(store_code: str, code: str, order_type: int, be_type: int) -> list:
    """拿到一个套餐的所有槽位（rounds）及每个槽位的可选子项。"""
    res = call_tool("query-meal-detail", {
        "storeCode": store_code,
        "orderType": order_type,
        "beType": be_type,
        "code": code,
    })
    data = (res.get("structuredContent") or {}).get("data") or {}
    return data.get("rounds") or []


# ---------------------------------------------------------------- 模糊匹配

def score(name: str, kw: str) -> float:
    """名称与关键词的相关度打分，越高越像。"""
    name, kw = name.strip(), kw.strip()
    if not name or not kw:
        return 0.0
    if name == kw:
        return 100.0
    if kw in name:
        return 80.0 - min(len(name) - len(kw), 30) * 0.5
    if name in kw:
        return 60.0
    return difflib.SequenceMatcher(None, name, kw).ratio() * 45


def match_menu(want: str, menu: dict, top: int = 3) -> list:
    """把一句心愿匹配到菜单里的商品，返回 [(code, name, price, 得分)]。"""
    scored = []
    for code, item in menu.items():
        s = score(item.get("name", ""), want)
        if s >= 30:
            scored.append((code, item.get("name", ""), item.get("currentPrice", "0"), s))
    scored.sort(key=lambda x: (-x[3], float(x[2] or 0)))
    return scored[:top]


# ---------------------------------------------------------------- 方案生成

def build_plans(menu: dict, wishes: list, store_code: str,
                order_type: int, be_type: int, max_combo: int = 8):
    """
    wishes: [{"kw": 原始心愿, ...}]

    返回候选方案列表，每个方案是一个 items 结构 + 人话描述。
    """
    # --- 0) 先把所有套餐的槽位扫一遍，建立「套餐内可选子项」池
    combos = [(c, v) for c, v in menu.items()
              if any(h in v.get("name", "") for h in COMBO_HINTS)]
    rounds_cache, slot_pool = {}, {}
    for code, _item in combos:
        try:
            rounds_cache[code] = combo_slots(store_code, code, order_type, be_type)
        except Exception:
            rounds_cache[code] = []
        for rnd in rounds_cache[code]:
            for ch in rnd.get("choices") or []:
                slot_pool.setdefault(ch.get("code"), ch.get("name", ""))

    # --- 1) 心愿匹配：可单点的（主菜单）+ 只在套餐里出现的（槽位子项）
    def is_combo(name: str) -> bool:
        return any(h in name for h in COMBO_HINTS)

    for w in wishes:
        singles = [(c, v.get("name", ""), v.get("currentPrice", "0"), s)
                   for c, v in menu.items()
                   for s in [score(v.get("name", ""), w["kw"])] if s >= 30 and not is_combo(v.get("name", ""))]
        singles = [x for x in singles if x[0] in menu]
        slot_only = [(c, n, "套餐内", s) for c, n in slot_pool.items()
                     for s in [score(n, w["kw"])] if s >= 35]
        singles.sort(key=lambda x: (-x[3], float(x[2] or 999)))
        slot_only.sort(key=lambda x: -x[3])
        w["cands"] = singles[:3]
        w["slot_cands"] = [(c, n) for c, n, _, _ in slot_only[:3]]

    # --- 2) 基线方案：每个心愿挑最便宜的可单点商品
    base_items, base_desc = [], []
    for w in wishes:
        if not w["cands"]:
            continue
        code, name, price, _ = min(w["cands"], key=lambda c: float(c[2] or 999))
        base_items.append({"productCode": code, "quantity": 1})
        base_desc.append(f"{name} ¥{price}")
    plans = [{
        "name": "全单点",
        "items": base_items,
        "desc": " + ".join(base_desc) or "（无可匹配商品）",
        "covered": len(base_items),
    }]

    # --- 3) 套餐方案：看每个套餐的槽位能覆盖几个心愿
    for w in wishes:
        w["_codes"] = {c[0] for c in w["cands"]} | {c for c, _ in w["slot_cands"]}
        w["_names"] = {c[1] for c in w["cands"]} | {n for _, n in w["slot_cands"]}

    ranked = []
    for code, item in combos:
        rounds = rounds_cache.get(code) or []
        if not rounds:
            continue
        picks, covered_idx = [], set()
        for rnd in rounds:
            choices = rnd.get("choices") or []
            best, best_s, best_idx = None, 0.0, None
            for ch in choices:
                cname, ccode = ch.get("name", ""), ch.get("code")
                local_s, local_idx = 0.0, None
                for i, w in enumerate(wishes):
                    sw = score(cname, w["kw"])
                    if ccode in w["_codes"] or cname in w["_names"]:
                        sw = max(sw, 92)
                    if sw > local_s:
                        local_s, local_idx = sw, i
                if local_s > best_s:
                    best, best_s, best_idx = ch, local_s, local_idx
            if best is None:
                continue
            hit = best_s >= 30
            if hit and best_idx is not None:
                covered_idx.add(best_idx)
            elif not hit:
                best = next((c for c in choices if c.get("isDefault") == 1), best)
            picks.append({
                "round": str(rnd.get("id")),
                "roundName": rnd.get("name", ""),
                "code": best.get("code"),
                "name": best.get("name", ""),
                "hit": hit,
            })
        if covered_idx:
            ranked.append((len(covered_idx), code, item.get("name", ""),
                           item.get("currentPrice", "0"), picks, covered_idx))
    ranked.sort(key=lambda x: (-x[0], float(x[3] or 999)))

    for hit, code, name, price, picks, covered_idx in ranked[:max_combo]:
        still = []
        for i, w in enumerate(wishes):
            if i in covered_idx:
                continue
            if w["cands"]:
                c = min(w["cands"], key=lambda x: float(x[2] or 999))
                still.append({"productCode": c[0], "quantity": 1, "_name": c[1], "_price": c[2]})
            elif w["slot_cands"]:
                still.append({"_name": f"{w['slot_cands'][0][1]}（仅套餐内）", "_price": "—", "_skip": True})
        items = [{
            "productCode": code,
            "quantity": 1,
            "roundList": [
                {"round": p["round"], "comboItemList": [{"code": p["code"], "quantity": 1}]}
                for p in picks
            ],
        }] + [{k: v for k, v in s.items() if not k.startswith("_")} for s in still if not s.get("_skip")]

        parts = [f"{name} ¥{price}（" + "、".join(p["name"] for p in picks) + "）"]
        parts += [f"{s['_name']} ¥{s['_price']}" for s in still]
        plans.append({
            "name": f"套餐流：{name}",
            "items": items,
            "desc": " + ".join(parts),
            "covered": hit + len([s for s in still if not s.get("_skip")]),
            "_hit": hit,
        })
    return plans


def price_plan(plan: dict, store_code: str, order_type: int, be_type: int) -> dict:
    try:
        res = call_tool("calculate-price", {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "items": plan["items"],
        })
        data = (res.get("structuredContent") or {}).get("data") or {}
        plan["price"] = yuan(data.get("price"))
        plan["original"] = yuan(data.get("originalPrice"))
        plan["discount"] = yuan(data.get("discount"))
        # 返回 0 元通常意味着该组合当前不可售，视为无效方案
        plan["ok"] = plan["price"] > 0
        if not plan["ok"]:
            plan["err"] = "该组合当前不可售"
            plan["price"] = None
    except Exception as exc:  # 某个组合不合法就跳过
        plan["ok"] = False
        plan["err"] = str(exc)[:120]
        plan["price"] = None
    return plan


# ---------------------------------------------------------------- 主流程

def find_store(city: str, keyword: str, be_type: int) -> list:
    res = call_tool("query-nearby-stores", {
        "beType": be_type, "searchType": 2, "city": city, "keyword": keyword,
    })
    return (res.get("structuredContent") or {}).get("data") or []


def run(wants: list, store_code: str = None, city: str = None, keyword: str = None,
        order_type: int = 1, be_type: int = 1, max_combo: int = 8, as_json: bool = False):
    if not store_code:
        stores = find_store(city, keyword, be_type)
        if not stores:
            raise SystemExit("没找到门店，换个关键词试试（如：华北理工大学 / 曹妃甸）")
        store_code = stores[0]["storeCode"]
        picked_store = stores[0]
    else:
        picked_store = {"storeCode": store_code, "storeName": store_code}

    menu = load_menu(store_code, order_type, be_type)
    wishes = [{"kw": w} for w in wants]
    plans = build_plans(menu, wishes, store_code, order_type, be_type, max_combo)
    for p in plans:
        price_plan(p, store_code, order_type, be_type)

    ok = [p for p in plans if p.get("ok") and p["price"] is not None]
    ok.sort(key=lambda p: p["price"])
    best = ok[0] if ok else None
    baseline = next((p for p in plans if p["name"] == "全单点"), None)

    result = {
        "store": picked_store,
        "wishes": [{"kw": w["kw"], "matched": [{"code": c[0], "name": c[1], "price": c[2]}
                                               for c in w["cands"]]} for w in wishes],
        "plans": [{k: v for k, v in p.items() if not k.startswith("_")} for p in ok],
        "best": {k: v for k, v in best.items() if not k.startswith("_")} if best else None,
        "baseline": {k: v for k, v in baseline.items() if not k.startswith("_")} if baseline else None,
    }
    if best and baseline and baseline.get("price"):
        result["saved"] = round(baseline["price"] - best["price"], 2)
        result["saved_ratio"] = round(result["saved"] / baseline["price"] * 100, 1)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    print(f"\n🍔 门店：{picked_store.get('storeName', store_code)}（{store_code}）")
    print("🎯 你的心愿：")
    for w in wishes:
        names = " / ".join(f"{c[1]} ¥{c[2]}" for c in w["cands"]) or "没匹配到，换个说法？"
        print(f"   · {w['kw']} → {names}")
    print("\n💰 比价结果（已用官方接口真实算价）：")
    for p in ok:
        tag = "  ✅ 最省" if p is best else ""
        print(f"   ¥{p['price']:<6} {p['name']}{tag}")
        print(f"          {p['desc']}")
    if result.get("saved") and result["saved"] > 0:
        print(f"\n🤑 比全单点省 ¥{result['saved']}（{result['saved_ratio']}%）")
    elif result.get("saved") is not None:
        print("\n这次单点就是最省的，套餐没占到便宜。")
    return result


def main():
    ap = argparse.ArgumentParser(description="麦麦心愿单：想吃啥，帮你找最便宜的吃法")
    ap.add_argument("--want", required=True, help='想吃的东西，逗号分隔，如 "吉士蛋麦满分,咖啡"')
    ap.add_argument("--store", help="门店编码，不给就按位置搜")
    ap.add_argument("--city", default="唐山市")
    ap.add_argument("--keyword", default="华北理工大学")
    ap.add_argument("--order-type", type=int, default=1, help="1-到店 2-外送")
    ap.add_argument("--be-type", type=int, default=1, help="1-到店自取 5-得来速")
    ap.add_argument("--max-combo", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    wants = [w.strip() for w in a.want.replace("，", ",").split(",") if w.strip()]
    run(wants, a.store, a.city, a.keyword, a.order_type, a.be_type, a.max_combo, a.json)


if __name__ == "__main__":
    main()
