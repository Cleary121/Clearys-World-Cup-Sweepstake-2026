#!/usr/bin/env python3
"""Cleary's Cup auto-updater. Pulls API-Football WC 2026 results + cards, rebuilds the
inline window.WC_DATA in index.html. MODE=dryrun writes a preview only; MODE=live writes index.html + ver.txt."""
import os, re, json, time, datetime, urllib.request, urllib.error

KEY  = os.environ.get("API_FOOTBALL_KEY","")
MODE = os.environ.get("MODE","dryrun").strip().lower()
BASE = "https://v3.football.api-sports.io"
LEAGUE, SEASON = 1, 2026
FINISHED = {"FT","AET","PEN"}

IDMAP = {1:"BEL",2:"FRA",3:"CRO",5:"SWE",6:"BRA",7:"URU",8:"COL",9:"ESP",10:"ENG",11:"PAN",
12:"JPN",13:"SEN",15:"SUI",16:"MEX",17:"KOR",20:"AUS",22:"IRN",23:"KSA",25:"GER",26:"ARG",
27:"POR",28:"TUN",31:"MAR",32:"EGY",770:"CZE",775:"AUT",777:"TUR",1090:"NOR",1108:"SCO",
1113:"BIH",1118:"NED",1501:"CIV",1504:"GHA",1508:"COD",1531:"RSA",1532:"ALG",1533:"CPV",
1548:"JOR",1567:"IRQ",1568:"UZB",1569:"QAT",2380:"PAR",2382:"ECU",2384:"USA",2386:"HAI",
4673:"NZL",5529:"CAN",5530:"CUW"}

def api(path):
    req=urllib.request.Request(BASE+path, headers={"x-apisports-key":KEY})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=30) as r:
                d=json.load(r)
                if d.get("errors"): raise RuntimeError("API errors: %s"%d["errors"])
                return d
        except Exception as e:
            if attempt==2: raise
            time.sleep(2)

def load_wcdata(html):
    m=re.search(r"window\.WC_DATA\s*=\s*\{", html)
    if not m: raise RuntimeError("WC_DATA assignment not found")
    b=m.end()-1; depth=0
    for j in range(b,len(html)):
        if html[j]=="{":depth+=1
        elif html[j]=="}":
            depth-=1
            if depth==0: return b,j+1,json.loads(html[b:j+1])
    raise RuntimeError("WC_DATA not found")

def compute_total(code, matches, teams, S):
    t=teams.get(code)
    if not t: return 0
    total=0
    for m in matches:
        if m.get("status")!="FINISHED": continue
        if m["home"]==code: mine,opp,oppc,yc,rc=m["hs"],m["as"],m["away"],m.get("hy",0),m.get("hr",0)
        elif m["away"]==code: mine,opp,oppc,yc,rc=m["as"],m["hs"],m["home"],m.get("ay",0),m.get("ar",0)
        else: continue
        if mine is None or opp is None: continue
        res = "win" if mine>opp else ("draw" if mine==opp else None)
        total += mine*S["goalFor"]
        if mine>S["multiGoalOver"]: total += (mine-S["multiGoalOver"])*S["multiGoalBonusPer"]
        total += yc*S["yellow"] + rc*S["red"]
        if res=="win": total += S["win"]
        elif res=="draw": total += S["draw"]
        ot=teams.get(oppc)
        if ot and res:
            gap=t["rank"]-ot["rank"]
            if gap>=S["upsetMinGap"]:
                for tier in S["upsetTiers"]:
                    if gap>=tier["minGap"]:
                        total += tier["win"] if res=="win" else tier["draw"]; break
    return total

def player_total(p,matches,teams,S): return sum(compute_total(c,matches,teams,S) for c in p.get("teams",[]))
def order(players,matches,teams,S):
    return [p["id"] for p in sorted(players,key=lambda p:-player_total(p,matches,teams,S))]

def main():
    html=open("index.html",encoding="utf-8").read()
    s,e,D=load_wcdata(html)
    teams,players,S=D["teams"],D["players"],D["scoring"]
    existing={(m["home"],m["away"]):m for m in D.get("matches",[])}

    fx=api("/fixtures?league=%d&season=%d"%(LEAGUE,SEASON))["response"]
    new_matches=[]; events_calls=0; notes=[]
    for f in fx:
        st=f["fixture"]["status"]["short"]; rnd=f["league"]["round"]
        if st not in FINISHED: continue
        if rnd=="Group Stage - 1": continue
        hid,aid=f["teams"]["home"]["id"],f["teams"]["away"]["id"]
        home,away=IDMAP.get(hid),IDMAP.get(aid)
        if not home or not away: notes.append("UNMAPPED %s/%s"%(hid,aid)); continue
        hs,as_=f["goals"]["home"],f["goals"]["away"]
        ex=existing.get((home,away))
        reuse = MODE=="live" and ex and ex.get("hs")==hs and ex.get("as")==as_ and "hy" in ex and "goals" in ex and ex.get("gv")==2
        if reuse:
            hy,ay,hr,ar=ex["hy"],ex["ay"],ex["hr"],ex["ar"]; goals=ex.get("goals",[]); cards=ex.get("cards",[])
        else:
            ev=api("/fixtures/events?fixture=%d"%f["fixture"]["id"])["response"]; events_calls+=1
            hy=ay=hr=ar=0; goals=[]; cards=[]
            for x in ev:
                typ=x.get("type"); det=x.get("detail",""); tid=x.get("team",{}).get("id")
                pl=(x.get("player") or {}).get("name"); mn=(x.get("time") or {}).get("elapsed")
                side="h" if tid==hid else ("a" if tid==aid else None)
                if side is None: continue
                if typ=="Card":
                    red=("Red" in det); yellow=(det=="Yellow Card")
                    if side=="h": hr+=1 if red else 0; hy+=1 if yellow else 0
                    else: ar+=1 if red else 0; ay+=1 if yellow else 0
                    cards.append({"s":side,"p":pl,"m":mn,"c":"r" if red else "y"})
                elif typ=="Goal" and det!="Missed Penalty":
                    if not pl: continue
                    if x.get("comments")=="Penalty Shootout": continue  # shootout pens never count as goals
                    goals.append({"s":side,"p":pl,"m":mn,"og":det=="Own Goal","pen":det=="Penalty"})
        pw=None
        if st in ("PEN","AET") and hs==as_:
            if f["teams"]["home"].get("winner"): pw="h"
            elif f["teams"]["away"].get("winner"): pw="a"
        md={"date":f["fixture"]["date"][:10],"home":home,"away":away,
            "hs":hs,"as":as_,"hy":hy,"ay":ay,"hr":hr,"ar":ar,"goals":goals,"cards":cards,"gv":2,"status":"FINISHED"}
        if pw: md["pw"]=pw
        new_matches.append(md)
    new_matches.sort(key=lambda m:(m["date"],m["home"]))

    prev_up={(u["home"],u["away"]):u for u in D.get("upcoming",[])}
    nowts=datetime.datetime.now(datetime.timezone.utc); pred_calls=0
    upcoming=[]
    for f in fx:
        if f["fixture"]["status"]["short"]!="NS": continue
        hid,aid=f["teams"]["home"]["id"],f["teams"]["away"]["id"]
        home,away=IDMAP.get(hid),IDMAP.get(aid)
        if not home or not away: continue
        entry={"dt":f["fixture"]["date"],"home":home,"away":away,"fid":f["fixture"]["id"]}
        ex=prev_up.get((home,away))
        if ex and ex.get("wp") and ex["wp"].get("v")==2: entry["wp"]=ex["wp"]
        else:
            try:
                kt=datetime.datetime.fromisoformat(f["fixture"]["date"].replace("Z","+00:00"))
                if (kt-nowts).total_seconds()<48*3600 and pred_calls<15:
                    od=api("/odds?fixture=%d&bet=1"%f["fixture"]["id"])["response"]; pred_calls+=1
                    o={}
                    for v in od[0]["bookmakers"][0]["bets"][0]["values"]: o[v["value"].lower()]=float(v["odd"])
                    ih,idr,ia=1.0/o["home"],1.0/o["draw"],1.0/o["away"]; tot=ih+idr+ia
                    entry["wp"]={"h":round(ih/tot*100),"d":round(idr/tot*100),"a":round(ia/tot*100),"v":2}
            except Exception: pass
        upcoming.append(entry)
    upcoming.sort(key=lambda m:m["dt"])

    st=api("/standings?league=%d&season=%d"%(LEAGUE,SEASON))
    wctable={}; seen=set()
    for grp in st["response"][0]["league"]["standings"]:
        for row in grp:
            tid=row["team"]["id"]
            if tid in seen: continue
            seen.add(tid); code=IDMAP.get(tid)
            if code: wctable[code]={"pts":row["points"],"gd":row["goalsDiff"]}

    def sig(ms): return sorted([m["home"],m["away"],m["hs"],m["as"],m["hy"],m["ay"],m["hr"],m["ar"]] for m in ms)
    changed = sig(new_matches)!=sig(D.get("matches",[])) or wctable!=D.get("wcTable",{}) or any("goals" not in m for m in D.get("matches",[])) or any(m.get("gv")!=2 for m in D.get("matches",[])) or upcoming!=D.get("upcoming")
    now=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    board=sorted(players,key=lambda p:-player_total(p,new_matches,teams,S))
    lines=["%2d. %-8s %4d pts"%(i+1,p["name"],player_total(p,new_matches,teams,S)) for i,p in enumerate(board)]
    summary=("MODE=%s  changed=%s  finished_g2=%d  events_calls=%d\nresultsUpdated=%s\n\nLEADERBOARD:\n%s\n\nMATCHES:\n%s\n\nNOTES: %s"
        %(MODE,changed,len(new_matches),events_calls,now,"\n".join(lines),
          "\n".join("  %s %s %s-%s %s  (Y%s/%s R%s/%s)"%(m["date"],m["home"],m["hs"],m["as"],m["away"],m["hy"],m["ay"],m["hr"],m["ar"]) for m in new_matches),
          notes or "none"))
    print(summary)

    if MODE=="dryrun":
        open("_dryrun.txt","w").write(summary)
        D2=dict(D); D2["matches"]=new_matches; D2["wcTable"]=wctable; D2["upcoming"]=upcoming
        D2["prevOrder"]=order(players,D.get("matches",[]),teams,S); D2["resultsUpdated"]=now; D2["updated"]=now
        open("_dryrun_index.html","w",encoding="utf-8").write(html[:s]+json.dumps(D2,ensure_ascii=False,indent=2)+html[e:])
        return
    if not changed:
        print("No change - skipping commit."); open("_nochange.txt","w").write(now); return
    D["prevOrder"]=order(players,D.get("matches",[]),teams,S)
    D["matches"]=new_matches; D["wcTable"]=wctable; D["upcoming"]=upcoming; D["resultsUpdated"]=now; D["updated"]=now
    newhtml=html[:s]+json.dumps(D,ensure_ascii=False,indent=2)+html[e:]
    stamp=datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    newhtml=re.sub(r"var V='[0-9-]+'","var V='%s'"%stamp,newhtml,count=1)
    open("index.html","w",encoding="utf-8").write(newhtml); open("ver.txt","w").write(stamp+"\n")
    print("LIVE written. build=",stamp)

if __name__=="__main__": main()
