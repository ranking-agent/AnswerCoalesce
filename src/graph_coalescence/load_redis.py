import redis

def get_redis(db):
    r = redis.Redis(host='localhost', port=6379, db=db)
    return r

def write_to(fname,db):
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
                pipe.execute()
                n = 0
    pipe.execute()

def go():
    write_to('links.txt',0)
    write_to('nodelabels.txt',1)

if __name__ == '__main__':
    go()

