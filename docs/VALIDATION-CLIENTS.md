# Recette des clients macOS et Windows

Le code des trois plateformes existe et les chemins macOS/Windows sont
couverts par des tests unitaires à base de mocks (`wg_client/test_tunnel.py`) ;
seul **Linux** a été validé de bout en bout (client-probe Docker). Ce
document est la checklist de recette à dérouler **sur de vraies machines**
macOS et Windows pour lever la réserve — une exécution complète par OS
suffit.

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

1. [ ] `pipx install wdg-client` → `wg-client --help` fonctionne.
2. [ ] `wg-client configure --server https://…` puis `wg-client connect` :
   le navigateur s'ouvre, le SSO aboutit, retour terminal sans action.
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

Environnement : Windows 10/11 avec le client WireGuard officiel
(`C:\Program Files\WireGuard\`), terminal **administrateur** (l'installation
de services tunnel l'exige).

1. [ ] `pipx install wdg-client` → `wg-client --help` fonctionne.
2. [ ] `wg-client configure` + `wg-client connect` : SSO navigateur OK.
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
