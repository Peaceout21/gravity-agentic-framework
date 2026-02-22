import base64
import os
import json
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional, List

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'gravitic-celestial', '.env'))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY or GOOGLE_API_KEY not found in .env")
    exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Simplified MetricSchema identical to core/tools/extraction_engine.py
class FinancialMetrics(BaseModel):
    revenue_growth_yoy: Optional[float] = Field(None, description="Year-over-year revenue growth percentage")
    eps_current_quarter: Optional[float] = Field(None, description="Earnings per share for the reported quarter")
    net_income_millions: Optional[float] = Field(None, description="Net income in millions of USD")

class ManagementGuidance(BaseModel):
    revenue_outlook: Optional[str] = Field(None, description="Management's qualitative/quantitative revenue forecast")
    key_growth_drivers: List[str] = Field(default_factory=list, description="Primary drivers of future growth mentioned")
    risk_factors: List[str] = Field(default_factory=list, description="Specific headwinds or risks identified")

class ExtractedFiling(BaseModel):
    metrics: FinancialMetrics
    guidance: ManagementGuidance
    source_language: str = Field(..., description="The original language of the document")
    currency_used: str = Field(..., description="The original currency used in the document")

async def test_extraction():
    # In a real scenario, this would be downloaded.
    # For the POC, we simulate having the text content of a PDF
    # The prompt instructs Gemini to handle the translation and normalization.
    
    prompt = """
    You are an expert financial analyst. Your task is to read the provided text from a Southeast Asian
    company's financial filing (e.g., an Indonesian quarterly report).
    
    1. Identify the original language and currency used.
    2. Extract key financial metrics (Revenue YoY growth, current EPS, Net Income).
    3. Translate all extracted narrative management guidance into professional English.
    4. Normalize the 'net_income_millions' to USD (Assume 1 USD = 15,500 IDR for this test if IDR is detected). 1 Trillion Rp = 1,000,000 Million Rp. 
    
    Provided Document Text (Simulated Indonesian Bank Q3 Report excerpt):
    
    Laporan Kinerja Keuangan Kuartal III 2023 - PT Bank Rakyat Bahagia Tbk.
    
    Pendapatan operasional perusahaan tumbuh secara solid, mencatatkan peningkatan sebesar 12.5% dibandingkan tahun lalu (Year-over-Year). 
    Laba bersih pada kuartal ini tercatat sebesar Rp 15.5 triliun. Laba per saham (EPS) mencapai Rp 250.
    
    Prospek Manajemen:
    Manajemen memproyeksikan pertumbuhan kredit yang kuat di sektor UMKM akan terus menjadi pendorong utama pada kuartal keempat. 
    Namun, kami tetap mewaspadai risiko pengetatan likuiditas global dan fluktuasi nilai tukar Rupiah terhadap Dolar AS yang dapat menekan margin bunga bersih (NIM).
    Kami menargetkan pertumbuhan pendapatan single-digit tinggi untuk sisa tahun ini.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractedFiling,
            ),
        )
        print("--- Extraction Successful ---")
        print(json.dumps(json.loads(response.text), indent=2))
    except Exception as e:
         print(f"Error during extraction: {e}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
