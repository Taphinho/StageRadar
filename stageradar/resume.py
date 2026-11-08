import re
from heapq import nlargest
from html import unescape

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stageradar.database import Offer
from stageradar.schemas import Status
from stageradar.scoring import SKILLS, detect_skills, matched, skill_text


def analyze(db: Session, text: str) -> dict:
    cv = skill_text(text)
    vocabulary = {skill_text(skill): alternatives for skill, alternatives in SKILLS.items()}
    detected = detect_skills(text)
    stmt = (
        select(Offer)
        .where(~Offer.hidden, ~Offer.expired, Offer.status.in_([Status.REVIEW, Status.TODO]))
        .options(selectinload(Offer.listings))
        .execution_options(yield_per=100)
    )

    def candidates():
        for offer in db.scalars(stmt):
            if not offer.details["internship"]:
                continue
            source_text = " ".join(
                unescape(re.sub(r"<[^>]*>", " ", str(item.snapshot.get("description", ""))))
                for item in offer.listings
            )
            skills = list(
                dict.fromkeys(
                    [*offer.details["skills"], *detect_skills(offer.title + " " + source_text)]
                )
            )
            present = [
                skill
                for skill in skills
                if skill in detected or (skill_text(skill) not in vocabulary and matched(cv, skill))
            ]
            if present:
                yield {
                    "id": offer.id,
                    "title": offer.title,
                    "employer": offer.employer,
                    "score": offer.score,
                    "rank": round(offer.score * 0.7 + 30 * len(present) / len(skills)),
                    "matches": present,
                    "gaps": [skill for skill in skills if skill not in present],
                }

    results = nlargest(15, candidates(), key=lambda item: (item["rank"], item["score"], item["id"]))
    return {"detected_skills": detected, "suggestions": results}
