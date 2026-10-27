"""Shewhart X-bar/R monitoring of SPI paste volume per board, Western Electric rules, Cpk per lot.

Phase I limits come from the first (reference) lot; later boards are phase II points. A rule violation is a
statistical signal that the process moved, not a defect finding and not a cause.
"""

from statistics import mean

A2, D3, D4, D2 = 0.373, 0.136, 1.864, 2.847  # Shewhart constants for subgroups of n = 8 pins (one board)
LSL, USL = 0.08, 0.16  # fictional paste-volume spec for the synthetic line, mm3
RULES = {"WE1": "1 point beyond 3 sigma", "WE2": "2 of 3 beyond 2 sigma, same side",
         "WE3": "4 of 5 beyond 1 sigma, same side", "WE4": "8 in a row on one side of the centre line",
         "R": "range outside the R-chart limits"}


def we_rules(z: list[float], i: int) -> list[str]:
    """Western Electric rules that fire at point i, given standardised X-bar values z."""
    hit = []
    if abs(z[i]) > 3:
        hit.append("WE1")
    for rule, k, n, lim in (("WE2", 2, 3, 2), ("WE3", 4, 5, 1)):
        w = z[max(0, i - n + 1):i + 1]
        if len(w) == n and abs(z[i]) > lim and sum(x * z[i] > 0 and abs(x) > lim for x in w) >= k:
            hit.append(rule)
    w = z[max(0, i - 7):i + 1]
    if len(w) == 8 and (all(x > 0 for x in w) or all(x < 0 for x in w)):
        hit.append("WE4")
    return hit


def monitor(spi: list[tuple[dict, str | None]], panel_lot: dict[str, str]) -> dict | None:
    """spi: (SPI record, evidence id or None) pairs. Subgroups are boards in event-time order."""
    groups: dict[tuple, dict] = {}
    for rec, ev in spi:
        g = groups.setdefault((rec["panel_id"], rec["board_id"]), {"t": rec["event_time"], "v": [], "ev": []})
        g["v"].append(rec["volume_mm3"])
        if ev:
            g["ev"].append(ev)
    pts = [{"panel": p, "board": b, "lot": panel_lot.get(p), "t": g["t"], "n": len(g["v"]),
            "xbar": round(mean(g["v"]), 5), "r": round(max(g["v"]) - min(g["v"]), 5), "v": g["v"], "ev": g["ev"]}
           for (p, b), g in sorted(groups.items(), key=lambda kv: (kv[1]["t"], kv[0]))]
    if not pts:
        return None
    ref_lot = pts[0]["lot"]
    ref = [p for p in pts if p["lot"] == ref_lot]
    cl, rbar = mean(p["xbar"] for p in ref), mean(p["r"] for p in ref)
    s = A2 * rbar / 3  # sigma of X-bar
    z = [(p["xbar"] - cl) / s for p in pts]
    for i, p in enumerate(pts):
        p["rules"] = we_rules(z, i) + (["R"] if not D3 * rbar <= p["r"] <= D4 * rbar else [])
        p["phase"] = "I" if p["lot"] == ref_lot else "II"
    lots: dict[str, dict] = {}
    for p in pts:
        lots.setdefault(p["lot"], {"pts": []})["pts"].append(p)
    out = {}
    for lot, v in lots.items():
        mu, sw = mean(x for p in v["pts"] for x in p["v"]), mean(p["r"] for p in v["pts"]) / D2
        alarms = [p for p in v["pts"] if p["rules"] and p["phase"] == "II"]
        out[lot] = {"boards": len(v["pts"]), "mean": round(mu, 5), "cpk": round(min(USL - mu, mu - LSL) / (3 * sw), 3),
                    "alarms": len(alarms), "first_alarm": _point(alarms[0]) if alarms else None,
                    "ev": [e for p in v["pts"] for e in p["ev"]]}
    first = next((p for p in pts if p["rules"] and p["phase"] == "II"), None)
    return {"reference_lot": ref_lot, "n": pts[0]["n"], "spec": [LSL, USL], "rules": RULES,
            "limits": {"cl": round(cl, 5), "ucl": round(cl + A2 * rbar, 5), "lcl": round(cl - A2 * rbar, 5),
                       "rbar": round(rbar, 5), "r_ucl": round(D4 * rbar, 5), "r_lcl": round(D3 * rbar, 5)},
            "reference_ev": [e for p in ref for e in p["ev"]], "lots": out,
            "first_alarm": _point(first) if first else None, "points": [_point(p) for p in pts]}


def _point(p: dict) -> dict:
    return {k: p[k] for k in ("panel", "board", "lot", "t", "xbar", "r", "rules", "phase", "ev")}


def from_items(items: list[dict]) -> dict | None:
    """Monitor a case's current evidence (latest source version per row); None without lots or SPI."""
    from app.ncr import latest_spi_by_board
    panel_lot = {i["key"][0]: i["rec"]["lot_id"] for i in items if i["type"] == "panels" and "lot_id" in i["rec"]}
    if not panel_lot:
        return None
    return monitor([(i["rec"], i["ev"]) for rows in latest_spi_by_board(items).values() for i in rows], panel_lot)


def from_bundle(bundle: dict) -> dict | None:
    """Replay a raw line bundle (no evidence ids yet), as an edge monitor would see the stream."""
    t = {a["entity_type"]: a["records"] for a in bundle["assets"]}
    return monitor([(r, None) for r in t.get("spi_measurements", [])],
                   {r["panel_id"]: r["lot_id"] for r in t.get("panels", []) if "lot_id" in r})
