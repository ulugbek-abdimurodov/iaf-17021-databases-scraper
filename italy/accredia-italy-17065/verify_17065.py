import csv, json, re, sys, collections, pdfplumber
from pathlib import Path
out = Path(sys.argv[1]); regs = sys.argv[2:]
rows = [r for r in csv.DictReader(open(out / 'scope_lines.csv'))]
tok = lambda s: re.findall(r'\w+', s)
for reg in regs or sorted({r['registration_no'] for r in rows}):
    rr = [r for r in rows if r['registration_no'] == reg]
    for src in sorted({r['source'] for r in rr}):
        got = collections.Counter()
        for r in rr:
            if r['source'] != src: continue
            o = json.loads(r['other_columns_raw']) if r['other_columns_raw'] else {}
            got.update(tok(' '.join([r['product_text_raw'], r['scheme_text_raw'], r['normative_docs_raw'], r['scheme_type_raw'], *o.values()])))
        want = collections.Counter()
        with pdfplumber.open(out / 'pdf' / f'{src}.pdf') as pdf:
            for p in pdf.pages:
                w = p.extract_words(); top = next((x['bottom'] for x in w if x['text'] in ('Expiry', 'Exipry')), 0)
                for l in p.crop((0, top + 1, p.width, p.height)).extract_text_lines():
                    if not re.match(r'^\d+\s*/\s*\d+$', l['text'].strip()): want.update(tok(l['text']))
        miss = want - got; extra = got - want
        print(reg, src, 'lines', sum(r['source'] == src for r in rr), 'pdf_tokens', sum(want.values()), 'missing', sum(miss.values()), list(miss)[:8], 'extra', sum(extra.values()), list(extra)[:5])
