import json
d = json.load(open("/home/venkatanarayana/team-everest/new-ocr/output/local_batch_2026-07-08_06-57-13/results/result.json"))
print("Top-level keys:", list(d.keys()))
print("batch:", d.get("batch"))
print("num_pdfs:", d.get("num_pdfs"))
print("fields count:", len(d.get("fields", [])))
print("pdfs count:", len(d.get("pdfs", [])))

if d.get("pdfs"):
    p0 = d["pdfs"][0]
    print("\nFirst PDF keys:", list(p0.keys()))
    print("First PDF fields count:", len(p0.get("fields", [])))
    for f in p0.get("fields", [])[:5]:
        print(f"  {f.get('label')}: {str(f.get('value',''))[:50]}")
