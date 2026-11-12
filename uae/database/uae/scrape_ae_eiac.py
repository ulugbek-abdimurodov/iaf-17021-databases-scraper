"""EIAC (UAE) register scraper for CertiFind.

eiac.gov.ae and accreditation.eiac.gov.ae are not reachable from the build
workspace, so the scrape runs in a browser session on https://eiac.gov.ae/directory/:

1. BROWSER_JS (below) is executed in the directory page. It reads the
   client-side DataTable (all 971 entries), keeps rows whose main field is a
   management-system scheme, fetches every directory-details page (retrying the
   flaky "There Are No Data" responses), downloads each certificate+scope PDF
   from https://accreditation.eiac.gov.ae/api/return_pdf_file?file_name=<file>
   and extracts text with pdf.js. Per PDF it keeps: title, validity, issue line,
   IAF/EA codes (only inside the IAF/NACE scope tables), ISO 22003-1 categories
   and the list of countries the CAB may issue certificates in.
2. The resulting JSON array is saved as database/uae/eiac_raw.json
   (run `python scrape_ae_eiac.py <dump.json>` to normalise/save a dump).
"""
import json
import sys
from pathlib import Path

BROWSER_JS = r"""
const API='https://accreditation.eiac.gov.ae/api/return_pdf_file?file_name=';
const pdfjsLib=await import('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs');
pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const rows=$('#myTable').DataTable().rows().nodes().toArray().map(n=>{const a=n.querySelector('a[href*=directory-details]');
  return {name:a.textContent.trim(),href:a.href,type:n.querySelector('p').innerText.trim()}}).filter(x=>/Management/.test(x.type));
const page=async x=>{for(let k=0;k<6;k++){const h=await (await fetch(x.href)).text();if(/Main Field/.test(h))return h;await sleep(1500)}};
const TX=async f=>{const b=await (await fetch(API+encodeURIComponent(f))).arrayBuffer();const doc=await pdfjsLib.getDocument({data:b}).promise;const out=[];
  for(let i=1;i<=doc.numPages;i++){const c=await (await doc.getPage(i)).getTextContent();const L={};
    c.items.forEach(it=>{const y=Math.round(it.transform[5]);(L[y]=L[y]||[]).push([it.transform[4],it.str])});
    out.push(Object.keys(L).sort((a,b)=>b-a).map(y=>L[y].sort((a,b)=>a[0]-b[0]).map(z=>z[1]).join(' ').replace(/\s+/g,' ').trim()).filter(Boolean).join('\n'))}
  return out.join('\n==PAGE==\n')};
const EX=t=>{const L=t.split('\n'),r={};const s=L.findIndex(l=>/S ?COPE OF/.test(l));r.ttl=s>=0?L[s+1]:'';
  r.val=(t.match(/Validity:([^\n]*)/)||[,''])[1];r.iss=((t.match(/Issue No\.:[^\n]*/)||[''])[0]).replace(/\s/g,'');
  const ea=new Set(),cat=new Set();let on=false;
  for(const l of L){if(/IAF Code|Cluster|Category Codes|Technical Area|Code\b.*Description/i.test(l))on=true;
    if(/Page \d+ of|allowed to issue|Accreditation History|info@eiac/.test(l))on=false;if(!on)continue;
    const m=l.match(/^(\d{1,2}) (?=[\d(A-Za-z])/);if(m&&+m[1]>=1&&+m[1]<=39)ea.add(+m[1]);
    const c=l.match(/^([A-K]) ?(?:I{1,3}|IV)? ?:/);if(c)cat.add(c[1])}
  r.ea=[...ea].sort((a,b)=>a-b).join(' ');r.cat=[...cat].sort().join('');
  const c=L.findIndex(l=>/in following countries/.test(l));const ct=[];
  if(c>=0)for(let k=c+1;k<L.length&&!/^The following|Page \d|Accreditation History|info@|covered in/.test(L[k]);k++)if(!/^[- ]+$/.test(L[k]))ct.push(L[k].replace(/-{3,}/g,'').trim());
  r.ct=ct.join(';');return r};
const out=[];
for(const x of rows){const h=await page(x);const d=new DOMParser().parseFromString(h,'text/html');const tx=d.body.innerText.replace(/\s+/g,' ');
  const g=(a,b)=>(tx.match(new RegExp(a+' ?(.*?) '+b))||[,''])[1].trim();
  const a=d.querySelector('.download-pdf');const hdr=a.parentElement.previousElementSibling;
  const r=EX(await TX(a.dataset.file));
  out.push({nm:x.name,id:a.dataset.name.replace(/\.pdf$/i,''),addr:g('Address','PO box'),po:g('Zip Code','Email'),em:g('Email','Website'),
    web:g('Website','Phone No\\.'),ph:g('Phone No\\.','(Main Field|Terms)'),init:g('Initial Accreditation Date:','Contacts'),
    since:(hdr.querySelector('p span')||{textContent:''}).textContent.trim(),...r,dir:(x.href.match(/ID=(\d+)/)||[])[1],f:a.dataset.file})}
JSON.stringify(out);
"""

if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("eiac_raw.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    Path(__file__).with_name("eiac_raw.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Registrations: {len(data)}")
