#!/usr/bin/env python3
"""
Crop precise regions for Fridge and 3.6 (Smartphone / Separate Wi-Fi) checkboxes
from page 3 of gunalakshmi.pdf.

PDF size: 1653 x 2339 pixels
Page 3 (0-indexed: page index 2)
"""
import sys
sys.path.insert(0, "/home/venkatanarayana/team-everest/new-ocr")

import fitz  # PyMuPDF
from PIL import Image
import io
import os

PDF_PATH = "/home/venkatanarayana/team-everest/new-ocr/Test_Batch/1test/gunalakshmi.pdf"
OUT_DIR = "/home/venkatanarayana/team-everest/new-ocr/output"
os.makedirs(OUT_DIR, exist_ok=True)

doc = fitz.open(PDF_PATH)
page = doc[2]  # page 3 (0-indexed)

# Render at 2x resolution for clarity
SCALE = 2.0
mat = fitz.Matrix(SCALE, SCALE)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
W, H = img.size
print(f"Page 3 rendered size: {W} x {H}")

def crop_region(img, x_frac_start, x_frac_end, y_frac_start, y_frac_end, name):
    W, H = img.size
    x0 = int(x_frac_start * W)
    x1 = int(x_frac_end * W)
    y0 = int(y_frac_start * H)
    y1 = int(y_frac_end * H)
    crop = img.crop((x0, y0, x1, y1))
    # scale up 3x for visibility
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST)
    path = os.path.join(OUT_DIR, name)
    crop.save(path)
    print(f"Saved {name}: ({x0},{y0}) -> ({x1},{y1})")
    return crop

# ── Question 4.1 assets row ──
# strip_55 shows y around 55-57% of page height
# Fridge is approx column 25-38% of page width
crop_region(img, 0.20, 0.42, 0.535, 0.565, "detail_fridge_area.png")
crop_region(img, 0.00, 0.30, 0.535, 0.565, "detail_washing_machine.png")
crop_region(img, 0.38, 0.55, 0.535, 0.565, "detail_ac.png")

# ── Question 3.6 row ──
# strip_61 shows y around 60-62% 
# Smartphone left side, Separate Wi-Fi middle
crop_region(img, 0.00, 0.35, 0.595, 0.625, "detail_q36_smartphone.png")
crop_region(img, 0.30, 0.65, 0.595, 0.625, "detail_q36_wifi.png")
crop_region(img, 0.60, 1.00, 0.595, 0.625, "detail_q36_others.png")

doc.close()
print("Done.")
