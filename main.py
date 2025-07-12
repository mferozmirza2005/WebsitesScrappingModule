from playwright.async_api import async_playwright, BrowserContext, Page
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm
from pathlib import Path
import asyncio
import orjson
import logging
import random
import json
import html
import sys
import re
import io

# === CONFIGURATION === #
SCRAPER_SITES = {
    "beercartel": {
        "enabled": True,
        "url": "https://beercartel.com.au/collections/beer",
    },
    "liquorland": {
        "enabled": True,
        "url": "https://www.liquorland.com.au/api/products/ll/nsw/beer?page=page_number&sort=&show=100&facets=craft",
    },
    "firstchoiceliquor": {
        "enabled": True,
        "url": "https://www.firstchoiceliquor.com.au/api/products/fc/nsw/beer?page=page_number&sort=&show=100&facets=craft",
    },
}

PRODUCTS_BUFFER = []
OUTPUT_JSON = Path("output.json")
OUTPUT_JSON_STARTED = False
PRODUCT_COUNT = 0

sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")


# === LOGGING SETUP === #
class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        TqdmLoggingHandler(),
    ],
)


# === UTILITIES === #
async def goto_with_retry(page: Page, url: str, retries: int = 3, base_delay: int = 5):
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return
        except Exception as e:
            logging.warning(f"⚠️ Retry {attempt}/{retries} for {url}: {e}")
            if attempt < retries:
                delay = base_delay * attempt + random.uniform(0, 2)
                logging.info(f"⏳ Waiting {delay:.2f}s before retry...")
                await asyncio.sleep(delay)
            else:
                logging.error(f"❌ Failed to load {url} after {retries} attempts.")
                raise


async def store_product(product: dict):
    PRODUCTS_BUFFER.append(product)
    OUTPUT_JSON.write_bytes(orjson.dumps(PRODUCTS_BUFFER, option=orjson.OPT_INDENT_2))


# === SCRAPER IMPLEMENTATIONS === #
async def scrape_beercartel(
    context: BrowserContext, base_url: str, total_pages: int = 3
):
    logging.info("Scraping BeerCartel")
    page = await context.new_page()

    try:
        if total_pages <= 0:
            await goto_with_retry(page, base_url)
            await page.wait_for_timeout(3000)
            soup = BeautifulSoup(await page.content(), "lxml")
            for link in soup.select("a[href*='?page=']"):
                try:
                    num = int(link.text.strip())
                    total_pages = max(total_pages, num)
                except ValueError:
                    continue
            logging.info(f"📄 Total pages found: {total_pages}")

        for page_number in tqdm(
            range(1, total_pages + 1), desc="BeerCartel", unit="page"
        ):
            url = f"{base_url}?page={page_number}"
            logging.info(f"🌐 BeerCartel Page {page_number}: {url}")
            await goto_with_retry(page, url)
            await page.wait_for_timeout(3000)
            soup = BeautifulSoup(await page.content(), "lxml")

            script_tag = next(
                (
                    s
                    for s in soup.find_all("script")
                    if "addCachedProductData" in s.text
                ),
                None,
            )
            if not script_tag:
                logging.warning(f"⚠️ No product JSON found on page {page_number}")
                continue

            match = re.search(
                r"addCachedProductData\((\[.*?\])\);", script_tag.string, re.DOTALL
            )
            if not match:
                logging.warning(
                    f"⚠️ Failed to extract JSON from script tag on page {page_number}"
                )
                continue

            product_data = json.loads(html.unescape(match.group(1)))

            for p in product_data:
                clean_desc = await page.evaluate(
                    "desc => { const div = document.createElement('div'); div.innerHTML = desc; return div.innerText; }",
                    p.get("description", ""),
                )
                product = {
                    "source": "beercartel",
                    "id": p.get("id"),
                    "name": p.get("title"),
                    "brand": p.get("vendor"),
                    "description": clean_desc,
                    "price": p.get("price", 0) / 100,
                    "member_price": None,
                    "non_member_price": p.get("price", 0) / 100,
                    "discount": None,
                    "volume_ml": None,
                    "unit": None,
                    "unit_price": p.get("price", 0) / 100,
                    "rating_average": None,
                    "rating_total": None,
                    "image_urls": [f"https:{img}" for img in p.get("images", [])],
                    "product_url": f"{base_url}/{p.get('handle', '')}",
                    "variants": [
                        {
                            "variant_id": v.get("id"),
                            "title": v.get("title"),
                            "sku": v.get("sku"),
                            "price": v.get("price", 0) / 100,
                            "available": v.get("available"),
                        }
                        for v in p.get("variants", [])
                    ],
                }
                await store_product(product)

    except Exception:
        logging.exception("❌ Error in BeerCartel scraper")


async def scrape_generic_json_api(context: BrowserContext, base_url: str, source: str):
    logging.info(f"Scraping {source.title()} (via JSON API)")
    page = await context.new_page()

    try:
        url = base_url.replace("page=page_number", "page=1")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        data = json.loads(await page.locator("pre").text_content())
        products = data.get("products", [])
        total_pages = data.get("meta", {}).get("page", {}).get("total", 1)

        logging.info(f"📄 Total {source.title()} pages: {total_pages}")

        async def process_product(item):
            product = {
                "source": source,
                "id": item.get("id"),
                "name": item.get("name"),
                "brand": item.get("brand"),
                "description": None,
                "price": item.get("price", {}).get("current"),
                "member_price": item.get("price", {}).get("memberOnlyPrice"),
                "non_member_price": item.get("price", {}).get("current"),
                "discount": (
                    round(item["price"]["normal"] - item["price"]["current"], 2)
                    if item["price"].get("normal", 0) > item["price"].get("current", 0)
                    else 0.0
                ),
                "volume_ml": item.get("volumeMl"),
                "unit": item.get("unitOfMeasureLabel"),
                "unit_price": item.get("price", {}).get("current"),
                "rating_average": item.get("ratings", {}).get("average"),
                "rating_total": item.get("ratings", {}).get("total"),
                "image_urls": [
                    f"https://www.{source}.com.au{item.get('image', {}).get('heroImage')}"
                ],
                "product_url": f"https://www.{source}.com.au{item.get('productUrl')}",
                "variants": [],
            }
            await store_product(product)

        for item in products:
            await process_product(item)

        for page_number in tqdm(
            range(2, total_pages + 1), desc=source.title(), unit="page"
        ):
            url = base_url.replace("page=page_number", f"page={page_number}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)
            data = json.loads(await page.locator("pre").text_content())
            for item in data.get("products", []):
                await process_product(item)

    except Exception:
        logging.exception(f"❌ Failed to scrape {source.title()}")


# === MAIN SCRAPER RUNNER === #
async def run_scraper():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            color_scheme="light",
        )

        if SCRAPER_SITES["beercartel"]["enabled"]:
            await scrape_beercartel(context, SCRAPER_SITES["beercartel"]["url"])

        for key in ("liquorland", "firstchoiceliquor"):
            if SCRAPER_SITES[key]["enabled"]:
                await scrape_generic_json_api(
                    context, SCRAPER_SITES[key]["url"], source=key
                )

        await browser.close()


# === ENTRY POINT === #
if __name__ == "__main__":
    try:
        asyncio.run(run_scraper())
    except KeyboardInterrupt:
        logging.warning("🛑 Scraper interrupted!")
        sys.exit(0)
