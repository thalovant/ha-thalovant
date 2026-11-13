Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: Actions musique : lecteurs Music Assistant joués et pilotés par le lien Home Assistant.

# Musique via Home Assistant

Si votre foyer utilise Music Assistant derrière Home Assistant (intégration *Music Assistant*), vos appareils Thalovant peuvent le piloter **par le lien Home Assistant déjà en place** : pas de seconde connexion, pas de port ouvert, aucun jeton Music Assistant sur le hub.

```
appareil -> hub -> thalovant-skill-music-assistant -> thalovant.home.request {action}
         -> hivemind-home-router (votre foyer seulement) -> cette intégration (custom_components/thalovant/music.py)
         -> Home Assistant : music_assistant.search / play_media, media_player.* -> Music Assistant
```

## Ce qu'elle fait

Les actions musique sont `capability` + `target` (+ `media`, `value`, `other`) :

- `play_media` (requête, type piste/album/artiste/liste/radio, artiste, `enqueue` play/replace/next/add) : `music_assistant.search` (la meilleure correspondance de nom dans votre bibliothèque et chez vos fournisseurs, affinée par l'artiste quand vous en nommez un, jamais une URL brute), puis `music_assistant.play_media`.
- `play_media` avec `favorites` : jusqu'à 50 titres favoris (`music_assistant.get_library`), lus en aléatoire (`media_player.shuffle_set`, une fois la lecture lancée). Avec `similar` : mode radio sur la piste en cours.
- `now_playing`, `shuffle`, `repeat` ; `transfer` (`other` = la source) ; `join` / `unjoin`.
- Le volume, la sourdine et la lecture (pause, reprise, suivant, précédent, arrêt) passent par les actions media communes.

Les lecteurs sont les **lecteurs Music Assistant exposés à Assist** (une enceinte Chromecast du même nom n'est jamais touchée). La cible se trouve par nom ou alias, zone, la pièce de l'appareil qui parle, un lecteur portant le nom de l'appareil (`mark2` sur le Mark II) et, pour « que joue-t-on », aléatoire et répétition seulement, l'unique lecteur en lecture. Deux candidats ou aucun : la demande continue en phrase, comme pour toute action structurée.

Les réponses viennent des traductions de l'intégration (anglais et français ; les autres langues entendent l'anglais). Un titre qu'aucun fournisseur n'a est une réponse (« Je n'ai pas trouvé ... »), pas une supposition ; un titre du même nom par un autre artiste que celui nommé n'est pas joué.

## Limites connues (l'intégration Music Assistant de Home Assistant ne les expose pas)

Pas de lecture par genre ni d'ajout du titre en cours aux favoris : utilisez le transport direct ou le pont de la compétence. La liste des enceintes n'est pas une action. Les favoris sont limités à 50 titres par demande.

Code : `custom_components/thalovant/music.py`, vecteurs de test partagés `tests/music_vectors.json`, `tests/test_music.py`.
