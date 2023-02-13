import functools
import logging
from random import choice, shuffle
from tipr.utils import *
from tipr.rps_cards import *

class RPSRules(object):

    keyframe_name = 'round'

    DEFAULT_OPTIONS = {
        'timed': False,
        'timer': 7,
        'player_count': 2,
    }
    stage_dict = {'1': [], '2': [], '3': []}

    def player_state(self, options):
        STARTING_HP = 250
        MAX_HP = STARTING_HP / .75
        return {
            'max_hp': MAX_HP,
            'hp': STARTING_HP,
            'coins': 0,
            'selection': {},  # {slot, ability_number, stage, timing}. Used for tracking in stage 4.
            'badges': [],  # [[Name, Arg, Round], ..]
            'badges_used': [],  # remembering during ability resolution
            'shields': {'n': 0, 'this_turn': 0},
            'restrictions': [],  # [[Name, Arg, Source ("<ability> @ round #"), Duration], ..]
            'stages': RPSRules.stage_dict,
            'cards': [{'name': card.__name__, 'level': 1, 'cracked': False, 'type': card.type, 'slot': card.slot}
                      for card in map(lambda name: globals()[name], options['deck'])]
        }

    def start_state(self, options):
        starting_state = {
            'meta': {
                'round': 1,
                'stage': 1,
                'outcome': {'player': None, 'type': None},  # 'win', 'ambush', 'default', 'draw', 'truce'
                'message': ['Game Start']
            },
            'p1': self.player_state(options),
            'p2': self.player_state(options),
        }
        return starting_state

    @staticmethod
    def deck():
        card_classes = [[] for _ in range(11)]
        for cls in RPSCard.__subclasses__():
            if hasattr(cls, 'slot'):
                card_classes[cls.slot].append(cls)
        return [choice(card_classes[x]).__name__ for x in range(11)]

    @functools.cache
    @staticmethod
    def deck_text(game):
        return [Box({'name': card.__name__, 'slot': card.slot, 'text': card.text})
                for card in RPSCard.__subclasses__() if card.__name__ in game.options['deck']]

    def get_selections(self, gamestate, seats=seats):
        ret = []
        for seat in seats:
            found = False
            for stage in ('1', '2', '3'):
                for action in gamestate[seat].stages[stage]:
                    if action.kind == 'RPS':
                        found = True
                        ret.append(Box(seat=seat, stage=int(stage),
                                       card=gamestate[seat].cards[action.slot]))  # modifiers go in here too
                        break
                if found:
                    break
            if not found:
                ret.append(None)
        return ret

    def outcome_message(self, player, outcome):
        match outcome:
            case 'truce':
                return "Truce! Everyone loses 1 health."
            case 'default':
                return f'{opp(player)} wins by default'
            case _:
                return f'{player} {outcome}'

    def response(self, game, seat):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat)

    def pure_response(self, options, gamestate, history, seat):

        if gamestate.meta.stage < 4 and seat != -1:
            # this player's current view + other player's view at last keyframe
            player = seats[seat]
            other = opp(player)
            for card in gamestate[other].cards:
                if 'revealed' not in card:
                    gamestate[other].cards[card.slot] = history[-1][0]['info'][other]['cards'][card.slot]
            gamestate[other].selection = {}
            gamestate[other].stages = RPSRules.stage_dict
        return gamestate

    def should_update(self, game, gamestate, timestamp):
        return ((game.options['timed'] or gamestate.meta.stage == 4)
                and game.last_tick and game.has_ticked(timestamp) or \
               (gamestate.meta.stage < 4 and any(gamestate.p1.stages.values()) and any(gamestate.p2.stages.values()))
     
    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def pure_update(self, options, gamestate, history):
        delta = empty_delta()
        match gamestate.meta.stage:
            case 1 | 2 as st:
                delta.meta.stage = st + 1
                return delta
            case 3:
                # Box(seat, stage, card)
                p1_selection, p2_selection = self.get_selections(gamestate)
                happens_first = Box(owner=None, slot=None, level=0, timing=0)
                happens_second = Box(owner=None, slot=None, level=0, timing=0)
                match p1_selection, p2_selection:
                    case None, None:
                        happens_first.update(owner='p1', slot=TRUCE)
                        happens_second.update(owner='p2', slot=TRUCE)
                        outcome = 'truce'

                    case (Box() as w, None) | (None, Box() as w):
                        loser = 'p2' if w.seat == 'p1' else 'p1'
                        happens_first.update(owner=loser, slot=INCOME)
                        happens_second.update(owner=w.seat, slot=w.card.slot, level=w.card.level)
                        outcome = 'default'
                    case Box() as p1, Box() as p2 if p1_selection.card.type == p2_selection.card.type:
                        match p1_selection.stage, p2_selection.stage:
                            case x, y if x == y:
                                order = [p1, p2]
                                if gamestate.p1.hp == gamestate.p2.hp and gamestate.p1.coins == gamestate.p2.coins:
                                    shuffle(order)
                                elif gamestate.p1.hp == gamestate.p2.hp:
                                    order.sort(key=lambda box: gamestate[box.seat].coins, reverse=True)
                                else:
                                    order.sort(key=lambda box: gamestate[box.seat].hp, reverse=True)
                                happens_first.update(owner=order[0].seat, slot=order[0].card.slot, level=order[0].card.level)
                                happens_second.update(owner=order[1].seat, slot=order[1].card.slot, level=order[1].card.level)
                                outcome = 'tie'
                            case x, y:
                                winner, loser = (p1, p2) if x < y else (p2, p1)
                                happens_first.update(owner=winner.seat, slot=winner.card.slot,
                                                     level=winner.card.level / 2,
                                                     timing=1 if abs(x-y) == 2 else 0)
                                outcome = 'ambush'
                    case Box() as p1, Box() as p2:
                        winner, loser = (p1, p2) if (p2.card.type + 1) % 3 == p1.card.type else (p2, p1)
                        happens_first.update(owner=winner.seat, slot=winner.card.slot,
                                             level=winner.card.level,
                                             timing=max(0, loser.stage - winner.stage))
                        outcome = 'win'

                msg = self.outcome_message(happens_first.owner, outcome)
                update(delta, {'meta': {'stage': 4, 'outcome': {'player': happens_first.owner, 'type': outcome}},
                         happens_first.owner: {'selection':
                               {'slot': happens_first.slot,
                                'timing': happens_first.timing,
                                # 'stage': when it was chosen
                                'ability_number': len(globals()[options.deck[happens_first.slot]].ability_order) + 3}}})
                add_message(delta, msg)
                if happens_second.owner:
                    update(delta, {happens_second.owner: {'selection':
                        {'slot': happens_second.slot,
                         'timing': 0,
                         'ability_number': len(globals()[options.deck[happens_second.slot]].ability_order) + 3}}})
                else:  # the card won't happen, but we might need the name
                    delta.ga(opp(happens_first.owner)).selection = {'slot': loser.card.slot, 'ability_number': 0}
                for seat in seats:
                    # in the future maybe wear-off messages for effects whose initial duration was > 1 turn
                    # can use history for this
                    delta.ga(seat).restrictions = [update(restriction, {'duration': restriction.duration - 1})
                                                   for restriction in gamestate.get(seat).restrictions if
                                                   restriction.duration != 1]
                return delta

            case 4:
                outcome = gamestate.meta.outcome
                active_player = outcome.player
                inactive_player = opp(active_player)
                if (selection := gamestate.get(active_player).selection).ability_number:
                    resolving_player = active_player
                else:
                    if not (selection := gamestate.get(inactive_player).selection).ability_number:  # done
                        round = gamestate.meta.round
                        delta.meta = {'round': round + 1, 'outcome': 'del'}
                        if options.timed:
                            delta.meta.stage = 1
                        else:
                            delta.meta.stage = 3
                        for seat in seats:
                            delta.ga(seat).stages = {'replace': RPSRules.stage_dict}
                            delta.get(seat).selection = {'replace': {}}
                            delta.get(seat).ga('shields').this_turn = 0

                        add_message(delta, f'round {round} ends')
                        logging.warn(f"ONE: {delta}")
                        return delta
                    else:
                        resolving_player = inactive_player

                # card updates its own stage so it can skip stuff, etc
                card = globals()[gamestate.get(resolving_player).cards[selection.slot].name]
                result = card.apply(gamestate, history, resolving_player)
                logging.warn(f"{delta}\n--\n{result}")
                return update(delta, result)

    def winner(self, game):
        game = Box(game.gamestate)
        p1_dead = game.p1.hp <= 0
        p2_dead = game.p2.hp <= 0
        if p2_dead and p1_dead:
            if game.p1.hp == game.p2.hp:
                return 'tie'
            return seats[game.p2.hp > game.p1.hp]
        elif p1_dead:
            return 'p2'
        elif p2_dead:
            return 'p1'
        else:
            return None

    def get_restrictions(self, gamestate, seat):
        return [next(filter(lambda c: c.__name__ == rest['name'],
                            Restriction.__subclasses__()))(rest['arg'], rest['source'], rest['duration'])
                for rest in gamestate.get(seat).get('restrictions')]

    def move(self, game, seat, move):
        if not game.status == ACTIVE:
            return {'error': f'game is {game.status}'}
        gamestate = Box(game.gamestate)
        move = Box(move)
        seat = f"p{seat+1}"
        if gamestate.meta.stage > 3:
            return {'error': 'between rounds'}
        for restriction in self.get_restrictions(gamestate, seat):
            if restriction.applies(gamestate, seat, move):
                return {'error': f'Move rejected due to {restriction.source}'}
        if game.options['timed']:
            return self.pure_move(Box(game.options), gamestate, game.history, seat, move)
        return self.pure_untimed_move(Box(game.options), gamestate, game.history, seat, move)

    def pure_move(self, options, gamestate, history, seat, move):
        for stage in range(1,4):
            if selections := gamestate.get(seat).stages.get(str(stage)):
                if any(filter(lambda x: x['kind'] == 'RPS', selections)):
                    return {'error': 'already submitted'}

        delta = empty_delta()
        match move.type:
            case 'selection':
                if move.selection // 3 > gamestate.meta.stage - 1:
                    return {'error': 'that move is not available yet'}
                delta.ga(seat).ga('stages')[str(gamestate.meta.stage)] = {'ins': [{'kind': 'RPS', 'slot': move.selection}]}
            case 'coin':
                pass

        return delta

    def pure_untimed_move(self, options, gamestate, history, seat, move):
        delta = empty_delta()
        if move.selection == -1:
            return update(delta, {seat: {'stages': {'pass': 1}}})
        stage = move.selection // 3 + 1
        delta.ga(seat).stages = {n: [{'kind': 'RPS', 'slot': move.selection}] if n == stage else [] for n in range(1,4)}
        return delta

    def next_tick(self, game):
        if game.gamestate['meta']['stage'] <= 3:
            return game.options['timer']
        else:
            return 2



