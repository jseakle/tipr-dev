from copy import deepcopy
from math import floor
from random import choice

from .utils import (
    Box, DEFAULT, GREEN, INCOME, PAPER, RED, ROCK, SCISSORS, TRUCE, TYPES,
    gen_patch, opp, seats,
)


COIN_ABILITIES = {
    'Suppress': {'tier': 1, 'cost': 10,
                 'text': 'Your opponent cannot select tier three abilities this round. Not usable in stage three.'},
    'Premonition': {'tier': 2, 'cost': 2,
                   'text': ('Reveal a selectable ability from an earlier tier that was not chosen '
                            'in an earlier stage. Twice per stage.')},
    'Infiltrate': {'tier': 3, 'cost': 4,
                  'text': 'Permanently change the type of the RPS ability you select this round.'},
}


def active_restrictions(state, seat):
    round_number = state.meta.round
    return [restriction for restriction in state[seat].restrictions
            if restriction.get('starts', 0) <= round_number
            and round_number <= restriction.get('until', round_number)
            and restriction.duration > 0]


def restricted(state, seat, name):
    return any(restriction.name == name for restriction in active_restrictions(state, seat))


def add_restriction(state, seat, name, arg, duration, source, immediate=False):
    starts = state.meta.round + (0 if immediate else 1)
    state[seat].restrictions.append({
        'name': name, 'arg': arg, 'duration': duration, 'source': source,
        'starts': starts, 'until': starts + duration - 1,
    })


def pattern_advances(state, seat, ability_type):
    position = state.pattern.indicators.get(seat, -1) + 1
    return position < 3 and ability_type == state.pattern.sequence[position]


def health_percent(player):
    return floor(100 * player.hp / player.max_hp + .5)


def describe_badge(badge):
    name, arg = badge[0], badge[1]
    if name.endswith('Curse'):
        curse_type = name[:-len('Curse')]
        condition = f' with {curse_type.lower()}' if curse_type else ''
        return f'if you win{condition}, take {arg:g} damage'
    descriptions = {
        'DmgBonus': f'+{arg} damage on your next win',
        'DmgMultiplier': f'×{arg} damage on your next win',
        'ScissorsDmgMultiplier': f'×{arg} damage if scissors; used up by your next win',
        'LvlBonus': f'+{arg} levels on your next win',
        'HalfLevel': 'half level on your next win',
        'LvlDamageBonus': f'+{arg} level damage on your next win',
    }
    return descriptions.get(name, name)


def describe_restriction(state, seat, restriction):
    name, arg = restriction['name'], restriction.get('arg')
    if name == 'Disabled':
        text = f"{state[seat].cards[arg]['name']} is disabled"
    elif name == 'StageBlocked':
        text = f'cannot act in stage {arg}'
    elif name == 'TypeBlocked':
        text = f'cannot select {TYPES[arg].lower()} abilities'
    elif name == 'Suppressed':
        text = f'cannot select tier {arg} abilities'
    elif name == 'CoinLocked':
        text = 'cannot spend coins'
    else:
        text = name
    until = restriction.get('until', state.meta.round)
    return f"{text} through round {until} ({restriction['source']})"


class GameEnded(Exception):
    """Stop the current ability immediately after lethal damage."""


def hurt(state, seat, amount, *, check_winner=True):
    amount = max(0, amount)
    if amount == 0:
        return
    player = state[seat]
    if player.shields.n > 0:
        player.shields.n -= 1
        player.shields.this_turn = min(player.shields.this_turn, player.shields.n)
        state.meta.message.append(f"{seat}: shield prevents {amount:g} damage")
        return
    player.hp -= amount
    player.damage_taken = player.get('damage_taken', 0) + amount
    player.damage_since_win = player.get('damage_since_win', 0) + amount
    state.meta.message.append(f"{seat}: takes {amount:g} damage")
    if player.hp <= 0 and check_winner:
        state.meta.winner = opp(seat)
        state.meta.message.append(f"{opp(seat)} wins!")
        raise GameEnded


def heal(state, seat, amount):
    player = state[seat]
    restored = min(max(0, amount), max(0, player.max_hp - player.hp))
    player.hp += restored
    state.meta.message.append(f"{seat}: gains {restored:g} health")


def level_up(state, seat, slot, amount=1):
    card = state[seat].cards[slot]
    card.level += amount
    card.cracked = False
    state.meta.message.append(f"{seat}: {card.name} gains {amount:g} level")


def set_type(card, ability_type, until=None):
    """Change an ability's type, permanently or (with `until`) through the given round."""
    if until is None:
        card.pop('temp_type', None)
    elif card.type != ability_type:
        original = card.get('temp_type', {}).get('original', card.type)
        card.temp_type = {'type': ability_type, 'original': original, 'until': until}
    card.type = ability_type


def expire_temporary_types(player, next_round):
    for card in player.cards:
        temp = card.get('temp_type')
        if temp and temp['until'] < next_round:
            if card.type == temp['type']:
                card.type = temp['original']
            del card['temp_type']


def level_damage(state, seat, slot, amount=1):
    if int(amount) != amount or amount < 0:
        raise ValueError("Level damage must be a nonnegative whole number")
    card = state[seat].cards[slot]
    for _ in range(int(amount)):
        if card.cracked:
            previous_level = card.level
            card.level = max(0, card.level - 1)
            card.cracked = False
            state.meta.message.append(f"{seat}: {card.name} levels down to {card.level:g}")
            if card.name == 'Shears' and card.level < previous_level:
                hurt(state, opp(seat), 10)
        else:
            card.cracked = True
            state.meta.message.append(f"{seat}: {card.name} cracks")


def _format(value):
    if isinstance(value, (int, float)):
        return f'{round(value, 2):g}'
    return str(value)


class CardText:
    """Builds a card's text.

    Without a view it is the generic text. With a view, the viewer's own copy of the card is
    described: calculated values get their current value in parentheses, and conditions that
    can already be decided are colored by whether they will happen (in html mode).
    """

    def __init__(self, view=None, seat=None, slot=None, html=True):
        self.view, self.seat, self.slot, self.html = view, seat, slot, html

    @property
    def live(self):
        return self.view is not None

    @property
    def player(self):
        return self.view[self.seat]

    @property
    def other(self):
        return self.view[opp(self.seat)]

    @property
    def card(self):
        return self.player.cards[self.slot]

    @property
    def L(self):
        return self.card.level

    def v(self, label, compute):
        if not self.live:
            return label
        value = compute()
        return label if value is None else f'{label} ({_format(value)})'

    def when(self, text, compute):
        if not self.live or not self.html:
            return text
        truth = compute()
        if truth is None:
            return text
        return f'<span style="color:{GREEN if truth else RED}">{text}</span>'

    def last_selection(self):
        previous = self.player.get('last_selection')
        return self.player.cards[previous['slot']] if previous else None


class RPSCard:
    type = DEFAULT
    slot = -1
    text = ''
    modifier = None
    badge_multiplier = 1

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if 'describe' in cls.__dict__:
            cls.text = cls.describe(CardText())
        if 'describe_modifier' in cls.__dict__:
            cls.modifier = cls.describe_modifier(CardText())

    @classmethod
    def describe(cls, t):
        return cls.text

    @classmethod
    def describe_modifier(cls, t):
        return cls.modifier
    ability_order = ()

    def __init__(self, state, seat):
        self.state = state
        self.seat = seat
        self.player = state[seat]
        self.other_seat = opp(seat)
        self.other = state[self.other_seat]
        self.selection = self.player.selection
        self.card = self.player.cards[self.selection.slot]

    @classmethod
    def steps(cls):
        return ('start', *cls.ability_order, 'level_up', 'level_damage', 'end')

    @classmethod
    def modifier_cost(cls) -> int:
        return cls.slot // 3 + 1 if cls.modifier else 0

    @classmethod
    def apply(cls, gamestate, history, seat):
        state = Box(deepcopy(gamestate))
        state.meta.message = []
        card = cls(state, seat)
        number = card.selection.ability_number
        if not 1 <= number <= len(cls.steps()):
            raise ValueError(f"Invalid resolution step {number} for {cls.__name__}")
        card.selection.ability_number -= 1
        try:
            getattr(card, cls.steps()[len(cls.steps()) - number])()
        except GameEnded:
            card.consume_badges()
            card.selection.ability_number = 0
        return Box(gen_patch(gamestate, state))

    @property
    def level(self):
        return self.selection.level

    @property
    def timing(self):
        return self.selection.timing

    @property
    def modified(self):
        return self.selection.get('modified', False)

    @property
    def winning(self):
        outcome = self.state.meta.outcome
        return outcome.type == 'win' and outcome.player == self.seat

    @property
    def opposing_slot(self):
        slot = self.other.selection.get('slot')
        return slot if slot is not None and 0 <= slot < 9 else None

    @property
    def opposing_type(self):
        if self.opposing_slot is not None:
            return self.other.selection.get('chosen_type', self.other.cards[self.opposing_slot].type)
        return DEFAULT

    def source(self):
        return f"{self.seat}'s {self.card.name} @ round {self.state.meta.round}"

    def mark_badge(self, index):
        if index not in self.selection.used_badges:
            self.selection.used_badges.append(index)
            self.player.badges_used.append(deepcopy(self.selection.badges[index]))

    def numeric_badges(self, kind, amount):
        if not self.winning:
            return amount
        for _ in range(self.badge_multiplier):
            for index, (name, arg, _) in enumerate(self.selection.get('badges', [])):
                applied = True
                if kind == 'damage' and name == 'DmgBonus':
                    amount += arg
                elif kind == 'damage' and name == 'DmgMultiplier':
                    amount *= arg
                elif (kind == 'damage' and name == 'ScissorsDmgMultiplier'
                      and self.selection.chosen_type == SCISSORS):
                    amount *= arg
                elif kind == 'level' and name == 'LvlBonus':
                    amount += arg
                elif kind == 'level' and name == 'HalfLevel':
                    amount /= 2
                elif kind == 'level_damage' and name == 'LvlDamageBonus':
                    amount += arg
                else:
                    applied = False
                if applied:
                    self.mark_badge(index)
        return amount

    def hit(self, target, amount):
        hurt(self.state, target, self.numeric_badges('damage', amount))

    def total_level(self, ability_type, owners):
        return sum(self.level if owner == self.seat and card.slot == self.card.slot else card.level
                   for owner in owners for card in self.state[owner].cards[:9]
                   if card.type == ability_type)

    def grant_badge(self, name, arg, target=None):
        target = target or self.seat
        self.state[target].badges.append([name, arg, self.state.meta.round])
        self.state.meta.message.append(f"{target}: gains a badge: {describe_badge([name, arg])}")

    def gain_shields(self, count):
        self.player.shields.n += count
        self.player.shields.this_turn += count
        self.state.meta.message.append(f"{self.seat}: gains {count} shield")

    def disable_opponent(self, duration):
        if self.opposing_slot is not None:
            add_restriction(self.state, self.other_seat, 'Disabled', self.opposing_slot,
                            duration, self.source())

    def start(self):
        self.selection.health_before = {seat: self.state[seat].hp for seat in seats}
        self.selection.badges = deepcopy(self.player.badges) if self.winning else []
        self.selection.used_badges = []
        self.player.badges_used = []
        self.selection.modified = False
        if self.modifier and self.selection.get('modifier') == self.card.slot:
            cost = self.modifier_cost()
            self.selection.modifier_cost = cost
            if self.player.coins >= cost and not restricted(self.state, self.seat, 'CoinLocked'):
                self.player.coins -= cost
                self.player.coins_spent = self.player.get('coins_spent', 0) + cost
                self.selection.modified = True
                self.state.meta.message.append(f"{self.seat}: pays ${cost:g} for {self.card.name}'s modifier")
            else:
                self.state.meta.message.append(f"{self.seat}: cannot pay for {self.card.name}'s modifier")
        self.selection.level = self.numeric_badges('level', self.level)

    def level_up(self):
        if self.winning:
            level_up(self.state, self.seat, self.card.slot)

    def level_damage(self):
        if self.winning and self.opposing_slot is not None:
            level_damage(self.state, self.other_seat, self.opposing_slot,
                         self.numeric_badges('level_damage', 1))

    def consume_badges(self):
        used = self.selection.get('used_badges', [])
        self.player.badges = [badge for index, badge in enumerate(self.player.badges)
                              if index not in used]
        self.player.badges_used = []

    def end(self):
        if self.winning:
            for _ in range(self.badge_multiplier):
                for index, (name, amount, _) in enumerate(self.selection.badges):
                    if name == 'Curse' or name == f"{TYPES[self.selection.chosen_type]}Curse":
                        self.mark_badge(index)
                        hurt(self.state, self.seat, amount)
            # Spent by any win, so it rewards picking scissors next turn rather than eventually.
            for index, (name, _, _) in enumerate(self.selection.badges):
                if name == 'ScissorsDmgMultiplier':
                    self.mark_badge(index)
        self.consume_badges()


class Pebble(RPSCard):
    type, slot = ROCK, 0
    ability_order = ('damage', 'badge')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('5 + L', lambda: 5 + t.L)} damage. T1: gain a 2x damage badge. "
                f"T2: {t.v('+3L', lambda: 3 * t.L)} damage.")

    def damage(self):
        self.hit(self.other_seat, 5 + self.level + (3 * self.level if self.timing >= 2 else 0))

    def badge(self):
        if self.timing >= 1:
            self.grant_badge('DmgMultiplier', 2)


class Napkin(RPSCard):
    type, slot = PAPER, 1
    ability_order = ('health', 'damage', 'shield')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('2L', lambda: 2 * t.L)} health. "
                "T1: +4X damage, where X is opposing level. T2: gain a shield.")

    def health(self):
        heal(self.state, self.seat, 2 * self.level)

    def damage(self):
        if self.timing >= 1 and self.opposing_slot is not None:
            self.hit(self.other_seat, 4 * self.other.cards[self.opposing_slot].level)

    def shield(self):
        if self.timing >= 2:
            self.gain_shields(1)


class ButterKnife(RPSCard):
    type, slot = SCISSORS, 2
    ability_order = ('damage', 'restriction')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('10 + 2L', lambda: 10 + 2 * t.L)} damage. Disable opposing ability for 1 turn. "
                "T1: disable another random opposing ability for 1 turn. "
                f"T2: {t.v('+10 + 2L', lambda: 10 + 2 * t.L)} damage.")

    def damage(self):
        amount = 10 + 2 * self.level
        if self.timing >= 2:
            amount += 10 + 2 * self.level
        self.hit(self.other_seat, amount)

    def restriction(self):
        self.disable_opponent(1)
        if self.timing >= 1:
            slot = choice([card.slot for card in self.other.cards[:9]
                           if card.slot != self.opposing_slot])
            add_restriction(self.state, self.other_seat, 'Disabled', slot, 1, self.source())


class Boulder(RPSCard):
    type, slot = ROCK, 3
    ability_order = ('badge',)

    @classmethod
    def describe(cls, t):
        return f"Gain a {t.v('+25+5L', lambda: 25 + 5 * t.L)} damage badge. T1: gain a +2 level badge."

    def badge(self):
        self.grant_badge('DmgBonus', 25 + 5 * self.level)
        if self.timing >= 1:
            self.grant_badge('LvlBonus', 2)


class Book(RPSCard):
    type, slot = PAPER, 4
    ability_order = ('damage', 'respec', 'previous_level')

    @classmethod
    def describe(cls, t):
        def shared_levels():
            return 1 + 7 * sum(card.level for player in (t.player, t.other) for card in player.cards[:9]
                               if card.type == t.card.type)

        def previous_type():
            previous = t.player.get('last_selection')
            return TYPES[previous['type']] if previous else 'none'

        def previous_name():
            card = t.last_selection()
            return card.name if card else 'none'

        return (f"{t.v('1+7X', shared_levels)} damage, where X is the total level of all abilities sharing "
                f"this type. Become {t.v('the type you selected last turn', previous_type)}, "
                f"or paper. {t.v('That previous ability', previous_name)} levels up. "
                "T1: the previous ability levels up two more times.")

    def damage(self):
        self.hit(self.other_seat, 1 + 7 * self.total_level(self.selection.chosen_type, seats))

    def respec(self):
        previous = self.player.get('last_selection')
        set_type(self.card, previous['type'] if previous else PAPER)

    def previous_level(self):
        previous = self.player.get('last_selection')
        if previous:
            level_up(self.state, self.seat, previous['slot'], 1 + (2 if self.timing >= 1 else 0))


class Wirecutter(RPSCard):
    type, slot = SCISSORS, 5
    ability_order = ('damage', 'badge', 'respec')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('X', lambda: sum(c.level for c in t.player.cards[:9] if c.type == SCISSORS))} damage, "
                "where X is the sum of your scissors levels. Gain a badge: 3x damage if scissors, "
                "used up by your next win of any type. "
                "T1: a random non-scissors ability of yours becomes scissors.")

    def damage(self):
        self.hit(self.other_seat, self.total_level(SCISSORS, (self.seat,)))

    def badge(self):
        self.grant_badge('ScissorsDmgMultiplier', 3)

    def respec(self):
        if self.timing >= 1:
            candidates = [card for card in self.player.cards[:9] if card.type != SCISSORS]
            if candidates:
                card = choice(candidates)
                set_type(card, SCISSORS)
                self.state.meta.message.append(f'{self.seat}: {card.name} becomes scissors')
            else:
                self.state.meta.message.append(f'{self.seat}: all RPS abilities are already scissors')


class Mountain(RPSCard):
    type, slot = ROCK, 6
    badge_multiplier = 2
    ability_order = ('damage', 'crack')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('15 + 10L', lambda: 15 + 10 * t.L)} damage. "
                "Crack all opposing abilities. Badges apply twice.")

    def damage(self):
        self.hit(self.other_seat, 15 + 10 * self.level)

    def crack(self):
        for card in self.other.cards[:9]:
            card.cracked = True


class Contract(RPSCard):
    type, slot = PAPER, 7
    ability_order = ('damage', 'shield', 'badge')

    @classmethod
    def describe(cls, t):
        return ("7 damage. Gain a shield. Your opponent gains an end badge: "
                f"if this is the opposing type, take {t.v('20 + 10L', lambda: 20 + 10 * t.L)} damage.")

    def damage(self):
        self.hit(self.other_seat, 7)

    def shield(self):
        self.gain_shields(1)

    def badge(self):
        if self.opposing_type != DEFAULT:
            self.grant_badge(f'{TYPES[self.opposing_type]}Curse', 20 + 10 * self.level,
                             self.other_seat)


class TwoHander(RPSCard):
    type, slot = SCISSORS, 8
    ability_order = ('damage', 'restriction')

    @classmethod
    def describe(cls, t):
        return (f"{t.when('5 damage below level one', lambda: t.L < 1)}, "
                f"{t.when('otherwise 50 damage', lambda: t.L >= 1)}. If the opposing ability is cracked, "
                "disable all opposing abilities for one turn and this ability for three turns.")

    def damage(self):
        self.hit(self.other_seat, 50 if self.level >= 1 else 5)

    def restriction(self):
        if self.opposing_slot is not None and self.other.cards[self.opposing_slot].cracked:
            for slot in range(9):
                add_restriction(self.state, self.other_seat, 'Disabled', slot, 1, self.source())
            add_restriction(self.state, self.seat, 'Disabled', self.card.slot, 3, self.source())


class Nugget(RPSCard):
    type, slot = ROCK, 0
    ability_order = ('damage', 'coins', 'badge')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('5L + 5', lambda: 5 * t.L + 5)} damage. ${t.v('2L', lambda: 2 * t.L)}. "
                f"T1: {t.v('+5L', lambda: 5 * t.L)} damage. T2: gain a +2 level damage badge.")

    @classmethod
    def describe_modifier(cls, t):
        return 'Triple coins.'

    def damage(self):
        self.hit(self.other_seat, 5 * self.level + 5 + (5 * self.level if self.timing >= 1 else 0))

    def coins(self):
        self.player.coins += 2 * self.level * (3 if self.modified else 1)

    def badge(self):
        if self.timing >= 2:
            self.grant_badge('LvlDamageBonus', 2)


class LoveLetter(RPSCard):
    type, slot = PAPER, 1
    ability_order = ('health', 'damage', 'uncrack')

    @classmethod
    def describe(cls, t):
        return (f"5 damage. {t.v('3L', lambda: 3 * t.L)} health. "
                "T1: uncrack a random one of your cracked abilities. "
                "T2: double health (stacks with the modifier).")

    @classmethod
    def describe_modifier(cls, t):
        return 'Double health.'

    def health(self):
        amount = 3 * self.level * (2 if self.modified else 1) * (2 if self.timing >= 2 else 1)
        heal(self.state, self.seat, amount)

    def damage(self):
        self.hit(self.other_seat, 5)

    def uncrack(self):
        cracked = [card for card in self.player.cards[:9] if card.cracked]
        if self.timing >= 1 and cracked:
            card = choice(cracked)
            card.cracked = False
            self.state.meta.message.append(f'{self.seat}: {card.name} is no longer cracked')


class Dagger(RPSCard):
    type, slot = SCISSORS, 2
    ability_order = ('damage', 'coins', 'restriction')

    @classmethod
    def describe(cls, t):
        def advances():
            return pattern_advances(t.view, t.seat, t.card.type) if t.view.get('pattern') else None

        return (f"{t.v('10L + 10', lambda: 10 * t.L + 10)} damage. "
                f"{t.when('If this advances your indicator, $2.', advances)} "
                "T1: your opponent cannot act in the same stage next turn. T2: double damage.")

    @classmethod
    def describe_modifier(cls, t):
        return f"{t.v('+5L', lambda: 5 * t.L)} damage."

    def damage(self):
        amount = 10 * self.level + 10 + (5 * self.level if self.modified else 0)
        self.hit(self.other_seat, amount * (2 if self.timing >= 2 else 1))

    def coins(self):
        if pattern_advances(self.state, self.seat, self.selection.chosen_type):
            self.player.coins += 2

    def restriction(self):
        if self.timing >= 1:
            add_restriction(self.state, self.other_seat, 'StageBlocked',
                            self.other.selection.stage, 1, self.source())


class Avalanche(RPSCard):
    type, slot = ROCK, 3
    ability_order = ('damage', 'coins', 'restriction')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('10L', lambda: 10 * t.L)} damage. ${t.v('4L', lambda: 4 * t.L)}. "
                "When this levels up, your other rock abilities level up too. "
                "T1: level damage dealt this round also applies to all other abilities of the opposing type.")

    @classmethod
    def describe_modifier(cls, t):
        return 'Your opponent cannot spend coins next turn.'

    def damage(self):
        self.hit(self.other_seat, 10 * self.level)

    def coins(self):
        self.player.coins += 4 * self.level

    def restriction(self):
        if self.modified:
            add_restriction(self.state, self.other_seat, 'CoinLocked', None, 1, self.source())

    def level_up(self):
        if self.winning:
            level_up(self.state, self.seat, self.card.slot)
            for card in self.player.cards[:9]:
                if card.type == ROCK and card.slot != self.card.slot:
                    level_up(self.state, self.seat, card.slot)

    def level_damage(self):
        if not self.winning or self.opposing_slot is None:
            return
        amount = self.numeric_badges('level_damage', 1)
        targets = [self.opposing_slot]
        if self.timing >= 1:
            targets.extend(card.slot for card in self.other.cards[:9]
                           if card.slot != self.opposing_slot and card.type == self.opposing_type)
        for slot in targets:
            level_damage(self.state, self.other_seat, slot, amount)


class Thesaurus(RPSCard):
    type, slot = PAPER, 4
    ability_order = ('damage', 'shield', 'restriction')

    @classmethod
    def describe(cls, t):
        return ("1 damage three times (badges only boost the first hit). "
                f"{t.when('Gain a shield if this is level one or higher.', lambda: t.L >= 1)} "
                f"{t.when('Gain two more if it is level three or higher.', lambda: t.L >= 3)} "
                "T1: disable your opponent's abilities of the opposing type for one turn.")

    @classmethod
    def describe_modifier(cls, t):
        def spent():
            this_turn = t.other.get('coins_spent', 0) if t.view.meta.stage >= 4 else '?'
            return f"{_format(t.other.get('last_coins_spent', 0))} + {_format(this_turn)}"

        return (f"The third hit does {t.v('+X', spent)} damage, where X is the coins your opponent "
                "spent last turn plus this turn.")

    def damage(self):
        # Badges only boost the first hit.
        self.hit(self.other_seat, 1)
        hurt(self.state, self.other_seat, 1)
        bonus = self.other.get('last_coins_spent', 0) + self.other.get('coins_spent', 0)
        hurt(self.state, self.other_seat, 1 + (bonus if self.modified else 0))

    def shield(self):
        count = int(self.level >= 1) + 2 * int(self.level >= 3)
        if count:
            self.gain_shields(count)

    def restriction(self):
        if self.timing >= 1 and self.opposing_type != DEFAULT:
            for card in self.other.cards[:9]:
                if card.type == self.opposing_type:
                    add_restriction(self.state, self.other_seat, 'Disabled', card.slot, 1, self.source())


class Shears(RPSCard):
    type, slot = SCISSORS, 5
    ability_order = ('damage', 'respec', 'badge')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('15L + 15', lambda: 15 * t.L + 15)} damage. When this levels down, 10 damage. "
                "T1: your opponent gains a badge that halves effective level.")

    @classmethod
    def describe_modifier(cls, t):
        return 'A random non-scissors ability of yours becomes scissors next turn.'

    def damage(self):
        self.hit(self.other_seat, 15 * self.level + 15)

    def respec(self):
        candidates = [card for card in self.player.cards[:9] if card.type != SCISSORS]
        if self.modified and candidates:
            card = choice(candidates)
            set_type(card, SCISSORS, until=self.state.meta.round + 1)
            self.state.meta.message.append(f'{self.seat}: {card.name} becomes scissors next turn')

    def badge(self):
        if self.timing >= 1:
            self.grant_badge('HalfLevel', None, self.other_seat)


class Asteroid(RPSCard):
    type, slot = ROCK, 6
    ability_order = ('coins', 'badge')

    @classmethod
    def describe(cls, t):
        return (f"Gain a {t.v('+20L', lambda: 20 * t.L)} damage badge. "
                f"${t.v('X', lambda: t.player.get('damage_since_win', 0))}, "
                "where X is the damage you have taken since you last won RPS.")

    @classmethod
    def describe_modifier(cls, t):
        return f"Your opponent loses ${t.v('X', lambda: t.player.get('damage_since_win', 0))}."

    def coins(self):
        amount = self.player.get('damage_since_win', 0)
        self.player.coins += amount
        if self.modified:
            self.other.coins = max(0, self.other.coins - amount)

    def badge(self):
        self.grant_badge('DmgBonus', 20 * self.level)


class Skywriting(RPSCard):
    type, slot = PAPER, 7
    ability_order = ('damage', 'health', 'restriction')

    @classmethod
    def describe(cls, t):
        def first_type():
            return TYPES[t.view.pattern.sequence[0]] if t.view.get('pattern') else None

        return (f"{t.v('11L%health', lambda: t.other.hp * 11 * t.L / 100)} damage. Next turn you cannot "
                f"select abilities matching {t.v('the first type in the pattern', first_type)}.")

    @classmethod
    def describe_modifier(cls, t):
        return f"{t.v('7L%health', lambda: t.player.hp * 7 * t.L / 100)} health."

    def damage(self):
        self.hit(self.other_seat, self.selection.health_before[self.other_seat] * 11 * self.level / 100)

    def health(self):
        if self.modified:
            heal(self.state, self.seat, self.selection.health_before[self.seat] * 7 * self.level / 100)

    def restriction(self):
        add_restriction(self.state, self.seat, 'TypeBlocked',
                        self.state.pattern.sequence[0], 1, self.source())


class Scissorstorm(RPSCard):
    type, slot = SCISSORS, 8
    ability_order = ('respec', 'damage')

    @classmethod
    def describe(cls, t):
        return (f"{t.v('20X', lambda: 20 * sum(c.level for c in t.player.cards[:9] if c.type == SCISSORS))} "
                "damage, where X is the sum of your scissors levels. Also does its level damage to each "
                "other ability in the opposing ability's tier.")

    @classmethod
    def describe_modifier(cls, t):
        def previous():
            card = t.last_selection()
            return 'none' if card is None else card.name

        return (f"First, {t.v('the ability you chose last turn', previous)} becomes scissors for 3 turns, "
                "counting this one.")

    def respec(self):
        previous = self.player.get('last_selection')
        if self.modified and previous:
            card = self.player.cards[previous['slot']]
            set_type(card, SCISSORS, until=self.state.meta.round + 2)
            self.state.meta.message.append(f'{self.seat}: {card.name} becomes scissors for 3 turns')

    def damage(self):
        self.hit(self.other_seat, 20 * self.total_level(SCISSORS, (self.seat,)))

    def level_damage(self):
        if not self.winning or self.opposing_slot is None:
            return
        amount = self.numeric_badges('level_damage', 1)
        targets = [self.opposing_slot]
        targets.extend(card.slot for card in self.other.cards[:9]
                       if card.slot != self.opposing_slot and card.slot // 3 == self.opposing_slot // 3)
        for slot in targets:
            level_damage(self.state, self.other_seat, slot, amount)


class Truce(RPSCard):
    slot = TRUCE
    ability_order = ('loss', 'coins')

    def loss(self):
        self.hit(self.seat, 1)

    def coins(self):
        self.player.coins += 1


class PaciveIncome(RPSCard):
    slot = INCOME
    ability_order = ('health', 'coins')

    def health(self):
        heal(self.state, self.seat, 2)

    def coins(self):
        self.player.coins += 2


CARD_CLASSES = {card.__name__: card for card in RPSCard.__subclasses__()}
CARD_CLASSES['Butterknife'] = ButterKnife
CARD_CLASSES['PassiveIncome'] = PaciveIncome

DECKS = {
    'basic': (Pebble, Napkin, ButterKnife, Boulder, Book, Wirecutter, Mountain, Contract, TwoHander),
    'advanced': (Nugget, LoveLetter, Dagger, Avalanche, Thesaurus, Shears, Asteroid, Skywriting, Scissorstorm),
}
