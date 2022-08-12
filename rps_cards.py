from tipr.models import Game
from tipr.utils import *

class Restriction(object):
    def __init__(self, arg, source, duration):
        self.arg = arg
        self.source = source
        self.duration = duration

    def json(self):
        return {'name': self.__class__.__name__,
                'arg': self.arg,
                'source': self.source,
                'duration': self.duration}

class Disabled(Restriction):
    def applies(self, gamestate, seat, move):
        if move.selection == self.arg:
            return True

class Badge(object):
    def __init__(self, seat, arg, round):
        self.seat = seat
        self.arg = arg
        self.round = round

    def json(self):
        return [self.__class__.__name__, self.arg, self.round]

class DmgMultiplier(Badge):
    types = 'damage'

    def apply(self, gamestate, delta):
        for seat in seats:
            if seat in delta:
                if 'hp' in delta.get(seat):
                    damage(delta, seat, self.arg, mul=True)
                    total = combine_numeric_modifiers(delta.get(seat).hp)
                    add_message(delta, f"{self.seat}: DmgMultiplier({self.arg}) applies to {seat}. {-total}")

class ScissorsDmgMultiplier(DmgMultiplier):

    def apply(self, gamestate, delta):
        selection = gamestate.get(self.seat).selection.slot
        sel_type = gamestate.get(self.seat).cards[selection].type
        if sel_type == SCISSORS:
            super(ScissorsDmgMultiplier, self).apply(gamestate, delta)
        else:
            add_message(delta, f"{self.seat}: ScissorsDmgMultiplier wasted on a {TYPES[sel_type]}!")

class DmgBonus(Badge):
    types = 'damage'

    def apply(self, gamestate, delta):
        for seat in seats:
            if seat in delta:
                if 'hp' in delta.get(seat):
                    damage(delta, seat, self.arg)
                    total = combine_numeric_modifiers(delta.get(seat).hp)
                    add_message(delta, f"{self.seat}: DmgBonus(+{self.arg}) applies to {seat}. {-total}")

class LvlBonus(Badge):
    types = 'level_up'

    def apply(self, gamestate, delta):
        for seat in seats:
            if seat in delta:
                for card in update(gamestate, delta).get(seat).cards:
                    if card.level > gamestate.get(seat).cards[card.slot].level:
                        card.level += 2
                        add_message(delta, f"{self.seat}: LvlBonus(+{self.arg}) applies to {seat}'s {card.name}.")

class Curse(Badge):
    types = 'start'

    def apply(self, gamestate, delta):
        damage(delta, self.seat, self.arg)
        total = combine_numeric_modifiers(delta.get(seat).hp)
        add_message(delta, f"{self.seat}: {self.__class__.__name__}({self.arg}) applies to {seat}. {-total}")

def generate_curses(type_):
    def apply(self, gamestate, delta):
        selection = gamestate.get(self.seat).selection.slot
        if TYPES[gamestate.get(self.seat).cards[selection].type] == type_:
            super(self.__class__, self).apply(gamestate, delta)
        else:
            add_message(delta, f"{self.seat}: {self.__class__.__name__} fades")
    name = f"{type_}Curse"
    globals()[name] = type(name, (Curse,), {'apply': apply})
[generate_curses(t) for t in TYPELIST]

effect_params = ['gamestate', 'history', 'seat', 'player', 'other', 'timing_bonus', 'level', 'badges_apply', 'delta']
class RPSCard(object):

    badge_multiplier = 1
    decks = ['basic']

    # called on every subclass
    def init(cls):
        # card stages count down; 0 means we're done and won't call apply again
        cls.abilities = update(Box({
            1: cls.level_up,
            2: cls.level_damage,
        }), {3+i:getattr(cls, x) for i, x in enumerate(reversed(cls.ability_order))})
        cls.abilities[len(cls.ability_order)+3] = cls.start

    @classmethod
    def get_badges(cls, seat, player, type, round):
        badges = map(lambda name, args, round: next(filter(lambda c: c.__name__ == name, descendants(Badge)))(seat, args, round), *mzip(*player.badges))
        return filter(lambda badge: type in badge.types and badge.round < round, badges)  # don't apply badges earned this round

    @classmethod
    def apply(cls, gamestate, history, seat):
        selection = gamestate.get(seat).selection
        ability_number = selection.ability_number
        timing_bonus = selection.timing
        player = gamestate.get(seat)
        level = player.cards[selection.slot].level
        other = gamestate.get(opp(seat))
        delta = update(empty_delta(), Box({seat: {'selection': {'ability_number': ability_number - 1}}}))
        badges_apply = gamestate.meta.outcome.type == 'win' and gamestate.meta.outcome.player == seat
        globals().update(locals())
        badge_tuple = cls.abilities[ability_number](cls)
        # one-type abilities can be named after their type instead of returning it
        badge_types = list(badge_tuple or (cls.abilities[ability_number].__name__,))

        badges_used = []
        for i in range(cls.badge_multiplier):
            if badges_apply:
                for badge_type in badge_types:
                    for badge in cls.get_badges(seat, player, badge_type, gamestate.meta.round):
                        if badge.apply(gamestate, delta) != 'skip':
                            badges_used.append(badge.json())
        if badges_used:
            # the same badge can apply to two abilities of one card, so a set avoids duplication
            delta.get(seat).badges_used = unluple(luple(gamestate.get(seat).badges_used) | luple(badges_used))

        if 'damage' in badge_types and other.shields.n > 0 and other.shields.n > other.shields.this_turn:
            delta.ga(opp(seat)).ga('shields').n = other.shields.n - 1
            add_message(delta, f"{opp(seat)}: Shield prevented {-combine_numeric_modifiers(delta.ga(opp(seat)).get('hp'))} dmg")
            update(delta, {opp(seat): {'hp': (('mul', 0),)}})

        # only use up badges after they've had a chance to apply to each stage
        if ability_number == 1:
            delta.ga(seat).badges = unluple(luple(gamestate.get(seat).badges.to_list()) -
                                            luple(gamestate.get(seat).badges_used.to_list()))
            delta.ga(seat).badges_used = []

        return delta

    def start(cls):
        return ('start',)

    def level_up(cls):
        if badges_apply:
            card = player.cards[player.selection.slot]
            card.level += 1
            card.cracked = False
            update(delta, {seat: {'cards': {'set': (card.slot, card)}}})
            add_message(delta, f'{seat}: {card.name} levels up')
            return ('level_up',)

    def level_damage(cls):
        if badges_apply:
            card = other.cards[other.selection.slot]

            if card.cracked:
                card.level=max(0, card.level - 1)
                card.cracked=False
                add_message(delta, f'{opp(seat)}: {card.name} levels down')
            else:
                card.cracked = True
                add_message(delta, f'{opp(seat)}: {card.name} cracks')
            update(delta, {opp(seat): {'cards': {'set': (card.slot, card)}}})
            return ('level_damage',)


# 1,2 timing bonuses, l level scaling, o other scaling
class Pebble(RPSCard):

    type = ROCK
    ability_order = ['damage', 'badge']
    slot = 0

    def damage(cls):
        dmg = 15
        explanation = ''
        if timing_bonus == 2:
            dmg += 3 * level
            explanation = f"15 + 3[l]({level})[/] = "
        damage(delta, opp(seat), dmg)
        add_message(delta, f"{seat}: Pebble hits! {explanation if explanation else ''}{dmg}")

    def badge(cls):
        if timing_bonus == 1:
            update(delta, {seat: {'badges': {'dins': ['DmgMultiplier', 2, gamestate.meta.round]}}})
            add_message(delta, f"{seat}: [1]Pebble grants DmgMultiplier(2x)[/1]")


class Napkin(RPSCard):

    type = PAPER
    ability_order = ['health', 'damage', 'shield']
    slot = 1

    def health(cls):
        damage(delta, seat, -level)
        add_message(delta, f"{seat}: Napkin heals! {level}")

    def damage(cls):
        other_ability = other.selection.slot
        other_level = other.cards[other_ability].level
        total = 4 * other_level
        damage(delta, opp(seat), total)
        add_message(delta, f"{seat}: [1]Napkin hits! 4[o]({other_level})[/o] = {total}[/1]")

    def shield(cls):
        if timing_bonus == 2:
            shields(delta, seat, 1)
            add_message(delta, f"{seat}: [2]Napkin grants a shield[/2]")


class ButterKnife(RPSCard):

    type = SCISSORS
    ability_order = ['damage', 'disable']
    slot = 2

    def damage(cls):
        dmg = 10 + 2 * level
        explanation = f" 10 + 2[l]({level})[/l]"
        if timing_bonus >= 1:
            dmg += 10
            dmg += 4 * level
            explanation += f" [1]+ 10 + 4[l]({level})[/l][/1]"
        damage(delta, opp(seat), dmg)
        add_message(delta, f"{seat}: ButterKnife hits! {explanation} = {dmg}")

    def disable(cls):
        duration = 1
        if timing_bonus == 2:
            duration = 2
        opposing_ability = other.selection.slot
        if opposing_ability not in [TRUCE, INCOME]:
            source = f"{seat}'s ButterKnife @ round {gamestate.meta.round}"
            rest = Disabled(opposing_ability, source, duration)
            update(delta, {opp(seat): {'restrictions': {'dins': rest.json()}}})
            opposing_name = other.cards[opposing_ability].name
            add_message(delta, f"{seat}: ButterKnife disables {opposing_name} for {'1 round' if duration == 1 else '[1]2[/1] rounds!'}")
        else:
            add_message(delta, f"{seat}: ButterKnife can't disable nothing!")


class Boulder(RPSCard):

    type = ROCK
    ability_order = ['badge']
    slot = 3

    def badge(cls):
        total = 5 + 5 * level
        explanation = f"5 + 5[l]({level})[/l]"
        update(delta, {seat: {'badges': {'dins': ['DmgBonus', total, gamestate.meta.round]}}})
        add_message(delta, f"{seat}: Boulder grants DmgBonus! {explanation} = {total}")
        if timing_bonus >= 1:
            update(delta, {seat: {'badges': {'dins': ['LvlBonus', 2, gamestate.meta.round]}}})
            add_message(delta, f"{seat}: [1]Boulder grants LvlBonus(2)![/1]")


class Book(RPSCard):

    type = PAPER
    ability_order = ['damage', 'respec', 'level']
    slot = 4

    def damage(cls):
        def type_levels(type, p):
            return [card.level for card in p.cards if card.type == type]
        book_type = player.cards[4].type
        ours = type_levels(book_type, player)
        theirs = type_levels(book_type, other)
        total = sum(ours) + sum(theirs)
        damage(delta, opp(seat), total)
        add_message(delta, f"{seat}: Book ({TYPES[book_type]}) hits! [l]{ours}[/l] + [L]{theirs}[/L] = {total}")

    def respec(cls):
        prev_frame = Game.intermediate_states(history, -2, last_only=True)
        card = player.cards[4]
        if not prev_frame or player.cards[prev_frame.info[seat].selection.slot].type == -1:
            card.type = PAPER
            add_message(delta, f"{seat}: Book reverts to paper, since no type was chosen last turn.")
        else:
            prev_card = player.cards[prev_frame.info[seat].selection.slot]
            prev_type = prev_card.type
            card.type = prev_type
            add_message(delta, f"{seat}: Book becomes {TYPES[prev_type]}, because {prev_card.name} was chosen last turn.")
        update(delta, {seat: {'cards': {'set': (4, card)}}})

    def level(cls):
        if timing_bonus >= 1:
            prev_frame = Game.intermediate_states(history, -2, last_only=True)
            if not prev_frame or player.cards[prev_frame.info[seat].selection.slot].type == -1:
                add_message(delta, f"{seat}: [1]Can't level up nothing![/1]")
                return
            prev_slot = prev_frame.info[seat].selection.slot
            card = player.cards[prev_slot]
            card.cracked = False
            card.level += 2
            update(delta, {seat: {'cards': {'set': (prev_slot, card)}}})
            add_message(delta, f"{seat}: [1]{card.name} levels up twice![/1] (Book)")

class Wirecutter(RPSCard):

    type = SCISSORS
    ability_order = ['damage', 'badge']
    slot = 5

    def damage(cls):
        levels = [card.level for card in player.cards if card.type == SCISSORS]
        total = sum(levels)
        damage(delta, opp(seat), total)
        add_message(delta, f"{seat}: Wirecutter hits! [l]{levels}[/l] = {total}")

    def badge(cls):
        if timing_bonus >= 1:
            update(delta, {seat: {'badges': {'dins': ['ScissorsDmgMultiplier', 3, gamestate.meta.round]}}})
            add_message(delta, f"{seat}: [1]Wirecutter grants ScissorsDmgMultiplier(3)![/1]")

class Mountain(RPSCard):

    type = ROCK
    ability_order = ['damage', 'crack']
    slot = 6
    badge_multiplier = 2

    def damage(cls):
        total = 15 + 2 * level
        damage(delta, opp(seat), total)
        add_message(delta, f"{seat}: Mountain hits! 15 + [l]{level} * 2[/l] = {total}")

    def crack(cls):
        other_type = other.cards[other.selection.slot].type
        cards_to_crack = [card for card in other.cards if card.type == other_type]
        for card in cards_to_crack:
            card.cracked = True
            update(delta, {opp(seat): {'cards': other.cards}})
        cards_to_crack = list(map(lambda card: card['name'], cards_to_crack))
        add_message(delta, f"{seat}: Mountain cracks all {opp(seat)} {TYPES[other_type]} cards! ({cards_to_crack})")

class Contract(RPSCard):

    type = PAPER
    ability_order = ['damage', 'shield', 'badge']
    slot = 7

    def damage(cls):
        dmg = 7
        damage(delta, opp(seat), dmg)
        add_message(delta, f"{seat}: Contract hits! 7")

    def shield(cls):
        shields(delta, seat, 1)
        add_message(delta, f"{seat}: Contract grants a shield")

    def badge(cls):
        other_type = other.cards[other.selection.slot].type
        if other_type < 0:
            add_message(delta, f"{seat}: Can't make a Contract with nothing!")
            return
        typename = TYPES[other_type]
        bonus = 5 * level
        total = 25 + bonus
        update(delta, {opp(seat): {'badges': {'dins': [f'{typename}Curse', total, gamestate.meta.round]}}})
        add_message(delta, f"{seat}: Contract grants {opp(seat)} {typename}Curse({total})")

class TwoHander(RPSCard):

    type = SCISSORS
    ability_order = ['damage', 'disable']
    slot = 8

    def damage(cls):
        dmg = 8 * level
        damage(delta, opp(seat), dmg)
        add_message(delta, f"{seat}: TwoHander hits! 8[l]({level})[/l] = {dmg}")

    def disable(cls):
        if other.cards[other.selection.slot].cracked:
            source = f"{seat}'s TwoHander @ round {gamestate.meta.round}"
            for i in range(9):
                rest = Disabled(i, source, 1)
                update(delta, {opp(seat): {'restrictions': {'dins': rest.json()}}})
            rest = Disabled(8, source, 3)
            update(delta, {seat: {'restrictions': {'dins': rest.json()}}})
            add_message(delta, f"{seat}: TwoHander disables everything for 1 round! TwoHander is disabled for 3 rounds.")
        else:
            add_message(delta, f"{seat}: TwoHander does not sense weakness!")


class Truce(RPSCard):

    type = DEFAULT
    ability_order = ['loss']
    slot = 9

    def loss(cls):
        damage(delta, seat, 1)


class PaciveIncome(RPSCard):

    type = DEFAULT
    ability_order = ['health']
    slot = 10

    def health(cls):
        damage(delta, seat, -2)

for cls in RPSCard.__subclasses__():
    RPSCard.init(cls)