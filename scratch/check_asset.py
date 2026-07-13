import json
path = "/home/venkatanarayana/team-everest/new-ocr/output/test_guna/results/result.json"
d = json.load(open(path))
ext = d.get("extraction_schema_json", d)
if isinstance(ext, str):
    ext = json.loads(ext)
print({k: ext[k] for k in ext if k.startswith("asset_")})
