import chess
import chess.polyglot
import copy
from log import l

# (C) 2017 by folkert@vanheusden.com
# released under AGPL v3.0

tt = []
tt_size = 0
tt_sub_size = 8
tt_age = 0

class tt_element(object):
    __slots__ = [ 'hash_', 'score', 'flags', 'depth', 'age', 'move' ]

    def __init__(self, hash_, score, flags, depth, age, move):
        self.hash_ = hash_
        self.score = score
        self.flags = flags
        self.depth = depth
        self.age = age
        self.move = move

def tt_init(size):
    global tt_size, tt_sub_size, tt

    l('Set TT size to %d entries ' % size)
    tt_size = size

    dummy_move = chess.Move(0, 0)

    tt = [[tt_element(None, None, None, -1, -1, None) for i in xrange(tt_sub_size)] for i in xrange(tt_size)]

def tt_inc_age():
    global tt_age

    tt_age += 1

def tt_calc_slot(h):
    global tt_size

    return h % tt_size

def tt_store(board, alpha, beta, score, move, depth, h):
    global tt_sub_size, tt, tt_age

    if score <= alpha:
        flags = 'U'
    elif score >= beta:
        flags = 'L'
    else:
        flags = 'E'

    idx = tt_calc_slot(h)

    use_ss = None

    use_ss2 = None
    min_depth = 99999

    for i in xrange(0, tt_sub_size):
        if tt[idx][i].hash_ == h:
            if tt[idx][i].depth > depth:
                return

            if flags != 'E' and tt[idx][i].depth == depth:
                return

            use_ss = i
            break

        if tt[idx][i].age != tt_age:
            use_ss = i
        elif tt[idx][i].depth < min_depth:
            min_depth = tt[idx][i].depth
            use_ss2 = i

    if not use_ss:
        use_ss = use_ss2

    tt[idx][use_ss] = tt_element(h, score, flags, depth, tt_age, move)

def tt_lookup(board, h):
    global tt_sub_size, tt

    idx = tt_calc_slot(h)

    for i in xrange(0, tt_sub_size):
        if tt[idx][i].hash_ == h:
            if tt[idx][i].move == None or tt[idx][i].move in board.get_move_list(h):
                return tt[idx][i]

    return None

def tt_get_pv(board, first_move):
    pv = first_move.uci()

    board.push(first_move)
    n = 1

    hist = set()

    while True:
        h = chess.polyglot.zobrist_hash(board)

        hit = tt_lookup(board, h)
        if not hit or not hit.move:
            break

        if hit.move in hist:
            break

        pv += ' ' + hit.move.uci()

        board.push(hit.move)
        hist.add(hit.move)

        n += 1

    for r in xrange(0, n):
        board.pop()

    return pv
