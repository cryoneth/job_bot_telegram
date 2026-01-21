"""Job post classification and field extraction."""

import logging
import re
from typing import Optional

from core.models import JobPost, SeniorityLevel

logger = logging.getLogger(__name__)


class JobClassifier:
    """Classifies messages as job posts and extracts structured information."""

    # Keywords that indicate a job posting
    JOB_KEYWORDS = {
        # Strong indicators
        "hiring",
        "vacancy",
        "job opening",
        "position available",
        "we're looking for",
        "we are looking for",
        "join our team",
        "apply now",
        "send your cv",
        "send cv",
        "submit resume",
        "open position",
        "job opportunity",
        "career opportunity",
        "open role",
        # Role-related
        "developer",
        "engineer",
        "designer",
        "analyst",
        "manager",
        "coordinator",
        "specialist",
        "consultant",
        "architect",
        "researcher",
        "scientist",
        "trader",
        "quant",
        # Requirements section
        "requirements",
        "qualifications",
        "experience required",
        "must have",
        "skills required",
        "what we expect",
        "what you'll need",
        "responsibilities",
        "about the role",
        "role overview",
        "job description",
        "what you'll do",
        "your responsibilities",
        # Employment terms
        "full-time",
        "fulltime",
        "part-time",
        "parttime",
        "contract",
        "freelance",
        "remote",
        "hybrid",
        "on-site",
        "onsite",
        "permanent",
        # Compensation
        "salary",
        "compensation",
        "benefits",
        "competitive pay",
        "equity",
        "stock options",
        # Application
        "how to apply",
        "to apply",
        "apply for this",
        "application",
        "interview",
        "candidate",
        "submit your",
        "apply here",
        # Web3/Crypto specific
        "web3",
        "blockchain",
        "defi",
        "crypto",
    }

    # Minimum number of keywords required
    MIN_KEYWORDS = 2

    # Seniority patterns (ordered from highest to lowest for priority matching)
    SENIORITY_PATTERNS = {
        SeniorityLevel.EXECUTIVE: r"\b(cto|ceo|cfo|coo|c-level|chief)\b",
        SeniorityLevel.VP: r"\b(vp|vice president|head of)\b",
        SeniorityLevel.DIRECTOR: r"\b(director)\b",
        SeniorityLevel.PRINCIPAL: r"\b(principal|staff engineer|staff)\b",
        SeniorityLevel.MANAGER: r"\b(manager|engineering manager)\b",
        SeniorityLevel.LEAD: r"\b(lead|team lead|tech lead)\b",
        SeniorityLevel.SENIOR: r"\b(senior|sr\.?)\b",
        SeniorityLevel.MID: r"\b(mid[- ]?level|intermediate|regular)\b",
        SeniorityLevel.JUNIOR: r"\b(junior|jr\.?|entry[- ]level|associate)\b",
        SeniorityLevel.INTERN: r"\b(intern|internship|trainee|apprentice)\b",
    }

    # Remote work patterns
    REMOTE_PATTERNS = [
        r"\b(fully[- ]?remote|100%[- ]?remote|remote[- ]?only)\b",
        r"\b(remote[- ]?first|remote[- ]?friendly)\b",
        r"\b(work[- ]?from[- ]?home|wfh)\b",
        r"\b(remote|distributed)\b",
    ]

    # Salary patterns
    SALARY_PATTERNS = [
        # Currency amounts
        r"[$€£]\s*\d+[,.]?\d*\s*[kK]?\s*[-–]\s*[$€£]?\s*\d+[,.]?\d*\s*[kK]?",
        r"\d+[,.]?\d*\s*[kK]?\s*[-–]\s*\d+[,.]?\d*\s*[kK]?\s*[$€£]",
        r"(salary|compensation|pay)[:\s]+[$€£]?\s*\d+[,.]?\d*\s*[kK]?",
        # Range patterns
        r"\d+[,.]?\d*\s*[-–]\s*\d+[,.]?\d*\s*(usd|eur|gbp|per year|annually|per month|monthly)",
    ]

    # URL pattern for application links
    URL_PATTERN = r"https?://[^\s<>\[\]()\"']+"

    # Email pattern
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    def __init__(self, min_keywords: int = MIN_KEYWORDS):
        """
        Initialize the classifier.

        Args:
            min_keywords: Minimum keywords required to classify as job post
        """
        self._min_keywords = min_keywords

    def is_job_post(self, text: str) -> tuple[bool, int]:
        """
        Check if text is a job posting.

        Args:
            text: Message text to classify

        Returns:
            Tuple of (is_job_post, keyword_count)
        """
        text_lower = text.lower()
        matched_keywords = []

        for keyword in self.JOB_KEYWORDS:
            if keyword in text_lower:
                matched_keywords.append(keyword)

        keyword_count = len(matched_keywords)
        is_job = keyword_count >= self._min_keywords

        if matched_keywords:
            logger.info(f"Job keywords found: {matched_keywords[:5]}{'...' if len(matched_keywords) > 5 else ''}")

        logger.debug(f"Job classification: {is_job} (keywords: {keyword_count})")
        return is_job, keyword_count

    def extract_job_post(self, text: str) -> JobPost:
        """
        Extract structured job information from text.

        Args:
            text: Job posting text

        Returns:
            JobPost with extracted fields
        """
        return JobPost(
            role_title=self._extract_role_title(text),
            company=self._extract_company(text),
            location=self._extract_location(text),
            is_remote=self._extract_remote(text),
            seniority=self._extract_seniority(text),
            salary_info=self._extract_salary(text),
            requirements=self._extract_requirements(text),
            application_link=self._extract_application_link(text),
            raw_text=text,
        )

    def _extract_role_title(self, text: str) -> Optional[str]:
        """Extract job title from text."""
        # Common patterns for job titles
        patterns = [
            # "Looking for a Senior Python Developer"
            r"looking for (?:a |an )?([A-Z][A-Za-z/\-\s]+(?:Developer|Engineer|Designer|Analyst|Manager|Lead|Architect|Specialist|Consultant|Coordinator))",
            # "Senior Python Developer position"
            r"([A-Z][A-Za-z/\-\s]+(?:Developer|Engineer|Designer|Analyst|Manager|Lead|Architect|Specialist|Consultant|Coordinator))\s+position",
            # "Hiring: Senior Python Developer"
            r"(?:Hiring|Vacancy|Position)[:\s]+([A-Z][A-Za-z/\-\s]+)",
            # "Job: Senior Python Developer"
            r"(?:Job|Role|Position)[:\s]+([A-Z][A-Za-z/\-\s]+)",
            # First line often contains the title (if capitalized and reasonable length)
            r"^([A-Z][A-Za-z\s/\-]+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                title = match.group(1).strip()
                # Clean up the title
                title = re.sub(r"\s+", " ", title)
                if 3 <= len(title) <= 80:  # Reasonable title length
                    return title

        return None

    def _extract_company(self, text: str) -> Optional[str]:
        """Extract company name from text."""
        patterns = [
            # "at TechCorp" or "@ TechCorp"
            r"(?:at|@)\s+([A-Z][A-Za-z0-9\s&\-\.]+?)(?:\s+is|\s+we|\s+are|,|\.|\n)",
            # "TechCorp is hiring"
            r"([A-Z][A-Za-z0-9\s&\-\.]+?)\s+is\s+(?:hiring|looking|seeking)",
            # "Company: TechCorp"
            r"(?:Company|Organization|Employer)[:\s]+([A-Za-z0-9\s&\-\.]+)",
            # "Join TechCorp"
            r"Join\s+([A-Z][A-Za-z0-9\s&\-\.]+?)(?:\s+as|\s+team|!|,|\.|\n)",
            # "About CompanyName" section header
            r"About\s+([A-Z][A-Za-z0-9]+)(?:\s|$|\n)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                company = match.group(1).strip()
                # Clean up
                company = re.sub(r"\s+", " ", company)
                if 2 <= len(company) <= 50:
                    return company

        # Try to extract from URL in text
        url_match = re.search(r"https?://(?:www\.)?([a-zA-Z0-9\-]+)\.", text)
        if url_match:
            domain = url_match.group(1)
            # Skip common non-company domains
            skip_domains = ["linkedin", "indeed", "glassdoor", "github", "twitter", "t", "x", "google", "bit", "tinyurl"]
            if domain.lower() not in skip_domains and len(domain) >= 2:
                # Capitalize the domain name
                return domain.capitalize()

        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """Extract location from text."""
        patterns = [
            # "Location: City, Country" or "Location: Remote"
            r"(?:Location|Based in|Office in|Located in)[:\s]+([A-Z][A-Za-z\s,]{2,30}?)(?:\.|,\s*[a-z]|\n|$)",
            # "City, State/Country" format - e.g., "New York, NY" or "London, UK"
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*[A-Z]{2,3})\b",
            # "in San Francisco" (followed by punctuation or newline)
            r"(?:based |located |position )?in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:[,\.\n]|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                location = match.group(1).strip().rstrip(",.")
                # Validate it looks like a location (not random text)
                if 2 <= len(location) <= 40:
                    # Skip if it contains job-related words (false positive)
                    skip_words = ["team", "company", "role", "position", "job", "work", "stack"]
                    if not any(word in location.lower() for word in skip_words):
                        return location

        return None

    def _extract_remote(self, text: str) -> Optional[bool]:
        """Check if job is remote."""
        text_lower = text.lower()

        # Check for explicit remote mentions
        for pattern in self.REMOTE_PATTERNS:
            if re.search(pattern, text_lower):
                return True

        # Check for on-site only
        if re.search(r"\b(on[- ]?site[- ]?only|office[- ]?based|in[- ]?office)\b", text_lower):
            return False

        return None  # Unknown

    def _extract_seniority(self, text: str) -> Optional[SeniorityLevel]:
        """Extract seniority level from text."""
        text_lower = text.lower()

        for level, pattern in self.SENIORITY_PATTERNS.items():
            if re.search(pattern, text_lower):
                return level

        return None

    def _extract_salary(self, text: str) -> Optional[str]:
        """Extract salary information from text."""
        for pattern in self.SALARY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return None

    def _extract_requirements(self, text: str) -> Optional[str]:
        """Extract requirements section from text."""
        # Find requirements section
        patterns = [
            r"(?:Requirements|Qualifications|What we['\s]re looking for|Must have|Skills)[:\s]*\n((?:[-•*]\s*[^\n]+\n?)+)",
            r"(?:Requirements|Qualifications)[:\s]*(.*?)(?:\n\n|\n[A-Z]|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                requirements = match.group(1).strip()
                # Limit length
                if len(requirements) > 500:
                    requirements = requirements[:500] + "..."
                return requirements

        return None

    def _extract_application_link(self, text: str) -> Optional[str]:
        """Extract application link from text."""
        urls = re.findall(self.URL_PATTERN, text)

        # Prioritize job platform links
        job_domains = [
            "linkedin.com",
            "indeed.com",
            "lever.co",
            "greenhouse.io",
            "workable.com",
            "breezy.hr",
            "jobs.",
            "careers.",
            "apply.",
        ]

        for url in urls:
            for domain in job_domains:
                if domain in url.lower():
                    return url

        # Return first URL if no job platform found
        if urls:
            return urls[0]

        # Check for email
        emails = re.findall(self.EMAIL_PATTERN, text)
        if emails:
            return f"mailto:{emails[0]}"

        return None
