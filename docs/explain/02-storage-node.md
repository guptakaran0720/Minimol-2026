# 02 · Storage node: chunk store and peer API

**One line:** Every node stores encrypted chunks on disk under their hash, enforces a disk quota, and serves them over an HTTP API where every request and every answer is signed with the cluster key.

**Analogy:** A left-luggage office. Each bag is filed under its fingerprint, so the clerk can check you handed in the bag you said you did. The office has a fixed number of shelves. Only people with the club badge can use the counter, and the clerk stamps every receipt so you know it came from the real clerk.

## How it works

1. **Content-addressed store.** A chunk lives at `chunks/<first 2 hex chars>/<chunk_id>` ([chunkstore.py:53](../../node/chunkstore.py#L53)). On every `put`, the store checks that `sha256(blob) == chunk_id` and raises `HashMismatch` if not ([chunkstore.py:59](../../node/chunkstore.py#L59)). A chunk that is already stored returns "not new" without writing ([chunkstore.py:62](../../node/chunkstore.py#L62)), which makes PUT idempotent.
2. **Atomic writes.** Data goes to a temp file, is flushed and `fsync`ed, and is then renamed into place with `os.replace` ([chunkstore.py:25](../../node/chunkstore.py#L25)). A crash can leave a temp file, never a half-written chunk under a valid ID. Leftover temp files are deleted on startup ([chunkstore.py:44](../../node/chunkstore.py#L44)).
3. **Quota.** The store keeps a running total of bytes used. A write that would go over `QUOTA_MB` raises `QuotaExceeded` ([chunkstore.py:64](../../node/chunkstore.py#L64)), which the API turns into `507` ([api_peer.py:153](../../node/api_peer.py#L153)). The check and the write happen under one lock.
4. **Peer API** ([api_peer.py](../../node/api_peer.py)):

   | Route | Answer |
   |---|---|
   | `GET /health` | node_id, host_id, addr, weight, free/used bytes, chunk count, uptime ([line 127](../../node/api_peer.py#L127)) |
   | `GET /peers` | known non-dead peers, for gossip ([line 140](../../node/api_peer.py#L140)) |
   | `PUT /chunks/{id}` | 201 new, 200 already present, 400 hash mismatch, 413 too big, 507 quota full ([line 145](../../node/api_peer.py#L145)) |
   | `GET /chunks/{id}` / `HEAD /chunks/{id}` | bytes or 404 / 200 or 404 |
   | `GET /inventory` | every chunk ID held here ([line 169](../../node/api_peer.py#L169)) |
   | `PUT /index/{owner_pub}` | 201; 401 bad signature; 409 version not newer ([line 173](../../node/api_peer.py#L173)) |
   | `GET /index/{owner_pub}` | the stored signed record, or 404 |

   There is **no DELETE route.** Bodies are capped *while they stream in*: chunks at 1 MiB + 64 B, index records at 1 MiB ([read_capped at api_peer.py:71](../../node/api_peer.py#L71), [config.py:27](../../node/config.py#L27)).
5. **Request signing.** Every peer request carries `X-Node`, `X-Ts`, `X-Sig`, where `X-Sig = HMAC-SHA256(cluster_key, method|path|node_id|ts|sha256(body))` ([auth.py:23](../../node/auth.py#L23)). The server accepts it only within ±30 s of `X-Ts` and compares in constant time ([auth.py:34](../../node/auth.py#L34)). Because `node_id` is inside the signature, a captured request can't be replayed under another node's name.
6. **Response signing.** Middleware signs every answer to an authenticated request: `X-Resp-Sig = HMAC(cluster_key, RESPONSE|status|request X-Sig|node_id|sha256(body))`, with the responder in `X-Node` ([api_peer.py:38](../../node/api_peer.py#L38), [auth.py:53](../../node/auth.py#L53)). The client rejects unsigned answers, bad signatures, and answers from a different node than the one it called ([peer_client.py:40](../../node/peer_client.py#L40)). Binding the request's signature means an old answer can't be replayed as the answer to a new question.

**`SIMULATED_DELAY_MS`.** After a request passes auth, the node sleeps for this many milliseconds before answering ([api_peer.py:114](../../node/api_peer.py#L114), read in [config.py:88](../../node/config.py#L88)). It applies to every authenticated peer request, including `/health`, so heartbeats and transfers both see the slow node. We use it for the routing demo and always say on stage that the delay is simulated.

## Why this design

**Decision:** cluster-wide HMAC on requests *and* responses, quotas, body caps, no remote delete. See [ARCHITECTURE_DECISIONS.md §12](../ARCHITECTURE_DECISIONS.md#12-security-cluster-hmac-quotas-no-remote-delete).

- **Strongest counter:** one leaked laptop exposes the shared key for the whole cluster.
- **Our defense:** true, and per-node identities with mutual TLS are the better design (planned). But the data is encrypted on the client, so even a full cluster member only ever sees ciphertext. And without the HMAC, anyone on the Wi-Fi could fill disks or answer `HEAD` with a fake "I have it".

**Decision:** atomic temp-file-then-rename writes with `fsync`.

- **Counter:** fsync on every chunk is slow.
- **Defense:** Wi-Fi is the bottleneck, not the disk, and a half-written chunk under a valid ID would be silent corruption. The hash check on read would catch it, but it's cheaper never to create it.

## Evidence

- [tests/test_chunkstore.py](../../tests/test_chunkstore.py): `test_put_get_has`, [`test_hash_mismatch_rejected`](../../tests/test_chunkstore.py#L26), `test_bad_id_rejected`, [`test_quota`](../../tests/test_chunkstore.py#L41), [`test_survives_restart_and_cleans_tmp`](../../tests/test_chunkstore.py#L49), `test_index_store_keeps_highest_version`.
- [tests/test_api_peer.py](../../tests/test_api_peer.py): `test_chunk_round_trip`, [`test_status_codes`](../../tests/test_api_peer.py#L67) (201/200/400/413/507), [`test_hmac_rejection`](../../tests/test_api_peer.py#L85), `test_wrong_cluster_key_client_raises`, [`test_simulated_delay`](../../tests/test_api_peer.py#L137), [`test_unsigned_or_impostor_responses_rejected`](../../tests/test_api_peer.py#L161), [`test_replayed_response_rejected`](../../tests/test_api_peer.py#L183).
- [tests/test_auth.py](../../tests/test_auth.py): `test_round_trip`, `test_any_change_rejected` (any change to method, path, node, timestamp or body fails), `test_timestamp_window`, `test_response_signature`.
- Measured in the Docker cluster (4 containers on one laptop, 5 reps): 20 MB CSV stored across 3 copies came to **0.905×** the original size; 5 MB random data came to **3.0×**. Caveat: one machine, so this proves correctness, not Wi-Fi performance.

## Limits

- One shared cluster key, no per-node identity. Mutual TLS is (planned).
- Traffic is HTTP, not TLS. Payloads are ciphertext, but headers and sizes are visible.
- A replay inside the 30 s window is possible. It only affects idempotent requests (re-PUT the same chunk, re-read ciphertext).
- The store doesn't re-hash a chunk when serving it; the reader re-hashes every blob it receives, so a corrupt copy is detected and skipped. Rot is also found proactively: a background scrub re-hashes 8 stored chunks per second (`node/scrub.py`) and quarantines any that fail, and repair restores them.
- The directory entry isn't fsynced after rename, so a power cut right after a write could lose that one chunk (the hash check still prevents corruption).
- `/health` free space is the node's own claim. A lying node can only cause failed PUTs, which move on to the next peer.

## Judge questions

**Q: What stops someone on the venue Wi-Fi from writing junk to my disk?**
A: Every peer request must carry an HMAC signed with the cluster key, checked within ±30 s, or it gets a 401. Even a valid member is limited by the quota (507) and by body caps (413), and there is no delete route.
*Follow-up:* "What if they replay a captured upload?" → Inside 30 s it just re-stores the same chunk, which is already there. The PUT is idempotent.

**Q: Why sign responses too?**
A: Without it, a stranger could answer `/health` as a fake peer and receive chunks, or answer `HEAD` with a fake "I have it" and stop repair. The response signature covers the status, the body hash and the request's own signature, so it can't be forged or replayed.
*Follow-up:* "Does the 401 get signed?" → No, and the client treats any 401 as an error, so an unsigned 401 can't trick it into anything.

**Q: How do you know a chunk wasn't corrupted on disk?**
A: Its name is its SHA-256, and the downloader re-hashes every blob it receives before using it, then the GCM tag is checked too. A bad copy is skipped and that peer is penalised, and the next holder is tried.
*Follow-up:* "Do you find corruption before someone reads it?" → Yes. The background scrub re-hashes every stored chunk, quarantines a bad one within its pass, and repair copies a good one back (16–20 s measured on 4 local nodes).
