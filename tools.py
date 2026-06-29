import os
import sqlite3
import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List
import re
import requests
import random
from urllib.parse import urlencode

from dotenv import load_dotenv
load_dotenv()


DB_PATH = "carduka_market.db"

def query_historical_sales(make: str, model: str, year: int, mileage: int) -> Dict[str, Any]:
    """Queries internal historical DB and returns basic statistical ranges."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Target a comparable local window (+/- 1 year and +/- 30k km mileage spread)
    query = """
        SELECT sale_price, condition_grade FROM historical_sales 
        WHERE LOWER(make) = LOWER(?) 
          AND LOWER(model) = LOWER(?)
          AND year BETWEEN ? AND ?
          AND mileage BETWEEN ? AND ?
    """
    params = (make, model, year - 1, year + 1, max(0, mileage - 30000), mileage + 30000)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {"error": f"No historical internal data matched for {year} {make} {model} within target boundaries."}
        
    prices = [row[0] for row in rows]
    return {
        "count": len(prices),
        "avg_price": sum(prices) / len(prices),
        "min_price": min(prices),
        "max_price": max(prices),
        "samples": rows
    }


def scrape_cars45_listings(make: str, model: str, year:int) -> List[Dict[str, Any]]:
    """
    Scrapes live car records off cars45.co.ke using the requested query route.
    Raises explicit RuntimeError on scraping error to execute your rigid fallback rule.
    """
    search_query = f"{make} {model} {year}".strip().replace(" ", "+")
    target_url = f"https://www.cars45.co.ke/listing?query={search_query}"

    user_agents_list = [
        'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.83 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36'
    ]

    # SCRAPEOPS_API_KEY = os.environ.get("SCRAPEOPS_API_KEY")
    # if not SCRAPEOPS_API_KEY:
    #     print("⚠️ Missing SCRAPEOPS_API_KEY env variable! Skipping live scrape.")
    #     return []

    # payload = {
    #     "api_key": SCRAPEOPS_API_KEY,
    #     "url": target_url,
    #     'bypass': 'cloudflare_level_1'
    # }
    # proxy_url = f"https://proxy.scrapeops.io/v1/?{urlencode(payload)}"

    # proxies = {
    #     "http": "http://sbrdipaf:9xamdocqqt1p@31.59.20.176:6754",
    #     "https": "http://sbrdipaf:9xamdocqqt1p@31.59.20.176:6754",
    # }
    
    try:
        response = requests.get(target_url, headers={'User-Agent': random.choice(user_agents_list)}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Cars45 webscraping fallback failed: HTTP status code {response.status_code}")
            
        soup = BeautifulSoup(response.text, "html.parser")
        listings = []
        
        # FIX: Target the exact anchor element cards found on Cars45
        cards = soup.find_all("a", class_="car-feature")
        
        if not cards:
            raise RuntimeError("Cars45 webscraping fallback failed: DOM structure altered or anti-bot challenge encountered.")
            
        # Parse and cap at the top 5 items for lean state context
        for card in cards[:5]: 
            name_el = card.find("p", class_="car-feature__name")
            if not name_el:
                continue
            title_text = name_el.get_text(strip=True)
            
            # Guardrail: Ensure it actually matches the requested vehicle manufacturer & model
            if make.lower() not in title_text.lower() or model.lower() not in title_text.lower():
                continue
                
            # Extract and parse pricing cleanly
            amount_el = card.find("p", class_="car-feature__amount")
            extracted_price = "Inquire for price"
            if amount_el:
                price_text = amount_el.get_text(strip=True)
                # Pull raw digits out of "KSh 5,249,999" -> 5249999
                digits = re.sub(r"\D", "", price_text)
                if digits:
                    extracted_price = f"KSh {int(digits):,}"

            condition = "Unknown"
            
            other_items = card.find_all("span", class_="car-feature__others__item")
            for item in other_items:
                item_text = item.get_text(strip=True)
                
                # Capture condition metrics (e.g., "Foreign Used" or "Local Used")
                if "used" in item_text.lower() or "new" in item_text.lower():
                    condition = item_text
            
            # Build the clean state object map
            listings.append({
                "raw_details": title_text,
                "extracted_price": extracted_price,
                "condition": condition
            })
            
        return listings
        
    except Exception as e:
        # Wrap cleanly to trigger the strict fallback constraint
        raise RuntimeError(f"Live market scraping tool error: {str(e)}")
    

def extract_text(content) -> str:
    # Safely extract text from Gemini response content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type") == "text"
        ).strip()
    return str(content).strip()
