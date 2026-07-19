#!/usr/bin/env python3
"""
Fill missing shirt numbers on DISC_DATA cards from ESPN's public roster API
(the squad source tbayryyev/worldcup-dashboard uses):

  teams list: https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/teams
  roster:     https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/teams/{id}?enable=roster

Cards imported from the dashboard's post-match reports sometimes arrive with an
empty or missing "number" field; this script matches each such card's player
against their team's ESPN roster (normalized full name, then surname) and
writes the jersey number in. Cards that already carry a number are never
touched, and ambiguous surname matches are skipped with a warning.

Usage:
  python3 build_numbers.py            # fetch rosters, patch index.html in place
  python3 build_numbers.py --dry-run  # report what would change
No third-party dependencies; needs outbound HTTPS to site.api.espn.com.
"""
import json, re, sys, unicodedata, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

# DISC team names -> ESPN display names, where they differ
ALIAS = {
    "Korea Republic": "South Korea", "Cabo Verde": "Cape Verde Islands",
    "Congo DR": "DR Congo", "Côte d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran", "Türkiye": "Turkey", "USA": "United States",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "worldcupwallchart-numbers/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def roster_maps():
    """{normalized espn team name: ({normalized player: jersey}, {surname: [jerseys]})}"""
    listing = fetch(f"{BASE}/teams")
    teams = []
    for group in listing.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = group.get("team") or {}
        if t.get("id"):
            teams.append((t["id"], t.get("displayName", "")))
    print(f"teams listed: {len(teams)}")
    out = {}
    for tid, name in teams:
        payload = fetch(f"{BASE}/teams/{tid}?enable=roster")
        athletes = (payload.get("team") or {}).get("athletes") or []
        by_name, by_surname = {}, {}
        for a in athletes:
            jersey = a.get("jersey")
            full = norm(a.get("displayName") or a.get("fullName") or "")
            if not jersey or not full:
                continue
            by_name[full] = jersey
            by_surname.setdefault(full.split()[-1], []).append(jersey)
        out[norm(name)] = (by_name, by_surname)
    return out


def main():
    dry = "--dry-run" in sys.argv
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const DISC_DATA=(\{.*?\});\n", html, re.S)
    disc = json.loads(m.group(1))

    rosters = roster_maps()

    filled = skipped = 0
    for c in disc["cards"]:
        if c.get("number"):
            continue
        team = ALIAS.get(c["team"], c["team"])
        maps = rosters.get(norm(team))
        if not maps:
            print(f"  WARN: no roster for team {c['team']!r} (M{c['match']})")
            skipped += 1
            continue
        by_name, by_surname = maps
        player = norm(c["player"])
        jersey = by_name.get(player)
        if jersey is None:
            candidates = by_surname.get(player.split()[-1], [])
            if len(candidates) == 1:
                jersey = candidates[0]
        if jersey is None:
            print(f"  WARN: no unique roster match for {c['player']!r} ({c['team']}, M{c['match']})")
            skipped += 1
            continue
        c["number"] = str(jersey)
        filled += 1

    print(f"filled: {filled}  unresolved: {skipped}")
    if not filled:
        print("no changes")
        return
    if dry:
        print("--dry-run: not writing")
        return
    payload = json.dumps(disc, ensure_ascii=False, separators=(",", ":"))
    INDEX.write_text(html[:m.start(1)] + payload + html[m.end(1):], encoding="utf-8")
    print("index.html DISC_DATA updated")


if __name__ == "__main__":
    main()
