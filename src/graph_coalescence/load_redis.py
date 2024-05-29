import os
import sys
import redis

def get_redis(db):
    r = redis.Redis(host=os.environ.get('REDIS_HOST', 'localhost'), port=int(os.environ.get('REDIS_PORT',  6379)), db=db)
    return r

def write_to(fname,db):
    print(f'Processing {fname}')

    r = get_redis(db)
    pipe = r.pipeline()
    n=0
    batchsize = 10000
    with open(fname,'r') as inf:
        for line in inf:
            x = line.strip().split('\t')
            if len(x) == 1:
                x.append('')
            pipe.set(x[0],x[1])
            n += 1
            if n >= batchsize:
                print(f'Executing {fname}')
                pipe.execute()
                n = 0
    pipe.execute()
    print(n)

def go():
    import os
    thisdir = os.environ.get('DATA_DIR', os.path.dirname(os.path.realpath(__file__)))
    write_to(os.path.join(thisdir, 'links.txt'),0)
    write_to(os.path.join(thisdir, 'nodelabels.txt'),1)
    write_to(os.path.join(thisdir, 'backlinks.txt'),2)
    write_to(os.path.join(thisdir, 'nodenames.txt'),3)
    write_to(os.path.join(thisdir, 'prov.txt'),4)
    write_to(os.path.join(thisdir, 'category_count.txt'),5)

def go_test():
    #Is going to run from ac root
    write_to('tests/test_links.txt',0)
    write_to('tests/test_nodelabels.txt',1)
    write_to('tests/test_backlinks.txt',2)
    write_to('tests/test_nodenames.txt',3)
    write_to('tests/test_prov.txt',4)
    write_to('tests/category_count.txt',5) #the cat counts are the same for the test db

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        go_test()
    else:
        go()

