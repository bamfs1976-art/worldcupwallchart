#!/usr/bin/env python3
"""
Refresh GOAL_DATA in index.html from the official FIFA timeline API.

Tokenless endpoints (same source pochih/worldcup2026 uses):
  calendar:  https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023&count=200&language=en
  timeline:  https://api.fifa.com/api/v3/timelines/17/285023/{IdStage}/{IdMatch}?language=en

Timeline event types: 0 = goal, 34 = own goal, 41 = penalty goal
(assists are the preceding Type 1 event — not used here).

FIFA's official match numbering disagrees with this wallchart's for M93/M94,
so matches are resolved by TEAM PAIR against DISC_DATA.matches (the wallchart's
own numbering); the official number is only trusted for M103/M104 before they
appear in DISC_DATA. Goals for matches that cannot be resolved are skipped with
a warning rather than guessed.

Usage:
  python3 build_goals.py            # fetch, rewrite GOAL_DATA in index.html
  python3 build_goals.py --dry-run  # print what would change, don't write
No third-party dependencies; needs outbound HTTPS to api.fifa.com.
"""
import json, re, sys, unicodedata, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
CAL = ("https://api.fifa.com/api/v3/calendar/matches"
       "?idCompetition=17&idSeason=285023&count=200&language=en")
TL = "https://api.fifa.com/api/v3/timelines/17/285023/{stage}/{match}?language=en"
GOAL_TYPES = {0: "goal", 34: "og", 41: "goal"}  # 41 rendered as goal + "(pen)"

# FIFA display names -> this wallchart's team names (G.t)
ALIAS = {
    "Korea Republic": "Rep. of Korea", "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Côte d'Ivoire": "Ivory Coast", "Cabo Verde": "Cape Verde", "Congo DR": "DR Congo",
    "United States": "USA", "IR Iran": "IR Iran", "Türkiye": "Türkiye",
}

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "worldcupwallchart-goals/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())

def main():
    dry = "--dry-run" in sys.argv
    html = INDEX.read_text(encoding="utf-8")
    disc = json.loads(re.search(r"const DISC_DATA=(\{.*?\});\n", html, re.S).group(1))

    # wallchart match lookup by unordered normalized team pair
    pair_to_match = {}
    for m in disc["matches"]:
        pair_to_match[frozenset((norm(m["home"]), norm(m["away"])))] = m["match"]

    cal = fetch(CAL)
    matches = cal.get("Results") or cal.get("results") or []
    print(f"calendar: {len(matches)} matches")

    goal_data = {}
    for fm in matches:
        # played matches only
        status = fm.get("MatchStatus")
        if status != 0:  # 0 = finished in FIFA's v3 API
            continue
        home = (fm.get("Home") or {}).get("TeamName") or []
        away = (fm.get("Away") or {}).get("TeamName") or []
        hname = home[0]["Description"] if home else None
        aname = away[0]["Description"] if away else None
        if not hname or not aname:
            continue
        hname, aname = ALIAS.get(hname, hname), ALIAS.get(aname, aname)
        official_no = fm.get("MatchNumber")
        wall_no = pair_to_match.get(frozenset((norm(hname), norm(aname))))
        if wall_no is None:
            if official_no in (103, 104):  # not yet in DISC_DATA; numbering unambiguous
                wall_no = official_no
            else:
                print(f"  WARN: cannot resolve {hname} v {aname} (official M{official_no}) — skipped")
                continue

        tl = fetch(TL.format(stage=fm["IdStage"], match=fm["IdMatch"]))
        events = tl.get("Event") or []
        goals = []
        for ev in events:
            etype = ev.get("Type")
            if etype not in GOAL_TYPES:
                continue
            minute = int(re.sub(r"[^0-9]", "", (ev.get("MatchMinute") or "0").split("+")[0]) or 0)
            player = (ev.get("PlayerName") or [{}])[0].get("Description") or "Unknown"
            # attribute to the scoring side's wallchart team name
            side_home = ev.get("HomeGoals") is not None  # fallback below if absent
            team = hname if ev.get("IdTeam") == (fm.get("Home") or {}).get("IdTeam") else aname
            if etype == 34:  # own goal: actor's team stays; type marks it
                goals.append({"min": minute, "team": team, "player": player, "type": "og"})
            elif etype == 41:
                goals.append({"min": minute, "team": team, "player": player + " (pen)"})
            else:
                goals.append({"min": minute, "team": team, "player": player})
        if goals:
            goal_data[wall_no] = sorted(goals, key=lambda g: g["min"])

    print(f"matches with goal events: {len(goal_data)}")

    # emit in the same literal style as the hand-seeded block
    def js_ev(g):
        parts = [f"min:{g['min']}", "team:" + json.dumps(g["team"], ensure_ascii=False),
                 "player:" + json.dumps(g["player"], ensure_ascii=False)]
        if g.get("type") == "og":
            parts.append("type:'og'")
        return "{" + ",".join(parts) + "}"

    lines = []
    for n in sorted(goal_data):
        lines.append(f"  {n}:[{','.join(js_ev(g) for g in goal_data[n])}]")
    literal = "const GOAL_DATA={\n" + ",\n".join(lines) + "\n};"

    pat = re.compile(r"const GOAL_DATA=\{.*?\n\};", re.S)
    assert len(pat.findall(html)) == 1, "GOAL_DATA block not found exactly once"
    new_html = pat.sub(lambda _: literal, html, count=1)
    if new_html == html:
        print("no changes")
        return
    if dry:
        print("--dry-run: would update GOAL_DATA")
        return
    INDEX.write_text(new_html, encoding="utf-8")
    print("index.html GOAL_DATA updated")

if __name__ == "__main__":
    main()
