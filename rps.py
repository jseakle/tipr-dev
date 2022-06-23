import functools
import random
from tipr.utils import *
from rps_cards import *



class RPSRules(object):

    DEFAULT_OPTIONS = {
        'timer': 10,
        'player_count': 2,
        'deck': 'basic',  # card classes tagged with deck names
    }

    def player_state(self, options):
        STARTING_HP = 250
        MAX_HP = STARTING_HP / .75
        return {
            'max_hp': MAX_HP,
            'hp': STARTING_HP,
            'coins': 0,
            'selection': None,  # {name, ability_number, stage}. Used for tracking in stage 4.
            'badges': [],
            'badges_used': [],  # remembering during ability resolution
            'shields': 0,
            'restrictions': [],
            'stages': {1: [], 2: [], 3: []},
            'cards': {name: {'level': 1, 'cracked': False, 'type': card.type} for name, card in RPSRules.deck(options['deck'])}
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

    @functools.cache
    @staticmethod
    def deck(deck):
        card_classes = filter(lambda cls: deck in cls.decks, RPSCard.__subclasses__())
        return {card.name: card for card in card_classes}

    @functools.cache
    @staticmethod
    def deck_text(deck):
        return {name: {'type': card.type, 'stage': card.stage, 'text': card.text} for name, card in RPSRules.deck(deck)}

    def get_selections(self, gamestate, seats=seats):
        ret = []
        for seat in seats:
            found = False
            for stage in (1, 2, 3):
                for action in gamestate[seat].stages[stage]:
                    if action.kind == 'RPS':
                        found = True
                        ret.append(Box(seat=seat, stage=stage, name=action.name,
                                       card=gamestate[seat].cards[action.name]))  # modifiers go in here too
                        break
                if found:
                    break
            if not found:
                ret.append(None)
        return ret

    def outcome_message(self, player, outcome):
        return f'{player} {outcome}'

    def response(self, game, seat, full=False):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat, full)

    def pure_response(self, options, gamestate, history, seat, full):
        if full:
            gamestate.meta.deck = RPSRules.deck_text(options.deck)

        initial = gamestate.meta.round == 1 and gamestate.meta.stage == 1
        if gamestate.meta.stage < 4 and seat != -1 and not initial:
            # this player's current view + other player's view at last keyframe
            player = seats[seat]
            other = opp(player)
            for name, card in gamestate[other].cards:
                if 'revealed' not in card:
                    gamestate[other].cards[name] = history[-1][0][other].cards[name]

        return gamestate

    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def pure_update(self, options, gamestate, history):
        match gamestate.meta.stage:
            case 1 | 2:
                return {'meta': {'stage': gamestate.meta.stage + 1, 'message': ''}}
            case 3:
                # Box(seat, stage, card)
                p1_selection, p2_selection = self.get_selections(gamestate)
                happens_first = happens_second = Box(owner=None, rps=None, level=0, timing=None)

                match p1_selection, p2_selection:
                    case None, None:
                        happens_first.update(owner='p1', rps='Truce')
                        happens_second.update(owner='p2', rps='Truce')
                        outcome = 'truce'
                    case ({**w}, None) | (None, {**w}):
                        happens_first.update(owner='p2' if w.seat == 'p1' else 'p1', rps='PaciveIncome')
                        happens_second.update(owner=w.seat, rps=w.name,
                                              level=gamestate[w.seat].cards[w.name].level)
                        outcome = 'default'
                    case Box() as p1, Box() as p2 if p1_selection.card.type == p2_selection.card.type:
                        match p1_selection.stage, p2_selection.stage:
                            case x, y if x == y:
                                order = [p1, p2]
                                if gamestate.p1.hp == gamestate.p2.hp and gamestate.p1.coins == gamestate.p2.coins:
                                    random.shuffle(order)
                                elif gamestate.p1.hp == gamestate.p2.hp:
                                    order.sort(key=lambda box: gamestate[box.seat].coins, reverse=True)
                                else:
                                    order.sort(key=lambda box: gamestate[box.seat].hp, reverse=True)
                                happens_first.update(owner=order[0].seat, rps=order[0].name,
                                                     level=gamestate[order[0].seat].cards[order[0].name].level)
                                happens_second.update(owner=order[1].seat, rps=order[1].name,
                                                      level=gamestate[order[1].seat].cards[order[1].name].level)
                                outcome = 'tie'
                            case x, y:
                                winner, loser = (p1, p2) if x < y else (p2, p1)
                                happens_first.update(owner=winner.seat, rps=winner.name,
                                                     level=gamestate[winner.seat].cards[winner.name].level / 2,
                                                     timing=1 if abs(x-y) == 2 else None)
                                outcome = 'ambush'
                    case Box() as p1, Box() as p2:
                        winner, loser = (p1, p2) if (p2.card.type + 1) % 3 == p1.card.type else (p2, p1)

                        happens_first.update(owner=winner.seat, rps=winner.name,
                                             level=gamestate[winner.seat].cards[winner.name].level,
                                             timing=max(0, winner.stage - loser.stage))
                        outcome = 'win'

                msg = self.outcome_message(happens_first.owner, outcome)
                delta = {'meta': {'stage': 4, 'message': msg, 'outcome': {'player': happens_first.owner, 'type': outcome}},
                        happens_first.owner: {'selection':
                              {'name': happens_first.rps,
                               'timing': happens_first.timing,
                               'ability': len(RPSRules.deck(options.deck).get(happens_first.rps).ability_order) + 2}}}
                if happens_second.owner:
                    delta[happens_second.owner].selection = \
                        {'name': happens_second.rps,
                         'ability':  len(RPSRules.deck(options.deck).get(happens_second.rps).ability_order) + 2}
                else:  # it won't happen, but we might need the name
                    delta[opp(happens_first.owner)].selection = {'name': p2_selection.name, 'ability': 0}

                return delta

            case 4:
                delta = empty_delta
                outcome = gamestate.meta.outcome
                active_player = outcome.player
                inactive_player = opp(active_player)
                if (selection := gamestate.get(active_player).selection).ability:
                    resolving_player = active_player
                else:
                   if not (selection := gamestate.get(inactive_player).selection).ability:  # done
                       round = gamestate.meta.round
                       delta.meta = {'round': round + 1, 'stage': 1}
                       for seat in seats:
                           # in the future maybe wear-off messages for effects whose initial duration was > 1 turn
                           # can use history for this
                           delta.ga(seat).restrictions = [update(restriction, {'duration': restriction.duration - 1})
                                      for restriction in gamestate.get(seat).restrictions if restriction.duration != 1]

                       delta.meta.message += f'round {round} ends'
                       return delta
                   else:
                       resolving_player = inactive_player

                # card updates its own stage so it can skip stuff, etc
                card = self.deck(options.deck)[selection]
                return update(delta, card.apply(gamestate, history, resolving_player))

    def move(self, game, move, seat):
        if not game.status == 'ACTIVE':
            return {'error': f'game is {game.status}'}
        return self.pure_move(Box(game.options), Box(game.gamestate), game.history, seat, Box(move))

    def pure_move(self, options, gamestate, history, seat, move):
        for restriction in gamestate.get(seat).restrictions:
            if restriction.applies(gamestate, seat, move):
                return {'error': restriction.source}

        delta = empty_delta
        match move.type:
            case 'selection':
                delta.ga(seat).selection = move.selection
            case 'coin':
                pass

        return delta

    def next_tick(self, game):
        if game.gamestate.meta.stage <= 3:
            return game.options['timer']
        else:
            return 2



