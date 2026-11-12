# BAS dataset review

19 bodies, 57 accreditations, 92 scope rows from 20 register entries.
Food-category-to-EA mappings are drafts (FOOD_CATEGORIES in prepare_certifind.py).

## Withdrawn and merged entries (3)

- 20 ОСС Axerta International EOOD (АКСЕРТА ИНТЕРНЕШЪНЪЛ ЕООД): register status 'Отнета акредитация' -> WITHDRAWN; accreditation kept for the record, no scopes written
- 20 ОСС Axerta International EOOD (АКСЕРТА ИНТЕРНЕШЪНЪЛ ЕООД): Bulgarian full-scope file is the suspension order (A 504 of 27.12.2024), not a scope; the English annex was read
- 17 ОСС КЮ-ЕИД ЮРЪП ЕООД: register entries 11252 (certificate 01.04.2026-31.03.2030) and 11291 (previous certificate, to 31.03.2026) merged. Dates from 11252, contacts from 11291, scope from the newest annex of both

## Annex versions (12)

- 1 ОСС Emergency Certification OOD (ИМЪРДЖЪНСИ СЕРТИФИКЕЙШЪН ООД): BG annex has no order number or date in its header; taken as issued with the certificate (2025-03-26)
- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД): BG annex has no order number or date in its header; taken as issued with the certificate (2026-10-27)
- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД): read BG order ? of 2026-10-27 (entry 11091); older: EN A 263 of 2025-07-30 (entry 11091)
- 6 ОСС OTC Bulgaria EOOD (ОТС БЪЛГАРИЯ ЕООД): read BG A 60 of 2026-02-23 (entry 11013); older: EN A 424 of 2024-11-12 (entry 11013)
- 14 ОСС Verification OOD (ВЕРИФИКАЦИЯ ООД): read BG A 96 of 2026-03-30 (entry 10538); older: EN A 163 of 2024-04-26 (entry 10538)
- 8 ОСС MG Global OOD (Ем Джи Глобал ООД): BG annex has no order number or date in its header; taken as issued with the certificate (2026-06-01)
- 8 ОСС MG Global OOD (Ем Джи Глобал ООД): read BG order ? of 2026-06-01 (entry 11259); older: EN A 464 of 2024-12-06 (entry 11259)
- 13 ОСС Dedal - Attestation and Certification OOD (ДЕДАЛ - ОЦЕНЯВАНЕ И СЕРТИФИКАЦИЯ ООД): read BG A 126 of 2026-04-29 (entry 10511); older: EN A 275 of 2024-07-12 (entry 10511)
- 18 ОСС INCERT EOOD (ИНСЕРТ ЕООД): read BG A 411 of 2025-12-22 (entry 11261); older: EN A 128 of 2024-04-01 (entry 11261)
- 10 ОСС CSB EOOD (СИ ЕС БИ ЕООД): read BG A 313 of 2026-09-28 (entry 10423); older: EN A 153 of 2025-05-02 (entry 10423)
- 4 ОСС National Institute for Research and Certification EOOD (НАЦИОНАЛЕН ИНСТИТУТ ЗА ИЗСЛЕДВАНИЯ И СЕРТИФИКАЦИЯ ЕООД): read BG A 54 of 2026-02-18 (entry 11268); older: EN A 8 of 2025-01-20 (entry 11268)
- 17 ОСС Q-Aid Europe EOOD (КЮ-ЕИД ЮРЪП ЕООД): read BG A 102 of 2026-04-01 (entry 11252); older: EN A 290 of 2023-07-20 (entry 11252), EN A 216 of 2024-05-31 (entry 11291), BG A 241 of 2022-03-31 (entry 11291)

## Draft EA mappings (check these) (9)

- 1 ОСС Emergency Certification OOD (ИМЪРДЖЪНСИ СЕРТИФИКЕЙШЪН ООД) ISO 22000: categories C, E -> EA 3;30
- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД) ISO 22000: categories C, D, E, F, G, I, K -> EA 3;7;12-15;17;29-31
- 6 ОСС OTC Bulgaria EOOD (ОТС БЪЛГАРИЯ ЕООД) ISO 22000: categories A, B, C -> EA 1;3
- 7 ОСС TÜV Rheinland Bulgaria EOOD (ТЮФ РЕЙНЛАНД БЪЛГАРИЯ ЕООД) ISO 22000: categories A, B, C, D, F, G, I, K -> EA 1;3;7;12-15;17;29;31
- 8 ОСС MG Global OOD (Ем Джи Глобал ООД) ISO 22000: categories A, B, C, D, E, F, G, H, I, J, K -> EA 1;3;7;12-15;17-18;29-31;35
- 13 ОСС Dedal - Attestation and Certification OOD (ДЕДАЛ - ОЦЕНЯВАНЕ И СЕРТИФИКАЦИЯ ООД) ISO 22000: categories A, C, D, E, F, G, H, I -> EA 1;3;7;14-15;17;29-31;35
- 18 ОСС INCERT EOOD (ИНСЕРТ ЕООД) ISO 22000: categories E, F, G -> EA 29-31
- 5 ОСС TÜV NORD Bulgaria EOOD (ТЮФ НОРД БЪЛГАРИЯ ЕООД) ISO 22000: categories C, D, E, F, G, I -> EA 3;7;14-15;17;29-31
- 4 ОСС National Institute for Research and Certification EOOD (НАЦИОНАЛЕН ИНСТИТУТ ЗА ИЗСЛЕДВАНИЯ И СЕРТИФИКАЦИЯ ЕООД) ISO 22000: categories A, B, C, D, E, F, G, H, I, K -> EA 1;3;7;12-15;17;29-31;35

## Conditionally granted (critical) codes (7)

- 3 ОСС ISO 45001: EA 1;6;23
- 10 ОСС ISO 9001: EA 22
- 15 ОСС ISO 14001: EA 1;5
- 15 ОСС ISO 45001: EA 1
- 17 ОСС ISO 9001: EA 12;15
- 17 ОСС ISO 14001: EA 12
- 17 ОСС ISO 45001: EA 12

## Limited scopes (55)

- 1 ОСС ISO 9001: EA 1-3;8;16-19;23;31-32;35;38-39
- 1 ОСС ISO 14001: EA 1-3;8;16-19;23;31-32;35;38-39
- 1 ОСС ISO 45001: EA 1-3;8;16-19;23;31-32;35;38-39
- 9 ОСС ISO 9001: EA 2;18;22;38
- 9 ОСС ISO 14001: EA 2;18;22;35;38
- 9 ОСС ISO 45001: EA 2;18;22;35;38
- 12 ОСС ISO 9001: EA 17-18;29;31;34-35
- 12 ОСС ISO 14001: EA 17-18;29;31;34-35
- 12 ОСС ISO 45001: EA 17-18;29;31;34-35
- 6 ОСС ISO 9001: EA 1-4;18;23;29;31-33;35;39
- 6 ОСС ISO 14001: EA 1-4;8;18;23;29;31-33;35
- 6 ОСС ISO 45001: EA 1-4;8;18;23;29;31-33;35
- 11 ОСС ISO 9001: EA 1-3;17-19;22-23;31;34-35;38-39
- 11 ОСС ISO 14001: EA 2;17-19;22-23;29;31-32;34-35;39
- 11 ОСС ISO 45001: EA 2;17-19;22-23;31-32;34-35;39
- 7 ОСС ISO 9001: EA 3;8;23;29;31-32;35;38-39
- 7 ОСС ISO 14001: EA 2-3;18;23;29;31;33-35;39
- 7 ОСС ISO 45001: EA 1;8;18;29;31;33-35;39
- 14 ОСС ISO 9001: EA 2-3;8;16;18;20;22;29;31-32;34-35;38-39
- 14 ОСС ISO 14001: EA 2-3;8;16;18;20;22;29;31-32;34-35;39
- 14 ОСС ISO 45001: EA 2-3;8;16;18;20;22;29;31-32;34-35;38-39
- 8 ОСС ISO 9001: EA 3;23;29;32;35;38
- 8 ОСС ISO 14001: EA 22-23;29;32;35;38
- 8 ОСС ISO 45001: EA 17;22-23;29;32;35;38
- 20 ОСС ISO 9001: EA 34
- 20 ОСС ISO 14001: EA 34
- 20 ОСС ISO 45001: EA 34
- 3 ОСС ISO 9001: EA 1;8;17-18;23;29;33-35;39
- 3 ОСС ISO 14001: EA 17-18;29;33-35;39
- 3 ОСС ISO 45001: EA 1;8;17-18;23;29;33-35;39
- 13 ОСС ISO 9001: EA 3;18;23
- 13 ОСС ISO 14001: EA 3;18;23
- 13 ОСС ISO 45001: EA 3;7;18;23
- 18 ОСС ISO 9001: EA 1-3;8;18;23;39
- 18 ОСС ISO 14001: EA 2-3;8;18;23;39
- 18 ОСС ISO 45001: EA 2-3;8;18;23;39
- 10 ОСС ISO 9001: EA 2-4;8;18;21;23;29;32;38-39
- 10 ОСС ISO 14001: EA 2-4;8;18;21;23;29;32;38-39
- 10 ОСС ISO 45001: EA 2-4;8;18;21;23;29;32;38-39
- 2 ОСС ISO 9001: EA 18;35;38
- 2 ОСС ISO 14001: EA 18;35
- 2 ОСС ISO 45001: EA 18;21;35;38
- 5 ОСС ISO 9001: EA 1-4;17-18;29;31-32;34-35;38-39
- 5 ОСС ISO 14001: EA 1-4;17-18;22;27;29;31-32;34-35;39
- 5 ОСС ISO 45001: EA 1-4;17-18;22;27;29;31-32;34-35;39
- 4 ОСС ISO 9001: EA 1-3;8;18;22-23;31;33-35;38-39
- 4 ОСС ISO 14001: EA 1-3;8;18;22-23;31;33-35;38-39
- 4 ОСС ISO 45001: EA 1-3;8;18;22-23;31;33-35;38-39
- 15 ОСС ISO 9001: EA 1-2;4;8;18;31;33-35;38-39
- 15 ОСС ISO 14001: EA 1-2;4;8;18;31;33-35;38-39
- 15 ОСС ISO 45001: EA 1-2;4;8;18;31;33-35;38-39
- 17 ОСС ISO 9001: EA 4;8;18;29;31-33;35;38-39
- 17 ОСС ISO 14001: EA 4;8;18;29;31-33;35;38-39
- 17 ОСС ISO 45001: EA 4;8;18;29;31-33;35;38-39
- 19 ОСС ISO 9001: EA 1

## Bulgarian and English annexes differ (4)

- 7 ОСС TÜV Rheinland Bulgaria EOOD (ТЮФ РЕЙНЛАНД БЪЛГАРИЯ ЕООД), A 146 (BG used): ISO 14001: BG 1-7;9-10;12;14-19;22-31;33-36;39 / EN 18-19;22-31;33-36;39; ISO 45001: BG 1-2;4;6-8;12;14-19;24-31;33-37;39 / EN 1-2;4;6-8;12-19;24-31;33-37;39
- 2 ОСС SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД), A 197 (BG used): ISO 9001: BG 1-10;12-20;22-25;27-39 / EN 1-10;12-16;18-20;22-23;25;27-39
- 5 ОСС TÜV NORD Bulgaria EOOD (ТЮФ НОРД БЪЛГАРИЯ ЕООД), A 135 (BG used): ISO 9001: BG 1-7;12;14-19;23;28-29;31-39 / EN 1-7;9;12;14;16;19;23;28-29;31-39; ISO 14001: BG 1-7;12;14-19;22-23;27-29;31-37;39 / EN 1-7;12;14;18-19;22-23;27-29;31-37;39; ISO 45001: BG 1-7;12;14-19;22-24;27-29;31-37;39 / EN 1-7;12;14;16;18-19;22;24;27-29;31-36;39
- 15 ОСС Certification and Inspection Bulgaria OOD (СЕРТИФИКАЦИЯ И ИНСПЕКЦИЯ БЪЛГАРИЯ ООД), A 101 (BG used): ISO 9001: BG 1-6;8-9;12;14-19;23-24;28-39 / EN 1-9;12;14-16;18-19;23-24;28-39; ISO 14001: BG 1-6;8-9;12;14-19;23-24;28-39 / EN 1-9;12;14-16;18-19;23-24;28-39

## Annexes without a sector table (recorded as ALL) (24)

- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД) ISO/IEC 27001
- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД) ISO 39001
- 9 ОСС Alpha Quality Certification EOOD (Алфа Куолити Сертификация ЕООД) ISO 37001
- 12 ОСС NGN OOD (ЕН ДЖИ ЕН ООД) ISO 39001
- 6 ОСС OTC Bulgaria EOOD (ОТС БЪЛГАРИЯ ЕООД) ISO/IEC 27001
- 6 ОСС OTC Bulgaria EOOD (ОТС БЪЛГАРИЯ ЕООД) ISO 39001
- 6 ОСС OTC Bulgaria EOOD (ОТС БЪЛГАРИЯ ЕООД) ISO 37001
- 14 ОСС Verification OOD (ВЕРИФИКАЦИЯ ООД) ISO/IEC 27001
- 8 ОСС MG Global OOD (Ем Джи Глобал ООД) ISO/IEC 27001
- 8 ОСС MG Global OOD (Ем Джи Глобал ООД) ISO 39001
- 13 ОСС Dedal - Attestation and Certification OOD (ДЕДАЛ - ОЦЕНЯВАНЕ И СЕРТИФИКАЦИЯ ООД) ISO/IEC 27001
- 13 ОСС Dedal - Attestation and Certification OOD (ДЕДАЛ - ОЦЕНЯВАНЕ И СЕРТИФИКАЦИЯ ООД) ISO 39001
- 18 ОСС INCERT EOOD (ИНСЕРТ ЕООД) ISO/IEC 27001
- 18 ОСС INCERT EOOD (ИНСЕРТ ЕООД) ISO 39001
- 18 ОСС INCERT EOOD (ИНСЕРТ ЕООД) ISO 37001
- 10 ОСС CSB EOOD (СИ ЕС БИ ЕООД) ISO/IEC 27001
- 10 ОСС CSB EOOD (СИ ЕС БИ ЕООД) ISO 39001
- 2 ОСС SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД) ISO/IEC 27001
- 2 ОСС SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД) ISO 39001
- 5 ОСС TÜV NORD Bulgaria EOOD (ТЮФ НОРД БЪЛГАРИЯ ЕООД) ISO 39001
- 4 ОСС National Institute for Research and Certification EOOD (НАЦИОНАЛЕН ИНСТИТУТ ЗА ИЗСЛЕДВАНИЯ И СЕРТИФИКАЦИЯ ЕООД) ISO/IEC 27001
- 15 ОСС Certification and Inspection Bulgaria OOD (СЕРТИФИКАЦИЯ И ИНСПЕКЦИЯ БЪЛГАРИЯ ООД) ISO/IEC 27001
- 17 ОСС Q-Aid Europe EOOD (КЮ-ЕИД ЮРЪП ЕООД) ISO/IEC 27001
- 19 ОСС Smart Certification EOOD (СМАРТ СЕРТИФИКЕЙШЪН ЕООД) ISO/IEC 27001

## Excluded schemes (2)

- 8 ОСС MG Global OOD (Ем Джи Глобал ООД): PEFC sustainable forest management, not an international management-system standard — "8. Сертификация на Системи за устойчиво управление на горите съгласно стандарт PEFC BG ST 1002:2024, PEFC BS 06:2021, PEFC BS 04:2021, PEFC "
- 5 ОСС TÜV NORD Bulgaria EOOD (ТЮФ НОРД БЪЛГАРИЯ ЕООД): PAS 24000 / FSSC 24000 social management, not an international management-system standard — "Сертификация на системи за социално управление, съгласно изискванията на PAS 24000:2022, FSSC 24000 версия 1 от 2022 година и FSSC 24000 доп"

## Contacts and names (9)

- Emergency Certification OOD (ИМЪРДЖЪНСИ СЕРТИФИКЕЙШЪН ООД): annex gives no address; address is the register's office city (Plovdiv, Bulgaria)
- 10447: certificate number '11 OCC' typed in Latin letters; written as '11 ОСС'
- TÜV Rheinland Bulgaria EOOD (ТЮФ РЕЙНЛАНД БЪЛГАРИЯ ЕООД): register lists 'office@bg.tuv.com; Konstantin.Krastev@bg.tuv.com'; kept office@bg.tuv.com
- MG Global OOD (Ем Джи Глобал ООД): annex gives no address; address is the register's office city (Sofia, Bulgaria)
- CSB EOOD (СИ ЕС БИ ЕООД): annex gives no address; address is the register's office city (Sofia, Bulgaria)
- SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД): phone '02 9 10 15' is not a complete Bulgarian number; left empty
- SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД): register lists 'albena.amzina@sgs.com; sgs_bulgaria@sgs.com'; kept sgs_bulgaria@sgs.com
- SGS Bulgaria EOOD (СЖС БЪЛГАРИЯ ЕООД): annex gives no address; address is the register's office city (Sofia, Bulgaria)
- 2 ОСС ISO 9001: NACE cells for EA 17;24 cite Regulation (EU) 333/2011, 715/2013; kept in the note
