#!/usr/bin/env python3
"""
Local PDF Certificate Batch Parser & SQL Seed Generator
Scans a local directory of downloaded DPA PDF certificates and generates 
a PostgreSQL migration script matching the CertiFind 02-seed.sql structure.
"""

import os
import re
import logging
from datetime import datetime
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configure your local folder containing the downloaded PDF certificates
LOCAL_PDF_DIR = "./certificates"  # <-- Change this to your actual folder path if different

class LocalCertificateParser:
    def __init__(self, pdf_dir):
        self.pdf_dir = pdf_dir

    def parse_all_pdfs(self):
        if not os.path.exists(self.pdf_dir):
            logger.error(f"Directory not found: {self.pdf_dir}. Please place your PDFs here.")
            return []

        pdf_files = [f for f in os.listdir(self.pdf_dir) if f.lower().endswith('.pdf')]
        logger.info(f"Found {len(pdf_files)} PDF certificates in {self.pdf_dir}.")
        
        parsed_records = []

        for filename in pdf_files:
            filepath = os.path.join(self.pdf_dir, filename)
            logger.info(f"Parsing: {filename}")
            
            try:
                reader = PdfReader(filepath)
                text = ""
                # Read first 2 pages where header metadata, company name, and cert numbers reside
                for page in reader.pages[:2]:
                    text += page.extract_text() or ""

                record = self._extract_metadata(text, filename)
                if record:
                    parsed_records.append(record)
            except Exception as e:
                logger.error(f"Failed to parse {filename}: {e}")

        logger.info(f"Successfully extracted metadata from {len(parsed_records)} certificates.")
        return parsed_records

    def _extract_metadata(self, text, filename):
        # 1. Extract Certificate / Registration Number (e.g., CS 007, CN 018, LT 128)
        cert_match = re.search(r'\b(CS\s*\d{3}|CN\s*\d{3}|LT\s*\d{3}|TI\s*\d{3}|LM\s*\d{3}|LK\s*\d{2})\b', text, re.IGNORECASE)
        cert_number = cert_match.group(1).replace(" ", " ").upper() if cert_match else filename.split('_')[0]

        # 2. Extract Company Name (Looking for common Albanian legal suffixes)
        name_match = re.search(r'([A-Z0-9\s,\.\-\"“„‘’"]+?(?:sh\.p\.k\.|Sh\.A\.|GmbH|shpk))\b', text, re.IGNORECASE)
        company_name = name_match.group(1).strip('"„“‘’ ') if name_match else filename.replace('.pdf', '').replace('_', ' ')

        # 3. Detect Accreditation Standard based on text clues
        standard = "ISO/IEC 17021-1" # Default management systems
        if "17024" in text:
            standard = "ISO/IEC 17024"
        elif "17025" in text or "Laborator Testues" in text:
            standard = "ISO/IEC 17025"
        elif "50001" in text or "50003" in text:
            standard = "ISO 50003"
        elif "27001" in text:
            standard = "ISO/IEC 27006"

        return {
            "name": company_name,
            "country": "Albania",
            "certificate_number": cert_number,
            "standard": standard,
            "filename": filename
        }

    def generate_sql_seed(self, records, output_file="dpa_local_certificates_seed.sql"):
        logger.info(f"Generating PostgreSQL seed file: {output_file}")
        
        sql_lines = [
            "-- Auto-generated Local DPA Albania Seed Script",
            "-- Compatible with CertiFind 02-seed.sql schema specification",
            "BEGIN;",
            ""
        ]

        # 1. Insert Certification Bodies
        sql_lines.append("-- Certification Bodies Insert")
        seen_names = set()
        for r in records:
            name = r['name'].replace("'", "''")
            if name in seen_names:
                continue
            seen_names.add(name)
            
            sql_lines.append(
                f"INSERT INTO certification_bodies (name, country, phone, email, website, address) "
                f"VALUES ('{name}', 'Albania', NULL, NULL, NULL, 'Tiranë, Albania') "
                f"ON CONFLICT (name) DO NOTHING;"
            )

        sql_lines.append("")
        sql_lines.append("-- Accreditations Insert")
        
        # 2. Insert Accreditations
        for r in records:
            name = r['name'].replace("'", "''")
            cert_no = r['certificate_number']
            std = r['standard']
            filename = r['filename']
            
            sql_lines.append(
                f"INSERT INTO accreditations (certification_body_id, accreditation_body_id, accreditation_standard, certificate_number, status, issue_date, expiry_date, proof_url) "
                f"SELECT cb.id, ab.id, '{std}', '{cert_no}', 'ACTIVE', '2026-01-01', '2030-01-01', 'https://www.dpa.gov.al' "
                f"FROM certification_bodies cb, accreditation_bodies ab "
                f"WHERE cb.name = '{name}' AND ab.code = 'DPA' "
                f"ON CONFLICT (certificate_number) DO NOTHING;"
            )

        sql_lines.append("")
        sql_lines.append("COMMIT;")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sql_lines))
            
        logger.info(f"Seed generation completed successfully: {output_file}")

if __name__ == "__main__":
    # Point this to the folder where your PDF certificates are stored
    TARGET_FOLDER = "./certificates" # <-- Change to your folder path if needed
    
    parser = LocalCertificateParser(TARGET_FOLDER)
    extracted_data = parser.parse_all_pdfs()
    
    if extracted_data:
        parser.generate_sql_seed(extracted_data)
    else:
        logger.warning("No records were extracted. Verify your PDF folder path.")