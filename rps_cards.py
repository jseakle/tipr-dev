from copy import deepcopy
from math import floor
from random import choice

from .utils import (
    Box, DEFAULT, INCOME, PAPER, ROCK, SCISSORS, TRUCE, TYPES,
    gen_patch, opp, seats,
)


COIN_ABILITIES = {
    'Suppress': {'tier': 1, 'cost': 10,
                 'text': 'Your opponent cannot select tier three abilities this round. Not usable in stage three.'},
    'Premonition': {'tier': 2, 'cost': 2,
                   'text': 'Reveal a selectable ability not chosen in an earlier stage. Twice per stage.'},
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


class RPSCard:
    type = DEFAULT
    slot = -1
    text = ''
    modifier = None
    badge_multiplier = 1
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
        self.state.meta.message.append(f"{target}: gains {name}({arg})")

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
        self.consume_badges()


class Pebble(RPSCard):
    type, slot = ROCK, 0
    ability_order = ('damage', 'badge')
    text = '5 + L damage. T1: gain a 2x damage badge. T2: +3L damage.'

    def damage(self):
        self.hit(self.other_seat, 5 + self.level + (3 * self.level if self.timing >= 2 else 0))

    def badge(self):
        if self.timing >= 1:
            self.grant_badge('DmgMultiplier', 2)


class Napkin(RPSCard):
    type, slot = PAPER, 1
    ability_order = ('health', 'damage', 'shield')
    text = '2L health. T1: +4X damage, where X is opposing level. T2: gain a shield.'

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
    text = ('10 + 2L damage. Disable opposing ability for 1 turn. '
            'T1: disable another random opposing ability for 1 turn. T2: +10 + 2L damage.')

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
    text = 'Gain a +25+5L damage badge. T1: gain a +2 level badge.'

    def badge(self):
        self.grant_badge('DmgBonus', 25 + 5 * self.level)
        if self.timing >= 1:
            self.grant_badge('LvlBonus', 2)


class Book(RPSCard):
    type, slot = PAPER, 4
    ability_order = ('damage', 'respec', 'previous_level')
    text = ('1+7X damage, where X is the total level of all abilities sharing this type. '
            'Become the type you selected last turn, or paper. That previous ability levels up. '
            'T1: the previous ability levels up two more times.')

    def damage(self):
        self.hit(self.other_seat, 1 + 7 * self.total_level(self.selection.chosen_type, seats))

    def respec(self):
        previous = self.player.get('last_selection')
        self.card.type = previous['type'] if previous else PAPER

    def previous_level(self):
        previous = self.player.get('last_selection')
        if previous:
            level_up(self.state, self.seat, previous['slot'], 1 + (2 if self.timing >= 1 else 0))


class Wirecutter(RPSCard):
    type, slot = SCISSORS, 5
    ability_order = ('damage', 'badge', 'respec')
    text = ('X damage, where X is the sum of your scissors levels. Gain a scissors-only 3x damage badge. '
            'T1: a random non-scissors ability of yours becomes scissors.')

    def damage(self):
        self.hit(self.other_seat, self.total_level(SCISSORS, (self.seat,)))

    def badge(self):
        self.grant_badge('ScissorsDmgMultiplier', 3)

    def respec(self):
        if self.timing >= 1:
            candidates = [card for card in self.player.cards[:9] if card.type != SCISSORS]
            if candidates:
                card = choice(candidates)
                card.type = SCISSORS
                self.state.meta.message.append(f'{self.seat}: {card.name} becomes scissors')
            else:
                self.state.meta.message.append(f'{self.seat}: all RPS abilities are already scissors')


class Mountain(RPSCard):
    type, slot = ROCK, 6
    badge_multiplier = 2
    ability_order = ('damage', 'crack')
    text = '15 + 10L damage. Crack all opposing abilities. Badges apply twice.'

    def damage(self):
        self.hit(self.other_seat, 15 + 10 * self.level)

    def crack(self):
        for card in self.other.cards[:9]:
            card.cracked = True


class Contract(RPSCard):
    type, slot = PAPER, 7
    ability_order = ('damage', 'shield', 'badge')
    text = ('7 damage. Gain a shield. Your opponent gains an end badge: '
            'if this is the opposing type, take 20 + 10L damage.')

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
    text = ('5 damage at level zero, otherwise 50 damage. If the opposing ability is cracked, disable all opposing '
            'abilities for one turn and this ability for three turns.')

    def damage(self):
        self.hit(self.other_seat, 5 if self.level == 0 else 50)

    def restriction(self):
        if self.opposing_slot is not None and self.other.cards[self.opposing_slot].cracked:
            for slot in range(9):
                add_restriction(self.state, self.other_seat, 'Disabled', slot, 1, self.source())
            add_restriction(self.state, self.seat, 'Disabled', self.card.slot, 3, self.source())


class Nugget(RPSCard):
    type, slot = ROCK, 0
    ability_order = ('damage', 'coins', 'badge')
    modifier = 'Triple coins.'
    text = '10 damage. $1+L/2. T1: +L damage, $3. T2: gain a +2 level damage badge.'

    def damage(self):
        self.hit(self.other_seat, 10 + (self.level if self.timing >= 1 else 0))

    def coins(self):
        amount = 1 + self.level / 2 + (3 if self.timing >= 1 else 0)
        self.player.coins += amount * (3 if self.modified else 1)

    def badge(self):
        if self.timing >= 2:
            self.grant_badge('LvlDamageBonus', 2)


class LoveLetter(RPSCard):
    type, slot = PAPER, 1
    ability_order = ('health', 'damage')
    modifier = 'Double health.'
    text = ('5 damage. L health. T1: +%health damage equal to your health% minus '
            "your opponent's health%. T2: double health before T1.")

    def health(self):
        amount = self.level * (2 if self.modified else 1) * (2 if self.timing >= 2 else 1)
        heal(self.state, self.seat, amount)

    def damage(self):
        amount = 5
        if self.timing >= 1:
            difference = health_percent(self.player) - health_percent(self.other)
            amount += self.selection.health_before[self.other_seat] * difference / 100
        self.hit(self.other_seat, amount)


class Dagger(RPSCard):
    type, slot = SCISSORS, 2
    ability_order = ('damage', 'coins', 'restriction')
    modifier = '+2L damage.'
    text = ('15 + 3L damage. If this advances your indicator, $2. '
            "T1: your opponent cannot act in the same stage next turn. T2: double damage.")

    def damage(self):
        amount = 15 + 3 * self.level + (2 * self.level if self.modified else 0)
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
    ability_order = ('damage', 'coins', 'levels')
    modifier = 'Your opponent loses $L.'
    text = '4+L damage. $4+L. T1: all your rock abilities level up.'

    def damage(self):
        self.hit(self.other_seat, 4 + self.level)

    def coins(self):
        self.player.coins += 4 + self.level
        if self.modified:
            self.other.coins = max(0, self.other.coins - self.level)

    def levels(self):
        if self.timing >= 1:
            for card in self.player.cards[:9]:
                if card.type == ROCK:
                    level_up(self.state, self.seat, card.slot)


class Thesaurus(RPSCard):
    type, slot = PAPER, 4
    ability_order = ('damage', 'shield', 'restriction')
    modifier = 'Your opponent loses all shields before damage.'
    text = ('1 damage. Gain a shield at level 1+, and two more at level 5+. '
            'T1: +X damage, where X is opposing coins spent this turn; disable the opposing ability for one turn.')

    def damage(self):
        if self.modified:
            self.other.shields.n = 0
            self.other.shields.this_turn = 0
        self.hit(self.other_seat, 1 + (self.other.get('coins_spent', 0) if self.timing >= 1 else 0))

    def shield(self):
        count = int(self.level >= 1) + 2 * int(self.level >= 5)
        if count:
            self.gain_shields(count)

    def restriction(self):
        if self.timing >= 1:
            self.disable_opponent(1)


class Shears(RPSCard):
    type, slot = SCISSORS, 5
    ability_order = ('damage', 'restriction', 'badge')
    modifier = 'Your opponent cannot spend coins next turn.'
    text = ('5+5L damage. When this levels down, 10 damage. '
            'T1: your opponent gains a badge that halves effective level.')

    def damage(self):
        self.hit(self.other_seat, 5 + 5 * self.level)

    def restriction(self):
        if self.modified:
            add_restriction(self.state, self.other_seat, 'CoinLocked', None, 1, self.source())

    def badge(self):
        if self.timing >= 1:
            self.grant_badge('HalfLevel', None, self.other_seat)


class Asteroid(RPSCard):
    type, slot = ROCK, 6
    ability_order = ('opposing_damage', 'self_damage', 'coins', 'badge')
    modifier = 'Steal $X instead.'
    text = ('4+L damage to both players, opponent first. $X, where X is damage you '
            'took last turn. Gain a +L damage badge.')

    def opposing_damage(self):
        self.hit(self.other_seat, 4 + self.level)

    def self_damage(self):
        self.hit(self.seat, 4 + self.level)

    def coins(self):
        amount = self.player.get('last_damage', 0)
        if self.modified:
            amount = min(amount, self.other.coins)
            self.other.coins -= amount
        self.player.coins += amount

    def badge(self):
        self.grant_badge('DmgBonus', self.level)


class Skywriting(RPSCard):
    type, slot = PAPER, 7
    ability_order = ('damage', 'health', 'restriction')
    modifier = '5L%health health.'
    text = ('10L%health damage. Next turn you cannot select abilities matching '
            'the first type in the pattern.')

    def damage(self):
        self.hit(self.other_seat, self.selection.health_before[self.other_seat] * self.level / 10)

    def health(self):
        if self.modified:
            heal(self.state, self.seat, self.selection.health_before[self.seat] * self.level / 20)

    def restriction(self):
        add_restriction(self.state, self.seat, 'TypeBlocked',
                        self.state.pattern.sequence[0], 1, self.source())


class Scissorstorm(RPSCard):
    type, slot = SCISSORS, 8
    ability_order = ('damage',)
    modifier = 'Also apply the losing ability\'s level damage to other opposing abilities of its type.'
    text = '7+2L damage. Apply the losing ability\'s level damage to all opposing abilities in its tier.'

    def damage(self):
        self.hit(self.other_seat, 7 + 2 * self.level)

    def level_damage(self):
        if not self.winning or self.opposing_slot is None:
            return
        amount = self.numeric_badges('level_damage', 1)
        targets = [self.opposing_slot]
        targets.extend(card.slot for card in self.other.cards[:9]
                       if card.slot != self.opposing_slot
                       and card.slot // 3 == self.opposing_slot // 3)
        if self.modified:
            targets.extend(card.slot for card in self.other.cards[:9]
                           if card.slot not in targets and card.type == self.opposing_type)
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
