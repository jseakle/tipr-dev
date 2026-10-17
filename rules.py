from django.template.loader import render_to_string 
from tipr.utils import *
from django.core.cache import cache
import logging, json

class Rules(object):
    def winner(self, game):
        pass

    # seat-specific view of gamestate
    def response(self, game, seat):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat)

    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def change_callback_data(self, name, seat, game, gamestate, now):
        pass

    def gameboard_context(self, name, seat, game, gamestate, now):
        return Box({
            'options': game.options,                           
            'people': game.people[0],                          
            'name': name,                                      
            'seat': seat,
            'active': game.status == ACTIVE,
        })

    def render_gameboard(self, name, load, seat, game, gamestate, now):
        response = Box()
        gameboard_context = self.gameboard_context(name, seat, game, gamestate, now)
        response.change_callback_data = self.change_callback_data(name, seat, game, gamestate, now)
        response.gameboard = render_to_string(f'{game.type}_board.html', gameboard_context)
        if(game.options['timed']):
            response.timer = render_to_string('timer.html', gameboard_context)
        response.chat = render_to_string( 'chat.html', {'chat_log': game.chat_log})
        name = gameboard_context.name
        if not load and response.gameboard == cache.get(f'{name}_{game.pk}_gameboard'):
            response.gameboard = 'U'
        else:
            cache.set(f'{name}_{game.pk}_gameboard', response.gameboard)

        # modularize this idea later
        try:
            response.inputs = render_to_string(f'{game.type}_inputs.html', gameboard_context)
            
            if not load and response.inputs == cache.get(f'{name}_{game.pk}_inputs'):
                response.inputs = 'U'
            else:
                cache.set(f'{name}_{game.pk}_inputs', response.inputs)
        except Exception:
            pass
            logging.exception('failed input render')        
        rendered_callback = json.dumps(response.change_callback_data)
        if not load and rendered_callback == cache.get(f'{name}_{game.pk}_change_callback_data'):
            response.change_callback_data = 'U'
        else:
            cache.set(f'{name}_{game.pk}_change_callback_data', json.dumps(response.change_callback_data))
        if not load and response.chat == cache.get(f'{name}_{game.pk}_chat'):
            response.chat = 'U'
        else:
            cache.set(f'{name}_{game.pk}_chat', response.chat)
        return response
