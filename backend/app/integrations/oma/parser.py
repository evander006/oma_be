"""Reusable OMA.by product parser (public HTML only, rate-limited, idempotent)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Category pages suitable for home furnishing demos.
DEFAULT_CATEGORY_SEEDS: list[dict[str, str]] = [
    {"id": "lighting", "name": "Освещение", "slug": "osveshchenie", "url": "/nastolnye-lampy-c"},
    {
        "id": "lighting-ceiling",
        "name": "Потолочные светильники",
        "slug": "potolochnye-svetilniki",
        "url": "/potolochnye-svetilniki-c",
    },
    {"id": "furniture", "name": "Мебель", "slug": "mebel", "url": "/mebel-c"},
    {
        "id": "plumbing-faucets",
        "name": "Смесители",
        "slug": "smesiteli",
        "url": "/smesiteli-dlya-umyvalnika-c",
    },
    {"id": "plumbing-sinks", "name": "Раковины", "slug": "rakoviny", "url": "/rakoviny-c"},
    {"id": "bath", "name": "Ванны", "slug": "vanny", "url": "/vanny-c"},
    {
        "id": "kitchen-sinks",
        "name": "Кухонные мойки",
        "slug": "moyki-kukhonnye",
        "url": "/moyki-kukhonnye-c",
    },
    {
        "id": "mirrors",
        "name": "Зеркала",
        "slug": "zerkala",
        "url": "/zerkala-c",
    },
        {
            "id": "shelves",
            "name": "Полки",
            "slug": "polki",
            "url": "/polki-nastennye-c",
        },
    {
        "id": "bathroom-accessories",
        "name": "Аксессуары для ванных",
        "slug": "aksessuary-dlya-vannykh-komnat",
        "url": "/aksessuary-dlya-vannykh-komnat-c",
    },
]


DIMENSION_PATTERNS = [
    (
        "width_mm",
        re.compile(
            r"(?:ширин[аы]|ширина\s*изделия|габарит.*?шир|width)\s*[:=]?\s*([\d.,]+)\s*(мм|см|м)?",
            re.I,
        ),
    ),
    (
        "height_mm",
        re.compile(
            r"(?:высот[аы]|высота\s*изделия|height)\s*[:=]?\s*([\d.,]+)\s*(мм|см|м)?",
            re.I,
        ),
    ),
    (
        "depth_mm",
        re.compile(
            r"(?:глубин[аы]|глубина\s*изделия|depth|длин[аы])\s*[:=]?\s*([\d.,]+)\s*(мм|см|м)?",
            re.I,
        ),
    ),
    (
        "diameter_mm",
        re.compile(r"(?:диаметр|ø|⌀)\s*[:=]?\s*([\d.,]+)\s*(мм|см|м)?", re.I),
    ),
    (
        "weight_kg",
        re.compile(r"(?:вес|масса)\s*[:=]?\s*([\d.,]+)\s*(кг|г)?", re.I),
    ),
]


@dataclass
class ParsedProduct:
    id: str
    source_product_id: str | None
    sku: str | None
    name: str
    brand: str | None
    category_id: str | None
    subcategory: str | None
    source_url: str
    description: str | None
    specifications: list[dict[str, str | None]] = field(default_factory=list)
    width_mm: float | None = None
    height_mm: float | None = None
    depth_mm: float | None = None
    diameter_mm: float | None = None
    weight_kg: float | None = None
    materials: str | None = None
    colors: str | None = None
    image_urls: list[str] = field(default_factory=list)
    local_images: list[str] = field(default_factory=list)
    price: float | None = None
    currency: str | None = None
    availability: str | None = None
    source: str = "oma.by"
    retrieved_at: str | None = None
    price_retrieved_at: str | None = None
    validation_status: str = "validated"
    validation_notes: list[str] = field(default_factory=list)
    model_path: str | None = None


@dataclass
class ImportReport:
    discovered: int = 0
    parsed: int = 0
    validated: int = 0
    failed: int = 0
    images_downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    started_at: str = ""
    finished_at: str = ""


class OmaParser:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.oma_base_url.rstrip("/")
        self.cache_dir = self.settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_at = 0.0
        verify = self.settings.oma_verify_ssl
        if self.settings.oma_allow_insecure_ssl:
            verify = False
        self._client = httpx.Client(
            timeout=self.settings.oma_request_timeout,
            follow_redirects=True,
            verify=verify,
            headers={"User-Agent": self.settings.oma_user_agent},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OmaParser:
        return self
    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        delay = self.settings.oma_request_delay_seconds
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def fetch_html(self, url: str, use_cache: bool = True) -> str:
        cache_path = self._cache_path(url)
        if use_cache and cache_path.is_file():
            return cache_path.read_text(encoding="utf-8", errors="ignore")
        self._throttle()
        self._last_request_at = time.monotonic()
        resp = self._client.get(url)
        resp.raise_for_status()
        # Prefer declared encoding; fall back to utf-8.
        text = resp.content.decode(resp.encoding or "utf-8", errors="ignore")
        cache_path.write_text(text, encoding="utf-8")
        return text

    def absolute_url(self, href: str) -> str:
        return urljoin(self.base + "/", href)

    def extract_product_links(self, category_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            if re.search(r"-p/?$", href):
                links.append(self.absolute_url(href))
        # Parent categories may only list subcategories ending with -c
        if not links:
            for a in soup.select("a[href$='-c'], a[href$='-c/']"):
                href = a.get("href") or ""
                sub_url = self.absolute_url(href)
                if sub_url.rstrip("/") == category_url.rstrip("/"):
                    continue
                try:
                    sub_html = self.fetch_html(sub_url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("subcategory fetch failed %s: %s", sub_url, exc)
                    continue
                links.extend(self.extract_product_links(sub_url, sub_html))
                if len(links) >= 40:
                    break
        # de-dupe preserve order
        seen: set[str] = set()
        out: list[str] = []
        for u in links:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _to_mm(self, value: float, unit: str | None) -> float:
        u = (unit or "мм").lower()
        if u.startswith("м") and not u.startswith("мм"):
            if u.startswith("мм"):
                return value
            if u.startswith("см"):
                return value * 10
            return value * 1000
        if u.startswith("см"):
            return value * 10
        if u in {"г", "гр"}:
            return value  # caller handles weight separately
        return value

    def _parse_number(self, raw: str) -> float | None:
        try:
            return float(raw.replace(",", ".").replace(" ", ""))
        except ValueError:
            return None

    def _parse_dimensions_from_text(self, text: str, product: ParsedProduct) -> None:
        for field_name, pattern in DIMENSION_PATTERNS:
            if getattr(product, field_name) is not None:
                continue
            m = pattern.search(text)
            if not m:
                continue
            num = self._parse_number(m.group(1))
            if num is None:
                continue
            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            if field_name == "weight_kg":
                u = (unit or "кг").lower()
                product.weight_kg = num / 1000 if u.startswith("г") else num
            else:
                setattr(product, field_name, self._to_mm(num, unit))

    def _parse_specs(self, soup: BeautifulSoup) -> list[dict[str, str | None]]:
        specs: list[dict[str, str | None]] = []
        rows = soup.select(
            ".product-params-short_row, .product-params__row, "
            "table.product-params tr, .characteristics__item"
        )
        for row in rows:
            name_el = row.select_one(
                ".product-params-short_name, .product-params__name, "
                "td:first-child, .characteristics__name, span:first-child"
            )
            val_el = row.select_one(
                ".product-params-short_value, .product-params__value, "
                "td:last-child, .characteristics__value, span:last-child"
            )
            if not name_el or not val_el:
                continue
            name = name_el.get_text(" ", strip=True)
            value = val_el.get_text(" ", strip=True)
            if name and value and name != value:
                specs.append({"name": name, "value": value, "unit": None})
        # de-dupe
        seen: set[str] = set()
        unique: list[dict[str, str | None]] = []
        for s in specs:
            key = s["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(s)
        return unique

    def _stable_id(self, source_url: str, sku: str | None, source_id: str | None) -> str:
        raw = sku or source_id or urlparse(source_url).path
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "-", (sku or source_id or "oma").lower())[:24].strip("-")
        return f"oma-{slug}-{digest}"

    def parse_product_page(
        self, url: str, category_id: str | None = None, subcategory: str | None = None
    ) -> ParsedProduct:
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(timezone.utc).isoformat()

        jsonld: dict[str, Any] = {}
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                jsonld = data
                break
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        jsonld = item
                        break

        name = None
        if jsonld.get("name"):
            name = str(jsonld["name"]).strip()
        if not name:
            h1 = soup.find("h1")
            name = h1.get_text(" ", strip=True) if h1 else None
        if not name:
            og = soup.select_one('meta[property="og:title"]')
            name = og.get("content") if og else None
        if not name:
            raise ValueError(f"Missing product name for {url}")

        sku = str(jsonld.get("sku")) if jsonld.get("sku") else None
        brand = None
        if isinstance(jsonld.get("brand"), dict):
            brand = jsonld["brand"].get("name")
        elif isinstance(jsonld.get("brand"), str):
            brand = jsonld["brand"]

        description = jsonld.get("description")
        if not description:
            desc_el = soup.select_one(".product-description, .product__description, #description")
            description = desc_el.get_text("\n", strip=True) if desc_el else None

        price = None
        currency = None
        availability = None
        offers = jsonld.get("offers")
        if isinstance(offers, dict):
            try:
                price = float(Decimal(str(offers.get("price"))))
            except (InvalidOperation, TypeError, ValueError):
                price = None
            currency = offers.get("priceCurrency")
            availability = offers.get("availability")
            if isinstance(availability, str) and "/" in availability:
                availability = availability.rsplit("/", 1)[-1]

        source_product_id = None
        data_id = soup.select_one("[data-product-id]")
        if data_id:
            source_product_id = data_id.get("data-product-id")

        image_urls: list[str] = []
        img = jsonld.get("image")
        if isinstance(img, str):
            image_urls.append(self.absolute_url(img))
        elif isinstance(img, list):
            image_urls.extend(self.absolute_url(i) for i in img if isinstance(i, str))
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            image_urls.append(self.absolute_url(og_img["content"]))
        for im in soup.select(".product-gallery img, .product-images img, img[data-src], img[src]"):
            src = im.get("data-src") or im.get("src")
            if src and "/upload/iblock/" in src:
                image_urls.append(self.absolute_url(src))
        # unique; skip UI placeholders (cards, logos)
        skip_bits = ("cardinb2b", "card_for_mobile", "logo", "favicon", "sprite")
        seen_img: set[str] = set()
        uniq_images: list[str] = []
        for u in image_urls:
            low = u.lower()
            if any(b in low for b in skip_bits):
                continue
            if u not in seen_img:
                seen_img.add(u)
                uniq_images.append(u)

        breadcrumbs = [
            a.get_text(" ", strip=True)
            for a in soup.select(".breadcrumbs a, nav.breadcrumb a")
        ]
        subcat = subcategory
        if not subcat and len(breadcrumbs) >= 3:
            subcat = breadcrumbs[-2]

        specs = self._parse_specs(soup)
        product = ParsedProduct(
            id=self._stable_id(url, sku, source_product_id),
            source_product_id=source_product_id,
            sku=sku,
            name=name,
            brand=brand,
            category_id=category_id,
            subcategory=subcat,
            source_url=url,
            description=description,
            specifications=specs,
            image_urls=uniq_images[:8],
            price=price,
            currency=currency or self.settings.default_currency,
            availability=availability,
            retrieved_at=now,
            price_retrieved_at=now if price is not None else None,
        )

        # Enrich dimensions from specs + description (only when present in source).
        blob = "\n".join(
            [f"{s['name']}: {s['value']}" for s in specs]
            + [description or "", name]
        )
        self._parse_dimensions_from_text(blob, product)

        for s in specs:
            n = (s["name"] or "").lower()
            if "материал" in n and not product.materials:
                product.materials = s["value"]
            if "цвет" in n and not product.colors:
                product.colors = s["value"]

        notes: list[str] = []
        if product.price is None:
            notes.append("price_missing")
        if not product.image_urls:
            notes.append("images_missing")
            product.validation_status = "incomplete"
        if product.width_mm is None and product.height_mm is None:
            notes.append("dimensions_missing")
        product.validation_notes = notes
        if product.validation_status != "incomplete":
            product.validation_status = "validated"
        return product

    def download_image(self, product_id: str, image_url: str, index: int) -> str | None:
        images_dir = self.settings.images_dir / product_id
        images_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(urlparse(image_url).path).suffix.lower() or ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ext = ".jpg"
        filename = f"{index:02d}{ext}"
        target = images_dir / filename
        if target.is_file() and target.stat().st_size > 0:
            return f"images/products/{product_id}/{filename}"
        self._throttle()
        self._last_request_at = time.monotonic()
        try:
            resp = self._client.get(image_url)
            resp.raise_for_status()
            target.write_bytes(resp.content)
            return f"images/products/{product_id}/{filename}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("image download failed %s: %s", image_url, exc)
            return None

    def collect(
        self,
        max_products: int | None = None,
        dry_run: bool = False,
        category_seeds: list[dict[str, str]] | None = None,
    ) -> ImportReport:
        max_products = max_products or self.settings.oma_max_products
        seeds = category_seeds or DEFAULT_CATEGORY_SEEDS
        report = ImportReport(
            dry_run=dry_run,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        collected: list[ParsedProduct] = []
        seen_urls: set[str] = set()
        per_category_target = max(2, max_products // max(1, len(seeds)))

        for seed in seeds:
            if len(collected) >= max_products:
                break
            cat_url = self.absolute_url(seed["url"])
            try:
                html = self.fetch_html(cat_url)
                links = self.extract_product_links(cat_url, html)
            except Exception as exc:  # noqa: BLE001
                msg = f"category failed {cat_url}: {exc}"
                logger.error(msg)
                report.errors.append(msg)
                report.failed += 1
                continue
            report.discovered += len(links)
            taken = 0
            for link in links:
                if len(collected) >= max_products or taken >= per_category_target + 2:
                    break
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                try:
                    product = self.parse_product_page(
                        link, category_id=seed["id"], subcategory=seed["name"]
                    )
                    report.parsed += 1
                    if product.validation_status == "validated" or product.image_urls:
                        if not dry_run:
                            locals_: list[str] = []
                            for idx, img_url in enumerate(product.image_urls[:3]):
                                path = self.download_image(product.id, img_url, idx)
                                if path:
                                    locals_.append(path)
                                    report.images_downloaded += 1
                            product.local_images = locals_
                        collected.append(product)
                        report.validated += 1
                        taken += 1
                    else:
                        report.failed += 1
                        report.errors.append(f"invalid product {link}")
                except Exception as exc:  # noqa: BLE001
                    report.failed += 1
                    report.errors.append(f"{link}: {exc}")
                    logger.exception("parse failed for %s", link)

        # If distribution left us short, fill from remaining links across seeds.
        if len(collected) < max_products:
            for seed in seeds:
                if len(collected) >= max_products:
                    break
                cat_url = self.absolute_url(seed["url"])
                try:
                    html = self.fetch_html(cat_url)
                    links = self.extract_product_links(cat_url, html)
                except Exception:
                    continue
                for link in links:
                    if len(collected) >= max_products:
                        break
                    if link in seen_urls:
                        continue
                    seen_urls.add(link)
                    try:
                        product = self.parse_product_page(
                            link, category_id=seed["id"], subcategory=seed["name"]
                        )
                        if not dry_run:
                            locals_: list[str] = []
                            for idx, img_url in enumerate(product.image_urls[:3]):
                                path = self.download_image(product.id, img_url, idx)
                                if path:
                                    locals_.append(path)
                                    report.images_downloaded += 1
                            product.local_images = locals_
                        collected.append(product)
                        report.validated += 1
                    except Exception as exc:  # noqa: BLE001
                        report.errors.append(f"{link}: {exc}")

        report.products = [asdict(p) for p in collected[:max_products]]
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report

    def save_report(self, report: ImportReport, path: Path | None = None) -> Path:
        out = path or (self.settings.data_dir / "products" / "import_report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        products_path = self.settings.products_json_path
        products_path.parent.mkdir(parents=True, exist_ok=True)
        products_path.write_text(
            json.dumps(report.products, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
