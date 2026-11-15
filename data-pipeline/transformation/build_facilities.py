"""Build a validated Abu Dhabi health-facility table from the SDI GeoJSON extracts.

Input : data/raw/abudhabi_sdi/*.geojson   (immutable, as served)
Output: data/processed/facilities/abu_dhabi_health_facilities.csv  (+ .json quality report)

The ONLY transformations applied, each recorded per row in `geo_quality`:
  - lon/lat transposition repaired where the pair is outside the Abu Dhabi
    bounding box but valid when swapped            -> geo_quality='swapped_repaired'
  - (0,0) placeholder coordinates nulled           -> geo_quality='missing_placeholder'
  - coordinates outside the emirate after repair   -> geo_quality='out_of_bounds'
  - otherwise                                      -> geo_quality='ok'

Nothing is dropped. No value is invented. Run from the repository root.

IMPORTANT — composite string fields. In the source, BEDS, SPECIALITIES, PROFESSIONALS
are NOT numbers. They are semicolon-delimited composite records, e.g.

    BEDS          "Acute Care , Pediatric , 38 , 0 , 0; Critical Care Unit , ... "
    PROFESSIONALS "Allied Health Care - 68; Consultant Physician - 27; ..."
    SPECIALITIES  "Surgery - Thoracic Surgery; Dental - Prosthodontics; ..."

They are copied through verbatim and must be parsed deliberately downstream; casting
them to a number yields nothing. `inpatient_bed_capacity` IS a plain integer and is the
field to use for bed counts. THIQA / BASIC / ENHANCED are 'N/A' for every row in the
source and carry no information — do not read insurance acceptance from them.
"""
import json, csv, glob, os, sys, hashlib

# Abu Dhabi emirate bounding box (generous), WGS84
LON_MIN, LON_MAX = 51.0, 56.5
LAT_MIN, LAT_MAX = 22.0, 25.5

FIELDS = ["facility_id","source_layer","facility_name_en","facility_name_ar","license_no",
          "license_status","type","category","subtype","region","city","is_public",
          "has_insurance","thiqa","basic","enhanced","beds","inpatient_bed_capacity",
          "emergency_department","pediatric_emergency_department","maternity_emergency_care",
          "home_care_services","specialities","professionals","longitude","latitude","geo_quality"]

def _count(rows, key):
    out = {}
    for r in rows:
        k = (r.get(key) or "(blank)")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))

def in_box(lon, lat):
    return (lon is not None and lat is not None
            and LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX)

def main(root="."):
    src = sorted(glob.glob(os.path.join(root, "data/raw/abudhabi_sdi/*.geojson")))
    if not src:
        sys.exit("no input GeoJSON found under data/raw/abudhabi_sdi/")
    out_dir = os.path.join(root, "data/processed/facilities")
    os.makedirs(out_dir, exist_ok=True)

    rows, stats = [], {}
    for path in src:
        layer = os.path.basename(path).replace(".geojson", "")
        gj = json.load(open(path, encoding="utf-8"))
        st = {"input_features": len(gj["features"]), "ok": 0, "swapped_repaired": 0,
              "missing_placeholder": 0, "out_of_bounds": 0, "null_geometry": 0}
        for ft in gj["features"]:
            p = ft.get("properties") or {}
            g = ft.get("geometry") or {}
            coords = (g.get("coordinates") or [None, None])[:2]
            lon, lat = (coords + [None, None])[:2]
            if lon is None or lat is None:
                q = "null_geometry"
            elif lon == 0 and lat == 0:
                q, lon, lat = "missing_placeholder", None, None
            elif in_box(lon, lat):
                q = "ok"
            elif in_box(lat, lon):
                lon, lat, q = lat, lon, "swapped_repaired"
            else:
                q = "out_of_bounds"
            st[q] += 1
            rows.append({
                "facility_id": p.get("OBJECTID"), "source_layer": layer,
                "facility_name_en": p.get("FACILITYNAME"), "facility_name_ar": p.get("FACILITYNAMEAR"),
                "license_no": p.get("FACILITYLICENSE"), "license_status": p.get("LICENSESTATUS"),
                "type": p.get("TYPE"), "category": p.get("CATEGORY"), "subtype": p.get("SUBTYPE"),
                "region": p.get("REGION"), "city": p.get("CITY"),
                "is_public": p.get("ISPUBLIC"), "has_insurance": p.get("HASINSURANCE"),
                "thiqa": p.get("THIQA"), "basic": p.get("BASIC"), "enhanced": p.get("ENHANCED"),
                "beds": p.get("BEDS"), "inpatient_bed_capacity": p.get("INPATIENTBEDCAPACITY"),
                "emergency_department": p.get("EMERGENCYDEPARTMENT"),
                "pediatric_emergency_department": p.get("PEDIATRICEMERGENCYDEPARTMENT"),
                "maternity_emergency_care": p.get("MATERNITYEMERGENCYCARE"),
                "home_care_services": p.get("HOMECARESERVICES"),
                "specialities": p.get("SPECIALITIES"), "professionals": p.get("PROFESSIONALS"),
                "longitude": lon, "latitude": lat, "geo_quality": q,
            })
        stats[layer] = st

    csv_path = os.path.join(out_dir, "abu_dhabi_health_facilities.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    digest = hashlib.sha256(open(csv_path, "rb").read()).hexdigest()
    report = {
        "generated_from": [os.path.relpath(p, root) for p in src],
        "output": os.path.relpath(csv_path, root),
        "output_sha256": digest,
        "total_rows": len(rows),
        "per_layer": stats,
        "bounding_box": {"lon": [LON_MIN, LON_MAX], "lat": [LAT_MIN, LAT_MAX]},
        "field_cautions": {
            "beds / specialities / professionals":
                "semicolon-delimited composite strings copied verbatim, NOT numeric; "
                "populated mainly for hospitals. Parse deliberately; do not cast.",
            "inpatient_bed_capacity":
                "plain integer; this is the field to use for bed counts.",
            "thiqa / basic / enhanced":
                "'N/A' in every source row - carries no information, do not use.",
            "license_status":
                "only a subset are 'Active'; filter before treating a row as an "
                "operating facility.",
        },
        "license_status_counts": _count(rows, "license_status"),
        "region_counts": _count(rows, "region"),
        "notes": [
            "Aggregate facility register. Contains NO patient data.",
            "geo_quality must be carried through any downstream use; rows that are not "
            "'ok' or 'swapped_repaired' have no usable coordinates.",
            "Licence: Abu Dhabi Government Open Data License (attribution required).",
        ],
    }
    json.dump(report, open(os.path.join(out_dir, "quality_report.json"), "w"), indent=1)
    print(f"wrote {csv_path} ({len(rows)} rows)\nsha256 {digest}")
    for k, v in stats.items():
        print(f"  {k:30} {v}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
