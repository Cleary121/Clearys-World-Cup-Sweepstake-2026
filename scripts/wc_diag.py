#!/usr/bin/env python3
# Diagnostic: confirm API-Football key/plan + dump trimmed WC 2026 shapes for building the updater.
import os, json, urllib.request, urllib.error

KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE = "https://v3.football.api-sports.io"
LEAGUE = 1      # World Cup
SEASON = 2026

def get(path):
    req = urllib.request.Request(BASE + path, headers={"x-apisports-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_httperror": e.code, "_body": e.read().decode("utf-8", "ignore")[:500]}
    except Exception as e:
        return {"_error": str(e)}

out = {}

# 1) account/plan + request usage
out["status"] = get("/status")

# 2) confirm league id + season coverage
out["league"] = get("/leagues?id=%d&season=%d" % (LEAGUE, SEASON))

# 3) teams (id -> name mapping is the key thing we need)
teams = get("/teams?league=%d&season=%d" % (LEAGUE, SEASON))
out["teams"] = [{"id": t["team"]["id"], "name": t["team"]["name"], "code": t["team"].get("code")}
                for t in teams.get("response", [])] if isinstance(teams.get("response"), list) else teams

# 4) fixtures: count by status, and grab one FINISHED fixture as a sample
fx = get("/fixtures?league=%d&season=%d" % (LEAGUE, SEASON))
resp = fx.get("response", []) if isinstance(fx, dict) else []
out["fixtures_count"] = len(resp)
def slim(f):
    return {"id": f["fixture"]["id"], "status": f["fixture"]["status"]["short"],
            "round": f["league"]["round"], "date": f["fixture"]["date"],
            "home": f["teams"]["home"]["name"], "homeId": f["teams"]["home"]["id"],
            "away": f["teams"]["away"]["name"], "awayId": f["teams"]["away"]["id"],
            "gh": f["goals"]["home"], "ga": f["goals"]["away"]}
finished = [f for f in resp if f["fixture"]["status"]["short"] in ("FT","AET","PEN")]
out["sample_fixtures"] = [slim(f) for f in resp[:6]]
out["finished_count"] = len(finished)

# 5) events for one finished fixture (to confirm card detail strings)
if finished:
    fid = finished[0]["fixture"]["id"]
    ev = get("/fixtures/events?fixture=%d" % fid)
    out["sample_events_fixture"] = fid
    out["sample_events"] = [{"type": e.get("type"), "detail": e.get("detail"),
                             "team": e.get("team",{}).get("name"), "elapsed": e.get("time",{}).get("elapsed")}
                            for e in ev.get("response", [])] if isinstance(ev, dict) else ev

# 6) standings shape (drives the wcTable / main pot)
st = get("/standings?league=%d&season=%d" % (LEAGUE, SEASON))
try:
    groups = st["response"][0]["league"]["standings"]
    out["sample_standing_group"] = [{"name": r["team"]["name"], "id": r["team"]["id"],
                                     "points": r["points"], "goalsDiff": r["goalsDiff"]} for r in groups[0]]
    out["standings_group_count"] = len(groups)
except Exception as e:
    out["standings_raw"] = st

open("_diag.json","w").write(json.dumps(out, indent=2, ensure_ascii=False))
print("wrote _diag.json")
print("status:", json.dumps(out.get("status"))[:300])
print("teams found:", len(out["teams"]) if isinstance(out["teams"], list) else out["teams"])
print("fixtures:", out.get("fixtures_count"), "finished:", out.get("finished_count"))
