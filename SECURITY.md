# Politique de sécurité

## Versions prises en charge

Seule la dernière version publiée reçoit des correctifs de sécurité.

| Version | Prise en charge |
|---|---|
| 0.1.x | ✅ |

## Signaler une vulnérabilité

**N'ouvrez pas d'issue publique.** Utilisez le signalement privé de GitHub :
onglet *Security* du dépôt → *Report a vulnerability*
([lien direct](https://github.com/3615nulsi/velos_montpellier/security/advisories/new)).

Indiquez si possible :

- la version de l'intégration et de Home Assistant ;
- une description du problème et de son impact ;
- les étapes pour le reproduire.

Projet maintenu bénévolement : je réponds généralement sous une semaine. Une fois le
correctif publié, l'avis de sécurité est rendu public en créditant l'auteur du
signalement, sauf s'il préfère rester anonyme.

## Périmètre

L'intégration interroge uniquement l'API open data publique de Montpellier Méditerranée
Métropole, sans clé ni identifiant, et ne dépend d'aucune bibliothèque externe. Les
problèmes touchant Home Assistant lui-même sont à signaler au
[projet Home Assistant](https://www.home-assistant.io/security/), et ceux de l'API
à la Métropole.
