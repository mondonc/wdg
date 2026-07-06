# Guide utilisateur — accès distant WDG

Ce guide s'adresse à **vous qui utilisez le VPN**, pas aux équipes qui
l'exploitent. Aucune connaissance réseau n'est nécessaire. Pour comprendre
comment le système fonctionne sous le capot, voir
[PARCOURS-UTILISATEUR.md](PARCOURS-UTILISATEUR.md).

En deux mots : vous lancez l'application WDG (un seul fichier), vous vous
connectez avec votre compte habituel (SSO), et ensuite tout est
automatique — vos accès suivent vos droits, sans fichier de configuration
à manipuler.

## 1. Installation (une fois)

**Le plus simple : l'application graphique tout-en-un** fournie par votre
équipe informatique — un seul fichier à lancer, rien d'autre à installer :

| Système | Fichier | Remarque |
|---|---|---|
| Windows | `wg-client-gui.exe` | au premier lancement, propose d'installer WireGuard tout seul (fourni avec) |
| Linux | `wg-client-gui` | WireGuard vient de votre distribution : `sudo apt install wireguard` |
| macOS | `wg-client-gui.app` | avec `brew install wireguard-tools` |

Lancez l'application : une icône WDG apparaît près de l'horloge (zone de
notification). Dans la fenêtre, renseignez une fois le champ **Serveur**
(adresse fournie par votre équipe, généralement `https://vpn.example.org`)
et cliquez **Enregistrer**.

<details>
<summary>Alternative en ligne de commande (utilisateurs avancés)</summary>

Installez WireGuard (tableau ci-dessus), puis :

```sh
pipx install wdg-client        # fournit la commande wg-client
wg-client configure --server https://vpn.example.org
```
</details>

## 2. Se connecter

Cliquez **Se connecter** dans la fenêtre WDG (ou dans le menu de l'icône,
clic droit). En ligne de commande : `wg-client connect`.

Ce qui va se passer :

1. **Votre navigateur s'ouvre** sur la page de connexion habituelle de
   l'établissement (SSO). Connectez-vous comme d'habitude — mot de passe,
   double authentification si vous en avez une.
2. Revenez à l'application : le client récupère vos accès et **monte les
   tunnels tout seul**. À la première connexion, il génère aussi votre
   clé personnelle (elle ne quitte jamais votre poste).
3. Vous voyez une ligne par accès dans le journal (et le tableau d'état
   se remplit), par exemple :

   ```
   ✓ wdg-users actif via gw-users-a (wdg0 : 10.30.0.0/23, 10.20.10.0/24).
   ```

C'est tout. Vos applications (navigateur, SSH, RDP…) fonctionnent
normalement : seul le trafic vers les réseaux de l'établissement passe
par le tunnel, le reste de votre navigation n'est pas touché.

La session de connexion est valable **12 heures** : au-delà, un
`wg-client connect` vous redemandera simplement de vous authentifier.

## 3. Au quotidien

Tout se fait depuis l'icône WDG près de l'horloge (clic droit) ou la
fenêtre. Fermer la fenêtre ne coupe rien : l'application reste dans la
zone de notification ; **Quitter** est dans le menu de l'icône.

| Ce que vous voulez | Icône / fenêtre | Ligne de commande |
|---|---|---|
| Vous connecter | menu **Se connecter** | `wg-client connect` |
| Voir l'état de vos tunnels | ouvrir la fenêtre (tableau) | `wg-client status` |
| Vous déconnecter | menu **Se déconnecter** | `wg-client disconnect` |
| Recharger vos accès (droits modifiés) | menu **Reconnecter** | `wg-client reconnect` |
| Vérifier qui vous êtes / vos groupes | bouton **Qui suis-je ?** | `wg-client login` |
| Oublier la session sur ce poste | — | `wg-client logout` |

En français : le client parle la langue de votre système ; pour forcer,
`WDG_LANG=fr wg-client …`.

## 4. Les questions fréquentes

**On m'a donné accès à un nouveau réseau, je ne le vois pas.**
Vos droits sont bien actifs côté serveur (en quelques secondes), mais
votre poste garde la liste d'accès chargée à la connexion. Cliquez
**Reconnecter** (ou `wg-client reconnect`) : elle sera rechargée.

**« Permission denied » / rien ne se monte.**
Établir un tunnel demande les droits administrateur du poste : sous
Windows, lancez l'application par clic droit → « Exécuter en tant
qu'administrateur » ; sous Linux/macOS, lancez-la avec `sudo` (l'élévation
intégrée arrivera dans une version ultérieure).

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
