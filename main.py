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
    context: BrowserContext, base_url: str, total_pages: int = 0
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
                    "product_url": f"https://beercartel.com.au/products/{p.get('handle', '')}",
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

                await goto_with_retry(page, product["product_url"])
                await page.wait_for_timeout(3000)

                product_content = await page.content()
                product_soup = BeautifulSoup(product_content, "lxml")

                if product_soup.find("span", class_="rating-value"):
                    rating_value = product_soup.select_one("span.rating-value")
                    if rating_value:
                        product["rating_average"] = float(rating_value.text.strip())
                    else:
                        product["rating_average"] = None

                    rating_total = product_soup.select_one("span.rating-count")

                    if rating_total:
                        product["rating_total"] = int(
                            rating_total.text.split(" ")[0].strip()
                        )
                    else:
                        product["rating_total"] = None
                elif product_soup.find("span", class_="jdgm-prev-badge__stars"):
                    rating_value = product_soup.select_one(
                        "span.jdgm-prev-badge__stars"
                    )

                    if rating_value:
                        product["rating_average"] = float(
                            rating_value.attrs.get("data-score", "0.0").strip()
                        )
                    else:
                        product["rating_average"] = None

                    rating_total = product_soup.select_one(
                        "span.jdgm-prev-badge__text"
                    )
                    if rating_total:
                        product["rating_total"] = int(
                            rating_total.text.split(" ")[0].strip()
                        )
                    else:
                        product["rating_total"] = None

                await store_product(product)

    except Exception:
        logging.exception("❌ Error in BeerCartel scraper")


async def scrape_generic_json_api(context: BrowserContext, base_url: str, source: str):
    logging.info(f"Scraping {source.title()} (via JSON API)")
    page = await context.new_page()

    base_api = {
        "liquorland": "https://www.liquorland.com.au/api/products/ll/nsw/beer",
        "firstchoiceliquor": "https://www.firstchoiceliquor.com.au/api/products/fc/nsw/beer",
    }[source]

    try:
        url = base_url.replace("page=page_number", "page=1")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        data = json.loads(await page.locator("pre").text_content())
        total_pages = data.get("meta", {}).get("page", {}).get("total", 1)

        logging.info(f"📄 Total {source.title()} pages: {total_pages}")

        async def process_product(item):
            raw_id = item.get("id", "")
            if not raw_id:
                return

            clean_id = raw_id.split("_")[0] if "_" in raw_id else raw_id
            detail_url = f"{base_api}/{clean_id}?catalogue=1"

            try:
                await page.goto(detail_url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(3000)
                data = json.loads(await page.locator("pre").text_content())
                detail_product = data.get("product", {})

                # Build structured variants
                variants = []
                for variant in detail_product.get("multiUOMPrice", []):
                    volume = variant.get("unitOfMeasureLabel") or variant.get(
                        "unitOfMeasure"
                    )
                    price_info = variant.get("price", {})
                    promo = variant.get("promotion", {})
                    dinkus = promo.get("dinkus", [])

                    discount_text = promo.get("calloutText")
                    if not discount_text and dinkus:
                        discount_text = dinkus[0].get("text")

                    variants.append(
                        {
                            "volume": volume,
                            "non_member_price": price_info.get("current"),
                            "member_price": price_info.get("memberOnlyPrice"),
                            "discount_text": discount_text,
                        }
                    )

                product = {
                    "source": source,
                    "id": detail_product.get("id"),
                    "name": detail_product.get("name"),
                    "brand": detail_product.get("brand"),
                    "description": detail_product.get("description"),
                    "price": detail_product.get("price", {}).get("current"),
                    "member_price": detail_product.get("price", {}).get(
                        "memberOnlyPrice"
                    ),
                    "non_member_price": detail_product.get("price", {}).get("current"),
                    "discount": (
                        round(
                            detail_product["price"]["normal"]
                            - detail_product["price"]["current"],
                            2,
                        )
                        if detail_product["price"].get("normal", 0)
                        > detail_product["price"].get("current", 0)
                        else 0.0
                    ),
                    "volume_ml": detail_product.get("volumeMl"),
                    "unit": detail_product.get("unitOfMeasureLabel"),
                    "unit_price": detail_product.get("price", {}).get("current"),
                    "rating_average": detail_product.get("ratings", {}).get("average"),
                    "rating_total": detail_product.get("ratings", {}).get("total"),
                    "image_urls": (
                        [
                            f"https://www.{source}.com.au{detail_product.get('image', {}).get('heroImage')}"
                        ]
                        if detail_product.get("image")
                        else []
                    ),
                    "product_url": f"https://www.{source}.com.au{detail_product.get('productUrl')}",
                    "variants": variants,
                }

                await store_product(product)
            except Exception as e:
                logging.warning(f"⚠️ Error processing product {raw_id}: {e}")
                return

        for page_number in tqdm(
            range(1, total_pages + 1), desc=source.title(), unit="page"
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
        browser = await p.chromium.launch(headless=False)
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
