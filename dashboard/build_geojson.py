"""Rebuild vn_provinces.geojson: simplify the 34 province files from thanglequoc/vietnamese-provinces-database (MIT).

Usage: python dashboard/build_geojson.py <dir with json/geojson/*/*.geojson> dashboard/vn_provinces.geojson
"""
import glob, json, sys
from shapely.geometry import shape, mapping
from shapely import set_precision

src, out = sys.argv[1], sys.argv[2]
NAME = {"Thanh Hoá": "Thanh Hóa", "Khánh Hoà": "Khánh Hòa"}  # match analysis/locations.csv spelling
feats = []
for f in sorted(glob.glob(f"{src}/*.geojson")):
    feat = json.load(open(f))["features"][0]
    p = feat["properties"]
    g = shape(feat["geometry"]).simplify(0.008, preserve_topology=True)
    g = set_precision(g, 0.001)
    name = NAME.get(p["name"], p["name"])
    feats.append({"type": "Feature", "id": name, "properties": {"name": name, "code": p["code"]},
                  "geometry": mapping(g)})
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"), ensure_ascii=False,
          separators=(",", ":"))
print(len(feats))
