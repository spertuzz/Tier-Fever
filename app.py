import eventlet
eventlet.monkey_patch()

import random
import os
import time
from functools import wraps

from better_profanity import profanity
from profanity_check import predict_prob

from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from flask_socketio import SocketIO, send, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'big_evil_secret_muahahaha'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

rooms = {}
settings = {}
categories = {}

cat_files = os.listdir('categories')

for f in cat_files:
    if not f.endswith('.txt'): continue
    title = None
    with open(f'categories/{f}', newline='', encoding='utf8') as file:
        for row in file:
            line = row.strip()
            if len(line) < 1: continue
            if title is None:
                title = line
                categories[title] = []
            else:
                categories[title].append(line)


# Determine if a string has profanity
def text_filter(text):
    filter1 = profanity.contains_profanity(text)
    filter2 = predict_prob([text])[0] > 0.8
    return filter1 or filter2


@app.after_request
def after_request(response):
    # Ensures responses aren't cached
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Expires'] = 0
    response.headers['Pragma'] = 'no-cache'
    return response

 
# Main decorator (checking for player disconnection)
def handle_state(f):
    @wraps(f)
    
    def decorator(*args, **kwargs):
        # Determine if the player is in a room
        if session.get('room') and session.get('name'):
            name = session['name']
            code = session['room']
            # Check if room still exists
            if code in rooms:
                # Check if the room is active and if the player is actually in it
                if settings[code]['state'] != 'open' and name in rooms[code]:
                    # Send player back to the game
                    return redirect('/game')
        # Return the original function otherwise
        return f(*args, **kwargs)
    
    return decorator


"""
FLASK REDIRECTS
"""


@app.route('/')
@handle_state
def index():
    # Return the index page (the join page)
    message = None
    if session.get('redirect'):
        if session['redirect'] == 'failed_join':
            message = 'This room does not exist!'
        elif session['redirect'] == 'inv_session':
            message = 'Your session contains invalid data.'
        elif session['redirect'] == 'room_closed':
            message = 'This room is not open.'
        elif session['redirect'] == 'kicked':
            message = 'You have been kicked from the room.'
        elif session['redirect'] == 'host_left':
            message = 'The host has closed the session.'
        else:
            message = 'An unknown error occured.'
    session.clear()
    return render_template('index.html', message=message)


@app.route('/join', methods=['GET', 'POST'])
@handle_state
def join():
    # Get room code
    if not session.get('joining'):
        if not request.form.get('code'):
            code = None
        else:
            code = request.form.get('code', type=int)
    else:
        code = session['joining']
    
    # Check if room exists
    if code in rooms:
        # Check if room can be joined
        if settings[code]['state'] != 'open':
            session['redirect'] = 'room_closed'
            return redirect('/')
        # Attempt to join room
        session['joining'] = code
        message = None
        if session.get('redirect'):
            if session['redirect'] == 'no_name':
                message = 'Please enter a name.'
            elif session['redirect'] == 'repeat_name':
                message = 'Someone is already using that name.'
            elif session['redirect'] == 'long_name':
                message = 'Your name cannot exceed 25 characters.'
            elif session['redirect'] == 'profanity':
                message = 'This lobby does not allow profanity.'
            else:
                message = 'An unknown error occured.'
            del session['redirect']
        return render_template('join.html', code=code, message=message)
    else:
        # Redirect user (nonexisting room)
        session['redirect'] = 'failed_join'
        return redirect('/')


@app.route('/room', methods=['GET', 'POST'])
@handle_state
def room():
    code = session.get('room') or session.get('joining')
        
    # Obtain room info and handle error cases
    if (not code) or (code not in rooms):
        session['redirect'] = 'inv_session'
        return redirect('/')
    
    if not session.get('room'):
        # Get username for identification and handle error cases
        if not request.form.get('name'):
            session['redirect'] = 'no_name'
            return redirect('/join')
        name = request.form.get('name').strip()
        if len(name) > 25:
            session['redirect'] = 'long_name'
            return redirect('/join')
        if settings[code]['configs']['safe_mode']:
            if text_filter(name):
                session['redirect'] = 'profanity'
                return redirect('/join')
        if name in rooms[code]:
            session['redirect'] = 'repeat_name'
            return redirect('/join')
            
        # Join room
        session['name'] = name
        session['room'] = code
        rooms[code][name] = {
            'score': 0,
            'host': False,
            'master': False,
            'picks': None,
            'pick_breakdown': None,
            'connected': True,
            'last_ping': None,
        }
    
    # Double-check validity (to fix refreshes)
    if not session.get('name'):
        session['redirect'] = 'inv_session'
        return redirect('/')
    name = session['name']
    if name not in rooms[code]:
        session['redirect'] = 'inv_session'
        return redirect('/')
        
    # Provide room page
    return render_template('room.html', code=code, name=name, players=rooms[code], host=rooms[code][name]['host'])


@app.route('/host', methods=['GET', 'POST'])
@handle_state
def host():
    # Create room with given settings
    if request.method == 'POST':
        # Get player name
        if not request.form.get('name'):
            session['redirect'] = 'no_name'
            return redirect('/host')
        name = request.form.get('name').strip()
        if len(name) > 25:
            session['redirect'] = 'long_name'
            return redirect('/host')
        if request.form.get('safe_mode'):
            if text_filter(name):
                session['redirect'] = 'profanity'
                return redirect('/host')
        
        # Determine available room codes and fetch one
        code = random.randint(100000, 999999)
        while code in rooms:
            code = random.randint(100000, 999999)
            
        # Gather room settings
        rounds = 2
        if request.form.get('rounds'):
            rounds = request.form.get('rounds', type=int)
            if rounds > 10 or rounds < 1:
                rounds = 2
        tiering_time = 40
        if request.form.get('tiering_time'):
            tiering_time = request.form.get('tiering_time', type=int)
            if tiering_time > 120 or tiering_time < 20:
                tiering_time = 40
        max_elements = 10
        if request.form.get('max_elements'):
            max_elements = request.form.get('max_elements', type=int)
            if max_elements > 20 or max_elements < 8:
                max_elements = 10
        master_time = 40
        if request.form.get('master_time'):
            master_time = request.form.get('master_time', type=int)
            if master_time > 120 or master_time < 20:
                master_time = 40
        masters_enabled = request.form.get('masters_enabled')
        safe_mode = request.form.get('safe_mode')
        
        # Create room
        rooms[code] = {}
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
        
        # Join room as host
        session['name'] = name
        session['room'] = code
        rooms[code][name] = {
            'score': 0,
            'host': True,
            'master': False,
            'picks': None,
            'pick_breakdown': None,
            'connected': True,
            'last_ping': None
        }
        return redirect('/room')
    
    # Otherwise send to hosting screen
    message = None
    if session.get('redirect'):
        if session['redirect'] == 'no_name':
            message = 'Please enter a name.'
        elif session['redirect'] == 'none_available':
            message = 'Somehow, there are no available room codes.'
        elif session['redirect'] == 'long_name':
            message = 'Your name cannot exceed 25 characters.'
        elif session['redirect'] == 'profanity':
            message = 'This lobby does not allow profanity.'
        else:
            message = 'An unknown error occured.'
        del session['redirect']
    return render_template('host.html', message=message)


@app.route('/kick', methods=['GET'])
def kick():
    # Set redirect message
    session['redirect'] = 'kicked'
    return redirect('/')


@app.route('/host_left', methods=['GET'])
def host_left():
    # Set redirect message
    session['redirect'] = 'host_left'
    return redirect('/')
    

@app.route('/game', methods=['GET'])
def game():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code] and settings[code]['state'] != 'open':
            # Send player to the game
            return render_template('game.html', name=name)
    return redirect('/')


"""
WEBSOCKETS
"""


# Clean up room
def clean_up(code):
    del rooms[code]
    del settings[code]


# Ping the user and wait for a return
def ping(code, name, packet):
    # Check if valid
    if code not in rooms: return
    if name and name not in rooms[code]: return
    if request and hasattr(request, 'sid'):
        # Set specific id if it exists
        this_sid = request.sid
    else:
        # Set id to the entire room code if not
        this_sid = code
    if name:
        # Set up ping and send empty request to client
        rooms[code][name]['last_ping'] = { 'time': time.time(), 'packet': packet }
        socketio.emit('ping', {}, to=this_sid)
    else:
        # Set up ping for all clients and send them empty requests
        for name in rooms[code]:
            rooms[code][name]['last_ping'] = { 'time': time.time(), 'packet': packet }
        socketio.emit('ping', {}, to=code)


@socketio.on('pong')
def pong_handler():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            # Calculate latency
            last_time = rooms[code][name]['last_ping']['time']
            packet = rooms[code][name]['last_ping']['packet']
            latency = (time.time() - last_time) / 2

            # Create new client packet
            client_data = packet['data'].copy()
            client_data['latency'] = latency

            # Emit data with latency
            emit(packet['route'], client_data, to=request.sid)


@socketio.on('disconnect')
def disconnect_handler():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            # Remove player from the room
            leave_room(code)
            kill = False
            if settings[code]['state'] == 'open':
                kill = rooms[code][name]['host']
                del rooms[code][name]
            else:
                rooms[code][name]['connected'] = False
                        
            # Update other players
            emit('update_players', { 'players': rooms[code], 'kill': kill }, to=code)
            
            # Kill room if empty
            if len(rooms[code]) < 1:
                clean_up(code)


# Timer incase the master takes too long to decide
def select_timer(code, wait_time):
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


@socketio.on('join')
def join_handler():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            # Join room
            join_room(code)
            rooms[code][name]['connected'] = True  
            rooms[code][name]['last_ping'] = None
            
            # Update players in the room
            emit('update_players', { 'players': rooms[code], 'kill': False }, to=code)
            
            # Check if players loaded in (in the 'starting' state)
            if settings[code]['state'] == 'starting':
                # Check if any player isn't loaded
                valid = True
                for player in rooms[code]:
                    if not rooms[code][player]['connected']:
                        valid = False
                        break
                # Move game to the first phase once everyone joins
                if valid:
                    # TBA: Game will start immediately, preferably there should be some animation.
                    
                    # Start selection phase (master)
                    settings[code]['state'] = 'selection'
                    settings[code]['round'] += 1
                    
                    # Determine if current round uses masters
                    if settings[code]['configs']['masters_enabled']:
                        # Select a valid master (trying not to repeat anyone too often)
                        candidates = []
                        for player in rooms[code]:
                            if player not in settings[code]['past_masters']:
                                candidates.append(player)
                        if len(candidates) < 1:
                            # Reset 'past_masters' list if everyone has had a turn
                            settings[code]['past_masters'] = []
                            candidates = list(rooms[code].keys())
                        master = random.choice(candidates)
                        settings[code]['current_master'] = master
                        settings[code]['past_masters'].append(master)
                        
                        # Select valid categories
                        cats = []
                        for i in range(3):
                            candidates = []
                            for category in categories:
                                if (category not in settings[code]['past_cats']) and (category not in cats):
                                    candidates.append(category)
                            if len(candidates) < 1:
                                # Reset 'past_cats' list if all categories have been seen
                                settings[code]['past_cats'] = []
                                candidates = list(categories.keys())
                            winner = random.choice(candidates)
                            cats.append(winner)
                        settings[code]['current_cats'] = cats
                        
                        # Start selection timer
                        start_time = time.time()
                        end_time = start_time + settings[code]['configs']['master_choice_time']
                        settings[code]['timer_start'] = start_time
                        settings[code]['timer_end'] = end_time
                        socketio.start_background_task(select_timer, code, settings[code]['configs']['master_choice_time'] + 1)
                        
                        # Start selection process
                        packet = {
                            'route': 'select',
                            'data': {
                                'master': master,
                                'categories': cats,
                                'timer_start': start_time,
                                'timer_end': end_time,
                                'server_time': time.time(),
                                'max_elements': settings[code]['configs']['max_elements'],
                                'round': settings[code]['round'],
                                'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
                            }
                        }
                        ping(code, None, packet)
                    else:
                        # Select a valid category
                        candidates = []
                        for cat in categories:
                            if cat not in settings[code]['past_cats']:
                                candidates.append(cat)
                        if len(candidates) < 1:
                            # Reset 'past_cats' list if all categories have been seen
                            settings[code]['past_cats'] = []
                            candidates = list(categories.keys())
                        category_name = random.choice(candidates)
                        
                        # Gather category info for selection
                        category_elements = random.sample(categories[category_name], settings[code]['configs']['max_elements'])
                        
                        # Set new category variables
                        settings[code]['active_cat'] = { 'name': category_name, 'elements': category_elements }
                        settings[code]['state'] = 'tiering'
                        
                        # Set new timer
                        start_time = time.time()
                        end_time = start_time +  settings[code]['configs']['player_tier_time']
                        settings[code]['timer_start'] = start_time
                        settings[code]['timer_end'] = end_time
                        
                        # Start timer
                        socketio.start_background_task(tier_timer, code, settings[code]['configs']['player_tier_time'] + 1)
                        
                        # Start next game phase
                        packet = {
                            'route': 'tier',
                            'data': {
                                'category': settings[code]['active_cat'],
                                'master': None,
                                'timer_start': start_time,
                                'timer_end': end_time,
                                'server_time': time.time(),
                                'round': settings[code]['round'],
                                'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
                            }
                        }
                        ping(code, None, packet)
            elif settings[code]['state'] == 'selection':
                # In case of disconnection during selection
                packet = {
                    'route': 'select',
                    'data': {
                        'master': settings[code]['current_master'],
                        'categories': settings[code]['current_cats'],
                        'timer_start': settings[code]['timer_start'],
                        'timer_end': settings[code]['timer_end'],
                        'server_time': time.time(),
                        'max_elements': settings[code]['configs']['max_elements'],
                        'round': settings[code]['round'],
                        'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
                    }
                }
                ping(code, name, packet)
            elif settings[code]['state'] == 'tiering':
                if name not in settings[code]['locked_players']:
                    # In case of disconnection during tiering
                    packet = {
                        'route': 'tier',
                        'data': {
                            'category': settings[code]['active_cat'],
                            'master': settings[code]['current_master'],
                            'timer_start': settings[code]['timer_start'],
                            'timer_end': settings[code]['timer_end'],
                            'server_time': time.time(),
                            'round': settings[code]['round'],
                            'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
                        }
                    }
                    ping(code, name, packet)
                else:
                    # In case of disconnection in the waiting room
                    packet = {
                        'route': 'waiting_room',
                        'data': {
                            'timer_start': settings[code]['timer_start'],
                            'timer_end': settings[code]['timer_end'],
                            'server_time': time.time()
                        }
                    }
                    ping(code, name, packet)
            elif settings[code]['state'] == 'scoring':                
                # Get game host and breakdowns
                host = None
                breakdowns = {}
                for player in rooms[code]:
                    if rooms[code][player]['host']:
                        host = player
                    breakdowns[player] = rooms[code][player]['pick_breakdown']
                
                # Determine if the game is over
                game_over = settings[code]['round'] >= settings[code]['configs']['rounds'] * len(rooms[code])
                
                # In case of disconnection during scoring
                packet = {
                    'route': 'score',
                    'data': {
                        'host': host,
                        'starting_scores': settings[code]['starting_scores'],
                        'picks': breakdowns,
                        'master': settings[code]['current_master'],
                        'master_picks': settings[code]['master_picks'],
                        'leaderboard': settings[code]['ending_scores'],
                        'game_over': game_over
                    }
                }
                ping(code, name, packet)


@socketio.on('kick')
def kick_handler(data):
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            if rooms[code][name]['host'] and settings[code]['state'] == 'open':
                # Kick player
                emit('kick', { 'name': data }, to=code)
                
                
@socketio.on('start_game')
def start_handler():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code] and len(rooms[code]) > 1:
            if rooms[code][name]['host'] and settings[code]['state'] == 'open':
                # Close room
                settings[code]['state'] = 'starting'
                
                # Send players to main game
                emit('start_game', {}, to=code)


@socketio.on('choice')
def choice_handler(data):
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            if settings[code]['current_master'] == name and settings[code]['state'] == 'selection':
                if data['type'] == 'normal':
                    # Gather category info based on normal selection
                    category_name = data['category']
                    category_elements = random.sample(categories[category_name], settings[code]['configs']['max_elements'])
                    settings[code]['past_cats'].append(category_name)
                else:
                    # Gather category info for custom selection
                    category_name = data['category_name']
                    category_elements = data['elements'][:settings[code]['configs']['max_elements']]
                    # Check if list meets requirements
                    if len(category_elements) < settings[code]['configs']['max_elements']:
                        emit('bad_list', {}, to=request.sid)
                        return
                    # Check if list contains profanity (in safe mode)
                    if settings[code]['configs']['safe_mode']:
                        failed_filter = text_filter(category_name)
                        for elem in category_elements:
                            if text_filter(elem):
                                failed_filter = True
                                break
                        if failed_filter:
                            emit('failed_filter', {}, to=request.sid)
                            return
                # Set new category variables
                settings[code]['active_cat'] = { 'name': category_name, 'elements': category_elements }
                settings[code]['state'] = 'tiering'
                
                # Set new timer
                start_time = time.time()
                end_time = start_time +  settings[code]['configs']['player_tier_time']
                settings[code]['timer_start'] = start_time
                settings[code]['timer_end'] = end_time
                
                # Start timer
                socketio.start_background_task(tier_timer, code, settings[code]['configs']['player_tier_time'] + 1)
                
                # Start next game phase
                packet = {
                    'route': 'tier',
                    'data': {
                        'category': settings[code]['active_cat'],
                        'master': settings[code]['current_master'],
                        'timer_start': start_time,
                        'timer_end': end_time,
                        'server_time': time.time(),
                        'round': settings[code]['round'],
                        'total_rounds': settings[code]['configs']['rounds'] * len(rooms[code])
                    }
                }
                ping(code, None, packet)


# Calculate scores for all players
def calculate_scores(code):
    # Reference sheet of letters
    letters = { 'S': 0, 'A': 1, 'B': 2, 'C': 3, 'D': 4, 'F': 5 }
    inv_letters = ['S', 'A', 'B', 'C', 'D', 'F']
    
    # Standard Deviations
    stdevs = {}
    
    # Master pick
    if settings[code]['configs']['masters_enabled']:
        master_picks = rooms[code][settings[code]['current_master']]['picks']
    else:
        master_picks = { 'S': [], 'A': [], 'B': [], 'C': [], 'D': [], 'F': [] }
    
    # Generate player map
    tiers = {}
    for player in rooms[code]:
        tiers[player] = {}
        if rooms[code][player]['picks'] is not None:
            for tier, items in rooms[code][player]['picks'].items():
                for item in items:
                    tiers[player][item] = letters[tier]
    
    # Calculate mean and stdev
    for element in settings[code]['active_cat']['elements']:
        # Select picks
        picks = []
        for player in tiers:
            if element in tiers[player]:
                picks.append(tiers[player][element])
        
        # Mean and stdev calculations
        mean = sum(picks) / len(picks)
        sse = 0
        for tier in picks:
            sse += (tier - mean) ** 2
        stdevs[element] = (sse / len(picks)) ** 0.5
        
        # Add average tier for non-master games
        if not settings[code]['configs']['masters_enabled']:
            mean_tier = inv_letters[round(mean)]
            master_picks[mean_tier].append(element)
    
    # Reset global master picks
    settings[code]['master_picks'] = {}
    
    # Master score accumulator
    master_score = 0
    master_breakdown = {}
    
    # Calculate player scores one by one
    for player in rooms[code]:
        # Prep breakdown
        rooms[code][player]['pick_breakdown'] = {}
        
        # If the player is not the master, evaluate their score by comparing it
        if player == settings[code]['current_master']: continue
        for element in settings[code]['active_cat']['elements']:
            # Check the player's rating
            player_tier = 3
            if element in tiers[player]:
                player_tier = tiers[player][element]
            
            # Check the master's rating
            master_tier = 3
            for letter in master_picks:
                if element in master_picks[letter]:
                    master_tier = letters[letter]
                    break
            
            # Calculate score
            score = 0
            this_master_score = 0
            diff = abs(player_tier - master_tier)
            if (diff == 0):
                score = 500
                this_master_score += 250
            elif (diff == 1):
                score = 250
            controversial = stdevs[element] >= 2
            if controversial:
                score *= 2  # Controversy multiplier
                this_master_score *= 2
            hive_mind = stdevs[element] == 0
            if hive_mind:
                score *= 2
                this_master_score *= 2
            master_score += this_master_score
            
            # Update score and score breakdown
            rooms[code][player]['pick_breakdown'][element] = { 'score': score, 'letter': inv_letters[player_tier] }
            settings[code]['master_picks'][element] = { 'letter': inv_letters[master_tier], 'controversial': controversial, 'hive_mind': hive_mind }
            rooms[code][player]['score'] += score
            
            # Update master breakdown
            if settings[code]['configs']['masters_enabled']:
                if element in master_breakdown:
                    master_breakdown[element]['score'] += this_master_score
                else:
                    master_breakdown[element] = { 'score': this_master_score, 'letter': inv_letters[master_tier] }
    
    # Set master score
    if settings[code]['configs']['masters_enabled']:
        rooms[code][settings[code]['current_master']]['score'] += master_score
        rooms[code][settings[code]['current_master']]['pick_breakdown'] = master_breakdown
        
    # Get leaderboard order
    score_map = {}
    for player in rooms[code]:
        score_map[player] = rooms[code][player]['score']
    sorted_map = [
        {'player': player, 'score': score}
        for player, score in sorted(score_map.items(), key=lambda item: item[1], reverse=True)
    ]
    settings[code]['ending_scores'] = sorted_map


# Timer incase players take too long to tier
def tier_timer(code, wait_time):
    # Wait the given time
    socketio.sleep(wait_time)
    # Check if the game still has not progressed
    if settings[code]['state'] == 'tiering':
        # Check if game state is valid
        if len(settings[code]['locked_players']) > 0:
            # Set the new game state
            settings[code]['state'] = 'scoring'
            
            # Resolve broken master
            if settings[code]['configs']['masters_enabled']:
                if rooms[code][settings[code]['current_master']]['picks'] is None:
                    settings[code]['current_master'] = random.choice(settings[code]['locked_players'])
            
            # Map scores
            starting_scores = {}
            for player in rooms[code]:
                starting_scores[player] = rooms[code][player]['score']
            settings[code]['starting_scores'] = starting_scores
            
            # Calculate scores if no one is left
            calculate_scores(code)
            
            # Get game host
            host = None
            breakdowns = {}
            for player in rooms[code]:
                if rooms[code][player]['host']:
                    host = player
                breakdowns[player] = rooms[code][player]['pick_breakdown']
                
            # Set the new game state
            settings[code]['state'] = 'scoring'
            
            # Determine if the game is over
            game_over = settings[code]['round'] >= settings[code]['configs']['rounds'] * len(rooms[code])
            
            # Progress the game
            packet = {
                'route': 'score',
                'data': {
                    'host': host,
                    'starting_scores': starting_scores,
                    'picks': breakdowns,
                    'master': settings[code]['current_master'],
                    'master_picks': settings[code]['master_picks'],
                    'leaderboard': settings[code]['ending_scores'],
                    'game_over': game_over
                }
            }
            ping(code, None, packet)
            
            # Clean up if game is over
            if game_over:
                clean_up(code)
        else:
            # Void the round and start the next one if no one did anything
            settings[code]['round'] -= 1
            
            # Reset relevant player data
            for player in rooms[code]:
                rooms[code][player]['master'] = False
                rooms[code][player]['picks'] = None
                rooms[code][player]['pick_breakdown'] = None
            
            # Reset relevant server data
            settings[code]['current_master'] = None
            settings[code]['active_cat'] = None
            settings[code]['current_cats'] = None
            settings[code]['locked_players'] = []
            settings[code]['master_picks'] = None
            settings[code]['starting_scores'] = None
            settings[code]['ending_scores'] = None
            
            # Change game state
            settings[code]['state'] = 'starting'
            
            # Move on
            emit('restart', {}, to=code)


@socketio.on('tier_complete')
def tier_complete_handler(data):
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            if settings[code]['state'] == 'tiering':
                # Check if list is valid
                repeats = []
                for letter in data:
                    for element in data[letter]:
                        if element in settings[code]['active_cat']['elements'] and element not in repeats:
                            repeats.append(element)
                if len(repeats) != len(settings[code]['active_cat']['elements']):
                    # Return an error if the list is wrong
                    emit('bad_tier', {}, to=request.sid)
                    return
                
                # Lock user in
                rooms[code][name]['picks'] = data
                settings[code]['locked_players'].append(name)
                
                # Check if players are still remaining
                if len(settings[code]['locked_players']) < len(rooms[code]):
                    packet = {
                        'route': 'waiting_room',
                        'data': {
                            'timer_start': settings[code]['timer_start'],
                            'timer_end': settings[code]['timer_end'],
                            'server_time': time.time()
                        }
                    }
                    ping(code, name, packet)
                else:
                    # Map scores
                    starting_scores = {}
                    for player in rooms[code]:
                        starting_scores[player] = rooms[code][player]['score']
                    settings[code]['starting_scores'] = starting_scores
                    
                    # Calculate scores if no one is left
                    calculate_scores(code)
                    
                    # Get game host
                    host = None
                    breakdowns = {}
                    for player in rooms[code]:
                        if rooms[code][player]['host']:
                            host = player
                        breakdowns[player] = rooms[code][player]['pick_breakdown']
                        
                    # Set the new game state
                    settings[code]['state'] = 'scoring'
                    
                    # Determine if the game is over
                    game_over = settings[code]['round'] >= settings[code]['configs']['rounds'] * len(rooms[code])
                    
                    # Progress the game
                    packet = {
                        'route': 'score',
                        'data': {
                            'host': host,
                            'starting_scores': starting_scores,
                            'picks': breakdowns,
                            'master': settings[code]['current_master'],
                            'master_picks': settings[code]['master_picks'],
                            'leaderboard': settings[code]['ending_scores'],
                            'game_over': game_over
                        }
                    }
                    ping(code, None, packet)
                        
                    # Clean up if game is over
                    if game_over:
                        clean_up(code)


@socketio.on('restart')
def restart_handler():
    # Get user data
    name = session.get('name')
    code = session.get('room')
    
    # Check if data is valid
    if (name and code) and (code in rooms):
        if name in rooms[code]:
            if settings[code]['state'] == 'scoring' and rooms[code][name]['host']:
                # Reset relevant player data
                for player in rooms[code]:
                    rooms[code][player]['master'] = False
                    rooms[code][player]['picks'] = None
                    rooms[code][player]['pick_breakdown'] = None
                
                # Reset relevant server data
                settings[code]['current_master'] = None
                settings[code]['active_cat'] = None
                settings[code]['current_cats'] = None
                settings[code]['locked_players'] = []
                settings[code]['master_picks'] = None
                settings[code]['starting_scores'] = None
                settings[code]['ending_scores'] = None
                
                # Change game state
                settings[code]['state'] = 'starting'
                
                # Move on
                emit('restart', {}, to=code)


# Run the app
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0')
