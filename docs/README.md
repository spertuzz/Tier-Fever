# Tier Fever

Welcome! Have you ever wanted to play a game about tier lists? Well, you probably haven't. That's an oddly specific thing to want. But if you somehow did, then this is the game for you!

## The Game Itself

Tier Fever is a multiplayer web game designed specifically to run in a Docker container, and even more specifically for my Raspberry Pi 5. It was designed to mimic the simple, easy-to-play style of games in the Jackbox Party Packs and the room-based systems in games like Gartic Phone. Anyone can create a room with the settings they desire, and others can join that room by inputting its code. Once enough people have joined, the host can start the game. Then, it proceeds as follows.

### Selection Phase

At the start of the game, a player will be chosen to be the **master**. In the selection phase, the master must select one of 3 categories of objects for players to rank, as the next part of the game will involve placing things on a tier list. If the master is dissatisfied with the options shown or has something unique in mind, they can write out their own list of elements. After they make their choice, the game moves on to the next phase.

### Tiering Phase

Here, players are working towards one goal: **maximizing score**. They are all given a blank tier list and an equal list of elements belonging to the category chosen by the master.

The way you earn score depends on who you're playing as:

- If you're a player, your goal is to match the master. Without being able to see their rankings, you must try to predict their placements as accurately as possible. In other words, try making the tier list they would make. Here, it helps to be playing with friends that you know fairly well.
- If you're the master, you want other players to succeed at predicting your list, as you'll be rewarded for that. In other words, don't try to sabotage the players. Your score depends on how well they guess your choices.

After everyone submits their lists (or the time runs out), the round moves onto its final phase.

### Scoring Phase

Finally, the results for the round are revealed. One by one, the master's placements are shown, and players receive points based on how accurately they predicted them:

- Guessing the master's 
