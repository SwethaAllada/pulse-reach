import json, time, urllib.request, urllib.parse, os, hashlib, sys, re
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
OUT=sys.argv[1]; os.makedirs(OUT+"/metadata",exist_ok=True); os.makedirs(OUT+"/files",exist_ok=True)
cat=json.load(open('ad_catalogue.json'))

# PRIORITY ids: DoH facility + health indicators + population, plus the brief's named examples
IDS={
 # 2025 DoH licensed-facility datasets (facility locations candidate)
 "491e2925-4b67-4f5b-89cd-10d886f180af":"doh_hospitals_2025",
 "c33bedd4-0547-4324-b0b2-1fe5c58d476f":"doh_health_centres_2025",
 "38106739-eb6d-43b3-8534-007ebcc3ecfa":"doh_clinics_2025",
 "76c8cfa8-ce6f-48c6-a3db-5ee5d69972fe":"doh_pharmacy_2025",
 "bf944d80-c181-47c0-924a-062dba2ecbd5":"doh_diagnostic_centers_2025",
 "133a02c6-9c16-4dd8-8971-32afcebe5d4d":"doh_dialysis_centre_2025",
 "aa2544fe-d6e5-426a-b6c9-4a27b213b754":"doh_mobile_health_unit_2025",
 "049fc043-3acd-40a6-ba1b-abb08e0f30e2":"doh_provision_health_service_2025",
 "6aeca57b-2e10-43b3-935a-8a741f1bac89":"doh_rehabilitation_center_2025",
 # Gov Digital geospatial facility sets
 "0d2b8550-8f89-441a-a6a3-377d52d19fca":"govdigital_hospitals",
 "1944d4b6-9c9d-454f-b219-a129ce70d547":"govdigital_health_centres",
 "851b3d1e-aeb8-45b2-9b3c-5716ead5bb19":"govdigital_clinics",
 "5871bfaf-562c-4312-95ff-30880fdbea36":"govdigital_pharmacies",
 "faad8d06-e366-4cc5-9f06-6234b9dc00ae":"govdigital_diagnostic_centers_blood_banks",
 # DoH population & health indicators
 "1dc618d2-2931-492c-916b-93b5dfb2c2be":"doh_population_benchmark_selected_time_series",
 "941ac91f-5ad3-49b9-84f8-6da26a9f4023":"doh_population_benchmark_intl_comparison",
 "f864d8f8-7049-42ba-bb01-1449dfe9cad6":"doh_population_structure",
 "2af30982-4430-42aa-8832-6d7dfaf84602":"doh_population_and_benchmarks",
 "44a7f9a4-00a3-4c01-aad8-b96eaf71575f":"doh_diabetes_prevalence",
 "70f6902b-fff1-496d-9f35-1712c5ef2aa2":"doh_non_communicable_diseases",
 "e715313f-f83d-471d-97be-4006246ee95a":"doh_cancer_incidence",
 "daa986b0-1832-41d1-aa44-bc5ea258d8e6":"doh_cancer_death",
 "25b1c6ae-141e-43c0-8521-ec1f8ae0049f":"doh_vital_statistics",
 "f91f00e5-7b6b-4003-af75-7b3aa33d6d4d":"doh_birth_statistics",
 "7115379b-ff84-4251-858e-cbcf5dc4da5f":"doh_death_statistics",
 "b6a5c783-272d-48f6-8b27-e445f520d7a5":"doh_communicable_diseases",
 "87621300-3368-4404-b333-b735227f4ca6":"doh_facilities",
 "0dc8adf5-e1fe-4b71-8b55-438ceed4cfcc":"doh_clinicians",
 "cec3fbe4-7b23-44d5-8cb2-68768c64b339":"doh_bed_occupancy",
 "b23df5bd-eac5-4069-9854-245d3977ffd3":"doh_bed_type_occupancy",
 "eafaad8b-ad82-4840-8c69-7de1294f4370":"doh_payer_members",
 "81b57879-4423-4c07-9041-53ed5a90bacc":"doh_abu_dhabi_health_statistics_2017",
 # the brief's named example
 "18c2f41d-9613-492a-aff3-4a4cd98677a6":"mohap_nurses_by_category_district_nationality_sex",
}
def get(url, timeout=60, tries=3, headers=None):
    h={"User-Agent":UA,"Accept":"*/*"}; h.update(headers or {})
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=timeout) as r:
                return r.read(), dict(r.headers), r.status
        except Exception as e:
            if a==tries-1: return None, {"_error":repr(e)[:250]}, None
            time.sleep(3)

log={}
for n,(did,slug) in enumerate(IDS.items(),1):
    rec={"identifier":did,"slug":slug,
         "catalogue_title":(cat.get(did) or {}).get('title'),
         "dataset_page":f"https://data.abudhabi/opendata/dataset/detail?id={did}"}
    b,h,st=get(f"https://data.abudhabi/opendata/api/1/metastore/schemas/dataset/items/{did}",
               headers={"Accept":"application/json"})
    if not b:
        rec["metadata"]={"error":h.get("_error")}; log[did]=rec; continue
    open(f"{OUT}/metadata/{slug}.json","wb").write(b)
    try: meta=json.loads(b)
    except Exception as e: rec["metadata"]={"parse_error":repr(e)}; log[did]=rec; continue
    rec["metadata"]={"path":f"{OUT}/metadata/{slug}.json","title":meta.get("title"),
        "publisher":(meta.get("publisher") or {}).get("name"),
        "license":meta.get("license"),"issued":meta.get("issued"),"modified":meta.get("modified"),
        "theme":meta.get("theme"),"description":(meta.get("description") or "")[:400],
        "contactPoint":meta.get("contactPoint")}
    rec["distributions"]=[]
    for di,d in enumerate(meta.get("distribution") or []):
        du=d.get("downloadURL") or d.get("accessURL")
        drec={"format":d.get("format"),"mediaType":d.get("mediaType"),
              "title":d.get("title"),"url":du}
        if du and re.search(r'\.(xlsx|xls|csv|json|geojson|zip)(\?|$)',du,re.I):
            fb,fh,fst=get(du,timeout=120)
            if fb:
                ext=re.search(r'\.([a-z]+)(\?|$)',du,re.I).group(1).lower()
                fn=f"{OUT}/files/{slug}" + (f"_{di}" if di else "") + f".{ext}"
                open(fn,'wb').write(fb)
                drec.update({"downloaded":True,"local":fn,"bytes":len(fb),
                   "sha256":hashlib.sha256(fb).hexdigest(),
                   "http_content_type":fh.get("Content-Type"),
                   "last_modified":fh.get("Last-Modified"),
                   "content_disposition":fh.get("Content-Disposition"),
                   "magic":fb[:4].hex()})
            else: drec.update({"downloaded":False,"error":fh.get("_error")})
        else:
            drec["downloaded"]=False
            drec["reason"]="non-file distribution (API/esri rest/landing page)" if du else "no URL"
        rec["distributions"].append(drec)
        time.sleep(0.3)
    log[did]=rec
    print(f"  [{n}/{len(IDS)}] {slug}: {sum(1 for x in rec['distributions'] if x.get('downloaded'))}/{len(rec['distributions'])} files")
    time.sleep(0.3)
json.dump(log,open(f"{OUT}/acquisition_log.json","w"),indent=1,ensure_ascii=False)
tot=sum(sum(1 for x in r.get('distributions',[]) if x.get('downloaded')) for r in log.values())
print("TOTAL FILES DOWNLOADED:",tot)
