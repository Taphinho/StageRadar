from datetime import UTC, datetime

import pytest

from stageradar.config import Settings
from stageradar.schemas import ListingInput


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        run_scheduler=False,
        greenhouse_boards={},
        smartrecruiters_companies={},
        lever_boards={},
        ashby_boards={},
        teamtailor_boards={},
        successfactors_boards={},
        thales_enabled=False,
        workday_boards={},
        career_sites=[],
    )


@pytest.fixture
def example() -> ListingInput:
    # Synthetic offer. Never imported into a live StageRadar database.
    return ListingInput(
        employer="Thales",
        title="Stage Pentest et Red Team",
        location="Palaiseau, Île-de-France",
        description=(
            "Stage de fin d’études de 6 mois, à partir d’avril 2027. "
            "Vous utiliserez Python, Linux, Burp Suite et Docker. Vous préparerez les campagnes "
            "avec les équipes du laboratoire, définirez le périmètre autorisé avec votre tuteur, "
            "réaliserez des tests d’intrusion sur des applications en préproduction, "
            "puis rédigerez un rapport détaillé et présenterez vos résultats aux développeurs. "
            "L’équipe assurera un accompagnement sur les outils et la méthodologie."
        ),
        original_url="https://example.org/jobs/123?utm_source=alert",
        published_at=datetime(2026, 11, 3, 12, tzinfo=UTC),
    )
