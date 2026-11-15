import json, urllib.request, urllib.parse, time, os, hashlib, sys
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
BASE="https://arcgis.sdi.abudhabi.ae/agspublish/rest/services/OpenData/ADSDI_OpenData/MapServer"
OUT=sys.argv[1]; os.makedirs(OUT,exist_ok=True)

def get(url,tries=3,timeout=90):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA,
                "Referer":"https://data.abudhabi/","Accept":"application/json"}),timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if a==tries-1: raise
            time.sleep(3)

# DoH health layers named by the data.abudhabi DoH datasets
LAYERS={330:"hospitals",329:"health_centres",328:"clinics",332:"pharmacy",
        217:"diagnostic_centers",231:"dialysis_centre",234:"rehabilitation_center",
        235:"mobile_health_unit",236:"provision_health_service"}

log={}
for lid,slug in LAYERS.items():
    rec={"layer_id":lid,"slug":slug,"layer_url":f"{BASE}/{lid}"}
    try:
        meta=json.loads(get(f"{BASE}/{lid}?f=json"))
    except Exception as e:
        rec["error"]=repr(e)[:200]; log[lid]=rec; print("META FAIL",lid,slug); continue
    rec["name"]=meta.get("name"); rec["description"]=meta.get("description")
    rec["geometryType"]=meta.get("geometryType")
    rec["spatialReference"]=meta.get("sourceSpatialReference") or meta.get("extent",{}).get("spatialReference")
    rec["maxRecordCount"]=meta.get("maxRecordCount")
    rec["fields"]=[{"name":f["name"],"type":f["type"],"alias":f.get("alias")} for f in meta.get("fields",[])]
    rec["copyrightText"]=meta.get("copyrightText")
    # count
    cnt=json.loads(get(f"{BASE}/{lid}/query?where=1%3D1&returnCountOnly=true&f=json"))
    rec["feature_count"]=cnt.get("count")
    # pull all features as GeoJSON (paged)
    feats=[]; off=0; page=min(int(meta.get("maxRecordCount") or 1000),1000)
    while True:
        q=urllib.parse.urlencode({"where":"1=1","outFields":"*","returnGeometry":"true",
            "outSR":"4326","f":"geojson","resultOffset":off,"resultRecordCount":page})
        d=json.loads(get(f"{BASE}/{lid}/query?{q}"))
        fs=d.get("features") or []
        feats.extend(fs)
        if len(fs)<page: break
        off+=page
        if off>20000: break
        time.sleep(0.4)
    gj={"type":"FeatureCollection",
        "_source":{"service":BASE,"layer_id":lid,"layer_name":meta.get("name"),
                   "retrieved":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                   "outSR":"EPSG:4326","query":"where=1=1&outFields=*"},
        "features":feats}
    b=json.dumps(gj,ensure_ascii=False,indent=1).encode()
    p=f"{OUT}/{slug}.geojson"; open(p,'wb').write(b)
    rec["local"]=p; rec["bytes"]=len(b); rec["sha256"]=hashlib.sha256(b).hexdigest()
    rec["features_retrieved"]=len(feats)
    log[lid]=rec
    print(f"  {lid:>4} {slug:28} count={rec['feature_count']} retrieved={len(feats)} bytes={len(b)}")
    time.sleep(0.5)
json.dump(log,open(f"{OUT}/acquisition_log.json","w"),indent=1,ensure_ascii=False)
print("DONE")
