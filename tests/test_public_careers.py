import json
from datetime import datetime

from stageradar.collectors.kpmg import KPMG
from stageradar.collectors.public_careers import PublicCareers


def test_public_careers_uses_original_date_and_job_title():
    record = {
        "@type": "JobPosting",
        "title": "Stage en cybersécurité",
        "datePosted": "02/11/2026",
        "description": "<p>Stage de six mois.</p>",
        "employmentType": "Stage",
        "jobLocation": {"address": {"addressCountry": "France", "addressLocality": "Montrouge"}},
    }
    data = (
        '<h1>Gestion des cookies</h1><script type="application/ld+json">'
        + json.dumps(record)
        + "</script>"
    ).encode()
    item = PublicCareers("creditagricole", "Crédit Agricole").parse_job(
        data,
        "https://groupecreditagricole.jobs/fr/nos-offres-emploi/1-reference--2026-12345--/",
    )
    assert item.title == "Stage en cybersécurité"
    assert item.published_at == datetime(2026, 11, 2)
    assert item.external_id == "2026-12345"
    assert item.start_date is None


def test_kpmg_uses_jobposting_instead_of_page_metadata():
    record = {
        "@type": "JobPosting",
        "title": "Stage audit IT",
        "identifier": {"value": "AUD123"},
        "datePosted": "2026-10-26",
        "description": "<p>Audit des systèmes.</p>",
        "employmentType": "Stage",
        "jobLocation": {"address": {"addressCountry": "FR", "addressLocality": "La Défense"}},
    }
    data = ('<script type="application/ld+json">' + json.dumps(record) + "</script>").encode()
    item = KPMG().parse_job(data, "https://emplois.kpmg.fr/emploi/la-defense/stage-audit/1/2")
    assert item.title == "Stage audit IT"
    assert item.published_at == datetime(2026, 10, 26)
    assert item.contract == "Stage"
