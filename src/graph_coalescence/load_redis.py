import sys
import redis

def get_redis(db):
    r = redis.Redis(host='localhost', port=6379, db=db)
    return r

def write_to(fname,db):
    print(f'Processing {fname}')

    r = get_redis(db)
    pipe = r.pipeline()
    n=0
    batchsize = 100000
    with open(fname,'r') as inf:
        for line in inf:
            x = line.strip().split('\t')
            pipe.set(x[0],x[1])
            n += 1
            if n >= batchsize:
                print(f'Executing {fname}')
                pipe.execute()
                n = 0
    pipe.execute()

def go():
    write_to('links.txt',0)
    write_to('nodelabels.txt',1)
    write_to('backlinks.txt',2)

def go_test():
    #Is going to run from ac root
    write_to('tests/test_links.txt',0)
    write_to('tests/test_nodelabels.txt',1)
    write_to('tests/test_backlinks.txt',2)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        go_test()
    else:
        go()

