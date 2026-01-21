"""Web scraper for fetching additional job details from application links."""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class WebScraper:
    """Scrapes job posting pages for additional content."""

    # Rate limiting: minimum seconds between requests
    MIN_REQUEST_INTERVAL = 1.0

    # Request timeout in seconds
    REQUEST_TIMEOUT = 15

    # Maximum content length to process (5MB)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # User agent to use for requests
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Domains that are known to block scrapers or require JS
    BLOCKED_DOMAINS = {
        "linkedin.com",  # Requires login
        "indeed.com",    # Heavy anti-scraping
        "glassdoor.com", # Requires login
        "x.com",         # Requires login, anti-scraping
        "twitter.com",   # Requires login, anti-scraping
    }

    # Selectors for common job platforms
    PLATFORM_SELECTORS = {
        "lever.co": {
            "title": ".posting-headline h2",
            "description": ".section-wrapper",
            "requirements": ".posting-requirements",
        },
        "greenhouse.io": {
            "title": ".app-title",
            "description": "#content",
            "requirements": "#content",
        },
        "workable.com": {
            "title": "[data-ui='job-title']",
            "description": "[data-ui='job-description']",
            "requirements": "[data-ui='job-requirements']",
        },
        "breezy.hr": {
            "title": ".position-title",
            "description": ".description",
            "requirements": ".description",
        },
        "ashbyhq.com": {
            "title": "h1",
            "description": "[data-testid='job-description']",
            "requirements": "[data-testid='job-description']",
        },
    }

    def __init__(self):
        """Initialize the web scraper."""
        self._last_request_time: float = 0
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            await asyncio.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    def _is_blocked_domain(self, url: str) -> bool:
        """Check if domain is known to block scrapers."""
        try:
            domain = urlparse(url).netloc.lower()
            for blocked in self.BLOCKED_DOMAINS:
                if blocked in domain:
                    return True
        except Exception:
            pass
        return False

    def _get_platform(self, url: str) -> Optional[str]:
        """Identify the job platform from URL."""
        try:
            domain = urlparse(url).netloc.lower()
            for platform in self.PLATFORM_SELECTORS:
                if platform in domain:
                    return platform
        except Exception:
            pass
        return None

    async def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch a web page's HTML content.

        Args:
            url: URL to fetch

        Returns:
            HTML content or None if failed
        """
        if self._is_blocked_domain(url):
            logger.debug(f"Skipping blocked domain: {url}")
            return None

        await self._rate_limit()

        try:
            session = await self._get_session()
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    logger.warning(f"HTTP {response.status} for {url}")
                    return None

                # Check content length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.MAX_CONTENT_LENGTH:
                    logger.warning(f"Content too large: {url}")
                    return None

                # Check content type
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    logger.debug(f"Not HTML content: {url}")
                    return None

                html = await response.text()
                logger.info(f"Fetched {len(html)} bytes from {url}")
                return html

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}")
        except aiohttp.ClientError as e:
            logger.warning(f"Error fetching {url}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")

        return None

    def parse_job_content(self, html: str, url: str) -> dict[str, Optional[str]]:
        """
        Parse job content from HTML.

        Args:
            html: HTML content
            url: Original URL (used to identify platform)

        Returns:
            Dict with extracted fields: title, description, requirements, full_text
        """
        soup = BeautifulSoup(html, "lxml")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        result = {
            "title": None,
            "description": None,
            "requirements": None,
            "full_text": None,
        }

        # Try platform-specific selectors first
        platform = self._get_platform(url)
        if platform and platform in self.PLATFORM_SELECTORS:
            selectors = self.PLATFORM_SELECTORS[platform]
            result["title"] = self._extract_by_selector(soup, selectors.get("title"))
            result["description"] = self._extract_by_selector(soup, selectors.get("description"))
            result["requirements"] = self._extract_by_selector(soup, selectors.get("requirements"))

        # Fallback to generic extraction
        if not result["title"]:
            result["title"] = self._extract_title(soup)

        if not result["description"]:
            result["description"] = self._extract_description(soup)

        # Get full text content
        result["full_text"] = self._extract_full_text(soup)

        return result

    def _extract_by_selector(self, soup: BeautifulSoup, selector: Optional[str]) -> Optional[str]:
        """Extract text using CSS selector."""
        if not selector:
            return None
        try:
            element = soup.select_one(selector)
            if element:
                return self._clean_text(element.get_text())
        except Exception:
            pass
        return None

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job title using common patterns."""
        # Try common title selectors
        selectors = [
            "h1.job-title",
            "h1.posting-title",
            "h1[class*='title']",
            ".job-title",
            ".position-title",
            "h1",
        ]
        for selector in selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    text = self._clean_text(element.get_text())
                    if text and len(text) < 200:  # Reasonable title length
                        return text
            except Exception:
                continue
        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job description using common patterns."""
        # Try common description selectors
        selectors = [
            ".job-description",
            ".description",
            "[class*='description']",
            "article",
            ".content",
            "main",
        ]
        for selector in selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    text = self._clean_text(element.get_text())
                    if text and len(text) > 100:  # Meaningful content
                        return text[:5000]  # Limit length
            except Exception:
                continue
        return None

    def _extract_full_text(self, soup: BeautifulSoup) -> str:
        """Extract all meaningful text from page."""
        # Get body or main content
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            main = soup

        text = self._clean_text(main.get_text())

        # Limit to reasonable length
        if len(text) > 10000:
            text = text[:10000]

        return text

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def scrape_job_url(self, url: str) -> Optional[dict[str, Optional[str]]]:
        """
        Scrape a job posting URL and extract content.

        Args:
            url: Job posting URL

        Returns:
            Dict with extracted content or None if failed
        """
        html = await self.fetch_page(url)
        if not html:
            return None

        return self.parse_job_content(html, url)

    async def get_enhanced_job_text(self, url: str, original_text: str) -> str:
        """
        Get enhanced job text by combining original post with scraped content.

        Args:
            url: Job posting URL
            original_text: Original message text

        Returns:
            Combined text for CV matching
        """
        scraped = await self.scrape_job_url(url)
        if not scraped:
            return original_text

        # Combine original text with scraped content
        parts = [original_text]

        if scraped.get("description"):
            parts.append("\n\n--- From Application Page ---\n")
            parts.append(scraped["description"])
        elif scraped.get("full_text"):
            # Use full text if no specific description found
            full_text = scraped["full_text"]
            # Only add if it provides new content
            if len(full_text) > len(original_text) * 1.5:
                parts.append("\n\n--- From Application Page ---\n")
                parts.append(full_text[:3000])  # Limit added content

        combined = "\n".join(parts)
        logger.info(f"Enhanced job text: {len(original_text)} -> {len(combined)} chars")
        return combined
