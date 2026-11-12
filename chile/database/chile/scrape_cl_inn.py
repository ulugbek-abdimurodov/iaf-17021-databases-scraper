"""INN Chile scraper. directorio.inn.cl is reachable only from a browser session (DataTables POST
/Directorio/retorna_lista_acreditados). Run in browser console on https://directorio.inn.cl/:
  T=$('#tabla_directorio_acreditados').DataTable(); T.page.len(3000).draw();
  rows=T.rows().data().toArray().filter(x=>/Sistemas/.test(x.NOMBRE_TIPO_OEC))
and export CODIGO_ACREDITACION, NOMBRE_FANTASIA, COMUNA, NOMBRE_AREA_ACREDITACION, TELEFONO,
FECHA_VIGENCIA_DESDE, FECHA_VIGENCIA_HASTA, NOMBRE_ESTADO_ACREDITACION, DOCUMENTO_ENCRYPT
as TSV to inn_raw.tsv. This script validates the export."""
import csv, sys
from pathlib import Path
rows = list(csv.reader(open(Path(__file__).with_name("inn_raw.tsv"), encoding="utf-8"), delimiter="\t"))
assert all(len(r) == 9 for r in rows), "bad row"
print(f"Rows: {len(rows)}")
