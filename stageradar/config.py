import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from stageradar.collectors.successfactors import HOSTS as SUCCESSFACTORS_HOSTS

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
PRIORITY_EMPLOYERS = [
    "Thales",
    "Orange Cyberdefense",
    "Bouygues Telecom",
    "Airbus",
    "Capgemini",
    "Sopra Steria",
    "Eviden",
    "Accenture",
    "CGI",
    "Wavestone",
    "BNP Paribas",
    "Société Générale",
    "BPCE",
    "Crédit Agricole",
    "Dassault Systèmes",
    "Atos",
    "Devoteam",
    "NEVERHACK",
    "Advens",
    "I-Tracing",
    "Synetis",
    "Intrinsec",
    "FTI Consulting",
    "Deloitte",
    "EY",
    "KPMG",
    "PwC",
    "Onepoint",
    "Sia",
    "Almond",
    "Chanel",
    "VINCI Energies",
    "Axians",
]

PRIORITY_CAREER_LINKS = {
    "Orange Cyberdefense": "https://orange.jobs/fr/fr/nos-activites/orange-cyberdefense",
    "Airbus": "https://www.airbus.com/fr/careers/students-and-graduates/interns/internships-in-france",
    "Accenture": "https://www.accenture.com/fr-fr/careers/jobsearch",
    "CGI": "https://www.cgi.com/france/fr-fr/recrute",
    "BNP Paribas": "https://group.bnpparibas/emploi-carriere/candidat-etudiant/stage-alternance",
    "Société Générale": "https://careers.societegenerale.com/stages",
    "BPCE": "https://recrutement.bpce.fr/offres-emploi?tax_country=france&external=false",
    "Crédit Agricole": "https://groupecreditagricole.jobs/fr/nos-offres/",
    "Dassault Systèmes": "https://www.3ds.com/fr/careers/jobs",
    "NEVERHACK": "https://neverhack.com/careers",
    "Synetis": "https://www.synetis.com/carriere/offres-emplois/",
    "Intrinsec": "https://www.intrinsec.com/rejoindre-intrinsec/",
    "FTI Consulting": (
        "https://fticonsult.referrals.selectminds.com/ftistudentcareers/page/"
        "france-studentsgraduate-opportunities-1239"
    ),
    "Deloitte": "https://fina.wd103.myworkdayjobs.com/fr-FR/DeloitteRecrute",
    "EY": "https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q?locale=fr",
    "KPMG": "https://emplois.kpmg.fr/profils-stages-alternances",
    "PwC": "https://carrieres.pwc.fr/fr/stage-offres.html",
    "Onepoint": "https://www.groupeonepoint.com/fr/nous-rejoindre/",
    "Chanel": "https://cc.wd3.myworkdayjobs.com/fr-FR/ChanelCareers",
    "VINCI Energies": "https://www.vinci-energies.com/job-offer/",
    "Axians": "https://www.axians.fr/axians-communication-cloud-carriere/",
}
CAREER_LABELS = {
    "synetis": "Synetis",
    "intrinsec": "Intrinsec",
    "societegenerale": "Société Générale",
    "creditagricole": "Crédit Agricole",
    "ey": "EY",
    "kpmg": "KPMG",
    "orange": "Orange Cyberdefense",
    "cgi": "CGI",
    "dassault": "Dassault Systèmes",
    "bpce": "BPCE",
    "bnp": "BNP Paribas",
}
WORKDAY_BOARDS = {
    "airbus": "Airbus",
    "accenture": "Accenture",
    "deloitte": "Deloitte",
    "pwc": "PwC",
    "onepoint": "Onepoint",
    "chanel": "Chanel",
}
CAREER_NOTES = {
    "FTI Consulting": (
        "Le 8 novembre 2026, le portail France étudiants indiquait aucune offre disponible."
    ),
    "NEVERHACK": "La page officielle renvoie vers LinkedIn, sans flux exploitable vérifié.",
}


class Weights(BaseModel):
    domain: int = Field(default=35, ge=0, le=100)
    skills: int = Field(default=10, ge=0, le=100)
    location: int = Field(default=18, ge=0, le=100)
    duration: int = Field(default=10, ge=0, le=100)
    start: int = Field(default=12, ge=0, le=100)
    education: int = Field(default=7, ge=0, le=100)
    freshness: int = Field(default=5, ge=0, le=100)
    employer: int = Field(default=3, ge=0, le=100)

    @model_validator(mode="after")
    def check_total(self) -> "Weights":
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Les pondérations doivent totaliser 100 points.")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="STAGERADAR_", extra="ignore", hide_input_in_errors=True
    )

    data_dir: Path = Path("data")
    collect_minutes: int = Field(default=30, ge=15, le=1440)
    run_scheduler: bool = True
    collect_on_start: bool = True
    greenhouse_boards: dict[str, str] = Field(
        default_factory=lambda: {
            "dataiku": "Dataiku",
            "mirakl": "Mirakl",
            "mirakllabs": "Mirakl Labs",
        },
        max_length=30,
    )
    smartrecruiters_companies: dict[str, str] = Field(
        default_factory=lambda: {
            "SopraSteria1": "Sopra Steria",
            "devoteam": "Devoteam",
            "Wavestone1": "Wavestone",
            "ADVENS": "Advens",
            "Sia": "Sia",
        },
        max_length=20,
    )
    lever_boards: dict[str, str] = Field(
        default_factory=lambda: {"global:theodo": "Theodo"}, max_length=20
    )
    ashby_boards: dict[str, str] = Field(
        default_factory=lambda: {"mistral.ai": "Mistral AI", "maki": "MakiPeople"},
        max_length=20,
    )
    teamtailor_boards: dict[str, str] = Field(
        default_factory=lambda: {
            "cybelangel": "CybelAngel",
            "hubone": "Hub One",
            "payplug": "Payplug",
            "orangecyberdefense": "Orange Cyberdefense",
            "itracing-1749199701": "I-Tracing",
            "almond": "Almond",
            "vinci-energies": "VINCI Energies",
        },
        max_length=20,
    )
    successfactors_boards: dict[str, str] = Field(
        default_factory=lambda: {
            "capgemini": "Capgemini",
            "arkema": "Arkema",
            "bouygues": "Bouygues Telecom",
            "atos": "Atos",
        }
    )
    thales_enabled: bool = True
    workday_boards: dict[str, str] = Field(default_factory=lambda: WORKDAY_BOARDS.copy())
    career_sites: list[str] = Field(default_factory=lambda: list(CAREER_LABELS))
    target_start: date = date(2027, 4, 1)
    target_months: int = Field(default=6, ge=1, le=24)
    priority_employers: list[str] = Field(default_factory=lambda: PRIORITY_EMPLOYERS.copy())
    priority_domains: list[str] = Field(
        default_factory=lambda: [
            "offensive",
            "defensive",
            "identity",
            "security",
            "infra",
            "cloud",
            "dev",
        ]
    )
    semantic_enabled: bool = False
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    weights: Weights = Field(default_factory=Weights)
    alert_threshold: int = Field(default=70, ge=0, le=100)
    telegram_token: SecretStr | None = None
    telegram_chat_id: int | None = None
    telegram_digest: bool = True
    telegram_commands: bool = True
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    allowed_hosts: list[str] = Field(default_factory=lambda: sorted(LOCAL_HOSTS), min_length=1)
    web_username: str = Field(default="stageradar", pattern=r"^[A-Za-z0-9_.-]{1,60}$")
    web_password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_config(self) -> "Settings":
        if self.workday_boards.keys() - WORKDAY_BOARDS.keys():
            raise ValueError("Portail Workday non pris en charge.")
        if set(self.career_sites) - CAREER_LABELS.keys():
            raise ValueError("Site carrière non pris en charge.")
        if self.successfactors_boards.keys() - SUCCESSFACTORS_HOSTS.keys():
            raise ValueError("Portail SuccessFactors non pris en charge.")
        board_formats = [
            (self.successfactors_boards, r"[a-z]+"),
            (self.greenhouse_boards, r"[a-zA-Z0-9_-]{1,80}"),
            (self.smartrecruiters_companies, r"[a-zA-Z0-9_-]{1,80}"),
            (self.lever_boards, r"(?:global|eu):[a-zA-Z0-9_-]{1,80}"),
            (self.ashby_boards, r"[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*"),
            (self.teamtailor_boards, r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"),
            (self.workday_boards, r"[a-z]+"),
        ]
        for boards, pattern in board_formats:
            if any(
                len(board) > 87
                or not re.fullmatch(pattern, board)
                or not employer.strip()
                or len(employer) > 250
                for board, employer in boards.items()
            ):
                raise ValueError("Identifiant de source ou nom d’entreprise invalide.")
        for host in self.allowed_hosts:
            if host not in LOCAL_HOSTS and not re.fullmatch(r"[a-z0-9.-]+", host):
                raise ValueError("Hôte web invalide. Indiquer un nom d’hôte sans port ni joker.")
        password = self.web_password.get_secret_value() if self.web_password else ""
        if password and (
            len(password) < 16 or not password.isascii() or not password.isprintable()
        ):
            raise ValueError(
                "Le mot de passe web doit avoir au moins 16 caractères ASCII imprimables."
            )
        if set(self.allowed_hosts) - LOCAL_HOSTS and not password:
            raise ValueError("Un hôte web distant exige un mot de passe.")
        token = self.telegram_token.get_secret_value() if self.telegram_token else ""
        if token and not re.fullmatch(r"\d{4,20}:[A-Za-z0-9_-]{20,100}", token):
            raise ValueError("Format de token Telegram invalide.")
        return self

    @property
    def telegram_enabled(self) -> bool:
        return bool(
            self.telegram_token and self.telegram_token.get_secret_value() and self.telegram_chat_id
        )
