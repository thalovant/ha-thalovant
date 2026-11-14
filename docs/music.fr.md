Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: 0.5.0 après la revérification du 2026-11-13 : `unmute` nommé, plafond de volume, `targets` non porté, et ce que sont les vecteurs de test.

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
- `now_playing`, `shuffle`, `repeat` ; `transfer` (`other` = la source ; sans elle, l'unique lecteur exposé en lecture) ; `join` / `unjoin`.
- Le volume, la sourdine et la lecture (pause, reprise, suivant, précédent, arrêt) passent par les actions media communes : `volume`, `mute`, `unmute`, `playback`.

**Plafond de volume.** L'option **Volume maximal** de l'intégration (1 à 100, 100 par défaut = aucun plafond) limite toute action structurée `volume`, absolue ou relative, sur un lecteur Music Assistant comme sur tout autre lecteur multimédia : une demande plus forte est réglée au plafond et la réponse le dit. Une phrase qu'Assist traite lui-même n'est pas plafonnée.

Les lecteurs sont les **lecteurs Music Assistant exposés à Assist** (une enceinte Chromecast du même nom n'est jamais touchée). La cible se trouve par nom ou alias, zone, la pièce de l'appareil qui parle, un lecteur portant le nom de l'appareil (`mark2` sur le Mark II) et, pour « que joue-t-on », aléatoire et répétition seulement, l'unique lecteur en lecture, en pause ou en mémoire tampon (le volume, la sourdine et la lecture n'utilisent jamais ce repli : sans lecteur propre à l'enceinte, ils passent par le chemin media générique). Un `transfer` sans source nomme l'unique lecteur exposé en lecture (jamais un lecteur caché à Assist, quel que soit l'ordre de Music Assistant). Deux candidats ou aucun : la demande continue en phrase, comme pour toute action structurée.

Les réponses viennent des traductions de l'intégration (anglais et français ; les autres langues entendent l'anglais). Un titre qu'aucun fournisseur n'a est une réponse (« Je n'ai pas trouvé ... »), pas une supposition ; l'artiste nommé affine la recherche et écarte un résultat dont les artistes listés ne le contiennent pas (ou n'y sont pas contenus : une correspondance par sous-chaîne, donc « Muse » peut correspondre à « Muse Tribute Band ») ; un résultat sans information d'artiste, comme une liste ou une radio, n'est pas écarté.

## Limites connues (l'intégration Music Assistant de Home Assistant ne les expose pas)

Pas de lecture par genre ni d'ajout du titre en cours aux favoris : utilisez le transport direct ou le pont de la compétence. La liste des enceintes n'est pas une action ici : le verbe `targets` de la spécification des connecteurs (0.4.0) n'est pas porté par ce chemin. Les favoris sont limités à 50 titres par demande.

## Vecteurs de test

`tests/music_vectors.json` est la **copie propre à ce dépôt** (forme `world` + `cases`). Ce n'est pas le fichier de vecteurs de la spécification des connecteurs, organisé en `validation` et `behavior` (`verb` + `args`) et qui contient un comportement non porté ici (`targets`). La copie est tenue à la main ; un test la compare au `behavior` de la spécification seulement quand ce paquet est installé, ce que l'intégration continue de ce dépôt ne fait pas. Détails dans la [version anglaise](music.md).

Code : `custom_components/thalovant/music.py`, `tests/music_vectors.json`, `tests/test_music.py`, `tests/test_music_contract.py`.
