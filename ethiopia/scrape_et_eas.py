"""EAS (Ethiopia) scraper. eas-eth.org is unreachable from the workspace, so extraction
runs in the browser: register page -> body pages -> scanned PDF certificates (OCR text layer via pdf.js).
Run this JS in a tab on https://eas-eth.org/certification-bodies/ and save the JSON to eas_raw.json."""
JS = r"""
const L=await import('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs');
L.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs';
const out={};
for(const a of document.querySelectorAll('article a')){
  const h=await (await fetch(a.href)).text();const d=new DOMParser().parseFromString(h,'text/html');
  const pdf=[...d.querySelectorAll('a')].map(x=>x.href).find(u=>/\.pdf$/i.test(u));let t='';
  if(pdf){const p=await L.getDocument(pdf).promise;for(let i=1;i<=p.numPages;i++){t+=' '+(await (await p.getPage(i)).getTextContent()).items.map(x=>x.str).join(' ')}}
  out[a.textContent.trim()]={page:a.href,pdf,html:d.body.innerText,pdf_text:t};
}
JSON.stringify(out)
"""
if __name__ == "__main__":
    print(JS)
