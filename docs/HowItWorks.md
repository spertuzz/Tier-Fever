# Okay, this is where the *real* fun starts.

You're here because you want to know how the game works. Good news: it's actually not *that* complicated. It was mainly a design challenge. But before we get into that, we have to be clear about what is being used here:

## What am I using?

Not much, really:

- **Python** to run:
  - **Flask** for the server itself and POSTing and GETting and everything.
  - **Flask-Session** for sessions.
  - **Flask-SocketIO** for WebSockets.
- **HTML** & **CSS** for the website's layout.
  - Plus **Jinja2** for the templates.
- **JavaScript** for general client-side programming.

Those are the *essentials*. What I used for the website to work. Like, it can run on my PC with just that. But, of course, I needed a little more for the RPi setup to be solid. So, this is what came after:

- **Gunicorn** to run the actual server on the RPi and streamline/speed things up.
- **Docker** to actually run the process on the RPi (for real this time) in a container.
- **Tailscale** to open my site to the public through a funnel (I do not have a static IP).

## Great! How do I make a room, though?

Good question! For this project, I treated a room as a list of its properties. What even is a room? In this game, it's just the players, the game phase (or `state` in my code), the room settings, and maybe some other things sprinkled in here and there. I split my rooms in two: one server-side dictionary, titled `rooms`, handles the players, while one titled `settings` handles all other properties about the room. This is what they look like:

```python
# Example of an entry in the "rooms" array
rooms[code][name] = {
    'score': 0,
    'host': True,
    'master': False,
    'picks': None,
    'pick_breakdown': None,
    'connected': True,
    'last_ping': None
}

# Example of an entry in the "settings" array
settings[code] = {
    'state': 'open',
    'round': 0,
    'timer_start': 0,
    'timer_end': 0,
    'current_master': None,
    'past_masters': [],
    'active_cat': None,
    'current_cats': None,
    'past_cats': [],
    'locked_players': [],
    'master_picks': None,
    'starting_scores': None,
    'ending_scores': None,
    'configs': {
        'master_choice_time': master_time,
        'player_tier_time': tiering_time,
        'masters_enabled': masters_enabled,
        'rounds': rounds,
        'max_elements': max_elements,
        'safe_mode': safe_mode
    }
}
```

So, yeah, that's a lot of things, but what truly matters is that they're simply the room's characteristics expressed as a dictionary. Now, you may have noticed that `code` index in the dictionary. That's actually the room code! This is a randomly chosen 6-digit number that is created whenever a room is made and becomes its unique identifier (and is also the number your friends use to join your room).

When players input the code to join the room, this adds them to the SocketIO room (through the `join_room` command) named after the room's code (meaning all SocketIO messages sent to the room will only be received by them), and new player instances are added to the `rooms[code]` dictionary, where players in the room are stored. `settings[code]`, similarly, would hold this room's settings.

## Cool, but how does that become a game?

It's actually quite simple. After a round starts, all phases work in very similar ways. Essentially, I wanted to avoid using too many SocketIO pings between the player and the server, since these can be a little finicky and unreliable. To prevent these hurdles from ruining the experience, I decided to only do *one* main server-to-client ping per round. To maximize the potential of this ping (and to make sure the client receives enough information to handle the rest of the round), the packets sent across them are a bit dense. Here's one of them:

```python
# Example of a dense packet used for the tiering phase
{
    'category': settings[code]['active_cat'],
    'master': settings[code]['current_master'],
    'timer_start': start_time,
    'timer_end': end_time,
    'server_time': time.time(),
    'round': settings[code]['round'],
    'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
}
```

Here, you can already see some relevant information being sent: `category`, so the client knows the category being ranked and its element; `master`, so the client knows who the master is; and `round`/`total_rounds`, which are numbers rendered on the screen. So, just from this information, it's enough to reconstruct most of the scene. Like, in the tiering state, knowing all the elements to be ranked and who the current master is (alongside those round numbers) is already enough to place those elements on the screen and have the player move them around. The one question left is: what are those *timer* things?

### The Timer System

In my game, I have to prevent things from dragging out. I can't just leave players editing their lists forever or allow the master to take ages to choose a category, as that would really suck.

Right when packets are being sent to all players so they can reconstruct the scene, a background timer is started using `socketio.start_background_task`
