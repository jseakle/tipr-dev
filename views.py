import json
import logging
from datetime import datetime, timedelta, timezone
from termcolor import colored as c

from django.core.cache import cache
from django.db import transaction

from tipr.utils import *
from django.http.response import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views import View

from tipr.models import Game
from tipr.rps import RPSRules
from tipr.liar import LiarRules

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
                pass
                #return JsonResponse({'error': 'waiting for all players to be ready'})
            gamestate = Box(game.gamestate)

            rules = rules_classes[game.type]
            seat = get_seat(game, name)

            if seat == -1 or game.status != ACTIVE:
                resp = rules.render_gameboard(request, seat, game, gamestate, now)
                logging.warning(resp)
                return JsonResponse(resp)

            # account for start of game conditions
            if game.next_tick is None:
                game.next_tick = rules.next_tick(game)
                game.save()
            if game.last_tick is None:
                game.last_tick = now
                game.save()

            ticked = False
            if rules.should_update(game, gamestate, now):
                logging.warning(2)
                ticked = True
                keyframe_name = rules.keyframe_name
                prev = gamestate.meta[keyframe_name]
                try:
                    delta = rules.do_update(game)
                    logging.warn(c(f'TICK: {delta}', "red"))
                    update(gamestate, delta)
                    logging.warn(f'TICK COMPLETE: {gamestate}')

                    for message in gamestate.meta.message:
                        game.chat('system', message, now)
                    gamestate.meta.message = []
                    game.gamestate = dict(gamestate)

                    if gamestate.meta[keyframe_name] != prev:
                        if winner := rules.winner(gamestate):
                            game.chat('system', winner, now)
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
                    return JsonResponse(rules.render_gameboard(request, seat, game, gamestate, now))

            gameboard = rules.render_gameboard(request, seat, game, gamestate, now)
            if ticked:
                game.last_tick = now
                game.next_tick = rules.next_tick(game)
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
        logging.warn(c(f'MOVE: {seat} {request.POST.get("move")}', "red"))
        move = json.loads(request.POST.get('move'))
        delta = rules.move(game, seat, move)
        logging.warning(f"DELTA {delta} from {move}")
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
        return render(request, f'{game.type}.html',
                      {'game': game, 'gametype': game.type, 'seat': get_seat(game, request.session.get('name')), **rules_classes[game.type].gameboard_data(game)})

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

class Changes(View):
    def get(self, request):
        response = render(request, 'changes.txt')
        response['Content-Disposition'] = "Content-Type: text/plain;"
        return response

