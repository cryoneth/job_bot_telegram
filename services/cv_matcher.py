"""CV matching service using semantic similarity."""

import logging
import re
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from core.models import JobPost, MatchResult, SeniorityLevel, UserFilters

logger = logging.getLogger(__name__)


class UserCVData:
    """Stores CV data for a single user."""

    def __init__(self, user_id: int, cv_text: str, embedding: np.ndarray, skills: set[str]):
        self.user_id = user_id
        self.cv_text = cv_text
        self.embedding = embedding
        self.skills = skills


class CVMatcher:
    """
    Matches job posts against CVs using hybrid scoring.
    Supports multiple users with individual CVs.

    Scoring algorithm (0-100):
    - Semantic similarity: 0-60 points
    - Keyword bonuses: 0-25 points
    - Rule-based adjustments: -20 to +15 points
    """

    # Model for semantic embeddings
    MODEL_NAME = "all-MiniLM-L6-v2"

    # Scoring weights
    MAX_SEMANTIC_SCORE = 60
    MAX_KEYWORD_SCORE = 25
    KEYWORD_BONUS = 7  # Per matching keyword (max 7)

    # Rule-based adjustments
    REMOTE_MATCH_BONUS = 10
    SENIORITY_MATCH_BONUS = 5
    EXCLUDED_KEYWORD_PENALTY = -10
    LOCATION_MISMATCH_PENALTY = -10

    def __init__(self):
        """Initialize the CV matcher."""
        self._model: Optional[SentenceTransformer] = None
        # Per-user CV storage
        self._user_cvs: dict[int, UserCVData] = {}
        # Legacy single-user support (user_id=0)
        self._cv_text: Optional[str] = None
        self._cv_embedding: Optional[np.ndarray] = None
        self._cv_skills: set[str] = set()

    def load_model(self) -> None:
        """Load the sentence transformer model."""
        if self._model is None:
            logger.info(f"Loading model: {self.MODEL_NAME}")
            self._model = SentenceTransformer(self.MODEL_NAME)
            logger.info("Model loaded successfully")

    def set_cv(self, cv_text: str, user_id: int = 0) -> None:
        """
        Set the CV to match against for a specific user.

        Args:
            cv_text: The CV content
            user_id: The user ID (0 for legacy single-user mode)
        """
        self.load_model()
        embedding = self._model.encode(cv_text, convert_to_numpy=True)
        skills = self._extract_skills(cv_text)

        # Store in per-user dict
        self._user_cvs[user_id] = UserCVData(
            user_id=user_id,
            cv_text=cv_text,
            embedding=embedding,
            skills=skills,
        )

        # Legacy support
        if user_id == 0:
            self._cv_text = cv_text
            self._cv_embedding = embedding
            self._cv_skills = skills

        logger.info(f"CV set for user {user_id} with {len(skills)} identified skills")

    def clear_cv(self, user_id: int = 0) -> None:
        """Clear the stored CV for a user."""
        self._user_cvs.pop(user_id, None)

        # Legacy support
        if user_id == 0:
            self._cv_text = None
            self._cv_embedding = None
            self._cv_skills = set()

        logger.info(f"CV cleared for user {user_id}")

    def has_cv(self, user_id: int = 0) -> bool:
        """Check if CV is loaded for a user."""
        return user_id in self._user_cvs

    def has_any_cv(self) -> bool:
        """Check if any user has a CV loaded."""
        return len(self._user_cvs) > 0

    def get_users_with_cv(self) -> list[int]:
        """Get list of user IDs that have CVs loaded."""
        return list(self._user_cvs.keys())

    def match(
        self, job_post: JobPost, filters: Optional[UserFilters] = None, user_id: int = 0
    ) -> MatchResult:
        """
        Match a job post against a user's CV.

        Args:
            job_post: The job post to match
            filters: User filter preferences
            user_id: The user ID to match against

        Returns:
            MatchResult with score and reasons
        """
        if not self.has_cv(user_id):
            return MatchResult(score=0, match_reasons=["No CV set"])

        if filters is None:
            filters = UserFilters()

        self.load_model()

        user_cv = self._user_cvs[user_id]

        # Calculate semantic similarity
        semantic_score = self._calculate_semantic_score(job_post.raw_text, user_cv.embedding)
        # Short posts tend to under-score semantically; give a small boost
        if len(job_post.raw_text) < 400:
            semantic_score *= 1.15

        # Calculate keyword score
        keyword_score, matched_skills = self._calculate_keyword_score(
            job_post.raw_text, user_cv.skills
        )

        # Apply rule-based adjustments
        adjustments, match_reasons, filter_reasons = self._apply_rules(
            job_post, filters
        )

        # Combine scores
        total_score = int(semantic_score + keyword_score + adjustments)
        total_score = max(0, min(100, total_score))  # Clamp to 0-100

        # Build match reasons
        if matched_skills:
            match_reasons.insert(0, f"Skills match: {', '.join(list(matched_skills)[:5])}")

        result = MatchResult(
            score=total_score,
            match_reasons=match_reasons[:5],  # Top 5 reasons
            filter_reasons=filter_reasons,
            semantic_score=semantic_score,
            keyword_score=keyword_score,
        )

        logger.debug(
            f"Match score: {total_score} (semantic: {semantic_score:.1f}, "
            f"keyword: {keyword_score:.1f}, adj: {adjustments})"
        )

        return result

    def _calculate_semantic_score(
        self, job_text: str, cv_embedding: Optional[np.ndarray] = None
    ) -> float:
        """Calculate semantic similarity score (0-60)."""
        if not self._model:
            return 0.0

        # Use provided embedding or fall back to legacy
        embedding = cv_embedding if cv_embedding is not None else self._cv_embedding
        if embedding is None:
            return 0.0

        job_embedding = self._model.encode(job_text, convert_to_numpy=True)

        # Cosine similarity
        similarity = np.dot(embedding, job_embedding) / (
            np.linalg.norm(embedding) * np.linalg.norm(job_embedding)
        )

        # Scale to 0-60
        return float(similarity * self.MAX_SEMANTIC_SCORE)

    def _calculate_keyword_score(
        self, job_text: str, cv_skills: Optional[set[str]] = None
    ) -> tuple[float, set[str]]:
        """Calculate keyword bonus score (0-25)."""
        # Use provided skills or fall back to legacy
        skills = cv_skills if cv_skills is not None else self._cv_skills

        job_skills = self._extract_skills(job_text)
        matched_skills = skills & job_skills

        # +5 per matching skill, max 5 skills = 25 points
        num_matches = min(len(matched_skills), 8)
        score = num_matches * self.KEYWORD_BONUS

        return float(score), matched_skills

    def _apply_rules(
        self, job_post: JobPost, filters: UserFilters
    ) -> tuple[int, list[str], list[str]]:
        """Apply rule-based scoring adjustments."""
        adjustment = 0
        match_reasons: list[str] = []
        filter_reasons: list[str] = []

        # Remote preference
        if filters.remote.value == "yes" and job_post.is_remote:
            adjustment += self.REMOTE_MATCH_BONUS
            match_reasons.append("Remote-friendly position")
        elif filters.remote.value == "no" and job_post.is_remote is False:
            adjustment += self.REMOTE_MATCH_BONUS
            match_reasons.append("On-site position (as preferred)")

        # Seniority match
        if filters.seniorities and job_post.seniority:
            if job_post.seniority in filters.seniorities:
                adjustment += self.SENIORITY_MATCH_BONUS
                match_reasons.append(
                    f"{job_post.seniority.value.title()} level (matches preference)"
                )
            else:
                filter_reasons.append(
                    f"Seniority: {job_post.seniority.value} "
                    f"(wanted: {', '.join(s.value for s in filters.seniorities)})"
                )

        # Excluded keywords
        job_text_lower = job_post.raw_text.lower()
        for excluded in filters.excluded:
            if excluded.lower() in job_text_lower:
                adjustment += self.EXCLUDED_KEYWORD_PENALTY
                filter_reasons.append(f"Contains excluded keyword: {excluded}")
                break  # Only penalize once

        # Required keywords (also boost score a bit)
        required_hits = 0
        for keyword in filters.keywords:
            if keyword.lower() in job_text_lower:
                required_hits += 1
                match_reasons.append(f"Contains required keyword: {keyword}")

        adjustment += min(required_hits * 4, 12)
        
        # Location match
        if filters.locations and job_post.location:
            location_lower = job_post.location.lower()
            location_match = any(
                loc.lower() in location_lower for loc in filters.locations
            )
            if location_match:
                match_reasons.append(f"Location: {job_post.location}")
            elif not job_post.is_remote:  # Only penalize if not remote
                adjustment += self.LOCATION_MISMATCH_PENALTY
                filter_reasons.append(
                    f"Location: {job_post.location} "
                    f"(wanted: {', '.join(filters.locations)})"
                )

        return adjustment, match_reasons, filter_reasons

    def _extract_skills(self, text: str) -> set[str]:
        """
        Extract skills from text (tech + community/growth/web3).

        Returns:
            Set of identified skills (lowercase)
        """
        # Common skills and technologies
        skill_patterns = [
            # --- Tech skills (existing) ---
            r"\b(python|javascript|typescript|java|c\+\+|c#|ruby|go|golang|rust|php|swift|kotlin|scala|r)\b",
            r"\b(react|vue|angular|svelte|node\.?js|express|django|flask|fastapi|spring|rails|laravel|nextjs|nuxt)\b",
            r"\b(sql|mysql|postgresql|postgres|mongodb|redis|elasticsearch|dynamodb|cassandra|sqlite)\b",
            r"\b(aws|azure|gcp|docker|kubernetes|k8s|terraform|ansible|jenkins|gitlab|github|ci/cd)\b",
            r"\b(machine learning|ml|deep learning|tensorflow|pytorch|pandas|numpy|scikit-learn|data science|nlp|ai)\b",
            r"\b(git|linux|agile|scrum|rest|graphql|microservices|api|testing|tdd|devops)\b",
            r"\b(html|css|sass|webpack|babel|npm|yarn|gradle|maven|spark|kafka|rabbitmq)\b",

            # --- Community / Marketing / Growth ---
            r"\b(community|community[\s\-]+management|community[\s\-]+lead|moderation|moderator|support|ops|operations)\b",
            r"\b(ambassador|ambassadors|creator[\s\-]+program|creator[\s\-]+programs|ugc|content|content[\s\-]+strategy|ghostwriting|narrative|positioning|distribution)\b",
            r"\b(growth|retention|onboarding|engagement|referrals|gamification|loyalty)\b",
            r"\b(partnerships|partner[\s\-]+campaigns|ecosystem|collaborations|business[\s\-]+development|bd|networking)\b",
            r"\b(ama|amas|workshops|events|event[\s\-]+management)\b",

            # --- Platforms ---
            r"\b(discord|telegram|farcaster|twitter|x|notion|slack|asana)\b",

            # --- Web3 ---
            r"\b(crypto|web3|defi|dao|token|tge|airdrop|layer\s?1|l1|ecosystem)\b",
            r"\b(kol|kols|influencer|influencers)\b",
        ]

        text_lower = text.lower()
        skills: set[str] = set()

        for pattern in skill_patterns:
            matches = re.findall(pattern, text_lower)
            # re.findall returns strings here (because each pattern has one capturing group)
            skills.update(m.strip().lower() for m in matches if m)

        # Normalize a couple of ambiguous ones
        if "x" in skills:
            skills.discard("x")
            skills.add("twitter")

        return skills

    def get_cv_summary(self, user_id: int = 0) -> dict:
        """Get summary of loaded CV for a user."""
        if user_id not in self._user_cvs:
            # Legacy fallback
            if user_id == 0 and self._cv_text:
                return {
                    "loaded": True,
                    "length": len(self._cv_text),
                    "skills_count": len(self._cv_skills),
                    "skills": sorted(self._cv_skills)[:20],
                }
            return {"loaded": False}

        user_cv = self._user_cvs[user_id]
        return {
            "loaded": True,
            "length": len(user_cv.cv_text),
            "skills_count": len(user_cv.skills),
            "skills": sorted(user_cv.skills)[:20],  # Top 20 skills
        }
