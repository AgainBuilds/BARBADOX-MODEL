#!/usr/bin/env python3
"""Build and settle 3+1 slips from picks.csv. Does not invent bookmaker prices."""
import csv, hashlib, os
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PICKS=ROOT/"picks.csv"; HISTORY=ROOT/"slip_history.csv"; REPORT=ROOT/"slip.md"
OVER=float(os.getenv("CORE1_SLIP_THRESHOLD","0.79"))
UNDER=float(os.getenv("CORE2_SLIP_THRESHOLD","0.75"))
MAX_NEW=max(0,int(os.getenv("MAX_NEW_SLIPS","3")))
FIELDS=["slip_id","generated_at","slip_no","leg_no","date","league","home","away","selection","market","probability","fair_odds","bookmaker_odds","source","hg","ag","leg_result","slip_result"]

def read(path):
    if not path.exists(): return []
    with path.open(newline="",encoding="utf-8-sig") as f: return list(csv.DictReader(f))
def write(path,fields,rows):
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
def norm(s): return "".join(c.lower() for c in str(s or "") if c.isalnum())
def core2(r):
    return str(r.get("note","")).upper().startswith("CORE2_UNDER35") or (str(r.get("market",""))=="3.5" and "UNDER" in str(r.get("factors","")).upper())
def pkey(r):
    return (str(r.get("date",""))[:10],str(r.get("league","")).upper().strip(),norm(r.get("home")),norm(r.get("away")),"3.5" if core2(r) else "1.5")
def leg_result(r):
    res=str(r.get("result","")).strip().upper()
    if res in ("HIT","MISS","VOID"): return res
    if res=="POSTPONED": return "VOID"
    try: hg,ag=int(r.get("hg","")),int(r.get("ag",""))
    except (TypeError,ValueError): return "PENDING"
    return ("HIT" if hg+ag<=3 else "MISS") if core2(r) else ("HIT" if hg+ag>=2 else "MISS")
def eligible(r,today):
    date=str(r.get("date",""))[:10]
    return date>=today and bool(date) and leg_result(r)=="PENDING"
def candidates(picks,today):
    overs=[]; unders=[]
    for r in picks:
        if not eligible(r,today): continue
        try: p=float(r.get("probability",""))
        except (ValueError,TypeError): continue
        if core2(r):
            if p>=UNDER: unders.append(r)
        else:
            try: market=float(r.get("market",""))
            except (ValueError,TypeError): continue
            if abs(market-1.5)<1e-4 and p>=OVER: overs.append(r)
    overs.sort(key=lambda r:(-float(r["probability"]),r["date"],r["league"]))
    unders.sort(key=lambda r:(-float(r["probability"]),r["date"],r["league"]))
    return overs,unders
def sid(legs):
    raw="|".join("|".join(map(str,pkey(r))) for r in legs)
    return hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
def refresh(history,picks):
    bykey={pkey(r):r for r in picks}
    groups={}
    for h in history:
        k=(str(h.get("date",""))[:10],str(h.get("league","")).upper().strip(),norm(h.get("home")),norm(h.get("away")),"3.5" if str(h.get("selection","")).upper()=="UNDER 3.5" else "1.5")
        current=bykey.get(k)
        if current:
            outcome=leg_result(current)
            if outcome!="PENDING":
                h["leg_result"]=outcome; h["hg"]=current.get("hg",""); h["ag"]=current.get("ag","")
        groups.setdefault(h.get("slip_id",""),[]).append(h)
    for rows in groups.values():
        outcomes=[str(r.get("leg_result","PENDING")).upper() for r in rows]
        if "MISS" in outcomes: overall="MISS"
        elif len(rows)==4 and all(x=="HIT" for x in outcomes): overall="HIT"
        elif len(rows)==4 and all(x in ("HIT","VOID") for x in outcomes) and "VOID" in outcomes: overall="VOID"
        else: overall="PENDING"
        for r in rows: r["slip_result"]=overall
    return history
def make_leg(slip_id,created,slip_no,n,r):
    is_u=core2(r); p=float(r["probability"])
    return {"slip_id":slip_id,"generated_at":created,"slip_no":slip_no,"leg_no":n,
      "date":str(r.get("date",""))[:10],"league":r.get("league",""),"home":r.get("home",""),"away":r.get("away",""),
      "selection":"UNDER 3.5" if is_u else "OVER 1.5","market":"3.5" if is_u else "1.5",
      "probability":f"{p:.4f}","fair_odds":f"{1/p:.3f}" if p>0 else "",
      "bookmaker_odds":"","source":"Core 2" if is_u else "Core 1",
      "hg":r.get("hg",""),"ag":r.get("ag",""),"leg_result":"PENDING","slip_result":"PENDING"}
def generate(history,picks,today):
    overs,unders=candidates(picks,today)
    existing={r.get("slip_id","") for r in history}; made=0
    created=datetime.now(timezone.utc).isoformat()
    for combo in combinations(overs,3):
        if made>=MAX_NEW: break
        keys=[pkey(r)[:4] for r in combo]
        if len(set(keys))<3: continue
        for under in unders:
            if pkey(under)[:4] in keys: continue
            legs=list(combo)+[under]; ident=sid(legs)
            if ident in existing: continue
            slip_no=f"{today}-{ident[:6]}"
            for i,r in enumerate(legs,1): history.append(make_leg(ident,created,slip_no,i,r))
            existing.add(ident); made+=1
            if made>=MAX_NEW: break
    print(f"New slips: {made}; eligible Core 1 Over 1.5: {len(overs)}; eligible Core 2 Under 3.5: {len(unders)}")
    return history
def render(history):
    groups={}
    for r in history: groups.setdefault(r["slip_id"],[]).append(r)
    settled=[g for g in groups.values() if g and g[0].get("slip_result") in ("HIT","MISS","VOID")]
    hits=sum(g[0]["slip_result"]=="HIT" for g in settled); losses=sum(g[0]["slip_result"]=="MISS" for g in settled)
    pending=sum(g[0].get("slip_result")=="PENDING" for g in groups.values())
    lines=["# BARBADOX 3+1 SLIP TRACKER","",f"Updated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}","","## Settlement summary",
      f"- Slips recorded: **{len(groups)}**",f"- Confirmed hits: **{hits}**",f"- Confirmed losses: **{losses}**",f"- Pending slips: **{pending}**",
      f"- Settled hit rate (voids excluded): **{hits/(hits+losses):.1%}**" if hits+losses else "- Settled hit rate: **not available yet**",
      "","## Odds","- Fair odds = `1 / model probability`; these are model-derived prices, not bookmaker odds.",
      "- Bookmaker odds are not currently fetched by this repository. Combined bookmaker odds, payout, and ROI are therefore not reported.",""]
    if not groups:
        lines += ["No complete slip exists yet.","Need 3 eligible Core 1 Over 1.5 picks at ≥79% and 1 eligible Core 2 Under 3.5 pick at ≥75%. Run Core 2 before running this workflow.",""]
    for ident,rows in sorted(groups.items(),key=lambda item:item[1][0].get("generated_at",""),reverse=True):
        first=rows[0]; lines += [f"## Slip {first.get('slip_no',ident)} — **{first.get('slip_result','PENDING')}**","","| Leg | Match | Pick | Probability | Fair odds | Actual score | Result |","|---:|---|---|---:|---:|---|---|"]
        for r in sorted(rows,key=lambda x:int(x.get("leg_no",0) or 0)):
            score=f"{r.get('hg')}–{r.get('ag')}" if r.get("hg") not in ("",None) and r.get("ag") not in ("",None) else "—"
            lines.append(f"| {r.get('leg_no')} | {r.get('home')} vs {r.get('away')} ({r.get('date')}) | {r.get('selection')} | {float(r.get('probability') or 0):.1%} | {r.get('fair_odds') or '—'} | {score} | {r.get('leg_result')} |")
        lines.append("")
    lines += ["## Settlement rules","- HIT means all four legs are graded HIT from actual scores.","- One MISS makes the slip MISS. Pending legs are never counted as wins.","- VOID is used only when no leg lost and at least one leg is void.","- Model probability alone does not establish profitability.",""]
    REPORT.write_text("\n".join(lines),encoding="utf-8")
def main():
    today=datetime.now(timezone.utc).date().isoformat()
    picks=read(PICKS); history=refresh(read(HISTORY),picks)
    history=generate(history,picks,today); history=refresh(history,picks)
    write(HISTORY,FIELDS,history); render(history)
    print(f"Report: {REPORT}"); print(f"Permanent slip history: {HISTORY}")
if __name__=="__main__": main()
