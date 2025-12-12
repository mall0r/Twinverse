[English](../README.md) | [Português (Brasil)](./README.pt-br.md) | [Français](./README.fr.md) | [Español](./README.es.md)

# MultiScope

**MultiScope** est un outil open-source pour Linux qui permet la création et la gestion de plusieurs sessions gamescope de steam, autorisant ainsi plusieurs joueurs à jouer simultanément sur un seul ordinateur.

---

## État du Projet

MultiScope est actuellement en développement actif mais est déjà entièrement fonctionnel pour les utilisateurs possédant des **cartes graphiques AMD**. Des tests sur du matériel **NVIDIA** n'ont pas encore été effectués, la compatibilité n'est donc pas garantie.

- **Compatibilité :**
  - ✅ **AMD :** Entièrement compatible
  - ⚠️ **NVIDIA :** Tests requis
  - ⚠️ **Intel :** Tests requis

## Le Problème que MultiScope Résout

De nombreux joueurs qui passent à Linux regrettent des outils comme **Nucleus Coop**, qui facilitent le multijoueur local dans les jeux qui ne le supportent pas nativement. MultiScope a été créé pour combler cette lacune, en offrant une solution robuste et facile à utiliser pour que les amis et la famille puissent jouer ensemble sur le même PC, même s'ils n'ont pas plusieurs ordinateurs.

## Fonctionnalités

- **Gestion des Profils :** Créez, modifiez et supprimez des profils pour différents jeux et configurations.
- **Interface Graphique Conviviale :** Une interface intuitive pour gérer les profils et les instances de jeu.
- **Support Multi-Écrans :** Configurez chaque instance de jeu pour qu'elle s'exécute sur un écran spécifique.
- **Paramètres Audio :** Dirigez l'audio de chaque instance vers différents périphériques de sortie.
- **Support de Plusieurs Claviers et Souris :** Assignez des périphériques d'entrée spécifiques à chaque joueur.

## Démonstration

*(Espace réservé pour des captures d'écran, des GIF ou des vidéos de MultiScope en action. Pour ajouter une image, utilisez la syntaxe suivante :)*
`![Description de l'image](URL_DE_L'IMAGE)`

## Installation

La manière la plus simple d'installer MultiScope est d'utiliser le paquet de la version, qui s'occupe de tout pour vous.

1.  **Téléchargez la dernière version :**
    Allez sur la page des [Releases](https://github.com/Mallor705/MultiScope/releases) et téléchargez le fichier `MultiScope.tar.gz`.

2.  **Extrayez l'archive :**
    ```bash
    tar -xzvf MultiScope.tar.gz
    ```

3.  **Accédez au dossier extrait :**
    (Le nom du dossier peut varier en fonction de la version)
    ```bash
    cd MultiScope-*
    ```

4.  **Exécutez le script d'installation :**
    ```bash
    ./install.sh
    ```

Après l'installation, vous trouverez MultiScope dans le menu des applications de votre système ou vous pourrez le lancer depuis le terminal avec la commande `multi-scope gui`. Le paquet inclut également un script `uninstall.sh` pour supprimer l'application.

## Comment Utiliser

1.  **Ouvrez MultiScope :** Lancez l'application depuis le menu des applications ou le terminal.
2.  **Créez un Profil :**
    - Cliquez sur "Ajouter un profil".
    - Nommez le profil (ex: "Stardew Valley - Joueur 1").
    - Configurez les options d'écran, d'audio et de périphériques d'entrée.
    - Enregistrez le profil.
3.  **Lancez un Jeu :**
    - Sélectionnez le profil souhaité.
    - Cliquez sur "Démarrer" pour ouvrir le jeu avec les paramètres définis.

## Compiler à Partir des Sources

Si vous êtes développeur et que vous souhaitez compiler le projet manuellement, suivez les étapes ci-dessous :

1.  **Clonez le dépôt :**
    ```bash
    git clone https://github.com/Mallor705/MultiScope.git
    cd MultiScope
    ```

2.  **Pour exécuter directement depuis les sources :**
    - Créez et activez un environnement virtuel :
      ```bash
      python3 -m venv .venv
      source .venv/bin/activate
      ```
    - Installez les dépendances :
      ```bash
      pip install -r requirements.txt
      ```
    - Exécutez l'application :
      ```bash
      ./run.sh
      ```
    
3.  **Pour compiler et installer à partir des sources :**
    ```bash
    ./build.sh
    ./install.sh
    ```

## Comment Contribuer

Nous apprécions votre intérêt à contribuer à MultiScope ! Si vous souhaitez aider, veuillez suivre ces directives :

1.  **Forkez le Dépôt :** Créez une copie du projet sur votre compte GitHub.
2.  **Créez une Branche :** Créez une branche pour votre nouvelle fonctionnalité ou correction (`git checkout -b ma-fonctionnalite`).
3.  **Faites vos Modifications :** Implémentez vos améliorations ou corrections.
4.  **Soumettez une Pull Request :** Ouvrez une Pull Request détaillant vos modifications.

Toutes les contributions sont les bienvenues, des corrections de bugs à l'implémentation de nouvelles fonctionnalités.

## Licence

Ce projet est sous licence **GNU General Public License v3.0 (GPL-3.0)**. Pour plus de détails, consultez le fichier [LICENSE](LICENSE).
