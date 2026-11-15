import json, time, urllib.parse, urllib.request, sys, os
B="https://data.abudhabi/opendata/apis/search_main.php"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
OUT=sys.argv[1]

def get(url, tries=3):
    for a in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"application/json",
                 "Referer":"https://data.abudhabi/opendata/dataset"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode('utf-8','replace'))
        except Exception as e:
            if a==tries-1: print("  FAIL",url[:120],repr(e)[:120]); return None
            time.sleep(3)

def page(q, pg, size=50, theme=None):
    p={"fulltext":q,"uid":"","page":str(pg),"page-size":str(size),"sort-order":"desc","sort":"modified"}
    u=B+"?"+urllib.parse.urlencode(p)
    if theme: u+="&theme="+urllib.parse.quote(theme)
    return get(u)

# 1) full Health theme sweep
found={}
def sweep(q, theme=None, label=""):
    pg=1
    while True:
        d=page(q,pg,50,theme)
        if not d or d.get('status')!=200: break
        rows=d.get('data') or []
        tot=int(d.get('total_count') or 0)
        for r in rows:
            i=r.get('identifier')
            if i and i not in found:
                found[i]={k:r.get(k) for k in ('identifier','title','description','publisher','modified','issued','theme')}
                found[i]['_hit']=label or q
        print(f"  [{label or q}] page {pg}: +{len(rows)} (total_count={tot}, unique={len(found)})")
        if pg*50>=tot or not rows: break
        pg+=1
        time.sleep(1)

print("### Health theme sweep")
sweep("", theme="Health", label="theme:Health")
print("### Keyword sweeps")
for q in ["health","hospital","beds","clinic","physician","doctor","nurse","nursing","vaccination",
          "immunization","immunisation","mortality","death","birth","population","demographic",
          "disease","insurance","patient","screening","medical","healthcare","facilities","workforce",
          "cancer","diabetes","maternal","child"]:
    sweep(q, label=q)
    time.sleep(0.5)

json.dump(found, open(OUT,'w'), indent=1, ensure_ascii=False)
print("TOTAL UNIQUE:",len(found),"->",OUT)
