#! /usr/bin/python

# (C) 2017 by folkert@vanheusden.com
# released under AGPL v3.0

from board import Board, init_board_ht
import chess
import chess.pgn
import math
import Queue
from select import select
import sys
import threading
import time
import traceback
from tt import tt_init
from brain import calc_move, cm_thread_start, cm_thread_check, cm_thread_stop, random_move
from log import set_l, l

tt_n_elements = 1024 * 8
ponder = False
benchmark = False
epd = False

class stdin_reader(threading.Thread, object):
    __slots__ = [ 'q' ]

    q = Queue.Queue()

    def run(self):
        l('stdin thread started')

        while True:
            line = sys.stdin.readline()

            self.q.put(line)

        l('stdin thread terminating')

    def get(self, to = None):
        try:
            if not to:
                return self.q.get()

            return self.q.get(True, to)

        except Queue.Empty as qe:
            return None

def perft(board, depth):
    if depth == 1:
        return board.legal_moves.count()

    total = 0

    for m in board.legal_moves:
        board.push(m)
        total += perft(board, depth - 1)
        board.pop()

    return total

def send(str_):
    print str_
    l('OUT: %s' % str_)
    sys.stdout.flush()

def main():
    try:
        sr = stdin_reader()
        sr.daemon = True
        sr.start()

        tt_init(tt_n_elements)

        board = Board()

        while True:
            line = sr.get()
            if line == None:
                break

            line = line.rstrip('\n')

            if len(line) == 0:
                continue

            l('IN: %s' % line)

            parts = line.split(' ')
            
            if parts[0] == 'uci':
                send('id name Feeks')
                send('id author Folkert van Heusden <mail@vanheusden.com>')
                send('uciok')

            elif parts[0] == 'isready':
                send('readyok')

            elif parts[0] == 'ucinewgame':
                board = Board()
                cm_thread_stop()

            elif parts[0] == 'auto':
                cm_thread_stop()

                tt = 1000
                n_rnd = 4
                if len(parts) == 2:
                    tt = float(parts[1])

                ab = Board()
                while not ab.is_checkmate():
                    if n_rnd > 0:
                        h = chess.polyglot.zobrist_hash(ab)
                        m = random_move(ab, h)
                        n_rnd -= 1

                    else:
                        m = calc_move(ab, tt, 999999)
                        m = m[1]

                    if m == None:
                        break

                    ab.push(m)
                    print m

                print 'done'

            elif parts[0] == 'perft':
                cm_thread_stop()

                depth = 4
                if len(parts) == 2:
                    depth = int(parts[1])

                start = time.time()
                total = 0

                for m in board.legal_moves:
                    board.push(m)
                    cnt = perft(board, depth - 1)
                    board.pop()

                    print '%s: %d' % (m.uci(), cnt)

                    total += cnt

                print '==========================='
                took = time.time() - start
                print 'Total time (ms) : %d' % math.ceil(took * 1000.0)
                print 'Nodes searched  : %d' % total
                print 'Nodes/second    : %d' % math.floor(total / took)

            elif parts[0] == 'position':
                is_moves = False
                nr = 1
                while nr < len(parts):
                    if is_moves:
                        board.push_uci(parts[nr])

                    elif parts[nr] ==  'fen':
                        board = Board(' '.join(parts[nr + 1:]))
                        break

                    elif parts[nr] == 'startpos':
                        board = Board()

                    elif parts[nr] == 'moves':
                        is_moves = True

                    else:
                        l('unknown: %s' % parts[nr])

                    nr += 1

            elif parts[0] == 'go':
                cm_thread_stop()

                movetime = None
                depth = None
                wtime = btime = None
                winc = binc = 0
                movestogo = None

                nr = 1
                while nr < len(parts):
                    if parts[nr] == 'wtime':
                        wtime = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'btime':
                        btime = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'winc':
                        winc = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'binc':
                        binc = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'movetime':
                        movetime = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'movestogo':
                        movestogo = int(parts[nr + 1])
                        nr += 1

                    elif parts[nr] == 'depth':
                        depth = int(parts[nr + 1])
                        nr += 1

                    else:
                        l('unknown: %s' % parts[nr])

                    nr += 1

###
                current_duration = movetime

                if current_duration:
                    current_duration = float(current_duration) / 1000.0

                elif wtime and btime:
                    ms = wtime
                    time_inc = winc
                    if not board.turn:
                        ms = btime
                        time_inc = binc

                    ms /= 1000.0
                    time_inc /= 1000.0

                    if movestogo == None:
                        movestogo = 40 - board.fullmove_number
                        while movestogo < 0:
                            movestogo += 40

                    current_duration = (ms + movestogo * time_inc) / (board.fullmove_number + 7);

                    limit_duration = ms / 15.0
                    if current_duration > limit_duration:
                        current_duration = limit_duration

                    if current_duration == 0:
                        current_duration = 0.001

                    l('mtg %d, ms %f, ti %f' % (movestogo, ms, time_inc))
###
                if current_duration:
                    l('search for %f seconds' % current_duration)

                if depth == None:
                    depth = 999

                cm_thread_start(board, current_duration, depth)

                line = None
                while cm_thread_check():
                    line = sr.get(0.01)

                    if line:
                        line = line.rstrip('\n')

                        if line == 'stop' or line == 'quit':
                            break

                result = cm_thread_stop()

                if line == 'quit':
                    break

                if result and result[1]:
                    send('bestmove %s' % result[1].uci())
                    board.push(result[1])

                else:
                    send('bestmove a1a1')

                if ponder:
                    cm_thread_start(board.copy())

            elif parts[0] == 'quit':
                break

            else:
                l('unknown: %s' % parts[0])

            sys.stdout.flush()

        cm_thread_stop()

    except KeyboardInterrupt as ki:
        l('ctrl+c pressed')
        cm_thread_stop()

    except Exception as ex:
        l(str(ex))
        l(traceback.format_exc())

def benchmark_test():
    tt_init(tt_n_elements)
    board = Board()
    calc_move(board, 60.0, 999999)

def epd_test(str_):
    parts = str_.split(';')
    board = chess.Board(parts[0])

    print parts[0]

    for test in parts:
        test = test.strip()

        if test[0] != 'D':
            continue

        pparts = test.split(' ')

        depth = int(pparts[0][1:])

        count = int(pparts[1])

        verify = perft(board, depth)

        print '\t', depth, verify, count,
        if verify == count:
            print 'ok'
        else:
            print 'FAIL!'
            sys.exit(1)

if len(sys.argv) == 2:
    set_l(sys.argv[1])

init_board_ht()

if benchmark:
    import cProfile
    cProfile.run('benchmark_test()', 'restats')
elif epd:
    while True:
        line = sys.stdin.readline()
        if not line:
            break

        if len(line) == 0 or line[0] == '#':
            continue

        epd_test(line)
else:
    main()
