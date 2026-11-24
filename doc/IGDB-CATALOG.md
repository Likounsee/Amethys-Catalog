# Catalogue maître Amethys — import IGDB actuel et publication statique

Le dépôt dédié est [Likounsee/Amethys-Catalog](https://github.com/Likounsee/Amethys-Catalog). Son site Pages est destiné à publier les données publiques du catalogue ; GitHub Pages n'est qu'un hébergeur statique interchangeable, pas une dépendance métier du launcher.

## Format distribué

Le catalogue maître appartient à Amethys : ses identifiants, son format public et ses règles de validation ne doivent pas dépendre d'un fournisseur de métadonnées. Dans SQLite, `amethys_id` est la clé primaire de `games`. Les identifiants IGDB et les identifiants de boutiques sont conservés séparément dans `game_source_ids` et pointent vers l'identifiant Amethys. Aujourd'hui, IGDB est uniquement le premier adaptateur d'ingestion Windows PC. Le pipeline construit temporairement une base SQLite depuis cette source, valide son intégrité, puis publie uniquement des fichiers compacts :

- `manifest.json` : version, nombre de jeux, empreintes SHA-256 et description des fragments.
- `index/games-index.json.zst` : index de recherche hors ligne, limité à `amethys_id`, nom et slug.
- `shards/{bucket}.json.zst` : fiches détaillées et identités de boutiques, partitionnées par plages d'ID Amethys.
- `metadata/genres.json` : liste des genres.

La base SQLite complète et ses 150 Mo décompressés restent des artefacts de construction temporaires : ils ne sont pas publiés et ne sont jamais téléchargés par défaut par les utilisateurs.

## Consommation côté launcher

1. Télécharger `manifest.json` et comparer `catalog_version`.
2. Télécharger l'index compressé s'il est absent ou si son SHA-256 a changé.
3. Décompresser et conserver l'index pour la recherche hors ligne.
4. Pour afficher une fiche, calculer `bucket = amethys_id / bucket_size`, récupérer le fragment indiqué par `path_template`, vérifier son SHA-256 et le mettre en cache.
5. Conserver les fragments utilisés récemment et les supprimer selon une politique de cache bornée.

Le client doit dépendre d'un contrat de fournisseur abstrait, pas de GitHub : Pages est le premier adaptateur ; un serveur Amethys pourra ensuite servir le même manifeste et les mêmes fichiers.

## Identité stable

Le registre `catalogs/amethys-id-registry.json` est persistant et versionné dans ce dépôt. Lors du premier lancement, le workflow le récupère depuis l'ancien dépôt launcher afin de conserver tous les IDs déjà publiés. Les IDs connus ne sont jamais réattribués. Ne jamais supprimer ce registre.

## Secrets et génération

Les secrets `IGDB_CLIENT_ID` et `IGDB_CLIENT_SECRET` doivent être configurés dans les Actions secrets de ce dépôt. Ils ne sont pas transférés automatiquement depuis Amethys-Launcher. Le workflow s'exécute manuellement ou chaque lundi à 04:17 UTC.

Le catalogue est une base de fiches maîtres uniquement. Une fiche peut exister sans offre de boutique connue : les identités de magasins enrichissent la fiche, elles ne conditionnent plus son existence. La bibliothèque locale du PC (installations détectées, importées ou gérées) reste dans la base privée du Core. Catalogue mondial, possession, disponibilité commerciale et installation sont quatre notions distinctes.

## Évolution des sources

- Ne jamais utiliser un identifiant IGDB comme identifiant Amethys.
- Le registre Amethys conserve les correspondances génériques `source:external_id` vers Amethys ID (avec l'ancien mapping IGDB conservé pour compatibilité) ; les IDs publiés ne sont jamais réattribués.
- Les prochains adaptateurs (éditeurs, boutiques ou autres sources autorisées) devront fournir des identifiants externes propres à leur source et être rapprochés d'une fiche Amethys existante avant de créer une nouvelle fiche.
- Les données de sources différentes doivent pouvoir coexister ; une source absente ou temporairement indisponible ne doit pas effacer les données déjà validées.
- Le format public (manifest, index, fragments) reste stable et indépendant du fournisseur d'hébergement. GitHub Pages n'est que l'hébergement actuel.
- IGDB pourra être retiré lorsque des sources officielles et autorisées couvriront suffisamment les besoins ; le launcher et les IDs Amethys ne devront pas avoir à changer.
