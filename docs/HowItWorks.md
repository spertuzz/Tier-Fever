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

Something important to note is that my Gunicorn instance is running with only one `eventlet` worker because all my stuff is in local Python dictionaries in the server RAM...
I also used `better_profanity` and `profanity_check` to create a mixed profanity filter that can be optionally enabled or disabled.

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

It's actually quite simple. After a round starts, all phases work in very similar ways. Essentially, I wanted to avoid using too many SocketIO pings between the player and the server, since these can be a little finicky and unreliable. Plus, I didn't want to overload my RPi. To prevent these hurdles from ruining the experience, I decided to only do *one* main server-to-client ping per round. To maximize the potential of this ping (and to make sure the client receives enough information to handle the rest of the round), the packets sent across them are a bit dense. Here's one of them:

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

Here, you can already see some relevant information being sent: `category`, so the client knows the category being ranked and its element; `master`, so the client knows who the master is; and `round`/`total_rounds`, which are numbers rendered on the screen. So, just from this information, it's enough to reconstruct most of the scene. Like, in the tiering state, knowing all the elements to be ranked and who the current master is (alongside those round numbers) is already enough to place those elements on the screen and have the player move them around. Even the *entire* scoring sequence is handled on the client, as the server sends all the necessary information to make that happen.

The one question left is: what are those *timer* things?

### The Timer System

In my game, I have to prevent things from dragging out. I can't just leave players editing their lists forever or allow the master to take ages to choose a category, as that would really suck.

As soon as packets are sent to all players so they can reconstruct the scene, a background timer starts using `socketio.start_background_task` and waits until it runs out. If it runs out before all players finish, then the packet sends everyone to the next game phase. Here's an example of one of these timers:

```python
# Timer in case the master takes too long to decide
def select_timer(code, wait_time):  # For the selection phase
    # Wait the given time
    socketio.sleep(wait_time)
    # Check if the game still has not progressed
    if settings[code]['state'] == 'selection':
        # Set the new game state
        settings[code]['state'] = 'tiering'
        
        # Select a random category
        category_name = random.choice(settings[code]['current_cats'])
        category_elements = random.sample(categories[category_name], settings[code]['configs']['max_elements'])
        settings[code]['past_cats'].append(category_name)
        
        # Format in settings
        settings[code]['active_cat'] = { 'name': category_name, 'elements': category_elements }
        settings[code]['state'] = 'tiering'
        
        # Decide new timer
        start_time = time.time()
        end_time = start_time +  settings[code]['configs']['player_tier_time']
        settings[code]['timer_start'] = start_time
        settings[code]['timer_end'] = end_time
        
        # Start next phase
        packet = {
            'route': 'tier',
            'data': {
                'category': settings[code]['active_cat'],
                'master': settings[code]['current_master'],
                'timer_start': start_time,
                'timer_end': end_time,
                'server_time': time.time()
            }
        }
        ping(code, None, packet)
```

This simply sends clients right to the next phase (the tiering phase, in this case) to prevent the game from stalling.

Now, I know what you may be thinking. Why, then, am I providing those timer variables in the packet?

It's simple, really. They're used so the client can build the progress bars (timers) on their own screen, running calculations based on those variables. It's nifty because, if they refresh the tab, the game could provide them with a new value for `server_time` to build the timer in sync with the game. Here's an example:

```javascript
// Gather progress bar elements and relevant numbers
const progress_bar = document.getElementById('select_timer')
const start_time = data['timer_start']
const end_time = data['timer_end']
const diff = end_time - start_time
const offset = data['server_time'] + data['latency'] - Date.now() / 1000

// Start timer loop (low wait time for smoothness)
timer = setInterval(function() {
  // Calculate time difference and progress bar progress
  let current_time = Date.now() / 1000 + offset
  let frac = (current_time - start_time) / diff
  let done = false
  // Logic in case timer ends prematurely
  if (frac > 1) {
    done = true
    frac = 1
  }
  progress_bar.style.width = (frac * 100).toString() + '%'
  
  // Handle color changes
  if (frac < 0.5) {
    progress_bar.style.color = '#198754'
    progress_bar.style.backgroundColor = '#198754'
    progress_bar.style.borderColor = '#198754'
  }
  else if (frac < 0.8) {
    progress_bar.style.color = '#ffc107'
    progress_bar.style.backgroundColor = '#ffc107'
    progress_bar.style.borderColor = '#ffc107'
  }
  else {
    progress_bar.style.color = '#dc3545'
    progress_bar.style.backgroundColor = '#dc3545'
    progress_bar.style.borderColor = '#dc3545'
  }
  
  // Stop animation if the timer ends
  if (done) clearInterval(timer)
}, 100)
```

This leads to a functioning game.

## Wait, refreshing? That can kill a lot of games.

Not mine (hopefully)! The key benefit of storing all room data in my weird little dictionary system is that, if a player ever disconnects and reconnects later, my server can pick up on that (if I have a `join` block in my client to send a `SocketIO` request) and send the client a packet to reconstruct the game at the same phase as everyone else. I call this "state saving". Plus, since my timer system allows for the current server time to be sent, the client can actually build the timer to be synced with other players. Pretty cool!

## What is `data['latency']`? I didn't see that in the packet!

Yeah, that's because it isn't there by itself. In fact, careful readers may have noticed that I haven't been using `emit` or `socketio.emit` for all these things. Rather, a weird `ping` function appears. What is that?

When I first made this game, I never calculated the client-server offset, so even if my math was perfect, players would be out of sync because of latency. Now, I could code a small latency calculation into the start of every client-side process (something like `const latency = Date.now() / 1000 - data['server_time']`), but I didn't want to do that. It would be *boring*. I wanted to not have to think about this. So I made `ping`.

What `ping` does is quite simple. When you pass the packet and receiver (`None` here means the entire room), `ping` stores them away for a bit and sends an empty packet to the receiver. Once it reaches the client, they immediately send another one back. Once it returns, it is received by a `pong_handler` function, which calculates the time elapsed since `ping` sent the initial message. Then, it sends the intended packet stored by `ping` to the receiver, adding `data['latency']` to it as the delay.

Now, that name, `data['latency']`, is a misnomer. Latency is usually RTT, or round-trip time, meaning the amount of time taken for a packet to reach the client and return. However, this is not what I send in `data['latency']`. Instead, the client actually receives `(end_time - start_time) * 1.5` or `RTT * 1.5`. But why? It's easy to see if you count how many times a packet is sent since the initial `ping`:

- First, the server sent an empty packet to the client.
- Then, the client sent back an empty message.
- Finally, the server sent the client the real packet.

That's 3 total trips, and `start_time` (which is included in many packets) was calculated back when `ping` was first called. If I want clients to correct themselves using the full time elapsed since the initial ping, I need to send the total delay for all these trips. Since it's 3 trips and not 2, a valid estimate for this time would be precisely `RTT * 1.5`.

Now, is this the best approach? I'll admit, it isn't. There are more reliable ways to sync clocks. A really competitive and hyper-precise multiplayer game would definitely ping players more often to account for random jitter, and would likely do a simple RTT calculation on the client since my 1.5 estimate, though correct, is still an estimate because we can't know how long that third trip will be. Nonetheless, it works for this game since it generally doesn't need millisecond-level precision. I just wanted my clocks to be in sync.

## Is that all?

Technically, no. Of course, there's many other small design decisions made in this game. Like choosing to make the threshold for a "controversial" ranking be $\sigma \geq 2$ (where each tier is an integer), but if I listed and explained them all, we'd be here for ages. What I told you just now is pretty much the most important stuff to know.

*(Well, unless you want to set it up on your own RPi. Just copy it on there and run `docker compose up -d --build`.)*

---

This project was honestly such a fun experience. I learned a ton about full-stack development, and also some fancy terms. Well, maybe. I was convinced for a while that my little ping-pong system was called an "NTP", and I recently learned, like, a week ago that this isn't true. Besides small stumbles like that, this was a blast!

Thank you so much for taking the time to read this, and I hope you have an amazing day!
