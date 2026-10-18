"""Computer players for RPS."""

from collections import Counter
from copy import deepcopy
import random

from .computer_players import ComputerPlayer
from .utils import Box, seats


def beats(ability_type):
    return (ability_type + 1) % 3


def round_types(history, seat):
    """(this seat's type, opponent's type) for each finished round; None where nothing was picked."""
    other = 'p2' if seat == 'p1' else 'p1'
    rounds = []
    blessed = [interval for interval in history if 'rewound' not in interval[0]]
    for interval in blessed[1:]:
        info = interval[0]['info']
        mine, theirs = info[seat].get('last_selection'), info[other].get('last_selection')
        rounds.append((mine and mine['type'], theirs and theirs['type']))
    return rounds


def _most_common(types):
    if not types:
        return None
    counts = Counter(types)
    best = max(counts.values())
    return next(t for t in reversed(types) if counts[t] == best)


def frequency(rounds):
    return _most_common([theirs for _, theirs in rounds if theirs is not None])


def markov(rounds, order):
    played = [theirs for _, theirs in rounds if theirs is not None]
    if len(played) <= order:
        return None
    context = played[-order:]
    followers = [played[i + order] for i in range(len(played) - order)
                 if played[i:i + order] == context]
    return _most_common(followers)


def beat_my_last(rounds):
    mine = [own for own, _ in rounds if own is not None]
    return beats(mine[-1]) if mine else None


def repeat_last(rounds):
    played = [theirs for _, theirs in rounds if theirs is not None]
    return played[-1] if played else None


PREDICTORS = (
    frequency,
    lambda rounds: markov(rounds, 1),
    lambda rounds: markov(rounds, 2),
    beat_my_last,
    repeat_last,
)


def predict(rounds):
    """Guess the opponent's next type with whichever predictor would have done best so far."""
    if all(theirs is None for _, theirs in rounds):
        return None
    scores = [0] * len(PREDICTORS)
    for i, (_, theirs) in enumerate(rounds):
        if theirs is None:
            continue
        for index, predictor in enumerate(PREDICTORS):
            if predictor(rounds[:i]) == theirs:
                scores[index] += 1
    guesses = [(score, -index, predictor(rounds))
               for index, (score, predictor) in enumerate(zip(scores, PREDICTORS))]
    opinions = [guess for guess in guesses if guess[2] is not None]
    return max(opinions)[2] if opinions else None


class RandomBot(ComputerPlayer):
    """Picks a random ability, adding its modifier a quarter of the time. Never uses coins."""

    name = 'RandomBot'
    modifier_chance = .25

    def wanted(self, view, history, seat):
        return list(range(9))

    def moves(self, rules, view, history, seat_index):
        seat = seats[seat_index]
        stage = view.meta.stage
        if stage not in (1, 2, 3) or rules.stage_complete(view, seat):
            return []
        now, later = self.options(rules, view, seat, self.wanted(view, history, seat))
        if not now and not later:
            now, later = self.options(rules, view, seat, range(9))
        # Each stage takes its share of the options still to come, so the overall pick is uniform.
        if not now or random.random() >= len(now) / (len(now) + len(later)):
            return [{'type': 'pass'}]
        slot = random.choice(now)
        modifier = {'type': 'modifier', 'selection': slot}
        moves = [{'type': 'selection', 'selection': slot}]
        if random.random() < self.modifier_chance and rules.move_error(view, seat, modifier) is None:
            moves.insert(0, modifier)
        return moves

    @staticmethod
    def options(rules, view, seat, slots):
        def selectable(state, slot):
            return rules.move_error(state, seat, {'type': 'selection', 'selection': slot}) is None

        stage = view.meta.stage
        now = [slot for slot in slots if selectable(view, slot)]
        later = set()
        for future_stage in range(stage + 1, 4):
            future = Box(deepcopy(view))
            future.meta.stage = future_stage
            later.update(slot for slot in slots if slot not in now and selectable(future, slot))
        return now, sorted(later)


class EnsembleBot(RandomBot):
    """Like RandomBot, but only picks abilities that beat its prediction of the opponent's type."""

    name = 'EnsembleBot'

    def wanted(self, view, history, seat):
        prediction = predict(round_types(history, seat))
        if prediction is None:
            return list(range(9))
        return [card.slot for card in view[seat].cards[:9] if card.type == beats(prediction)]
