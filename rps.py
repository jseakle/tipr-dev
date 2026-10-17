from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from numbers import Real
from random import choice, randint, shuffle

from .rps_cards import (
    CARD_CLASSES, COIN_ABILITIES, DECKS, active_restrictions,
    add_restriction, describe_badge, describe_restriction, heal, health_percent, hurt, level_up,
)
from .rules import Rules
from .utils import (
    ACTIVE, BLUE, Box, FINISHED, GREEN, INCOME, PAPER, RED,
    ROCK, SCISSORS, TRUCE, TYPES, WHITE, YELLOW,
    gen_patch, opp, seats, update,
)


class RPSRules(Rules):
    keyframe_name = 'round'
    DEFAULT_OPTIONS = {
        'timed': True,
        'timer': 10,
        'starting_hp': 150,
        'player_count': 2,
        'fps': 8,
    }
    stage_dict = {'1': [], '2': [], '3': []}

    @staticmethod
    def fresh_stages():
        return {'1': [], '2': [], '3': []}

    @classmethod
    def prepare_options(cls, options):
        if not isinstance(options, Mapping):
            raise ValueError('Options must be an object')
        if 'max_hp' in options:
            raise ValueError('max_hp is derived from starting_hp; configure starting_hp instead')
        if 'modifier_costs' in options:
            raise ValueError('Modifier costs are fixed to their ability tiers')
        result = {**deepcopy(cls.DEFAULT_OPTIONS), **deepcopy(options)}
        for name in ('starting_hp', 'timer', 'fps'):
            value = result[name]
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be a positive number')
        if not isinstance(result['timer'], int) or not isinstance(result['fps'], int):
            raise ValueError('timer and fps must be whole numbers')
        if not isinstance(result['starting_hp'], int):
            raise ValueError('starting_hp must be a positive integer')
        if (not isinstance(result['timed'], bool)
                or type(result['player_count']) is not int or result['player_count'] != 2):
            raise ValueError('RPS requires two players and a boolean timed option')
        deck = result.get('deck')
        if deck is None:
            deck = cls.deck()
        elif isinstance(deck, str):
            deck = cls.deck(deck)
        if not isinstance(deck, list) or len(deck) not in (9, 11):
            raise ValueError('A deck must contain nine RPS abilities')
        for slot, name in enumerate(deck[:9]):
            if not isinstance(name, str) or name not in CARD_CLASSES or CARD_CLASSES[name].slot != slot:
                raise ValueError(f'Invalid ability in deck slot {slot}')
        result['deck'] = [CARD_CLASSES[name].__name__ for name in deck[:9]] + ['Truce', 'PaciveIncome']
        return result

    def player_state(self, options):
        starting_hp = options.get('starting_hp', self.DEFAULT_OPTIONS['starting_hp'])
        max_hp = starting_hp / .75
        return {
            'max_hp': max_hp, 'hp': starting_hp, 'coins': 2,
            'selection': {}, 'modifier': None, 'infiltrate': False,
            'premonitions': {'2': [], '3': []},
            'coins_spent': 0, 'damage_taken': 0, 'last_damage': 0,
            'last_selection': None,
            'badges': [], 'badges_used': [],
            'shields': {'n': 0, 'this_turn': 0},
            'restrictions': [], 'stages': self.fresh_stages(),
            'cards': [
                {'name': name, 'level': slot // 3 + 1 if slot < 9 else 1, 'cracked': False,
                 'type': CARD_CLASSES[name].type, 'slot': slot}
                for slot, name in enumerate(options['deck'])
            ],
        }

    def start_state(self, options):
        options = self.prepare_options(options)
        p1, p2 = self.player_state(options), self.player_state(options)
        state = {
            'meta': {'round': 1, 'stage': 1, 'outcome': {'player': None, 'type': None},
                     'message': ['Game Start']},
            'p1': p1, 'p2': p2, 'pattern': None,
        }
        if not self.basic_only(state):
            state['pattern'] = self.generate_pattern_reward()
            state['meta']['message'].append(self.pattern_message(state['pattern'], p1['cards']))
        return state

    @staticmethod
    def basic_only(state):
        """Basic-only decks play without the pattern, modifiers, or coin abilities."""
        basic = {card.__name__ for card in DECKS['basic']}
        return all(card['name'] in basic for card in state['p1']['cards'][:9])

    @staticmethod
    def deck(mode: str = 'random'):
        if mode == 'random':
            cards = [choice(pair) for pair in zip(DECKS['basic'], DECKS['advanced'])]
        elif mode in DECKS:
            cards = DECKS[mode]
        else:
            raise ValueError(f'Unknown deck: {mode}')
        return [card.__name__ for card in cards] + ['Truce', 'PaciveIncome']

    @staticmethod
    def generate_pattern_reward():
        reward_type = choice(['coins', 'health', 'level', 'shields'])
        amounts = {'coins': (10, 20), 'health': (20, 40), 'level': (1, 2), 'shields': (1, 2)}
        pattern = {
            'sequence': [choice([ROCK, PAPER, SCISSORS]) for _ in range(3)],
            'reward_type': reward_type, 'reward_amount': randint(*amounts[reward_type]),
            'indicators': {},
        }
        if reward_type == 'level':
            pattern['reward_slot'] = randint(0, 8)
        return pattern

    @staticmethod
    def reward_label(pattern, cards=None):
        label = f"{pattern['reward_type']} +{pattern['reward_amount']}"
        slot = pattern.get('reward_slot')
        if slot is not None:
            label += f" ({cards[slot]['name'] if cards else f'slot {slot}'})"
        return label

    def pattern_message(self, pattern, cards=None):
        names = ' -> '.join(TYPES[ability_type] for ability_type in pattern['sequence'])
        return f"Pattern: {names}, reward: {self.reward_label(pattern, cards)}"

    def _advance_pattern(self, state, selections=None):
        if not state.get('pattern') or self.basic_only(state):
            return
        pattern = state.pattern
        indicators = {}
        for selection in self.get_selections(state) if selections is None else selections:
            if selection is None:
                continue
            position = pattern.indicators.get(selection.seat, -1) + 1
            if position < 3 and selection.card.type == pattern.sequence[position]:
                indicators[selection.seat] = position
            elif selection.card.type == pattern.sequence[0]:
                indicators[selection.seat] = 0
        rewarded = [seat for seat in seats if indicators.get(seat) == 2]
        for seat in rewarded:
            reward, amount = pattern.reward_type, pattern.reward_amount
            if reward == 'coins':
                state[seat].coins += amount
            elif reward == 'health':
                heal(state, seat, amount)
            elif reward == 'level':
                slot = pattern.get('reward_slot')
                if slot is None:
                    slot = choice(state[seat].cards[:9]).slot
                level_up(state, seat, slot, amount)
            elif reward == 'shields':
                state[seat].shields.n += amount
                state.meta.message.append(f'{seat}: gains {amount:g} shield')
            else:
                raise ValueError(f'Unknown pattern reward: {reward}')
            state.meta.message.append(
                f'{seat} completes the pattern: {self.reward_label(pattern, state[seat].cards)}')
        if rewarded:
            state.pattern = self.generate_pattern_reward()
            state.meta.message.append(self.pattern_message(state.pattern, state.p1.cards))
        else:
            state.pattern.indicators = indicators

    def update_pattern_indicators(self, gamestate, delta):
        state = Box(deepcopy(gamestate))
        selections = self.get_selections(state)
        update(state, delta)
        self._advance_pattern(state, selections)
        patch = gen_patch(gamestate, state)
        delta.clear()
        delta.update(patch)
        return delta

    @staticmethod
    def deck_text(game):
        return [Box(name=card['name'], slot=card['slot'],
                    text=CARD_CLASSES[card['name']].text,
                    modifier=CARD_CLASSES[card['name']].modifier,
                    modifier_cost=CARD_CLASSES[card['name']].modifier_cost(),
                    tier=card['slot'] // 3 + 1)
                for card in game.gamestate['p1']['cards'][:9]]

    def get_selections(self, gamestate, seats=seats):
        result = []
        for seat in seats:
            selection = None
            for stage in ('1', '2', '3'):
                for action in gamestate[seat].stages.get(stage, []):
                    if action['kind'] == 'RPS':
                        card = Box(deepcopy(gamestate[seat].cards[action['slot']]))
                        card.type = action.get('type', card.type)
                        selection = Box(seat=seat, stage=int(stage), card=card,
                                        modifier=action.get('modifier'))
                        break
                if selection is not None:
                    break
            result.append(selection)
        return result

    def pure_response(self, options, gamestate, history, seat):
        state = Box(deepcopy(gamestate))
        if state.meta.stage >= 4:
            return state
        visible = seats[seat] if seat in (0, 1) else None
        for player in seats:
            if player == visible:
                continue
            if history:
                state[player].cards = deepcopy(history[-1][0]['info'][player]['cards'])
            else:
                for stage in ('1', '2', '3'):
                    for action in state[player].stages.get(stage, []):
                        if action.get('kind') == 'RPS' and 'previous_type' in action:
                            state[player].cards[action.slot].type = action.previous_type
            state[player].selection = {}
            state[player].stages = self.fresh_stages()
            state[player].modifier = None
            state[player].infiltrate = False
            state[player].premonitions = {'2': [], '3': []}
        return state

    def stage_complete(self, state, seat):
        if self.get_selections(state, (seat,))[0] is not None:
            return True
        stage = state.meta.stage
        if any(action['kind'] == 'pass' for action in state[seat].stages.get(str(stage), [])):
            return True
        return any(rest.name == 'StageBlocked' and rest.arg == stage
                   for rest in active_restrictions(state, seat))

    def should_update(self, game, gamestate, timestamp):
        if game.status != ACTIVE or self.winner(gamestate):
            return False
        stage = gamestate.meta.stage
        if stage <= 3 and all(self.stage_complete(gamestate, seat) for seat in seats):
            return True
        return bool((game.options.get('timed', True) or stage == 4)
                    and game.last_tick is not None and game.has_ticked(timestamp))

    def _set_resolution(self, options, state, selected, timing=0, factor: float = 1, resolves=True):
        card = selected.card
        state[selected.seat].selection = {
            'slot': card.slot, 'stage': selected.stage, 'chosen_type': card.type,
            'level': card.level * factor, 'timing': timing,
            'modifier': selected.get('modifier'),
            'modifier_cost': CARD_CLASSES[card.name].modifier_cost(),
            'ability_number': len(CARD_CLASSES[card.name].steps()) if resolves else 0,
        }

    def _begin_resolution(self, options, state):
        p1, p2 = self.get_selections(state)
        if p1 is None and p2 is None:
            order = [Box(seat=seat, stage=0, card=state[seat].cards[TRUCE]) for seat in seats]
            outcome = 'truce'
            for selected in order:
                self._set_resolution(options, state, selected)
        elif p1 is None or p2 is None:
            selected = p1 if p1 is not None else p2
            assert selected is not None
            other_seat = opp(selected.seat)
            income = Box(seat=other_seat, stage=0, card=state[other_seat].cards[INCOME])
            order = [income, selected]
            outcome = 'default'
            for action in order:
                self._set_resolution(options, state, action)
        elif p1.card.type == p2.card.type and p1.stage == p2.stage:
            order = [p1, p2]
            if (state.p1.hp, state.p1.coins) == (state.p2.hp, state.p2.coins):
                shuffle(order)
            else:
                order.sort(key=lambda selected: (state[selected.seat].hp, state[selected.seat].coins),
                           reverse=True)
            outcome = 'tie'
            for selected in order:
                self._set_resolution(options, state, selected)
        else:
            if p1.card.type == p2.card.type:
                winner, loser = (p1, p2) if p1.stage < p2.stage else (p2, p1)
                outcome, factor, timing = 'ambush', .5, 0
            else:
                winner, loser = (p1, p2) if (p1.card.type - p2.card.type) % 3 == 1 else (p2, p1)
                outcome, factor = 'win', 1
                timing = max(0, loser.stage - winner.stage)
            order = [winner, loser]
            self._set_resolution(options, state, winner, timing, factor)
            self._set_resolution(options, state, loser, resolves=False)
        state.meta.stage = 4
        state.meta.outcome = {'player': order[0].seat, 'type': outcome}
        basic = self.basic_only(state)
        descriptions = {
            'truce': 'Truce: both players take 1 damage' + ('.' if basic else ' and earn $1.'),
            'default': 'One player passes: +2 health' + ('' if basic else ' and $2') + ', then the selected ability.',
            'tie': f'Same type and stage: {order[0].seat} acts first.',
            'ambush': f'{order[0].seat} acts at half level, without timing bonuses.',
            'win': f'{order[0].seat} wins RPS.',
        }
        state.meta.message.append(descriptions[outcome])

    def _end_round(self, state):
        selections = dict(zip(seats, self.get_selections(state)))
        self._advance_pattern(state)
        next_round = state.meta.round + 1
        for seat in seats:
            player = state[seat]
            selected = selections[seat]
            player.last_selection = ({'slot': selected.card.slot, 'type': selected.card.type}
                                     if selected is not None else None)
            player.last_damage = player.get('damage_taken', 0)
            player.damage_taken = 0
            player.coins_spent = 0
            player.modifier = None
            player.infiltrate = False
            player.premonitions = {'2': [], '3': []}
            player.stages = self.fresh_stages()
            player.selection = {}
            player.badges_used = []
            player.shields.this_turn = 0
            remaining = []
            for restriction in player.restrictions:
                if 'until' in restriction:
                    if restriction.until >= next_round:
                        remaining.append(restriction)
                elif restriction.duration > 1:
                    restriction.duration -= 1
                    remaining.append(restriction)
            player.restrictions = remaining
        state.meta.message.append(f'Round {state.meta.round} ends')
        state.meta.round = next_round
        state.meta.stage = 1
        state.meta.outcome = {'player': None, 'type': None}

    def pure_update(self, options, gamestate, history):
        if self.winner(gamestate):
            return {}
        state = Box(deepcopy(gamestate))
        state.meta.message = []
        stage = state.meta.stage
        if stage in (1, 2):
            state.meta.stage += 1
        elif stage == 3:
            self._begin_resolution(options, state)
        elif stage == 4:
            first = state.meta.outcome.player
            if state.meta.outcome.type == 'truce' and state[first].selection.ability_number:
                for seat in seats:
                    hurt(state, seat, 1, check_winner=False)
                    state[seat].coins += 1
                    state[seat].selection.ability_number = 0
                if winner := self.winner(state):
                    state.meta.message.append(winner)
            else:
                for seat in (first, opp(first)):
                    selection = state[seat].selection
                    if selection.ability_number:
                        card = CARD_CLASSES[state[seat].cards[selection.slot].name]
                        update(state, card.apply(state, history, seat))
                        break
                else:
                    self._end_round(state)
        else:
            raise ValueError(f'Invalid stage: {stage}')
        return Box(gen_patch(gamestate, state))

    def winner(self, gamestate):
        if winner := gamestate.meta.get('winner'):
            return 'Tie game!' if winner == 'tie' else f'{winner} wins!'
        p1_dead, p2_dead = gamestate.p1.hp <= 0, gamestate.p2.hp <= 0
        if p1_dead and p2_dead:
            return 'Tie game!'
        if p1_dead or p2_dead:
            return f'{"p2" if p1_dead else "p1"} wins!'
        return None

    def get_restrictions(self, gamestate, seat):
        return active_restrictions(gamestate, seat)

    def _ability_error(self, state, seat, slot):
        if slot // 3 + 1 > state.meta.stage:
            return 'That ability is not unlocked yet'
        ability_type = state[seat].cards[slot].type
        for restriction in active_restrictions(state, seat):
            blocked = (
                (restriction.name == 'Disabled' and restriction.arg == slot)
                or (restriction.name == 'Suppressed' and slot >= 6)
                or (restriction.name == 'StageBlocked' and restriction.arg == state.meta.stage)
                or (restriction.name == 'TypeBlocked' and restriction.arg == ability_type)
            )
            if blocked:
                return f'Move rejected due to {restriction.source}'
        return None

    def _premonition_candidates(self, state, seat):
        other = opp(seat)
        earlier = {action['slot'] for stage in range(1, state.meta.stage)
                   for action in state[other].stages[str(stage)] if action['kind'] == 'RPS'}
        revealed = state[seat].get('premonitions', {}).get(str(state.meta.stage), [])
        return [slot for slot in range(9) if slot not in earlier and slot not in revealed
                and slot // 3 + 1 < state.meta.stage
                and self._ability_error(state, other, slot) is None]

    def move_error(self, state, seat, move):
        if seat not in seats or not isinstance(move, Mapping):
            return 'Invalid move'
        if self.winner(state):
            return 'The game is finished'
        if state.meta.stage not in (1, 2, 3):
            return 'Between rounds'
        if self.get_selections(state, (seat,))[0] is not None:
            return 'Already selected an RPS ability'
        stage = state.meta.stage
        player = state[seat]
        if any(action['kind'] == 'pass' for action in player.stages[str(stage)]):
            return 'Already passed this stage'
        kind = move.get('type')
        if kind == 'pass':
            return None
        if kind not in ('selection', 'modifier', 'coin'):
            return 'Unknown move type'
        if kind in ('modifier', 'coin') and self.basic_only(state):
            return 'The basic deck has no modifiers or coin abilities'
        for restriction in active_restrictions(state, seat):
            if restriction.name == 'StageBlocked' and restriction.arg == stage:
                return f'Move rejected due to {restriction.source}'
        if kind in ('selection', 'modifier'):
            slot = move.get('selection')
            if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < 9:
                return 'Choose an RPS ability slot from 0 to 8'
            if kind == 'modifier':
                if slot // 3 + 1 > stage:
                    return 'That modifier is not unlocked yet'
                if not CARD_CLASSES[player.cards[slot].name].modifier:
                    return 'That ability has no modifier'
                return None
            if error := self._ability_error(state, seat, slot):
                return error
            if player.get('infiltrate'):
                ability_type = move.get('as_type')
                if type(ability_type) is not int or ability_type not in (ROCK, PAPER, SCISSORS):
                    return 'Choose a type for Infiltrate'
            elif 'as_type' in move:
                return 'Use Infiltrate before changing an ability type'
            return None
        ability = move.get('ability')
        if not isinstance(ability, str) or ability not in COIN_ABILITIES:
            return 'Unknown coin ability'
        coin = COIN_ABILITIES[ability]
        if coin['tier'] > stage:
            return 'That coin ability is not unlocked yet'
        if ability == 'Suppress' and stage == 3:
            return 'Suppress is not usable in stage three'
        if ability == 'Infiltrate' and player.get('infiltrate'):
            return 'Infiltrate is already active this round'
        for restriction in active_restrictions(state, seat):
            if restriction.name == 'CoinLocked' or (restriction.name == 'Suppressed' and coin['tier'] == 3):
                return f'Move rejected due to {restriction.source}'
        if player.coins < coin['cost']:
            return 'Not enough coins'
        if ability == 'Premonition':
            if len(player.get('premonitions', {}).get(str(stage), [])) >= 2:
                return 'Premonition has already been used twice this stage'
            if not self._premonition_candidates(state, seat):
                return 'No abilities can be revealed'
        return None

    def move(self, game, seat, move):
        if game.status != ACTIVE:
            return {'error': f'Game is not active ({game.status})'}
        if seat not in (0, 1):
            return {'error': 'Only seated players can move'}
        if type(move) is int and move == -1:
            move = {'type': 'pass'}
        return self.pure_move(Box(game.options), Box(game.gamestate), game.history, seats[seat], move)

    def pure_move(self, options, gamestate, history, seat, move):
        if error := self.move_error(gamestate, seat, move):
            return {'error': error}
        state = Box(deepcopy(gamestate))
        state.meta.message = []
        player = state[seat]
        stage = str(state.meta.stage)
        kind = move['type']
        if kind == 'pass':
            player.stages[stage].append({'kind': 'pass'})
        elif kind == 'modifier':
            player.modifier = move['selection']
        elif kind == 'selection':
            card = player.cards[move['selection']]
            previous_type = card.type
            if player.get('infiltrate'):
                card.type = move['as_type']
            player.stages[stage].append({
                'kind': 'RPS', 'slot': card.slot, 'type': card.type,
                'previous_type': previous_type, 'modifier': player.get('modifier'),
            })
        else:
            ability = move['ability']
            cost = COIN_ABILITIES[ability]['cost']
            player.coins -= cost
            player.coins_spent = player.get('coins_spent', 0) + cost
            player.stages[stage].append({'kind': 'coin', 'ability': ability})
            if ability == 'Suppress':
                add_restriction(state, opp(seat), 'Suppressed', 3, 1,
                                f"{seat}'s Suppress @ round {state.meta.round}", immediate=True)
            elif ability == 'Premonition':
                revealed = choice(self._premonition_candidates(state, seat))
                player.setdefault('premonitions', {'2': [], '3': []})[stage].append(revealed)
            elif ability == 'Infiltrate':
                player.infiltrate = True
            state.meta.message.append(f'{seat}: pays ${cost} for {ability}')
        return Box(gen_patch(gamestate, state))

    def pure_untimed_move(self, options, gamestate, history, seat, move):
        return self.pure_move(options, gamestate, history, seat, move)

    def next_tick(self, game):
        if game.gamestate['meta']['stage'] <= 3:
            return game.options.get('timer', 10) if game.options.get('timed', True) else 0
        return 2 if game.gamestate['meta']['message'] else 0

    def gameboard_context(self, name, seat, game, gamestate, now):
        visible = self.response(game, seat)
        context = super().gameboard_context(name, seat, game, gamestate, now)
        context.update(game.response(visible, now))
        context.status = seats[seat] if seat in (0, 1) else 'spectating'
        context.finished = game.status == FINISHED
        context.winner = self.winner(visible)
        context.timed = game.options.get('timed', True)
        stage = visible.meta.stage
        own_seat = seats[seat] if seat in (0, 1) else None
        selected = [selection.card.slot if selection else None for selection in self.get_selections(visible)]
        cards, modifiers = [], []
        for card in visible.p1.cards[:9]:
            other = visible.p2.cards[card.slot]
            ability = CARD_CLASSES[card.name]
            mine = visible[own_seat].cards[card.slot] if own_seat else card
            color_index = int(card.slot == selected[0]) + 2 * int(card.slot == selected[1])
            color = [WHITE, BLUE, RED, YELLOW][color_index]
            if stage < 4 and not color_index and card.slot // 3 + 1 <= stage:
                color = GREEN
            move = {'type': 'selection', 'selection': card.slot}
            if own_seat and visible[own_seat].get('infiltrate'):
                move['as_type'] = mine.type
            error = self.move_error(visible, own_seat, move) if own_seat else 'Spectating'
            modifier = None
            if ability.modifier:
                modifier_error = (self.move_error(visible, own_seat, {'type': 'modifier', 'selection': card.slot})
                                  if own_seat else 'Spectating')
                chosen = [visible[player].get('modifier') == card.slot for player in seats]
                check_index = int(chosen[0]) + 2 * int(chosen[1])
                modifier = Box(
                    slot=card.slot, name=card.name, text=ability.modifier,
                    cost=ability.modifier_cost(), checked=bool(check_index),
                    check_color=[WHITE, BLUE, RED, YELLOW][check_index],
                    disabled=not context.active or modifier_error is not None,
                    reason=modifier_error or f'Modifier (${ability.modifier_cost()}): {ability.modifier}',
                )
                modifiers.append(modifier)
            cards.append(Box(
                slot=card.slot,
                name=f"{card.level:g}{'X' if card.cracked else ''} {card.name} {other.level:g}{'X' if other.cracked else ''}",
                type_label=f'{TYPES[card.type]} / {TYPES[other.type]}',
                color=color, disabled=not context.active or error is not None,
                reason=error or ability.text, modifier=modifier,
            ))
        context.cards = cards
        context.modifiers = modifiers
        context.basic_only = self.basic_only(visible)
        context.coins = []
        for ability, data in ({} if context.basic_only else COIN_ABILITIES).items():
            error = (self.move_error(visible, own_seat, {'type': 'coin', 'ability': ability})
                     if own_seat else 'Spectating')
            context.coins.append(Box(name=ability, **data, disabled=not context.active or error is not None,
                                     color=GREEN if data['tier'] <= stage else WHITE, reason=error or data['text']))
        context.rows = [
            Box(tier=tier, cards=cards[3 * (tier - 1):3 * tier],
                coins=[coin for coin in context.coins if coin.tier == tier])
            for tier in (1, 2, 3)
        ]
        context.pass_disabled = (not own_seat or not context.active
                                 or self.move_error(visible, own_seat, {'type': 'pass'}) is not None)
        passed = [any(action['kind'] == 'pass' for action in visible[player].stages.get(str(min(stage, 3)), []))
                  for player in seats]
        context.pass_color = [WHITE, BLUE, RED, YELLOW][int(passed[0]) + 2 * int(passed[1])]
        context.infiltrate = bool(own_seat and visible[own_seat].get('infiltrate') and stage < 4)
        context.premonitions = []
        if own_seat:
            for reveal_stage, slots in visible[own_seat].get('premonitions', {}).items():
                for slot in slots:
                    context.premonitions.append(f"Stage {reveal_stage}: {visible[opp(own_seat)].cards[slot].name}")
        for player in seats:
            context[f'{player}_percent'] = health_percent(visible[player])
            context[f'{player}_badges'] = '; '.join(describe_badge(badge) for badge in visible[player].badges)
            context[f'{player}_restrictions'] = [
                describe_restriction(visible, player, rest) for rest in visible[player].restrictions
            ]
        pattern = visible.get('pattern')
        context.pattern = None if context.basic_only or not pattern else {
            'sequence': [TYPES[value] for value in pattern.sequence],
            'reward_type': pattern.reward_type, 'reward_amount': pattern.reward_amount,
            'reward_label': self.reward_label(pattern, visible.p1.cards),
            'p1_indicator': pattern.indicators.get('p1'),
            'p2_indicator': pattern.indicators.get('p2'),
        }
        return context

    def game_data(self, game, seat):
        coins = {} if self.basic_only(game.gamestate) else COIN_ABILITIES
        return {'cards': self.deck_text(game), 'fps': game.options.get('fps', 8),
                'coin_texts': [Box(name=name, **data) for name, data in coins.items()]}
