#! /usr/bin/python

# (C) 2017 by folkert@vanheusden.com
# released under AGPL v3.0

import chess
import chess.pgn
import collections
from psq import psq, psq_individual
from tt import tt_inc_age, tt_store, tt_lookup, tt_get_pv
from log import l
from operator import itemgetter
import math
import sys
import threading
import time
import traceback

stats_node_count = 0
stats_tt_checks = stats_tt_hits = 0
stats_avg_bco_index_cnt = stats_avg_bco_index = 0

infinite = 131072
checkmate = 10000

material_table = {
	'P' : 100, 'p' : 100,
	'N' : 325, 'n' : 325,
	'B' : 325, 'b' : 325,
	'R' : 500, 'r' : 500,
	'Q' : 975, 'q' : 975,
	'K' : 10000, 'k' : 10000
	}

pmaterial_table = {
	chess.PAWN : 100,
	chess.KNIGHT : 325,
	chess.BISHOP : 325,
	chess.ROOK : 500,
	chess.QUEEN : 975,
	chess.KING : 10000
	}

to_flag = None

def set_to_flag(to_flag):
	to_flag.set()
	l("time is up");

def get_stats():
	global stats_avg_bco_index, stats_node_count, stats_tt_hits, stats_tt_checks

	return { 'stats_node_count' : stats_node_count,
		'stats_tt_hits' : stats_tt_hits,
		'stats_tt_checks' : stats_tt_checks,
		'stats_avg_bco_index_cnt' : stats_avg_bco_index_cnt,
		'stats_avg_bco_index' : stats_avg_bco_index }

def reset_stats():
	global stats_avg_bco_index_cnt, stats_avg_bco_index, stats_node_count, stats_tt_hits, stats_tt_checks

	stats_avg_bco_index_cnt = stats_avg_bco_index = stats_node_count = stats_tt_checks = stats_tt_hits = 0

def verify_board(what, board):
    m1 = board.get_move_list()

    from board import Board
    b2 = Board(board.fen())
    m2 = b2._get_move_list()

    if collections.Counter(m1) != collections.Counter(m2):
        print 'FAIL ', title, board.fen()
        print m1
        print m2
        sys.exit(1)

def material(pm):
	score = 0

	for p in pm:
		piece = pm[p]

		if piece.color: # white
			score += pmaterial_table[piece.piece_type]
		else:
			score -= pmaterial_table[piece.piece_type]

	return score

def mobility(board):
        if board.turn:
                white_n = board.move_count()

                board.push(chess.Move.null())
                black_n = board.move_count()
                board.pop()

        else:
                black_n = board.move_count()

                board.push(chess.Move.null())
                white_n = board.move_count()
                board.pop()

        return white_n - black_n

def pm_to_filemap(piece_map):
	files = [[[0 for k in xrange(8)] for j in xrange(7)] for i in xrange(2)]

	for p in piece_map:
		piece = piece_map[p]

		files[piece.color][piece.piece_type][p & 7] += 1

	return files

def count_double_pawns(file_map):
	n = 0

	for i in xrange(0, 8):
		if file_map[chess.WHITE][chess.PAWN][i] >= 2:
			n += file_map[chess.WHITE][chess.PAWN][i] - 1

		if file_map[chess.BLACK][chess.PAWN][i] >= 2:
			n -= file_map[chess.BLACK][chess.PAWN][i] - 1

	return n

def count_rooks_on_open_file(file_map):
	n = 0

	for i in xrange(0, 8):
		if file_map[chess.WHITE][chess.PAWN][i] == 0 and file_map[chess.WHITE][chess.ROOK][i] > 0:
			n += 1

		if file_map[chess.BLACK][chess.PAWN][i] == 0 and file_map[chess.BLACK][chess.ROOK][i] > 0:
			n -= 1

	return n

def evaluate(board):
	pm = board.piece_map()

	score = material(pm)

	score += psq(pm) / 4

	score += mobility(board) * 10

	pfm = pm_to_filemap(pm)

	score += count_double_pawns(pfm)

	score += count_rooks_on_open_file(pfm)

	if board.turn:
	    return score

	return -score

def pc_to_list(board, moves_first):
	out = []

	for m in board.get_move_list():
		score = 0

		if m.promotion:
			score += pmaterial_table[m.promotion] << 18

		victim_type = board.piece_type_at(m.to_square)
		if victim_type:
			score += pmaterial_table[victim_type] << 18


		#	me = board.piece_at(m.from_square)
		#	score += (material_table['Q'] - material_table[me.symbol()]) << 8

		# -20 elo: 
		#else:
		#	me = board.piece_at(m.from_square)
		#	score += psq_individual(m.to_square, me) - psq_individual(m.from_square, me)

		record = { 'score' : score, 'move' : m }

		out.append(record)

	for i in xrange(0, len(moves_first)):
		for m in out:
			if m['move'] == moves_first[i]:
				m['score'] = infinite - i

	return sorted(out, key=itemgetter('score'), reverse = True) 

def blind(board, m):
	victim_type = board.piece_type_at(m.to_square)
	victim_eval = pmaterial_table[victim_type]

	me_type = board.piece_type_at(m.from_square)
	me_eval = pmaterial_table[me_type]

	return victim_eval < me_eval and board.attackers(not board.turn, m.to_square)

def is_draw(board):
	if board.halfmove_clock >= 100:
		return True

	# FIXME enough material counts

	return False

def qs(board, alpha, beta):
	global to_flag
	if to_flag.is_set():
		return -infinite

	global stats_node_count
	stats_node_count += 1

	if board.is_checkmate():
		return -checkmate

	if is_draw(board):
		return 0

	best = -infinite

	is_check = board.is_check()
	if not is_check:
		best = evaluate(board)

		if best > alpha:
			alpha = best

			if best >= beta:
				return best

	moves = pc_to_list(board, [])

	move_count = 0
	for m_work in moves:
		m = m_work['move']

		is_capture_move = board.piece_type_at(m.to_square) != None

                if is_check == False:
                    if is_capture_move == False and m.promotion == None:
                        continue

                    if is_capture_move and blind(board, m):
			continue

		move_count += 1

		board.push(m)

		score = -qs(board, -beta, -alpha)

		board.pop()

                #verify_board('qs %s' % m, board)

		if score > best:
			best = score

			if score > alpha:
				alpha = score

				if score >= beta:
					global stats_avg_bco_index, stats_avg_bco_index_cnt
					stats_avg_bco_index += move_count - 1
					stats_avg_bco_index_cnt += 1
					break

	if move_count == 0:
		if is_check: # stale mate
		    return 0

		return evaluate(board)

	return best

def tt_lookup_helper(board, alpha, beta, depth):
	tt_hit = tt_lookup(board)
	if not tt_hit:
		return None

	rc = (tt_hit['score'], tt_hit['move'])

	if tt_hit['depth'] < depth:
		return [ False, rc ]

	if tt_hit['flags'] == 'E':
		return [ True, rc ]

	if tt_hit['flags'] == 'L' and tt_hit['score'] >= beta:
		return [ True, rc ]

	if tt_hit['flags'] == 'U' and tt_hit['score'] <= alpha:
		return [ True, rc ]

	return [ False, rc ]

def search(board, alpha, beta, depth, siblings, max_depth, is_nm):
	global to_flag
	if to_flag.is_set():
		return (-infinite, None)

	if board.is_checkmate():
		return (-checkmate, None)

	if is_draw(board):
		return (0, None)

	if depth == 0:
	    return (qs(board, alpha, beta), None)

	top_of_tree = depth == max_depth

	global stats_node_count
	stats_node_count += 1

	global stats_tt_checks
	stats_tt_checks += 1
	tt_hit = tt_lookup_helper(board, alpha, beta, depth)
	if tt_hit:
		global stats_tt_hits
		stats_tt_hits += 1

		if tt_hit[0]:
			return tt_hit[1]

	alpha_orig = alpha

	best = -infinite
	best_move = None

	### NULL MOVE ###
	if not board.is_check() and depth >= 3 and not top_of_tree and not is_nm:
		board.push(chess.Move.null())
		nm_result = search(board, -beta, -beta + 1, depth - 3, [], max_depth, True)
		board.pop()

		if -nm_result[0] >= beta:
			return (-nm_result[0], None)
	#################

	moves_first = []
	if tt_hit and tt_hit[1][1]:
		moves_first.append(tt_hit[1][1])

	moves_first += siblings

	moves = pc_to_list(board, moves_first)

	new_siblings = []

	move_count = 0
	for m_work in moves:
		m = m_work['move']
		move_count += 1

		new_depth = depth - 1

		if depth >= 3 and move_count >= 4:
			new_depth -= 1

			if move_count >= 6:
				new_depth -= 1

		board.push(m)

		result = search(board, -beta, -alpha, new_depth, new_siblings, max_depth, False)
		score = -result[0]

		board.pop()

                #verify_board('search %s' % m, board)

		if score > best:
			best = score
			best_move = m

			if not m in siblings:
				if len(siblings) == 2:
					del siblings[-1]

				siblings.insert(0, m)

			if score > alpha:
				alpha = score

				if score >= beta:
					global stats_avg_bco_index, stats_avg_bco_index_cnt
					stats_avg_bco_index += move_count - 1
					stats_avg_bco_index_cnt += 1
					break

	if move_count == 0:
		is_check = board.is_check()

		if not is_check:
			return (0, None)

		l('ERR')

	if alpha > alpha_orig and not to_flag.is_set():
		tt_store(board, alpha_orig, beta, best, best_move, depth)

	return (best, best_move)

def calc_move(board, max_think_time, max_depth):
	global to_flag
	to_flag = threading.Event()
	to_flag.clear()

	t = None
	if max_think_time:
		t = threading.Timer(max_think_time, set_to_flag, args=[to_flag])
		t.start()

	reset_stats()
	tt_inc_age()

	l(board.fen())

	if board.move_count() == 1:
		l('only 1 move possible')

		for m in board.get_move_list():
			break

		return [ 0, m, 0, 0.0 ]

	result = None
	alpha = -infinite
	beta = infinite

	siblings = []
	start_ts = time.time()
	for d in xrange(1, max_depth + 1):
		cur_result = search(board, alpha, beta, d, siblings, d, False)

		diff_ts = time.time() - start_ts

		if to_flag.is_set():
			if result:
				result[3] = diff_ts
			break

		stats = get_stats()

		if cur_result[1]:
			diff_ts_ms = math.ceil(diff_ts * 1000.0)

			pv = tt_get_pv(board, cur_result[1])
			msg = 'depth %d score cp %d time %d nodes %d pv %s' % (d, cur_result[0], diff_ts_ms, stats['stats_node_count'], pv)

			print 'info %s' % msg
			sys.stdout.flush()

			l(msg)

		result = [cur_result[0], cur_result[1], d, diff_ts]

		if max_think_time and diff_ts > max_think_time / 2.0:
			break

		if cur_result[0] <= alpha:
			alpha = -infinite
		elif cur_result[0] >= beta:
			beta = infinite
		else:
			alpha = cur_result[0] - 50
			if alpha < -infinite:
				alpha = -infinite

			beta = cur_result[0] + 50
			if beta > infinite:
				beta = infinite

		#l('a: %d, b: %d' % (alpha, beta))

	if t:
		t.cancel()

	l('valid moves: %s' % board.get_move_list())

	if result == None or result[1] == None:
		l('random move!')
		l(board.get_stats())

		result = [ 0, random_move(board), 0, time.time() - start_ts ]

	l('selected move: %s' % result)

	diff_ts = time.time() - start_ts

	stats = get_stats()

	avg_bco = -1
	if stats['stats_avg_bco_index_cnt']:
		avg_bco = float(stats['stats_avg_bco_index']) / stats['stats_avg_bco_index_cnt']

	if stats['stats_tt_checks'] and diff_ts > 0:
		l('nps: %f, nodes: %d, tt_hits: %f%%, avg bco index: %.2f' % (stats['stats_node_count'] / diff_ts, stats['stats_node_count'], stats['stats_tt_hits'] * 100.0 / stats['stats_tt_checks'], avg_bco))

	return result

def calc_move_wrapper(board, duration, depth):
        global thread_result

	try:
		thread_result = calc_move(board, duration, depth)

        except Exception as ex:
                l(str(ex))
                l(traceback.format_exc())

		thread_result = None

import random
def random_move(board):
	moves = board.get_move_list()
	idx = random.randint(0, len(moves) - 1)
	l('n moves: %d, chosen: %d = %s' % (len(moves), idx, moves[idx]))
	if not board.is_legal(moves[idx]):
		l('FAIL')
	return moves[idx]

thread = None
thread_result = None

def cm_thread_start(board,duration=None,depth=999999):
        global thread
        thread = threading.Thread(target=calc_move_wrapper, args=(board,duration,depth,))
        thread.start()

def cm_thread_check():
        global thread
        if thread:
                thread.join(0.05)

		return thread.is_alive()

	return False

def cm_thread_stop():
        global to_flag
        if to_flag:
                set_to_flag(to_flag)

        global thread
        if thread:
                thread.join()
		del thread
		thread = None

        global thread_result
        return thread_result
