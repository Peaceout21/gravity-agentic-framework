import logging
import uuid
import datetime
import json
from core.tools.market_provider import MarketProvider
from core.tools.edgar_client import FilingRecord
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional, List
import os

logger = logging.getLogger(__name__)

# This provider is responsible for fetching local filings. For the POC, we will simulate
# downloading a PDF but actually returning predetermined text, mimicking OCR output.
class SeaProvider(MarketProvider):
    def __init__(self, timeout_seconds=20):
        self.timeout_seconds = timeout_seconds
        self.market_code = "SEA_LOCAL"

    def get_latest_events(self, tickers):
        # type: (list) -> list
        # Simulate polling an aggregator or SEC equivalent for SEA
        results = []
        for ticker in tickers:
            logger.info(f"SeaProvider polling for {ticker}...")
            # Simulate finding an IDR financial report 
            record = FilingRecord(
                ticker=ticker,
                accession_number=f"SEA-{ticker}-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
                filing_url=f"https://sea-exchange.local/{ticker}_Q3_2023.pdf", # simulated URL
                filing_type="Q3",
                market="SEA_LOCAL",
                exchange="IDX",
                issuer_id=ticker,
                source="idx_aggregator",
                source_event_id=str(uuid.uuid4()),
                document_type="Q3_Report",
                currency="IDR",
                metadata={"language": "id", "filing_date": datetime.datetime.now().strftime('%Y-%m-%d')}
            )
            results.append(record)
        return results

    def get_document_text(self, record):
        # type: (FilingRecord) -> str
        logger.info(f"SeaProvider simulating OCR text extraction for {record.filing_url}")
        
        # In a real scenario, this would download the PDF and use an OCR service or Gemini Vision.
        # Here we use the snippet from our successful POC script.
        simulated_text = """
        Laporan Kinerja Keuangan Kuartal III 2023 - PT Bank Rakyat Bahagia Tbk.
        
        Pendapatan operasional perusahaan tumbuh secara solid, mencatatkan peningkatan sebesar 12.5% dibandingkan tahun lalu (Year-over-Year). 
        Laba bersih pada kuartal ini tercatat sebesar Rp 15.5 triliun. Laba per saham (EPS) mencapai Rp 250.
        
        Prospek Manajemen:
        Manajemen memproyeksikan pertumbuhan kredit yang kuat di sektor UMKM akan terus menjadi pendorong utama pada kuartal keempat. 
        Namun, kami tetap mewaspadai risiko pengetatan likuiditas global dan fluktuasi nilai tukar Rupiah terhadap Dolar AS yang dapat menekan margin bunga bersih (NIM).
        Kami menargetkan pertumbuhan pendapatan single-digit tinggi untuk sisa tahun ini.
        """
        return simulated_text
