#!/usr/bin/env python3
"""Merge qualified Core 2 Under 3.5 selections into picks.csv without clashing with Core 1."""
import csv, os, re
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPORT_DIR=ROOT/os.getenv("REPORT_DIR","reports")
PICKS=ROOT/"picks.csv"
RUN_LOG=ROOT/"core2_run.log"
THRESHOLD=float(os.getenv("THRESHOLD","0.75"))
FIELDS=["date","league","home","away","market","probability","core_probability","low","high","field_temp_c","factors","logged_at","hg","ag","result","note"]

def read_csv(path):
    if not path.exists(): return []
    with path.open(newline="",encoding="utf-8-sig") as f: return list(csv.DictReader(f))
def norm(s): return "".join(c.lower() for c in str(s or "") if c.isalnum())
def is_core2(r): return str(r.get("note","")).strip().upper().startswith("CORE2_UNDER35")
def key(r):
    # Market is part of the key: a fixture can have both O1.5 and U3.5 records.
    market="3.5" if is_core2(r) else str(r.get("market","")).strip()
    return (str(r.get("date",""))[:10],str(r.get("league","")).upper().strip(),norm(r.get("home")),norm(r.get("away")),market)

def make_pick(s,historical):
    try: p=float(s.get("p_final",""))
    except (ValueError,TypeError): return None
    if not 0 <= p <= 1 or p < THRESHOLD: return None
    hg=ag=result=""
    if historical:
        try: hg,ag=int(s["hg"]),int(s["ag"])
        except (KeyError,ValueError,TypeError): return None
        result="HIT" if hg+ag<=3 else "MISS"
        flag=str(s.get("hit","")).strip()
        if flag in ("0","1") and flag != ("1" if result=="HIT" else "0"):
            print("WARNING: Core 2 report hit flag disagrees with score:",s.get("home"),"vs",s.get("away"))
    return {"date":str(s.get("date",""))[:10],"league":s.get("league",""),"home":s.get("home",""),"away":s.get("away",""),
      "market":"3.5","probability":f"{p:.4f}","core_probability":s.get("p_cal","") or s.get("p_raw",""),
      "low":"","high":"","field_temp_c":"","factors":"Core 2 Under 3.5 walk-forward",
      "logged_at":datetime.now(timezone.utc).isoformat(),"hg":hg,"ag":ag,"result":result,
      "note":"CORE2_UNDER35|HISTORICAL" if historical else "CORE2_UNDER35|UPCOMING"}

def parse_upcoming_log():
    """Core 2 currently prints upcoming picks to stdout; turn qualified lines into CSV rows."""
    if not RUN_LOG.exists(): return []
    pattern=re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s+([A-Z0-9]+)\s+(.+?)\s+vs\s+(.+?)\s+(\d+(?:\.\d+)?)%\s+\(raw\s+(\d+(?:\.\d+)?)%\)",re.I)
    out=[]
    for line in RUN_LOG.read_text(encoding="utf-8",errors="replace").splitlines():
        m=pattern.search(line)
        if not m: continue
        date,league,home,away,final,raw=m.groups()
        p=float(final)/100
        if p>=THRESHOLD:
            out.append({"date":date,"league":league,"home":home.strip(),"away":away.strip(),
                        "p_final":f"{p:.4f}","p_cal":f"{p:.4f}","p_raw":f"{float(raw)/100:.4f}","cleared":"1"})
    return out

def main():
    existing=read_csv(PICKS)
    positions={key(row):i for i,row in enumerate(existing)}
    historical=read_csv(REPORT_DIR/"core2_results.csv")
    upcoming=read_csv(REPORT_DIR/"core2_upcoming.csv")
    if not upcoming:
        upcoming=parse_upcoming_log()
        if upcoming:
            REPORT_DIR.mkdir(parents=True,exist_ok=True)
            with (REPORT_DIR/"core2_upcoming.csv").open("w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=["date","league","home","away","p_final","p_cal","p_raw","cleared"])
                w.writeheader(); w.writerows(upcoming)
            print(f"Exported {len(upcoming)} qualified upcoming Core 2 forecasts from console log.")
    added=updated=protected=0
    for rows,is_hist in ((historical,True),(upcoming,False)):
        for source in rows:
            if is_hist and str(source.get("cleared","")).strip()!="1": continue
            pick=make_pick(source,is_hist)
            if pick is None: continue
            k=key(pick)
            if k not in positions:
                positions[k]=len(existing); existing.append(pick); added+=1; continue
            i=positions[k]; old=existing[i]
            if not is_core2(old):
                protected+=1; continue
            was_hist="HISTORICAL" in str(old.get("note","")).upper()
            if is_hist or not was_hist:
                existing[i]=pick; updated+=1
    with PICKS.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader()
        w.writerows({field:r.get(field,"") for field in FIELDS} for r in existing)
    print("\nBARBADOX CORE 2 TRACKING COMPLETE")
    print(f"Threshold: {THRESHOLD:.1%} | new: {added} | updated: {updated} | protected: {protected}")
    print(f"Total shared picks: {len(existing)}")

if __name__=="__main__": main()
