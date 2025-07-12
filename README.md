# Websites Scrapping Module

A powerful and extensible Python-based web scraper for extracting beer product data from major Australian liquor retailers — **BeerCartel**, **Liquorland**, and **FirstChoiceLiquor**.

This tool uses **Playwright**, **BeautifulSoup**, and **TQDM** to collect product information and save it as structured JSON for analytics, comparison, or retail insights.

---

## 🚀 Features

- ✅ Async scraping with Playwright
- ✅ JSON & HTML scraping (hybrid)
- ✅ Pagination support
- ✅ Retry logic with exponential backoff
- ✅ Logs with progress bar via `tqdm`
- ✅ Output saved as `output.json`

---

## 📦 Requirements

| Component  | Minimum Version              |
| ---------- | ---------------------------- |
| Python     | 3.8+                         |
| Node.js    | 16+ (for Playwright install) |
| OS         | Windows/macOS/Linux          |
| Disk Space | ~100MB+                      |
| Network    | Stable Internet              |

---

## 🔧 Installation

### 1. Clone the Repo

```bash
git clone https://github.com/mferozmirza2005/WebsitesScrappingModule.git
cd WebsitesScrappingModule
```

### 2. Create and Activate Virtual Environment (Recommended)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
playwright install
```

If not using `requirements.txt`, install manually:

```bash
pip install playwright beautifulsoup4 tqdm orjson lxml
playwright install
```

---

## ⚙️ Configuration

Edit `SCRAPER_SITES` in `main.py` to enable/disable target sites or update URLs:

```python
SCRAPER_SITES = {
    "beercartel": {"enabled": True, "url": "https://beercartel.com.au/collections/beer"},
    "liquorland": {"enabled": True, "url": "https://www.liquorland.com.au/api/products/..."},
    "firstchoiceliquor": {"enabled": True, "url": "https://www.firstchoiceliquor.com.au/api/products/..."},
}
```

---

## ▶️ Usage

### Run the Scraper

```bash
python main.py
```

It will automatically:

- Launch a Playwright browser in headless mode
- Scrape enabled websites
- Save results to `output.json`
- Log actions in `scraper.log`

---

## 📂 Output Format

### 📁 `output.json`

A list of product entries like:

```json
{
  "source": "beercartel",
  "id": "123456",
  "name": "Example Lager",
  "brand": "Brew Co.",
  "description": "Light and crisp.",
  "price": 4.99,
  "image_urls": ["https://..."],
  "product_url": "https://...",
  "variants": [...]
}
```

---

## 📄 Logs

Check `scraper.log` for detailed logs with timestamps and error tracking:

```bash
tail -f scraper.log
```

---

## ✅ JSON Fields Collected

| Field            | Description                       |
| ---------------- | --------------------------------- |
| `source`         | Website name                      |
| `id`             | Product ID                        |
| `name`           | Product name                      |
| `brand`          | Manufacturer or brand             |
| `description`    | Cleaned HTML description          |
| `price`          | Current price                     |
| `member_price`   | Member-only price (if available)  |
| `discount`       | Discount amount                   |
| `unit_price`     | Price per unit                    |
| `volume_ml`      | Volume (in mL, if available)      |
| `unit`           | Unit label (e.g., 6 Pack, Bottle) |
| `rating_average` | Average user rating               |
| `rating_total`   | Total number of ratings           |
| `image_urls`     | Product image URLs                |
| `product_url`    | Full URL to the product page      |
| `variants`       | List of product variant data      |

---

## 🧠 Advanced Usage

### Headless Debugging

To view the browser during scraping:

```python
browser = await p.chromium.launch(headless=False)
```

### Retry Logic

You can configure retry attempts and delays inside `goto_with_retry`:

```python
async def goto_with_retry(page, url, retries=3, base_delay=5):
```

### Add Proxy Support

Update `playwright.new_context()` with proxy configuration if needed.

---

## 🛠 Troubleshooting

| Problem                    | Solution                                                 |
| -------------------------- | -------------------------------------------------------- |
| Timeout loading page       | Check internet or increase timeout                       |
| Empty results              | Inspect selectors or response structure                  |
| Website structure changed  | Update scraping logic inside respective scraper function |
| Unicode errors on terminal | Make sure system stdout supports UTF-8                   |

---

## 📌 License

MIT License. © 2025 Muhammad Feroz Mirza

---

## 🙋‍♂️ Author

**Muhammad Feroz Mirza** 🧠 Full-stack Automation Engineer
- Github - [@mferozmirza2005](https://github.com/mferozmirza2005)
- LinkedIn - [@m-feroz-mirza](https://linkedin.com/in/m-feroz-mirza)
- Twiter/X - [@M_Feroz_Mirza](https://x.com/@M_Feroz_Mirza)
- Instagram - [@ferozmirza2005](https://instagram.com/ferozmirza2005/)
