import json
import logging
from copy import deepcopy

from django.core.cache import cache
from django.db import transaction

from .utils import ACTIVE, FINISHED, PAUSED, Box, gen_patch, tznow, update
from django.http.response import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.views import View

from .models import Game
from .rps import RPSRules
from .liar import LiarRules

rules_classes = {
    'rps': RPSRules(),
    'liar': LiarRules(),
}
reserved_names = ['']


def pause_others(game):
    if game.status == FINISHED:
        return
    if not all(game.people[1]):
        return
    if game.status != ACTIVE:
        game.last_tick = tznow()
        game.next_tick = rules_classes[game.type].next_tick(game)
        game.status = ACTIVE
        game.save(update_fields=['status', 'last_tick', 'next_tick'])
    Game.objects.filter(status=ACTIVE).exclude(pk=game.pk).update(status=PAUSED)

class Register(View):
    def post(self, request):
        name = request.POST.get('name')
        if not name or name in reserved_names:
            return JsonResponse({'error': 'please choose a different name'})
        cache.set(request.session.session_key, name)
        request.session['name'] = name

        next = request.session.get('redirected_from')
        if next:
            return redirect(next)
        return HttpResponse()

class Sit(View):
    @transaction.atomic
    def post(self, request):
        name = request.session.get('name')
        if not name:
            return JsonResponse({'error': 'please register a name first'})
        try:
            seat = int(request.POST.get('seat'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Choose a valid seat'})
        if seat not in (0, 1):
            return JsonResponse({'error': 'Choose a valid seat'})
        gameid = request.POST.get('game')
        if not gameid:
            game_type = request.POST.get('type')
            if game_type not in rules_classes:
                return JsonResponse({'error': 'Unknown game type'})
            rules = rules_classes[game_type]
            try:
                supplied = json.loads(request.POST.get('options') or '{}')
                if not isinstance(supplied, dict):
                    raise ValueError('Options must be an object')
                options = (rules.prepare_options(supplied) if game_type == 'rps'
                           else {**deepcopy(rules.DEFAULT_OPTIONS), **supplied})
            except (TypeError, ValueError) as error:
                return JsonResponse({'error': f'Invalid game options: {error}'})
            starting_seats = [['']*options['player_count'], [False]*options['player_count']]
            starting_seats[0][seat] = name
            starting_seats[1][seat] = True
            game = Game(type=game_type, people=starting_seats, options=options, gamestate=rules.start_state(options))
            game.keyframe()
        else:
            try:
                game = Game.objects.select_for_update().filter(pk=int(gameid)).first()
            except (TypeError, ValueError):
                return JsonResponse({'error': 'This game does not exist'})
            if game is None:
                return JsonResponse({'error': 'This game does not exist'})
            if game.people[0][seat]:
                return JsonResponse({'error': 'seat already taken'})
            game.people[0][seat] = name
            game.people[1][seat] = True
            if all(game.people[1]):
                pause_others(game)
        game.save()
        request.session['gameid'] = game.pk
        return JsonResponse({'game': game.pk})  # unused, revisit

def get_seat(game, name):
    seat = -1
    if name and name in game.people[0][:2]:
        seat = game.people[0].index(name)  # 0 is p1
    return seat


def apply_game_delta(game, rules, delta, now, event_type):
    before = Box(deepcopy(game.gamestate))
    state = Box(deepcopy(before))
    update(state, delta)
    messages = list(state.meta.message)
    game.gamestate = state.to_dict()
    if event_type == 'time':
        game.last_tick = now
        game.next_tick = rules.next_tick(game)
    state.meta.message = []
    if winner := rules.winner(state):
        game.status = FINISHED
        game.next_tick = 0
        if winner not in messages:
            messages.append(winner)
    game.gamestate = state.to_dict()
    for message in messages:
        game.chat('system', message, now)
    if state.meta[rules.keyframe_name] != before.meta[rules.keyframe_name]:
        game.keyframe()
    else:
        game.event(event_type, gen_patch(before, state), now)
    return state


class Update(object):

    @staticmethod
    def do(name, id, load):

        with transaction.atomic():
            now = tznow()

            try:
                game = Game.objects.select_for_update().filter(pk=int(id)).first()
            except (TypeError, ValueError):
                return {'error': 'This game does not exist'}
            if game is None:
                return {'error': 'This game does not exist'}
            gamestate = Box(game.gamestate)

            rules = rules_classes[game.type]
            seat = get_seat(game, name)

            if seat == -1 or game.status != ACTIVE:
                resp = rules.render_gameboard(name, load, seat, game, gamestate, now)
                return resp

            # account for start of game conditions
            if game.next_tick is None:
                game.next_tick = rules.next_tick(game)
                game.save()
            if game.last_tick is None:
                game.last_tick = now
                game.save()

            if rules.winner(gamestate):
                gamestate = apply_game_delta(game, rules, {}, now, 'time')
            elif rules.should_update(game, gamestate, now):
                gamestate = apply_game_delta(game, rules, rules.do_update(game), now, 'time')
            return rules.render_gameboard(name, load, seat, game, gamestate, now)

class Submit(View):
    @transaction.atomic
    def post(self, request):
        now = tznow()
        name = request.session.get('name')
        try:
            gameid = int(request.POST.get('game'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'This game does not exist'})
        game = Game.objects.select_for_update().filter(pk=gameid).first()
        if game is None:
            return JsonResponse({'error': 'This game does not exist'})
        try:
            move = json.loads(request.POST.get('move'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Move must be valid JSON'})

        if isinstance(move, str) and move.startswith('chat: '):

            move = move[6:]
            if move == 'rewind':
                if sum('rewound' not in interval[0] for interval in game.history) < 2:
                    return JsonResponse({'error': 'There is no previous round to rewind to'})
                msg = f'{name} clicked rewind'
                game.rewind(1, msg)
                return JsonResponse({})
            game.chat(name, move)
            return JsonResponse({})
                

        rules = rules_classes[game.type]
        seat = get_seat(game, name)
        if seat == -1:
            return JsonResponse({'error': f'{name} tried to move but is not a player'})
        delta = rules.move(game, seat, move)
        if 'error' in delta:
            logging.warning('Move rejected: %s', delta['error'])
            return JsonResponse(delta)
        apply_game_delta(game, rules, delta, now, 'move')
        return JsonResponse(game.response(rules.response(game, seat), now))


class Home(View):
    def get(self, request):
        return render(request, 'home.html')


class GamePage(View):
    def get(self, request, id):
        game = Game.objects.get(pk=id)
        pause_others(game)
        request.session['gameid'] = game.pk
        return render(request, f'{game.type}.html',
                      {'game': game, 'gametype': game.type, 'seat': get_seat(game, request.session.get('name')), **rules_classes[game.type].gameboard_data(game)})

class GameList(object):

    @staticmethod
    def do(name, load):
        response = Box()
        response.name = name
        gamelist_context = Box()
        gamelist_context.name = name
        gamelist_context.my_games = []
        gamelist_context.other_games = []
        for game in Game.objects.filter(status__lt=FINISHED):
            if name and name in game.people[0]:
                gamelist_context.my_games.append(game)

            else:
                gamelist_context.other_games.append(game)
        response.gamelist = render_to_string('gamelist.html', gamelist_context)
        if not load and response.gamelist == cache.get(f'{name}_gamelist'):
            response.gamelist = 'U'
        else:
            cache.set(f'{name}_gamelist', response.gamelist)

        return response

 
class Worker(View):
    def get(self, request):
        logging.warning('huh?')
        resp = HttpResponse(render_to_string('update_worker.js'), content_type='application/javascript', headers={'Cache-Control': 'no-store'})
        return resp
