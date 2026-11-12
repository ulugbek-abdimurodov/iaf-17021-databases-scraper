"""SANAS (South Africa) CB register scraper.

sanas.co.za is not reachable from the build workspace, so extraction runs in a
browser tab on https://www.sanas.co.za (same-origin SharePoint REST + pdf.js).
Paste BROWSER_JS into the devtools console; it leaves the compact export in
window.__d.T, which is saved as sanas_raw.txt (format documented below).

Sources:
  /_api/web/lists/getbytitle('Legal Entity (Published)')/items  (Field_x0020_Of_x0020_AccreditatiId eq 3 = Certification Bodies)
  /_api/web/lists/getbytitle('Certificate (Published)')/items    (latest per Legal_x0020_EntityId -> /Certificate Published/<FileLeafRef>)

sanas_raw.txt: cert lines `facility|body_idx|initial_date|expiry|scheme|ea_ranges|food_cats|md_areas|pdf_stem`,
then `#`, then body lines `idx|name|address|city|postcode|province|phone|email|`.
"""
BROWSER_JS = r"""
// 1) entities  2) latest certificate per entity  3) pdf.js text per PDF
// 4) parse: lines after 'IAF Code'/'Codes' header -> leading 1-39 numbers = EA;
//    'Category X' / 'X  Name' -> ISO 22003-1 categories; medical-device area lines kept for MD8.
// 5) scheme from 'authorised to certify organisations to ISO ...' text, else Discipline field.
// See conversation log; dates shifted +2h (SharePoint stores SAST midnight as UTC 22:00).
"""
if __name__ == "__main__":
    print(__doc__)
