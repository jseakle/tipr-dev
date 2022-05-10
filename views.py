import json
from datetime import datetime, timedelta
from utils import *
from django.http.response import JsonResponse
from django.shortcuts import render
from django.views import View

from tipr.models import Game
from tipr.rps import RPSRules

rules_classes = {
    'rps': RPSRules(),
}

class Register(View):
    def post(self, request):
        request.session['name'] = request.POST.get('name')

class Sit(View):
    def post(self, request):
        name = request.session.get('name')
        seat = request.POST.get('seat')
        gameid = request.POST.get('game')
        if not gameid:
            rules = rules_classes[request.POST.get('type')]
            options = rules.STATIC_OPTIONS.copy().update(request.POST.get('options'))
            starting_seats = [['']*options['player_count'], [False]*options['player_count']]
            starting_seats[0][seat] = name
            starting_seats[1][seat] = True
            game = Game(type=type, player_names=starting_seats, options=options, gamestate=rules.start_state(options))
        else:
            game = Game.objects.get(pk=gameid)
            if game.people[0][seat]:
                return JsonResponse({'error': 'seat already taken'})
            game.people[0][seat] = name
            game.people[1][seat] = True
        game.save()
        return JsonResponse({'game': gameid})

def get_seat(game, name):
    seat = game.people[0].index(name)  # 0 is p1
    if seat > game.options['player_count'] - 1:
        return -1
    return seat

class Load(View):
    def get(self, request):
        name = request.session.get('name')
        game = Game.objects.filter(people__contains=name, status=ACTIVE)
        if not game:
            return render(request, 'homepage.html')
        seat = get_seat(game, name)
        return render(request, f'{game.type}.html',
                      game.response(rules_classes[game.type].response(game, seat),
                                    datetime.now(), full=True))

class Update(View):
    def post(self, request):
        now = datetime.now()
        name = request.session.get('name')
        game = Game.objects.filter(people__contains=name, status=ACTIVE).get()
        rules = rules_classes[game.type]
        seat = get_seat(game, name)
        if seat is -1:
            return JsonResponse(game.response(rules.response(game, seat)))

        if game.next_tick is -1:
            game.next_tick = rules.next_tick(game.gamestate)
            game.save()

        if game.last_tick and now - game.last_tick > timedelta(seconds=game.next_tick):
            if all(game.people[1]):
                keyframe_name = rules.keyframe_name
                prev = game.gamestate.meta[keyframe_name]
                try:
                    game.gamestate = rules.do_update(game)
                    if game.gamestate['meta'][keyframe_name] != prev:
                        game.keyframe()
                except Exception as e:
                    message = f'error doing timed update: {e}\nresetting to {keyframe_name} {prev}'
                    game.rewind(1, message)
                    return JsonResponse(game.response(rules.response(game, seat), now))
            else:
                game.people[1][seat] = True
                game.save()
        return JsonResponse(game.response(rules.response(game, seat), now))

class Submit(View):
    def post(self, request):
        now = datetime.now()
        name = request.session.get('name')
        game = Game.objects.filter(people__contains=name, status=ACTIVE).get()
        rules = rules_classes[game.type]
        seat = get_seat(game, name)
        move = json.loads(request.POST.get('move'))
        game.event('move', move, now)
        result = rules.move(move, seat)
        game.event('delta', result, now)
        return JsonResponse(result)