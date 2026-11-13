Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: revue de la documentation : recoupée avec music.py (conditions des replis de lecteur, commandes communes qui atteignent tout lecteur exposé par son nom, valeurs de shuffle et repeat, réponses « rien en lecture » et « pas de favoris », fichiers de vecteurs), état : sur main après v0.4.0, pas publié. Passage par un francophone à faire.

# Musique via Home Assistant

Si votre foyer utilise Music Assistant derrière Home Assistant (intégration *Music Assistant*), vos appareils Thalovant peuvent le piloter **par le lien Home Assistant déjà en place** : pas de seconde connexion, pas de port ouvert, aucun jeton Music Assistant sur le hub.

```
appareil -> hub -> thalovant-skill-music-assistant -> thalovant.home.request {action}
         -> hivemind-home-router (votre foyer seulement) -> cette intégration (custom_components/thalovant/music.py)
         -> Home Assistant : music_assistant.search / play_media, media_player.* -> Music Assistant
```

## Ce qu'elle fait

**État.** Fusionné sur `main` (pull request #31) après la version `v0.4.0` ; `manifest.json` indique encore 0.4.0, donc une installation HACS de la 0.4.0 ne l'a pas. La documentation a été recoupée avec le code ; la vérification en réel contre un serveur Music Assistant est celle de l'auteur (voir [MAINTENANCE_REPORT.md](../MAINTENANCE_REPORT.md)) et n'a pas été refaite.

Le chemin d'une demande musique est choisi sur le hub, par la bibliothèque media de la compétence musique : la connexion du pont domestique si elle est en ligne, sinon ce lien Home Assistant, sinon une connexion directe (`choose_route()` dans `[thalovant-media-core: thalovant_media_core/connector.py]`). Cette page traite du chemin Home Assistant.

Les actions musique sont `capability` + `target` (+ `media`, `value`, `other`) :

- `play_media` (requête, type piste/album/artiste/liste/radio, artiste, `enqueue` play/replace/next/add ; sans `enqueue`, on remplace la file) : `music_assistant.search` (la meilleure correspondance de nom dans votre bibliothèque et chez vos fournisseurs, affinée par l'artiste quand vous en nommez un, jamais une URL brute), puis `music_assistant.play_media`. Le champ `media.album` de la spécification est accepté par le routeur mais cette intégration ne le lit pas.
- `play_media` avec `favorites` : jusqu'à 50 titres favoris (`music_assistant.get_library`), lus en aléatoire (`media_player.shuffle_set`, une fois la lecture lancée) ; sans favoris : « Vous n'avez aucun favori à jouer. ». Avec `similar` : mode radio sur la piste en cours ; rien en lecture : « Rien n'est en cours sur {player}. ».
- `now_playing` (répond seulement si une piste joue ou est en pause), `shuffle` (`value` on/off), `repeat` (`value` off/one/all ; toute autre valeur n'est pas exécutée et la demande continue en phrase) ; `transfer` (`other` = la source ; sans elle, l'unique lecteur exposé en lecture) ; `join` / `unjoin`.
- Le volume, la sourdine (et son retrait) et la lecture (lecture, pause, suivant, précédent, arrêt) passent par les actions media communes : avec la cible `here` d'abord vers le lecteur Music Assistant de l'enceinte, avec une cible nommée par le chemin générique décrit plus bas.

Pour les capacités musique (`play_media`, `now_playing`, `shuffle`, `repeat`, `transfer`, `join`, `unjoin`), les lecteurs sont les **lecteurs Music Assistant exposés à Assist** (plateforme `music_assistant` du registre) : une enceinte Chromecast du même nom n'est jamais touchée. La cible se trouve par nom ou alias, zone, ou la pièce de l'appareil qui parle (`here`). Deux replis ne servent **que pour la cible `here`** : un lecteur portant le nom de l'appareil (`mark2` sur le Mark II) et, pour `now_playing`, `shuffle` et `repeat` seulement, l'unique lecteur en lecture, en pause ou en mémoire tampon. Un `transfer` sans source nomme l'unique lecteur exposé en lecture (jamais un lecteur caché à Assist, quel que soit l'ordre de Music Assistant). Deux candidats ou aucun : la demande continue en phrase, comme pour toute action structurée.

**Les commandes communes ne se limitent pas aux lecteurs Music Assistant quand la cible est nommée.** `volume`, `mute`, `unmute` et `playback` n'utilisent un lecteur Music Assistant que pour la cible `here` (et jamais le repli « celui qui joue »). Avec une cible nommée, ou si la pièce de l'enceinte n'a pas de lecteur Music Assistant, elles passent par le chemin media générique, qui trouve **n'importe quel `media_player` exposé**, y compris un Chromecast ou un téléviseur du même nom (deux du même nom ne sont pas départagés : la demande continue en phrase).

Si les services de l'intégration Music Assistant manquent (non installée ou non chargée), une demande de lecture est laissée à la phrase, sans erreur. Une demande partage le budget de 10 secondes du hub (au plus 8,5 s ici) : une recherche qui dépasse le temps répond « Désolé, Home Assistant a mis trop de temps à répondre. » si rien n'avait démarré, et « Désolé, je n'ai pu en faire qu'une partie. » si la lecture avait déjà démarré, jamais la phrase par-dessus.

Les réponses viennent des traductions de l'intégration (anglais et français ; les autres langues entendent l'anglais). Un titre qu'aucun fournisseur n'a est une réponse (« Je n'ai pas trouvé ... »), pas une supposition ; l'artiste nommé affine la recherche et écarte un résultat dont les artistes listés ne le contiennent pas (ou n'y sont pas contenus : une correspondance par sous-chaîne, donc « Muse » peut correspondre à « Muse Tribute Band ») ; un résultat sans information d'artiste, comme une liste ou une radio, n'est pas écarté.

## Limites connues (l'intégration Music Assistant de Home Assistant ne les expose pas)

Pas de lecture par genre ni d'ajout du titre en cours aux favoris : utilisez le transport direct ou le pont de la compétence. La liste des enceintes n'est pas une action. Les favoris sont limités à 50 titres par demande.

Code : `custom_components/thalovant/music.py`, `tests/test_music.py`. Vecteurs de test : ce dépôt garde `tests/music_vectors.json` (23 cas) ; le pont autonome lit la copie de la spécification, `[thalovant-connector-spec: thalovant_connector_spec/vectors/music_assistant.json]` (les mêmes 23 cas, un champ `request_valid` en plus). Les deux ont été comparés et concordent cas par cas ; rien ne vérifie qu'ils le restent.
