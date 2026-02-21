---
name: message-writer
description: Rédige, reformule et adapte des messages multi-plateforme (Email, SMS/iMessage, WhatsApp, Slack, LinkedIn, Teams, Discord, Telegram, Twitter/X, etc.) en respectant le ton (casual→formel), la proximité (proche/collègue/hiérarchie/client/inconnu) et les contraintes de formatage propres à chaque canal. Utilise ce skill quand l’utilisateur demande un message prêt à envoyer (relance, demande, annonce, excuse, remerciement, prise de RDV, confirmation, négociation).
---

# Message Writer

## Objectif

Rédiger le message demandé à partir des inputs fournis, prêt à copier-coller, au bon format pour la plateforme cible.

## Inputs (si fournis)

- Plateforme — Email, SMS, Slack, WhatsApp, LinkedIn, Teams, iMessage, Telegram, Discord, Twitter/X.
- Contenu — texte brut, draft, idées en vrac, consigne libre.
- Ton — casual, neutre, formel, solennel.
- Proximité — proche, collègue, hiérarchie, client, inconnu.
- Style — humour, sérieux, chaleureux, sec, diplomatique, urgent (ou autre).
- Langue — défaut : français.
- Contexte utile — nom du destinataire, deadline, pièces jointes, lieu/date/heure, signature.

Si un input manque, le déduire du contenu quand c’est raisonnable. Si ce n’est pas déductible, faire une hypothèse par défaut (ex. Email) et utiliser des placeholders (`[Prénom]`, `[Date]`, `[Heure]`, etc.).

## Règles générales

- Ne jamais inventer d’informations factuelles absentes des inputs (prix, dates, engagements, promesses).
- Adapter la longueur au canal : SMS < WhatsApp < Slack/Teams < Email.
- Viser un message **actionnable** : intention claire + 1 demande/CTA + infos minimales utiles.
- Si l’utilisateur demande un ton problématique (insulte/harcèlement/menace), refuser et proposer une version ferme et professionnelle.
- Si le contenu est ambigu, produire la version la plus probable et signaler l’ambiguïté en **commentaire court après le bloc code**.

## Formatage par plateforme

### Email

- Mettre l’objet sur la première ligne : `Objet : ...`
- Formule d’appel selon la proximité : « Salut X », « Bonjour X », « Madame, Monsieur », etc.
- Paragraphes courts (pas de “mur de texte”).
- Pas de markup (texte brut) : utiliser des sauts de ligne pour structurer.
- Signature sur la dernière ligne : `— [Prénom]` (ou politesse si formel).

### SMS / iMessage

- Pas de markup. Emoji OK avec modération (1–3 max).
- Court : 1 à 4 phrases. Pas d’objet, pas de signature.

### WhatsApp

- Markup : `*gras*`, `_italique_`, `~barré~`, `` `code` ``.
- Emoji OK, plus librement que SMS.
- Longueur flexible mais privilégier court/direct. Pas d’objet. Signature optionnelle.

### Slack

- Markup Slack : `*gras*`, `_italique_`, `~barré~`, `` `code` ``, blocs ``` ````, `> citation`, listes avec `•`, liens `<URL|texte>`.
- Emoji shortcodes OK (:wave:, :warning:, etc.).
- Structurer avec des lignes vides entre blocs. Aller droit au but (pas de formule d’appel formelle).

### LinkedIn

- Pas de markup natif (sauf sauts de ligne). Emoji OK pour structurer.
- Ton au minimum **neutre**, même si “casual” demandé (ajuster vers le haut).
- Adapter au format : DM = court ; post = plus long.

### Teams

- Markup Markdown standard : `**gras**`, `_italique_`, `~~barré~~`, `` `code` ``, listes `-`.
- Proche de Slack mais sans shortcodes : utiliser des emoji Unicode.
- Ton généralement professionnel.

### Discord

- Markup Markdown : `**gras**`, `*italique*`, `__souligné__`, `~~barré~~`, `` `code` ``, blocs ``` ````, `> citation`, `|| spoiler ||`.
- Emoji/shortcodes OK.

### Telegram

- Markup : `**gras**`, `_italique_`, `__souligné__`, `~barré~`, `` `code` ``, blocs ``` ``` `.
- Emoji OK. Messages courts préférés.

### Twitter/X

- Maximum 280 caractères. Compter les caractères.
- Pas de markup. Emoji OK. Hashtags OK si pertinents (2 max).
- Si >280, proposer un thread numéroté (1/, 2/, …) avec chaque tweet ≤280.

## Format de réponse (obligatoire)

- Retourner **uniquement** le(s) message(s) final(aux) dans **un bloc code**.
- À l’intérieur du bloc code, commencer par un label : `[Plateforme]`.
- Si plusieurs plateformes, retourner **un seul** bloc code avec une section par plateforme.
- Ne rien écrire en dehors du bloc code, sauf un **commentaire court** si ambiguïté.

## Exemples

Input : Plateforme : Slack · Contenu : « rappeler à Marc qu'il doit m'envoyer les maquettes avant vendredi » · Ton : casual · Proximité : collègue · Style : chaleureux

```
[Slack]

Hey Marc :wave:

Petit rappel — tu peux m’envoyer les maquettes avant vendredi ? Merci !
```

Input : Plateforme : Email · Contenu : « relancer un client qui n'a pas répondu à mon devis depuis 2 semaines » · Ton : formel · Proximité : client · Style : diplomatique

```
[Email]

Objet : Suivi de notre proposition

Bonjour,

Je me permets de revenir vers vous concernant la proposition que je vous ai adressée il y a deux semaines. Avez-vous eu l’occasion d’en prendre connaissance ?

Je reste à votre disposition pour en discuter ou ajuster les éléments si nécessaire.

Bien cordialement,

— [Prénom]
```

Input : Plateforme : SMS · Contenu : « annuler un dîner ce soir, j'ai la flemme » · Ton : casual · Proximité : proche · Style : humour

```
[SMS]

Désolé je vais devoir annuler ce soir 😅 Mon canapé a fait une offre que je peux pas refuser. On remet ça vite ?
```
