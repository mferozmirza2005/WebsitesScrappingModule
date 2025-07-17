from playwright.async_api import async_playwright, BrowserContext, Page
from typing import Optional, Dict, Any
from tqdm.asyncio import tqdm
from datetime import datetime
from bs4 import BeautifulSoup
from pathlib import Path
import asyncio
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

if OUTPUT_JSON.exists():
    try:
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            PRODUCTS_BUFFER = json.load(f)
            PRODUCT_COUNT = len(PRODUCTS_BUFFER)
            logging.info(f"📝 Loaded {PRODUCT_COUNT} existing products")
    except Exception as e:
        logging.warning(f"⚠️ Failed to load existing products: {e}")
        PRODUCTS_BUFFER = []

EXISTING_PRODUCT_IDS = {
    (p["source"], p["Product ID"], p.get("Variant URL"))
    for p in PRODUCTS_BUFFER
}

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

def is_product_exists(source: str, product_id: str, variant_url: Optional[str] = None) -> bool:
    """Check if a product already exists in the scraped data."""
    return (source, str(product_id), variant_url) in EXISTING_PRODUCT_IDS


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
    global PRODUCT_COUNT
    PRODUCTS_BUFFER.append(product)
    EXISTING_PRODUCT_IDS.add((
        product["source"],
        product["Product ID"],
        product.get("Variant URL")
    ))
    PRODUCT_COUNT += 1
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(PRODUCTS_BUFFER, f, indent=2, ensure_ascii=False)


def create_standardized_product(
    source: str,
    product_id: str,
    product_url: str,
    name: str,
    brand: str,
    style: Optional[str] = None,
    abv: Optional[float] = None,
    description: Optional[str] = None,
    rating: Optional[float] = None,
    review_count: Optional[int] = None,
    bundle: Optional[str] = None,
    stock: Optional[str] = None,
    non_member_price: Optional[float] = None,
    promo_price: Optional[float] = None,
    discount_price: Optional[float] = None,
    member_price: Optional[float] = None,
    variant_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a standardized product dictionary with all expected fields.
    """
    return {
        "Product ID": product_id,
        "Product URL": product_url,
        "Name": name,
        "Brand": brand,
        "Style": style,
        "ABV": f"{abv}%" if abv else None,
        "Description": description,
        "Rating": rating,
        "Review": review_count,
        "Bundle": bundle,
        "Stock": stock,
        "Non-Member Price": f"${non_member_price:.2f}" if non_member_price else None,
        "Promo Price": f"${promo_price:.2f}" if promo_price else None,
        "Discount Price": f"${discount_price:.2f}" if discount_price else None,
        "Member Price": f"${member_price:.2f}" if member_price else None,
        "Variant URL": variant_url,
        "source": source,
        "created_at": datetime.now().isoformat(),
    }


def extract_abv_from_description(description: str) -> Optional[float]:
    """Extract ABV percentage from description text."""
    if not description:
        return None

    abv_match = re.search(r"ABV:\s*(\d+(?:\.\d+)?)%", description, re.IGNORECASE)
    if abv_match:
        return float(abv_match.group(1))

    patterns = [
        r"ABV\s*(\d+(?:\.\d+)?)%",
        r"(\d+(?:\.\d+)?)%\s*ABV",
        r"(\d+(?:\.\d+)?)%\s*alcohol",
        r"alcohol\s*(\d+(?:\.\d+)?)%",
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return float(match.group(1))

    return None


def extract_style_from_name(name: str, description: str = "") -> Optional[str]:
    """Extract beer style from product name or description."""
    if not name and not description:
        return None

    if description:
        style_match = re.search(r"Style:\s*([^\n\r]+)", description, re.IGNORECASE)
        if style_match:
            style_text = style_match.group(1).strip()
            return style_text

    styles = [
        "IPA",
        "Pale Ale",
        "Stout",
        "Porter",
        "Lager",
        "Pilsner",
        "Wheat Beer",
        "Sour",
        "Saison",
        "Belgian",
        "Amber Ale",
        "Brown Ale",
        "Red Ale",
        "Hazy",
        "NEIPA",
        "Double IPA",
        "Triple IPA",
        "Session IPA",
        "Imperial",
        "Barleywine",
        "Gose",
        "Lambic",
        "Fruited",
        "Sour Ale",
    ]

    if description:
        for style in styles:
            if style.upper() in description.upper():
                return style

    if name:
        name_upper = name.upper()
        for style in styles:
            if style.upper() in name_upper:
                return style

    return None


# === SCRAPER IMPLEMENTATIONS === #
async def scrape_beercartel(
    context: BrowserContext, base_url: str, total_pages: int = 1
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

            script_text = script_tag.get_text() if script_tag else ""
            match = re.search(
                r"addCachedProductData\((\[.*?\])\);", script_text, re.DOTALL
            )
            if not match:
                logging.warning(
                    f"⚠️ Failed to extract JSON from script tag on page {page_number}"
                )
                continue

            product_data = json.loads(html.unescape(match.group(1)))

            for p in product_data:
                product_id = str(p.get("id"))
                variants = p.get("variants", [])
                
                if variants:
                    all_variants_exist = all(
                        is_product_exists(
                            "beercartel",
                            str(variant.get("id", p.get("id"))),
                            f"https://beercartel.com.au/products/{p.get('handle', '')}?variant={variant.get('id')}"
                        )
                        for variant in variants
                    )
                    if all_variants_exist:
                        logging.info(f"⏩ Skipping existing product and variants: {p.get('title')} ({product_id})")
                        continue
                else:
                    if is_product_exists(
                        "beercartel",
                        product_id,
                        f"https://beercartel.com.au/products/{p.get('handle', '')}"
                    ):
                        logging.info(f"⏩ Skipping existing product: {p.get('title')} ({product_id})")
                        continue

                clean_desc = await page.evaluate(
                    "desc => { const div = document.createElement('div'); div.innerHTML = desc; return div.innerText; }",
                    p.get("description", ""),
                )

                abv = extract_abv_from_description(clean_desc)
                style = extract_style_from_name(p.get("title", ""), clean_desc or "")

                product_url = (
                    f"https://beercartel.com.au/products/{p.get('handle', '')}"
                )
                await goto_with_retry(page, product_url)
                await page.wait_for_timeout(3000)

                product_content = await page.content()
                product_soup = BeautifulSoup(product_content, "lxml")

                rating_average = None
                rating_total = None

                if product_soup.find("span", class_="rating-value"):
                    rating_value = product_soup.select_one("span.rating-value")
                    if rating_value:
                        rating_average = float(rating_value.text.strip())

                    rating_total_elem = product_soup.select_one("span.review-count")
                    if rating_total_elem:
                        rating_text = rating_total_elem.text.split(" ")[0].strip()
                        rating_total = int(rating_text.replace(",", ""))
                elif product_soup.find("span", class_="jdgm-prev-badge__stars"):
                    rating_value = product_soup.select_one(
                        "span.jdgm-prev-badge__stars"
                    )
                    if rating_value:
                        data_score = rating_value.get("data-score", "0.0")
                        if isinstance(data_score, list):
                            data_score = data_score[0] if data_score else "0.0"
                        if data_score:
                            rating_average = float(data_score)

                    rating_total_elem = product_soup.select_one(
                        "span.jdgm-prev-badge__text"
                    )
                    if rating_total_elem:
                        rating_text = rating_total_elem.text.split(" ")[0].strip()
                        rating_total = int(rating_text.replace(",", ""))

                quantity_max = await page.eval_on_selector(
                    "input.product-quantity",
                    'el => parseInt(el.getAttribute("max"))',
                )

                if quantity_max is None:
                    stock_status = "Unknown"
                elif quantity_max > 50:
                    stock_status = "In Stock"
                elif quantity_max <= 0:
                    stock_status = "No Stock"
                else:
                    stock_status = "Low Stock"

                variants = p.get("variants", [])
                if variants:
                    for variant in variants:
                        variant_product = create_standardized_product(
                            source="beercartel",
                            product_id=str(variant.get("id", p.get("id"))),
                            product_url=product_url,
                            name=p.get("title"),
                            brand=p.get("vendor"),
                            style=style,
                            abv=abv,
                            description=clean_desc,
                            rating=rating_average,
                            review_count=rating_total,
                            bundle=variant.get("title", "Single"),
                            stock=stock_status,
                            non_member_price=variant.get("price", 0) / 100,
                            variant_url=f"{product_url}?variant={variant.get('id')}",
                        )
                        await store_product(variant_product)
                else:
                    product = create_standardized_product(
                        source="beercartel",
                        product_id=str(p.get("id")),
                        product_url=product_url,
                        name=p.get("title"),
                        brand=p.get("vendor"),
                        style=style,
                        abv=abv,
                        description=clean_desc,
                        rating=rating_average,
                        review_count=rating_total,
                        bundle="Single",
                        stock=stock_status,
                        non_member_price=p.get("price", 0) / 100,
                        variant_url=product_url,
                    )
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

        content = await page.locator("pre").text_content()
        if not content:
            logging.error(f"❌ No content found for {source}")
            return

        data = json.loads(content)
        total_pages = data.get("meta", {}).get("page", {}).get("total", 1)

        logging.info(f"📄 Total {source.title()} pages: {total_pages}")

        async def process_product(item):
            raw_id = item.get("id", "")
            if not raw_id:
                return

            clean_id = raw_id.split("_")[0] if "_" in raw_id else raw_id
            
            variants_data = item.get("multiUOMPrice", [])
            if variants_data:
                all_variants_exist = all(
                    is_product_exists(
                        source,
                        variant.get("id", clean_id),
                        f"https://www.{source}.com.au{variant.get('productUrl')}"
                    )
                    for variant in variants_data
                )
                if all_variants_exist:
                    logging.info(f"⏩ Skipping existing product and variants: {item.get('name')} ({clean_id})")
                    return
            else:
                if is_product_exists(
                    source,
                    clean_id,
                    f"https://www.{source}.com.au{item.get('productUrl')}"
                ):
                    logging.info(f"⏩ Skipping existing product: {item.get('name')} ({clean_id})")
                    return

            detail_url = f"{base_api}/{clean_id}?catalogue=1"

            try:
                await page.goto(detail_url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(3000)

                content = await page.locator("pre").text_content()
                if not content:
                    logging.warning(f"⚠️ No content found for product {raw_id}")
                    return

                data = json.loads(content)
                detail_product = data.get("product", {})

                abv = None
                product_properties = detail_product.get("productProperties", [])
                for prop in product_properties:
                    if prop.get("key") == "Alcohol Content":
                        abv_str = prop.get("value", "")
                        if abv_str and "%" in abv_str:
                            abv = float(abv_str.replace("%", ""))
                        break

                if not abv:
                    description = detail_product.get("description", "")
                    abv = extract_abv_from_description(description)

                style = None
                for prop in product_properties:
                    if prop.get("key") == "Style":
                        style = prop.get("value")
                        break

                if not style:
                    style = extract_style_from_name(
                        detail_product.get("name", ""), description or ""
                    )

                stock_info = detail_product.get("stock", {})
                stock_status = stock_info.get("delivery", "Unknown")
                if stock_status == "":
                    stock_status = "Unknown"

                price_info = detail_product.get("price", {})
                current_price = price_info.get("current", 0)
                normal_price = price_info.get("normal", current_price)

                if normal_price > current_price:
                    non_member_price = normal_price
                    discount_price = current_price
                else:
                    non_member_price = current_price
                    discount_price = None

                base_product = create_standardized_product(
                    source=source,
                    product_id=detail_product.get("id"),
                    product_url=f"https://www.{source}.com.au{detail_product.get('productUrl')}",
                    name=detail_product.get("name"),
                    brand=detail_product.get("brand"),
                    style=style,
                    abv=abv,
                    description=detail_product.get("description"),
                    rating=detail_product.get("ratings", {}).get("average"),
                    review_count=detail_product.get("ratings", {}).get("total"),
                    non_member_price=non_member_price,
                    member_price=price_info.get("memberOnlyPrice"),
                    discount_price=discount_price,
                    stock=stock_status,
                )

                variants_data = detail_product.get("multiUOMPrice", [])
                if variants_data:
                    for variant in variants_data:
                        variant_product = create_standardized_product(
                            source=source,
                            product_id=variant.get("id", detail_product.get("id")),
                            product_url=f"https://www.{source}.com.au{detail_product.get('productUrl')}",
                            name=variant.get("productName", detail_product.get("name")),
                            brand=variant.get("brand", detail_product.get("brand")),
                            style=style,
                            abv=abv,
                            description=detail_product.get("description"),
                            rating=detail_product.get("ratings", {}).get("average"),
                            review_count=detail_product.get("ratings", {}).get("total"),
                            bundle=variant.get("unitOfMeasureLabel")
                            or variant.get("unitOfMeasure"),
                            stock=stock_status,
                            non_member_price=variant.get("price", {}).get("current", 0),
                            member_price=variant.get("price", {}).get(
                                "memberOnlyPrice"
                            ),
                            variant_url=f"https://www.{source}.com.au{variant.get('productUrl')}",
                        )

                        variant_promo = variant.get("promotion", {})
                        promo_text = variant_promo.get("calloutText")
                        if not promo_text and variant_promo.get("dinkus"):
                            promo_text = variant_promo["dinkus"][0].get("text")

                        if promo_text:
                            variant_product["Promo Price"] = promo_text

                        variant_price_info = variant.get("price", {})
                        normal_price = variant_price_info.get(
                            "normal", variant_price_info.get("current", 0)
                        )
                        current_price = variant_price_info.get("current", 0)
                        if normal_price > current_price:
                            variant_product["Discount Price"] = (
                                f"${normal_price - current_price:.2f}"
                            )

                        await store_product(variant_product)
                else:
                    base_product["Bundle"] = detail_product.get(
                        "unitOfMeasureLabel", "Each"
                    )
                    await store_product(base_product)

            except Exception as e:
                logging.warning(f"⚠️ Error processing product {raw_id}: {e}")
                return

        for page_number in tqdm(
            range(1, total_pages + 1), desc=source.title(), unit="page"
        ):
            url = base_url.replace("page=page_number", f"page={page_number}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)

            content = await page.locator("pre").text_content()
            if not content:
                logging.warning(f"⚠️ No content found for page {page_number}")
                continue

            data = json.loads(content)
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
