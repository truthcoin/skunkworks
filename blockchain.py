""" This file explains explains the rules for adding and removing blocks from the local chain.
"""
import time
import copy
import custom
import tools
import networking
import transactions
import sys

default_entry={'count': 0, 'amount': 0, 'votecoin':{}, 'votes':{}, 'shares':{}}

def db_get(n, DB):
    n = str(n)
    try:
        return tools.unpackage(DB['db'].Get(n))
    except:
        db_put(n, default_entry, DB)
        return db_get(n, DB)
def db_put(key, dic, DB): return DB['db'].Put(str(key), tools.package(dic))
def db_delete(key, DB): return DB['db'].Delete(str(key))
def db_existence(key, DB):
    n=str(key)
    try:
        a=tools.unpackage(DB['db'].Get(n))
        return not a==default_entry
    except:
        return False
def count(address, DB):
    # Returns the number of transactions that pubkey has broadcast.
    def zeroth_confirmation_txs(address, DB):
        def is_zero_conf(t):
            other_address=tools.make_address(t['pubkeys'], len(t['signatures']))
            return address == other_address
        return len(filter(is_zero_conf, DB['txs']))
    current = db_get(address, DB)['count']
    zeroth=zeroth_confirmation_txs(address, DB)
    return current+zeroth
def add_tx(tx, DB):
    # Attempt to add a new transaction into the pool.
    out=['']
    if type(tx) != type({'a':1}): 
        return False
    address = tools.make_address(tx['pubkeys'], len(tx['signatures']))
    def verify_count(tx, txs):
        return tx['count'] != count(address, DB)
    def type_check(tx, txs):
        if not tools.E_check(tx, 'type', [str, unicode]):
            out[0]+='blockchain type'
            return False
        if tx['type'] == 'mint':
            return False
        if tx['type'] not in transactions.tx_check:
            out[0]+='bad type'
            return False
        return True
    def too_big_block(tx, txs):
        return len(tools.package(txs+[tx])) > networking.MAX_MESSAGE_SIZE - 5000
    def verify_tx(tx, txs, out):
        if not type_check(tx, txs):
            out[0]+='type error'
            return False
        if tx in txs:
            out[0]+='no duplicates'
            return False
        if verify_count(tx, txs):
            out[0]+='count error'
            return False
        if too_big_block(tx, txs):
            out[0]+='too many txs'
            return False
        if not transactions.tx_check[tx['type']](tx, txs, DB):
            out[0]+='update transactions.py to find out why. print statements are no good. ' +str(tx)
            return False
        return True
    if verify_tx(tx, DB['txs'], out):
        DB['txs'].append(tx)
        return('added tx: ' +str(tx))
    else:
        return('failed to add tx because: '+out[0])
targets = {}
times = {}  # Stores blocktimes
def recent_blockthings(key, DB, size, length=0):
    # Grabs info from old blocks.
    if key == 'time':
        storage = times
    if key == 'target':
        storage = targets
    def get_val(length):
        leng = str(length)
        if not leng in storage:
            storage[leng] = db_get(leng, DB)[key]
        return storage[leng]
    if length == 0:
        length = DB['length']
    start = (length-size) if (length-size) >= 0 else 0
    return map(get_val, range(start, length))
def hexSum(a, b):
    # Sum of numbers expressed as hexidecimal strings
    return tools.buffer_(str(hex(int(a, 16)+int(b, 16)))[2: -1], 64)
def hexInvert(n):
    # Use double-size for division, to reduce information leakage.
    return tools.buffer_(str(hex(int('f' * 128, 16) / int(n, 16)))[2: -1], 64)
def target(DB, length=0):
    """ Returns the target difficulty at a paticular blocklength. """
    if length == 0:
        length = DB['length']
    if length < 4:
        return '0' * 4 + 'f' * 60  # Use same difficulty for first few blocks.
    if length <= DB['length'] and str(length) in targets:
        return targets[str(length)]  # Memoized, This is a small memory leak. It takes up more space linearly over time. but every time you restart the program, it gets cleaned out.
    def targetTimesFloat(target, number):
        a = int(str(target), 16)
        b = int(a * number)
        return tools.buffer_(str(hex(b))[2: -1], 64)
    def weights(length):
        return [custom.inflection ** (length-i) for i in range(length)]
    def estimate_target(DB):
        """
        We are actually interested in the average number of hashes required to
        mine a block. number of hashes required is inversely proportional
        to target. So we average over inverse-targets, and inverse the final
        answer. """
        def sumTargets(l):
            if len(l) < 1:
                return 0
            while len(l) > 1:
                l = [hexSum(l[0], l[1])] + l[2:]
            return l[0]
        targets = recent_blockthings('target', DB, custom.history_length)
        w = weights(len(targets))
        tw = sum(w)
        targets = map(hexInvert, targets)
        def weighted_multiply(i):
            return targetTimesFloat(targets[i], w[i]/tw)
        weighted_targets = [weighted_multiply(i) for i in range(len(targets))]
        return hexInvert(sumTargets(weighted_targets))
    def estimate_time(DB):
        times = recent_blockthings('time', DB, custom.history_length)
        blocklengths = [times[i] - times[i - 1] for i in range(1, len(times))]
        w = weights(len(blocklengths))  # Geometric weighting
        tw = sum(w)  # Normalization constant
        return sum([w[i] * blocklengths[i] / tw for i in range(len(blocklengths))])
    retarget = estimate_time(DB) / custom.blocktime(length)
    return targetTimesFloat(estimate_target(DB), retarget)


def add_block(block_pair, DB):
    """Attempts adding a new block to the blockchain.
     Median is good for weeding out liars, so long as the liars don't have 51%
     hashpower. """
    def median(mylist):
        if len(mylist) < 1:
            return 0
        return sorted(mylist)[len(mylist) / 2]

    def block_check(block, DB):
        def tx_check(txs):
            start = copy.deepcopy(txs)
            out = []
            start_copy = []
            while start != start_copy:
                if start == []:
                    return False  # Block passes this test
                start_copy = copy.deepcopy(start)
                if transactions.tx_check[start[-1]['type']](start[-1], out, DB):
                    out.append(start.pop())
                else:
                    return True  # Block is invalid
            return True  # Block is invalid
        if not isinstance(block, dict):
            return False
        if 'error' in block:
            return False
        if 'length' not in block:
            return False
        length = DB['length']
        if int(block['length']) != int(length) + 1:
            return False
        if block['diffLength'] != hexSum(DB['diffLength'],
                                         hexInvert(block['target'])):
            return False
        if length >= 0:
            if tools.det_hash(db_get(length, DB)) != block['prevHash']:
                return False
        a = copy.deepcopy(block)
        a.pop('nonce')
        if u'target' not in block.keys():
            return False
        half_way = {u'nonce': block['nonce'], u'halfHash': tools.det_hash(a)}
        if tools.det_hash(half_way) > block['target']:
            return False
        if block['target'] != target(DB, block['length']):
            return False
        earliest = median(recent_blockthings('time', DB, custom.mmm))
        if 'time' not in block:
            return False
        if block['time'] > time.time():
            return False
        if block['time'] < earliest:
            return False
        if tx_check(block['txs']):
            return False
        return True
    if type(block_pair)==type([1,2,3]):
        block=block_pair[0]
        peer=block_pair[1]
    else:
        block=block_pair
        peer=False
    #tools.log('attempt to add block: ' +str(block))
    if block_check(block, DB):
        #tools.log('add_block: ' + str(block))
        i=0
        if peer != False:
            for p in DB['peers_ranked']:
                if p[0]==peer:
                    j=i
                i+=1
            DB['peers_ranked'][j][1]*=0.1#listen more to people who have newer blocks.
        db_put(block['length'], block, DB)
        DB['length'] = block['length']
        DB['diffLength'] = block['diffLength']
        orphans = copy.deepcopy(DB['txs'])
        DB['txs'] = []
        for tx in block['txs']:
            DB['add_block']=True
            transactions.update[tx['type']](tx, DB)
        for tx in orphans:
            add_tx(tx, DB)


def delete_block(DB):
    """ Removes the most recent block from the blockchain. """
    if DB['length'] < 0:
        return
    try:
        targets.pop(str(DB['length']))
    except:
        pass
    try:
        times.pop(str(DB['length']))
    except:
        pass
    block = db_get(DB['length'], DB)
    orphans = copy.deepcopy(DB['txs'])
    DB['txs'] = []
    for tx in block['txs']:
        orphans.append(tx)
        DB['add_block']=False
        transactions.update[tx['type']](tx, DB)
    db_delete(DB['length'], DB)
    DB['length'] -= 1
    if DB['length'] == -1:
        DB['diffLength'] = '0'
    else:
        block = db_get(DB['length'], DB)
        DB['diffLength'] = block['diffLength']
    for orphan in sorted(orphans, key=lambda x: x['count']):
        add_tx(orphan, DB)
def suggestions(DB, s, f):
    while True:
        DB['heart_queue'].put(s)
        time.sleep(1)
        #tools.log('size: ' +str(DB[s].qsize()))
        if not DB[s].empty():
            #tools.log('got thing: ' +str(s))
            try:
                f(DB[s].get(False), DB)
            except:
                tools.log('suggestions ' + s + ' '+str(sys.exc_info()))
def suggestion_txs(DB): 
    return suggestions(DB, 'suggested_txs', add_tx)
def suggestion_blocks(DB): 
    return suggestions(DB, 'suggested_blocks', add_block)

