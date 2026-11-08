# StageRadar

Veille personnelle de stages, en priorité en cybersécurité et en informatique. Le profil initial vise un stage de fin d’études de six mois à partir d’avril 2027 en Île-de-France. StageRadar surveille les sources configurées et sa couverture dépend des tableaux et des imports disponibles.

## Démarrer sur Debian 13

Depuis le dossier StageRadar, avec Docker et le plugin Docker Compose v2 (ou ultérieur) accessibles à votre compte.

```sh
cp -n .env.example .env
chmod 600 .env
docker compose up -d --build
```

Ouvrez [StageRadar](http://127.0.0.1:8000). La migration SQLite et la première collecte sont lancées automatiquement. Ouvrez **Sources** pour suivre la collecte. Une source partielle peut déjà fournir des offres.

Le volume nommé `stageradar-data` contient la base et survit à l’arrêt et à la recréation du conteneur. Le fichier `.env` est exclu de l’image et du versionnement. Le service est publié sur la boucle locale IPv4. Pour un autre port local, changez `STAGERADAR_PORT` dans `.env`.

| Action | Commande |
| --- | --- |
| État | `docker compose ps` |
| Journal | `docker compose logs -f --tail=100 stageradar` |
| Santé | `curl -fsS http://127.0.0.1:8000/health` |
| Historique | `curl -fsS http://127.0.0.1:8000/api/runs` |
| Collecte à la demande | `curl -fsS -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/collect` |
| Arrêt | `docker compose stop` |
| Relance | `docker compose up -d` |
| Mise à jour après remplacement du code | `docker compose up -d --build` |
| Application des changements de `.env` | `docker compose up -d --force-recreate` |

La collecte à la demande respecte le délai minimal et les limites renvoyées par les fournisseurs. Si l’authentification web est activée, les requêtes API doivent inclure les identifiants. `/health` reste accessible avec un hôte autorisé.

## Utiliser StageRadar

- **Explorer les offres** permet de chercher en français ou en anglais, de filtrer les offres et d’afficher les critères du score. La recherche normalise les accents. Le filtre de période retient les dates de publication connues. Le tri peut suivre la publication ou la première détection. Les fiches indiquent la date fournie par chaque source.
- **Candidatures** rassemble huit statuts, les notes, les dates et les rappels. Les rappels échus sont comptés dans le tableau de bord et le résumé Telegram. L’application ne soumet pas de candidature.
- **Importer une offre** permet de coller les informations d’une annonce ou d’une alerte. Le serveur enregistre les liens tels qu’ils lui sont transmis et ne les visite pas.
- **Mon CV** compare le texte collé aux compétences reconnues dans les annonces ouvertes. Le classement combine la pertinence de l’offre (70 %) et la part de compétences reconnues en commun (30 %). Les écarts signalent les compétences non retrouvées dans le texte fourni. Le texte est traité par l’instance locale sans être enregistré ni envoyé à un service d’IA.
- **Paramètres** affiche la configuration effective. Les modifications se font dans `.env`, avec recréation du service.

## Sources, scoring et notifications

- [Connecteurs et règles de collecte](docs/connecteurs.md)
- [Configuration et diagnostic Telegram](docs/telegram.md)
- [API OpenAPI](http://127.0.0.1:8000/docs) et [schéma JSON](http://127.0.0.1:8000/openapi.json). Le rendu de la documentation Swagger peut nécessiter un accès au CDN de Swagger UI.

Par défaut, les collectes se déclenchent toutes les 30 minutes. Les tâches utilisent le fuseau Europe/Paris pour le résumé quotidien et la maintenance. Les dates de détection et de collecte sont stockées en UTC.

Les critères du score totalisent 100 points. Les poids par défaut sont domaine 35, compétences 10, localisation 18, durée 10, début 12, niveau étudiant 7, fraîcheur 5 et entreprise 3. Les catégories sont 85–100 très élevée, 70–84 intéressante, 50–69 à examiner et 0–49 faible. Une durée ou un début inconnu reçoit une partie des points. Une indication incompatible réduit les points. L’offre conserve ses champs sources et signale les déductions.

Les paramètres de recherche et les pondérations sont détaillés dans [`.env.example`](.env.example). Les listes et dictionnaires sont au format JSON. `STAGERADAR_SEMANTIC_ENABLED=true` ajoute une analyse contextuelle locale fondée sur des associations de concepts au sein de la même phrase. Elle est désactivée par défaut et ne nécessite ni modèle téléchargé ni service distant.

## Architecture et exploitation

- `stageradar/collectors/` lit les API publiques et retourne des objets normalisés.
- `collection.py` ordonnance les passages par source et enregistre les résultats. `offers.py` rapproche les annonces, conserve les versions et appelle `scoring.py`.
- `database.py` décrit les tables SQLite/SQLAlchemy. `migrations/` contient la migration Alembic versionnée, appliquée au démarrage.
- `telegram.py` utilise une file persistante. `runtime.py` configure APScheduler et verrouille le répertoire SQLite pour éviter deux instances concurrentes.
- `main.py` sert l’API FastAPI et `web/` contient le tableau de bord responsive en HTML, CSS et JavaScript natifs.

Le conteneur fonctionne sans privilèges supplémentaires, avec un système de fichiers en lecture seule et un volume de données dédié. Pour un accès distant, conservez la publication sur la boucle locale et placez un proxy TLS devant elle. Ajoutez le nom d’hôte exact à `STAGERADAR_ALLOWED_HOSTS`, gardez `127.0.0.1` pour le contrôle de santé et configurez `STAGERADAR_WEB_USERNAME` et `STAGERADAR_WEB_PASSWORD` (au moins 16 caractères). Le proxy doit préserver l’en-tête `Host`. Configurez la rétention des journaux du proxy en fonction de l’usage personnel de l’instance.

Pour sauvegarder SQLite, arrêtez le service et copiez l’intégralité du volume, fichiers WAL éventuels compris. Pour vérifier la consommation en cours de collecte, utilisez `docker stats --no-stream "$(docker compose ps -q stageradar)"`.

## Développement local

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
PYTHON_BIN=python ./scripts/init.sh
python -m uvicorn stageradar.main:create_app --factory --host 127.0.0.1 --port 8000
```

Le script crée le répertoire `data/` par défaut et applique les migrations. `python -m stageradar collect` exécute une collecte ponctuelle et affiche son résultat lorsque le service est arrêté. Pour un test séparé, choisissez un autre `STAGERADAR_DATA_DIR`.

```sh
python -m pytest -q
ruff check .
ruff format --check .
node --check stageradar/web/app.js
docker compose config --quiet
```

Les tests utilisent des offres synthétiques et des transports HTTP simulés. Une installation neuve démarre avec une base vide. Le logiciel est distribué sous [licence MIT](LICENSE). Les annonces conservent leurs droits et conditions d’origine.
