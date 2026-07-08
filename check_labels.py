import json, glob, os

results = glob.glob("/home/venkatanarayana/team-everest/new-ocr/output/*/results/result.json")
results += glob.glob("/home/venkatanarayana/team-everest/new-ocr/output/*/0/results/result.json")
results.sort(key=os.path.getmtime, reverse=True)

if not results:
    print("No result.json found")
    exit()

path = results[0]
print(f"Using: {path}\n")
data = json.load(open(path))
fields = data.get("fields", [])

# Check if it's a batch result
if "pdfs" in data and not fields:
    for pdf_result in data["pdfs"]:
        if isinstance(pdf_result, dict) and "fields" in pdf_result:
            fields = pdf_result["fields"]
            break

print(f"Total fields: {len(fields)}\n")
for f in fields:
    label = f.get("label", "?")
    value = str(f.get("value", "")).strip()
    page = f.get("page", "?")
    print(f"  [p{page}] {label} = {value[:60]}")
