import json
import logging
from datetime import datetime, timedelta, timezone

from django.core.cache import cache
from django.db import transaction

from tipr.utils import *
from django.http.response import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views import View

from tipr.models import Game
from tipr.rps import RPSRules

rules_classes = {
    'rps': RPSRules(),
}
reserved_names = ['']


def pause_others(game):
    if game.status == FINISHED:
        return
    if not all(game.people[1]):
        return
    game.status = ACTIVE
    game.save()
    for g in (Game.objects.filter(status=ACTIVE) | \
             Game.objects.filter(people__0__contains=game.people[0][0]) | \
             Game.objects.filter(people__0__contains=game.people[0][1])).exclude(id=game.pk):
        g.status = PAUSED
        g.save()

class Register(View):
    def post(self, request):
        name = request.POST.get('name')
        if not name or name in reserved_names:
            return JsonResponse({'error': 'please choose a different name'})
        request.session['name'] = name

        next = request.session.get('redirected_from')
        if next:
            return redirect(next)
        return HttpResponse()

class Sit(View):
    def post(self, request):
        name = request.session.get('name')
        if not name:
            return {'error': 'please register a name first'}
        seat = int(request.POST.get('seat'))
        gameid = request.POST.get('game')
        if not gameid:
            game_type = request.POST.get('type')
            rules = rules_classes[game_type]
            options = update(rules.DEFAULT_OPTIONS.copy(), request.POST.get('options'))
            options['deck'] = RPSRules.deck()
            starting_seats = [['']*options['player_count'], [False]*options['player_count']]
            starting_seats[0][seat] = name
            starting_seats[1][seat] = True
            game = Game(type=game_type, people=starting_seats, options=options, gamestate=rules.start_state(options))
            game.keyframe()
        else:
            game = Game.objects.get(pk=gameid)
            if game.people[0][seat]:
                return JsonResponse({'error': 'seat already taken'}, status=500)
            game.people[0][seat] = name
            game.people[1][seat] = True
            if all(game.people[1]):
                game.status = ACTIVE
                pause_others(game)
        game.save()
        request.session['gameid'] = game.pk
        return JsonResponse({'game': game.pk})  # unused, revisit

def get_seat(game, name):
    seat = -1
    if name and name in game.people[0][:2]:
        seat = game.people[0].index(name)  # 0 is p1
    return seat

class Load(View):
    def get(self, request):
        name = request.session.get('name')
        game = Game.objects.filter(people__0__contains=name, status=ACTIVE)
        pause_others(game)
        if not game:
            return render(request, 'homepage.html')
        seat = get_seat(game, name)
        return render(request, f'{game.type}.html',
                      game.response(rules_classes[game.type].response(game, seat, full=True),
                                    tznow(), full=True))

class Update(View):
    def post(self, request):
        with transaction.atomic():
            now = tznow()
            name = request.session.get('name')
            id = request.session.get('gameid')

            if id:
                game = Game.objects.filter(pk=id)
            else:
                game = None
            if not game:
                return JsonResponse({'error': 'This game does not exist'})
            game = game.get()
            if game.status == CREATED:
                return JsonResponse({'error': 'waiting for all players to be ready'})
            gamestate = Box(game.gamestate)
            stage = gamestate.meta.stage

            rules = rules_classes[game.type]
            seat = get_seat(game, name)

            def render_gameboard():
                response = Box()
                gameboard_context = game.response(rules.response(game, seat), now)
                gamestate = Box(gameboard_context.gamestate)
                stage = gamestate.meta.stage
                gameboard_context.seat = ('p1', 'p2', 'spectating')[seat]
                cards = []
                highest_slot = stage * 3 if stage < 4 else -1
                for card_dict in gamestate.p1.cards[:-2]:
                    card = Box(card_dict)
                    other = Box(gamestate.p2.cards[card.slot])
                    card.name = f"{card.level}{'X' if card.cracked else ''} {card.name} {other.level}{'X' if other.cracked else ''}"
                    if stage < 4 and game.options['timed']:
                        card.color = GREEN if card.slot < highest_slot else '#FFF'
                    else:
                        selections = rules.get_selections(gamestate)
                        p1_slot = selections[0].card.slot if selections[0] else None
                        p2_slot = selections[1].card.slot if selections[1] else None
                        if card.slot == p1_slot == p2_slot:
                            card.color = YELLOW
                        elif card.slot == p1_slot:
                            card.color = BLUE
                        elif card.slot == p2_slot:
                            card.color = RED
                        else:
                            card.color = WHITE
                    cards.append(card)

                pass_color = ('pass' in gamestate.p1.stages) + ('pass' in gamestate.p2.stages) * 2
                gameboard_context.pass_color = [WHITE, BLUE, RED, YELLOW][pass_color]
                gameboard_context.cards = cards
                gameboard_context.p1_badges = [f"{badge[0]}({badge[1]})" for badge in gamestate.p1.badges]
                gameboard_context.p2_badges = [f"{badge[0]}({badge[1]})" for badge in gamestate.p2.badges]
                gameboard_context.selections = [] if stage < 4 else [gamestate.p1.selection.slot, gamestate.p2.selection.slot]
                gameboard_context.timed = game.options['timed']
                response.gameboard = render(request, 'gameboard.html', gameboard_context).content.decode()
                response.timer = render(request, 'timer.html', gameboard_context).content.decode()
                response.chat = render(request, 'chat.html', {'chat_log': game.chat_log}).content.decode()
                load = request.POST.get('load') == 'true'
                if not load and response.gameboard == cache.get(f'{name}_gameboard'):
                    response.gameboard = 'U'
                else:
                    cache.set(f'{name}_gameboard', response.gameboard)
                if not load and response.chat == cache.get(f'{name}_chat'):
                    response.chat = 'U'
                else:
                    cache.set(f'{name}_chat', response.chat)
                return response

            if seat == -1 or game.status != ACTIVE:
                return JsonResponse(render_gameboard())

            # account for start of game conditions
            if game.next_tick is None:
                game.next_tick = rules.next_tick(game)
                game.save()
            if game.last_tick is None:
                game.last_tick = now
                game.save()

            ticked = False
            if ((game.options['timed'] or stage == 4) and game.last_tick and now - game.last_tick > timedelta(seconds=game.next_tick)) or \
                    (stage < 4 and any(gamestate.p1.stages.values()) and any(gamestate.p2.stages.values())):
                ticked = True
                keyframe_name = rules.keyframe_name
                prev = gamestate.meta[keyframe_name]
                try:
                    delta = rules.do_update(game)
                    logging.warn(f"{delta}")
                    update(gamestate, delta)
                    messages = len(gamestate.meta.message)
                    for message in gamestate.meta.message:
                        game.chat('system', message, now)
                    gamestate.meta.message = []
                    game.gamestate = dict(gamestate)
                    if stage == 4 and not messages:
                        game.next_tick = 0
                    else:
                        game.next_tick = rules.next_tick(game)

                    if gamestate.meta[keyframe_name] != prev:
                        if winner := rules.winner(game):
                            if winner == 'tie':
                                msg = "Tie game!"
                            else:
                                msg = f"{winner} wins!"
                            game.chat('system', msg, now)
                            game.status = FINISHED
                        game.keyframe()
                    else:
                        game.event('time', delta, now)
                except Exception as e:
                    logging.exception(f'rewinding')
                    s()
                    message = f'error doing timed update: {e}\nresetting to {keyframe_name} {prev}'
                    game.chat('system', message, now)
                    game.rewind(1, message)
                    return JsonResponse(render_gameboard())

            gameboard = render_gameboard()
            if ticked:
                game.last_tick = now
                game.save()
                game.refresh_from_db()
            return JsonResponse(gameboard)

class Submit(View):
    def post(self, request):
        now = tznow()
        name = request.session.get('name')
        try:
            game = Game.objects.filter(people__0__contains=name, status=ACTIVE).get()
        except:
            return JsonResponse({'error': 'no active game'}, status=500)
        rules = rules_classes[game.type]
        seat = get_seat(game, name)
        # {"type": "selection", "selection": <slot>}
        move = json.loads(request.POST.get('move'))
        delta = rules.move(game, seat, move)
        if 'error' in delta:
            logging.warn(delta)
            return JsonResponse(delta, status=500)
        game.event('move', move, now)
        update(game.gamestate, delta)
        game.save()
        return JsonResponse(game.response(rules.response(game, seat), now))


class Home(View):
    def get(self, request):
        return render(request, 'home.html')

class GamePage(View):
    def get(self, request, id):
        game = Game.objects.get(pk=id)
        pause_others(game)
        request.session['gameid'] = game.pk
        return render(request, 'game.html', {'game': game})

class GameList(View):
    def post(self, request):
        name = request.session.get('name')
        response = Box()
        response.name = name
        gamelist_context = Box()
        gamelist_context.my_games = []
        gamelist_context.other_games = []
        for game in Game.objects.filter(status__lt=FINISHED):
            if name and name in game.people[0]:
                gamelist_context.my_games.append(game)

            else:
                gamelist_context.other_games.append(game)

        response.gamelist = render(request, 'gamelist.html', gamelist_context).content.decode()
        if not request.POST.get('load') and response.gamelist == cache.get(f'{name}_gamelist'):
            response.gamelist = 'U'
        else:
            cache.set(f'{name}_gamelist', response.gamelist)

        return JsonResponse(response)