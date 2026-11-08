# Telegram

## Relier votre bot

1. Créez un bot dédié avec [@BotFather](https://t.me/BotFather) en utilisant `/newbot`.
2. Ouvrez une conversation privée avec ce bot et envoyez-lui `/start`.
3. Récupérez le champ numérique `message.chat.id`. Vous pouvez interroger `getUpdates` avant de démarrer StageRadar en utilisant ce script local. Il masque le token pendant la saisie et affiche uniquement les identifiants de chat.

   ```sh
   python3 - <<'PY'
   import getpass
   import json
   import re
   from urllib.error import URLError
   from urllib.request import urlopen

   token = getpass.getpass("Token du bot : ")
   if not re.fullmatch(r"\d{4,20}:[A-Za-z0-9_-]{20,100}", token):
       raise SystemExit("Format du token invalide.")
   try:
       with urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10) as response:
           data = json.load(response)
   except (URLError, ValueError):
       raise SystemExit("Impossible de lire getUpdates. Vérifiez le bot et l’absence de webhook.") from None
   chats = {
       update["message"]["chat"]["id"]
       for update in data.get("result", []) if "message" in update
   }
   print(*sorted(chats), sep="\n")
   if not chats:
       print("Aucun chat. Envoyez un nouveau message au bot puis relancez la commande.")
   PY
   ```

4. Renseignez `STAGERADAR_TELEGRAM_TOKEN` et `STAGERADAR_TELEGRAM_CHAT_ID` dans votre fichier `.env` local. Utilisez `chmod 600 .env`, puis appliquez les valeurs avec `docker compose up -d --force-recreate`.
5. Envoyez `/help` dans la conversation configurée. Le bot répond aux commandes `/start`, `/latest`, `/top`, `/stats`, `/sources` et `/help` du chat autorisé. Un bot avec webhook actif ou un second consommateur de `getUpdates` peut empêcher cette lecture.

[Documentation de Telegram Bot API](https://core.telegram.org/bots/api)

## Alertes, résumé et reprise

`STAGERADAR_ALERT_THRESHOLD` vaut 70 par défaut. Une offre admissible est placée dans la file SQLite après déduplication. Le traitement a lieu toutes les 15 secondes. Les alertes mises en file entre 22 h et 8 h, heure de Paris, sont différées. Configurez `STAGERADAR_QUIET_START` et `STAGERADAR_QUIET_END` avec la même heure pour désactiver cette plage.

Le résumé de 8 h couvre la fenêtre depuis 8 h la veille et indique les rappels échus. Il est rattrapé le jour même si l’instance redémarre après 8 h. Réglez `STAGERADAR_TELEGRAM_DIGEST=false` pour le désactiver, ou `STAGERADAR_TELEGRAM_COMMANDS=false` pour désactiver les réponses.

En cas de limitation de débit, StageRadar temporise et reprend les envois. Un délai après la transmission ou un arrêt pendant l’envoi peut laisser la livraison dans l’état `uncertain`. Telegram ne fournit pas de clé d’idempotence pour `sendMessage`. StageRadar ne retente pas automatiquement ces cas afin d’éviter les doublons.

## Diagnostic

- **Paramètres** indique si Telegram est configuré et compte les états de la file. Un état `failed` correspond notamment à un token ou un chat refusé.
- `docker compose logs --tail=100 stageradar` permet d’observer les échecs sans afficher le token.
- Si le bot ne répond pas, vérifiez que vous lui avez écrit en premier, que le chat est autorisé et que les commandes sont activées.
