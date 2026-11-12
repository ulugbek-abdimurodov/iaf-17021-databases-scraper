"""ECA (Costa Rica) OCSG register. Workspace egress to eca.or.cr is blocked, so data was
collected via browser from https://eca.or.cr/organismos-de-certificacion-de-sistemas/ and
the scope PDFs; this file records the extracted raw data."""
import json
BASE="https://eca.or.cr/descargas/196/acreditaciones/"
RAW=[{"id":"OCSG-001","name":"Asociación Instituto de Normas Técnicas de Costa Rica (INTECO)",
 "address":"300 Norte de Muñoz & Nanne, San Pedro de Montes de Oca, San José","phone":"+506 4080 6490",
 "email":"fchaves@inteco.org","website":"https://www.inteco.org/","issue_date":"2005-06-13",
 "source_url":"https://eca.or.cr/oec/asociacion-instituto-de-normas-tecnicas-de-costa-rica-direccion-de-servicios-de-certificacion-sistemas-de-gestion/",
 "schemes":[
  ("ISO 9001",[1,2,3,4,7,9,10,12,13,14,15,16,17,18,19,24,25,26,28,29,30,31,32,33,34,35,36,37,38,39],"4256/ocsg-001-inteco-alcance-acreditacion-reconocimiento-internacional.pdf"),
  ("ISO 14001",[1,3,4,7,9,10,12,13,14,15,16,17,19,24,25,27,28,29,30,32,33,34,35,36,37,39],"4256/ocsg-001-inteco-alcance-acreditacion-reconocimiento-internacional.pdf"),
  ("ISO 45001",[3,14,16,19,25,28,34,36],"4256/ocsg-001-inteco-alcance-acreditacion-reconocimiento-internacional.pdf"),
  ("ISO 50001",[],"4256/ocsg-001-inteco-alcance-acreditacion-reconocimiento-internacional.pdf"),
  ("ISO/IEC 27001",[],"4257/ocsg-001-inteco-alcance-acreditacion-reconocimiento-nacional.pdf")]}]
if __name__=="__main__":
    json.dump(RAW,open("eca_raw.json","w"),ensure_ascii=False,indent=1)
