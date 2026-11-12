# UAF review log

Scope: UAF Management Systems programme, active and visible CABs (64 listed).

Non-17021-1 schedules ignored (inspection, testing lab, product certification, GHG validation/verification).

| Body | Reason |
| --- | --- |
| Accredify Global LLC | skipped schemes: Artificial Intelligence Management System |
| ACCURATE GLOBAL INC | skipped schemes: Anti - Bribery Management Systems; Artificial Intelligence Management Systems |
| A-MARK RATINGS PRIVATE LIMITED | skipped schemes: Anti - Bribery Management Systems |
| AMERICO QUALITY STANDARDS REGISTECH PRIVATE LIMITED | skipped schemes: Anti - Bribery Management Systems |
| ANS System Certification Private Limited | skipped schemes: Anti - bribery management systems; Asset management System; Educational organizations Management systems; Facility M anagement Management systems |
| ARS Assessment Private Ltd | skipped schemes: Anti - Bribery Management Systems; Educational Organizations Management System |
| BLUESTAR MANAGEMENT SYSTEMS PVT. LTD. | skipped schemes: Safety Management Systems |
| Certi-Trust Africa & Middle East | skipped schemes: Anti - Bribery Management Systems |
| CQI CERTIFICATION PRIVATE LIMITED | skipped schemes: Anti - Bribery Management Systems |
| FQC FIRST QUALITY CERTIFICATION PVT.LTD | skipped schemes: Safety Management Systems |
| Gabriel Registrar Certificate Issuing Services LLC | skipped schemes: Anti - Bribery Management Systems; Artificial Intelligence Management Systems; Asset Management Systems; Compliance Management Systems; Event Sustainability Management Systems; Facility Management - Management Systems |
| Global Inter Certification(GIC) | skipped schemes: Anti - B ribery M anagement S ystems |
| Guardian Assessment Pvt. Ltd | skipped schemes: Anti - Bribery Management Systems; Educational Organizations Management Systems; Product Certification Scheme; Verification of GHG statements at the organization level |
| HYM International Certifications Pvt. Ltd | skipped schemes: Educational Organizations Management Systems |
| IFC GLOBAL LLC | skipped schemes: Anti - Bribery Management Systems |
| Institute of Global Certification Co., Ltd. | skipped schemes: Anti - bribery management systems; Compliance Management Systems; Educational organizations Management systems |
| INTER CERT PRIVATE LIMITED | skipped schemes: Artificial Intelligence Management Systems; Asset Management Systems; Educational Organizations Management Systems |
| International Conformity Assessment services Inc | no in-scope ISO/IEC 17021-1 scheme; holds: Asset Management Systems Scheme |
| KVQA ASSESSMENT PRIVATE LIMITED | skipped schemes: Artificial Intelligence Management System; I nformation Security Management System |
| LMS Assessment Services Private Limited | skipped schemes: Anti - Bribery Management Systems |
| NACE CERTIFICATION PRIVATE LIMITED | skipped schemes: Educational Organizations Management Systems |
| PDCA Certification Private Limited | skipped schemes: Anti - bribery management systems; Artificial Intelligence Management Systems; Facility Management Management systems |
| QACS International Pvt. Ltd | skipped schemes: Anti Bribery Management Systems |
| SCK CERTIFICATIONS PRIVATE LIMITED | skipped schemes: Anti - Bribery Management Systems |
| Sistema Management Services Private Limited | skipped schemes: Anti - Bribery Management Systems Scheme (ABMS) |
| SQC Certification Services Private Limited | skipped schemes: Anti Bribery Management Systems; Artificial Intelligence Management Systems |
| TNV Global Limited (TNV) | skipped schemes: Anti - Bribery Management Systems; Artificial Intelligence Management Systems; Asset Management Systems; Educational Organizations Management Systems; Facility Management - Management Systems |
| ZEPPY CERTIFICATION LIMITED | skipped schemes: Anti Bribery Management Systems |

## Known parse gaps (fix manually)
- BMSPL, FQC: ISO 45001 row split across lines ("…Safety Management Systems") — not imported; acc. no. not captured.
- KVQA: ISO/IEC 27001 row ("I nformation Security…") — not imported.
- EUROLAB/TNV/GPL: only the MS schedule used; IB/TLAB/PrCB/VVB schedules ignored.
- ISO 50001 technical areas, ISO/IEC 27001/27701/20000-1 and ISO 22301 carry no sector codes in UAF schedules → empty ea_codes.
