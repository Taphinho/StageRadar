import re
import unicodedata
from datetime import date
from functools import lru_cache

from stageradar.config import Settings
from stageradar.schemas import ListingInput, paris_date

DOMAINS = {
    "offensive": (
        "Pentest / Red Team",
        1.0,
        "pentest|penetration testing|test d'intrusion|tests d'intrusion|red team|offensive security|securite offensive|ethical hacking",
    ),
    "defensive": (
        "SOC / Blue Team",
        1.0,
        "soc|blue team|incident response|reponse aux incidents|siem|threat hunting|dfir|security operations|detection engineering",
    ),
    "identity": (
        "IAM / PAM",
        1.0,
        "iam|pam|identity security|identity and access management|gestion des identites|sailpoint|cyberark",
    ),
    "security": (
        "Cybersécurité",
        0.92,
        "cybersecurite|cybersecurity|cyber security|securite informatique|information security|appsec|security engineering|security engineer|securite des si",
    ),
    "infra": (
        "Systèmes et réseaux",
        0.78,
        "administration systemes|systemes et reseaux|system administrator|network engineer|infrastructure engineer|administrateur systeme|ingenieur reseau",
    ),
    "cloud": ("Cloud / DevSecOps", 0.84, "cloud|devsecops|devops|site reliability|cloud platform"),
    "dev": (
        "Développement logiciel",
        0.75,
        "software engineer|software engineering|software development|developpement logiciel|developpeur|developpeuse|fullstack|full stack|informatique|computer science",
    ),
}
CONTEXTS = {
    "offensive": (
        "exploitation|exploit|payload|simulation d'attaque",
        "vulnerabilite|vulnerabilities|surface d'attaque",
    ),
    "defensive": (
        "alertes|alerts|journaux|security logs",
        "investigation|compromission|triage|correlation",
    ),
    "identity": (
        "provisionnement|provisioning|cycle de vie des comptes",
        "droits d'acces|access rights|comptes privilegies",
    ),
    "cloud": (
        "pipeline|pipelines|ci cd",
        "analyse de vulnerabilites|secret scanning|container security",
    ),
}
SKILLS = {
    "Python": "python",
    "Linux": "linux",
    "SIEM": "siem",
    "IAM": "iam",
    "PAM": "pam",
    "Docker": "docker",
    "Kubernetes": "kubernetes|k8s",
    "Terraform": "terraform",
    "AWS": "aws|amazon web services",
    "Azure": "azure",
    "GCP": "gcp|google cloud|google cloud platform",
    "Java": "java",
    "JavaScript": "javascript|ecmascript",
    "SQL": "sql",
    "Go": "golang",
    "Splunk": "splunk",
    "Microsoft Sentinel": "microsoft sentinel",
    "Active Directory": "active directory|ad ds",
    "Burp Suite": "burp suite",
    "Git": "git",
    "PowerShell": "powershell",
    "Ansible": "ansible",
    "TypeScript": "typescript",
    "C++": "cpp|c plus plus|cplusplus",
    "C#": "csharp|c sharp",
    ".NET": "dotnet|asp net",
    "Bash": "bash|shell scripting|scripts shell|scripting shell",
    "PHP": "php",
    "Rust": "rust",
    "Ruby": "ruby",
    "Swift": "swift",
    "Kotlin": "kotlin",
    "HTML": "html|html5",
    "CSS": "css|css3",
    "React": "react|reactjs|react js",
    "Angular": "angular|angularjs",
    "Vue.js": "vue js|vuejs",
    "Node.js": "node js|nodejs",
    "Spring Boot": "spring boot",
    "Django": "django",
    "Flask": "flask",
    "FastAPI": "fastapi",
    "Express": "express js|expressjs",
    "GitLab": "gitlab",
    "GitHub": "github",
    "CI/CD": "ci cd|integration continue|continuous integration|continuous delivery|deploiement continu",
    "Jenkins": "jenkins",
    "GitHub Actions": "github actions",
    "GitLab CI": "gitlab ci",
    "Argo CD": "argo cd|argocd",
    "Helm": "helm",
    "OpenShift": "openshift",
    "Podman": "podman",
    "Prometheus": "prometheus",
    "Grafana": "grafana",
    "ELK": "elk|elastic stack|elasticsearch logstash kibana",
    "Elasticsearch": "elasticsearch",
    "Logstash": "logstash",
    "Kibana": "kibana",
    "Windows Server": "windows server",
    "Ubuntu": "ubuntu",
    "Debian": "debian",
    "Kali Linux": "kali linux|kali",
    "Red Hat": "red hat|rhel",
    "VMware": "vmware|vsphere|esxi",
    "Proxmox": "proxmox",
    "Hyper-V": "hyper v",
    "TCP/IP": "tcp ip|tcpip",
    "DNS": "dns",
    "DHCP": "dhcp",
    "VLAN": "vlan|vlans",
    "VPN": "vpn",
    "SSH": "ssh",
    "TLS/SSL": "tls|ssl",
    "HTTP": "HTTP|https",
    "Wireshark": "wireshark",
    "Cisco": "cisco",
    "Fortinet": "fortinet|fortigate",
    "pfSense": "pfsense",
    "Palo Alto": "palo alto|pan os",
    "Nmap": "nmap",
    "Metasploit": "metasploit",
    "Nessus": "nessus",
    "OpenVAS": "openvas|greenbone",
    "Qualys": "qualys",
    "OWASP": "owasp",
    "OWASP ZAP": "owasp zap|zaproxy",
    "MITRE ATT&CK": "mitre att ck|mitre attack",
    "Wazuh": "wazuh",
    "QRadar": "qradar",
    "Suricata": "suricata",
    "Snort": "snort",
    "YARA": "yara",
    "Sigma": "sigma rules|regles sigma",
    "EDR": "edr|endpoint detection and response",
    "XDR": "xdr|extended detection and response",
    "SOAR": "soar|security orchestration automation and response",
    "DLP": "dlp|data loss prevention",
    "IDS/IPS": "ids|ips|intrusion detection|intrusion prevention",
    "SOC": "soc|security operations center|security operations centre",
    "Pentest": "pentest|pentesting|penetration testing|test d'intrusion|tests d'intrusion",
    "Réponse aux incidents": "incident response|reponse aux incidents",
    "Threat hunting": "threat hunting|chasse aux menaces",
    "Forensique": "forensic|forensics|forensique|dfir",
    "Reverse engineering": "reverse engineering|retro ingenierie",
    "Cryptographie": "cryptographie|cryptography",
    "PKI": "pki|public key infrastructure",
    "OAuth 2.0": "oauth|oauth2",
    "OpenID Connect": "openid connect|oidc",
    "SAML": "saml",
    "LDAP": "ldap",
    "Kerberos": "kerberos",
    "Microsoft Entra ID": "entra id|azure ad",
    "Keycloak": "keycloak",
    "CyberArk": "cyberark",
    "SailPoint": "sailpoint",
    "ISO 27001": "iso 27001|iso27001|iso iec 27001",
    "ISO 27005": "iso 27005|iso27005",
    "EBIOS RM": "ebios|ebios risk manager",
    "NIST": "nist",
    "RGPD": "rgpd|gdpr",
    "GRC": "grc|gouvernance risques conformite|governance risk compliance",
    "Analyse de risques": "analyse de risques|analyse des risques|risk assessment|risk analysis",
    "Sécurité réseau": "securite reseau|network security|securite des reseaux",
    "Sécurité applicative": "appsec|application security|securite applicative",
    "DevSecOps": "devsecops",
    "PostgreSQL": "postgresql|postgres",
    "MySQL": "mysql",
    "MariaDB": "mariadb",
    "SQLite": "sqlite",
    "MongoDB": "mongodb",
    "Redis": "redis",
    "Oracle": "oracle database|oracle sql",
    "SQL Server": "sql server|mssql",
    "Pandas": "pandas",
    "NumPy": "numpy",
    "Scikit-learn": "scikit learn|sklearn",
    "PyTorch": "pytorch",
    "TensorFlow": "tensorflow",
    "Machine learning": "machine learning|apprentissage automatique",
    "Deep learning": "deep learning|apprentissage profond",
    "LLM": "llm|llms|large language model|large language models",
    "RAG": "retrieval augmented generation|rag",
    "Power BI": "power bi|powerbi",
    "Tableau": "tableau software|tableau desktop",
    "Excel": "excel",
    "Spark": "apache spark|pyspark",
    "Kafka": "kafka",
    "Airflow": "airflow",
    "REST": "rest api|api rest|restful",
    "GraphQL": "graphql",
    "gRPC": "grpc",
    "Postman": "postman",
    "Pytest": "pytest",
    "JUnit": "junit",
    "Selenium": "selenium",
    "SonarQube": "sonarqube",
    "Agile": "agile|agiles",
    "Scrum": "scrum",
    "Jira": "jira",
    "Confluence": "confluence",
    "ITIL": "itil",
    "TOEIC": "toeic",
    "TOEFL": "toefl",
}
SKILLS.update(
    {
        "OSPF": "ospf",
        "RIP": "rip|routing information protocol",
        "5G": "5g|5 g",
        "FTTx/PON": "fttx|ftth|fttb|fttc|pon|gpon|xgs pon",
        "Fibre optique": "fibre optique|fiber optics|optical fiber|optical fibre",
        "VoIP": "voip|voice over ip|voix sur ip",
        "COOJA": "cooja",
        "Contiki-NG": "contiki ng|contiki",
        "Filebeat": "filebeat",
        "Sysmon": "sysmon",
        "Sockets TCP": "sockets tcp|socket tcp|tcp sockets|tcp socket",
        "C": "c language|langage c|programmation c|c programming",
    }
)

IDF = (
    "ile de france|idf|paris|la defense|courbevoie|puteaux|nanterre|suresnes|levallois perret|"
    "boulogne billancourt|issy les moulineaux|velizy villacoublay|velizy|meudon|"
    "montreuil|saint denis|aubervilliers|versailles|saclay|palaiseau|massy|"
    "cergy|guyancourt|rueil malmaison|fontenay sous bois|charenton le pont|ivry sur seine|"
    "hauts de seine|seine saint denis|val de marne|val d oise|essonne|yvelines|seine et marne"
)
MONTHS = (
    "janvier|january",
    "fevrier|february",
    "mars|march",
    "avril|april",
    "mai|may",
    "juin|june",
    "juillet|july",
    "aout|august",
    "septembre|september",
    "octobre|october",
    "novembre|november",
    "decembre|december",
)
MONTH_BY_NAME = {name: month for month, names in enumerate(MONTHS, 1) for name in names.split("|")}
INTERNSHIP = "stage|stagiaire|intern|internship|internships|trainee|pfe|projet de fin d'etudes"
NON_INTERNSHIP = "cdi|cdd|permanent|apprenticeship|alternance|contrat pro"


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^\w']+", " ", text.replace("’", "'")).strip()


def matched(text: str, alternatives: str) -> bool:
    return any(
        re.search(r"(?<!\w)" + re.escape(normalize(word)) + r"(?!\w)", text)
        for word in alternatives.split("|")
        if word.strip()
    )


def skill_text(value: str) -> str:
    # Preserve meaningful punctuation before general text normalization.
    value = re.sub(r"(?i)(?<!\w)c\+\+(?!\w)", " cpp ", value)
    value = re.sub(r"(?i)(?<!\w)c#(?!\w)", " csharp ", value)
    value = re.sub(r"(?i)(?<!\w)\.net\b", " dotnet ", value)
    value = re.sub(r"(?<![\w])C(?![\w+'#])", " c language ", value)
    return normalize(value)


@lru_cache(maxsize=1)
def skill_phrases() -> tuple[dict[str, set[str]], int]:
    phrases = {}
    for skill, terms in SKILLS.items():
        for term in terms.split("|"):
            phrases.setdefault(normalize(term), set()).add(skill)
    return phrases, max(len(term.split()) for term in phrases)


def detect_skills(value: str) -> list[str]:
    tokens = skill_text(value).split()
    phrases, maximum = skill_phrases()
    found = set()
    for length in range(1, maximum + 1):
        for index in range(len(tokens) - length + 1):
            found.update(phrases.get(" ".join(tokens[index : index + length]), ()))
    return [skill for skill in SKILLS if skill in found]


def is_internship(listing: ListingInput, plain: str) -> bool:
    if listing.contract:
        return matched(normalize(listing.contract), INTERNSHIP)
    title = normalize(listing.title)
    if matched(title, INTERNSHIP):
        return True
    if matched(title, NON_INTERNSHIP):
        return False
    return bool(
        re.search(
            r"\b(?:stage|internship)\s+(?:de\s+)?(?:[3-9]\s+(?:mois|months?)|"
            r"fin d'etudes|position|opportunity)|\b(?:offre|sujet|convention) de stage\b|"
            r"\b[3-9]\s*month\s+internship\b|\bas an intern\b",
            normalize(plain),
        )
    )


def infer_start(plain: str) -> tuple[int, int] | None:
    months = "|".join(MONTH_BY_NAME)
    values = {
        (int(year), MONTH_BY_NAME[month])
        for month, year in re.findall(
            rf"\b(?:a partir d'|(?:debut|demarrage|start(?:ing)?(?: date)?|a partir de|des|from)"
            rf"(?:\s+(?:en|in|of|le|the))*\s+)(?:\d{{1,2}}\s+)?({months})\s+(20\d{{2}})\b",
            plain,
        )
    }
    return next(iter(values)) if len(values) == 1 else None


def contextual_domains(text: str, priority: list[str]) -> list[str]:
    sentences = [normalize(sentence) for sentence in re.split(r"[.!?;\n]", text[:20_000])]
    return [
        name
        for name, (action, object_) in CONTEXTS.items()
        if name in priority
        and any(matched(sentence, action) and matched(sentence, object_) for sentence in sentences)
    ]


def evaluate(
    listing: ListingInput,
    plain: str,
    settings: Settings,
    today: date,
) -> tuple[dict, int, list[dict], list[str]]:
    title, description = normalize(listing.title), normalize(plain)
    text = f"{title} {description}"
    intern = is_internship(listing, plain)
    durations = {
        int(value)
        for value in re.findall(
            r"\b(\d{1,2})\s+(?:mois|months?)\b", f"{title} {description[:3500]}"
        )
        if 1 <= int(value) <= 36
    }
    duration_range = bool(re.search(r"\b\d{1,2}\s+(?:a|to)\s+\d{1,2}\s+(?:mois|months?)\b", text))
    duration = listing.duration_months
    if duration is None and len(durations) == 1 and not duration_range:
        duration = next(iter(durations))
    if duration is None and matched(text, "six mois|six months|six month internship"):
        duration = 6
    inferred_start = infer_start(text) if not listing.start_date else None
    start = (
        (listing.start_date.year, listing.start_date.month)
        if listing.start_date
        else inferred_start
    )
    skills = list(
        dict.fromkeys(
            [
                *listing.skills,
                *detect_skills(f"{listing.title} {plain}"),
            ]
        )
    )
    domains = [
        name
        for name in settings.priority_domains
        if name in DOMAINS and matched(text, DOMAINS[name][2])
    ]
    keyword_match = any(matched(text, keyword) for keyword in settings.keywords)
    domain_fraction = max(
        (DOMAINS[name][1] * (1 if matched(title, DOMAINS[name][2]) else 0.8) for name in domains),
        default=0,
    )
    contextual = (
        contextual_domains(plain, settings.priority_domains) if settings.semantic_enabled else []
    )
    contextual = [name for name in contextual if name not in domains]
    if contextual:
        domain_fraction = max(domain_fraction, max(DOMAINS[name][1] * 0.72 for name in contextual))
    domain_evidence = [DOMAINS[name][0] for name in domains] + [
        DOMAINS[name][0] + " (indices contextuels)" for name in contextual
    ]
    domains.extend(contextual)
    if keyword_match:
        domain_fraction = max(domain_fraction, 0.8)
    location = normalize(listing.location or "")
    places = settings.locations or IDF.split("|")
    local = any(matched(location, place) for place in places)
    if not settings.locations:
        local = local or bool(re.search(r"\b(?:75|77|78|91|92|93|94|95)\d{3}\b", location))
        local = local and not bool(re.search(r"\bparis (?:texas|ontario)\b", location))
    target = settings.target_start.year * 12 + settings.target_start.month
    delta = None if start is None else start[0] * 12 + start[1] - target
    published = paris_date(listing.published_at) if listing.published_at else None
    freshness = (today - published).days if published else None
    level = matched(
        text, "fin d'etudes|pfe|bac 5|master|final year|graduate student|etudiant|student"
    )
    employer = any(
        matched(normalize(listing.employer), name) for name in settings.priority_employers
    )
    fractions = [
        (
            "domain",
            domain_fraction,
            ", ".join(domain_evidence)
            or ("Mot-clé personnalisé" if keyword_match else "Domaine cible non identifié"),
        ),
        ("skills", min(len(skills) / 4, 1), ", ".join(skills[:8]) or "Compétences non identifiées"),
        (
            "location",
            1 if local else (0.3 if not location else 0),
            listing.location or "Localisation inconnue",
        ),
        (
            "duration",
            0.5 if duration is None else int(duration == settings.target_months),
            f"{duration} mois" if duration else "Durée inconnue",
        ),
        (
            "start",
            0.5 if delta is None else (1 if delta == 0 else 0.45 if delta == 1 else 0),
            f"{start[0]:04d}-{start[1]:02d}" if start else "Début inconnu",
        ),
        (
            "education",
            1 if level else 0.5 if intern else 0,
            "Profil étudiant ou fin d’études" if level else "Niveau non précisé",
        ),
        (
            "freshness",
            0.2
            if freshness is None
            else (1 if 0 <= freshness <= 7 else 0.5 if 7 < freshness <= 30 else 0),
            published.isoformat() if published else "Date de publication inconnue",
        ),
        (
            "employer",
            int(employer),
            "Entreprise suivie" if employer else "Entreprise hors préférences",
        ),
    ]
    reasons = [
        {
            "criterion": key,
            "points": round(getattr(settings.weights, key) * value),
            "max": getattr(settings.weights, key),
            "detail": reason,
        }
        for key, value, reason in fractions
    ]
    score = sum(reason["points"] for reason in reasons)
    if not intern and score > 49:
        reasons.append(
            {
                "criterion": "contract",
                "points": 49 - score,
                "max": 0,
                "detail": "Stage non identifié : score plafonné à 49",
            }
        )
        score = 49
    remote = listing.remote
    if remote is None and matched(location, "remote|teletravail|hybrid|hybride"):
        remote = "hybride" if matched(location, "hybrid|hybride") else "télétravail"
    fields = {
        "location": listing.location,
        "contract": listing.contract or ("Stage" if intern else None),
        "duration_months": duration,
        "start_date": listing.start_date.isoformat()
        if listing.start_date
        else (f"{start[0]:04d}-{start[1]:02d}" if start else None),
        "remote": remote,
        "skills": skills,
        "internship": intern,
        "provenance": {
            "location": "source" if listing.location else "unknown",
            "contract": "source" if listing.contract else ("inferred" if intern else "unknown"),
            "duration_months": "source"
            if listing.duration_months
            else ("inferred" if duration else "unknown"),
            "start_date": "source" if listing.start_date else ("inferred" if start else "unknown"),
            "remote": "source" if listing.remote else ("inferred" if remote else "unknown"),
            "skills": {
                skill: "source" if skill in listing.skills else "inferred" for skill in skills
            },
        },
    }
    return fields, score, reasons, domains


def category(score: int) -> str:
    if score >= 85:
        return "Priorité très élevée"
    if score >= 70:
        return "Intéressante"
    if score >= 50:
        return "À examiner"
    return "Faible pertinence"
