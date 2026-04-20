# Verifying the answer-coalesce.rdb

The `.rdb` file is too large to load on the ht1 login node.
Always run verification on a largemem compute node.

## Steps

### 1. Request a largemem compute node
```bash
srun --partition=largemem --mem=240G --cpus-per-task=4 --time=02:00:00 --pty bash
```

### 2. Set Redis paths
```bash
REDIS_SERVER=$(which redis-server)
REDIS_CLI=$(which redis-cli)
```

### 3. Start Redis pointing at the .rdb
```bash
$REDIS_SERVER \
    --port 6380 \
    --dbfilename answer-coalesce.rdb \
    --dir /projects/stars/var/answer_coalesce/YYYY-MM-DD \
    --daemonize yes
```

### 4. Wait for loading to complete
```bash
$REDIS_CLI -p 6380 info persistence | grep loading
```
Wait until `loading:0` before proceeding. For a 42GB file expect around 10 minutes.

### 5. Check key counts across all databases
```bash
$REDIS_CLI -p 6380 info keyspace
```

Expected output for a valid `.rdb`:

| DB | File | Expected Keys |
|---|---|---|
| db0 | links.txt | ~4.8M |
| db1 | nodelabels.txt | ~4.8M |
| db2 | backlinks.txt | ~166M |
| db3 | nodenames.txt | ~4.8M |
| db4 | prov.txt | ~137M |
| db5 | category_count.txt | ~50 |

### 6. Sample a key to verify content
```bash
# Get a random key from db0 (links)
$REDIS_CLI -p 6380 -n 0 randomkey

# Get its value
$REDIS_CLI -p 6380 -n 0 get <key>
```

### 7. Shutdown Redis when done
```bash
$REDIS_CLI -p 6380 shutdown nosave
```

## Notes
- Always use `shutdown nosave` when verifying — you do not want to
  overwrite the `.rdb` with an incomplete save
- Do not run redis-server on the ht1 login node — it will be killed
  by the OS due to memory limits
- The largemem nodes (largemem-5-[1-2], largemem-6-[1-2]) are the
  only nodes with sufficient RAM to load the full dataset
- Activate your conda environment before running `which redis-server`
  to ensure the correct Redis binary is found