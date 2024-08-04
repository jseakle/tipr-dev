from django.shortcuts import render
from tipr.utils import *
from django.core.cache import cache

class Rules(object):
    def winner(self, game):
        pass


    def render_gameboard(self, request, seat, game, gamestate, now):
        gameboard_context = self.gameboard_context(request, seat, game, gamestate, now)
        response = Box()
        response.gameboard = render(request, f'{game.type}_board.html', gameboard_context).content.decode()
        response.timer = render(request, 'timer.html', gameboard_context).content.decode()
        response.chat = render(request, 'chat.html', {'chat_log': game.chat_log}).content.decode()
        load = request.POST.get('load') == 'true'
        name = gameboard_context.name
        if not load and response.gameboard == cache.get(f'{name}_gameboard'):
            response.gameboard = 'U'
        else:
            cache.set(f'{name}_gameboard', response.gameboard)
        if not load and response.chat == cache.get(f'{name}_chat'):
            response.chat = 'U'
        else:
            cache.set(f'{name}_chat', response.chat)
        return response
