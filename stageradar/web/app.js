const $ = (selector) => document.querySelector(selector);
const suggestionDays = 4;
const suggestionMinScore = 70;
const pages = {
  dashboard: ["Vue d’ensemble", "Les dernières détections et le suivi de vos candidatures."],
  suggestions: ["Suggestions", `Stages publiés dans les ${suggestionDays} derniers jours et classés par pertinence à partir de ${suggestionMinScore}/100.`],
  offers: ["Explorer les offres", "Filtrez les annonces et consultez le détail de leur pertinence."],
  applications: ["Candidatures", "Retrouvez vos prochaines actions et l’avancement de vos candidatures."],
  excluded: ["Offres exclues", "Retrouvez les offres mises de côté et rétablissez celles qui vous intéressent."],
  profile: ["Mon CV", "Comparez vos compétences aux offres disponibles."],
  sources: ["Sources", "Consultez l’état des connecteurs et l’historique des collectes."],
  settings: ["Paramètres", "Consultez la configuration effective et l’état des notifications."],
};
const statuses = {
  review: "À examiner", todo: "À postuler", sent: "Candidature envoyée", follow_up: "Relance prévue",
  interview: "Entretien", rejected: "Refus", offer: "Offre obtenue", archived: "Archivée",
};
const health = {
  operational: "Opérationnelle", degraded: "Dégradée", unavailable: "Indisponible",
  unconfigured: "Non configurée en collecte automatique",
};
const resultLabels = {
  ok: "Réussie", partial: "Partielle", running: "En cours", waiting: "En attente",
  interrupted: "Interrompue", failed: "Échec",
};
let viewVersion = 0;

function el(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function button(label, handler, className = "secondary") {
  const node = el("button", label, className);
  node.type = "button";
  node.addEventListener("click", handler);
  return node;
}

function external(label, url, className = "link-button") {
  const link = el("a", label, className);
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return el("span", label);
    link.href = parsed.href;
    link.rel = "noopener noreferrer";
    link.target = "_blank";
  } catch {
    return el("span", label);
  }
  return link;
}

function thalesWorkday(offer) {
  const original = new URL(offer.original_url);
  const match = original.pathname.match(/^\/fr\/fr\/job\/(R\d+)(?:\/|$)/);
  if (original.hostname !== "careers.thalesgroup.com" || !match) return null;
  const reference = match[1];
  const direct = new URL(offer.apply_url);
  if (direct.hostname === "thales.wd3.myworkdayjobs.com") {
    return { label: "Ouvrir dans Workday ↗", url: direct.href, reference };
  }
  return {
    label: "Chercher dans Workday ↗",
    url: "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers?q=" + reference,
    reference,
  };
}

async function api(path, method = "GET", body = {}) {
  const options = method === "GET" ? {} : {
    method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  };
  const response = await fetch("/api" + path, options);
  const data = await response.json();
  if (!response.ok) {
    const message = Array.isArray(data.detail)
      ? data.detail.map((entry) => entry.loc.slice(1).join(".") + " · " + entry.msg).join(" / ")
      : data.detail;
    throw new Error(message || "Requête impossible.");
  }
  return data;
}

function tell(message) {
  $("#feedback").textContent = message;
  $("#feedback").hidden = !message;
}

function putOptions(select, entries) {
  for (const [key, label] of Object.entries(entries)) {
    select.add(new Option(label, key));
  }
}

function fmtTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short", timeStyle: "short", timeZone: "Europe/Paris",
  }).format(new Date(value));
}

function fmtPublication(value) {
  if (!value) return "Date de publication inconnue";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long", timeZone: "Europe/Paris",
  }).format(new Date(value));
}

function section(title, body) {
  const node = el("section", undefined, "panel");
  node.append(el("h2", title), body);
  return node;
}

function facts(entries) {
  const list = el("dl");
  for (const [label, value] of entries) list.append(el("dt", label), el("dd", value ?? "—"));
  return list;
}

async function showDashboard(version) {
  const [stats, latest] = await Promise.all([api("/stats"), api("/offers?sort=date&limit=4")]);
  if (version !== viewVersion) return;
  const metrics = el("div", undefined, "metrics");
  for (const [label, value] of [
    ["Offres détectées", stats.total], ["Nouvelles aujourd’hui", stats.today],
    ["Priorité très élevée", stats.high], ["Candidatures envoyées", stats.sent],
    ["Entretiens et offres", stats.interviews], ["Rappels à traiter", stats.reminders],
  ]) {
    const item = el("div", undefined, "metric");
    item.append(el("strong", value), el("span", label));
    metrics.append(item);
  }
  const chart = el("div", undefined, "chart");
  const maximum = Math.max(1, ...stats.trend.map((day) => day.count));
  for (const day of stats.trend) {
    const row = el("div", undefined, "chart-row");
    const date = day.date.slice(8) + "/" + day.date.slice(5, 7);
    const bar = el("progress");
    bar.max = maximum;
    bar.value = day.count;
    bar.setAttribute("aria-label", date + " · " + day.count + " détections");
    row.append(el("span", date), bar, el("span", day.count));
    chart.append(row);
  }
  const recent = el("div");
  if (latest.items.length) latest.items.forEach((offer) => recent.append(offerCard(offer)));
  else recent.append(el("p", "Aucune offre enregistrée. Importez une annonce ou vérifiez les sources.", "muted"));
  $("#dashboard").replaceChildren(metrics, section("Détections sur 14 jours", chart), section("Dernières offres détectées", recent));
}

function offerCard(offer) {
  const card = el("article", undefined, "card");
  const top = el("div", undefined, "card-top");
  const info = el("div");
  info.append(el("h3", offer.title), el("p", [offer.employer, offer.location].filter(Boolean).join(" · "), "muted"));
  const publication = offer.published_at ? "Publication le " + fmtPublication(offer.published_at) : fmtPublication(null);
  info.append(el("p", publication + " · Détection le " + fmtTime(offer.first_seen), "muted"));
  const score = el("span", offer.score + "/100", "pill score" + (offer.score >= 85 ? " score-high" : ""));
  score.title = offer.category;
  top.append(info, score);
  const tags = el("div");
  const indicators = [statuses[offer.status], offer.expired && "Expirée", offer.hidden && "Exclue",
    offer.reminder_on && "Rappel le " + offer.reminder_on, ...offer.skills.slice(0, 6)];
  indicators.filter(Boolean).forEach((item) => tags.append(el("span", item, "pill")));
  const actions = el("div", undefined, "actions");
  const workday = thalesWorkday(offer);
  actions.append(
    button("Détails et candidature", () => showDetail(offer.id).catch((error) => tell(error.message))),
    external(workday?.label || "Ouvrir l’annonce ↗", workday?.url || offer.apply_url),
    button(offer.favorite ? "Retirer des favoris" : "Mettre en favori", () => changeOffer(offer.id, {favorite: !offer.favorite})),
    button(offer.hidden ? "Rétablir" : "Exclure", () => changeOffer(offer.id, {hidden: !offer.hidden}), "secondary exclude-button"),
  );
  card.append(top, tags, actions);
  return card;
}

async function changeOffer(id, changes) {
  try {
    await api("/offers/" + id, "PATCH", changes);
    if (Object.hasOwn(changes, "hidden")) {
      if ($("#detail-dialog").open) $("#detail-dialog").close();
      tell(changes.hidden ? "Offre exclue. Vous pouvez la rétablir dans « Offres exclues »." : "Offre rétablie.");
    }
    await render();
  } catch (error) {
    tell(error.message);
  }
}

async function excludeAllThales(control) {
  control.disabled = true;
  try {
    const result = await api("/offers/exclude-thales", "POST");
    await render();
    tell(result.excluded + " offre(s) Thales exclue(s). Retrouvez-les dans « Offres exclues ».");
  } catch (error) {
    tell(error.message);
  } finally {
    control.disabled = false;
  }
}

async function showList(page, version, offset = 0) {
  const suggestions = page === "suggestions";
  const excluded = page === "excluded";
  const applications = page === "applications";
  const form = $(applications ? "#application-filters" : "#filters");
  const params = suggestions
    ? new URLSearchParams({published_days: suggestionDays, min_score: suggestionMinScore, sort: "score"})
    : excluded
    ? new URLSearchParams({excluded_only: "true", expired: "true", sort: "date"})
    : new URLSearchParams([...new FormData(form)].filter(([, value]) => value));
  if (applications) {
    params.set("expired", "true");
    params.set("sort", "date");
  }
  params.set("limit", "20");
  params.set("offset", offset);
  const result = await api("/offers?" + params);
  if (version !== viewVersion) return;
  const targets = {suggestions: "#suggestions", excluded: "#excluded", applications: "#application-results", offers: "#offer-results"};
  const target = $(targets[page]);
  target.replaceChildren(el("p", result.total + " offre(s)", "muted results-heading"));
  if (suggestions || page === "offers") {
    const actions = el("div", undefined, "actions");
    const exclude = button("Exclure toutes les offres Thales",
      (event) => excludeAllThales(event.currentTarget), "secondary exclude-button");
    exclude.title = "Exclut toutes les offres Thales déjà enregistrées, sur toutes les pages.";
    actions.append(exclude);
    target.append(actions);
  }
  if (excluded) {
    target.append(button("Rétablir toutes les offres Thales", async (event) => {
      const control = event.currentTarget;
      control.disabled = true;
      try {
        const restored = await api("/offers/restore-thales", "POST");
        await render();
        tell(restored.restored + " offre(s) Thales rétablie(s).");
      } catch (error) { tell(error.message); }
      finally { control.disabled = false; }
    }));
  }
  if (!result.items.length) {
    const empty = suggestions
      ? "Aucun stage récent n’atteint le seuil de pertinence."
      : excluded
      ? "Aucune offre exclue."
      : "Aucune offre pour ces filtres.";
    target.append(el("p", empty, "panel"));
  }
  for (const offer of result.items) target.append(offerCard(offer));
  const pager = el("div", undefined, "actions");
  if (offset > 0) pager.append(button("Précédent", () => render(offset - 20)));
  if (offset + result.items.length < result.total) pager.append(button("Suivant", () => render(offset + 20)));
  target.append(pager);
}

function offerDescription(offer) {
  const source = offer.sources.find((listing) => listing.source === offer.primary_source);
  const raw = source?.snapshot.description || offer.description;
  const container = el("div", undefined, "offer-description");
  if (!raw?.trim()) {
    container.append(el("p", "Description indisponible.", "muted"));
    return container;
  }

  // Parse inside an inert template and rebuild only text and formatting, without attributes.
  const template = el("template");
  template.innerHTML = raw;
  if (!template.content.childElementCount && /&lt;\/?[a-z]/i.test(raw)) {
    template.innerHTML = template.content.textContent;
  }
  const formats = new Set(["p", "ul", "ol", "li", "br", "div", "strong", "b", "em", "i", "blockquote"]);
  const omitted = new Set(["script", "style", "template", "iframe", "object", "svg", "math"]);
  function copyContent(parent, children) {
    for (const child of children) {
      if (child.nodeType === Node.TEXT_NODE) {
        parent.append(document.createTextNode(child.textContent));
      } else if (child.nodeType === Node.ELEMENT_NODE && !omitted.has(child.localName)) {
        const tag = child.localName;
        const safe = /^h[1-6]$/.test(tag) ? "h4" : formats.has(tag) ? tag : null;
        const node = safe ? el(safe) : parent;
        copyContent(node, child.childNodes);
        if (safe && (safe === "br" || node.textContent.trim())) parent.append(node);
      }
    }
  }
  copyContent(container, template.content.childNodes);
  if (!container.textContent.trim()) container.append(el("p", "Description indisponible.", "muted"));
  return container;
}

function detailDisclosure(title, content) {
  const details = el("details", undefined, "detail-disclosure");
  details.append(el("summary", title), content);
  return details;
}

async function showDetail(id) {
  const [offer, revisions] = await Promise.all([api("/offers/" + id), api("/offers/" + id + "/revisions")]);
  const dialog = $("#detail-dialog");
  const workday = thalesWorkday(offer);
  $("#detail-title").textContent = offer.title;
  $("#detail-employer").textContent = offer.employer;
  $("#detail-location").textContent = [offer.location, workday?.reference].filter(Boolean).join(" · ");

  const field = (name, value) => {
    if (!value) return "Non précisé";
    return value + (offer.provenance[name] === "inferred" ? " (déduit)" : "");
  };
  const essentials = el("dl", undefined, "detail-facts");
  for (const [label, value] of [
    ["Contrat", field("contract", offer.contract)],
    ["Début", field("start_date", offer.start_date)],
    ["Durée", field("duration_months", offer.duration_months && offer.duration_months + " mois")],
    ["Publication", fmtPublication(offer.published_at)],
  ]) {
    const item = el("div");
    item.append(el("dt", label), el("dd", value));
    essentials.append(item);
  }

  const explanation = el("ul", undefined, "detail-list");
  for (const reason of offer.reasons) {
    const row = el("li");
    row.append(el("strong", reason.points + " / " + reason.max + " pts"), el("span", reason.detail));
    explanation.append(row);
  }
  const provenance = el("div", undefined, "detail-provenance");
  const sourceLinks = el("ul", undefined, "detail-list");
  for (const listing of offer.sources) {
    const row = el("li");
    row.append(
      external(listing.source + (listing.closed_at ? " (fermée)" : ""), listing.snapshot.original_url),
      el("span", fmtPublication(listing.published_at), "muted"),
    );
    sourceLinks.append(row);
  }
  provenance.append(facts([
    ["Première détection", fmtTime(offer.first_seen)],
    ["Dernière vérification", fmtTime(offer.last_seen)],
  ]), sourceLinks);
  if (revisions.length) {
    provenance.append(el("p", revisions.length + " modification(s) dans l’historique récent.", "muted"));
  }

  const editor = el("form", undefined, "editor");
  const state = el("select");
  state.name = "status";
  putOptions(state, statuses);
  state.value = offer.status;
  const message = el("p", undefined, "wide form-message");
  message.setAttribute("role", "status");
  const save = el("button", "Enregistrer", "primary");
  editor.append(
    labeled("Statut", state), labeled("Date de candidature", input("applied_on", "date", offer.applied_on)),
    labeled("Date de rappel", input("reminder_on", "date", offer.reminder_on)),
    labeled("Notes", Object.assign(el("textarea"), {name: "notes", value: offer.notes, maxLength: 20000, rows: 4}), "wide"),
    save, message,
  );
  editor.addEventListener("input", () => { message.textContent = ""; });
  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    message.textContent = "";
    message.classList.remove("saved");
    try {
      const patch = Object.fromEntries(new FormData(editor));
      for (const key of ["applied_on", "reminder_on"]) patch[key] ||= null;
      await api("/offers/" + id, "PATCH", patch);
      message.textContent = "Candidature mise à jour.";
      message.classList.add("saved");
      void render();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      save.disabled = false;
    }
  });

  const actions = el("div", undefined, "actions detail-actions");
  actions.append(external(workday?.label || "Ouvrir la candidature ↗", workday?.url || offer.apply_url, "primary"));
  if (workday || offer.original_url !== offer.apply_url) {
    actions.append(external("Annonce d’origine ↗", offer.original_url, "secondary"));
  }
  actions.append(button("Suivre ma candidature", () => state.focus(), "secondary detail-jump"));
  actions.append(button(offer.hidden ? "Rétablir cette offre" : "Exclure cette offre",
    () => changeOffer(offer.id, {hidden: !offer.hidden}), "secondary exclude-button"));
  if (offer.expired) actions.append(el("span", "Offre expirée", "pill"));

  const description = section("Description du poste", offerDescription(offer));
  const main = el("div", undefined, "detail-main");
  main.append(
    description,
    detailDisclosure("Pertinence · " + offer.score + "/100", explanation),
    detailDisclosure("Sources et historique", provenance),
  );
  const sidebar = section("Suivi de candidature", editor);
  sidebar.classList.add("detail-tracking");
  const work = el("div", undefined, "detail-layout");
  work.append(main, sidebar);
  const summary = el("div", undefined, "detail-summary");
  summary.append(actions, essentials);
  if (offer.remote) summary.append(el("p", "Télétravail · " + field("remote", offer.remote), "muted"));
  $("#detail-body").replaceChildren(summary, work);
  if (!dialog.open) dialog.showModal();
  $("#detail-body").scrollTop = 0;
}

function input(name, type, value) {
  return Object.assign(el("input"), {name, type, value: value ?? ""});
}

function labeled(label, field, className) {
  const node = el("label", label, className);
  node.append(field);
  return node;
}

async function showSources(version) {
  const [sources, history, config] = await Promise.all([
    api("/sources"), api("/runs"), api("/settings"),
  ]);
  if (version !== viewVersion) return;
  const run = button("Lancer une collecte", async () => {
    run.disabled = true;
    try {
      await api("/collect", "POST");
      tell("Collecte complète demandée, sans attendre le prochain créneau.");
      window.setTimeout(() => {
        if (window.location.hash === "#sources") render();
      }, 3000);
    } catch (error) {
      tell(error.message);
    } finally {
      run.disabled = false;
    }
  }, "primary");
  window.setTimeout(() => updateTracking(), 0);
  const tracking = el("div", undefined, "card");
  tracking.setAttribute("aria-live", "polite");
  async function updateTracking() {
    try {
      const state = await api("/collection-progress");
      if (version !== viewVersion || !tracking.isConnected) return;
      const title = state.running ? "Collecte en cours" : state.started_at ? "Dernière collecte terminée" : "Aucune collecte en cours";
      const bar = el("progress");
      bar.max = state.total || 1;
      bar.value = state.completed;
      bar.setAttribute("aria-label", "Sources traitées");
      tracking.replaceChildren(el("h3", title), bar,
        el("p", `${state.completed} / ${state.total} sources examinées · ${state.results.filter(item => ["ok", "partial"].includes(item.status)).length} collectées · ${state.results.filter(item => item.status === "cooldown").length} reportées`));
      if (state.started_at) tracking.append(el("p", state.mode === "manual" ? "Relance manuelle complète" : "Passage automatique : les sources non échues sont reportées.", "muted"));
      const details = el("details");
      details.append(el("summary", "Résultat par source"));
      for (const item of state.results) details.append(el("p", (item.label || item.source) + " : " + (item.status === "cooldown" ? "Reportée — " + item.reason : resultLabels[item.status] || item.status)));
      tracking.append(details);
      if (state.current) tracking.append(el("p", "Source en cours : " + state.current));
      if (state.started_at) tracking.append(el("p", "Démarrée le " + fmtTime(state.started_at), "muted"));
      tracking.append(el("p", `${state.fetched} annonces reçues · ${state.created} nouvelles offres · ${state.updated} mises à jour`),
        el("p", "Les compteurs sont actualisés à la fin de chaque source. Rafraîchissement toutes les 2 secondes.", "muted"));
      const failures = state.results.filter(item => item.status === "failed").length;
      if (failures) tracking.append(el("p", failures + " source(s) en échec — voir le détail ci-dessous.", "form-message"));
    } catch (error) {
      if (version === viewVersion) tracking.textContent = "Suivi momentanément indisponible : " + error.message;
    }
    if (version === viewVersion && tracking.isConnected) window.setTimeout(updateTracking, 2000);
  }
  const grid = el("div", undefined, "source-grid");
  for (const source of sources.filter((item) => item.mode === "automatic")) {
    const card = el("article", undefined, "card");
    let state = health[source.health];
    if (source.last_status === "waiting") state = "Première collecte en attente";
    else if (source.last_status === "running") state = "Collecte en cours";
    else if (source.stale) state = "Données à revérifier";
    else if (source.last_status === "ok" && !source.active_offers) state = "Flux accessible · aucun stage";
    card.append(el("h3", source.label), el("span", state, "pill"),
      el("p", "Dernière collecte réussie · " + fmtTime(source.last_success), "muted"),
      el("p", source.fetched + " annonces reçues · toutes les " + source.interval_minutes + " min", "muted"),
      el("p", (source.active_offers ?? 0) + " stage(s) enregistré(s) · " + (source.visible_offers ?? 0) + " visible(s)"));
    if (source.skipped) card.append(el("p", source.skipped + " fiche(s) non récupérée(s) sur ce passage.", "muted"));
    if (source.retry_at) card.append(el("p", "Nouvel essai autorisé le " + fmtTime(source.retry_at), "muted"));
    if (source.visible_offers) {
      card.append(button("Voir les stages", () => {
        $("#filters").reset();
        $("#filters [name=source]").value = source.key;
        location.hash = "#offers";
      }));
    }
    card.append(button("Recollecter cette source", async () => {
      try {
        await api("/collect", "POST", {sources: [source.key]});
        tell("Collecte complète lancée pour " + source.label + ".");
        render();
      } catch (error) { tell(error.message); }
    }));
    if (source.error) card.append(el("p", source.error, "form-message"));
    grid.append(card);
  }
  if (!grid.childNodes.length) grid.append(el("p", "Aucun tableau automatique configuré."));
  const logs = el("ul", undefined, "log");
  for (const item of history) logs.append(el("li",
    fmtTime(item.started_at) + " · " + item.source + " · " + resultLabels[item.status] +
    " · " + item.created + " nouvelles / " + item.updated + " modifiées" +
    (item.error ? " · " + item.error : "")));
  const manuals = el("p", sources.filter((item) => item.mode === "manual").map((item) => item.label).join(" · "));
  $("#sources").replaceChildren(run, tracking, section("Collecte automatique", grid),
    section("Historique", history.length ? logs : el("p", "Aucune collecte enregistrée.")),
    section("Sources disponibles à l’import manuel", manuals));
  const careerLinks = Object.entries(config.priority_career_links || {});
  if (careerLinks.length) {
    const portals = el("ul", undefined, "log");
    for (const [employer, url] of careerLinks) {
      const row = el("li");
      const label = employer === "Orange Cyberdefense" ? employer + " · France" : employer;
      row.append(external(label + " ↗", url));
      const automatic = sources.filter((source) => source.mode === "automatic" &&
        (source.employers || [source.label]).includes(employer));
      const details = automatic.length
        ? automatic.map((source) => source.label + " · " + resultLabels[source.last_status] +
          " · " + (source.active_offers || 0) + " stage(s)").join(" / ")
        : config.career_notes?.[employer] || "Collecte automatique non disponible";
      row.append(el("p", details, "muted"));
      portals.append(row);
    }
    $("#sources").append(section("Couverture des sites carrière", portals));
  }
}

async function showSettings(version) {
  const config = await api("/settings");
  if (version !== viewVersion) return;
  const instructions = el("p", "Modifiez le fichier .env, puis recréez le service pour appliquer les changements.", "panel muted");
  $("#settings").replaceChildren(instructions, section("Recherche et scoring", facts([
    ["Début cible", config.target_start], ["Durée cible", config.target_months + " mois"],
    ["Domaines", config.priority_domains.join(", ")], ["Entreprises", config.priority_employers.join(", ")],
    ["Mots-clés ajoutés", config.keywords.join(", ") || "Aucun"],
    ["Localisations", config.locations.join(", ") || "Île-de-France (profil par défaut)"],
    ["Pondérations", Object.entries(config.weights).map(([key, value]) => key + " " + value).join(" · ")],
    ["Fréquence", config.collect_minutes + " minutes"],
    ["Analyse contextuelle", config.semantic_enabled ? "Activée" : "Désactivée"],
  ])), section("Telegram", facts([
    ["Statut", config.telegram_enabled ? "Configuré" : "Non configuré"],
    ["Seuil d’alerte", config.alert_threshold + "/100"], ["Résumé à 8 h", config.telegram_digest ? "Activé" : "Désactivé"],
    ["Commandes", config.telegram_commands ? "Activées" : "Désactivées"],
    ["Plage nocturne", config.quiet_start === config.quiet_end ? "Aucune" : config.quiet_start + " h – " + config.quiet_end + " h"],
    ["File de notifications", Object.entries(config.notifications).map(([key, value]) => key + " " + value).join(" · ") || "Vide"],
  ])));
}

async function render(offset = 0) {
  const version = ++viewVersion;
  const requested = location.hash.slice(1) || location.pathname.slice(1);
  const page = Object.hasOwn(pages, requested) ? requested : "dashboard";
  const [title, subtitle] = pages[page];
  $("#title").textContent = title;
  $("#subtitle").textContent = subtitle;
  document.querySelectorAll(".page").forEach((node) => node.hidden = node.id !== page);
  document.querySelectorAll("nav a").forEach((link) => {
    const destination = link.hash.slice(1) || link.pathname.slice(1);
    if (destination === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  try {
    if (page === "dashboard") await showDashboard(version);
    if (["suggestions", "offers", "applications", "excluded"].includes(page)) await showList(page, version, offset);
    if (page === "sources") await showSources(version);
    if (page === "settings") await showSettings(version);
  } catch (error) {
    if (version === viewVersion) tell(error.message);
  }
}

async function analyzeResume(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector("button[type=submit], button.primary");
  submit.disabled = true;
  try {
    const result = await api("/resume/analyze", "POST", Object.fromEntries(new FormData(form)));
    const cards = el("div");
    for (const suggestion of result.suggestions) {
      const card = el("article", undefined, "card");
      card.append(el("h3", suggestion.title), el("p", suggestion.employer + " · Classement CV " + suggestion.rank + "/100"),
        facts([["En commun", suggestion.matches.join(", ")], ["À vérifier dans le CV", suggestion.gaps.join(", ") || "—"]]),
        button("Détails et candidature", () => showDetail(suggestion.id).catch((error) => tell(error.message))));
      cards.append(card);
    }
    if (!result.suggestions.length) cards.append(el("p", "Aucune offre ouverte avec une compétence en commun."));
    $("#profile-results").replaceChildren(
      section("Compétences reconnues", el("p", result.detected_skills.join(", ") || "Aucune dans le dictionnaire.")),
      section("Suggestions", cards),
    );
  } catch (error) {
    tell(error.message);
  } finally {
    submit.disabled = false;
  }
}

async function init() {
  putOptions($("#application-state"), {"": "Tous les statuts", ...statuses});
  $("#application-state").value = "todo";
  $("#resume-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const message = $("#resume-import-status");
    const submit = $("#profile-form button.primary");
    event.target.disabled = true;
    submit.disabled = true;
    message.textContent = "Import du CV en cours…";
    try {
      if (file.size > 5000000) throw new Error("Le CV doit faire moins de 5 Mo.");
      const content = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(new Error("Impossible de lire ce fichier."));
        reader.readAsDataURL(file);
      });
      const result = await api("/resume/import", "POST", {filename: file.name, content});
      $("#profile-form textarea").value = result.text;
      $("#profile-results").replaceChildren();
      message.textContent = file.name + " importé. Vérifiez le texte, puis cliquez sur Analyser.";
    } catch (error) { message.textContent = error.message; }
    finally { event.target.disabled = false; event.target.value = ""; submit.disabled = false; }
  });
  $("#profile-form").addEventListener("submit", analyzeResume);
  $("#filters").addEventListener("submit", (event) => { event.preventDefault(); render(); });
  $("#filters").addEventListener("reset", () => setTimeout(render, 0));
  $("#application-filters").addEventListener("submit", (event) => { event.preventDefault(); render(); });
  window.addEventListener("hashchange", () => { tell(""); render(); });
  $("#open-import").addEventListener("click", () => $("#import-dialog").showModal());
  $("#import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const message = $("#import-feedback");
    const submit = form.querySelector("button[type=submit], button.primary");
    submit.disabled = true;
    message.textContent = "";
    try {
      const fields = Object.fromEntries([...new FormData(form)].filter(([, value]) => value.trim()));
      if (fields.duration_months) fields.duration_months = Number(fields.duration_months);
      if (fields.skills) fields.skills = fields.skills.split(",").map((value) => value.trim()).filter(Boolean);
      const result = await api("/offers/import", "POST", fields);
      form.reset();
      $("#import-dialog").close();
      tell(result.created ? "Offre ajoutée." : "Offre déjà connue. Provenance mise à jour.");
      await render();
      await showDetail(result.offer.id);
    } catch (error) {
      if ($("#import-dialog").open) message.textContent = error.message;
      else tell(error.message);
    } finally {
      submit.disabled = false;
    }
  });
  try {
    const configuration = await api("/settings");
    putOptions($("#import-platform"), configuration.manual_sources);
    putOptions($("#filter-domain"), configuration.domains);
    const sources = await api("/sources");
    putOptions($("#filter-source"), Object.fromEntries(sources.map((source) => [source.key, source.label])));
  } catch (error) {
    tell(error.message);
  }
  await render();
}

init();
