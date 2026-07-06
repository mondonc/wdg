# Guide utilisateur — accès distant WDG

Ce guide s'adresse à **vous qui utilisez le VPN**, pas aux équipes qui
l'exploitent. Aucune connaissance réseau n'est nécessaire. Pour comprendre
comment le système fonctionne sous le capot, voir
[PARCOURS-UTILISATEUR.md](PARCOURS-UTILISATEUR.md).

En deux mots : vous installez WireGuard et le client WDG, vous vous
connectez une fois avec votre compte habituel (SSO), et ensuite tout est
automatique — vos accès suivent vos droits, sans fichier de configuration
à manipuler.

## 1. Installation (une fois)

Deux logiciels à installer :

**WireGuard** (le moteur du tunnel) :

| Système | Comment |
|---|---|
| Windows | installeur officiel : <https://www.wireguard.com/install/> |
| macOS | app WireGuard du Mac App Store, ou `brew install wireguard-tools` |
| Linux | `sudo apt install wireguard` (ou équivalent de votre distribution) |

**Le client WDG** (`wg-client`) — fourni par votre équipe informatique :

```sh
pipx install wdg-client        # ou : pip install wdg-client
```

Puis indiquez une fois pour toutes l'adresse du service (fournie par
votre équipe, généralement `https://vpn.example.org`) :

```sh
wg-client configure --server https://vpn.example.org
```

## 2. Se connecter

```sh
wg-client connect
```

Ce qui va se passer :

1. **Votre navigateur s'ouvre** sur la page de connexion habituelle de
   l'établissement (SSO). Connectez-vous comme d'habitude — mot de passe,
   double authentification si vous en avez une.
2. Revenez au terminal : le client récupère vos accès et **monte les
   tunnels tout seul**. À la première connexion, il génère aussi votre
   clé personnelle (elle ne quitte jamais votre poste).
3. Vous voyez une ligne par accès, par exemple :

   ```
   ✓ wdg-users actif via gw-users-a (wdg0 : 10.30.0.0/23, 10.20.10.0/24).
   ```

C'est tout. Vos applications (navigateur, SSH, RDP…) fonctionnent
normalement : seul le trafic vers les réseaux de l'établissement passe
par le tunnel, le reste de votre navigation n'est pas touché.

La session de connexion est valable **12 heures** : au-delà, un
`wg-client connect` vous redemandera simplement de vous authentifier.

## 3. Au quotidien

| Ce que vous voulez | Commande |
|---|---|
| Vous connecter | `wg-client connect` |
| Voir l'état de vos tunnels | `wg-client status` |
| Vous déconnecter | `wg-client disconnect` |
| Recharger vos accès (droits modifiés) | `wg-client reconnect` |
| Vérifier qui vous êtes / vos groupes | `wg-client login` |
| Oublier la session sur ce poste | `wg-client logout` |

En français : le client parle la langue de votre système ; pour forcer,
`WDG_LANG=fr wg-client …`.

## 4. Les questions fréquentes

**On m'a donné accès à un nouveau réseau, je ne le vois pas.**
Vos droits sont bien actifs côté serveur (en quelques secondes), mais
votre poste garde la liste d'accès chargée à la connexion. Faites
`wg-client reconnect` : elle sera rechargée.

**« Site en panne » / la connexion a mis du temps puis a fonctionné.**
C'est normal : si le point d'entrée le plus proche ne répond pas, le
client **bascule automatiquement** sur un autre site (une douzaine de
secondes d'attente par essai). Vous n'avez rien à faire.

**Je n'arrive plus à accéder à un réseau qui marchait.**
Vérifiez d'abord `wg-client status` (les tunnels sont-ils montés, la
poignée de main est-elle récente ?). Puis `wg-client reconnect`. Si le
problème persiste, vos droits ont peut-être changé : `wg-client login`
affiche vos groupes actuels — comparez avec ce que vous attendez, et
contactez votre correspondant informatique.

**« The server requires a post-quantum connection… »**
Votre poste n'arrive pas à établir le niveau de chiffrement exigé par le
serveur. Il faut une version récente du système ou d'OpenSSL (≥ 3.5) —
contactez votre correspondant informatique.

**« Le trousseau du système est indisponible… »**
Le client range vos clés dans le coffre de mots de passe du système
(Trousseau macOS, Gestionnaire d'identifiants Windows, keyring GNOME).
Sur un poste Linux sans session graphique, installez `gnome-keyring` ou
le paquet Python `keyrings.alt`.

**`wg-quick not found` / `wireguard.exe not found`.**
WireGuard n'est pas installé (ou pas au chemin standard) : reprenez
l'étape 1.

**Faut-il me déconnecter le soir ?**
Ce n'est pas obligatoire. La session expire seule au bout de 12 h ; les
tunnels restent inoffensifs. `wg-client disconnect` si vous préférez.

**Sur un poste partagé ?**
Chaque session utilisateur du poste a son propre trousseau, donc ses
propres clés et sa propre session WDG. Faites `wg-client logout` en
partant si le compte système est partagé (à éviter).

## 5. En cas de blocage

Donnez à votre correspondant informatique :

1. la sortie de `wg-client status` ;
2. la commande qui échoue et son message d'erreur exact ;
3. votre système (Windows/macOS/Linux) et l'heure de l'incident.

Il pourra vérifier de son côté vos groupes et l'état des passerelles.
