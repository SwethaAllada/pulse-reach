import json, time, urllib.parse, urllib.request, os, hashlib, sys
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PROXY="https://statad.gov.ae/o/communication?url="
OUT=sys.argv[1]; os.makedirs(OUT,exist_ok=True)
os.makedirs(OUT+"/indicator_detail",exist_ok=True)
os.makedirs(OUT+"/indicator_metadata",exist_ok=True)

def call(path, params, binary=False, tries=3):
    q="&".join(f"{k}={urllib.parse.quote(str(v))}" for k,v in params.items())
    full=path+("?"+q if q else "")
    url=PROXY+urllib.parse.quote(full)
    for a in range(tries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA,
                "Referer":"https://statad.gov.ae/health?ThemeID=221&tab=KSI",
                "Accept":"application/json, */*"})
            with urllib.request.urlopen(req,timeout=90) as r:
                return r.read(), dict(r.headers)
        except Exception as e:
            if a==tries-1: return None, {"_error":repr(e)[:250]}
            time.sleep(4)

# PRIORITY indicators: the 8 named in the brief + population/demography + child-health + capacity
PRIORITY = {
 # --- the eight named in the task brief ---
 2825:"clinics", 2845:"clinics_by_region", 4052:"hospital_beds_by_region",
 3998:"physicians_by_facility_region", 2589:"inpatients_by_citizenship",
 2590:"inpatients_by_type_of_illness", 2592:"inpatients_by_facility_region",
 2614:"cancer_deaths",
 # --- population / demography (closes the biggest gap) ---
 3916:"population_estimates", 3919:"population_estimates_by_gender",
 3175:"population_estimates_by_region", 3178:"population_density_by_region",
 3920:"population_growth_rate_by_region", 3002:"population_growth_rate_by_gender",
 4868:"projection_of_population_by_age_group", 4870:"projection_of_population_by_region",
 4869:"projection_of_population_by_gender", 4866:"projection_of_population",
 # --- health-system capacity ---
 2800:"hospitals", 2801:"hospitals_by_region", 4111:"hospital_beds",
 2753:"hospital_beds_by_type", 2822:"health_centers", 2823:"health_centers_by_region",
 2847:"pharmacies", 2848:"pharmacies_by_region",
 2798:"licensed_healthcare_facilities_by_type_and_region",
 # --- workforce ---
 2701:"physicians", 2702:"nurses", 2703:"nurses_by_facility_region", 2704:"nurses_by_sector",
 2729:"pharmacists", 2731:"pharmacists_by_facility_region", 2681:"clinicians_by_type_and_facility_region",
 3997:"physicians_per_1000_population", 2705:"nurses_per_1000_population",
 2728:"dentists_per_1000_population", 2732:"pharmacists_per_1000_population",
 # --- utilisation ---
 2872:"inpatients", 2617:"outpatients", 2619:"outpatients_by_citizenship",
 2622:"outpatients_by_facility_region",
 # --- child & maternal health (Well-Child pathway denominators) ---
 3463:"births_by_citizenship", 3465:"births_by_region", 3466:"births_by_gender",
 3549:"births_by_region_citizenship_gender", 3269:"crude_birth_rate_by_region",
 3267:"crude_birth_rate_by_region_and_citizenship",
 3507:"infant_deaths_by_gender", 3506:"infant_deaths_by_region", 3583:"infant_deaths_by_citizenship",
 3505:"infant_deaths_by_region_citizenship_gender",
 3319:"infant_mortality_rate_by_region", 3274:"infant_mortality_rate_by_citizenship",
 3321:"infant_mortality_rate_by_gender",
 3495:"neonatal_deaths_by_region", 3496:"neonatal_deaths_by_citizenship",
 3813:"neonatal_mortality_rate_by_region",
 3502:"post_neonatal_deaths_by_region", 3498:"post_neonatal_mortality_rate_by_region",
 3423:"under_five_deaths_by_region", 3508:"under_five_deaths_by_citizenship",
 3509:"under_five_deaths_by_gender", 3424:"under_five_deaths_by_region_citizenship_gender",
 3280:"under_five_mortality_rate_by_region", 3281:"under_five_mortality_rate_by_citizenship",
 3459:"stillbirths_by_region", 3421:"stillbirth_rate_by_region",
 # --- mortality / disease ---
 2985:"deaths_by_cause_of_death", 2584:"deaths_by_cause_and_age_group",
 2585:"deaths_by_cause_and_citizenship", 2583:"deaths_by_cause_and_gender",
 2586:"deaths_by_cause_and_region", 3536:"deaths_by_region", 3510:"deaths_by_citizenship",
 3535:"deaths_by_citizenship_and_age_group", 3422:"deaths_by_region_citizenship_gender",
 3271:"crude_death_rate_by_region", 3276:"age_specific_mortality_rate_by_region",
 2616:"cancer_deaths_by_citizenship", 2615:"cancer_deaths_by_gender",
 2649:"communicable_disease_notifications", 2651:"communicable_disease_notifications_by_type",
 2650:"communicable_disease_notifications_by_age_group",
 # --- insurance (Thiqa-relevant denominators) ---
 2677:"health_insurance_members_by_type", 2679:"proportion_with_health_insurance_by_region",
}

print("acquiring", len(PRIORITY), "indicators")
log={}
for n,(iid,slug) in enumerate(sorted(PRIORITY.items()),1):
    rec={"indicator_id":iid,"slug":slug}
    b,h = call("Statistics/GetClickhouseIndicatorDetail", {"indicatorId":iid,"lang":"EN"})
    if b:
        p=f"{OUT}/indicator_detail/{iid}_{slug}.json"
        open(p,'wb').write(b)
        rec["detail"]={"path":p,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()}
        try:
            d=json.loads(b)["Data"]
            rec["detail"]["rows"]=len(d.get("Data") or [])
            rec["detail"]["title"]=d["Metadata"]["component_title"]
            rec["detail"]["data_source"]=d["Metadata"].get("data_source")
            rec["detail"]["updated"]=d["Metadata"].get("updated")
        except Exception as e: rec["detail"]["parse_error"]=repr(e)[:150]
    else: rec["detail"]={"error":h.get("_error")}
    time.sleep(0.5)
    b2,h2 = call("Statistics/GetMetadataAndMethodology", {"indicatorId":iid,"lang":"EN"})
    if b2 and b2[:2]==b'PK':
        p2=f"{OUT}/indicator_metadata/{iid}_{slug}_metadata.xlsx"
        open(p2,'wb').write(b2)
        rec["metadata_xlsx"]={"path":p2,"bytes":len(b2),"sha256":hashlib.sha256(b2).hexdigest()}
    else:
        rec["metadata_xlsx"]={"error":(h2.get("_error") if b2 is None else "not xlsx: "+repr(b2[:80]))}
    log[iid]=rec
    if n%10==0: print(" ",n,"/",len(PRIORITY))
    time.sleep(0.5)

json.dump(log,open(f"{OUT}/acquisition_log.json","w"),indent=1,ensure_ascii=False)
ok=sum(1 for r in log.values() if 'path' in r.get('detail',{}))
okm=sum(1 for r in log.values() if 'path' in r.get('metadata_xlsx',{}))
print(f"DONE detail:{ok}/{len(PRIORITY)} metadata_xlsx:{okm}/{len(PRIORITY)}")
