Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: Music actions: Music Assistant players played and steered through the Home Assistant link.

# Musique via Home Assistant

Si votre foyer utilise Music Assistant derriere Home Assistant (integration *Music Assistant*), vos appareils Thalovant peuvent le piloter **par le lien Home Assistant deja en place** : pas de seconde connexion, pas de port ouvert, aucun jeton Music Assistant sur le hub.

```
appareil -> hub -> thalovant-skill-music-assistant -> thalovant.home.request {action}
         -> hivemind-home-router (votre foyer seulement) -> cette integration (custom_components/thalovant/music.py)
         -> Home Assistant : music_assistant.search / play_media, media_player.* -> Music Assistant
```

## Ce qu'elle fait

Les actions musique sont `capability` + `target` (+ `media`, `value`, `other`) : `play_media` (requete, type piste/album/artiste/liste/radio, artiste, `enqueue` play/replace/next/add) via `music_assistant.search` puis `play_media` (meilleure correspondance de nom dans votre bibliotheque, jamais une URL brute) ; `play_media` avec `favorites` (favoris en aleatoire) ou `similar` (mode radio sur la piste en cours) ; `now_playing` ; `shuffle`, `repeat` ; `transfer` (`other` = la source) ; `join`/`unjoin` ; et le volume, la sourdine et la lecture (pause, reprise, suivant, precedent, arret) par les actions media communes.

Les lecteurs sont les **lecteurs Music Assistant exposes a Assist** (une enceinte Chromecast du meme nom n'est jamais touchee). La cible se trouve par nom ou alias, zone, la piece de l'appareil qui parle, un lecteur portant le nom de l'appareil (`mark2` sur le Mark II) et, pour « que joue-t-on », aleatoire et repetition seulement, l'unique lecteur en lecture. Deux candidats ou aucun : la demande continue en phrase, comme pour toute action structuree.

Les reponses viennent des traductions de l'integration (anglais et francais ; les autres langues entendent l'anglais). Un titre absent de votre bibliotheque est une reponse (« Je n'ai pas trouve ... »), pas une supposition.

## Limites connues (l'integration Music Assistant de Home Assistant ne les expose pas)

Pas de lecture par genre ni d'ajout du titre en cours aux favoris : utilisez le transport direct ou le pont de la competence. La liste des enceintes n'est pas une action.

Code : `custom_components/thalovant/music.py`, vecteurs de test partages `tests/music_vectors.json`, `tests/test_music.py`.
