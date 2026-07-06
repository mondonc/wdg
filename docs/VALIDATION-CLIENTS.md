# Recette des clients macOS et Windows

Le code des trois plateformes existe et les chemins macOS/Windows sont
couverts par des tests unitaires à base de mocks (`wg_client/test_tunnel.py`) ;
seul **Linux** a été validé de bout en bout (client-probe Docker, binaire
PyInstaller autonome). Ce document est la checklist de recette à dérouler
**sur de vraies machines** macOS et Windows pour lever la réserve — une
exécution complète par OS suffit.

Les artefacts se produisent avec `make build-clients` : binaires Linux,
`wg-client-gui.exe`/`wg-client.exe` Windows (compilés sous Wine — la
recette ci-dessous les valide sur un vrai Windows) et le MSI WireGuard
officiel embarqué. Le binaire macOS se construit sur un Mac avec les
mêmes commandes PyInstaller (voir la cible `build-clients` du Makefile).

Prérequis communs : un compte de test dans le SSO avec au moins deux
services accordés (deux tunnels attendus), une stack WDG joignable
(maquette exposée ou environnement de test), et l'URL publique du plan de
contrôle.

Cocher chaque case ; noter version OS + version WireGuard en tête de
rapport.

## macOS

Environnement : macOS avec l'app WireGuard (App Store) **ou**
`brew install wireguard-tools` (la CLI `wg-quick` est requise : c'est elle
que le client pilote).

1. [ ] Binaire `wg-client-gui` (compilé sur Mac, mêmes commandes
   PyInstaller que `build-clients`) démarre ; icône dans la barre de
   menus. À défaut, `pipx install 'wdg-client[gui]'` + `wg-client-gui`.
2. [ ] **Se connecter** (ou `wg-client connect`) : le navigateur s'ouvre,
   le SSO aboutit, retour sans action.
3. [ ] Trousseau : ouvrir Trousseaux d'accès → une entrée `wg-client`
   (clé privée + jeton). La clé n'apparaît dans aucun fichier.
4. [ ] Deux tunnels montés (`wg-client status` : une ligne par service,
   poignée de main < 2 min) ; interfaces visibles dans `wg show`
   (`utun*`).
5. [ ] Confs écrites dans `/usr/local/etc/wireguard/wdg*.conf`, mode 600.
6. [ ] Atteindre une ressource de chaque réseau accordé (HTTP/SSH).
7. [ ] Ressource d'un réseau **non** accordé : injoignable.
8. [ ] Failover : demander à l'exploitant de couper l'instance préférée →
   `wg-client reconnect` bascule sur l'autre site (≤ ~15 s par instance).
9. [ ] `wg-client disconnect` : interfaces disparues, confs supprimées ou
   inactives ; reconnexion propre derrière.
10. [ ] `WDG_LANG=fr wg-client status` : sortie en français.
11. [ ] (si exigé) `configure --require-pq` : soit PQ négocié, soit refus
    propre avec le message OpenSSL ≥ 3.5.

## Windows

Environnement : Windows 10/11, de préférence **sans** WireGuard préinstallé
(pour éprouver l'installation embarquée) ; lancement **administrateur**
(l'installation du MSI et des services tunnel l'exige).

1. [ ] `wg-client-gui.exe` (build Wine) démarre ; icône dans la zone de
   notification ; **au premier lancement sans WireGuard, propose et
   réussit l'installation silencieuse du MSI embarqué** (posé à côté de
   l'exe). À défaut, `pipx install wdg-client` pour la CLI seule.
2. [ ] Bouton **Se connecter** (ou `wg-client connect` en terminal admin) :
   SSO navigateur OK.
3. [ ] Gestionnaire d'identifiants : entrées `wg-client` présentes.
4. [ ] Registre : `HKLM\Software\WireGuard\MultipleSimultaneousTunnels = 1`
   (posé automatiquement par le client).
5. [ ] Deux services tunnel `WireGuardTunnel$wdg0`/`$wdg1` en cours
   d'exécution (`sc query` ou l'interface WireGuard) — **les deux
   simultanément** : c'est le point le plus important de la recette
   Windows.
6. [ ] Confs écrites sous `C:\ProgramData\WireGuard\wdg*.conf`.
7. [ ] Réseaux accordés joignables ; réseau non accordé injoignable.
8. [ ] `wg-client status` : l'état repose sur le service (pas d'âge de
   poignée de main sous Windows — comportement attendu).
9. [ ] `wg-client disconnect` : services désinstallés proprement.
10. [ ] Terminal **non**-admin : `connect` échoue avec un message
    compréhensible (pas de traceback) — noter le message obtenu.
11. [ ] `WDG_LANG=fr` : sortie en français.

## Résultat

- Les deux checklists complètes → cocher « Client Python (macOS / Windows) »
  dans le README et retirer la réserve du
  [GUIDE-UTILISATEUR](GUIDE-UTILISATEUR.md) s'il en mentionne une.
- Tout écart : ouvrir un ticket avec la ligne cochée en échec, le message
  exact et les versions — le chemin de code correspondant est isolé dans
  `wg_client/tunnel.py`, les corrections sont locales.
