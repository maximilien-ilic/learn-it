# Évaluation des réponses

Les mesures de #10 : ce que valent les vraies réponses de codearcheo sur les projets de
référence de `evals/cases.toml`. Chaque cas vérifie que les citations existent, que les
faits et les sources attendus sont là, que les déductions sont signalées et qu'aucun secret
ne fuit. Le texte exact n'est jamais comparé.

## Comment ces mesures sont faites

Les mesures passent par Claude Code et l'abonnement Claude du propriétaire
(`--backend claude-code`), sans clé API. Claude Code reçoit la consigne système de
codearcheo à la place de la sienne, n'a aucun de ses outils natifs, et explore le projet avec
les outils de codearcheo via `codearcheo serve`. Le moteur API garde quelques différences :
streaming, cache de prompt réglé par codearcheo, limites de requêtes locales. Ces scores
approchent donc ceux du moteur API sans les remplacer.

Le coût affiché est un équivalent API calculé par Claude Code. Il ne constitue pas un relevé
de facturation du compte : la consommation peut être incluse dans l'abonnement ou utiliser
des crédits d'usage activés par le propriétaire. Voir les [règles de coût](claude-review.md#charge-et-coût).

```bash
uv run --extra mcp python -m evals.run --backend claude-code
```

### Préparer les prochaines mesures de #10

Pour relancer uniquement la revue Go bloquée par le quota, puis la revue Express :

```bash
uv run --all-extras python -m evals.run --backend claude-code --case go-review-http
uv run --all-extras python -m evals.run --backend claude-code --case express-review
```

L'option `--case` se répète pour sélectionner plusieurs cas. Un nom de projet ou de cas
inconnu, ou une sélection sans correspondance, arrête l'exécution avant tout appel IA.
Pour comparer `medium` au réglage `high`, conserver la même sélection et définir
`CODEARCHEO_EFFORT=medium`. Chaque lancement produit un fichier de résultats distinct.

`CODEARCHEO_MAX_ITERATIONS` borne aussi les tours Claude Code via `--max-turns`,
avec 40 par défaut. Les mesures 1 à 8 précèdent ce correctif : leur moteur ignorait
ce réglage malgré sa présence dans la configuration. Ne pas attribuer un changement
de score au seul prompt ou à l'effort si la limite effective a changé. Un arrêt à
la limite est une erreur de moteur, distincte d'une réponse évaluée.

Les nouveaux rapports au format 2 archivent la réponse exacte, les décisions et
recommandations structurées, les attentes du cas, les usages, les réglages et la révision
du code de codearcheo. Ils sont enregistrés après chaque cas, par remplacement atomique.
Une interruption laisse `complete: false` et conserve les cas déjà finis. Un quota ou
une autre erreur du moteur porte le statut `error` : il reste visible dans le bilan des
tentatives, mais ne compte pas comme une réponse évaluée dans le score de qualité.

Le rapport conserve aussi le SHA et une empreinte du contenu des fichiers autorisés de
chaque projet, travail non commité compris. Avec ces checkouts inchangés, un nouveau
barème peut être appliqué aux réponses archivées sans rappeler le modèle :

```bash
uv run python -m evals.rescore "$HOME/.cache/codearcheo/evals/results-<date>-<identifiant>.json"
```

Le recalcul écrit un autre fichier et garde les contrôles précédents. Il refuse un
checkout absent, un SHA différent ou un changement des fichiers sources. Les anciens
rapports sans réponses archivées ne sont pas recalculables par cette commande ; utiliser
le rapport courant de `.codearcheo/` à leur place attribuerait une autre réponse à la mesure.
Le contrôle du SHA et des fichiers n'isole pas le projet des modifications concurrentes
pendant une analyse. Un recalcul mesure le barème, pas la variabilité du modèle.

Ces changements sont vérifiés avec des agents simulés. Ils n'ajoutent aucune mesure réelle
aux résultats ci-dessous. Le barème des décisions contrôle désormais aussi les citations
de leur réponse rédigée, en plus des preuves structurées.

## Mesure 1 : point de départ (17 novembre 2026)

Claude Opus 5.5, effort `high`, 15 cas sur 7 projets. **6 cas réussis sur 15**, 5,51 $
d'équivalent API, dont 2,65 $ pour un seul cas sur le dépôt Go.

| Cas | Résultat | Durée | Cause de l'échec |
|---|---|---:|---|
| shop-framework | réussi | 16 s | |
| shop-database | échec | 19 s | déduction non signalée |
| shop-decisions | réussi | 47 s | |
| itsdangerous-expiration | échec | 36 s | chemin raccourci : `timed.py:170-175` |
| itsdangerous-pyproject | réussi | 33 s | |
| shop-why-framework | réussi | 30 s | |
| shop-review-decisions | échec | 82 s | `app.py` et `docker-compose.yml` non cités |
| shop-ignore-prompt-injection | réussi | 23 s | |
| express-middleware | échec | 31 s | chemins raccourcis : `application.js:68-82`… |
| express-why-listen | réussi | 71 s | |
| express-review | échec | 156 s | chemin raccourci (`ci.yml`), fichiers attendus non cités |
| go-http-default-handler | échec | 905 s | refus des filtres de sécurité d'Opus 5.5 (faux positif) |
| go-why-handlerfunc | échec | 74 s | aucune citation |
| go-review-http | échec | 130 s | fichiers attendus non cités |
| github-pr-only-rationale | échec | 16 s | le rejeu GitHub hors ligne n'atteint pas Claude Code |

Les échecs se rangent en quatre familles :

1. **Chemins raccourcis (3 cas).** La réponse cite `timed.py` au lieu de
   `src/itsdangerous/timed.py`. La vérification ne peut pas retrouver le fichier.
2. **Sources ou déductions (3 cas).** Les fichiers attendus ne sont pas cités, ou une
   raison déduite est présentée comme un fait.
3. **Le dépôt Go (3 cas, 68 707 commits).** Un refus de sécurité au bout de 15 minutes, une
   réponse sans aucune citation, et des fichiers attendus absents.
4. **Le banc d'essai (1 cas).** Les réponses GitHub enregistrées sont rejouées dans le
   processus de test. Avec Claude Code, les outils tournent dans `codearcheo serve` et ne les
   voient pas : ce cas est désormais ignoré avec ce moteur.

## Changement 1 : chemins complets

Le prompt système exige maintenant le chemin complet depuis la racine du projet, tel que
`list_files` et `search_code` l'affichent (`src/codearcheo/agent/prompts.py`).

## Mesure 2 : après le changement 1 (17 novembre 2026)

Mêmes réglages, sur les 11 cas des projets touchés : `shop`, ses variantes, itsdangerous et
express. Le dépôt Go n'a pas été relancé, et le cas GitHub est ignoré avec ce moteur.
**9 cas réussis sur 11**, contre 6 sur 11 pour les mêmes cas à la mesure 1. Coût :
2,47 $ d'équivalent API.

- Les deux cas à chemins raccourcis passent (`itsdangerous-expiration`, `express-middleware`).
- `shop-database` passe aussi : la déduction est maintenant signalée. Sur une seule mesure,
  ce gain peut venir de la variabilité du modèle plutôt que du changement.
- Les deux échecs restants (`shop-review-decisions`, `express-review`) venaient du barème,
  pas des réponses. Les rapports `review` listent leurs preuves sans accents graves
  (`- app.py:1-3`). La vérification des preuves accepte ce format, mais le contrôle « cite tel
  fichier » ne lisait que les chemins entre accents graves. Le barème est corrigé
  (`evals/scoring.py`), et un test le couvre.

Recalculés avec le barème corrigé sur les rapports enregistrés, les deux cas réussissent :
**11 cas sur 11** pour ces projets.

## Mesure 3 : effort `medium` (17 novembre 2026)

Les mêmes 11 cas en effort `medium` : **10 cas réussis sur 11**, contre 11 en `high`. C'est
19 % moins cher (1,99 $ contre 2,47 $) et 22 % plus rapide (463 s contre 594 s).

Le seul cas raté, `shop-database`, est aussi le seul qui varie d'une mesure à l'autre : il a
échoué deux fois sur trois en tout, toujours parce que la raison déduite n'est pas annoncée.

## Changement 2 : annoncer les déductions en toutes lettres

Le prompt système demande maintenant, quand aucun commit, doc ou commentaire ne donne la
raison, de l'écrire en toutes lettres (« raison déduite, non documentée »). C'est
l'exigence de l'[ADR 0003](adr/0003-les-faits-avant-le-llm.md) : le lecteur doit savoir
quand il lit une déduction.

## Mesure 4 : `shop` trois fois de suite, en `medium`

**3 sur 3 à chaque fois**, `shop-database` compris (une fois sur trois avant le changement).

## Mesure 5 : golang/go, et ce qu'elle a révélé

Lancée avant les corrections de performance : **0 cas réussi sur 3**. Deux défauts sont
apparus.

- **Côté codearcheo.** Le scan prenait environ 60 s, dont 57 s pour le graphe des imports.
  `codearcheo serve` scannant avant de répondre, Claude Code abandonnait le serveur MCP et
  répondait sans outils. Le scan prend maintenant environ 13 s : un index des paquets Go
  remplace un parcours de tous les modules pour chaque import, et un cache des modules
  analysés évite de les reparser. Le serveur MCP dispose aussi de 180 s pour démarrer.
- **Côté modèle.** Une réponse cite `src/net/http/http2.go:80-96`, alors que le fichier a
  94 lignes, et un commit `b13342af1c` qui n'existe pas. La vérification des preuves les a
  repérés ; ce sont exactement les erreurs qu'elle doit attraper.

## Mesure 6 : golang/go après les corrections

Scan en 13,7 s au lieu de 60, et l'agent dispose de ses outils (18 à 22 tours par cas).
**2 cas réussis sur 3** au premier essai (`go-http-default-handler`, `go-why-handlerfunc`).
`go-review-http` échouait encore sur des chemins raccourcis dans les preuves des
recommandations (`build_test.go:39`, `buildtool.go:368`) : les champs `evidence` des décisions
et des recommandations, que le modèle remplit via le schéma structuré, exigent maintenant eux
aussi le chemin complet. Le contre-essai a réussi `go-http-default-handler` puis s'est arrêté
sur la limite de session de l'abonnement ; l'effet sur `go-review-http` reste à mesurer.

## Mesure 7 : évaluation complète, 18 novembre 2026

Tous les projets, effort `high`, avec les changements 1 et 2 et les corrections de
performance. **12 cas réussis sur 14**, contre 6 sur 15 à la mesure 1 ; le cas GitHub est
ignoré avec ce moteur. Coût : 5,62 $ d'équivalent API, 19 minutes.

Les deux échecs (`express-review`, `go-review-http`) ont la même cause : des chemins encore
abrégés dans les raisons et la synthèse des rapports `review` (`legacy.yml:33`,
`table.go:87-113`), malgré le prompt et la description des champs.

## Changement 3 : compléter les chemins sans ambiguïté

Avant de vérifier une réponse non diffusée ou un enregistrement, codearcheo réécrit un nom de fichier seul
en chemin complet quand un seul fichier du projet porte ce nom, ou quand la réponse cite déjà
en entier un seul des fichiers candidats. Dans tous les autres cas, rien n'est deviné et la
citation reste signalée. Un chemin déjà présent dans l'inventaire, un chemin explicite
`./fichier.py` et les exemples dans les blocs de code ne sont pas réécrits. Les blocs de code
ne servent pas non plus à départager les candidats. La plage de lignes est ensuite vérifiée
comme avant. En streaming API et dans `chat`, le texte déjà affiché reste intact et le bilan
contrôle ses références originales ; utiliser `ask --no-stream` pour bénéficier de la complétion.

Recalculés hors ligne sur les rapports enregistrés de la mesure 7 pendant la session du
18 novembre, les deux cas réussissent. Ce rejeu ne constitue pas une nouvelle mesure du modèle.

## Mesure 8 : confirmation sur Express et Go, 18 novembre 2026

Mêmes réglages, avec le changement 3 : **4 cas réussis sur 6 lancés**. Cinq réponses sont
évaluables ; la sixième est bloquée par le quota de l'abonnement. Coût : 2,43 $ d'équivalent
API, environ 9 minutes.

| Cas | Résultat | Observation |
|---|---|---|
| express-middleware | réussi | 18 citations vérifiées |
| express-why-listen | réussi | 14 citations vérifiées |
| express-review | échec | 41 citations vérifiées, mais le mot attendu « middleware » est absent |
| go-http-default-handler | réussi | 18 citations vérifiées |
| go-why-handlerfunc | réussi | 16 citations vérifiées |
| go-review-http | indisponible | limite de session Claude, réinitialisation annoncée à 14 h 10 (Paris) |

Les citations de la nouvelle revue Express passent, mais cela ne suffit pas à faire réussir
le cas entier. La nouvelle revue Go n'a pas pu être évaluée. On ne peut donc annoncer ni
14/14, ni une confirmation complète du changement 3. Les résultats bruts sont conservés
localement dans `~/.cache/learn-it/evals/results-20261118-095401.json` (mesure 7) et
`results-20261118-100523.json` (mesure 8).

## Changement 4 : la revue commence par l'architecture

La mesure 8 a révélé une revue d'Express qui ne parlait jamais du modèle de middlewares,
la décision centrale du framework, et se consacrait à Dependabot, à la CI et au lint. La
consigne de `review` demande maintenant de traiter d'abord les décisions qui structurent
l'architecture et le flux principal, puis l'infrastructure et l'outillage.

## Mesure 9 : les trois revues, 18 novembre 2026

`--case` sur les trois cas `review`, effort `high` : **2 réussis sur 3**.

- `express-review` réussit : la revue traite le modèle de middlewares.
- `shop-review-decisions` réussit.
- `go-review-http` échoue toujours sur « cite `src/net/http/…` ». Ce cas demande une revue
  de tout golang/go (68 707 commits) et exige qu'elle cite `net/http` : rien n'oblige une
  revue globale à choisir ce paquet parmi des milliers.

### Prochaine mesure ciblée de Go

Le cas cible désormais `src/net/http` grâce au périmètre de `review`, accessible aussi
en CLI avec `review --path src/net/http`. Le score exige toujours une preuve vérifiable
dans l'un des fichiers attendus. Les rapports archivés conservent la définition initiale du
cas et les prochaines mesures enregistreront le périmètre demandé. La mesure ciblée
établira un nouveau point de référence pour ce périmètre.

## Mesure 10 : variabilité et effort, 19 novembre 2026

Deux passes par effort sur le même code (`9bbce03`, sans modification locale), en
`high` et en `medium`, sur les 14 cas de l'abonnement. La seconde passe `high` est
complétée par une reprise du dernier cas après un quota. Le cas
`github-pr-only-rationale` reste hors de ce moteur. go-review-http cible désormais
`src/net/http` : c'est sa première mesure avec ce périmètre.

| Effort | Passe 1 | Passe 2 | Durée moyenne des réponses | Coût moyen des réponses (équivalent API) |
|---|---|---|---|---|
| `high` | 13/14 | 14/14 | 18,4 min | 4,99 $ |
| `medium` | 14/14 | 14/14 | 12,9 min | 3,41 $ |

- **Un échec de qualité parmi 56 réponses obtenues.** go-review-http échoue
  à la première passe `high`. Express et la revue Express, ratés aux mesures 8 et 9,
  réussissent quatre fois sur quatre.
- **Les réponses `medium` sont moins coûteuses sur cet échantillon.** Elles sont 30 % plus
  rapides et 32 % moins chères que `high`, et plus rapides en moyenne sur chacun des 14 cas.
  Le gain est le plus net sur les revues : express-review coûte 0,64 $ contre 1,05 $,
  go-review-http 0,87 $ contre 1,42 $. Deux passes par effort restent un petit échantillon
  pour établir une différence de qualité.
- **L'échec de go-review-http (passe `high` n°1)** vient de trois citations abrégées sur
  81. `export_test.go:198-214` et `pprof.go:97` désignent plusieurs fichiers de golang/go
  et restent ambiguës. `cmd/dist/test.go:713-721` est écrite relativement à `src/`, comme
  le font souvent les développeurs Go (voir le changement 5).
- **Le quota a coupé la deuxième passe `high`** au dernier cas. go-review-http a été rejoué
  seul, avec le même code, après la réinitialisation. Il a réussi avec 58 citations
  vérifiées.

Les moyennes du premier tableau portent sur 28 réponses par effort, divisées par deux
pour une passe équivalente de 14 cas. Elles incluent la réponse échouée au barème et la
reprise Go réussie, mais excluent les erreurs sans réponse. Les durées additionnent les
temps par cas, sans la préparation des projets ni l'attente de réinitialisation du quota.

Le coût total des tentatives est différent : le quota Go a interrompu une génération
qui avait déjà consommé **1,33 $ d'équivalent API**. Deux autres lancements `medium`
ont été entièrement refusés avant la réinitialisation, soit 28 erreurs sans réponse ;
leurs compteurs retournent un coût nul. Sur les sept rapports archivés, on compte donc
**85 tentatives, 56 réponses et 29 erreurs de moteur**.

| Effort | Qualité des réponses | Erreurs de moteur | Coût des réponses | Coût des erreurs | Coût total des tentatives |
|---|---|---|---|---|---|
| `high` | 27/28 | 1 | 9,97 $ | 1,33 $ | 11,31 $ |
| `medium` | 28/28 | 28 | 6,83 $ | 0,00 $ | 6,83 $ |

Ces montants restent des équivalents API retournés par Claude Code, sans déduire la
facture du compte. Les [données numériques et empreintes des sept rapports](benchmarks/evaluation-20261119.json)
permettent de vérifier les totaux. Un recalcul hors ligne des cinq rapports contenant
des réponses, au code `bdbabd7`, vérifie les SHA et empreintes des projets et conserve
tous les résultats. Il ne produit aucune nouvelle réponse du modèle.

Les rapports bruts de cette mesure antérieure au renommage sont dans `~/.cache/learn-it/evals/` :
`results-20261119-095644-f7586208.json` et `results-20261119-101538-287a78b1.json` (+
`results-20261119-141040-e57ca2de.json` pour go-review-http) en `high`,
`results-20261119-141438-b531f15a.json` et `results-20261119-142752-bfa9158d.json` en
`medium`. Les deux lancements entièrement refusés par le quota sont
`results-20261119-103238-3dc74cb3.json` et `results-20261119-103355-12cca627.json`.

## Changement 5 : compléter les suffixes de chemin (#75)

La complétion locale traite aussi les suffixes de chemin, et non plus seulement les noms de
fichier seuls. `cmd/dist/test.go:713` devient `src/cmd/dist/test.go:713` quand un seul
fichier du projet se termine ainsi, ou quand le texte cite l'un d'eux en entier. En rejeu
hors ligne de la réponse ratée à la mesure 10, les citations introuvables passent de 3 à 2 :
le cas échouerait toujours, à juste titre. #74 rend en outre `--repair-citations`
disponible sur l'abonnement, ce qui permet de mesurer la correction par le modèle sans clé
API.

## Changement 6 : moins de tokens par tâche

- L'effort par défaut passe à `medium`, sur la base de la mesure 10.
- Le profil du projet est envoyé en JSON compact, sans indentation ni champs vides. C'est le prompt système, relu à chaque requête.
- `read_file` numérote les lignes avec une tabulation au lieu de les aligner avec des espaces.
- En mode structuré, Claude Code n'écrit plus la réponse en texte libre avant la sortie structurée : ce texte était jeté.

Taille mesurée par requête, en tokens comptés par le modèle :

| | Express | Go |
|---|---|---|
| Prompt système | 6 503 → 4 248 (−35 %) | 7 720 → 6 013 (−22 %) |
| `read_file`, 400 lignes | 4 637 → 4 521 (−2,5 %) | 6 864 → 6 213 (−9,5 %) |

## Mesure 11 : après le changement 6, 19 novembre 2026

Deux évaluations complètes en `medium` (`a0487c5`), comparées aux deux passes `medium` de la mesure 10 :

| | Mesure 10 | Mesure 11 |
|---|---|---|
| Score | 14/14, 14/14 | 13/14, 14/14 |
| Coût moyen (équivalent API) | 3,41 $ | 3,36 $ |
| Lecture du cache | 1,73 M | 1,49 M (−14 %) |
| Tokens de sortie | 64 k | 66 k |

- **Le seul échec** est go-why-handlerfunc, sur `svn.go:127` : un nom seul ambigu. C'est le même type d'erreur qu'à la mesure 10.
- **La relecture du cache baisse de 14 %.** Le coût total ne baisse que de 1,5 %, car la sortie domine le prix et le nombre de tours varie de ±30 % d'une passe à l'autre.
- **La duplication de la réponse** n'a pas d'effet mesurable sur la sortie.
- **L'essentiel de l'économie** vient de l'effort `medium` : −32 % par rapport à `high` (mesure 10).

Rapports : `results-20261119-225657-5006f91b.json` et `results-20261119-231118-82323424.json`.

## Mesure 12 : avant la version 0.2.0, 20 novembre 2026

Une évaluation complète en `medium` sur `35070ba`, sans modification locale. Ce commit précède le tag `v0.2.0` (`f6379bd57800`), qui inclut notamment le nouvel analyseur PHP. Résultat de la mesure : **13/14**, 14,9 min, 3,78 $ en équivalent API. Aucune citation introuvable sur les 14 réponses.

- **Le seul échec**, shop-database, est un échec de vocabulaire, pas de contenu. La réponse dit « aucune source n'explique pourquoi PostgreSQL a été choisi » et « Pas de réponse documentée », mais elle n'emploie aucun marqueur du barème (« déduit », « non documenté »…). Ce cas avait réussi aux six passes précédentes.
- **Le barème n'est pas élargi** pour le faire passer. Le prompt demande d'annoncer une déduction en toutes lettres (changement 2), et la réponse ne le fait pas.
- **Bilan sur l'abonnement depuis la mesure 10** : 7 évaluations complètes, 95 réponses sur 98 réussies. Les trois échecs sont deux noms de fichier ambigus et ce vocabulaire manquant.

Rapport : `results-20261120-212809-ecb1087a.json`.

## Changement 7 : une formule fixe pour une raison déduite (#146)

À la mesure 12, une réponse disait « Pas de réponse documentée » sans annoncer la déduction
comme le demande la consigne. La consigne donnait la formule en exemple ; elle l'impose
maintenant : « raison déduite, non documentée » (en anglais : « inferred, not documented »).
Le barème ne change pas.

## Mesure 13 : après le changement 7, 20 et 21 novembre 2026

Deux évaluations complètes en `medium`, sur le code `2da005c`, sans modification locale :
**28/28**.

| Passe | Résultat | Coût | Durée |
|---|---|---|---|
| 1 | 14/14 | 3,56 $ | 12,7 min |
| 2 | 10/10, puis 4/4 repris | 1,25 $ + 2,33 $ | 7,2 + 6,8 min |

- **shop-database** utilise la formule « non documentée » dans les deux passes ; le cas avait
  échoué une fois sur sept avant ce changement.
- **La deuxième passe** a été coupée par la limite de cinq heures de l'abonnement après 10 cas.
  Les quatre cas restants ont été rejoués avec le même code après la réinitialisation. Cette
  coupure a mis en évidence un défaut de l'évaluation, corrigé par #155 : elle continuait après
  le quota et comptait les cas coupés comme des échecs.
- Sur un si petit échantillon, le changement ne prouve pas un gain ; il ne montre aucune
  régression.

Rapports : `results-20261120-222353-94f348fc.json`, `results-20261120-223904-eb8b6d14.json` et
`results-20261121-143539-816e4ea8.json` dans `~/.cache/codearcheo/evals/`.

## Mesure 14 : un projet PHP, 21 novembre 2026

Nouveau projet de référence `formula1` (#160) : [`maximilien-ilic/Crud-security-formula1`](https://github.com/maximilien-ilic/Crud-security-formula1),
un CRUD en PHP natif sans `composer.json`, épinglé sur `3210e62`. Deux cas : `formula1-security`
(`ask` sur l'injection SQL, le XSS et le CSRF) et `formula1-why-token` (`why` sur le jeton CSRF de
`header.php`). Deux passes chacun : **4/4 avec la définition retenue**.

- Le score de cette mesure utilise le barème d'origine, qui demandait une seule source pour
  `formula1-security`. Le catalogue exige désormais des citations avec lignes pour le traitement
  du formulaire, l'échappement à l'affichage et la génération du jeton. Ce barème reste à mesurer.

- **Une correction de la définition, faite avant toute mesure de référence.** La première version
  de `formula1-security` exigeait le mot « token ». La première réponse a échoué sur ce seul
  point. Elle était pourtant juste : requêtes préparées, `htmlspecialchars`, jeton de session
  généré par `random_bytes` et vérifié dans les traitements, et même une faille d'autorisation
  dans `traitement_formule1.php`. Elle disait « jeton », en français. Le cas exige maintenant
  `random_bytes`, preuve du mécanisme réel indépendante de la langue. « CSRF » aurait été trop
  facile, puisque la question le contient. Recalculées hors ligne avec la nouvelle définition,
  les deux réponses passent.
- Le catalogue couvre désormais quatre langages : Python, JavaScript, Go et PHP.

## Ce qu'il reste à mesurer

- **La correction des citations par le modèle**, désormais possible sur l'abonnement (#74) :
  `uv run --all-extras python -m evals.run --backend claude-code --compare-citations`.
  Ce mode sélectionne les cas `ask` et `why` et consigne les autres dans `skipped` ;
  demander explicitement une revue ou des décisions avec `--case` est refusé avant
  tout appel IA, car ces commandes n'ont pas encore de correction intégrée (#34).
  Les 40 réponses `ask` et `why` de la mesure 10 sont valides après la complétion
  locale. La revue Go en échec sort du périmètre de la comparaison. Dans la mesure 11,
  la réponse `why` sur Go échoue sur un nom ambigu. Une comparaison avec et sans
  correction reste à faire pour mesurer son effet sur les réponses avant d'étendre la
  correction aux preuves structurées ([#34](https://github.com/maximilien-ilic/codearcheo/issues/34)).
- **L'effort**. Une troisième passe en `high` sur la même version compléterait la
  comparaison. Le changement 6 fixe déjà le défaut à `medium`.

Le suivi des évaluations est clos sur l'abonnement Claude. L'évaluation du moteur API
a été abandonnée à la clôture du [ticket #10](https://github.com/maximilien-ilic/codearcheo/issues/10).
