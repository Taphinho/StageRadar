# Connecteurs

| Source | Mode disponible | Périmètre |
| --- | --- | --- |
| Greenhouse Job Board API | Automatique, sans compte | Tableaux publics Dataiku, Mirakl et Mirakl Labs par défaut. |
| SmartRecruiters Posting API | Automatique, sans compte | Publications françaises de Sopra Steria, Devoteam, Wavestone, Advens et Sia. Les détails sont chargés pour les stages identifiés en Île-de-France, et dans toute la France pour Advens. |
| Lever Postings API | Automatique, sans compte | Theodo par défaut. Compatible avec les instances globale et européenne. |
| Ashby Job Postings API | Automatique, sans compte | Mistral AI et MakiPeople par défaut. Seules les offres listées sont retenues. |
| Teamtailor RSS | Automatique, sans compte | Flux carrière de CybelAngel, Hub One, Payplug, I-Tracing, Almond, du portail international Orange Cyberdefense et de VINCI Energies Young Talents Days. |
| SAP SuccessFactors | Automatique, sans compte | Flux RSS de Capgemini, Arkema, Bouygues Telecom et du portail commun Atos / Eviden. Stages situés en France. |
| Thales | Automatique, sans compte | Stages repérables dans le sitemap du portail carrière français et localisés en France. |
| Orange Jobs France | Automatique | Sitemap français et fiches publiques, dont Orange Cyberdefense. |
| Workday | Automatique | Recherches publiques et fiches France d’Airbus, Accenture, Deloitte, PwC Campus, Onepoint et Chanel. |
| Sites carrière | Automatique | Synetis, Intrinsec, Société Générale, Crédit Agricole, EY étudiants, KPMG, CGI, BPCE, BNP Paribas et Dassault Systèmes. |
| LinkedIn Jobs, Indeed, HelloWork, Welcome to the Jungle, JobTeaser et Apec | Import manuel | Collez une annonce consultée directement ou reçue par alerte. |
| France Travail | Import manuel | L’accès à l’API Offres d’emploi est restreint et passe par une demande auprès de France Travail. |
| Autres sites carrière, alertes e-mail, autres RSS et API | Import manuel | Sélectionnez la provenance et fournissez le lien d’origine. La lecture de boîte e-mail et l’abonnement à un flux arbitraire ne sont pas implémentés. |

[Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) · [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/endpoints) · [Lever Postings API](https://github.com/lever/postings-api#lever-postings-api) · [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) · [Flux RSS Teamtailor](https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide) · [Conditions d’accès France Travail](https://www.data.gouv.fr/dataservices/api-offres-demploi)

## Employeurs prioritaires

| Employeur | Accès depuis StageRadar |
| --- | --- |
| Thales | Collecte automatique à partir du sitemap français. |
| Orange Cyberdefense | RSS international. Accès direct aux offres françaises sur [Orange Jobs](https://orange.jobs/fr/fr/nos-activites/orange-cyberdefense). |
| Airbus | Collecte Workday France. [Portail stages Airbus](https://www.airbus.com/fr/careers/students-and-graduates/interns/internships-in-france). |
| Capgemini | RSS SuccessFactors. |
| Sopra Steria | API SmartRecruiters. |
| Eviden | RSS Atos. L’employeur est nommé Eviden lorsque l’introduction de l’offre le désigne explicitement. |
| Accenture | Collecte Workday France. [Recherche Accenture](https://www.accenture.com/fr-fr/careers/jobsearch). |
| CGI | Recherche Njoyn publique des stages France. [Site carrière CGI France](https://www.cgi.com/france/fr-fr/recrute). |
| Wavestone | API SmartRecruiters. |
| BNP Paribas | Liste publique filtrée sur Stage et fiches structurées. [Stages BNP Paribas](https://group.bnpparibas/emploi-carriere/candidat-etudiant/stage-alternance). |
| Société Générale | Liste publique et fiches structurées. [Stages Société Générale](https://careers.societegenerale.com/stages). |
| BPCE | Recherche publique de stages en France. [Site recrutement BPCE](https://recrutement.bpce.fr/offres-emploi?tax_country=france&external=false). |
| Crédit Agricole | Pages publiques parcourues progressivement et fiches structurées. [Offres Crédit Agricole](https://groupecreditagricole.jobs/fr/nos-offres/). |
| Dassault Systèmes | Sitemap carrière et fiches françaises. [Offres Dassault Systèmes](https://www.3ds.com/fr/careers/jobs). |
| Atos | RSS SuccessFactors partagé avec Eviden. |
| Devoteam | API SmartRecruiters. |
| NEVERHACK | Accès direct au [site carrière NEVERHACK](https://neverhack.com/careers), qui renvoie vers ses annonces LinkedIn. |
| Advens | API SmartRecruiters. |
| I-Tracing | RSS Teamtailor. |
| Synetis | Widget public WelcomeKit utilisé par l’employeur. [Offres Synetis](https://www.synetis.com/carriere/offres-emplois/). |
| Intrinsec | Widget public Boond utilisé par l’employeur. [Recrutement Intrinsec](https://www.intrinsec.com/rejoindre-intrinsec/). |
| FTI Consulting | Accès direct aux [offres FTI pour étudiants et jeunes diplômés en France](https://fticonsult.referrals.selectminds.com/ftistudentcareers/page/france-studentsgraduate-opportunities-1239). |
| Deloitte | Collecte Workday France. [Portail Deloitte France](https://fina.wd103.myworkdayjobs.com/fr-FR/DeloitteRecrute). |
| EY | Recherche publique Yello France et fiches. [Portail étudiants et jeunes diplômés](https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q?locale=fr), proposé par [EY France](https://www.ey.com/fr_fr/careers/job-search). |
| KPMG | Sitemap et fiches structurées. [Stages et alternances KPMG](https://emplois.kpmg.fr/profils-stages-alternances). |
| PwC | Collecte Workday Global Campus Careers, France. [Offres de stage PwC](https://carrieres.pwc.fr/fr/stage-offres.html). |
| Onepoint | Collecte Workday France. [Recrutement Onepoint](https://www.groupeonepoint.com/fr/nous-rejoindre/). |
| Sia | [API SmartRecruiters](https://careers.smartrecruiters.com/Sia). |
| Almond | [RSS Teamtailor](https://careers.almond.eu/jobs.rss). |
| Chanel | Collecte Workday France. [Portail Chanel](https://cc.wd3.myworkdayjobs.com/fr-FR/ChanelCareers). |
| VINCI Energies | Collecte du [RSS Young Talents Days](https://youngtalentsdays.vinci-energies.com/jobs.rss) et accès direct au [portail général](https://www.vinci-energies.com/job-offer/). |
| Axians | Offres identifiées dans le flux Young Talents Days et accès direct à la [page de recrutement IT](https://www.axians.fr/axians-communication-cloud-carriere/). |

La couverture de chaque portail, son état réel et ses liens figurent dans l’onglet **Sources**. Les offres trouvées sur ces portails peuvent être ajoutées avec **Importer une offre**.

## Configurer un tableau

Les variables suivantes associent les identifiants des tableaux aux noms d’entreprise.

| Variable | Identifiant attendu |
| --- | --- |
| `STAGERADAR_GREENHOUSE_BOARDS` | Nom du tableau, par exemple `dataiku` |
| `STAGERADAR_SMARTRECRUITERS_COMPANIES` | Identifiant de l’entreprise, par exemple `SopraSteria1` |
| `STAGERADAR_LEVER_BOARDS` | Instance puis tableau, par exemple `global:theodo`. Utilisez `eu:` pour un portail `jobs.eu.lever.co`. |
| `STAGERADAR_ASHBY_BOARDS` | Dernier segment de la page publique, par exemple `mistral.ai` |
| `STAGERADAR_SUCCESSFACTORS_BOARDS` | Identifiants de portails vérifiés, `capgemini`, `arkema`, `bouygues` et `atos`. |
| `STAGERADAR_TEAMTAILOR_BOARDS` | Sous-domaine Teamtailor, par exemple `cybelangel`. `orangecyberdefense`, `almond` et `vinci-energies` utilisent leurs domaines officiels. |
| `STAGERADAR_THALES_ENABLED` | `false` désactive la collecte Thales. |

Une valeur `{}` désactive un fournisseur. Les nouveaux tableaux par défaut s’appliquent au prochain démarrage, sauf si leurs variables sont déjà renseignées dans votre `.env`. Avant d’ajouter un tableau, vérifiez la documentation officielle, les droits de réutilisation, les règles robots.txt applicables et les limites de requêtes de la source.

Les collecteurs interrogent uniquement les hôtes HTTPS prévus pour chaque fournisseur, en lecture seule et sans suivre les redirections. Les liens d’annonce, de candidature et de détail fournis par les données ne pilotent pas les destinations HTTP du serveur. Les appels ont un délai maximal et une taille de réponse plafonnée. Le code applique un backoff pour les erreurs temporaires et conserve la prochaine date autorisée par `Retry-After` dans SQLite. Les sites nécessitant une session, un CAPTCHA ou un accès privé passent par l’import.

## Ce qui est collecté et conservé

- Greenhouse livre les descriptions avec la liste. Le connecteur peut donc identifier des stages dont l’intitulé est générique. Il utilise la date de première publication quand l’API la fournit.
- SmartRecruiters liste les offres publiques françaises et charge au plus 24 fiches nouvelles ou republiées par tableau et par passage. Les fiches dont la date de publication n’a pas changé sont réutilisées. Les stages sont présélectionnés par l’intitulé ou le type de contrat. Advens est suivi dans toute la France, avec traitement prioritaire des fiches d’Île-de-France. Un stage générique et mal renseigné dans l’API peut échapper à cette présélection.
- Lever conserve les descriptions et les listes de compétences. Le champ technique de création n’est pas utilisé comme date de publication.
- Ashby fournit les descriptions, les localisations et l’horodatage de publication quand ces champs sont renseignés.
- Les flux Teamtailor contiennent les descriptions et les liens publics. Une annonce peut disparaître du flux sans être fermée, donc cette omission ne fait pas expirer l’offre.
- SuccessFactors lit les flux RSS de recrutement des portails vérifiés. Ces flux annoncent une durée de cache de 12 heures, utilisée comme intervalle minimal entre collectes. Leur date d’expiration RSS ne sert pas à déterminer la fermeture des offres. Les autres portails SuccessFactors restent disponibles à l’import manuel.
- Thales lit les sitemaps publics et les données structurées des fiches. Il privilégie la date Workday intégrée à la fiche lorsqu’elle correspond à la référence de l’offre. Il ouvre au plus 20 fiches par passage, en commençant par les intitulés de cybersécurité et techniques. Après chaque démarrage, une partie de ce quota sert à relire les fiches déjà connues. La disparition d’un lien du sitemap ne suffit pas à fermer l’offre.
- Les annonces partagent un modèle normalisé. La fiche conserve une copie de chaque provenance avec sa description, son identifiant et ses liens. Les changements significatifs créent une révision. Le score et les déductions peuvent être recalculés à partir de l’offre.
- La déduplication privilégie l’identifiant stable de la source et l’URL canonique. Entre sources, elle utilise aussi une similarité textuelle élevée lorsque l’entreprise, le titre et la localisation concordent et que les champs connus restent compatibles. Les correspondances ambiguës restent séparées.
- Deux instantanés complets réussis sans une annonce peuvent fermer sa provenance automatique. Une autre provenance ouverte maintient l’offre active. Un import manuel reste visible et peut être archivé ou masqué. Une panne ou une pagination incomplète ne suffit pas pour déclarer une offre expirée.

## Cas de SAP SuccessFactors

Les portails de [Capgemini](https://careers.capgemini.com/sitemal.xml) et d’[Arkema](https://jobs.arkema.com/sitemal.xml) publient des flux RSS sur `/sitemal.xml`. L’API OData de recrutement nécessite des droits propres à l’employeur. SAP propose aussi des exports de syndication XML configurés par l’employeur. [Droits d’accès OData](https://help.sap.com/docs/SAP_SUCCESSFACTORS_PLATFORM/d599f15995d348a1b45ba5603e2aba9b/5511f05d636f414084a22909bc35f509.html) · [Gestion des flux SAP](https://help.sap.com/docs/successfactors-recruiting/setting-up-and-maintaining-sap-successfactors-recruiting/aa846a9515204a2d8e1dbd62c79fc103.html)

## Couverture et dates des nouveaux portails

- Les recherches Workday utilisent les requêtes publiques du portail candidat, sans compte. Les destinations sont limitées aux tenants vérifiés. Les fiches de pays autres que la France sont écartées. La date `startDate` de ces réponses correspond à la publication, elle ne devient jamais une date de début du stage.
- Les collecteurs à fiches chargent un nombre borné de nouvelles annonces et relisent régulièrement les annonces connues. Un premier passage partiel peut déjà fournir des stages. Les annonces restantes sont prises en charge lors des passages suivants.
- Crédit Agricole parcourt quatre pages publiques par passage et poursuit les suivantes au prochain passage. Ce parcours complète progressivement les annonces récentes et plus anciennes.
- EY ne donne pas d’année exploitable dans la date de liste vérifiée. La publication reste inconnue. Ces stages figurent dans Explorer, mais ne sont pas présentés comme récemment publiés dans Suggestions.
- Orange Jobs peut republier des dates techniques. Le collecteur utilise la date de publication explicitement indiquée dans la description, quand elle existe.
- Les dates de modification de BPCE et de Crédit Agricole ne remplacent pas la publication d’origine.
- Les sorties sélectives ou partielles ne déclarent pas une offre fermée sur la seule disparition de son URL.

## Résultats de l’audit du 8 novembre 2026

Les flux Hub One, I-Tracing et Orange Cyberdefense international répondaient, mais ne contenaient aucun stage français retenu. Cela représente un flux accessible sans stage correspondant à la collecte actuelle. Orange Jobs France apporte une couverture complémentaire.

BNP Paribas renvoyait HTTP 403 avec la première requête serveur. Ses pages répondent avec les en-têtes Web ordinaires et sont désormais collectées. Le portail France étudiants de FTI Consulting affichait explicitement aucune offre disponible. NEVERHACK renvoyait vers LinkedIn, dont la page d’offres répondait HTTP 403 depuis le serveur. Ces portails conservent un accès direct dans Sources.

Le collecteur Thales relit désormais ses fiches connues par cycles. Les relectures différées de fiches déjà enregistrées ne sont plus comptées comme annonces manquantes.

Les variables `STAGERADAR_WORKDAY_BOARDS` et `STAGERADAR_CAREER_SITES` pilotent les nouveaux portails. Une valeur `{}` pour Workday ou `[]` pour les sites carrière les désactive. Les nouveaux connecteurs respectent les bornes HTTP, les délais de reprise et les exclusions enregistrées.

## Lire l’état d’une source

| État | Signification |
| --- | --- |
| Opérationnelle | Dernier instantané complet |
| Dégradée | Instantané partiel, ou échec après un passage réussi |
| Indisponible | Aucun passage réussi enregistré |
| Non configurée | Collecte automatique absente. L’import manuel est disponible pour les sources listées. |

Consultez l’historique pour distinguer un passage incomplet, une limite de débit et une erreur de format. Les champs publics des annonces peuvent contenir des données personnelles publiées par le recruteur. Conservez la base à usage personnel et respectez les droits et conditions de chaque source avant toute redistribution.
