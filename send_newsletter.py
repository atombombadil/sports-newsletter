#!/usr/bin/env python3
"""Daily sports scores newsletter — NHL, MLB, NFL via ESPN public API."""

import json
import os
import smtplib
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:
    EASTERN = None

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

SPORTS = {
    "nhl": {"path": "hockey/nhl",    "label": "NHL Hockey",    "color": "#000000", "icon": "🏒", "months": {10,11,12,1,2,3,4,5,6}},
    "mlb": {"path": "baseball/mlb",  "label": "MLB Baseball",  "color": "#003087", "icon": "⚾", "months": {3,4,5,6,7,8,9,10}},
    "nfl": {"path": "football/nfl",  "label": "NFL Football",  "color": "#013369", "icon": "🏈", "months": {9,10,11,12,1,2}},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(val) -> int:
    try: return int(float(str(val)))
    except: return 0

def _now_et() -> datetime:
    if EASTERN:
        return datetime.now(EASTERN)
    off = -4 if 3 <= datetime.now(timezone.utc).month <= 10 else -5
    return datetime.now(timezone.utc) + timedelta(hours=off)

def active_sports(month: int) -> list:
    return [k for k, v in SPORTS.items() if month in v["months"]]

def yesterday_et() -> tuple:
    d = _now_et() - timedelta(days=1)
    return d.strftime("%Y%m%d"), d.strftime("%B %d, %Y")

def tomorrow_et() -> tuple:
    d = _now_et() + timedelta(days=1)
    return d.strftime("%Y%m%d"), d.strftime("%B %d, %Y")

def fmt_et(iso: str) -> str:
    if not iso: return "TBD"
    try:
        s = iso.rstrip("Z").replace("T", " ").split(".")[0].strip()
        if len(s) == 16: s += ":00"
        utc = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if EASTERN:
            dt = utc.astimezone(EASTERN)
            tz = dt.strftime("%Z")
        else:
            off = -4 if 3 <= utc.month <= 10 else -5
            dt = utc + timedelta(hours=off)
            tz = "EDT" if off == -4 else "EST"
        h = dt.hour % 12 or 12
        return f"{h}:{dt.strftime('%M')} {'AM' if dt.hour < 12 else 'PM'} {tz}"
    except: return "TBD"

# ── ESPN API ──────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  fetch error (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return None

def fetch_scoreboard(path: str, date_str: str):
    return _get(f"{ESPN_BASE}/{path}/scoreboard?dates={date_str}")

def fetch_summary(path: str, eid: str):
    return _get(f"{ESPN_BASE}/{path}/summary?event={eid}")

# ── Scoreboard parser ─────────────────────────────────────────────────────────

def parse_games(data) -> list:
    if not data or "events" not in data: return []
    games = []
    for ev in data["events"]:
        comp = ev.get("competitions", [{}])[0]
        comps = comp.get("competitors", [])
        st_type = comp.get("status", {}).get("type", {})
        home = next((c for c in comps if c.get("homeAway") == "home"), None)
        away = next((c for c in comps if c.get("homeAway") == "away"), None)
        if not home or not away: continue
        hs, as_ = home.get("score", ""), away.get("score", "")
        completed = st_type.get("completed", False)
        winner = None
        if completed and hs and as_:
            try: winner = "home" if int(float(hs)) > int(float(as_)) else "away"
            except: pass
        games.append({
            "event_id": ev.get("id", ""),
            "home_team":  home.get("team", {}).get("displayName", "TBD"),
            "home_abbr":  home.get("team", {}).get("abbreviation", ""),
            "home_score": hs,
            "away_team":  away.get("team", {}).get("displayName", "TBD"),
            "away_abbr":  away.get("team", {}).get("abbreviation", ""),
            "away_score": as_,
            "status":     st_type.get("shortDetail", ""),
            "completed":  completed,
            "winner":     winner,
            "start_time": comp.get("date", ""),
        })
    return games

# ── Detail parsers ────────────────────────────────────────────────────────────

def _hdr_linescores(summary: dict) -> tuple:
    """Return (home_list, away_list) of linescore dicts from header."""
    comp = summary.get("header", {}).get("competitions", [{}])[0]
    comps = comp.get("competitors", [])
    home = next((c for c in comps if c.get("homeAway") == "home"), {})
    away = next((c for c in comps if c.get("homeAway") == "away"), {})
    return home.get("linescores", []), away.get("linescores", [])

def parse_nhl_detail(summary) -> dict:
    if not summary: return {}
    d = {}

    # Period scores + game type
    try:
        home_ls, away_ls = _hdr_linescores(summary)
        comp = summary["header"]["competitions"][0]
        sd = comp.get("status", {}).get("type", {}).get("shortDetail", "")
        n = max(len(home_ls), len(away_ls))
        labels = []
        for i in range(n):
            if i < 3: labels.append(f"P{i+1}")
            elif i == 3: labels.append("SO" if "SO" in sd.upper() else "OT")
            else: labels.append(f"OT{i-2}")
        d["periods"] = {
            "labels": labels,
            "home": [ls.get("displayValue", "") for ls in home_ls],
            "away": [ls.get("displayValue", "") for ls in away_ls],
        }
        if "SO" in sd.upper(): d["game_type"] = "SO"
        elif "OT" in sd.upper(): d["game_type"] = "OT"
    except: pass

    # Shots on goal (team level)
    try:
        ts = {}
        for t in summary.get("boxscore", {}).get("teams", []):
            ha = t.get("homeAway", "")
            ts[ha] = {s["name"]: s.get("displayValue", "") for s in t.get("statistics", []) if "name" in s}
        d["team_stats"] = ts
    except: pass

    # Team ID → abbreviation map (for tagging scoring plays)
    try:
        comp = summary["header"]["competitions"][0]
        d["team_id_map"] = {
            cx.get("team", {}).get("id", ""): cx.get("team", {}).get("abbreviation", "")
            for cx in comp.get("competitors", [])
        }
    except: pass

    # Goalies (stat group whose keys include 'saves')
    try:
        goalies = []
        for bp in summary.get("boxscore", {}).get("players", []):
            team_abbr = bp.get("team", {}).get("abbreviation", "")
            for grp in bp.get("statistics", []):
                keys = grp.get("keys", [])
                if "saves" not in keys: continue
                sv_i  = keys.index("saves")
                sa_i  = keys.index("shotsAgainst") if "shotsAgainst" in keys else -1
                for ath in grp.get("athletes", []):
                    stats = ath.get("stats", [])
                    sv = stats[sv_i] if sv_i < len(stats) else ""
                    sa = stats[sa_i] if sa_i >= 0 and sa_i < len(stats) else ""
                    if sv:
                        goalies.append({
                            "name": ath.get("athlete", {}).get("displayName", ""),
                            "team": team_abbr, "sv": sv, "sa": sa,
                        })
        if goalies: d["goalies"] = goalies
    except: pass

    # Scoring plays (from plays[] array, not the missing scoringPlays key)
    try:
        id_map = d.get("team_id_map", {})
        plays = []
        for p in summary.get("plays", []):
            if not p.get("scoringPlay"): continue
            p_num = p.get("period", {}).get("number", 1)
            p_label = f"P{p_num}" if p_num <= 3 else ("OT" if p_num == 4 else f"OT{p_num-3}")
            clock = p.get("clock", {}).get("displayValue", "")
            team_id = p.get("team", {}).get("id", "") if isinstance(p.get("team"), dict) else ""
            scorer, assists = "", []
            for part in p.get("participants", []):
                if not isinstance(part, dict): continue
                name = part.get("athlete", {}).get("displayName", "")
                ptype = part.get("type", "")
                if ptype == "scorer": scorer = name
                elif ptype == "assister": assists.append(name)
            if not scorer:
                txt = p.get("text", "")
                scorer = txt.split(" Goal")[0] if " Goal" in txt else txt[:40]
            plays.append({
                "period": p_label, "clock": clock,
                "team": id_map.get(team_id, ""),
                "scorer": scorer, "assists": assists,
                "home_score": p.get("homeScore", ""),
                "away_score": p.get("awayScore", ""),
            })
        if plays: d["scoring_plays"] = plays
    except: pass

    return d


def parse_mlb_detail(summary) -> dict:
    if not summary: return {}
    d = {}

    # Inning line score + R/H/E from linescore objects
    try:
        home_ls, away_ls = _hdr_linescores(summary)
        n = max(len(home_ls), len(away_ls), 9)
        while len(home_ls) < n: home_ls.append({})
        while len(away_ls) < n: away_ls.append({})
        d["innings"] = {
            "labels": [str(i + 1) for i in range(n)],
            "home": [ls.get("displayValue", "") for ls in home_ls],
            "away": [ls.get("displayValue", "") for ls in away_ls],
        }
        d["rhe"] = {
            "home": {
                "R": str(sum(_int(ls.get("displayValue", 0)) for ls in home_ls)),
                "H": str(sum(ls.get("hits",   0) for ls in home_ls if ls)),
                "E": str(sum(ls.get("errors", 0) for ls in home_ls if ls)),
            },
            "away": {
                "R": str(sum(_int(ls.get("displayValue", 0)) for ls in away_ls)),
                "H": str(sum(ls.get("hits",   0) for ls in away_ls if ls)),
                "E": str(sum(ls.get("errors", 0) for ls in away_ls if ls)),
            },
        }
    except: pass

    # Pitchers (group with 'IP' in names/keys) and batters
    try:
        starters, top_batters = [], []
        for bp in summary.get("boxscore", {}).get("players", []):
            team_abbr = bp.get("team", {}).get("abbreviation", "")
            for grp in bp.get("statistics", []):
                ref = grp.get("names") or grp.get("keys") or []
                athletes = grp.get("athletes", [])

                if any(k in ref for k in ("IP", "inningsPitched")):
                    def idx(keys_list):
                        for needle in keys_list:
                            if needle in ref: return ref.index(needle)
                        return -1
                    ip_i  = idx(["IP", "inningsPitched"])
                    h_i   = idx(["H", "hits"])
                    er_i  = idx(["ER", "earnedRuns"])
                    bb_i  = idx(["BB", "baseOnBalls", "walks"])
                    k_i   = idx(["K", "SO", "strikeouts"])
                    if athletes:
                        sv = athletes[0].get("stats", [])
                        ip = sv[ip_i] if ip_i >= 0 and ip_i < len(sv) else ""
                        if ip:
                            starters.append({
                                "name": athletes[0].get("athlete", {}).get("displayName", ""),
                                "team": team_abbr, "ip": ip,
                                "h":  sv[h_i]  if h_i  >= 0 and h_i  < len(sv) else "",
                                "er": sv[er_i] if er_i >= 0 and er_i < len(sv) else "",
                                "bb": sv[bb_i] if bb_i >= 0 and bb_i < len(sv) else "",
                                "k":  sv[k_i]  if k_i  >= 0 and k_i  < len(sv) else "",
                            })

                elif any(k in ref for k in ("H-AB", "AB", "atBats")):
                    def idx2(keys_list):
                        for needle in keys_list:
                            if needle in ref: return ref.index(needle)
                        return -1
                    hr_i  = idx2(["HR", "homeRuns"])
                    rbi_i = idx2(["RBI", "RBIs"])
                    h_i   = idx2(["H", "hits"])
                    ab_i  = idx2(["AB", "atBats"])
                    for ath in athletes:
                        sv = ath.get("stats", [])
                        hr  = _int(sv[hr_i])  if hr_i  >= 0 and hr_i  < len(sv) else 0
                        rbi = _int(sv[rbi_i]) if rbi_i >= 0 and rbi_i < len(sv) else 0
                        if hr > 0 or rbi >= 2:
                            h_v  = sv[h_i]  if h_i  >= 0 and h_i  < len(sv) else ""
                            ab_v = sv[ab_i] if ab_i >= 0 and ab_i < len(sv) else ""
                            parts = []
                            if hr > 0:  parts.append(f"{hr} HR")
                            if rbi > 0: parts.append(f"{rbi} RBI")
                            if h_v and ab_v: parts.append(f"{h_v}-for-{ab_v}")
                            if parts:
                                top_batters.append({
                                    "name": ath.get("athlete", {}).get("displayName", ""),
                                    "team": team_abbr,
                                    "line": ", ".join(parts),
                                })
        if starters:    d["starters"]    = starters
        if top_batters: d["top_batters"] = top_batters
    except: pass

    return d


def parse_nfl_detail(summary) -> dict:
    if not summary: return {}
    d = {}

    # Quarter scores
    try:
        home_ls, away_ls = _hdr_linescores(summary)
        n = max(len(home_ls), len(away_ls))
        d["quarters"] = {
            "labels": [f"Q{i+1}" if i < 4 else "OT" for i in range(n)],
            "home": [ls.get("displayValue", "") for ls in home_ls],
            "away": [ls.get("displayValue", "") for ls in away_ls],
        }
        if n > 4: d["game_type"] = "OT"
    except: pass

    # Passing / rushing leaders from boxscore players
    try:
        pass_leader, rush_leader = None, None
        best_py, best_ry = -1, -1
        for bp in summary.get("boxscore", {}).get("players", []):
            team = bp.get("team", {}).get("abbreviation", "")
            for grp in bp.get("statistics", []):
                keys = grp.get("keys", [])
                athletes = grp.get("athletes", [])

                if "completions/passingAttempts" in keys:
                    py_i = keys.index("passingYards")              if "passingYards"              in keys else -1
                    td_i = keys.index("passingTouchdowns")         if "passingTouchdowns"         in keys else -1
                    ca_i = keys.index("completions/passingAttempts") if "completions/passingAttempts" in keys else -1
                    for ath in athletes:
                        sv = ath.get("stats", [])
                        py = _int(sv[py_i]) if py_i >= 0 and py_i < len(sv) else 0
                        if py > best_py:
                            best_py = py
                            ca = sv[ca_i] if ca_i >= 0 and ca_i < len(sv) else ""
                            td = sv[td_i] if td_i >= 0 and td_i < len(sv) else ""
                            pass_leader = {
                                "name": ath.get("athlete", {}).get("displayName", ""),
                                "team": team,
                                "display": f"{ca}, {py} YDS, {td} TD",
                            }

                elif "rushingAttempts" in keys:
                    ry_i = keys.index("rushingYards")        if "rushingYards"        in keys else -1
                    rt_i = keys.index("rushingTouchdowns")   if "rushingTouchdowns"   in keys else -1
                    ra_i = keys.index("rushingAttempts")     if "rushingAttempts"     in keys else -1
                    for ath in athletes:
                        sv = ath.get("stats", [])
                        ry = _int(sv[ry_i]) if ry_i >= 0 and ry_i < len(sv) else 0
                        if ry > best_ry:
                            best_ry = ry
                            ra = sv[ra_i] if ra_i >= 0 and ra_i < len(sv) else ""
                            td = sv[rt_i] if rt_i >= 0 and rt_i < len(sv) else ""
                            rush_leader = {
                                "name": ath.get("athlete", {}).get("displayName", ""),
                                "team": team,
                                "display": f"{ra} CAR, {ry} YDS, {td} TD",
                            }
        leaders = {}
        if pass_leader: leaders["passing"] = pass_leader
        if rush_leader: leaders["rushing"] = rush_leader
        if leaders: d["leaders"] = leaders
    except: pass

    # Turnovers
    try:
        to = {}
        for t in summary.get("boxscore", {}).get("teams", []):
            ha = t.get("homeAway", "")
            team = t.get("team", {}).get("abbreviation", "")
            for s in t.get("statistics", []):
                if s.get("name") == "turnovers":
                    to[ha] = {"team": team, "count": s.get("displayValue", "0")}
        if to: d["turnovers"] = to
    except: pass

    return d

# ── Notable detection ─────────────────────────────────────────────────────────

def detect_notables(sport_key: str, games: list, details: dict) -> list:
    notables = []
    for g in games:
        if not g["completed"]: continue
        det = details.get(g["event_id"], {})
        hs, as_ = _int(g["home_score"]), _int(g["away_score"])
        margin = abs(hs - as_)
        winner = g["home_team"] if hs > as_ else g["away_team"]
        loser  = g["away_team"] if hs > as_ else g["home_team"]
        score  = f"{max(hs, as_)}–{min(hs, as_)}"

        if sport_key == "nhl":
            if hs == 0 or as_ == 0:
                notables.append(f"🥅 <b>Shutout:</b> {winner} shut out {loser} ({score})")
            gt = det.get("game_type", "")
            if gt == "SO":
                notables.append(f"🔫 <b>Shootout:</b> {winner} def. {loser} in a shootout")
            elif gt == "OT":
                notables.append(f"⏱ <b>Overtime:</b> {winner} def. {loser} in OT ({score})")
            if margin >= 4:
                notables.append(f"💥 <b>Blowout:</b> {winner} {score} {loser}")

        elif sport_key == "mlb":
            rhe = det.get("rhe", {})
            loser_ha = "away" if hs > as_ else "home"
            try:
                if _int(rhe.get(loser_ha, {}).get("H", "1")) == 0:
                    notables.append(f"🚫 <b>No-Hitter:</b> {winner} held {loser} hitless ({score})")
            except: pass
            if margin >= 6:
                notables.append(f"💥 <b>Blowout:</b> {winner} {score} {loser}")

        elif sport_key == "nfl":
            if det.get("game_type") == "OT":
                notables.append(f"⏱ <b>Overtime:</b> {winner} def. {loser} in OT ({score})")
            if margin >= 21:
                notables.append(f"💥 <b>Blowout:</b> {winner} {score} {loser}")

    return notables

# ── HTML helpers ──────────────────────────────────────────────────────────────

def _lbl(text: str) -> str:
    return (f'<div style="font-size:10px;font-weight:700;letter-spacing:0.8px;'
            f'color:#999;text-transform:uppercase;margin:10px 0 4px;">{text}</div>')

def _score_table(away_abbr, home_abbr, labels, away_vals, home_vals,
                 extra_labels=None, extra_away=None, extra_home=None) -> str:
    TH  = 'style="padding:3px 5px;text-align:center;font-size:11px;font-weight:600;color:#888;border-bottom:1px solid #e8e8e8;"'
    THX = 'style="padding:3px 5px;text-align:center;font-size:11px;font-weight:700;color:#555;border-bottom:1px solid #e8e8e8;border-left:2px solid #ddd;"'
    TD  = 'style="padding:3px 5px;text-align:center;font-size:12px;color:#444;"'
    TDX = 'style="padding:3px 5px;text-align:center;font-size:12px;font-weight:700;color:#1a1a1a;border-left:2px solid #ddd;"'
    TDN = 'style="padding:3px 8px 3px 0;font-size:12px;font-weight:600;color:#555;white-space:nowrap;"'

    heads = "".join(f"<th {TH}>{l}</th>" for l in labels)
    if extra_labels:
        heads += "".join(f"<th {THX}>{l}</th>" for l in extra_labels)
    else:
        heads += f"<th {THX}>T</th>"

    def row(abbr, vals, extras):
        cells = "".join(f"<td {TD}>{v if v != '' else '–'}</td>" for v in vals)
        if extras:
            xc = "".join(f"<td {TDX}>{v}</td>" for v in extras)
        else:
            xc = f"<td {TDX}>{sum(_int(v) for v in vals)}</td>"
        return f"<tr><td {TDN}>{abbr}</td>{cells}{xc}</tr>"

    return (
        '<div style="overflow-x:auto;margin-bottom:10px;">'
        '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        f'<thead><tr><th style="padding:3px 8px 3px 0;"></th>{heads}</tr></thead>'
        '<tbody>'
        f'{row(away_abbr, away_vals, extra_away)}'
        f'{row(home_abbr, home_vals, extra_home)}'
        '</tbody></table></div>'
    )

def _detail_box(content: str) -> str:
    return (f'<div style="background:#f8f9fa;padding:12px 16px 8px;'
            f'border-top:1px dashed #e0e0e0;margin-top:6px;">{content}</div>')

# ── Sport-specific detail HTML ────────────────────────────────────────────────

def _nhl_detail_html(game: dict, det: dict) -> str:
    if not det: return ""
    parts = []

    pd = det.get("periods")
    if pd:
        parts.append(_score_table(game["away_abbr"], game["home_abbr"],
                                  pd["labels"], pd["away"], pd["home"]))

    ts = det.get("team_stats", {})
    a_shots = ts.get("away", {}).get("shotsTotal", "")
    h_shots = ts.get("home", {}).get("shotsTotal", "")
    if a_shots or h_shots:
        parts.append(_lbl("Shots on Goal"))
        parts.append(
            f'<div style="font-size:12px;color:#555;">'
            f'{game["away_abbr"]} <b style="color:#1a1a1a;">{a_shots}</b>'
            f'&nbsp;&nbsp;&nbsp;{game["home_abbr"]} <b style="color:#1a1a1a;">{h_shots}</b>'
            f'</div>'
        )

    goalies = det.get("goalies", [])
    if goalies:
        parts.append(_lbl("Goalies"))
        for gl in goalies:
            sa = f" / {gl['sa']} SA" if gl.get("sa") else ""
            parts.append(
                f'<div style="font-size:12px;color:#555;padding:1px 0;">'
                f'<b style="color:#1a1a1a;">{gl["name"]}</b> ({gl["team"]}): {gl["sv"]} SV{sa}'
                f'</div>'
            )

    plays = det.get("scoring_plays", [])
    if plays:
        parts.append(_lbl("Goals"))
        for p in plays:
            ast = ""
            if p.get("assists"):
                ast = f' <span style="font-size:11px;color:#aaa;">({", ".join(p["assists"])})</span>'
            team = f'<b style="color:#1a1a1a;">{p["team"]}</b> ' if p.get("team") else ""
            sc = f'{p["away_score"]}–{p["home_score"]}'
            parts.append(
                '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
                '<tr>'
                f'<td style="font-size:12px;color:#555;padding:2px 0;">'
                f'<span style="color:#bbb;font-size:11px;">{p["period"]} {p["clock"]}</span>'
                f' {team}{p["scorer"]}{ast}</td>'
                f'<td style="font-size:12px;font-weight:700;color:#1a1a1a;'
                f'text-align:right;white-space:nowrap;">{sc}</td>'
                '</tr></table>'
            )

    return _detail_box("".join(parts)) if parts else ""


def _mlb_detail_html(game: dict, det: dict) -> str:
    if not det: return ""
    parts = []

    inn = det.get("innings")
    rhe = det.get("rhe", {})
    if inn:
        ar, hr = rhe.get("away", {}), rhe.get("home", {})
        parts.append(_score_table(
            game["away_abbr"], game["home_abbr"],
            inn["labels"], inn["away"], inn["home"],
            extra_labels=["R", "H", "E"],
            extra_away=[ar.get("R",""), ar.get("H",""), ar.get("E","")],
            extra_home=[hr.get("R",""), hr.get("H",""), hr.get("E","")],
        ))

    starters = det.get("starters", [])
    if starters:
        parts.append(_lbl("Starting Pitchers"))
        for sp in starters:
            line = f'{sp["ip"]} IP, {sp["h"]} H, {sp["er"]} ER, {sp["bb"]} BB, {sp["k"]} K'
            parts.append(
                f'<div style="font-size:12px;color:#555;padding:1px 0;">'
                f'<b style="color:#1a1a1a;">{sp["name"]}</b> ({sp["team"]}): {line}</div>'
            )

    batters = det.get("top_batters", [])
    if batters:
        parts.append(_lbl("Top Performers"))
        for b in batters:
            parts.append(
                f'<div style="font-size:12px;color:#555;padding:1px 0;">'
                f'<b style="color:#1a1a1a;">{b["name"]}</b> ({b["team"]}): {b["line"]}</div>'
            )

    return _detail_box("".join(parts)) if parts else ""


def _nfl_detail_html(game: dict, det: dict) -> str:
    if not det: return ""
    parts = []

    qtr = det.get("quarters")
    if qtr:
        parts.append(_score_table(game["away_abbr"], game["home_abbr"],
                                  qtr["labels"], qtr["away"], qtr["home"]))

    leaders = det.get("leaders", {})
    passing = leaders.get("passing")
    rushing = leaders.get("rushing")
    if passing or rushing:
        parts.append(_lbl("Statistical Leaders"))
    if passing:
        parts.append(
            f'<div style="font-size:12px;color:#555;padding:1px 0;">'
            f'<span style="font-size:11px;color:#bbb;">PASS</span> '
            f'<b style="color:#1a1a1a;">{passing["name"]}</b> ({passing["team"]}): {passing["display"]}</div>'
        )
    if rushing:
        parts.append(
            f'<div style="font-size:12px;color:#555;padding:1px 0;">'
            f'<span style="font-size:11px;color:#bbb;">RUSH</span> '
            f'<b style="color:#1a1a1a;">{rushing["name"]}</b> ({rushing["team"]}): {rushing["display"]}</div>'
        )

    to = det.get("turnovers", {})
    ato, hto = to.get("away", {}), to.get("home", {})
    if ato or hto:
        parts.append(_lbl("Turnovers"))
        parts.append(
            f'<div style="font-size:12px;color:#555;">'
            f'{ato.get("team", game["away_abbr"])} <b style="color:#1a1a1a;">{ato.get("count","0")}</b>'
            f'&nbsp;&nbsp;&nbsp;'
            f'{hto.get("team", game["home_abbr"])} <b style="color:#1a1a1a;">{hto.get("count","0")}</b>'
            f'</div>'
        )

    return _detail_box("".join(parts)) if parts else ""


DETAIL_FN = {"nhl": _nhl_detail_html, "mlb": _mlb_detail_html, "nfl": _nfl_detail_html}

# ── Section builders ──────────────────────────────────────────────────────────

def _game_row(sport_key: str, game: dict, det: dict) -> str:
    def w(side): return "font-weight:700;" if game["winner"] == side else "font-weight:400;"
    status_color = "#27ae60" if game["completed"] else "#e67e22"
    detail_html = DETAIL_FN.get(sport_key, lambda g, d: "")(game, det)
    return (
        '<tr><td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr>'
        f'<td style="font-size:14px;{w("away")}color:#1a1a1a;padding-bottom:4px;">{game["away_team"]}</td>'
        f'<td style="font-size:20px;{w("away")}color:#1a1a1a;text-align:right;padding-bottom:4px;min-width:36px;">{game["away_score"]}</td>'
        '</tr><tr>'
        f'<td style="font-size:14px;{w("home")}color:#1a1a1a;">'
        f'{game["home_team"]} <span style="font-size:11px;color:#ccc;font-weight:400;">HOME</span></td>'
        f'<td style="font-size:20px;{w("home")}color:#1a1a1a;text-align:right;min-width:36px;">{game["home_score"]}</td>'
        '</tr></table>'
        f'<div style="margin-top:5px;">'
        f'<span style="font-size:11px;font-weight:600;color:{status_color};'
        f'text-transform:uppercase;letter-spacing:0.4px;">{game["status"]}</span></div>'
        f'{detail_html}'
        '</td></tr>'
    )


def _sport_section(sport_key: str, games: list, details: dict, date_display: str) -> str:
    sport = SPORTS[sport_key]
    completed = [g for g in games if g["completed"]]
    if completed:
        rows = "\n".join(_game_row(sport_key, g, details.get(g["event_id"], {})) for g in completed)
        count = f"{len(completed)} game{'s' if len(completed) != 1 else ''}"
    else:
        rows = (f'<tr><td style="padding:20px 16px;text-align:center;color:#999;'
                f'font-size:14px;font-style:italic;">No completed games for {date_display}</td></tr>')
        count = "No games"
    return (
        f'<div style="margin-bottom:24px;border-radius:10px;overflow:hidden;'
        f'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
        f'<div style="background:{sport["color"]};padding:14px 16px;">'
        f'<span style="color:#fff;font-size:15px;font-weight:700;">{sport["icon"]}&nbsp; {sport["label"]}</span>'
        f'<span style="color:rgba(255,255,255,0.6);font-size:12px;float:right;">{count}</span>'
        f'</div>'
        f'<div style="background:#fff;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'
        f'</div></div>'
    )


def _highlights_html(notables: list) -> str:
    if not notables: return ""
    items = "".join(
        f'<div style="font-size:13px;color:#333;padding:5px 0;border-bottom:1px solid #fef3cd;">{n}</div>'
        for n in notables
    )
    return (
        '<div style="margin-bottom:24px;border-radius:10px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
        '<div style="background:#f59e0b;padding:14px 16px;">'
        '<span style="color:#fff;font-size:15px;font-weight:700;">⚡ Highlights</span>'
        '</div>'
        f'<div style="background:#fffbeb;padding:12px 16px;">{items}</div>'
        '</div>'
    )


def _tomorrow_html(upcoming: dict, tom_display: str) -> str:
    sections = []
    for k, games in upcoming.items():
        if not games: continue
        sport = SPORTS[k]
        rows = "".join(
            f'<div style="font-size:13px;color:#333;padding:5px 0;border-bottom:1px solid #f0f0f0;">'
            f'<b>{g["away_team"]}</b> @ <b>{g["home_team"]}</b>'
            f'<span style="float:right;color:#888;font-size:12px;">{fmt_et(g["start_time"])}</span>'
            f'</div>'
            for g in games
        )
        sections.append(
            f'<div style="margin-bottom:12px;">'
            f'<div style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;'
            f'letter-spacing:0.6px;margin-bottom:4px;">{sport["icon"]} {sport["label"]}</div>'
            f'{rows}</div>'
        )
    if not sections: return ""
    return (
        '<div style="margin-bottom:24px;border-radius:10px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
        '<div style="background:#4a5568;padding:14px 16px;">'
        f'<span style="color:#fff;font-size:15px;font-weight:700;">📅 Tomorrow — {tom_display}</span>'
        '</div>'
        f'<div style="background:#fff;padding:12px 16px;">{"".join(sections)}</div>'
        '</div>'
    )


def build_html(sport_sections: list, notables: list, upcoming: dict,
               date_display: str, tom_display: str) -> str:
    body = _highlights_html(notables) + "\n".join(sport_sections) + _tomorrow_html(upcoming, tom_display)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Daily Sports Scores — {date_display}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:620px;margin:0 auto;padding:24px 16px 32px;">
    <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
                border-radius:12px;padding:28px 24px;margin-bottom:24px;text-align:center;">
      <div style="font-size:32px;margin-bottom:10px;">🏆</div>
      <h1 style="margin:0 0 6px;color:#fff;font-size:22px;font-weight:700;letter-spacing:0.5px;">
        Daily Sports Scores</h1>
      <p style="margin:0;color:#a0aec0;font-size:14px;">{date_display}</p>
    </div>
    {body}
    <div style="text-align:center;padding-top:8px;">
      <p style="margin:0;color:#bbb;font-size:12px;">
        Scores via ESPN &middot; Sent automatically every morning</p>
    </div>
  </div>
</body>
</html>"""

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(to: str, frm: str, pwd: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(frm, pwd)
        s.sendmail(frm, to, msg.as_string())

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    to  = os.environ.get("REPORT_RECIPIENT",    "").strip()
    frm = os.environ.get("GMAIL_ADDRESS",       "").strip()
    pwd = os.environ.get("GMAIL_APP_PASSWORD",  "").strip()
    missing = [n for n, v in [("REPORT_RECIPIENT", to), ("GMAIL_ADDRESS", frm), ("GMAIL_APP_PASSWORD", pwd)] if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")

    now_et      = _now_et()
    sport_keys  = active_sports(now_et.month)
    date_str, date_display = yesterday_et()
    tom_str,  tom_display  = tomorrow_et()
    print(f"Active sports: {sport_keys}")
    print(f"Yesterday: {date_display}  |  Tomorrow: {tom_display}")

    # Scoreboards (yesterday + tomorrow) — all in parallel
    with ThreadPoolExecutor(max_workers=8) as pool:
        yest_futs = {k: pool.submit(fetch_scoreboard, SPORTS[k]["path"], date_str) for k in sport_keys}
        tom_futs  = {k: pool.submit(fetch_scoreboard, SPORTS[k]["path"], tom_str)  for k in sport_keys}
        yest_sbs  = {k: f.result() for k, f in yest_futs.items()}
        tom_sbs   = {k: f.result() for k, f in tom_futs.items()}

    all_games = {k: parse_games(yest_sbs[k]) for k in sport_keys}
    for k, games in all_games.items():
        print(f"  {SPORTS[k]['label']}: {len(games)} game(s), "
              f"{sum(1 for g in games if g['completed'])} completed")

    # Summaries for all completed games — one parallel batch across all sports
    to_fetch = [(k, g["event_id"]) for k in sport_keys
                for g in all_games[k] if g["completed"] and g["event_id"]]
    print(f"Fetching {len(to_fetch)} game summaries...")
    with ThreadPoolExecutor(max_workers=10) as pool:
        sum_futs = {(k, eid): pool.submit(fetch_summary, SPORTS[k]["path"], eid)
                    for k, eid in to_fetch}
        raw_summaries = {key: f.result() for key, f in sum_futs.items()}

    parsers = {"nhl": parse_nhl_detail, "mlb": parse_mlb_detail, "nfl": parse_nfl_detail}
    details = {(k, eid): parsers[k](raw) for (k, eid), raw in raw_summaries.items()}

    # Notables
    all_notables = []
    for k in sport_keys:
        game_dets = {g["event_id"]: details.get((k, g["event_id"]), {}) for g in all_games[k]}
        all_notables.extend(detect_notables(k, all_games[k], game_dets))

    # Tomorrow's upcoming games
    upcoming = {
        k: [g for g in parse_games(tom_sbs[k]) if not g["completed"]]
        for k in sport_keys
    }

    # Build + send
    sport_sections = []
    for k in sport_keys:
        game_dets = {g["event_id"]: details.get((k, g["event_id"]), {}) for g in all_games[k]}
        sport_sections.append(_sport_section(k, all_games[k], game_dets, date_display))

    html = build_html(sport_sections, all_notables, upcoming, date_display, tom_display)
    print(f"Sending to {to}...")
    send_email(to, frm, pwd, f"🏆 Sports Scores — {date_display}", html)
    print("Done.")


if __name__ == "__main__":
    main()
