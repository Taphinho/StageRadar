from datetime import date, datetime

from stageradar.scoring import category, evaluate, is_internship


def test_explains_score_and_inference(settings, example):
    fields, score, reasons, domains = evaluate(
        example, example.description, settings, date(2026, 11, 5)
    )
    assert score == 100
    assert sum(reason["points"] for reason in reasons) == score
    assert domains[0] == "offensive"
    assert fields["start_date"] == "2027-04"
    assert fields["duration_months"] == 6
    assert fields["provenance"]["start_date"] == "inferred"
    assert fields["provenance"]["skills"]["Python"] == "inferred"
    assert category(score) == "Priorité très élevée"


def test_missing_dates_still_allow_relevant_score(settings, example):
    text = "Étudiant en dernière année. Python, Linux, Burp Suite et Docker."
    fields, score, _, _ = evaluate(example, text, settings, date(2026, 11, 5))
    assert score >= 70
    assert fields["provenance"]["start_date"] == "unknown"
    assert fields["provenance"]["duration_months"] == "unknown"


def test_publication_after_paris_midnight_uses_local_day(settings, example):
    offer = example.model_copy(update={"published_at": datetime(2026, 11, 4, 23, 30)})
    _, _, reasons, _ = evaluate(offer, offer.description, settings, date(2026, 11, 12))
    freshness = next(reason for reason in reasons if reason["criterion"] == "freshness")
    assert freshness["detail"] == "2026-11-05"
    assert freshness["points"] == settings.weights.freshness


def test_title_may_hide_internship_and_cdi_takes_precedence(example):
    generic = example.model_copy(update={"title": "Analyste SOC"})
    assert is_internship(generic, "Stage de fin d’études de 6 mois pour le SOC.")
    permanent = generic.model_copy(update={"title": "CDI - Analyste SOC"})
    assert not is_internship(permanent, "Nous proposons aussi un stage de fin d’études.")
    assert not is_internship(generic, "Join the last stage of the deployment process.")


def test_incompatible_start_reduces_score(settings, example):
    compatible = evaluate(example, example.description, settings, date(2026, 11, 5))
    incompatible = evaluate(
        example, example.description.replace("avril", "janvier"), settings, date(2026, 11, 5)
    )
    assert compatible[1] - incompatible[1] == settings.weights.start


def test_contradictory_duration_and_start_stay_unknown(settings, example):
    fields, _, _, _ = evaluate(
        example,
        "Stage de 4 à 6 mois. Début avril 2027 ou à partir de mai 2027.",
        settings,
        date(2026, 11, 5),
    )
    assert fields["duration_months"] is None
    assert fields["start_date"] is None


def test_contextual_domains_are_opt_in(settings, example):
    generic = example.model_copy(update={"title": "Stage d’ingénierie"})
    description = "Analyser les journaux pour mener une investigation après compromission."
    disabled = evaluate(generic, description, settings, date(2026, 11, 5))
    enabled = evaluate(
        generic,
        description,
        settings.model_copy(update={"semantic_enabled": True}),
        date(2026, 11, 5),
    )
    assert "defensive" not in disabled[3]
    assert "defensive" in enabled[3]
    assert enabled[1] > disabled[1]
    assert "indices contextuels" in enabled[2][0]["detail"]


def test_skill_detection_covers_cyber_variants_and_punctuation():
    from stageradar.scoring import detect_skills

    detected = set(
        detect_skills(
            "C++, C#, .NET, TypeScript, Wireshark, Nmap, ISO/IEC 27001, Amazon Web Services, K8s, CI/CD, Microsoft Entra ID, Power BI, tcp/ip"
        )
    )
    assert {
        "C++",
        "C#",
        ".NET",
        "TypeScript",
        "Wireshark",
        "Nmap",
        "ISO 27001",
        "AWS",
        "Kubernetes",
        "CI/CD",
        "Microsoft Entra ID",
        "Power BI",
        "TCP/IP",
    } <= detected
    assert "JavaScript" not in detected
    assert "Java" not in detect_skills("JavaScript")
    assert not {"C++", "C#", ".NET", "Go", "SQL"} & set(
        detect_skills("Communication, go to market, PostgreSQL, internet")
    )


def test_skills_from_user_cv():
    from stageradar.scoring import detect_skills

    text = "Cisco Wireshark TCP/IP VLAN OSPF RIP 5G FTTx/PON Fibre optique VoIP Active Directory LDAP COOJA/Contiki-NG Linux Debian Ubuntu Docker Kubernetes Ansible Git GitHub Actions CI/CD Elasticsearch Kibana Filebeat Keycloak Python Bash C C++ Java SQL MongoDB Django REST API Sockets TCP JavaScript HTML/CSS Wazuh Splunk ELK Sysmon Burp Suite Metasploit Nmap MITRE ATT&CK OWASP TLS"
    expected = {
        "Cisco",
        "Wireshark",
        "TCP/IP",
        "VLAN",
        "OSPF",
        "RIP",
        "5G",
        "FTTx/PON",
        "Fibre optique",
        "VoIP",
        "Active Directory",
        "LDAP",
        "COOJA",
        "Contiki-NG",
        "Linux",
        "Debian",
        "Ubuntu",
        "Docker",
        "Kubernetes",
        "Ansible",
        "Git",
        "GitHub Actions",
        "CI/CD",
        "Elasticsearch",
        "Kibana",
        "Filebeat",
        "Keycloak",
        "Python",
        "Bash",
        "C",
        "C++",
        "Java",
        "SQL",
        "MongoDB",
        "Django",
        "REST",
        "Sockets TCP",
        "JavaScript",
        "HTML",
        "CSS",
        "Wazuh",
        "Splunk",
        "ELK",
        "Sysmon",
        "Burp Suite",
        "Metasploit",
        "Nmap",
        "MITRE ATT&CK",
        "OWASP",
        "TLS/SSL",
    }
    assert expected <= set(detect_skills(text))
    assert "C" not in detect_skills("C++ C# c'est avec efficacité")
