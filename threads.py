"""This program starts all the threads going. When it hears a kill signal, it kills all the threads and packs up the database.
"""
import ht, miner, peer_recieve, time, threading, tools, custom, networking, sys, truthcoin_api, blockchain, peers_check, multiprocessing, Queue
#import leveldb
import ht

def main(brainwallet):
    print('starting truthcoin')
    heart_queue=multiprocessing.Queue()
    suggested_blocks=multiprocessing.Queue()
    #db = leveldb.LevelDB(custom.database_name)
    DB = {#'targets':{},
          #'times':{},
          #'db': db,
        'txs': [],
        'reward_peers_queue':multiprocessing.Queue(),
        'suggested_blocks': suggested_blocks,
        'suggested_txs': multiprocessing.Queue(),
        'heart_queue': heart_queue,
        'memoized_votes':{},
        #'peers_ranked':[],
        'diffLength': '0'}
    tools.db_put('peers_ranked', [])
    tools.db_put('targets', {})
    tools.db_put('times', {})
    tools.db_put('stop', False)
    tools.db_put('mine', False)
    DB['privkey']=tools.det_hash(brainwallet)
    DB['pubkey']=tools.privtopub(DB['privkey'])
    DB['address']=tools.make_address([DB['pubkey']], 1)
    def len_f(i, DB):
        if not tools.db_existence(str(i), DB): return i-1
        return len_f(i+1, DB)
    DB['length']=len_f(0, DB)
    DB['diffLength']='0'
    if DB['length']>-1:
        '''
        {'target': blockchain.suggestion_txs,
         'args': (DB,),
         'daemon': True},
        {'target': blockchain.suggestion_blocks,
         'args': (DB,),
         'daemon': True},
        '''
        #print('thing: ' +str(tools.db_get(str(DB['length']), DB)))
        DB['diffLength']=tools.db_get(str(DB['length']), DB)['diffLength']
    worker_tasks = [
        #all these workers share memory DB
        #if any one gets blocked, then they are all blocked.
        {'target': truthcoin_api.main,
         'args': (DB, heart_queue),
         'daemon':True},
        {'target': blockchain.main,
         'args': (DB,),
         'daemon': True},
        {'target': miner.main,
         'args': (DB['pubkey'], DB),
         'daemon': False},
        {'target': peers_check.main,
         'args': (custom.peers, DB),
         'daemon': True},
        {'target': networking.serve_forever,
         'args': (custom.port, lambda d: peer_recieve.main(d, DB), heart_queue, DB),
         'daemon': True}
    ]
    processes= [#this thread does NOT share memory with the rest.
        {'target':tools.heart_monitor,
         'args':(heart_queue, )}
    ]
    cmds=[]
    for process in processes:
        cmd=multiprocessing.Process(target=process['target'], args=process['args'])
        cmd.start()
        cmds.append(cmd)
    def start_worker_proc(**kwargs):
        daemon=kwargs.pop('daemon', True)
        proc = threading.Thread(**kwargs)
        proc.daemon = daemon
        proc.start()
        return proc
    workers = [start_worker_proc(**task_info) for task_info in worker_tasks]
    while not tools.db_get('stop'):
        time.sleep(0.5)
    tools.log('about to stop threads')
    DB['heart_queue'].put('stop')
    for worker in workers:
        tools.log('stopped a thread')
        worker.join()
    for cmd in cmds:
        tools.log('stopped a thread')
        cmd.join()
    #del DB['db']
    tools.log('all threads stopped')
    sys.exit(1)

